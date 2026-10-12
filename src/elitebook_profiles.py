#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Profiles, user overrides and the pure decisions built on them.

Nothing here touches hardware or the clock. Given the facts (power source,
battery level, a manual choice, a running game, the idle stage) these
functions say which profile should be in force and which concrete values the
hardware should hold. The daemon gathers the facts and applies the result;
keeping the decisions pure is what lets the tests cover every rule without
root, sysfs fixtures or timing.

Standard library only, like the rest of the stack.
"""

from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

VALID_EPPS = ("performance", "balance_performance", "balance_power", "power")
PROFILE_NAMES = ("ac", "performance", "battery", "battery-saver", "gaming", "cool")

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"
# Kept from the watcher era: the GNOME extension labels this source "Steam".
SOURCE_GAME = "steam-game-watcher"

IDLE_NONE = "none"
IDLE_SOFT = "soft"
IDLE_DEEP = "deep"

SUPPORTED_PRODUCT_SUBSTRINGS = (
    "EliteBook 835 G7",
    "EliteBook 835 G8",
    "EliteBook 835 G9",
    "EliteBook 845 G7",
    "EliteBook 845 G8",
    "EliteBook 845 G9",
    "ProBook 445 G8",
    "ProBook 445 G9",
    "ProBook 455 G8",
    "ProBook 455 G9",
)
CEZANNE_RE = re.compile(r"AMD Ryzen (5|7) PRO (5650U|5750U|5850U)")
REMBRANDT_RE = re.compile(r"AMD Ryzen (5|7) PRO (6650U|6850U)")


@dataclasses.dataclass(frozen=True)
class Profile:
    """Everything one profile asks of the machine.

    ``max_freq_khz`` None means uncapped; ``vrmmax_ma`` None leaves the
    firmware's stock VRM current limit alone. ``runtime_pm`` is ``auto``
    (idle PCI devices may power down) or ``default`` (what the kernel chose at
    boot); ``panel_power_savings`` is the amdgpu ABM level, 0 (off) to 4.
    """

    name: str
    epp: str
    stapm_mw: int
    fast_mw: int
    slow_mw: int
    apu_mw: int
    tctl_c: int
    boost: bool
    max_freq_khz: int | None
    vrmmax_ma: int | None
    tuned_profile: str
    runtime_pm: str
    panel_power_savings: int


BATTERY_SAVER_MAX_FREQ_KHZ = 1800000

# STAPM is listed for completeness: on STT platforms such as the 845 G8 the
# firmware rewrites it within a second (docs/troubleshooting.md), so the slow
# limit is the sustained envelope that actually holds.
BUILTIN_PROFILES = {
    "ac": Profile(
        "ac", "balance_power", 22000, 30000, 18000, 18000, 90, True, None, None,
        "balanced", "default", 0,
    ),
    "performance": Profile(
        "performance", "balance_performance", 22000, 30000, 18000, 18000, 90, True,
        None, None, "balanced", "default", 0,
    ),
    "battery": Profile(
        "battery", "balance_power", 15000, 22000, 15000, 15000, 80, True, None,
        45000, "balanced", "auto", 1,
    ),
    "battery-saver": Profile(
        "battery-saver", "power", 10000, 15000, 8000, 8000, 80, False,
        BATTERY_SAVER_MAX_FREQ_KHZ, 30000, "powersave", "auto", 3,
    ),
    "gaming": Profile(
        "gaming", "balance_performance", 30000, 30000, 23000, 23000, 92, True, None,
        None, "balanced", "default", 0,
    ),
    "cool": Profile(
        "cool", "power", 16000, 22000, 12000, 12000, 85, True, None, 40000,
        "balanced", "default", 0,
    ),
}  # fmt: skip


# --- profiles.conf ---------------------------------------------------------

_CONF_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$")


@dataclasses.dataclass(frozen=True)
class ProfileConfig:
    """Parsed /etc/elitebook-thermal-profile/profiles.conf.

    The last occurrence of a key wins, and a last occurrence left empty
    (after stripping comments and whitespace) counts as absent. The file is
    parsed, never executed.
    """

    path: Path
    values: dict[str, tuple[str, int]] = dataclasses.field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> ProfileConfig:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return cls(path)
        last: dict[str, tuple[str, int]] = {}
        for lineno, line in enumerate(text.splitlines(), 1):
            match = _CONF_LINE_RE.match(line)
            if match:
                last[match.group(1)] = (match.group(2), lineno)
        values: dict[str, tuple[str, int]] = {}
        for key, (raw, lineno) in last.items():
            value = re.sub(r"\s+", "", raw.split("#", 1)[0])
            if value:
                values[key] = (value, lineno)
        return cls(path, values)

    def get(self, key: str) -> tuple[str, int] | None:
        return self.values.get(key)


def _is_uint(value: str) -> bool:
    return value.isascii() and value.isdecimal()


class _Overrides:
    """Applies one profile's keys from profiles.conf, collecting warnings."""

    def __init__(self, config: ProfileConfig, prefix: str) -> None:
        self.config = config
        self.prefix = prefix
        self.warnings: list[str] = []

    def _lookup(self, suffix: str) -> tuple[str, str, int] | None:
        key = f"{self.prefix}_{suffix}"
        found = self.config.get(key)
        if found is None:
            return None
        return key, found[0], found[1]

    def _warn(self, lineno: int, text: str) -> None:
        self.warnings.append(f"{self.config.path} line {lineno}: {text}")

    def uint(self, suffix: str, minimum: int, maximum: int, current: int) -> int:
        found = self._lookup(suffix)
        if found is None:
            return current
        key, value, lineno = found
        if not _is_uint(value):
            self._warn(lineno, f"{key}='{value}' is not an integer; keeping {current}")
            return current
        if not minimum <= int(value) <= maximum:
            self._warn(
                lineno,
                f"{key}={value} is outside the safe range {minimum}-{maximum}; "
                f"keeping {current}",
            )
            return current
        return int(value)

    def optional_uint(
        self, suffix: str, minimum: int, maximum: int, current: int | None
    ) -> int | None:
        found = self._lookup(suffix)
        if found is None:
            return current
        shown = "stock" if current is None else str(current)
        key, value, lineno = found
        if not _is_uint(value):
            self._warn(lineno, f"{key}='{value}' is not an integer; keeping {shown}")
            return current
        if not minimum <= int(value) <= maximum:
            self._warn(
                lineno,
                f"{key}={value} is outside the safe range {minimum}-{maximum}; "
                f"keeping {shown}",
            )
            return current
        return int(value)

    def epp(self, current: str) -> str:
        found = self._lookup("EPP")
        if found is None:
            return current
        key, value, lineno = found
        if value in VALID_EPPS:
            return value
        self._warn(
            lineno, f"{key}='{value}' is not a valid EPP hint; keeping {current}"
        )
        return current

    def boost(self, current: bool) -> bool:
        found = self._lookup("BOOST")
        if found is None:
            return current
        key, value, lineno = found
        lower = value.lower()
        if lower in ("on", "1", "yes", "true"):
            return True
        if lower in ("off", "0", "no", "false"):
            return False
        shown = "on" if current else "off"
        self._warn(
            lineno,
            f"{key}='{value}' is not a valid boost setting (expected on/off); "
            f"keeping {shown}",
        )
        return current

    def max_freq(self, current: int | None) -> int | None:
        found = self._lookup("MAX_FREQ_KHZ")
        if found is None:
            return current
        shown = "uncapped" if current is None else str(current)
        key, value, lineno = found
        if value.lower() in ("uncapped", "none", "0"):
            return None
        if not _is_uint(value):
            self._warn(
                lineno,
                f"{key}='{value}' must be an integer kHz or 'uncapped'; keeping {shown}",
            )
            return current
        if not 1000000 <= int(value) <= 5000000:
            self._warn(
                lineno,
                f"{key}={value} is outside the safe range 1000000-5000000 kHz; "
                f"keeping {shown}",
            )
            return current
        return int(value)

    def runtime_pm(self, current: str) -> str:
        found = self._lookup("RUNTIME_PM")
        if found is None:
            return current
        key, value, lineno = found
        if value.lower() in ("auto", "default"):
            return value.lower()
        self._warn(
            lineno,
            f"{key}='{value}' is not a valid runtime PM setting (expected "
            f"auto/default); keeping {current}",
        )
        return current


