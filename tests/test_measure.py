# SPDX-License-Identifier: GPL-3.0-or-later
"""``measure`` and ``probe``: the read-only tools for deciding what to tune.

Both run against fixture sysfs trees, so no battery and no root are needed.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import typing

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import elitebook_common as common  # noqa: E402

CLI = REPO_ROOT / "src" / "elitebook-thermal-profile"


def _load_cli() -> typing.Any:
    loader = importlib.machinery.SourceFileLoader("elitebook_cli", str(CLI))
    spec = importlib.util.spec_from_loader("elitebook_cli", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


cli = _load_cli()

# What amdgpu prints on Renoir and Cezanne APUs.
PP_POWER_PROFILE_MODE = """  0 BOOTUP_DEFAULT :
  1 3D_FULL_SCREEN*:
  2 POWER_SAVING   :
  3 VIDEO          :
  4 VR             :
  5 COMPUTE        :
  6 CUSTOM         :
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def _laptop_sysfs(root: Path) -> Path:
    sysfs = root / "sys"
    cpu = sysfs / "devices" / "system" / "cpu"
    policy = cpu / "cpufreq" / "policy0"
    _write(policy / "scaling_driver", "amd-pstate-epp")
    _write(policy / "energy_performance_preference", "balance_power")
    _write(
        policy / "energy_performance_available_preferences",
        "default performance balance_performance balance_power power",
    )
    _write(cpu / "cpufreq" / "boost", "1")
    _write(cpu / "amd_pstate" / "status", "active")
    _write(sysfs / "power" / "mem_sleep", "[s2idle]")
    _write(
        sysfs / "module" / "pcie_aspm" / "parameters" / "policy",
        "[default] performance powersave powersupersave",
    )
    for name, control in (("0000:00:00.0", "on"), ("0000:01:00.0", "auto")):
        _write(sysfs / "bus" / "pci" / "devices" / name / "power" / "control", control)
    hda = sysfs / "module" / "snd_hda_intel" / "parameters"
    _write(hda / "power_save", "1")
    _write(hda / "power_save_controller", "Y")
    gpu = root / "devices" / "gpu"
    _write(gpu / "power_dpm_force_performance_level", "auto")
    _write(gpu / "pp_power_profile_mode", PP_POWER_PROFILE_MODE)
    (root / "drivers" / "amdgpu").mkdir(parents=True)
    (gpu / "driver").symlink_to(root / "drivers" / "amdgpu")
    (sysfs / "class" / "drm" / "card1").mkdir(parents=True)
    (sysfs / "class" / "drm" / "card1" / "device").symlink_to(gpu)
    _write(
        sysfs / "class" / "drm" / "card1-eDP-1" / "amdgpu" / "panel_power_savings",
        "3",
    )
    usb = sysfs / "bus" / "usb" / "devices"
    _write(usb / "1-1" / "power" / "control", "on")
    _write(usb / "1-2" / "power" / "control", "auto")
    _write(usb / "usb1" / "power" / "control", "auto")
    # Interfaces have no power/control of their own and must not count.
    (usb / "1-1:1.0").mkdir(parents=True)
    _write(
        sysfs / "module" / "nvme_core" / "parameters" / "default_ps_max_latency_us",
        "100000",
    )
    (sysfs / "class" / "net" / "wlp1s0" / "wireless").mkdir(parents=True)
    (sysfs / "class" / "net" / "lo").mkdir(parents=True)
    return sysfs


def test_inventory_reads_every_knob(tmp_path: Path) -> None:
    sysfs = _laptop_sysfs(tmp_path)
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("BOOT_IMAGE=/vmlinuz quiet amd_pstate=active splash\n")
    rows = {
        (group, name): value
        for group, name, value in common.power_inventory(sysfs, cmdline)
    }
    assert rows[("cpu", "scaling_driver")] == "amd-pstate-epp"
    assert rows[("cpu", "amd_pstate")] == "active"
    assert rows[("cpu", "epp")] == "balance_power"
    assert rows[("platform", "mem_sleep")] == "s2idle"
    assert rows[("pcie", "aspm_policy")] == "default"
    assert rows[("pcie", "runtime_pm")] == "1 auto, 1 on"
    assert rows[("audio", "power_save_s")] == "1"
    assert rows[("gpu", "card1_dpm_level")] == "auto"
    assert rows[("gpu", "card1_power_profile")] == "3D_FULL_SCREEN"
    assert rows[("gpu", "panel_power_savings")] == "3"
    assert rows[("usb", "autosuspend")] == "2 auto, 1 on"
    assert rows[("storage", "nvme_apst_max_latency_us")] == "100000"
    assert rows[("wireless", "interfaces")] == "wlp1s0"
    assert rows[("kernel", "cmdline")] == "amd_pstate=active"
    # Missing knobs are reported as missing, not skipped.
    assert rows[("platform", "platform_profile")] == ""


