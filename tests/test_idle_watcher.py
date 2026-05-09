import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHER_PATH = REPO_ROOT / "src" / "elitebook-idle-watcher"


def load_idle_watcher():
    previous_state_dir = os.environ.get("ELITEBOOK_THERMAL_STATE_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ELITEBOOK_THERMAL_STATE_DIR"] = tmp
        module_name = f"elitebook_idle_watcher_test_{len(sys.modules)}"
        loader = importlib.machinery.SourceFileLoader(module_name, str(WATCHER_PATH))
        spec = importlib.util.spec_from_loader(module_name, loader)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

    if previous_state_dir is None:
        os.environ.pop("ELITEBOOK_THERMAL_STATE_DIR", None)
    else:
        os.environ["ELITEBOOK_THERMAL_STATE_DIR"] = previous_state_dir

    return module


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


if __name__ == "__main__":
    unittest.main()