def resolve_profile(
    name: str,
    config: ProfileConfig,
    battery_saver_max_freq_khz: int = BATTERY_SAVER_MAX_FREQ_KHZ,
) -> tuple[Profile, list[str]]:
    """The built-in profile with the user's overrides applied.

    A refused override keeps the built-in value and produces a warning: a
    typo in profiles.conf must never leave the machine untuned.
    """
    base = BUILTIN_PROFILES[name]
    if name == "battery-saver":
        base = dataclasses.replace(base, max_freq_khz=battery_saver_max_freq_khz)
    o = _Overrides(config, name.upper().replace("-", "_"))
    profile = dataclasses.replace(
        base,
        stapm_mw=o.uint("STAPM_MW", 4000, 45000, base.stapm_mw),
        fast_mw=o.uint("FAST_MW", 4000, 45000, base.fast_mw),
        slow_mw=o.uint("SLOW_MW", 4000, 45000, base.slow_mw),
        apu_mw=o.uint("APU_MW", 4000, 45000, base.apu_mw),
        tctl_c=o.uint("TCTL_C", 60, 100, base.tctl_c),
        epp=o.epp(base.epp),
        boost=o.boost(base.boost),
        max_freq_khz=o.max_freq(base.max_freq_khz),
        vrmmax_ma=o.optional_uint("VRMMAX_MA", 15000, 120000, base.vrmmax_ma),
        runtime_pm=o.runtime_pm(base.runtime_pm),
        panel_power_savings=o.uint(
            "PANEL_POWER_SAVINGS", 0, 4, base.panel_power_savings
        ),
    )
    return profile, o.warnings