def test_inventory_survives_an_empty_tree(tmp_path: Path) -> None:
    rows = common.power_inventory(tmp_path / "nothing", tmp_path / "no-cmdline")
    assert rows
    assert all(value == "" for _, _, value in rows)


def test_battery_power_from_either_firmware_style(tmp_path: Path) -> None:
    watts = tmp_path / "watts"
    _write(watts / "power_now", "7250000")
    assert common.battery_power_w(watts) == pytest.approx(7.25)
    amps = tmp_path / "amps"
    _write(amps / "current_now", "600000")
    _write(amps / "voltage_now", "12000000")
    assert common.battery_power_w(amps) == pytest.approx(7.2)
    assert common.battery_power_w(tmp_path / "none") is None


def test_battery_energy_from_either_firmware_style(tmp_path: Path) -> None:
    energy = tmp_path / "energy"
    _write(energy / "energy_now", "30000000")
    _write(energy / "energy_full", "52000000")
    assert common.battery_energy_wh(energy) == pytest.approx(30.0)
    assert common.battery_energy_wh(energy, "energy_full") == pytest.approx(52.0)
    charge = tmp_path / "charge"
    _write(charge / "charge_now", "2500000")
    _write(charge / "charge_full", "4000000")
    _write(charge / "voltage_min_design", "11550000")
    assert common.battery_energy_wh(charge) == pytest.approx(28.875)
    assert common.battery_energy_wh(charge, "energy_full") == pytest.approx(46.2)


def _supplies(root: Path, on_ac: bool) -> Path:
    supplies = root / "power-supply"
    _write(supplies / "AC" / "type", "Mains")
    _write(supplies / "AC" / "online", "1" if on_ac else "0")
    battery = supplies / "BAT0"
    _write(battery / "type", "Battery")
    _write(battery / "status", "Charging" if on_ac else "Discharging")
    _write(battery / "capacity", "64")
    _write(battery / "power_now", "6000000")
    _write(battery / "energy_now", "33000000")
    _write(battery / "energy_full", "51000000")
    return supplies


def _run(root: Path, supplies: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "ELITEBOOK_POWER_SUPPLY_DIR": str(supplies),
        "ELITEBOOK_THERMAL_STATE_DIR": str(root / "state"),
        "ELITEBOOK_HWMON_DIR": str(root / "hwmon"),
        "ELITEBOOK_SYSFS_ROOT": str(root / "sys"),
        "ELITEBOOK_PROC_CMDLINE": str(root / "cmdline"),
        "ELITEBOOK_MEASURE_INTERVAL": "0.05",
    }
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_measure_reports_draw_and_runtime(tmp_path: Path) -> None:
    supplies = _supplies(tmp_path, on_ac=False)
    _write(tmp_path / "state" / "current", "profile=battery\nsource=auto")
    proc = _run(tmp_path, supplies, "measure", "1", "--json")
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["ended"] == "complete"
    assert result["samples"] >= 2
    assert result["power_w"] == {"avg": 6.0, "min": 6.0, "max": 6.0}
    assert result["runtime"] == {"full_h": 8.5, "remaining_h": 5.5}
    assert (result["profile"], result["source"]) == ("battery", "auto")
    assert result["changed_during"] is False
    assert result["phases"][0]["phase"] == "battery (auto), idle none"
    # A fixture that never changes is exactly what a stuck reading looks like.
    assert result["power_updates"] == 0
    assert result["energy_counter"]["rate_w"] is None

    proc = _run(tmp_path, supplies, "measure", "1")
    assert proc.returncode == 0, proc.stderr
    assert "avg 6.0 W" in proc.stdout
    assert "a full battery lasts about 8.5 h" in proc.stdout


def test_measure_refuses_on_ac(tmp_path: Path) -> None:
    supplies = _supplies(tmp_path, on_ac=True)
    proc = _run(tmp_path, supplies, "measure", "5")
    assert proc.returncode == 1
    assert "unplug the charger" in proc.stderr


def test_measure_stops_when_plugged_in(tmp_path: Path) -> None:
    supplies = _supplies(tmp_path, on_ac=False)

    def plug_in() -> None:
        time.sleep(0.5)
        (supplies / "AC" / "online").write_text("1\n")

    plugger = threading.Thread(target=plug_in)
    plugger.start()
    began = time.monotonic()
    proc = _run(tmp_path, supplies, "measure", "30", "--json")
    plugger.join()
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ended"] == "plugged in"
    assert time.monotonic() - began < 20


def test_measure_rejects_bad_arguments(tmp_path: Path) -> None:
    supplies = _supplies(tmp_path, on_ac=False)
    for args in (("measure", "abc"), ("measure", "0"), ("measure", "5", "6")):
        assert _run(tmp_path, supplies, *args).returncode == 2


