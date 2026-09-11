# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PREFLIGHT = (
    Path(__file__).resolve().parent.parent / "src" / "elitebook-hibernate-preflight"
)


def run_preflight(
    args: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_usage_help() -> None:
    res = run_preflight(["-h"])
    assert res.returncode == 0
    assert "Usage: elitebook-hibernate-preflight" in res.stderr


def test_usage_unknown_mode() -> None:
    res = run_preflight(["bogus-mode"])
    assert res.returncode == 2
    assert "Usage: elitebook-hibernate-preflight" in res.stderr


def test_missing_config_file(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.conf"
    res = run_preflight(
        ["check-config"], env={"ELITEBOOK_HIBERNATE_CONF": str(missing)}
    )
    assert res.returncode == 1
    assert f"missing {missing}" in res.stderr


def test_check_config_valid(tmp_path: Path) -> None:
    conf = tmp_path / "hibernate.conf"
    conf.write_text(
        "SWAPFILE=/swap/hibernate.swap\n"
        "RESUME_UUID=00000000-0000-0000-0000-000000000000\n"
        "RESUME_OFFSET=12345\n"
        "IMAGE_SIZE_BYTES=21474836480\n",
        encoding="utf-8",
    )
    res = run_preflight(["check-config"], env={"ELITEBOOK_HIBERNATE_CONF": str(conf)})
    assert res.returncode == 0
    assert "ok config=" in res.stderr
    assert "swapfile=/swap/hibernate.swap" in res.stderr
    assert "offset=12345" in res.stderr


@pytest.mark.parametrize(
    ("content", "expected_err"),
    [
        (
            "SWAPFILE=/swap/hibernate.swap\nRESUME_UUID=abc\nIMAGE_SIZE_BYTES=100\n",
            "missing RESUME_OFFSET",
        ),
        (
            "RESUME_UUID=abc\nRESUME_OFFSET=123\nIMAGE_SIZE_BYTES=100\n",
            "missing SWAPFILE",
        ),
        (
            "SWAPFILE=relative/path.swap\nRESUME_UUID=abc\nRESUME_OFFSET=123\nIMAGE_SIZE_BYTES=100\n",
            "SWAPFILE must be an absolute path",
        ),
        (
            "SWAPFILE=/swap\nRESUME_UUID=abc\nRESUME_OFFSET=not-an-int\nIMAGE_SIZE_BYTES=100\n",
            "RESUME_OFFSET must be an integer",
        ),
        (
            "SWAPFILE=/swap\nRESUME_UUID=abc\nRESUME_OFFSET=123\nIMAGE_SIZE_BYTES=bad\n",
            "IMAGE_SIZE_BYTES must be an integer",
        ),
    ],
)
def test_check_config_invalid(tmp_path: Path, content: str, expected_err: str) -> None:
    conf = tmp_path / "bad.conf"
    conf.write_text(content, encoding="utf-8")
    res = run_preflight(["check-config"], env={"ELITEBOOK_HIBERNATE_CONF": str(conf)})
    assert res.returncode == 1
    assert expected_err in res.stderr
