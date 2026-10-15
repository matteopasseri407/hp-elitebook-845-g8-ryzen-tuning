# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared stdlib-only helpers for the EliteBook thermal profile stack.

The dispatcher, the idle watcher and the Steam watcher all read the same
sysfs trees (power supplies, hwmon sensors, cpufreq policy), locate RyzenAdj
the same way and serialize through the same dispatcher lock. Those helpers
used to be copied in each script and already diverged once during the
bash-to-Python migration, so they live here now.

Rules for this module:

- standard library only, no new runtime dependencies (it runs as root from
  systemd/udev),
- pure functions with explicit paths: never read the environment, so unit
  tests can load the callers with different fixture directories without
  module-reload tricks,
- never exit and never print: report failures through return values or
  exceptions and let the caller decide the message and exit code.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import time
import typing
from pathlib import Path

_UINT_RE = re.compile(r"^[0-9]+$")
_LOCKDOWN_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
_TEMPERATURE_SENSORS = ("k10temp", "zenpower")
_ACTIVE_GPU_MODE_RE = re.compile(r"^\s*\d+\s+([A-Z0-9_]+)\s*\*", re.MULTILINE)


def read_trimmed(path: Path) -> str:
    """Read a sysfs/proc file, dropping NUL bytes and edge whitespace."""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data.replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()


def is_uint(value: str | None) -> bool:
    return bool(value) and _UINT_RE.match(value or "") is not None


def read_key_value_file(path: Path) -> dict[str, str]:
    """Parse a KEY=value state file; the first occurrence of a key wins."""
    state: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return state
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            if key not in state:
                state[key] = value
    return state


def on_ac_power(power_supply_dir: Path, *, default_when_unknown: bool = False) -> bool:
    """True when a mains supply reports online.

    A present ``AC/online`` file decides alone (the historical behaviour);
    otherwise the first ``Mains`` supply decides. When nothing answers,
    ``default_when_unknown`` applies: the dispatcher treats that as battery,
    the Steam watcher as AC.
    """
    ac_online = power_supply_dir / "AC" / "online"
    try:
        if ac_online.exists():
            return read_trimmed(ac_online) == "1"
    except OSError:
        pass
    try:
        supplies = sorted(power_supply_dir.glob("*"))
    except OSError:
        return default_when_unknown
    for supply in supplies:
        if read_trimmed(supply / "type") != "Mains":
            continue
        return read_trimmed(supply / "online") == "1"
    return default_when_unknown


def battery_device(power_supply_dir: Path) -> Path | None:
    try:
        supplies = sorted(power_supply_dir.glob("*"))
    except OSError:
        return None
    for supply in supplies:
        try:
            if read_trimmed(supply / "type") == "Battery":
                return supply
        except OSError:
            continue
    return None


def battery_capacity(power_supply_dir: Path) -> int | None:
    """Battery percentage, or None when no battery answers."""
    supply = battery_device(power_supply_dir)
    if supply is None:
        return None
    raw = read_trimmed(supply / "capacity")
    if not is_uint(raw):
        return None
    return int(raw)


def _micro(supply: Path, name: str) -> int | None:
    raw = read_trimmed(supply / name)
    return int(raw) if is_uint(raw) else None


def battery_status(supply: Path) -> str:
    """``Discharging``, ``Charging``, ``Full``, ``Not charging`` or empty."""
    return read_trimmed(supply / "status")


def battery_power_w(supply: Path) -> float | None:
    """What the battery delivers right now, in watts.

    Firmware reports either ``power_now`` (microwatts) or ``current_now``
    (microamps) with ``voltage_now`` (microvolts); HP machines differ by
    model. While charging the value is the charge rate, not the draw.
    """
    power = _micro(supply, "power_now")
    if power is not None:
        return power / 1e6
    current = _micro(supply, "current_now")
    voltage = _micro(supply, "voltage_now")
    if current is None or voltage is None:
        return None
    return current * voltage / 1e12


def battery_energy_wh(supply: Path, name: str = "energy_now") -> float | None:
    """Battery energy in watt-hours: ``energy_now`` by default, or another
    ``energy_*`` attribute such as ``energy_full``. Firmware that reports
    ``charge_*`` in microamp-hours instead is converted at the design voltage.
    """
    energy = _micro(supply, name)
    if energy is not None:
        return energy / 1e6
    charge = _micro(supply, name.replace("energy", "charge", 1))
    voltage = _micro(supply, "voltage_min_design") or _micro(supply, "voltage_now")
    if charge is None or voltage is None:
        return None
    return charge * voltage / 1e12