def test_probe_prints_text_and_json(tmp_path: Path) -> None:
    _laptop_sysfs(tmp_path)
    supplies = _supplies(tmp_path, on_ac=True)
    proc = _run(tmp_path, supplies, "probe")
    assert proc.returncode == 0, proc.stderr
    assert "aspm_policy" in proc.stdout and "default" in proc.stdout
    assert "platform_profile           -" in proc.stdout
    proc = _run(tmp_path, supplies, "probe", "--json")
    payload = json.loads(proc.stdout)
    assert payload["gpu"]["card1_power_profile"] == "3D_FULL_SCREEN"
    assert payload["platform"]["platform_profile"] is None


# --- summarize: the figures, from samples shaped like the real laptop's ---


def _samples(
    seconds: float,
    power: typing.Callable[[float], float | None],
    energy: typing.Callable[[float], float | None],
    phase: typing.Callable[[float], str] = lambda t: "battery (auto), idle deep",
    every: float = 2.0,
) -> list[typing.Any]:
    count = int(seconds / every) + 1
    return [
        cli.Sample(
            t=i * every,
            power_w=power(i * every),
            energy_wh=energy(i * every),
            temp_c=50.0,
            phase=phase(i * every),
        )
        for i in range(count)
    ]


def _stepped(
    start_wh: float, watts: float, step_wh: float = 0.1
) -> typing.Callable[[float], float]:
    """A counter that only moves in whole steps, like the HP battery's."""
    return lambda t: math.ceil((start_wh - watts * t / 3600) / step_wh - 1e-9) * step_wh


def test_a_reading_that_never_moves_is_reported_stale() -> None:
    # 31 samples all at 6.76 W: what the laptop showed in one 60 s run.
    result = cli.summarize(_samples(60, lambda t: 6.76, lambda t: 30.0), 60.0)
    assert result["power_updates"] == 0
    assert result["power_reading_stale"] is True
    assert result["power_w"]["avg"] == 6.76


