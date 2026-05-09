import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHER_PATH = REPO_ROOT / "src" / "elitebook-idle-watcher"
WATCHER_ENV_KEYS = (
    "ELITEBOOK_THERMAL_STATE_DIR",
    "ELITEBOOK_DISPATCHER_LOCK_TIMEOUT",
    "ELITEBOOK_IDLE_SAMPLE_INTERVAL",
    "ELITEBOOK_IDLE_SOFT_ENTER_SAMPLES",
    "ELITEBOOK_IDLE_DEEP_ENTER_SAMPLES",
    "ELITEBOOK_IDLE_ENTER_BUSY_PERCENT",
    "ELITEBOOK_IDLE_EXIT_BUSY_PERCENT",
    "ELITEBOOK_IDLE_ENTER_LOAD1",
    "ELITEBOOK_IDLE_EXIT_LOAD1",
)


def load_idle_watcher_with_state(state_dir: Path):
    previous_env = {key: os.environ.get(key) for key in WATCHER_ENV_KEYS}
    for key in WATCHER_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["ELITEBOOK_THERMAL_STATE_DIR"] = str(state_dir)

    module_name = f"elitebook_idle_watcher_test_{len(sys.modules)}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(WATCHER_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    for key, value in previous_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    return module


def load_idle_watcher():
    with tempfile.TemporaryDirectory() as tmp:
        return load_idle_watcher_with_state(Path(tmp))


def base_state(**overrides: str) -> dict[str, str]:
    state = {
        "profile": "battery",
        "source": "auto",
        "epp": "balance_power",
        "stapm_mw": "18000",
        "fast_mw": "30000",
        "slow_mw": "15000",
        "apu_mw": "15000",
        "tctl_c": "88",
        "boost": "on",
        "max_freq": "uncapped",
    }
    state.update(overrides)
    return state


class IdleWatcherOverlayTests(unittest.TestCase):
    def test_soft_idle_preserves_battery_saver_cap(self):
        watcher = load_idle_watcher()

        values, _ = watcher.overlay_values(
            base_state(
                profile="battery-saver",
                epp="power",
                boost="off",
                max_freq="1800000",
                slow_mw="8000",
                apu_mw="8000",
                tctl_c="80",
            ),
            "soft",
        )

        self.assertEqual(values["boost"], "off")
        self.assertEqual(values["max_freq"], "1800000")

    def test_soft_idle_uses_lower_numeric_cap(self):
        watcher = load_idle_watcher()
        watcher.SOFT_IDLE_MAX_FREQ_KHZ = "2200000"

        values, _ = watcher.overlay_values(base_state(max_freq="1800000"), "soft")

        self.assertEqual(values["max_freq"], "1800000")

    def test_soft_idle_keeps_uncapped_when_base_is_uncapped(self):
        watcher = load_idle_watcher()

        values, _ = watcher.overlay_values(base_state(max_freq="uncapped"), "soft")

        self.assertEqual(values["max_freq"], "uncapped")

    def test_deep_idle_does_not_raise_stricter_base_cap(self):
        watcher = load_idle_watcher()
        watcher.DEEP_IDLE_MAX_FREQ_KHZ = "1800000"

        values, _ = watcher.overlay_values(base_state(max_freq="1400000"), "deep")

        self.assertEqual(values["max_freq"], "1400000")

    def test_default_idle_thresholds_are_less_nervous(self):
        watcher = load_idle_watcher()

        self.assertEqual(watcher.ENTER_BUSY_PERCENT, 2.5)
        self.assertEqual(watcher.EXIT_BUSY_PERCENT, 8.0)
        self.assertEqual(watcher.SOFT_ENTER_SAMPLES, 5)

    def test_oscillating_interactive_load_does_not_enter_soft_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher = load_idle_watcher_with_state(Path(tmp))
            watcher.SAMPLE_INTERVAL = 0
            watcher.SOFT_ENTER_SAMPLES = 5
            watcher.time.sleep = lambda _seconds: None
            watcher.cpu_sample = lambda: (0, 0)
            watcher.load1 = lambda: 0.2

            applied: list[str] = []
            busy_values = iter([2.0, 3.2, 2.1, 3.1, 2.2, 3.0, 2.3, 3.3])
            watcher.cpu_busy_percent = lambda _previous, _current: next(busy_values)
            watcher.apply_idle_overlay = lambda _state, stage, _busy, _load1: (
                applied.append(stage) or True
            )

            watcher.PROFILE_STATE.write_text(
                "\n".join(f"{key}={value}" for key, value in base_state().items()),
                encoding="utf-8",
            )

            previous = (0, 0)
            idle_count = 0
            for _ in range(8):
                previous, idle_count = watcher.check_once(previous, idle_count)

            self.assertEqual(applied, [])
            self.assertEqual(idle_count, 0)


if __name__ == "__main__":
    unittest.main()