# --- which profile is in force -------------------------------------------


def auto_profile(on_ac: bool, battery_percent: int | None, low_threshold: int) -> str:
    """ac on mains, battery-saver at or below the threshold, battery otherwise."""
    if on_ac:
        return "ac"
    if low_threshold > 0 and battery_percent is not None:
        if battery_percent <= low_threshold:
            return "battery-saver"
    return "battery"


def choose_base(
    on_ac: bool,
    battery_percent: int | None,
    low_threshold: int,
    manual: str | None,
    game_running: bool,
) -> tuple[str, str]:
    """(profile, source) for the facts given.

    Precedence, highest first: the low battery guard, a manual choice, a
    running game, the automatic AC/battery choice. The low battery guard
    outranks a manual choice on purpose: running a laptop flat because a
    performance override was left on is the failure it exists to prevent.
    """
    automatic = auto_profile(on_ac, battery_percent, low_threshold)
    if automatic == "battery-saver":
        return automatic, SOURCE_AUTO
    if manual is not None:
        return manual, SOURCE_MANUAL
    if game_running:
        return "gaming", SOURCE_GAME
    return automatic, SOURCE_AUTO


# --- idle overlay ----------------------------------------------------------


def _env_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _env_number(env: dict[str, str], key: str, default: float) -> float:
    try:
        return float(env.get(key, ""))
    except ValueError:
        return default


def _env_khz(env: dict[str, str], key: str, default: int | None) -> int | None:
    raw = env.get(key)
    if raw is None:
        return default
    if raw.strip().lower() == "uncapped":
        return None
    return int(raw) if _is_uint(raw.strip()) else default


def _env_int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    return int(raw) if _is_uint(raw) else default


