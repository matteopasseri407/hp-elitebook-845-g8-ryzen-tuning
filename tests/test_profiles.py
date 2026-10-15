# SPDX-License-Identifier: GPL-3.0-or-later
"""The pure decisions: profiles, overrides, precedence, idle, targets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import elitebook_profiles as profiles  # noqa: E402


def config(tmp_path: Path, text: str) -> profiles.ProfileConfig:
    path = tmp_path / "profiles.conf"
    path.write_text(text, encoding="utf-8")
    return profiles.ProfileConfig.load(path)


def test_builtin_values_are_unchanged() -> None:
    ac = profiles.BUILTIN_PROFILES["ac"]
    assert (ac.slow_mw, ac.fast_mw, ac.tctl_c, ac.epp) == (
        18000,
        30000,
        90,
        "balance_power",
    )
    battery = profiles.BUILTIN_PROFILES["battery"]
    assert (battery.slow_mw, battery.fast_mw, battery.tctl_c, battery.vrmmax_ma) == (
        15000,
        22000,
        80,
        45000,
    )
    saver = profiles.BUILTIN_PROFILES["battery-saver"]
    assert saver.boost is False and saver.max_freq_khz == 1800000
    assert set(profiles.BUILTIN_PROFILES) == set(profiles.PROFILE_NAMES)


def test_missing_config_changes_nothing(tmp_path: Path) -> None:
    conf = profiles.ProfileConfig.load(tmp_path / "absent.conf")
    profile, warnings = profiles.resolve_profile("cool", conf)
    assert profile == profiles.BUILTIN_PROFILES["cool"]
    assert warnings == []


def test_overrides_last_wins_and_comments_are_stripped(tmp_path: Path) -> None:
    conf = config(
        tmp_path,
        "AC_SLOW_MW=14000\n  AC_SLOW_MW = 16000  # later wins\nAC_EPP=power\n",
    )
    profile, warnings = profiles.resolve_profile("ac", conf)
    assert profile.slow_mw == 16000
    assert profile.epp == "power"
    assert profile.fast_mw == 30000
    assert warnings == []


def test_empty_last_value_counts_as_absent(tmp_path: Path) -> None:
    conf = config(tmp_path, "AC_SLOW_MW=14000\nAC_SLOW_MW=  # cleared\n")
    profile, _ = profiles.resolve_profile("ac", conf)
    assert profile.slow_mw == 18000


def test_refused_values_keep_defaults_and_name_the_line(tmp_path: Path) -> None:
    conf = config(
        tmp_path,
        "# header\nAC_SLOW_MW=95000\nAC_EPP=turbo\nAC_BOOST=maybe\n"
        "AC_MAX_FREQ_KHZ=99999999\nAC_VRMMAX_MA=abc\nAC_RUNTIME_PM=sometimes\n"
        "AC_PANEL_POWER_SAVINGS=9\n",
    )
    profile, warnings = profiles.resolve_profile("ac", conf)
    assert profile == profiles.BUILTIN_PROFILES["ac"]
    text = "\n".join(warnings)
    assert "line 2: AC_SLOW_MW=95000 is outside the safe range 4000-45000" in text
    assert "is not a valid EPP hint" in text
    assert "is not a valid boost setting" in text
    assert "AC_MAX_FREQ_KHZ=99999999 is outside the safe range" in text
    assert "AC_VRMMAX_MA='abc' is not an integer; keeping stock" in text
    assert "is not a valid runtime PM setting" in text
    assert "AC_PANEL_POWER_SAVINGS=9 is outside the safe range 0-4" in text


def test_overrides_are_per_profile(tmp_path: Path) -> None:
    conf = config(tmp_path, "COOL_SLOW_MW=9000\nBATTERY_SAVER_TCTL_C=70\n")
    assert profiles.resolve_profile("ac", conf)[0].slow_mw == 18000
    assert profiles.resolve_profile("cool", conf)[0].slow_mw == 9000
    assert profiles.resolve_profile("battery-saver", conf)[0].tctl_c == 70


def test_device_and_frequency_overrides(tmp_path: Path) -> None:
    conf = config(
        tmp_path,
        "BATTERY_RUNTIME_PM=default\nBATTERY_PANEL_POWER_SAVINGS=0\n"
        "BATTERY_MAX_FREQ_KHZ=2400000\nBATTERY_BOOST=off\nAC_MAX_FREQ_KHZ=uncapped\n",
    )
    battery, _ = profiles.resolve_profile("battery", conf)
    assert battery.runtime_pm == "default"
    assert battery.panel_power_savings == 0
    assert battery.max_freq_khz == 2400000
    assert battery.boost is False
    assert profiles.resolve_profile("ac", conf)[0].max_freq_khz is None


def test_battery_saver_frequency_cap_comes_from_the_caller(tmp_path: Path) -> None:
    conf = profiles.ProfileConfig.load(tmp_path / "absent.conf")
    saver, _ = profiles.resolve_profile("battery-saver", conf, 2200000)
    assert saver.max_freq_khz == 2200000


def test_shipped_example_is_inert() -> None:
    conf = profiles.ProfileConfig.load(REPO_ROOT / "config" / "profiles.conf.example")
    for name in profiles.PROFILE_NAMES:
        profile, warnings = profiles.resolve_profile(name, conf)
        assert profile == profiles.BUILTIN_PROFILES[name]
        assert warnings == []


# --- precedence ----------------------------------------------------------


def test_auto_profile() -> None:
    assert profiles.auto_profile(True, 5, 20) == "ac"
    assert profiles.auto_profile(False, 21, 20) == "battery"
    assert profiles.auto_profile(False, 20, 20) == "battery-saver"
    assert profiles.auto_profile(False, None, 20) == "battery"
    assert profiles.auto_profile(False, 5, 0) == "battery"


def test_low_battery_guard_outranks_manual_and_game() -> None:
    assert profiles.choose_base(False, 10, 20, "performance", True) == (
        "battery-saver",
        profiles.SOURCE_AUTO,
    )


def test_manual_outranks_game_and_game_outranks_auto() -> None:
    assert profiles.choose_base(True, 90, 20, "cool", True) == (
        "cool",
        profiles.SOURCE_MANUAL,
    )
    assert profiles.choose_base(True, 90, 20, None, True) == (
        "gaming",
        profiles.SOURCE_GAME,
    )
    assert profiles.choose_base(False, 90, 20, None, False) == (
        "battery",
        profiles.SOURCE_AUTO,
    )


# --- idle hysteresis ---------------------------------------------------------


def feed(detector: profiles.IdleDetector, samples: list[float]) -> list[str]:
    return [detector.update(busy, 0.2, True) for busy in samples]


def test_soft_then_deep_then_out_on_one_busy_sample() -> None:
    detector = profiles.IdleDetector(profiles.IdleSettings())
    stages = feed(detector, [1.0] * 35)
    assert stages[3] == profiles.IDLE_NONE
    assert stages[4] == profiles.IDLE_SOFT
    assert stages[29] == profiles.IDLE_DEEP
    assert detector.update(9.0, 0.2, True) == profiles.IDLE_NONE


def test_oscillating_interactive_load_never_enters_soft_idle() -> None:
    detector = profiles.IdleDetector(profiles.IdleSettings())
    stages = feed(detector, [1.0, 1.0, 1.0, 1.0, 5.0] * 10)
    assert set(stages) == {profiles.IDLE_NONE}


def test_middle_band_keeps_the_stage_but_restarts_the_count() -> None:
    detector = profiles.IdleDetector(profiles.IdleSettings())
    feed(detector, [1.0] * 10)
    assert detector.stage == profiles.IDLE_SOFT
    # 5% is neither quiet nor busy: soft idle holds, deep idle waits longer.
    assert feed(detector, [5.0] * 40)[-1] == profiles.IDLE_SOFT


def test_high_load_average_alone_ends_idle() -> None:
    detector = profiles.IdleDetector(profiles.IdleSettings())
    feed(detector, [1.0] * 10)
    assert detector.update(1.0, 2.0, True) == profiles.IDLE_NONE


def test_not_allowed_or_disabled_means_no_overlay() -> None:
    detector = profiles.IdleDetector(profiles.IdleSettings())
    feed(detector, [1.0] * 10)
    assert detector.update(1.0, 0.2, False) == profiles.IDLE_NONE
    disabled = profiles.IdleDetector(profiles.IdleSettings(enabled=False))
    assert set(feed(disabled, [1.0] * 40)) == {profiles.IDLE_NONE}


def test_idle_settings_read_the_old_watcher_environment() -> None:
    settings = profiles.IdleSettings.from_env(
        {
            "ELITEBOOK_IDLE_SOFT_ENTER_SAMPLES": "3",
            "ELITEBOOK_DEEP_IDLE_MAX_FREQ_KHZ": "uncapped",
            "ELITEBOOK_DEEP_IDLE_DISABLE_BOOST": "0",
            "ELITEBOOK_IDLE_OVERLAY": "0",
            "ELITEBOOK_DEEP_IDLE_EPP": "turbo",
            "ELITEBOOK_IDLE_EXIT_BUSY_PERCENT": "oops",
        }
    )
    assert settings.soft_enter_samples == 3
    assert settings.deep_max_freq_khz is None
    assert settings.deep_disable_boost is False
    assert settings.enabled is False
    assert settings.deep_epp == "power"
    assert settings.exit_busy_percent == 8.0


# --- targets ----------------------------------------------------------------


def test_no_idle_target_is_the_profile() -> None:
    battery = profiles.BUILTIN_PROFILES["battery"]
    target = profiles.target_for(battery, profiles.IDLE_NONE, profiles.IdleSettings())
    assert target.cpu == profiles.CpuPolicy("balance_power", True, None)
    assert target.smu == profiles.SmuLimits(15000, 22000, 15000, 15000, 80, 45000)
    assert (target.runtime_pm, target.panel_power_savings) == ("auto", 1)


def test_soft_idle_only_moves_the_epp_and_keeps_stricter_caps() -> None:
    saver = profiles.BUILTIN_PROFILES["battery-saver"]
    idle = profiles.IdleSettings(soft_epp="balance_power")
    target = profiles.target_for(saver, profiles.IDLE_SOFT, idle)
    assert target.cpu == profiles.CpuPolicy("balance_power", False, 1800000)
    assert target.smu.slow_mw == saver.slow_mw


def test_deep_idle_lowers_but_never_raises() -> None:
    saver = profiles.BUILTIN_PROFILES["battery-saver"]
    idle = profiles.IdleSettings(deep_max_freq_khz=2400000, deep_fast_mw=20000)
    target = profiles.target_for(saver, profiles.IDLE_DEEP, idle)
    assert target.cpu.max_freq_khz == 1800000
    assert target.cpu.boost is False
    assert target.smu.fast_mw == saver.fast_mw
    assert target.smu.slow_mw == 6000
    assert target.smu.vrmmax_ma == saver.vrmmax_ma


def test_deep_idle_can_leave_smu_alone() -> None:
    ac = profiles.BUILTIN_PROFILES["ac"]
    idle = profiles.IdleSettings(deep_apply_smu=False)
    target = profiles.target_for(ac, profiles.IDLE_DEEP, idle)
    assert target.smu == profiles.target_for(ac, profiles.IDLE_NONE, idle).smu
    # The 1.8 GHz cap already keeps boost out; the boost switch is left alone.
    assert target.cpu == profiles.CpuPolicy("power", True, 1800000)


def test_lower_cap() -> None:
    assert profiles.lower_cap(None, None) is None
    assert profiles.lower_cap(None, 1800000) == 1800000
    assert profiles.lower_cap(2400000, 1800000) == 1800000


def test_hardware_problem() -> None:
    cpu = "AMD Ryzen 7 PRO 5850U with Radeon Graphics"
    assert (
        profiles.hardware_problem("HP", "HP EliteBook 845 G8 Notebook PC", cpu) is None
    )
    assert "unsupported vendor" in (profiles.hardware_problem("Dell", "XPS", cpu) or "")
    assert "Rembrandt" in (
        profiles.hardware_problem("HP", "HP EliteBook 845 G9", "AMD Ryzen 7 PRO 6850U")
        or ""
    )


def test_cap_battery_current() -> None:
    idle = profiles.IdleSettings()
    gaming = profiles.target_for(
        profiles.BUILTIN_PROFILES["gaming"], profiles.IDLE_NONE, idle
    )
    assert profiles.cap_battery_current(gaming, 45000).smu.vrmmax_ma == 45000
    assert profiles.cap_battery_current(gaming, None) == gaming
    saver = profiles.target_for(
        profiles.BUILTIN_PROFILES["battery-saver"], profiles.IDLE_NONE, idle
    )
    assert profiles.cap_battery_current(saver, 45000).smu.vrmmax_ma == 30000


def test_pcie_aspm_is_opt_in_and_validated(tmp_path: Path) -> None:
    assert {p.pcie_aspm for p in profiles.BUILTIN_PROFILES.values()} == {"default"}
    conf = tmp_path / "profiles.conf"
    conf.write_text(
        "BATTERY_PCIE_ASPM=PowerSuperSave\nAC_PCIE_ASPM=turbo\n", encoding="utf-8"
    )
    config = profiles.ProfileConfig.load(conf)
    battery, warnings = profiles.resolve_profile("battery", config)
    assert (battery.pcie_aspm, warnings) == ("powersupersave", [])
    ac, warnings = profiles.resolve_profile("ac", config)
    assert ac.pcie_aspm == "default"
    assert warnings and "is not a PCIe ASPM policy" in warnings[0]
