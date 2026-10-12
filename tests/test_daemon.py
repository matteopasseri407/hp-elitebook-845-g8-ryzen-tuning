# SPDX-License-Identifier: GPL-3.0-or-later
"""End to end: the real daemon process against fixture sysfs trees.

Starts ``elitebook-thermal-profile daemon`` as root (the control socket only
answers root), drives it with the same CLI commands the GNOME extension and
the power guard use, and reads the state files they read. Nothing points at
real hardware: every sysfs path is a fixture directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "src" / "elitebook-thermal-profile"

NEEDS_ROOT = os.geteuid() != 0 and (
    shutil.which("sudo") is None
    or subprocess.run(
        ["sudo", "-n", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode
    != 0
)


def _as_root(env: dict[str, str], *args: str) -> list[str]:
    pairs = [f"{key}={value}" for key, value in env.items()]
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    return [*prefix, "env", *pairs, str(CLI), *args]


@unittest.skipIf(NEEDS_ROOT, "needs root or passwordless sudo")
class DaemonTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.root = root
        cpufreq = root / "cpufreq"
        cpufreq.mkdir()
        (cpufreq / "boost").write_text("1\n", encoding="utf-8")
        for name in ("policy0", "policy1"):
            policy = cpufreq / name
            policy.mkdir()
            (policy / "cpuinfo_max_freq").write_text("4500000\n", encoding="utf-8")
            (policy / "scaling_max_freq").write_text("4500000\n", encoding="utf-8")
            (policy / "energy_performance_preference").write_text(
                "balance_performance\n", encoding="utf-8"
            )
        dmi = root / "dmi"
        dmi.mkdir()
        (dmi / "sys_vendor").write_text("HP\n", encoding="utf-8")
        (dmi / "product_name").write_text("HP EliteBook 845 G8\n", encoding="utf-8")
        (root / "cpuinfo").write_text(
            "model name\t: AMD Ryzen 7 PRO 5850U with Radeon Graphics\n",
            encoding="utf-8",
        )
        supplies = root / "power-supply"
        (supplies / "AC").mkdir(parents=True)
        (supplies / "AC" / "type").write_text("Mains\n", encoding="utf-8")
        (supplies / "AC" / "online").write_text("1\n", encoding="utf-8")
        (supplies / "BAT0").mkdir()
        (supplies / "BAT0" / "type").write_text("Battery\n", encoding="utf-8")
        (supplies / "BAT0" / "capacity").write_text("80\n", encoding="utf-8")
        self.ryzenadj_log = root / "ryzenadj.log"
        ryzenadj = root / "ryzenadj"
        ryzenadj.write_text(
            f'#!/bin/sh\necho "$@" >> {self.ryzenadj_log}\nexit 0\n', encoding="utf-8"
        )
        ryzenadj.chmod(0o755)
        (root / "pci").mkdir()
        (root / "drm").mkdir()
        self.state = root / "state"
        self.env = {
            "ELITEBOOK_THERMAL_STATE_DIR": str(self.state),
            "ELITEBOOK_CPUFREQ_DIR": str(cpufreq),
            "ELITEBOOK_DMI_ID_DIR": str(dmi),
            "ELITEBOOK_CPUINFO_PATH": str(root / "cpuinfo"),
            "ELITEBOOK_POWER_SUPPLY_DIR": str(supplies),
            "ELITEBOOK_PROFILE_CONF": str(root / "profiles.conf"),
            "ELITEBOOK_HWMON_DIR": str(root / "hwmon"),
            "ELITEBOOK_PCI_DEVICES_DIR": str(root / "pci"),
            "ELITEBOOK_DRM_DIR": str(root / "drm"),
            "ELITEBOOK_LOCKDOWN_PATH": str(root / "lockdown"),
            "ELITEBOOK_IDLE_OVERLAY": "0",
            "ELITEBOOK_STEAM_DETECTION": "0",
            "ELITEBOOK_IDLE_SAMPLE_INTERVAL": "0.2",
            # Fixture power supplies send no kernel events: poll them instead.
            "ELITEBOOK_POWER_POLL_INTERVAL": "0.2",
            "RYZENADJ": str(ryzenadj),
            "PATH": "/usr/bin:/bin",
        }
        self.daemon = subprocess.Popen(
            _as_root(self.env, "daemon"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._wait_for(lambda: (self.state / "control").exists(), "control socket")

    def tearDown(self) -> None:
        if self.daemon.poll() is None:
            self._stop_daemon()
        if self.daemon.stdout is not None:
            self.daemon.stdout.close()
        try:
            self._tmp.cleanup()
        except PermissionError:
            subprocess.run(
                ["sudo", "-n", "rm", "-rf", self._tmp.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    def _stop_daemon(self) -> None:
        # The daemon runs as root under sudo; signal it through sudo too.
        subprocess.run(
            # Anchored so the pattern cannot match the sudo/pkill command
            # line that carries it.
            ["sudo", "-n", "pkill", "-TERM", "-f", f"^python3 {CLI} daemon$"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self.daemon.wait(timeout=10)

    def _wait_for(self, check, what: str, timeout: float = 10.0) -> None:  # type: ignore[no-untyped-def]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return
            if self.daemon.poll() is not None:
                output = self.daemon.stdout.read() if self.daemon.stdout else ""
                self.fail(f"daemon exited while waiting for {what}:\n{output}")
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}")

    def _cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            _as_root(self.env, *args), capture_output=True, text=True, check=False
        )

    def _state(self) -> dict[str, str]:
        text = (self.state / "current").read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    def _epp(self) -> str:
        path = self.root / "cpufreq" / "policy0" / "energy_performance_preference"
        return path.read_text(encoding="utf-8").strip()

    def test_manual_choice_auto_and_power_source_changes(self) -> None:
        self._wait_for(lambda: (self.state / "current").exists(), "first apply")
        self.assertEqual(self._state()["profile"], "ac")
        self.assertEqual(self._state()["source"], "auto")

        proc = self._cli("cool")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("'cool' applied", proc.stdout)
        self.assertEqual(self._state()["profile"], "cool")
        self.assertEqual(self._state()["source"], "manual")
        self.assertEqual(self._epp(), "power")

        # A manual choice survives the power source changing.
        (self.root / "power-supply" / "AC" / "online").write_text("0\n")
        time.sleep(1.0)
        self.assertEqual(self._state()["profile"], "cool")

        proc = self._cli("auto")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(self._state()["profile"], "battery")
        self.assertEqual(self._state()["source"], "auto")

        (self.root / "power-supply" / "AC" / "online").write_text("1\n")
        self._wait_for(lambda: self._state()["profile"] == "ac", "switch to ac")

    def test_low_battery_refuses_a_manual_profile(self) -> None:
        (self.root / "power-supply" / "AC" / "online").write_text("0\n")
        (self.root / "power-supply" / "BAT0" / "capacity").write_text("10\n")
        self._wait_for(
            lambda: (self.state / "current").exists()
            and self._state()["profile"] == "battery-saver",
            "battery-saver",
        )
        proc = self._cli("performance")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("battery-saver stays in force", proc.stderr)

    def _ryzenadj_writes(self) -> list[str]:
        # "-i" is the one-time read of the firmware's own limits at startup.
        if not self.ryzenadj_log.exists():
            return []
        lines = self.ryzenadj_log.read_text().splitlines()
        return [line for line in lines if line.strip() != "-i"]

    def test_unchanged_facts_do_not_rerun_ryzenadj(self) -> None:
        self._wait_for(lambda: self._ryzenadj_writes(), "first RyzenAdj write")
        time.sleep(1.5)  # about seven ticks at 0.2 s
        self.assertEqual(len(self._ryzenadj_writes()), 1, msg=self._ryzenadj_writes())
        proc = self._cli("reassert")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(len(self._ryzenadj_writes()), 2)

    def test_liveness_probes_leave_no_warnings(self) -> None:
        self._wait_for(lambda: (self.state / "current").exists(), "first apply")
        for _ in range(3):
            proc = self._cli("apply-once", "cool")
            self.assertIn("service is running", proc.stderr)
        self._stop_daemon()
        output = self.daemon.stdout.read() if self.daemon.stdout else ""
        self.assertNotIn("warning", output)

    def test_config_edit_is_picked_up_without_a_command(self) -> None:
        self._wait_for(lambda: (self.state / "current").exists(), "first apply")
        (self.root / "profiles.conf").write_text("AC_SLOW_MW=12000\n")
        self._wait_for(
            lambda: self._state()["slow_mw"] == "12000", "config reload", timeout=15
        )

    def test_status_apply_once_and_shutdown(self) -> None:
        self._wait_for(lambda: (self.state / "current").exists(), "first apply")
        status = subprocess.run(
            [str(CLI), "status", "--json"],
            env={**os.environ, **self.env},
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(status.stdout)
        self.assertEqual(payload["profile"], "ac")
        self.assertEqual(payload["idle_stage"], "none")

        proc = self._cli("apply-once", "cool")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("service is running", proc.stderr)

        self._stop_daemon()
        self.assertEqual(self.daemon.returncode, 0)
        self.assertFalse((self.state / "control").exists())
        proc = self._cli("cool")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("service is not running", proc.stderr)
