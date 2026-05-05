import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHER_PATH = REPO_ROOT / "src" / "elitebook-steam-game-watcher"


def load_watcher(power_supply_dir: Path):
    previous_power_dir = os.environ.get("ELITEBOOK_POWER_SUPPLY_DIR")
    os.environ["ELITEBOOK_POWER_SUPPLY_DIR"] = str(power_supply_dir)

    module_name = f"elitebook_steam_game_watcher_test_{len(sys.modules)}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(WATCHER_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    if previous_power_dir is None:
        os.environ.pop("ELITEBOOK_POWER_SUPPLY_DIR", None)
    else:
        os.environ["ELITEBOOK_POWER_SUPPLY_DIR"] = previous_power_dir

    return module


def write_supply(root: Path, name: str, supply_type: str, **values: str) -> None:
    supply = root / name
    supply.mkdir(parents=True)
    (supply / "type").write_text(f"{supply_type}\n", encoding="utf-8")
    for key, value in values.items():
        (supply / key).write_text(f"{value}\n", encoding="utf-8")


class SteamGameWatcherPowerSupplyTests(unittest.TestCase):
    def test_ac_path_is_used_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            power_supply_dir = Path(tmp)
            write_supply(power_supply_dir, "AC", "Mains", online="1")
            watcher = load_watcher(power_supply_dir)

            self.assertTrue(watcher.on_ac_power())

    def test_mains_fallback_handles_non_ac_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            power_supply_dir = Path(tmp)
            write_supply(power_supply_dir, "ADP1", "Mains", online="0")
            watcher = load_watcher(power_supply_dir)

            self.assertFalse(watcher.on_ac_power())

    def test_battery_low_uses_mains_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            power_supply_dir = Path(tmp)
            write_supply(power_supply_dir, "ADP1", "Mains", online="0")
            write_supply(power_supply_dir, "BAT0", "Battery", capacity="20")
            watcher = load_watcher(power_supply_dir)

            self.assertTrue(watcher.battery_is_low())

    def test_missing_power_supply_defaults_to_ac(self):
        with tempfile.TemporaryDirectory() as tmp:
            power_supply_dir = Path(tmp) / "missing"
            watcher = load_watcher(power_supply_dir)

            self.assertTrue(watcher.on_ac_power())


if __name__ == "__main__":
    unittest.main()