@dataclasses.dataclass(frozen=True)
class IdleSettings:
    """When idle stages start and end, and what each one asks for.

    Defaults match the watcher this replaced. Soft idle only shifts the EPP
    hint; deep idle also drops boost, caps the frequency and lowers the SMU
    limits. Neither stage ever raises a value above the base profile's.
    """

    enabled: bool = True
    soft_enter_samples: int = 5
    deep_enter_samples: int = 30
    enter_busy_percent: float = 2.5
    exit_busy_percent: float = 8.0
    enter_load1: float = 1.2
    exit_load1: float = 1.6
    soft_epp: str = "balance_power"
    soft_disable_boost: bool = False
    soft_max_freq_khz: int | None = None
    deep_epp: str = "power"
    deep_disable_boost: bool = True
    deep_max_freq_khz: int | None = 1800000
    deep_apply_smu: bool = True
    deep_stapm_mw: int = 10000
    deep_fast_mw: int = 12000
    deep_slow_mw: int = 6000
    deep_apu_mw: int = 6000
    deep_tctl_c: int = 75

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> IdleSettings:
        e = dict(os.environ) if env is None else env
        d = cls()
        soft_epp = e.get("ELITEBOOK_SOFT_IDLE_EPP", d.soft_epp)
        deep_epp = e.get("ELITEBOOK_DEEP_IDLE_EPP", d.deep_epp)
        return cls(
            enabled=_env_bool(e, "ELITEBOOK_IDLE_OVERLAY", d.enabled),
            soft_enter_samples=_env_int(
                e, "ELITEBOOK_IDLE_SOFT_ENTER_SAMPLES", d.soft_enter_samples
            ),
            deep_enter_samples=_env_int(
                e, "ELITEBOOK_IDLE_DEEP_ENTER_SAMPLES", d.deep_enter_samples
            ),
            enter_busy_percent=_env_number(
                e, "ELITEBOOK_IDLE_ENTER_BUSY_PERCENT", d.enter_busy_percent
            ),
            exit_busy_percent=_env_number(
                e, "ELITEBOOK_IDLE_EXIT_BUSY_PERCENT", d.exit_busy_percent
            ),
            enter_load1=_env_number(e, "ELITEBOOK_IDLE_ENTER_LOAD1", d.enter_load1),
            exit_load1=_env_number(e, "ELITEBOOK_IDLE_EXIT_LOAD1", d.exit_load1),
            soft_epp=soft_epp if soft_epp in VALID_EPPS else d.soft_epp,
            soft_disable_boost=_env_bool(
                e, "ELITEBOOK_SOFT_IDLE_DISABLE_BOOST", d.soft_disable_boost
            ),
            soft_max_freq_khz=_env_khz(
                e, "ELITEBOOK_SOFT_IDLE_MAX_FREQ_KHZ", d.soft_max_freq_khz
            ),
            deep_epp=deep_epp if deep_epp in VALID_EPPS else d.deep_epp,
            deep_disable_boost=_env_bool(
                e, "ELITEBOOK_DEEP_IDLE_DISABLE_BOOST", d.deep_disable_boost
            ),
            deep_max_freq_khz=_env_khz(
                e, "ELITEBOOK_DEEP_IDLE_MAX_FREQ_KHZ", d.deep_max_freq_khz
            ),
            deep_apply_smu=_env_bool(
                e, "ELITEBOOK_DEEP_IDLE_APPLY_RYZENADJ", d.deep_apply_smu
            ),
            deep_stapm_mw=_env_int(e, "ELITEBOOK_DEEP_IDLE_STAPM_MW", d.deep_stapm_mw),
            deep_fast_mw=_env_int(e, "ELITEBOOK_DEEP_IDLE_FAST_MW", d.deep_fast_mw),
            deep_slow_mw=_env_int(e, "ELITEBOOK_DEEP_IDLE_SLOW_MW", d.deep_slow_mw),
            deep_apu_mw=_env_int(e, "ELITEBOOK_DEEP_IDLE_APU_MW", d.deep_apu_mw),
            deep_tctl_c=_env_int(e, "ELITEBOOK_DEEP_IDLE_TCTL_C", d.deep_tctl_c),
        )


class IdleDetector:
    """Hysteresis between busy, soft idle and deep idle.

    Fed one CPU sample per tick. Entering needs consecutive quiet samples,
    leaving needs a single busy one, so foreground work gets the full profile
    back within a sample while a brief lull does not flap the overlay.
    """

    def __init__(self, settings: IdleSettings) -> None:
        self.settings = settings
        self.stage = IDLE_NONE
        self.quiet_samples = 0

    def reset(self) -> None:
        self.stage = IDLE_NONE
        self.quiet_samples = 0

    def update(self, busy_percent: float, load1: float, allowed: bool) -> str:
        s = self.settings
        if not (allowed and s.enabled):
            self.reset()
            return self.stage
        busy = busy_percent >= s.exit_busy_percent or load1 >= s.exit_load1
        quiet = busy_percent <= s.enter_busy_percent and load1 <= s.enter_load1
        if self.stage != IDLE_NONE:
            if busy:
                self.reset()
                return self.stage
            if quiet:
                self.quiet_samples = min(self.quiet_samples + 1, s.deep_enter_samples)
            else:
                self.quiet_samples = 0
            if self.stage != IDLE_DEEP and self.quiet_samples >= s.deep_enter_samples:
                self.stage = IDLE_DEEP
            return self.stage
        self.quiet_samples = self.quiet_samples + 1 if quiet else 0
        if self.quiet_samples >= s.soft_enter_samples:
            self.stage = IDLE_SOFT
            self.quiet_samples = min(self.quiet_samples, s.deep_enter_samples)
        return self.stage


