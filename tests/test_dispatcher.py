"""Tests for the Python dispatcher extras: status --json, idempotent sysfs
writes, and config warnings that name the offending line.

The shell suites cover the inherited bash contract; these cover what the
rewrite added. Like the shell suites they drive the real dispatcher against
fixture directories, so they need root or passwordless sudo.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = REPO_ROOT / "src" / "elitebook-thermal-profile"

NEEDS_ROOT = os.geteuid() != 0 and (
    shutil.which("sudo") is None
    or subprocess.run(
        ["sudo", "-n", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode
    != 0
)


def _write_fixture(root: Path) -> dict[str, str]:
    cpufreq = root / "cpufreq"
    cpufreq.mkdir(parents=True)
    (cpufreq / "boost").write_text("1\n", encoding="utf-8")
    for policy in ("policy0", "policy1"):
        policy_dir = cpufreq / policy
        policy_dir.mkdir()
        (policy_dir / "cpuinfo_max_freq").write_text("4500000\n", encoding="utf-8")
        (policy_dir / "scaling_max_freq").write_text("4500000\n", encoding="utf-8")
        (policy_dir / "energy_performance_preference").write_text(
            "balance_performance\n", encoding="utf-8"
        )
    dmi = root / "dmi"
    dmi.mkdir()
    (dmi / "sys_vendor").write_text("HP\n", encoding="utf-8")
    (dmi / "product_name").write_text(
        "HP EliteBook 845 G8 Notebook PC\n", encoding="utf-8"
    )
    cpuinfo = root / "cpuinfo"
    cpuinfo.write_text(
        "model name\t: AMD Ryzen 7 PRO 5850U with Radeon Graphics\n",
        encoding="utf-8",
    )
    ryzenadj = root / "ryzenadj"
    ryzenadj.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ryzenadj.chmod(0o755)
    (root / "power-supply").mkdir()
    (root / "emptybin").mkdir()
    return {
        "ELITEBOOK_THERMAL_STATE_DIR": str(root / "state"),
        "ELITEBOOK_CPUFREQ_DIR": str(cpufreq),
        "ELITEBOOK_DMI_ID_DIR": str(dmi),
        "ELITEBOOK_CPUINFO_PATH": str(cpuinfo),
        "ELITEBOOK_POWER_SUPPLY_DIR": str(root / "power-supply"),
        "ELITEBOOK_PROFILE_CONF": str(root / "absent.conf"),
        "ELITEBOOK_HWMON_DIR": str(root / "hwmon"),
        "RYZENADJ": str(ryzenadj),
        "PATH": f"{root / 'emptybin'}:/usr/bin:/bin",
    }


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [str(DISPATCHER), *args]
    full_env = dict(os.environ)
    full_env.update(env)
    if os.geteuid() == 0:
        return subprocess.run(
            cmd, env=full_env, capture_output=True, text=True, check=False
        )
    sudo_env = [
        f"{key}={value}"
        for key, value in full_env.items()
        if key.startswith(("ELITEBOOK_", "RYZENADJ", "PATH"))
    ]
    return subprocess.run(
        ["sudo", "-n", "env", *sudo_env, *cmd],
        capture_output=True,
        text=True,
        check=False,
    )


def _state_value(root: Path, key: str) -> str:
    for line in (root / "state" / "current").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


@unittest.skipIf(NEEDS_ROOT, "needs root or passwordless sudo")
class DispatcherExtrasTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.env = _write_fixture(self.root)

    def tearDown(self) -> None:
        # The dispatcher runs as root and leaves root-owned state behind.
        try:
            self._tmp.cleanup()
        except PermissionError:
            subprocess.run(
                ["sudo", "-n", "rm", "-rf", self._tmp.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    def _status_json(self) -> dict:
        proc = _run(self.env, "status", "--json")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return json.loads(proc.stdout)

    def test_status_json_reports_applied_profile(self) -> None:
        proc = _run(self.env, "cool")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

        payload = self._status_json()
        self.assertEqual(payload["profile"], "cool")
        self.assertEqual(payload["smu"], "ok")
        self.assertEqual(payload["power_mw"]["slow"], "12000")
        self.assertEqual(payload["tctl_c"], "85")
        self.assertIn("updated", payload)

    def test_status_json_without_state_is_still_json(self) -> None:
        proc = _run(self.env, "status", "--json")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("error", json.loads(proc.stdout))

    def test_reapply_does_not_rewrite_identical_sysfs(self) -> None:
        proc = _run(self.env, "cool")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

        watched = [
            self.root / "cpufreq" / "boost",
            self.root / "cpufreq" / "policy0" / "scaling_max_freq",
            self.root / "cpufreq" / "policy0" / "energy_performance_preference",
        ]
        before = [path.stat().st_mtime_ns for path in watched]

        proc = _run(self.env, "cool")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        after = [path.stat().st_mtime_ns for path in watched]

        self.assertEqual(before, after)
        self.assertEqual(_state_value(self.root, "profile"), "cool")

    def test_config_warning_names_the_line(self) -> None:
        conf = self.root / "profiles.conf"
        conf.write_text(
            "# user overrides\n# kept comment\nAC_SLOW_MW=95000\n",
            encoding="utf-8",
        )
        self.env["ELITEBOOK_PROFILE_CONF"] = str(conf)

        proc = _run(self.env, "ac")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("line 3", proc.stderr)
        self.assertIn("outside the safe range", proc.stderr)
        self.assertEqual(_state_value(self.root, "slow_mw"), "18000")


if __name__ == "__main__":
    unittest.main()
