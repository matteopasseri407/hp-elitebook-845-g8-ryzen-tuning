# SPDX-License-Identifier: GPL-3.0-or-later
"""``measure`` and ``probe``: the read-only tools for deciding what to tune.

Both run against fixture sysfs trees, so no battery and no root are needed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import elitebook_common as common  # noqa: E402

CLI = REPO_ROOT / "src" / "elitebook-thermal-profile"

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
    # Too short a window for the energy counter to mean anything.
    assert result["power_from_energy_w"] is None

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
