#!/usr/bin/env python3
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


def cpu_temperature_c(hwmon_dir: Path) -> int | None:
    """CPU package temperature in whole degrees, or None if no sensor answers.

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
            raw = read_trimmed(hwmon / "temp1_input")
            if not is_uint(raw):
                continue
            return int(raw) // 1000
    return None


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
) -> bool:
    """Run RyzenAdj with the five profile limits; False when it could not run."""
    try:
        result = subprocess.run(
            [
                ryzenadj_bin,
                f"--stapm-limit={stapm_mw}",
                f"--fast-limit={fast_mw}",
                f"--slow-limit={slow_mw}",
                f"--apu-slow-limit={apu_mw}",
                f"--tctl-temp={tctl_c}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except OSError:
        return False


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
