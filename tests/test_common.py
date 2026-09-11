# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_PATH = REPO_ROOT / "src" / "elitebook_common.py"

_spec = importlib.util.spec_from_file_location("elitebook_common", COMMON_PATH)
assert _spec is not None and _spec.loader is not None
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)


def make_cpufreq(root: Path, *, with_epp: bool = True) -> Path:
    cpufreq = root / "cpufreq"
    cpufreq.mkdir()
    (cpufreq / "boost").write_text("1\n", encoding="utf-8")
    for name in ("policy0", "policy1"):
        policy = cpufreq / name
        policy.mkdir()
        (policy / "cpuinfo_max_freq").write_text("4500000\n", encoding="utf-8")
        (policy / "scaling_max_freq").write_text("4500000\n", encoding="utf-8")
        if with_epp:
            (policy / "energy_performance_preference").write_text(
                "balance_performance\n", encoding="utf-8"
            )
    return cpufreq


def test_apply_writes_boost_epp_and_max_freq(tmp_path: Path) -> None:
    cpufreq = make_cpufreq(tmp_path)

    failures = common.apply_cpu_policy(cpufreq, "power", "off", "1800000")

    assert failures == []
    assert (cpufreq / "boost").read_text(encoding="utf-8").strip() == "0"
    for name in ("policy0", "policy1"):
        policy = cpufreq / name
        assert (policy / "scaling_max_freq").read_text(encoding="utf-8").strip() == (
            "1800000"
        )
        assert (policy / "energy_performance_preference").read_text(
            encoding="utf-8"
        ).strip() == "power"


def test_skip_unchanged_does_not_rewrite(tmp_path: Path) -> None:
    cpufreq = make_cpufreq(tmp_path)
    common.apply_cpu_policy(cpufreq, "power", "off", "1800000", skip_unchanged=True)
    watched = [
        cpufreq / "boost",
        cpufreq / "policy0" / "scaling_max_freq",
        cpufreq / "policy0" / "energy_performance_preference",
    ]
    before = [path.stat().st_mtime_ns for path in watched]

    failures = common.apply_cpu_policy(
        cpufreq, "power", "off", "1800000", skip_unchanged=True
    )

    assert failures == []
    assert [path.stat().st_mtime_ns for path in watched] == before


def test_uncapped_restores_cpuinfo_max(tmp_path: Path) -> None:
    cpufreq = make_cpufreq(tmp_path)
    (cpufreq / "policy0" / "scaling_max_freq").write_text("1800000\n", encoding="utf-8")

    failures = common.apply_cpu_policy(cpufreq, "balance_power", "on", "uncapped")

    assert failures == []
    assert (cpufreq / "policy0" / "scaling_max_freq").read_text(
        encoding="utf-8"
    ).strip() == "4500000"


def test_missing_epp_reports_failure(tmp_path: Path) -> None:
    cpufreq = make_cpufreq(tmp_path, with_epp=False)

    failures = common.apply_cpu_policy(cpufreq, "power", "off", "1800000")

    assert any("no cpufreq policy accepted EPP" in message for message in failures)


def test_unwritable_target_is_reported(tmp_path: Path) -> None:
    cpufreq = make_cpufreq(tmp_path)
    blocked = cpufreq / "policy0" / "scaling_max_freq"
    blocked.unlink()
    blocked.mkdir()

    failures = common.apply_cpu_policy(cpufreq, "power", "off", "1800000")

    assert any("rejected max freq 1800000" in message for message in failures)


def test_apply_smu_limits_reports_success_and_failure(tmp_path: Path) -> None:
    ok = tmp_path / "ryzenadj-ok"
    ok.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ok.chmod(0o755)
    bad = tmp_path / "ryzenadj-bad"
    bad.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    bad.chmod(0o755)

    assert common.apply_smu_limits(str(ok), "22000", "30000", "18000", "18000", "90")
    assert not common.apply_smu_limits(
        str(bad), "22000", "30000", "18000", "18000", "90"
    )
    assert not common.apply_smu_limits(
        str(tmp_path / "missing"), "22000", "30000", "18000", "18000", "90"
    )