def test_a_reading_that_moves_is_not_stale() -> None:
    def power(t: float) -> float:
        return 6.6 + 0.2 * (int(t // 10) % 3)

    result = cli.summarize(_samples(300, power, _stepped(40.0, 6.8)), 300.0)
    assert result["power_updates"] >= 20
    assert result["power_reading_stale"] is False


def test_long_still_stretch_counts_as_stale() -> None:
    def power(t: float) -> float:
        return 7.0 if t < 200 else 6.5

    result = cli.summarize(_samples(300, power, _stepped(40.0, 6.8)), 300.0)
    assert result["power_updates"] == 1
    assert result["power_still_s"] == 200.0
    assert result["power_reading_stale"] is True


def test_energy_steps_give_the_right_rate_where_start_minus_end_does_not() -> None:
    watts = 6.8
    counter = _stepped(40.03, watts)
    samples = _samples(300, lambda t: watts, counter)
    # The naive figure: fall between first and last sample over the run.
    naive = (samples[0].energy_wh - samples[-1].energy_wh) * 3600 / 300
    result = cli.summarize(samples, 300.0)
    energy = result["energy_counter"]
    assert energy["steps"] >= 3
    assert energy["step_wh"] == pytest.approx(0.1)
    assert energy["rate_w"] == pytest.approx(watts, rel=0.1)
    assert energy["agrees"] is True
    # The coarse counter throws the naive figure well off on the same data.
    assert abs(naive - watts) > abs(energy["rate_w"] - watts)


def test_a_counter_that_disagrees_is_flagged_not_hidden() -> None:
    # The 300 s run: direct reading 6.8 W, energy counter implying 3.6 W.
    result = cli.summarize(_samples(300, lambda t: 6.8, _stepped(40.0, 3.6)), 300.0)
    energy = result["energy_counter"]
    assert energy["agrees"] is False
    assert energy["differs_by"] == pytest.approx(0.47, abs=0.06)


def test_too_few_counter_steps_give_no_cross_check() -> None:
    result = cli.summarize(_samples(60, lambda t: 7.0, _stepped(40.0, 7.0)), 60.0)
    assert result["energy_counter"]["rate_w"] is None
    assert result["energy_counter"]["agrees"] is None


def test_phases_count_only_fresh_readings() -> None:
    def phase(t: float) -> str:
        if t < 240:
            return "battery (auto), idle deep"
        if t < 274:
            return "battery (auto), idle soft"
        return "battery (auto), idle none"

    def power(t: float) -> float:
        # Firmware refreshes every 60 s: 6.9, 7.0, 6.8 W during deep idle,
        # then nothing fresh before the run ends.
        return {0: 7.5, 1: 6.9, 2: 7.0, 3: 6.8}[min(int(t // 60), 3)]

    result = cli.summarize(_samples(300, power, _stepped(40.0, 6.9), phase), 300.0)
    assert result["changed_during"] is True
    deep, soft, none = result["phases"]
    assert deep["phase"] == "battery (auto), idle deep"
    assert (deep["seconds"], deep["readings"]) == (240.0, 3)
    # The 7.5 W the run started with is minutes old and does not count.
    assert deep["power_w"] == pytest.approx(6.9)
    assert deep["energy_w"] == pytest.approx(6.9, rel=0.1)
    assert (soft["readings"], soft["power_w"]) == (0, None)
    assert (none["seconds"], none["readings"], none["power_w"]) == (26.0, 0, None)


def test_phase_report_says_too_few_readings(capsys: pytest.CaptureFixture[str]) -> None:
    def phase(t: float) -> str:
        return "battery (auto), idle soft" if t < 30 else "battery (auto), idle deep"

    def power(t: float) -> float:
        return 7.0 + 0.1 * (int(t // 20) % 2)

    result = cli.summarize(_samples(300, power, _stepped(40.0, 7.0), phase), 300.0)
    result.update(
        ended="complete",
        runtime={"full_h": None, "remaining_h": None},
    )
    cli.print_measurement(result)
    out = capsys.readouterr().out
    assert "idle soft" in out and "too few readings (1)" in out
    assert "idle deep" in out and "from 14 readings" in out


# --- PCIe ASPM: opt in only, and back to the boot policy ---------------------


def _aspm_param(
    tmp_path: Path, content: str = "[default] performance powersave powersupersave"
) -> Path:
    param = tmp_path / "policy"
    param.write_text(content + "\n", encoding="utf-8")
    return param


def test_aspm_default_without_a_record_writes_nothing(tmp_path: Path) -> None:
    param = _aspm_param(tmp_path)
    before = param.stat().st_mtime_ns
    state, warning = common.apply_pcie_aspm(param, "default", tmp_path / "record")
    assert (state, warning) == ("default", None)
    assert param.stat().st_mtime_ns == before
    assert not (tmp_path / "record").exists()


def test_aspm_opt_in_records_the_boot_policy_and_restores_it(tmp_path: Path) -> None:
    param = _aspm_param(tmp_path, "default performance [powersave] powersupersave")
    record = tmp_path / "record"
    assert common.apply_pcie_aspm(param, "powersupersave", record) == (
        "powersupersave",
        None,
    )
    assert param.read_text().strip() == "powersupersave"
    assert record.read_text().strip() == "powersave"
    # Asking again changes nothing and keeps the first record.
    assert common.apply_pcie_aspm(param, "powersupersave", record) == (
        "powersupersave",
        None,
    )
    assert record.read_text().strip() == "powersave"
    assert common.apply_pcie_aspm(param, "default", record) == ("powersave", None)
    assert param.read_text().strip() == "powersave"
    assert not record.exists()


def test_aspm_missing_or_refused_is_reported_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "no-such-policy"
    assert common.apply_pcie_aspm(missing, "powersupersave", tmp_path / "r") == (
        "unsupported",
        None,
    )
    param = _aspm_param(tmp_path)
    real_write = Path.write_text

    def refuse(self: Path, *args: typing.Any, **kwargs: typing.Any) -> int:
        if self == param:
            raise PermissionError(1, "Operation not permitted")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse)
    state, warning = common.apply_pcie_aspm(param, "powersupersave", tmp_path / "r")
    assert state == "failed"
    assert warning is not None and "refused" in warning


def test_probe_reports_link_states_and_power_source(tmp_path: Path) -> None:
    sysfs = _laptop_sysfs(tmp_path)
    nvme = sysfs / "bus" / "pci" / "devices" / "0000:01:00.0" / "link"
    for state, value in (("l1_aspm", "1"), ("l1_1_aspm", "1"), ("l1_2_aspm", "0")):
        _write(nvme / state, value)
    wifi = sysfs / "bus" / "pci" / "devices" / "0000:00:00.0" / "link"
    for state, value in (("l0s_aspm", "0"), ("l1_aspm", "1"), ("l1_2_aspm", "0")):
        _write(wifi / state, value)
    _write(sysfs / "class" / "power_supply" / "AC" / "type", "Mains")
    _write(sysfs / "class" / "power_supply" / "AC" / "online", "0")
    rows = {
        (group, name): value
        for group, name, value in common.power_inventory(sysfs, tmp_path / "none")
    }
    assert rows[("power", "source")] == "battery"
    assert rows[("pcie", "links_L1")] == "on for 2 of 2"
    assert rows[("pcie", "links_L1.2")] == "on for 0 of 2"
    assert rows[("pcie", "links_L0S")] == "on for 0 of 1"
    assert rows[("pcie", "links_L1.1")] == "on for 1 of 1"
