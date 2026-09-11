# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / "src" / "elitebook-power-guard"


def run_guard(
    args: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_usage_help() -> None:
    res = run_guard(["-h"])
    assert res.returncode == 0
    assert "Usage: elitebook-power-guard" in res.stderr


def test_usage_unknown_mode() -> None:
    res = run_guard(["bogus-mode"])
    assert res.returncode == 2
    assert "Usage: elitebook-power-guard" in res.stderr


def test_thermal_headroom_overrun(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    thermal = "samples=3600\n" "over_target=1400\n" "target_c=90\n" "peak_c=97\n"
    (state_dir / "thermal").write_text(thermal, encoding="utf-8")
    (state_dir / "current").write_text("smu=ok\n", encoding="utf-8")

    res = run_guard(
        ["check"],
        env={
            "ELITEBOOK_THERMAL_STATE_DIR": str(state_dir),
            "ELITEBOOK_THERMAL_PROFILE_BIN": str(tmp_path / "absent"),
        },
    )
    combined = res.stdout + res.stderr
    assert "not holding its thermal target" in combined
    assert "peak 97 C" in combined


def test_thermal_headroom_brief_excursions(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    thermal = "samples=3600\n" "over_target=180\n" "target_c=90\n" "peak_c=93\n"
    (state_dir / "thermal").write_text(thermal, encoding="utf-8")
    (state_dir / "current").write_text("smu=ok\n", encoding="utf-8")

    res = run_guard(
        ["check"],
        env={
            "ELITEBOOK_THERMAL_STATE_DIR": str(state_dir),
            "ELITEBOOK_THERMAL_PROFILE_BIN": str(tmp_path / "absent"),
        },
    )
    combined = res.stdout + res.stderr
    assert "not holding its thermal target" not in combined


def test_thermal_headroom_too_few_samples(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    thermal = "samples=60\n" "over_target=55\n" "target_c=90\n" "peak_c=99\n"
    (state_dir / "thermal").write_text(thermal, encoding="utf-8")
    (state_dir / "current").write_text("smu=ok\n", encoding="utf-8")

    res = run_guard(
        ["check"],
        env={
            "ELITEBOOK_THERMAL_STATE_DIR": str(state_dir),
            "ELITEBOOK_THERMAL_PROFILE_BIN": str(tmp_path / "absent"),
        },
    )
    combined = res.stdout + res.stderr
    assert "not holding its thermal target" not in combined


def test_thermal_headroom_zero_target(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    thermal = "samples=3600\n" "over_target=0\n" "target_c=0\n" "peak_c=99\n"
    (state_dir / "thermal").write_text(thermal, encoding="utf-8")
    (state_dir / "current").write_text("smu=ok\n", encoding="utf-8")

    res = run_guard(
        ["check"],
        env={
            "ELITEBOOK_THERMAL_STATE_DIR": str(state_dir),
            "ELITEBOOK_THERMAL_PROFILE_BIN": str(tmp_path / "absent"),
        },
    )
    combined = res.stdout + res.stderr
    assert "not holding its thermal target" not in combined


@pytest.mark.parametrize(
    ("smu_state", "expected_msg"),
    [
        (
            "unavailable",
            "SMU limits are not being applied: RyzenAdj is not installed",
        ),
        (
            "blocked",
            "SMU limits are blocked by kernel lockdown",
        ),
        (
            "failed",
            "RyzenAdj ran but failed to apply SMU limits",
        ),
    ],
)
def test_smu_state_warnings(tmp_path: Path, smu_state: str, expected_msg: str) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "current").write_text(f"smu={smu_state}\n", encoding="utf-8")

    res = run_guard(
        ["check"],
        env={
            "ELITEBOOK_THERMAL_STATE_DIR": str(state_dir),
            "ELITEBOOK_THERMAL_PROFILE_BIN": str(tmp_path / "absent"),
        },
    )
    combined = res.stdout + res.stderr
    assert expected_msg in combined


def test_guard_state_file_written(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "current").write_text("smu=ok\n", encoding="utf-8")

    res = run_guard(
        ["check"],
        env={
            "ELITEBOOK_THERMAL_STATE_DIR": str(state_dir),
            "ELITEBOOK_THERMAL_PROFILE_BIN": str(tmp_path / "absent"),
        },
    )
    assert res.returncode in (0, 1)
    guard_file = state_dir / "guard"
    assert guard_file.is_file()
    content = guard_file.read_text(encoding="utf-8")
    assert "mode=check" in content
    assert "status=" in content
    assert "updated=" in content
    assert "details=" in content
