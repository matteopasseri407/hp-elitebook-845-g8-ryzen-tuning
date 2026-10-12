# SPDX-License-Identifier: GPL-3.0-or-later
"""The reconcile engine against a fake machine.

The point of the engine is that it writes only what changed, rewrites
everything on a schedule or after a resume, and keeps one consistent picture
of which profile is in force. These tests drive it with plain facts and a
recording fake, so no root and no sysfs are involved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import elitebook_engine as engine_mod  # noqa: E402
import elitebook_profiles as profiles  # noqa: E402


class FakeHardware:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.smu_result: tuple[str, str | None] = ("ok", None)

    def apply_tuned(self, tuned_profile: str) -> list[str]:
        self.calls.append(("tuned", tuned_profile))
        return []

    def apply_cpu(self, cpu: profiles.CpuPolicy) -> list[str]:
        self.calls.append(("cpu", cpu))
        return []

    def apply_smu(self, smu: profiles.SmuLimits) -> tuple[str, str | None]:
        self.calls.append(("smu", smu))
        return self.smu_result

    def apply_devices(self, runtime_pm: str, panel: int) -> tuple[str, list[str]]:
        self.calls.append(("devices", (runtime_pm, panel)))
        return str(panel), []

    def kinds(self) -> list[str]:
        kinds = [kind for kind, _ in self.calls]
        self.calls.clear()
        return kinds


class RecordingLog(engine_mod.Log):
    def __init__(self) -> None:
        super().__init__()
        self.infos: list[str] = []
        self.warnings: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def facts(
    now: float,
    on_ac: bool = False,
    battery: int | None = 80,
    busy: float = 50.0,
    game: bool = False,
    temp: int | None = 60,
) -> engine_mod.Facts:
    return engine_mod.Facts(
        now=now,
        on_ac=on_ac,
        battery_percent=battery,
        busy_percent=busy,
        load1=0.5,
        game_running=game,
        temperature_c=temp,
    )


Setup = tuple[engine_mod.Engine, FakeHardware, RecordingLog, Path]


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    hw = FakeHardware()
    log = RecordingLog()
    state = tmp_path / "state"
    files = engine_mod.StateFiles(state, log)
    conf = profiles.ProfileConfig.load(tmp_path / "absent.conf")
    eng = engine_mod.Engine(hw, files, log, conf, profiles.IdleSettings())
    return eng, hw, log, state


def state_of(state: Path, name: str = "current") -> dict[str, str]:
    return engine_mod.common.read_key_value_file(state / name)


def test_first_step_applies_everything_and_records_it(setup: Setup) -> None:
    eng, hw, log, state = setup
    eng.step(facts(0))
    assert hw.kinds() == ["tuned", "cpu", "smu", "devices"]
    current = state_of(state)
    assert current["profile"] == "battery"
    assert current["source"] == "auto"
    assert current["smu"] == "ok"
    assert current["slow_mw"] == "15000"
    assert current["panel_power_savings"] == "1"
    assert any("'battery' applied" in line for line in log.infos)


def test_identical_steps_write_nothing(setup: Setup) -> None:
    eng, hw, _, state = setup
    eng.step(facts(0))
    hw.kinds()
    before = (state / "current").stat().st_mtime_ns
    for second in range(1, 100):
        eng.step(facts(second, battery=80 - second // 10))
    assert hw.kinds() == []
    assert (state / "current").stat().st_mtime_ns == before


def test_thermal_record_keeps_building_while_the_battery_drains(setup: Setup) -> None:
    eng, _, _, state = setup
    for second in range(120):
        eng.step(facts(second, battery=90 - second // 20, temp=70 + second % 3))
    eng.thermal.write()
    thermal = state_of(state, "thermal")
    assert thermal["samples"] == "120"
    assert thermal["peak_c"] == "72"
    assert thermal["profile"] == "battery"


def test_threshold_crossing_switches_and_drops_a_manual_choice(setup: Setup) -> None:
    eng, hw, log, state = setup
    eng.set_manual("performance")
    eng.step(facts(0, battery=30))
    assert state_of(state)["profile"] == "performance"
    assert state_of(state, "override")["profile"] == "performance"
    hw.kinds()
    eng.step(facts(1, battery=20))
    assert state_of(state)["profile"] == "battery-saver"
    assert eng.manual is None
    assert not (state / "override").exists()
    assert "smu" in hw.kinds()
    assert any("low battery guard" in line for line in log.infos)


def test_any_profile_on_battery_keeps_the_battery_current_limit(setup: Setup) -> None:
    eng, hw, log, state = setup
    eng.set_manual("gaming")
    eng.step(facts(0, on_ac=True))
    smu = [arg for kind, arg in hw.calls if kind == "smu"][-1]
    assert smu.vrmmax_ma is None
    assert state_of(state)["vrmmax_ma"] == "stock"
    hw.kinds()
    eng.step(facts(1, on_ac=False))
    smu = [arg for kind, arg in hw.calls if kind == "smu"][-1]
    assert smu.vrmmax_ma == 45000
    assert smu.fast_mw == 30000
    assert state_of(state)["vrmmax_ma"] == "45000"
    assert any("held at 45 A" in line for line in log.infos)
    hw.kinds()
    eng.set_manual("cool")
    eng.step(facts(2, on_ac=False))
    smu = [arg for kind, arg in hw.calls if kind == "smu"][-1]
    assert smu.vrmmax_ma == 40000


def test_battery_saver_holds_until_the_battery_climbs_back(setup: Setup) -> None:
    eng, _, _, state = setup
    eng.step(facts(0, battery=20))
    assert state_of(state)["profile"] == "battery-saver"
    eng.step(facts(1, battery=21))
    eng.step(facts(2, battery=22))
    assert state_of(state)["profile"] == "battery-saver"
    eng.step(facts(3, battery=23))
    assert state_of(state)["profile"] == "battery"
    eng.step(facts(4, battery=21))
    assert state_of(state)["profile"] == "battery"


def test_base_change_during_an_overlay_rewrites_the_overlay_file(setup: Setup) -> None:
    eng, _, _, state = setup
    for second in range(31):
        eng.step(facts(second, busy=1.0))
    assert state_of(state, "idle-watcher")["base_profile"] == "battery"
    eng.step(facts(31, on_ac=True, busy=1.0))
    assert state_of(state, "idle-watcher")["base_profile"] == "ac"
    assert state_of(state, "idle-watcher")["stage"] == "deep"


def test_idle_overlay_writes_only_cpu_then_smu_and_leaves_current_alone(
    setup: Setup,
) -> None:
    eng, hw, _, state = setup
    eng.step(facts(0))
    hw.kinds()
    before = (state / "current").stat().st_mtime_ns
    for second in range(1, 5):
        eng.step(facts(second, busy=1.0))
    assert hw.kinds() == []
    eng.step(facts(5, busy=1.0))
    assert eng.stage == profiles.IDLE_SOFT
    assert hw.kinds() == []  # battery EPP already balance_power: nothing to move
    assert state_of(state, "idle-watcher")["stage"] == "soft"
    for second in range(6, 31):
        eng.step(facts(second, busy=1.0))
    assert eng.stage == profiles.IDLE_DEEP
    assert hw.kinds() == ["cpu", "smu"]
    assert state_of(state, "idle-watcher")["stage"] == "deep"
    eng.step(facts(31, busy=40.0))
    assert eng.stage == profiles.IDLE_NONE
    assert hw.kinds() == ["cpu", "smu"]
    assert not (state / "idle-watcher").exists()
    assert (state / "current").stat().st_mtime_ns == before


def test_reassert_rewrites_everything_hourly(setup: Setup) -> None:
    eng, hw, _, _ = setup
    eng.step(facts(0))
    hw.kinds()
    eng.step(facts(engine_mod.REASSERT_INTERVAL_S - 1))
    assert hw.kinds() == []
    eng.step(facts(engine_mod.REASSERT_INTERVAL_S))
    assert hw.kinds() == ["tuned", "cpu", "smu", "devices"]


def test_resume_reasserts_now_and_once_more_shortly_after(setup: Setup) -> None:
    eng, hw, _, _ = setup
    eng.step(facts(0))
    hw.kinds()
    eng.request_reassert(100.0, followup=True)
    eng.step(facts(100))
    assert "smu" in hw.kinds()
    eng.step(facts(105))
    assert hw.kinds() == []
    eng.step(facts(100 + engine_mod.RESUME_FOLLOWUP_S))
    assert "smu" in hw.kinds()
    eng.step(facts(120))
    assert hw.kinds() == []


def test_a_plain_reassert_keeps_the_resume_followup(setup: Setup) -> None:
    eng, hw, _, _ = setup
    eng.step(facts(0))
    eng.request_reassert(100.0, followup=True)
    eng.request_reassert(101.0)
    eng.step(facts(101))
    hw.kinds()
    eng.step(facts(100 + engine_mod.RESUME_FOLLOWUP_S))
    assert "smu" in hw.kinds()


def test_smu_failure_warns_once_and_retries(setup: Setup) -> None:
    eng, hw, log, state = setup
    hw.smu_result = ("failed", "RyzenAdj failed to apply SMU limits.")
    eng.step(facts(0))
    assert state_of(state)["smu"] == "failed"
    eng.step(facts(engine_mod.SMU_RETRY_S))
    assert log.warnings.count("RyzenAdj failed to apply SMU limits.") == 1
    hw.kinds()
    hw.smu_result = ("ok", None)
    eng.step(facts(2 * engine_mod.SMU_RETRY_S))
    assert hw.kinds() == ["smu"]
    assert state_of(state)["smu"] == "ok"


def test_unavailable_ryzenadj_is_not_retried(setup: Setup) -> None:
    eng, hw, _, _ = setup
    hw.smu_result = ("unavailable", "RyzenAdj not found")
    eng.step(facts(0))
    hw.kinds()
    eng.step(facts(engine_mod.SMU_RETRY_S + 1))
    assert hw.kinds() == []


def test_game_switches_to_gaming_without_idle_overlay(setup: Setup) -> None:
    eng, _, _, state = setup
    for second in range(40):
        eng.step(facts(second, on_ac=True, busy=1.0, game=True))
    assert state_of(state)["profile"] == "gaming"
    assert state_of(state)["source"] == "steam-game-watcher"
    assert eng.stage == profiles.IDLE_NONE
    eng.step(facts(41, on_ac=True, game=False))
    assert state_of(state)["profile"] == "ac"


def test_manual_choice_beats_a_game(setup: Setup) -> None:
    eng, _, _, state = setup
    eng.set_manual("cool")
    eng.step(facts(0, on_ac=True, game=True))
    assert state_of(state)["profile"] == "cool"
    assert state_of(state)["source"] == "manual"


def test_tuned_switch_is_followed_by_the_cpu_policy(setup: Setup) -> None:
    eng, hw, _, _ = setup
    eng.step(facts(0, battery=50))
    hw.kinds()
    eng.step(facts(1, battery=10))
    assert hw.kinds()[:2] == ["tuned", "cpu"]


def test_config_reload_applies_only_what_changed(setup: Setup, tmp_path: Path) -> None:
    eng, hw, _, state = setup
    eng.step(facts(0))
    hw.kinds()
    conf = tmp_path / "new.conf"
    conf.write_text("BATTERY_SLOW_MW=12000\n", encoding="utf-8")
    eng.set_config(profiles.ProfileConfig.load(conf))
    eng.step(facts(1))
    assert hw.kinds() == ["smu"]
    assert state_of(state)["slow_mw"] == "12000"


def test_thermal_record_restarts_only_on_a_new_base(setup: Setup) -> None:
    eng, _, _, _ = setup
    for second in range(10):
        eng.step(facts(second))
    assert eng.thermal.samples == 10
    eng.request_reassert(10.0)
    eng.step(facts(10))
    assert eng.thermal.samples == 11
    eng.step(facts(11, on_ac=True))
    assert eng.thermal.samples == 1
    assert eng.thermal.profile == "ac"


def test_leave_idle_puts_the_base_back(setup: Setup) -> None:
    eng, hw, _, state = setup
    for second in range(31):
        eng.step(facts(second, busy=1.0))
    assert eng.stage == profiles.IDLE_DEEP
    hw.kinds()
    eng.leave_idle()
    assert hw.kinds() == ["cpu", "smu"]
    assert not (state / "idle-watcher").exists()


def test_control_request_does_not_count_as_an_idle_sample(setup: Setup) -> None:
    eng, _, _, _ = setup
    for second in range(4):
        eng.step(facts(second, busy=1.0))
    for _ in range(10):
        eng.step(facts(4, busy=1.0), sample_idle=False)
    assert eng.stage == profiles.IDLE_NONE


def test_manual_gaming_request_drops_the_overlay_at_once(setup: Setup) -> None:
    eng, _, _, _ = setup
    for second in range(31):
        eng.step(facts(second, busy=1.0))
    eng.set_manual("gaming")
    eng.step(facts(31, busy=1.0), sample_idle=False)
    assert eng.stage == profiles.IDLE_NONE


# --- sensors -----------------------------------------------------------------


def test_game_detector_scans_on_its_own_schedule() -> None:
    scans: list[int] = []

    def scan() -> tuple[dict[str, str] | None, bool]:
        scans.append(1)
        return None, len(scans) > 1

    detector = engine_mod.GameDetector(
        interval_ac=30, interval_battery=120, interval_active=20, scan=scan
    )
    detector.poll(0, on_ac=False)
    detector.poll(119, on_ac=False)
    assert len(scans) == 1
    detector.poll(120, on_ac=False)
    detector.poll(139, on_ac=False)
    assert len(scans) == 2
    detector.poll(140, on_ac=False)
    assert len(scans) == 3
    assert engine_mod.GameDetector(enabled=False, scan=scan).poll(0, True) is None


def make_proc(root: Path, pid: int, ppid: int, comm: str, env: bytes = b"") -> None:
    entry = root / str(pid)
    entry.mkdir()
    (entry / "comm").write_text(comm + "\n", encoding="utf-8")
    (entry / "stat").write_text(f"{pid} ({comm}) S {ppid} 0 0\n", encoding="utf-8")
    (entry / "environ").write_bytes(env)


def test_find_steam_game(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    assert engine_mod.find_steam_game(proc) == (None, False)
    make_proc(proc, 100, 1, "steam")
    make_proc(proc, 150, 100, "pressure-vessel", b"SteamAppId=730\0")
    make_proc(proc, 200, 150, "bash", b"HOME=/x\0")
    assert engine_mod.find_steam_game(proc) == (None, True)
    make_proc(proc, 300, 200, "cs2", b"PATH=/bin\0SteamGameId=730\0")
    game, steam = engine_mod.find_steam_game(proc)
    assert steam is True
    assert game == {"pid": "300", "comm": "cs2", "appid": "730"}


def test_cpu_sampler(tmp_path: Path) -> None:
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 0 100 700 100 0 0 0 0 0\n", encoding="utf-8")
    sampler = engine_mod.CpuSampler(stat)
    stat.write_text("cpu  150 0 150 1500 100 0 0 0 0 0\n", encoding="utf-8")
    assert sampler.busy_percent() == pytest.approx(100 * 100 / 900)
    assert sampler.busy_percent() == 0.0


# --- RyzenAdj and the firmware's VRM limit -------------------------------------


def fake_ryzenadj(tmp_path: Path, info: str) -> Path:
    log = tmp_path / "calls"
    script = tmp_path / "ryzenadj"
    script.write_text(
        f'#!/bin/sh\necho "$@" >> {log}\n'
        f"[ \"$1\" = -i ] && printf '%s\\n' '{info}'\nexit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_read_stock_vrmmax(tmp_path: Path) -> None:
    script = fake_ryzenadj(
        tmp_path, "| EDC LIMIT VDD       |    90.000 | vrmmax-current |"
    )
    assert engine_mod.read_stock_vrmmax_ma(str(script)) == 90000
    other = tmp_path / "other"
    other.mkdir()
    silent = fake_ryzenadj(other, "| STAPM LIMIT | 15.000 | stapm-limit |")
    assert engine_mod.read_stock_vrmmax_ma(str(silent)) is None


def test_profile_without_vrm_limit_writes_the_stock_one_back(tmp_path: Path) -> None:
    script = fake_ryzenadj(tmp_path, "")
    hw = engine_mod.SysfsHardware(
        cpufreq_dir=tmp_path,
        pci_devices_dir=tmp_path,
        drm_dir=tmp_path,
        runtime_pm_defaults=tmp_path / "rpm",
        lockdown_path=tmp_path / "lockdown",
        ryzenadj=str(script),
        stock_vrmmax_ma=90000,
    )
    ac = profiles.target_for(
        profiles.BUILTIN_PROFILES["ac"], profiles.IDLE_NONE, profiles.IdleSettings()
    )
    battery = profiles.target_for(
        profiles.BUILTIN_PROFILES["battery"],
        profiles.IDLE_NONE,
        profiles.IdleSettings(),
    )
    assert hw.apply_smu(battery.smu) == ("ok", None)
    assert hw.apply_smu(ac.smu) == ("ok", None)
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    assert "--vrmmax-current=45000" in calls[0]
    assert "--vrmmax-current=90000" in calls[1]