# --- what the hardware should hold ---------------------------------------


@dataclasses.dataclass(frozen=True)
class CpuPolicy:
    epp: str
    boost: bool
    max_freq_khz: int | None


@dataclasses.dataclass(frozen=True)
class SmuLimits:
    stapm_mw: int
    fast_mw: int
    slow_mw: int
    apu_mw: int
    tctl_c: int
    vrmmax_ma: int | None


@dataclasses.dataclass(frozen=True)
class Target:
    cpu: CpuPolicy
    smu: SmuLimits
    runtime_pm: str
    panel_power_savings: int
    tuned_profile: str


def lower_cap(a: int | None, b: int | None) -> int | None:
    """The stricter of two frequency caps, where None means uncapped."""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def target_for(profile: Profile, idle_stage: str, idle: IdleSettings) -> Target:
    cpu = CpuPolicy(profile.epp, profile.boost, profile.max_freq_khz)
    smu = SmuLimits(
        profile.stapm_mw,
        profile.fast_mw,
        profile.slow_mw,
        profile.apu_mw,
        profile.tctl_c,
        profile.vrmmax_ma,
    )
    if idle_stage == IDLE_SOFT:
        cpu = CpuPolicy(
            idle.soft_epp,
            profile.boost and not idle.soft_disable_boost,
            lower_cap(profile.max_freq_khz, idle.soft_max_freq_khz),
        )
    elif idle_stage == IDLE_DEEP:
        cpu = CpuPolicy(
            idle.deep_epp,
            profile.boost and not idle.deep_disable_boost,
            lower_cap(profile.max_freq_khz, idle.deep_max_freq_khz),
        )
        if idle.deep_apply_smu:
            smu = SmuLimits(
                min(profile.stapm_mw, idle.deep_stapm_mw),
                min(profile.fast_mw, idle.deep_fast_mw),
                min(profile.slow_mw, idle.deep_slow_mw),
                min(profile.apu_mw, idle.deep_apu_mw),
                min(profile.tctl_c, idle.deep_tctl_c),
                profile.vrmmax_ma,
            )
    return Target(
        cpu,
        smu,
        profile.runtime_pm,
        profile.panel_power_savings,
        profile.tuned_profile,
    )


def cap_battery_current(target: Target, cap_ma: int | None) -> Target:
    """Hold any profile to the battery's VRM peak current limit.

    The battery pack browns out on the current spike of an all-core AVX2
    burst (a local LLM starting a long prompt) when the VRM limit is the
    firmware's stock value. The battery profiles carry a lower limit, but a
    manual choice or a Steam game can put an AC profile in force on battery,
    so the limit is applied to whatever profile runs there.
    """
    if cap_ma is None:
        return target
    current = target.smu.vrmmax_ma
    if current is not None and current <= cap_ma:
        return target
    return dataclasses.replace(
        target, smu=dataclasses.replace(target.smu, vrmmax_ma=cap_ma)
    )


# --- supported hardware ----------------------------------------------------


def hardware_problem(vendor: str, product: str, cpu: str) -> str | None:
    """Why this machine is not supported, or None when it is."""
    if vendor not in ("HP", "Hewlett-Packard"):
        return (
            f"unsupported vendor '{vendor}' "
            "(set ELITEBOOK_THERMAL_FORCE=1 to override)"
        )
    if not any(sub in product for sub in SUPPORTED_PRODUCT_SUBSTRINGS):
        return (
            f"unsupported product '{product}' "
            "(set ELITEBOOK_THERMAL_FORCE=1 to override)"
        )
    if CEZANNE_RE.search(cpu):
        return None
    if REMBRANDT_RE.search(cpu):
        return (
            f"known HP AMD Rembrandt hardware '{product}' / '{cpu}' is not enabled "
            "yet because these SMU limits are only validated on Cezanne "
            "(set ELITEBOOK_THERMAL_FORCE=1 to override after reviewing profile values)"
        )
    return (
        f"unsupported CPU '{cpu}' (validated Cezanne CPUs: Ryzen PRO 5650U, 5750U, "
        "5850U; set ELITEBOOK_THERMAL_FORCE=1 to override)"
    )
