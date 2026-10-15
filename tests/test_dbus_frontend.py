# SPDX-License-Identifier: GPL-3.0-or-later
"""The D-Bus front end and the GNOME indicator code that calls it.

The pure parts (request mapping, socket forwarding, ordering) run anywhere.
The end-to-end tests start a private bus, a stand-in polkit, the real daemon
against fixture sysfs trees, and the real front end, then switch profiles
through the indicator's own profileSwitcher.js under gjs. They need root,
because the daemon's control socket only answers root, plus PyGObject,
dbus-daemon and gjs; without them they are skipped.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import typing
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import elitebook_profiles as profiles  # noqa: E402

FRONT_END = REPO_ROOT / "src" / "elitebook-thermal-profile-dbus"
CLI = REPO_ROOT / "src" / "elitebook-thermal-profile"
SWITCHER = (
    REPO_ROOT
    / "gnome-extension"
    / "elitebook-thermal-profile@matteopasseri.github.io"
    / "profileSwitcher.js"
)
GJS_DRIVER = Path(__file__).resolve().parent / "gjs_switch_profile.js"
FAKE_POLKIT = Path(__file__).resolve().parent / "fake_polkit.py"


def _load_front_end() -> typing.Any:
    loader = importlib.machinery.SourceFileLoader("elitebook_dbus", str(FRONT_END))
    spec = importlib.util.spec_from_loader("elitebook_dbus", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


dbus_mod = _load_front_end()


# --- pure parts ------------------------------------------------------------


def test_profiles_match_the_daemon() -> None:
    assert dbus_mod.PROFILES == ("auto", *profiles.PROFILE_NAMES)


def test_requests_match_the_command_line() -> None:
    assert dbus_mod.daemon_request("auto") == {"cmd": "auto"}
    assert dbus_mod.daemon_request("cool") == {"cmd": "set", "profile": "cool"}


def test_unknown_profile_is_refused_before_anything_else() -> None:
    try:
        dbus_mod.daemon_request("turbo")
    except dbus_mod.Refused as exc:
        assert exc.name == "InvalidProfile"
        assert "turbo" in exc.message
    else:
        raise AssertionError("an unknown profile was accepted")


class _FakeDaemon:
    """Answers one connection on a Unix socket with a canned reply."""

    def __init__(self, path: Path, reply: bytes) -> None:
        self.request: bytes = b""
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(path))
        self._server.listen(1)
        self._reply = reply
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conn, _ = self._server.accept()
        with conn:
            while not self.request.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                self.request += chunk
            conn.sendall(self._reply)
        self._server.close()

    def join(self) -> None:
        self._thread.join(timeout=5)


def test_forward_returns_the_daemon_message(tmp_path: Path) -> None:
    path = tmp_path / "control"
    fake = _FakeDaemon(path, b'{"ok": true, "message": "applied"}\n')
    message = dbus_mod.forward({"cmd": "auto"}, path, timeout=5)
    fake.join()
    assert message == "applied"
    assert json.loads(fake.request) == {"cmd": "auto"}


def test_forward_reports_a_refusal(tmp_path: Path) -> None:
    path = tmp_path / "control"
    _FakeDaemon(path, b'{"ok": false, "message": "battery is low"}\n')
    try:
        dbus_mod.forward({"cmd": "set", "profile": "gaming"}, path, timeout=5)
    except dbus_mod.Refused as exc:
        assert (exc.name, exc.message) == ("Refused", "battery is low")
    else:
        raise AssertionError("a refusal was reported as success")


def test_forward_rejects_an_unreadable_reply(tmp_path: Path) -> None:
    path = tmp_path / "control"
    _FakeDaemon(path, b"not json\n")
    try:
        dbus_mod.forward({"cmd": "auto"}, path, timeout=5)
    except dbus_mod.Refused as exc:
        assert exc.name == "Failed"
    else:
        raise AssertionError("garbage was reported as success")


def test_forward_reports_a_stopped_daemon(tmp_path: Path) -> None:
    try:
        dbus_mod.forward({"cmd": "auto"}, tmp_path / "missing", timeout=5)
    except dbus_mod.Refused as exc:
        assert exc.name == "ServiceDown"
    else:
        raise AssertionError("a missing socket was reported as success")


def test_forwarder_keeps_order_and_reports_every_outcome() -> None:
    sent: list[dict[str, str]] = []
    outcomes: list[tuple[str, str]] = []
    finished = threading.Event()

    def send(request: dict[str, str]) -> str:
        time.sleep(0.05 if request.get("profile") == "gaming" else 0)
        sent.append(request)
        if request.get("profile") == "battery":
            raise dbus_mod.Refused("Refused", "battery is low")
        if request.get("profile") == "cool":
            raise RuntimeError("boom")
        return "ok"

    def deliver(func: typing.Callable[[], None]) -> None:
        func()
        if len(outcomes) == 4:
            finished.set()

    forwarder = dbus_mod.Forwarder(send, deliver)
    for profile in ("gaming", "auto", "battery", "cool"):
        forwarder.submit(
            profile,
            lambda message, p=profile: outcomes.append((p, message)),
            lambda refused, p=profile: outcomes.append((p, refused.name)),
        )
    assert finished.wait(5)
    assert [r.get("profile", r["cmd"]) for r in sent] == [
        "gaming",
        "auto",
        "battery",
        "cool",
    ]
    assert outcomes == [
        ("gaming", "ok"),
        ("auto", "ok"),
        ("battery", "Refused"),
        ("cool", "Failed"),
    ]


# --- end to end --------------------------------------------------------------


def _have_gi() -> bool:
    try:
        import gi  # type: ignore[import-untyped, import-not-found, unused-ignore]

        gi.require_version("Gio", "2.0")
        from gi.repository import (  # type: ignore[import-untyped, import-not-found, unused-ignore]  # noqa: F401
            Gio,
        )
    except (ImportError, ValueError):
        return False
    return True


SKIP_REASON = (
    "needs root"
    if os.geteuid() != 0
    else "needs PyGObject"
    if not _have_gi()
    else "needs dbus-daemon"
    if shutil.which("dbus-daemon") is None
    else "needs gjs"
    if shutil.which("gjs") is None
    else ""
)

# CI sets this in the job that installs everything, so the end-to-end tests
# fail there instead of being skipped without anyone noticing.
if SKIP_REASON and os.environ.get("ELITEBOOK_REQUIRE_DBUS_TESTS") == "1":
    raise RuntimeError(f"D-Bus end-to-end tests cannot run: {SKIP_REASON}")

BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:path={path}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow user="*"/>
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


def _write_fixture(root: Path) -> dict[str, str]:
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
    ryzenadj = root / "ryzenadj"
    ryzenadj.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ryzenadj.chmod(0o755)
    (root / "pci").mkdir()
    (root / "drm").mkdir()
    return {
        "ELITEBOOK_THERMAL_STATE_DIR": str(root / "state"),
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
        "ELITEBOOK_POWER_POLL_INTERVAL": "0.2",
        "RYZENADJ": str(ryzenadj),
        "PATH": "/usr/bin:/bin",
    }


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class EndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.procs: list[subprocess.Popen[str]] = []
        self.env = _write_fixture(self.root)
        self.state = Path(self.env["ELITEBOOK_THERMAL_STATE_DIR"])

        config = self.root / "bus.conf"
        config.write_text(BUS_CONFIG.format(path=self.root / "bus"), encoding="utf-8")
        bus = self._spawn(
            ["dbus-daemon", f"--config-file={config}", "--nofork", "--print-address=1"]
        )
        assert bus.stdout is not None
        self.address = bus.stdout.readline().strip()
        self.assertTrue(self.address, "dbus-daemon printed no address")

        self.polkit_answer = self.root / "polkit-answer"
        self.polkit_answer.write_text("yes\n", encoding="utf-8")
        self.polkit_log = self.root / "polkit.log"
        self.polkit_log.touch()
        self.polkit = self._spawn(
            [
                sys.executable,
                str(FAKE_POLKIT),
                self.address,
                str(self.polkit_answer),
                str(self.polkit_log),
            ]
        )
        assert self.polkit.stdout is not None
        self.assertEqual(self.polkit.stdout.readline().strip(), "ready")

        self.daemon = self._spawn([sys.executable, str(CLI), "daemon"], self.env)
        self._wait_for(lambda: (self.state / "current").exists(), "first apply")
        self.front_end = self._start_front_end()

    def tearDown(self) -> None:
        for proc in reversed(self.procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()
        self._tmp.cleanup()

    def _spawn(
        self, argv: list[str], env: dict[str, str] | None = None
    ) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, **(env or {})},
        )
        self.procs.append(proc)
        return proc

    def _start_front_end(self) -> subprocess.Popen[str]:
        proc = self._spawn(
            [sys.executable, str(FRONT_END)],
            {
                "ELITEBOOK_DBUS_ADDRESS": self.address,
                "ELITEBOOK_THERMAL_STATE_DIR": str(self.state),
            },
        )
        assert proc.stdout is not None
        line = proc.stdout.readline()
        self.assertIn("serving", line)
        return proc

    def _stop(self, proc: subprocess.Popen[str]) -> None:
        proc.terminate()
        proc.wait(timeout=10)

    def _wait_for(
        self, check: typing.Callable[[], bool], what: str, timeout: float = 10.0
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}")

    def _state(self) -> dict[str, str]:
        text = (self.state / "current").read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    def _switch(
        self, profile: str, pkexec: list[str] | None = None
    ) -> dict[str, typing.Any]:
        marker = self.root / "pkexec-ran"
        argv = pkexec or ["/bin/sh", "-c", f"touch {marker}; echo via-pkexec"]
        proc = subprocess.run(
            [
                "gjs",
                "-m",
                str(GJS_DRIVER),
                str(SWITCHER),
                self.address,
                profile,
                json.dumps(argv),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        result: dict[str, typing.Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return result

    def _pkexec_ran(self) -> bool:
        return (self.root / "pkexec-ran").exists()

    def _polkit_calls(self) -> list[dict[str, typing.Any]]:
        lines = self.polkit_log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    def _raw_call(self, profile: str, interactive: bool) -> tuple[str | None, str]:
        """SetProfile from Python; (D-Bus error name or None, message)."""
        import gi  # type: ignore[import-untyped, import-not-found, unused-ignore]

        gi.require_version("Gio", "2.0")
        from gi.repository import (  # type: ignore[import-untyped, import-not-found, unused-ignore]
            Gio,
            GLib,
        )

        connection = Gio.DBusConnection.new_for_address_sync(
            self.address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )
        flags = (
            Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION
            if interactive
            else Gio.DBusCallFlags.NONE
        )
        try:
            reply = connection.call_sync(
                dbus_mod.BUS_NAME,
                dbus_mod.OBJECT_PATH,
                dbus_mod.INTERFACE,
                "SetProfile",
                GLib.Variant("(s)", (profile,)),
                GLib.VariantType("(s)"),
                flags,
                30000,
                None,
            )
        except GLib.Error as exc:
            name = Gio.DBusError.get_remote_error(exc)
            Gio.DBusError.strip_remote_error(exc)
            return name, str(exc.message)
        finally:
            connection.close_sync(None)
        return None, str(reply.unpack()[0])

    def test_switches_profiles_without_pkexec(self) -> None:
        result = self._switch("cool")
        self.assertEqual(result["via"], "dbus")
        self.assertTrue(result["ok"], msg=result)
        self.assertIn("'cool' applied", result["message"])
        self.assertEqual(self._state()["profile"], "cool")
        self.assertEqual(self._state()["source"], "manual")

        result = self._switch("auto")
        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(self._state()["profile"], "ac")
        self.assertEqual(self._state()["source"], "auto")
        self.assertFalse(self._pkexec_ran())

        calls = self._polkit_calls()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call["action"], dbus_mod.POLKIT_ACTION)
            self.assertEqual(call["kind"], "system-bus-name")
            # The indicator lets polkit ask for a password when needed.
            self.assertEqual(call["flags"], 1)

    def test_a_refusal_from_polkit_is_final(self) -> None:
        self.polkit_answer.write_text("no\n", encoding="utf-8")
        result = self._switch("gaming")
        self.assertEqual(result, {**result, "ok": False, "via": "dbus"})
        self.assertIn("not authorized", result["message"])
        self.assertEqual(self._state()["profile"], "ac")
        self.assertFalse(self._pkexec_ran())

    def test_a_refusal_from_the_daemon_is_passed_on(self) -> None:
        (self.root / "power-supply" / "AC" / "online").write_text("0\n")
        (self.root / "power-supply" / "BAT0" / "capacity").write_text("10\n")
        self._wait_for(
            lambda: self._state()["profile"] == "battery-saver", "battery-saver"
        )
        result = self._switch("performance")
        self.assertEqual(result, {**result, "ok": False, "via": "dbus"})
        self.assertIn("battery-saver stays in force", result["message"])
        self.assertFalse(self._pkexec_ran())

    def test_falls_back_to_pkexec_without_the_front_end(self) -> None:
        self._stop(self.front_end)
        result = self._switch("cool")
        self.assertEqual(result, {"ok": True, "message": "via-pkexec", "via": "pkexec"})
        self.assertTrue(self._pkexec_ran())

    def test_pkexec_failure_is_reported(self) -> None:
        self._stop(self.front_end)
        result = self._switch("cool", ["/bin/sh", "-c", "echo denied >&2; exit 126"])
        self.assertEqual(result, {"ok": False, "message": "denied", "via": "pkexec"})

    def test_unknown_profile_never_reaches_polkit(self) -> None:
        name, message = self._raw_call("turbo", interactive=True)
        self.assertEqual(name, dbus_mod.ERROR_PREFIX + "InvalidProfile")
        self.assertIn("turbo", message)
        self.assertEqual(self._polkit_calls(), [])

    def test_non_interactive_callers_get_no_password_prompt(self) -> None:
        name, _ = self._raw_call("cool", interactive=False)
        self.assertIsNone(name)
        self.assertEqual(self._polkit_calls()[0]["flags"], 0)

    def test_a_stopped_daemon_is_reported(self) -> None:
        self._stop(self.daemon)
        name, message = self._raw_call("cool", interactive=True)
        self.assertEqual(name, dbus_mod.ERROR_PREFIX + "ServiceDown")
        self.assertIn("not running", message)

    def test_no_answer_from_polkit_is_not_a_yes(self) -> None:
        self._stop(self.polkit)
        name, _ = self._raw_call("cool", interactive=True)
        self.assertEqual(name, dbus_mod.ERROR_PREFIX + "NotAuthorized")
        self.assertEqual(self._state()["profile"], "ac")

    def test_quick_successive_clicks_apply_in_order(self) -> None:
        results: list[dict[str, typing.Any]] = []

        def switch(profile: str) -> None:
            results.append(self._switch(profile))

        first = threading.Thread(target=switch, args=("gaming",))
        first.start()
        # Let the first request reach the bus before the second.
        self._wait_for(lambda: len(self._polkit_calls()) >= 1, "first polkit check")
        switch("cool")
        first.join(timeout=60)
        self.assertTrue(all(r["ok"] for r in results), msg=results)
        self.assertEqual(self._state()["profile"], "cool")
