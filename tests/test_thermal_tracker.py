"""Tests for the thermal record kept by the idle watcher.

The profiles are open loop, so this record is the only evidence of whether a
profile is holding its thermal target. It has to reset when the profile
changes, count time above target honestly, and never take the watcher down
when a sensor or the filesystem misbehaves.
"""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHER_PATH = REPO_ROOT / "src" / "elitebook-idle-watcher"
ENV_KEYS = (
    "ELITEBOOK_THERMAL_STATE_DIR",
    "ELITEBOOK_HWMON_DIR",
    "ELITEBOOK_THERMAL_WRITE_SAMPLES",
)


def load_watcher(state_dir: Path, hwmon_dir: Path, write_samples: str = "1"):
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    os.environ["ELITEBOOK_THERMAL_STATE_DIR"] = str(state_dir)
    os.environ["ELITEBOOK_HWMON_DIR"] = str(hwmon_dir)
    os.environ["ELITEBOOK_THERMAL_WRITE_SAMPLES"] = write_samples
    try:
        loader = importlib.machinery.SourceFileLoader(
            "elitebook_idle_watcher_thermal", str(WATCHER_PATH)
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[loader.name] = module
        loader.exec_module(module)
        return module
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def make_hwmon(root: Path, name: str, millidegrees: int) -> None:
    sensor = root / "hwmon0"
    sensor.mkdir(parents=True, exist_ok=True)
    (sensor / "name").write_text(f"{name}\n", encoding="utf-8")
    (sensor / "temp1_input").write_text(f"{millidegrees}\n", encoding="utf-8")


def set_temperature(root: Path, millidegrees: int) -> None:
    (root / "hwmon0" / "temp1_input").write_text(f"{millidegrees}\n", encoding="utf-8")


def read_record(state_dir: Path) -> dict[str, str]:
    record: dict[str, str] = {}
    for line in (state_dir / "thermal").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            record[key] = value
    return record


class ThermalTrackerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir()
        self.hwmon = self.root / "hwmon"
        self.hwmon.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_zenpower_is_read_when_k10temp_is_absent(self) -> None:
        # The development machine runs zenpower and has no k10temp at all.
        make_hwmon(self.hwmon, "zenpower", 63250)
        watcher = load_watcher(self.state_dir, self.hwmon)
        self.assertEqual(watcher.cpu_temperature_c(), 63)

    def test_missing_sensor_reports_none_without_raising(self) -> None:
        watcher = load_watcher(self.state_dir, self.hwmon)
        self.assertIsNone(watcher.cpu_temperature_c())

    def test_peak_and_time_above_target(self) -> None:
        make_hwmon(self.hwmon, "k10temp", 70000)
        watcher = load_watcher(self.state_dir, self.hwmon)
        tracker = watcher.ThermalTracker()
        state = {"profile": "ac", "updated": "t0", "tctl_c": "90"}

        for millidegrees in (70000, 95000, 80000, 92000):
            set_temperature(self.hwmon, millidegrees)
            tracker.sample(state)

        record = read_record(self.state_dir)
        self.assertEqual(record["peak_c"], "95")
        self.assertEqual(record["samples"], "4")
        # 95 and 92 are above the 90 C target; 70 and 80 are not.
        self.assertEqual(record["over_target"], "2")
        self.assertEqual(record["target_c"], "90")
        self.assertEqual(record["profile"], "ac")

    def test_applying_a_new_profile_resets_the_record(self) -> None:
        make_hwmon(self.hwmon, "k10temp", 99000)
        watcher = load_watcher(self.state_dir, self.hwmon)
        tracker = watcher.ThermalTracker()

        tracker.sample({"profile": "ac", "updated": "t0", "tctl_c": "90"})
        self.assertEqual(read_record(self.state_dir)["peak_c"], "99")

        # A peak from the previous profile must not be attributed to the new
        # one, otherwise every profile inherits the worst moment of the day.
        set_temperature(self.hwmon, 70000)
        tracker.sample({"profile": "cool", "updated": "t1", "tctl_c": "85"})

        record = read_record(self.state_dir)
        self.assertEqual(record["peak_c"], "70")
        self.assertEqual(record["samples"], "1")
        self.assertEqual(record["over_target"], "0")
        self.assertEqual(record["target_c"], "85")
        self.assertEqual(record["profile"], "cool")

    def test_no_target_recorded_means_no_judgement(self) -> None:
        make_hwmon(self.hwmon, "k10temp", 99000)
        watcher = load_watcher(self.state_dir, self.hwmon)
        tracker = watcher.ThermalTracker()

        tracker.sample({"profile": "ac", "updated": "t0", "tctl_c": "0"})

        record = read_record(self.state_dir)
        self.assertEqual(record["peak_c"], "99")
        self.assertEqual(record["over_target"], "0")

    def test_unwritable_state_dir_does_not_kill_the_watcher(self) -> None:
        make_hwmon(self.hwmon, "k10temp", 70000)
        watcher = load_watcher(self.state_dir / "missing", self.hwmon)
        tracker = watcher.ThermalTracker()
        self.state_dir.chmod(0o500)
        try:
            tracker.sample({"profile": "ac", "updated": "t0", "tctl_c": "90"})
        finally:
            self.state_dir.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