def _choice(path: Path) -> str:
    """The selected entry of a sysfs choice list such as ``a [b] c``."""
    raw = read_trimmed(path)
    match = re.search(r"\[([^\]]+)\]", raw)
    return match.group(1) if match else raw


def _count_power_control(devices: list[Path]) -> str:
    counts: dict[str, int] = {}
    for device in devices:
        value = read_trimmed(device / "power" / "control")
        if value:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return ""
    return ", ".join(f"{count} {value}" for value, count in sorted(counts.items()))


def _glob(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted(base.glob(pattern))
    except OSError:
        return []


def power_inventory(sysfs: Path, cmdline: Path) -> list[tuple[str, str, str]]:
    """Every power knob this machine exposes, as (group, name, value).

    Read only. Empty values mean the knob does not exist here, which is an
    answer too: it says what a profile could and could not change on this
    machine. ``sysfs`` is normally /sys and ``cmdline`` /proc/cmdline.
    """
    rows: list[tuple[str, str, str]] = []

    def add(group: str, name: str, value: str) -> None:
        rows.append((group, name, value))

    supplies = sysfs / "class" / "power_supply"
    if _glob(supplies, "*"):
        add("power", "source", "AC" if on_ac_power(supplies) else "battery")
    else:
        add("power", "source", "")

    cpu = sysfs / "devices" / "system" / "cpu"
    policy = cpu / "cpufreq" / "policy0"
    add("cpu", "scaling_driver", read_trimmed(policy / "scaling_driver"))
    add("cpu", "amd_pstate", read_trimmed(cpu / "amd_pstate" / "status"))
    add("cpu", "epp", read_trimmed(policy / "energy_performance_preference"))
    add(
        "cpu",
        "epp_choices",
        read_trimmed(policy / "energy_performance_available_preferences"),
    )
    add("cpu", "boost", read_trimmed(cpu / "cpufreq" / "boost"))

    add(
        "platform",
        "platform_profile",
        read_trimmed(sysfs / "firmware" / "acpi" / "platform_profile"),
    )
    add(
        "platform",
        "platform_profile_choices",
        read_trimmed(sysfs / "firmware" / "acpi" / "platform_profile_choices"),
    )
    add("platform", "mem_sleep", _choice(sysfs / "power" / "mem_sleep"))

    add(
        "pcie",
        "aspm_policy",
        _choice(sysfs / "module" / "pcie_aspm" / "parameters" / "policy"),
    )
    add(
        "pcie",
        "runtime_pm",
        _count_power_control(_glob(sysfs / "bus" / "pci" / "devices", "*")),
    )
    for state, (on, offered) in aspm_link_states(
        sysfs / "bus" / "pci" / "devices"
    ).items():
        name = state.replace("_aspm", "").upper().replace("_", ".")
        add("pcie", f"links_{name}", f"on for {on} of {offered}" if offered else "")

    hda = sysfs / "module" / "snd_hda_intel" / "parameters"
    add("audio", "power_save_s", read_trimmed(hda / "power_save"))
    add("audio", "power_save_controller", read_trimmed(hda / "power_save_controller"))

    for card in _glob(sysfs / "class" / "drm", "card[0-9]"):
        device = card / "device"
        try:
            driver = os.path.basename(os.readlink(device / "driver"))
        except OSError:
            continue
        if driver != "amdgpu":
            continue
        add(
            "gpu",
            f"{card.name}_dpm_level",
            read_trimmed(device / "power_dpm_force_performance_level"),
        )
        modes = read_trimmed(device / "pp_power_profile_mode")
        # One row per mode, the active one marked with "*":
        # "  1 3D_FULL_SCREEN*:" or "  0 BOOTUP_DEFAULT *: ...".
        match = _ACTIVE_GPU_MODE_RE.search(modes)
        add("gpu", f"{card.name}_power_profile", match.group(1) if match else "")
    for knob in _glob(
        sysfs / "class" / "drm", "card*-eDP-*/amdgpu/panel_power_savings"
    ):
        add("gpu", "panel_power_savings", read_trimmed(knob))

    add(
        "usb",
        "autosuspend",
        _count_power_control(
            [
                d
                for d in _glob(sysfs / "bus" / "usb" / "devices", "*")
                if ":" not in d.name
            ]
        ),
    )

    add(
        "storage",
        "nvme_apst_max_latency_us",
        read_trimmed(
            sysfs / "module" / "nvme_core" / "parameters" / "default_ps_max_latency_us"
        ),
    )
    sata = [
        read_trimmed(host / "link_power_management_policy")
        for host in _glob(sysfs / "class" / "scsi_host", "host*")
    ]
    add("storage", "sata_link_power", ", ".join(sorted({p for p in sata if p})))

    wireless = [
        net.name
        for net in _glob(sysfs / "class" / "net", "*")
        if (net / "wireless").exists()
    ]
    add("wireless", "interfaces", ", ".join(wireless))

    try:
        tokens = cmdline.read_text(encoding="utf-8", errors="ignore").split()
    except OSError:
        tokens = []
    relevant = [
        t
        for t in tokens
        if t.split("=", 1)[0].startswith(
            ("amd_pstate", "pcie_aspm", "amdgpu", "processor.", "mem_sleep")
        )
    ]
    add("kernel", "cmdline", " ".join(relevant))
    return rows


def find_temperature_input(hwmon_dir: Path) -> Path | None:
    """The CPU package temperature file, or None if no known sensor exists.

    k10temp is the in-tree driver; zenpower is a common out-of-tree
    replacement, and a machine running that one has no k10temp at all.
    """
    for wanted in _TEMPERATURE_SENSORS:
        try:
            hwmons = sorted(hwmon_dir.glob("hwmon*"))
        except OSError:
            continue
        for hwmon in hwmons:
            if read_trimmed(hwmon / "name") != wanted:
                continue
            candidate = hwmon / "temp1_input"
            if is_uint(read_trimmed(candidate)):
                return candidate
    return None


def read_temperature_c(temp_input: Path) -> int | None:
    raw = read_trimmed(temp_input)
    return int(raw) // 1000 if is_uint(raw) else None


def cpu_temperature_c(hwmon_dir: Path) -> int | None:
    """CPU package temperature in whole degrees, or None if no sensor answers."""
    found = find_temperature_input(hwmon_dir)
    return None if found is None else read_temperature_c(found)


def find_ryzenadj(configured: str, search_paths: list[str]) -> str | None:
    """Locate the RyzenAdj binary without ever failing.

    An explicitly configured path that is unusable returns None so the
    caller can report it as fatal; a missing binary is a normal degraded
    case, also None.
    """
    if configured:
        candidate = Path(configured)
        try:
            usable = candidate.is_file() and os.access(configured, os.X_OK)
        except OSError:
            usable = False
        return configured if usable else None
    for search in search_paths:
        if search and os.access(search, os.X_OK):
            try:
                if Path(search).is_file():
                    return search
            except OSError:
                continue
    return shutil.which("ryzenadj")


def kernel_lockdown_mode(lockdown_path: Path) -> str:
    """Active kernel lockdown mode: none, integrity, confidentiality..."""
    try:
        content = (
            lockdown_path.read_bytes()
            .replace(b"\x00", b"")
            .decode("utf-8", errors="ignore")
            .replace("\n", "")
        )
    except OSError:
        return "unavailable"
    if "[none]" in content:
        return "none"
    match = _LOCKDOWN_BRACKET_RE.search(content)
    if match:
        return match.group(1)
    return content or "unknown"


def acquire_dispatcher_lock(state_dir: Path, timeout_s: float) -> typing.TextIO:
    """Take the shared dispatcher lock, raising TimeoutError when contended."""
    state_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    lock_file = (state_dir / "dispatcher.lock").open("w", encoding="utf-8")
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_file
        except BlockingIOError:
            if time.monotonic() >= deadline:
                lock_file.close()
                raise TimeoutError(
                    f"could not acquire dispatcher lock within {timeout_s:g}s"
                )
            time.sleep(0.1)


def sysfs_value_matches(path: Path, desired: str) -> bool:
    """True when a sysfs file already holds the desired value."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip() == desired
    except OSError:
        return False


def apply_cpu_policy(
    cpufreq_dir: Path,
    epp: str,
    boost: str,
    max_freq: str,
    *,
    skip_unchanged: bool = False,
) -> list[str]:
    """Apply boost, EPP and max frequency to every cpufreq policy.

    Returns one message per operation that did not take effect, in the order
    the caller should report them; an empty list means everything applied.
    With ``skip_unchanged`` a sysfs file already holding the desired value is
    left alone, which keeps udev replays from rewriting identical values
    (without it the write is attempted anyway, for callers that do not care).
    ``max_freq`` may be the literal ``uncapped``, resolved per policy from
    cpuinfo_max_freq. The function never prints or exits: the caller decides
    whether the returned messages are warnings, logs, or nothing at all.
    """
    failures: list[str] = []

    boost_value = "1" if boost == "on" else "0"
    boost_path = cpufreq_dir / "boost"
    try:
        boost_exists = boost_path.exists()
    except OSError:
        boost_exists = False
    if boost_exists and not (
        skip_unchanged and sysfs_value_matches(boost_path, boost_value)
    ):
        try:
            boost_path.write_text(boost_value + "\n", encoding="utf-8")
        except OSError:
            failures.append("failed to write cpufreq boost")

    try:
        policies = sorted(cpufreq_dir.glob("policy*"))
    except OSError:
        policies = []

    for policy in policies:
        try:
            if not policy.is_dir():
                continue
        except OSError:
            continue
        max_path = policy / "scaling_max_freq"
        try:
            if not max_path.exists():
                continue
        except OSError:
            continue
        if max_freq == "uncapped":
            cpuinfo_max = policy / "cpuinfo_max_freq"
            try:
                if not cpuinfo_max.is_file():
                    continue
                value = cpuinfo_max.read_text(encoding="utf-8")
            except OSError:
                continue
            if skip_unchanged and sysfs_value_matches(max_path, value.strip()):
                continue
            try:
                max_path.write_text(value, encoding="utf-8")
            except OSError:
                failures.append(f"failed to restore {policy}/scaling_max_freq")
        else:
            if skip_unchanged and sysfs_value_matches(max_path, max_freq):
                continue
            try:
                max_path.write_text(max_freq + "\n", encoding="utf-8")
            except OSError:
                failures.append(f"rejected max freq {max_freq} for {policy}")

    epp_applied = 0
    for policy in policies:
        epp_path = policy / "energy_performance_preference"
        try:
            if not epp_path.exists():
                continue
        except OSError:
            continue
        if skip_unchanged and sysfs_value_matches(epp_path, epp):
            epp_applied += 1
            continue
        try:
            epp_path.write_text(epp + "\n", encoding="utf-8")
            epp_applied += 1
        except OSError:
            failures.append(f"failed to write EPP {epp} to {policy}")
    if epp_applied == 0:
        failures.append(
            f"no cpufreq policy accepted EPP {epp}; skipping EPP "
            "(cpufreq driver not in EPP mode?)"
        )

    return failures


def apply_smu_limits(
    ryzenadj_bin: str,
    stapm_mw: str,
    fast_mw: str,
    slow_mw: str,
    apu_mw: str,
    tctl_c: str,
    vrmmax_ma: str | None = None,
) -> bool:
    """Run RyzenAdj with profile limits; False when it could not run."""
    cmd = [
        ryzenadj_bin,
        f"--stapm-limit={stapm_mw}",
        f"--fast-limit={fast_mw}",
        f"--slow-limit={slow_mw}",
        f"--apu-slow-limit={apu_mw}",
        f"--tctl-temp={tctl_c}",
    ]
    if vrmmax_ma and vrmmax_ma != "stock":
        cmd.append(f"--vrmmax-current={vrmmax_ma}")
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # A hung RyzenAdj must not hang its caller: the daemon would stop
        # answering and the systemd watchdog would kill it.
        return False


# Display drivers keep their own runtime PM policy: forcing it from here can
# blank or stall the panel, so they are never touched.
_RUNTIME_PM_DRIVER_DENYLIST = ("amdgpu", "radeon", "nouveau", "nvidia")


def _runtime_pm_candidates(pci_devices_dir: Path) -> list[Path]:
    """PCI devices with a bound driver whose runtime PM we may change."""
    try:
        devices = sorted(pci_devices_dir.glob("*"))
    except OSError:
        return []
    candidates: list[Path] = []
    for device in devices:
        try:
            driver_link = device / "driver"
            if not driver_link.exists():
                continue
            driver = os.path.basename(os.readlink(driver_link))
        except OSError:
            continue
        if driver in _RUNTIME_PM_DRIVER_DENYLIST:
            continue
        if read_trimmed(device / "class").startswith("0x03"):
            continue
        if not (device / "power" / "control").exists():
            continue
        candidates.append(device)
    return candidates


def apply_pci_runtime_pm(
    pci_devices_dir: Path, policy: str, defaults_file: Path
) -> list[str]:
    """Let idle PCI devices runtime-suspend, or put back the boot defaults.

    ``auto`` switches every eligible device to ``auto`` and records the value
    it replaced in ``defaults_file``; ``default`` writes the recorded values
    back and forgets them. The record lives under /run, so a reboot starts
    again from the kernel's own defaults. Devices whose driver has no runtime
    PM callbacks simply stay active, so the switch is harmless for them.
    Returns one message per write that did not take effect.
    """
    failures: list[str] = []
    recorded = read_key_value_file(defaults_file)

    if policy == "default":
        for name, value in recorded.items():
            control = pci_devices_dir / name / "power" / "control"
            if sysfs_value_matches(control, value):
                continue
            try:
                control.write_text(value + "\n", encoding="utf-8")
            except OSError:
                failures.append(f"failed to restore runtime PM {value} for {name}")
        try:
            defaults_file.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            failures.append(f"failed to remove {defaults_file}")
        return failures

    for device in _runtime_pm_candidates(pci_devices_dir):
        control = device / "power" / "control"
        current = read_trimmed(control)
        if current == "auto":
            continue
        try:
            control.write_text("auto\n", encoding="utf-8")
        except OSError:
            failures.append(f"failed to enable runtime PM for {device.name}")
            continue
        recorded.setdefault(device.name, current or "on")
    if recorded:
        try:
            write_atomic(
                defaults_file,
                "".join(
                    f"{name}={value}\n" for name, value in sorted(recorded.items())
                ),
            )
        except OSError:
            failures.append(f"failed to record runtime PM defaults in {defaults_file}")
    return failures


def apply_panel_power_savings(drm_dir: Path, level: str) -> str:
    """Set the amdgpu panel power savings (ABM) level on internal panels.

    Returns ``ok``, ``unsupported`` when no internal panel exposes the knob
    (older kernels, non-AMD graphics), or ``failed`` when a write was refused,
    for example because amdgpu.abmlevel is pinned on the kernel command line.
    """
    try:
        knobs = sorted(drm_dir.glob("card*-eDP-*/amdgpu/panel_power_savings"))
    except OSError:
        knobs = []
    if not knobs:
        return "unsupported"
    status = "ok"
    for knob in knobs:
        if sysfs_value_matches(knob, level):
            continue
        try:
            knob.write_text(level + "\n", encoding="utf-8")
        except OSError:
            status = "failed"
    return status


def apply_pcie_aspm(
    policy_param: Path, policy: str, defaults_file: Path
) -> tuple[str, str | None]:
    """Set the kernel's PCIe ASPM policy, or put back the boot one.

    Returns (the policy now in force or ``unsupported``/``failed``, a warning
    or None). ``default`` restores the value recorded before the first change
    and writes nothing when there is none, so a machine whose profiles all
    keep the default never sees a write. The record lives under /run, so a
    reboot starts again from the boot policy.
    """
    if not policy_param.exists():
        return "unsupported", None
    current = _choice(policy_param)
    recorded = read_trimmed(defaults_file)
    if policy == "default":
        if not recorded:
            return current or "unknown", None
        if current != recorded:
            try:
                policy_param.write_text(recorded + "\n", encoding="utf-8")
            except OSError:
                return current or "unknown", (
                    f"failed to restore the boot PCIe ASPM policy {recorded}"
                )
        try:
            defaults_file.unlink()
        except OSError:
            pass
        return _choice(policy_param) or recorded, None
    if current == policy:
        return policy, None
    if not recorded and current:
        try:
            write_atomic(defaults_file, current + "\n")
        except OSError:
            return current, (
                f"not changing the PCIe ASPM policy: could not record the boot "
                f"policy {current} in {defaults_file} to restore it later"
            )
    try:
        policy_param.write_text(policy + "\n", encoding="utf-8")
    except OSError:
        return "failed", (
            f"the kernel refused PCIe ASPM policy {policy}; the firmware may keep "
            "ASPM control for itself, or pcie_aspm=off is on the command line"
        )
    return _choice(policy_param) or policy, None


def aspm_link_states(pci_devices_dir: Path) -> dict[str, tuple[int, int]]:
    """For each ASPM state, (links where it is on, links that offer it).

    The kernel exposes one ``link/<state>`` file per state a link supports,
    reading 1 when the state is enabled; under the ``default`` policy that is
    whatever the firmware chose.
    """
    counts: dict[str, tuple[int, int]] = {}
    for state in ("l0s_aspm", "l1_aspm", "l1_1_aspm", "l1_2_aspm"):
        on = offered = 0
        for knob in _glob(pci_devices_dir, f"*/link/{state}"):
            value = read_trimmed(knob)
            if value in ("0", "1"):
                offered += 1
                on += value == "1"
        counts[state] = (on, offered)
    return counts


def write_atomic(path: Path, content: str, mode: int = 0o644) -> None:
    """Write text to a file atomically via a temporary file in the same directory."""
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, path)
