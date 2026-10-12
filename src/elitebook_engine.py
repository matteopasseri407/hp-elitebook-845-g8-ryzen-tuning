#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The reconcile engine: the only code that writes power settings.

Every tick the daemon hands the engine a snapshot of the facts (power source,
battery level, CPU load, a running game, the temperature). The engine works
out which profile should be in force and which concrete values the hardware
should hold (elitebook_profiles), compares that with what it applied last,
and writes only the difference. A periodic reassert, and one right after a
resume from sleep, rewrites everything in case firmware reset it.

One writer, one place that decides. The previous design had a dispatcher, an
idle watcher and a Steam watcher writing the same knobs under a shared lock
and comparing timestamps in state files to notice each other; that is what
let a battery level update every minute clobber the idle overlay and reset
the thermal record.

Hardware access sits behind small classes so the tests can run the engine
against fakes or fixture directories.
"""

from __future__ import annotations

import dataclasses
import os
import re
import shutil
import subprocess
import sys
import time
import typing
from datetime import datetime
from pathlib import Path

import elitebook_common as common
import elitebook_profiles as profiles
from elitebook_profiles import CpuPolicy, Profile, ProfileConfig, SmuLimits, Target

REASSERT_INTERVAL_S = 3600.0
RESUME_FOLLOWUP_S = 10.0
SMU_RETRY_S = 300.0
# Percentage points the battery must climb back above the low battery
# threshold before battery-saver lets go: estimated capacity jitters by a
# point under changing load, and each flip would switch profiles.
LOW_BATTERY_HYSTERESIS = 2
THERMAL_WRITE_SAMPLES = 60


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Log:
    """Messages for the journal (daemon) or the terminal (one-shot runs)."""

    def __init__(self, prog: str = "elitebook-thermal-profile") -> None:
        self.prog = prog

    def info(self, message: str) -> None:
        print(message, flush=True)

    def warn(self, message: str) -> None:
        print(f"{self.prog}: warning: {message}", file=sys.stderr, flush=True)


# --- facts ---------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Facts:
    now: float
    on_ac: bool
    battery_percent: int | None
    busy_percent: float
    load1: float
    game_running: bool
    temperature_c: int | None


class CpuSampler:
    """CPU busy share between consecutive calls, from /proc/stat."""

    def __init__(self, proc_stat: Path = Path("/proc/stat")) -> None:
        self.proc_stat = proc_stat
        self.previous = self._read()

    def _read(self) -> tuple[int, int]:
        try:
            first = self.proc_stat.read_text(encoding="utf-8").splitlines()[0]
            values = [int(value) for value in first.split()[1:]]
        except (OSError, IndexError, ValueError):
            return 0, 0
        return sum(values), values[3] + values[4]

    def busy_percent(self) -> float:
        current = self._read()
        total = current[0] - self.previous[0]
        idle = current[1] - self.previous[1]
        self.previous = current
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (total - idle) / total))


def load1(loadavg: Path = Path("/proc/loadavg")) -> float:
    try:
        return float(loadavg.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


# --- Steam games -----------------------------------------------------------

_STEAM_ID_RE = re.compile(rb"^[1-9][0-9]*$")
_STEAM_ID_KEYS = (b"SteamGameId", b"SteamAppId", b"STEAM_COMPAT_APP_ID")
# /proc/<pid>/comm is truncated to 15 characters, so these use the truncated
# forms or matches silently fail.
_STEAM_ROOT_COMMANDS = {"steam", "steamwebhelper"}
_STEAM_IGNORED_COMMANDS = {
    "steam",
    "steamwebhelper",
    "steam-runtime-l",
    "pressure-vessel",
    "pv-bwrap",
}


def steam_appid_from_environ(environ_path: Path) -> str | None:
    try:
        data = environ_path.read_bytes()
    except OSError:
        return None
    for entry in data.split(b"\0"):
        key, sep, value = entry.partition(b"=")
        if sep and key in _STEAM_ID_KEYS and _STEAM_ID_RE.match(value):
            return value.decode("ascii", errors="ignore")
    return None


def _process_comms(proc: Path) -> dict[int, str]:
    comms: dict[int, str] = {}
    try:
        entries = list(proc.iterdir())
    except OSError:
        return comms
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        comms[int(entry.name)] = comm.strip()
    return comms


def _parent_pid(proc: Path, pid: int) -> int | None:
    try:
        stat = (proc / str(pid) / "stat").read_text(encoding="utf-8", errors="ignore")
        return int(stat.rsplit(") ", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def find_steam_game(
    proc: Path = Path("/proc"),
) -> tuple[dict[str, str] | None, bool]:
    """(the running game, whether Steam itself is running).

    The common case is no Steam at all, so the first pass reads only each
    process name; parent links are read only once a Steam process exists.
    """
    comms = _process_comms(proc)
    roots = {pid for pid, comm in comms.items() if comm in _STEAM_ROOT_COMMANDS}
    if not roots:
        return None, False
    children: dict[int, list[int]] = {}
    for pid in comms:
        ppid = _parent_pid(proc, pid)
        if ppid is not None:
            children.setdefault(ppid, []).append(pid)
    descendants: set[int] = set()
    stack = list(roots)
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in descendants:
                descendants.add(child)
                stack.append(child)
    for pid in sorted(descendants - roots):
        comm = comms[pid]
        if comm in _STEAM_IGNORED_COMMANDS:
            continue
        appid = steam_appid_from_environ(proc / str(pid) / "environ")
        if appid:
            return {"pid": str(pid), "comm": comm, "appid": appid}, True
    return None, True


class GameDetector:
    """Scans for a Steam game on its own, slower schedule.

    A process scan costs far more than a CPU sample, so it runs every
    ``interval_active`` seconds while Steam is open and every ``interval_ac``
    or ``interval_battery`` seconds otherwise; between scans the last answer
    stands.
    """

    def __init__(
        self,
        enabled: bool = True,
        interval_ac: float = 30.0,
        interval_battery: float = 120.0,
        interval_active: float = 20.0,
        scan: typing.Callable[[], tuple[dict[str, str] | None, bool]] = find_steam_game,
    ) -> None:
        self.enabled = enabled
        self.interval_ac = interval_ac
        self.interval_battery = interval_battery
        self.interval_active = interval_active
        self.scan = scan
        self.next_scan = 0.0
        self.game: dict[str, str] | None = None

    def poll(self, now: float, on_ac: bool) -> dict[str, str] | None:
        if not self.enabled:
            return None
        if now < self.next_scan:
            return self.game
        self.game, steam_running = self.scan()
        if steam_running:
            interval = self.interval_active
        else:
            interval = self.interval_ac if on_ac else self.interval_battery
        self.next_scan = now + interval
        return self.game


# --- hardware --------------------------------------------------------------


class Hardware(typing.Protocol):
    def apply_tuned(self, tuned_profile: str) -> list[str]: ...

    def apply_cpu(self, cpu: CpuPolicy) -> list[str]: ...

    def apply_smu(self, smu: SmuLimits) -> tuple[str, str | None]: ...

    def apply_devices(self, runtime_pm: str, panel: int) -> tuple[str, list[str]]: ...


_EDC_LIMIT_RE = re.compile(r"^\|\s*EDC LIMIT VDD\s*\|\s*([0-9.]+)\s*\|", re.MULTILINE)


def read_stock_vrmmax_ma(ryzenadj: str) -> int | None:
    """The VRM peak current (EDC) limit the SMU holds right now, in mA."""
    try:
        result = subprocess.run(
            [ryzenadj, "-i"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _EDC_LIMIT_RE.search(result.stdout)
    if result.returncode != 0 or not match:
        return None
    try:
        amps = float(match.group(1))
    except ValueError:
        return None
    return int(round(amps * 1000)) if amps > 0 else None


@dataclasses.dataclass
class SysfsHardware:
    """The real machine: cpufreq sysfs, RyzenAdj, PCI runtime PM, amdgpu ABM.

    ``stock_vrmmax_ma`` is the firmware's own EDC limit, read before the first
    write after boot. RyzenAdj only changes the limits it is given, so a
    profile without a VRM limit has to write the stock value back, or the
    battery profile's lower limit would stay in force on AC until reboot.
    """

    cpufreq_dir: Path
    pci_devices_dir: Path
    drm_dir: Path
    runtime_pm_defaults: Path
    lockdown_path: Path
    ryzenadj: str | None
    stock_vrmmax_ma: int | None = None
    tuned_active_profile: Path = Path("/etc/tuned/active_profile")

    def apply_tuned(self, tuned_profile: str) -> list[str]:
        # Fedora drives part of the policy through tuned; elsewhere this is a
        # no-op. Only switch when tuned reports a different profile.
        if shutil.which("tuned-adm") is None:
            return []
        if common.read_trimmed(self.tuned_active_profile) == tuned_profile:
            return []
        try:
            result = subprocess.run(
                ["tuned-adm", "profile", tuned_profile],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return []
        except (OSError, subprocess.SubprocessError):
            pass
        return [
            f"tuned-adm did not apply '{tuned_profile}'; continuing with direct "
            "CPU/SMU policy."
        ]

    def apply_cpu(self, cpu: CpuPolicy) -> list[str]:
        return common.apply_cpu_policy(
            self.cpufreq_dir,
            cpu.epp,
            "on" if cpu.boost else "off",
            "uncapped" if cpu.max_freq_khz is None else str(cpu.max_freq_khz),
            skip_unchanged=True,
        )

    def apply_smu(self, smu: SmuLimits) -> tuple[str, str | None]:
        if self.ryzenadj is None:
            return "unavailable", (
                "RyzenAdj not found; applied CPU policy only (EPP, boost, "
                "frequency). Install ryzenadj for the SMU power limits, or set "
                "RYZENADJ=/path/to/ryzenadj."
            )
        ok = common.apply_smu_limits(
            self.ryzenadj,
            str(smu.stapm_mw),
            str(smu.fast_mw),
            str(smu.slow_mw),
            str(smu.apu_mw),
            str(smu.tctl_c),
            self._vrmmax_arg(smu.vrmmax_ma),
        )
        if ok:
            return "ok", None
        lockdown = common.kernel_lockdown_mode(self.lockdown_path)
        if lockdown not in ("none", "unavailable"):
            return "blocked", (
                f"RyzenAdj could not apply SMU limits; kernel lockdown is "
                f"'{lockdown}', which Secure Boot normally enables. CPU policy "
                "(EPP, boost, frequency) was applied. See docs/troubleshooting.md."
            )
        return "failed", (
            "RyzenAdj failed to apply SMU limits. CPU policy (EPP, boost, "
            "frequency) was applied."
        )

    def _vrmmax_arg(self, vrmmax_ma: int | None) -> str | None:
        if vrmmax_ma is not None:
            return str(vrmmax_ma)
        if self.stock_vrmmax_ma is not None:
            return str(self.stock_vrmmax_ma)
        return None

    def apply_devices(self, runtime_pm: str, panel: int) -> tuple[str, list[str]]:
        warnings = common.apply_pci_runtime_pm(
            self.pci_devices_dir, runtime_pm, self.runtime_pm_defaults
        )
        status = common.apply_panel_power_savings(self.drm_dir, str(panel))
        if status == "failed":
            warnings.append(
                f"the panel refused power saving level {panel} "
                "(is amdgpu.abmlevel set on the kernel command line?)"
            )
        return (str(panel) if status == "ok" else status), warnings


# --- state files -----------------------------------------------------------


class StateFiles:
    """The /run files the CLI, the GNOME extension and the guard read.

    ``current`` describes the base profile (never the idle overlay),
    ``idle-watcher`` the overlay while one is active, ``thermal`` the
    temperature record, and ``override`` the manual choice so it survives a
    daemon restart (but not a reboot: /run is a tmpfs).
    """

    def __init__(self, state_dir: Path, log: Log) -> None:
        self.dir = state_dir
        self.log = log

    def _write(self, name: str, lines: list[str]) -> None:
        try:
            common.write_atomic(self.dir / name, "\n".join(lines) + "\n")
        except OSError as exc:
            self.log.warn(f"could not write {self.dir / name}: {exc}")

    def _remove(self, name: str) -> None:
        try:
            (self.dir / name).unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.log.warn(f"could not remove {self.dir / name}: {exc}")

    def write_current(self, lines: list[str]) -> None:
        self._write("current", lines)

    def write_idle(self, lines: list[str]) -> None:
        self._write("idle-watcher", lines)

    def clear_idle(self) -> None:
        self._remove("idle-watcher")

    def write_thermal(self, lines: list[str]) -> None:
        self._write("thermal", lines)

    def read_override(self) -> str | None:
        value = common.read_key_value_file(self.dir / "override").get("profile")
        return value if value in profiles.PROFILE_NAMES else None

    def write_override(self, profile: str | None) -> None:
        if profile is None:
            self._remove("override")
        else:
            self._write("override", [f"profile={profile}", f"updated={now_iso()}"])


class ThermalTracker:
    """Records whether the base profile holds its thermal target.

    The profiles are open loop and the firmware runs its own thermal control,
    so this only measures. The record starts over when the base profile
    changes, never on a reassert or an idle overlay, so it keeps building for
    as long as the same profile is in force.
    """

    def __init__(self, files: StateFiles, write_every: int = THERMAL_WRITE_SAMPLES):
        self.files = files
        self.write_every = write_every
        self.profile = ""
        self.profile_updated = ""
        self.target_c = 0
        self.peak_c = 0
        self.peak_at = ""
        self.samples = 0
        self.over_target = 0
        self.current_c: int | None = None
        self._pending = 0

    def reset(self, profile: str, profile_updated: str, target_c: int) -> None:
        self.profile = profile
        self.profile_updated = profile_updated
        self.target_c = target_c
        self.peak_c = 0
        self.peak_at = ""
        self.samples = 0
        self.over_target = 0
        self._pending = self.write_every

    def sample(self, temperature: int | None) -> None:
        self.current_c = temperature
        if temperature is None or not self.profile:
            return
        self.samples += 1
        write_now = False
        if temperature > self.peak_c:
            self.peak_c = temperature
            self.peak_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            write_now = True
        if self.target_c > 0 and temperature > self.target_c:
            self.over_target += 1
        self._pending += 1
        if write_now or self._pending >= self.write_every:
            self.write()

    def write(self) -> None:
        self._pending = 0
        current = "unknown" if self.current_c is None else str(self.current_c)
        self.files.write_thermal(
            [
                f"profile={self.profile or 'unknown'}",
                f"profile_updated={self.profile_updated or 'unknown'}",
                f"target_c={self.target_c}",
                f"peak_c={self.peak_c}",
                f"peak_at={self.peak_at or 'unknown'}",
                f"current_c={current}",
                f"samples={self.samples}",
                f"over_target={self.over_target}",
                f"updated={time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
            ]
        )


# --- the engine ------------------------------------------------------------


def describe(profile: Profile) -> str:
    max_freq = "uncapped" if profile.max_freq_khz is None else profile.max_freq_khz
    vrm = "" if profile.vrmmax_ma is None else f", VRM {profile.vrmmax_ma // 1000}A"
    return (
        f"EliteBook thermal profile '{profile.name}' applied: "
        f"boost {'on' if profile.boost else 'off'}, max freq {max_freq}, "
        f"EPP {profile.epp}, FAST {profile.fast_mw}mW, "
        f"SLOW/APU {profile.slow_mw}mW, Tctl {profile.tctl_c}C{vrm}."
    )


class Engine:
    def __init__(
        self,
        hardware: Hardware,
        files: StateFiles,
        log: Log,
        config: ProfileConfig,
        idle: profiles.IdleSettings,
        low_battery_threshold: int = 20,
        battery_saver_max_freq_khz: int = profiles.BATTERY_SAVER_MAX_FREQ_KHZ,
        manual: str | None = None,
    ) -> None:
        self.hardware = hardware
        self.files = files
        self.log = log
        self.config = config
        self.idle = profiles.IdleDetector(idle)
        self.low_battery_threshold = low_battery_threshold
        self.battery_saver_max_freq_khz = battery_saver_max_freq_khz
        self.manual = manual
        self.thermal = ThermalTracker(
            files, env_int("ELITEBOOK_THERMAL_WRITE_SAMPLES", THERMAL_WRITE_SAMPLES)
        )
        self.applied: Target | None = None
        self.base: tuple[Profile, str] | None = None
        self.stage = profiles.IDLE_NONE
        self.smu_status = "unknown"
        self.panel_state = "unknown"
        self.next_reassert = 0.0
        self.followup: float | None = None
        self.next_smu_retry: float | None = None
        self.last_facts: Facts | None = None
        self._resolved: dict[str, Profile] = {}
        self._saver_latched = False
        self._written_vrmmax: int | None | str = "unset"

    # Inputs that do not arrive with every tick.

    def set_config(self, config: ProfileConfig) -> None:
        self.config = config
        self._resolved.clear()

    def set_manual(self, profile: str | None) -> None:
        self.manual = profile
        self.files.write_override(profile)

    def request_reassert(self, now: float, followup: bool = False) -> None:
        self.next_reassert = now
        if followup:
            self.followup = now + RESUME_FOLLOWUP_S

    def _resolve(self, name: str) -> Profile:
        if name not in self._resolved:
            profile, warnings = profiles.resolve_profile(
                name, self.config, self.battery_saver_max_freq_khz
            )
            for warning in warnings:
                self.log.warn(warning)
            self._resolved[name] = profile
        return self._resolved[name]

    def step(self, facts: Facts, sample_idle: bool = True) -> None:
        """Reconcile against ``facts``.

        ``sample_idle`` False reuses the idle stage instead of counting this
        call as a CPU sample: a control request between ticks must not push
        the machine towards deep idle faster.
        """
        self.last_facts = facts
        threshold = self.low_battery_threshold
        if self._saver_latched and threshold > 0:
            threshold += LOW_BATTERY_HYSTERESIS
        name, source = profiles.choose_base(
            facts.on_ac,
            facts.battery_percent,
            threshold,
            self.manual,
            facts.game_running,
        )
        self._saver_latched = source == profiles.SOURCE_AUTO and name == "battery-saver"
        if (
            source == profiles.SOURCE_AUTO
            and name == "battery-saver"
            and self.manual is not None
        ):
            self.log.info(
                f"Battery at {facts.battery_percent}%: low battery guard replaces "
                f"the manual '{self.manual}' profile."
            )
            self.set_manual(None)
        profile = self._resolve(name)
        if sample_idle:
            stage = self.idle.update(facts.busy_percent, facts.load1, name != "gaming")
        else:
            if name == "gaming":
                self.idle.reset()
            stage = self.idle.stage
        target = profiles.target_for(profile, stage, self.idle.settings)
        if not facts.on_ac:
            target = profiles.cap_battery_current(
                target, self._resolve("battery").vrmmax_ma
            )
        self._reconcile(facts, profile, source, stage, target)
        self.thermal.sample(facts.temperature_c)

    def _reconcile(
        self,
        facts: Facts,
        profile: Profile,
        source: str,
        stage: str,
        target: Target,
    ) -> None:
        now = facts.now
        reassert = now >= self.next_reassert or (
            self.followup is not None and now >= self.followup
        )
        retry_smu = self.next_smu_retry is not None and now >= self.next_smu_retry
        prev = self.applied
        everything = prev is None or reassert

        tuned_changed = (
            everything or prev is None or prev.tuned_profile != target.tuned_profile
        )
        if tuned_changed:
            for warning in self.hardware.apply_tuned(target.tuned_profile):
                self.log.warn(warning)
        # tuned may rewrite EPP, so the CPU policy always follows a tuned switch.
        if everything or tuned_changed or prev is None or prev.cpu != target.cpu:
            for warning in self.hardware.apply_cpu(target.cpu):
                self.log.warn(warning)

        smu_before = self.smu_status
        if everything or retry_smu or prev is None or prev.smu != target.smu:
            status, smu_warning = self.hardware.apply_smu(target.smu)
            if smu_warning and status != smu_before:
                self.log.warn(smu_warning)
            self.smu_status = status
            self.next_smu_retry = (
                None if status in ("ok", "unavailable") else now + SMU_RETRY_S
            )

        panel_before = self.panel_state
        if (
            everything
            or prev is None
            or prev.runtime_pm != target.runtime_pm
            or prev.panel_power_savings != target.panel_power_savings
        ):
            self.panel_state, warnings = self.hardware.apply_devices(
                target.runtime_pm, target.panel_power_savings
            )
            for warning in warnings:
                self.log.warn(warning)

        self.applied = target
        if reassert:
            self.next_reassert = now + REASSERT_INTERVAL_S
            if self.followup is not None and now >= self.followup:
                self.followup = None

        base_changed = self.base != (profile, source)
        if base_changed:
            self.base = (profile, source)
            self.log.info(describe(profile))
        vrmmax = target.smu.vrmmax_ma
        if vrmmax != profile.vrmmax_ma and vrmmax != self._written_vrmmax:
            self.log.info(
                f"On battery: VRM peak current held at {(vrmmax or 0) // 1000} A "
                f"for the '{profile.name}' profile."
            )
        if (
            base_changed
            or self.smu_status != smu_before
            or self.panel_state != panel_before
            or vrmmax != self._written_vrmmax
        ):
            self._written_vrmmax = vrmmax
            updated = self._write_current(profile, source, facts, vrmmax)
            if base_changed:
                self.thermal.reset(profile.name, updated, profile.tctl_c)

        # The overlay file names its base profile, so a base change while an
        # overlay is active rewrites it too.
        if stage != self.stage or (base_changed and stage != profiles.IDLE_NONE):
            self._write_idle(stage, profile, source, facts, target)
            self.stage = stage

    def _write_current(
        self, profile: Profile, source: str, facts: Facts, vrmmax: int | None
    ) -> str:
        updated = now_iso()
        battery = "unknown" if facts.battery_percent is None else facts.battery_percent
        max_freq = "uncapped" if profile.max_freq_khz is None else profile.max_freq_khz
        vrm = "stock" if vrmmax is None else vrmmax
        self.files.write_current(
            [
                f"profile={profile.name}",
                f"source={source}",
                f"epp={profile.epp}",
                f"smu={self.smu_status}",
                f"stapm_mw={profile.stapm_mw}",
                f"fast_mw={profile.fast_mw}",
                f"slow_mw={profile.slow_mw}",
                f"apu_mw={profile.apu_mw}",
                f"tctl_c={profile.tctl_c}",
                f"boost={'on' if profile.boost else 'off'}",
                f"max_freq={max_freq}",
                f"vrmmax_ma={vrm}",
                f"runtime_pm={profile.runtime_pm}",
                f"panel_power_savings={self.panel_state}",
                f"battery_percent={battery}",
                f"low_battery_threshold_percent={self.low_battery_threshold}",
                f"updated={updated}",
            ]
        )
        return updated

    def _write_idle(
        self, stage: str, profile: Profile, source: str, facts: Facts, target: Target
    ) -> None:
        if stage == profiles.IDLE_NONE:
            self.files.clear_idle()
            self.log.info(
                f"EliteBook idle overlay cleared: restored {profile.name} profile."
            )
            return
        cpu, smu = target.cpu, target.smu
        max_freq = "uncapped" if cpu.max_freq_khz is None else str(cpu.max_freq_khz)
        boost = "on" if cpu.boost else "off"
        self.files.write_idle(
            [
                "active=1",
                f"stage={stage}",
                f"base_profile={profile.name}",
                f"base_source={source}",
                f"busy_percent={facts.busy_percent:.2f}",
                f"load1={facts.load1:.2f}",
                f"epp={cpu.epp}",
                f"boost={boost}",
                f"max_freq={max_freq}",
                f"stapm_mw={smu.stapm_mw}",
                f"fast_mw={smu.fast_mw}",
                f"slow_mw={smu.slow_mw}",
                f"apu_mw={smu.apu_mw}",
                f"tctl_c={smu.tctl_c}",
                f"updated={time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
            ]
        )
        self.log.info(
            f"EliteBook {stage} idle overlay active: EPP {cpu.epp}, boost {boost}, "
            f"max freq {max_freq}, FAST {smu.fast_mw}mW, SLOW/APU {smu.slow_mw}mW, "
            f"Tctl {smu.tctl_c}C."
        )

    def leave_idle(self) -> None:
        """Drop the idle overlay before the daemon exits.

        Stopping the service must not leave the machine on deep idle caps:
        the base profile stays applied, the overlay goes.
        """
        if self.last_facts is None or self.base is None:
            return
        self.idle.reset()
        profile, source = self.base
        target = profiles.target_for(profile, profiles.IDLE_NONE, self.idle.settings)
        self._reconcile(self.last_facts, profile, source, profiles.IDLE_NONE, target)


def env_int(key: str, default: int, env: typing.Mapping[str, str] | None = None) -> int:
    raw = (os.environ if env is None else env).get(key, "").strip()
    return int(raw) if raw.isdecimal() else default
