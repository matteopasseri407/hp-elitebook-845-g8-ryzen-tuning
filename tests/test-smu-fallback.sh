#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The README promises that when RyzenAdj is missing or blocked, the dispatcher
# still applies the kernel-level controls: EPP, boost, and the frequency cap.
# These tests hold it to that promise, and check that the state file says which
# of the two happened instead of claiming SMU limits that were never applied.
#
# Everything is redirected to fixtures, so nothing here touches the real CPU.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TMPDIR="$(mktemp -d)"

# The dispatcher runs as root and leaves root-owned state behind, so plain rm
# would fail and turn a passing run into a failing one.
cleanup() {
  rm -rf "$TMPDIR" 2>/dev/null && return 0
  if [[ "$EUID" -ne 0 ]]; then
    sudo -n rm -rf "$TMPDIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT

failures=0

fail() {
  echo "FAIL: $*" >&2
  failures=$((failures + 1))
}

# The dispatcher writes CPU policy, so it re-executes itself under sudo when
# not already root. Without a usable sudo there is nothing to test here.
if [[ "$EUID" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
  echo "SKIP: needs root or passwordless sudo to exercise the dispatcher"
  exit 0
fi

make_cpufreq_fixture() {
  local root="$1" policy

  mkdir -p "$root"
  printf '1\n' >"$root/boost"
  for policy in policy0 policy1; do
    mkdir -p "$root/$policy"
    printf '4500000\n' >"$root/$policy/cpuinfo_max_freq"
    printf '4500000\n' >"$root/$policy/scaling_max_freq"
    printf 'balance_performance\n' >"$root/$policy/energy_performance_preference"
  done
}

make_dmi_fixture() {
  local root="$1"

  mkdir -p "$root/dmi"
  printf 'HP\n' >"$root/dmi/sys_vendor"
  printf 'HP EliteBook 845 G8 Notebook PC\n' >"$root/dmi/product_name"
  printf 'model name\t: AMD Ryzen 7 PRO 5850U with Radeon Graphics\n' >"$root/cpuinfo"
}

# $1 scenario name, $2 ryzenadj path ("" for none), $3 lockdown file ("" for none)
run_dispatcher() {
  local scenario="$1" ryzenadj="$2" lockdown="$3" profile="${4:-cool}"
  local root="$TMPDIR/$scenario"
  local -a env_args

  make_cpufreq_fixture "$root/cpufreq"
  make_dmi_fixture "$root"

  env_args=(
    "ELITEBOOK_THERMAL_STATE_DIR=$root/state"
    "ELITEBOOK_CPUFREQ_DIR=$root/cpufreq"
    "ELITEBOOK_DMI_ID_DIR=$root/dmi"
    "ELITEBOOK_CPUINFO_PATH=$root/cpuinfo"
    "ELITEBOOK_POWER_SUPPLY_DIR=$root/power-supply"
    # Point the search at a directory that has no ryzenadj, so the degraded
    # path is reachable even on a machine where one is installed.
    "ELITEBOOK_RYZENADJ_SEARCH_PATHS=$root/emptybin/ryzenadj"
    "PATH=$root/emptybin:/usr/bin:/bin"
  )
  mkdir -p "$root/emptybin" "$root/power-supply"
  [[ -n "$ryzenadj" ]] && env_args+=("RYZENADJ=$ryzenadj")
  [[ -n "$lockdown" ]] && env_args+=("ELITEBOOK_LOCKDOWN_PATH=$lockdown")

  if [[ "$EUID" -eq 0 ]]; then
    env "${env_args[@]}" "$REPO_DIR/src/elitebook-thermal-profile" "$profile" \
      >"$root/out" 2>"$root/err" && echo 0 >"$root/rc" || echo $? >"$root/rc"
  else
    # The redirects are deliberately outside sudo: the transcripts belong to
    # the test user under TMPDIR, not to root.
    # shellcheck disable=SC2024
    sudo -n env "${env_args[@]}" "$REPO_DIR/src/elitebook-thermal-profile" "$profile" \
      >"$root/out" 2>"$root/err" && echo 0 >"$root/rc" || echo $? >"$root/rc"
  fi
}

state_value() {
  local scenario="$1" key="$2"
  awk -F= -v k="$key" '$1 == k {print $2; exit}' "$TMPDIR/$scenario/state/current" 2>/dev/null || true
}

# --- RyzenAdj absent -------------------------------------------------------
# The search path points at an empty directory and PATH carries no ryzenadj,
# so this reproduces a machine without RyzenAdj even when one is installed.
run_dispatcher absent "" ""
rc="$(cat "$TMPDIR/absent/rc")"

[[ "$rc" = "0" ]] ||
  fail "dispatcher exited $rc without RyzenAdj; it must degrade, not fail"
[[ -f "$TMPDIR/absent/state/current" ]] ||
  fail "no state file was written without RyzenAdj"
[[ "$(state_value absent smu)" = "unavailable" ]] ||
  fail "expected smu=unavailable, got '$(state_value absent smu)'"
[[ "$(state_value absent profile)" = "cool" ]] ||
  fail "expected the requested profile to be recorded"
grep -q "RyzenAdj not found" "$TMPDIR/absent/err" ||
  fail "no warning explained that RyzenAdj was missing"

# The promise being tested: CPU policy is applied anyway.
[[ "$(cat "$TMPDIR/absent/cpufreq/policy0/energy_performance_preference")" = "power" ]] ||
  fail "EPP was not applied without RyzenAdj (cool expects 'power')"
[[ "$(cat "$TMPDIR/absent/cpufreq/policy1/energy_performance_preference")" = "power" ]] ||
  fail "EPP was not applied to every policy without RyzenAdj"
[[ "$(cat "$TMPDIR/absent/cpufreq/boost")" = "1" ]] ||
  fail "boost was not applied without RyzenAdj (cool keeps boost on)"

# battery-saver is the profile that caps frequency; check the cap lands too.
run_dispatcher capped "" "" battery-saver
[[ "$(cat "$TMPDIR/capped/cpufreq/policy0/scaling_max_freq")" = "1800000" ]] ||
  fail "the battery-saver frequency cap was not applied without RyzenAdj"
[[ "$(cat "$TMPDIR/capped/cpufreq/boost")" = "0" ]] ||
  fail "battery-saver did not disable boost without RyzenAdj"

# --- RyzenAdj present but failing under lockdown ---------------------------
cat >"$TMPDIR/ryzenadj-failing" <<'EOF'
#!/bin/sh
echo "simulated SMU write failure" >&2
exit 1
EOF
chmod 0755 "$TMPDIR/ryzenadj-failing"

printf 'none [integrity] confidentiality\n' >"$TMPDIR/lockdown-integrity"
run_dispatcher blocked "$TMPDIR/ryzenadj-failing" "$TMPDIR/lockdown-integrity"

[[ "$(cat "$TMPDIR/blocked/rc")" = "0" ]] ||
  fail "dispatcher failed instead of degrading when SMU writes are blocked"
[[ "$(state_value blocked smu)" = "blocked" ]] ||
  fail "expected smu=blocked under kernel lockdown, got '$(state_value blocked smu)'"
grep -q "kernel lockdown is 'integrity'" "$TMPDIR/blocked/err" ||
  fail "the lockdown warning did not name the active lockdown mode"
grep -qi "secure boot" "$TMPDIR/blocked/err" ||
  fail "the lockdown warning did not mention Secure Boot, its usual cause"
[[ "$(cat "$TMPDIR/blocked/cpufreq/policy0/energy_performance_preference")" = "power" ]] ||
  fail "EPP was not applied when SMU writes are blocked"

# --- RyzenAdj present and failing with lockdown off ------------------------
printf '[none] integrity confidentiality\n' >"$TMPDIR/lockdown-none"
run_dispatcher failed "$TMPDIR/ryzenadj-failing" "$TMPDIR/lockdown-none"

[[ "$(cat "$TMPDIR/failed/rc")" = "0" ]] ||
  fail "dispatcher failed instead of degrading when RyzenAdj errored"
[[ "$(state_value failed smu)" = "failed" ]] ||
  fail "expected smu=failed with lockdown off, got '$(state_value failed smu)'"

# --- RyzenAdj present and working -----------------------------------------
cat >"$TMPDIR/ryzenadj-ok" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod 0755 "$TMPDIR/ryzenadj-ok"
run_dispatcher ok "$TMPDIR/ryzenadj-ok" "$TMPDIR/lockdown-none"

[[ "$(cat "$TMPDIR/ok/rc")" = "0" ]] ||
  fail "dispatcher failed on the healthy path"
[[ "$(state_value ok smu)" = "ok" ]] ||
  fail "expected smu=ok when RyzenAdj succeeds, got '$(state_value ok smu)'"

# --- A misconfigured RYZENADJ stays fatal ----------------------------------
# Degrading is for hardware and policy limits, not for a path the user typed
# wrong: that should be reported, not quietly ignored.
run_dispatcher misconfigured "$TMPDIR/does-not-exist" ""
[[ "$(cat "$TMPDIR/misconfigured/rc")" != "0" ]] ||
  fail "an unusable RYZENADJ path was accepted instead of reported"
grep -q "is not executable" "$TMPDIR/misconfigured/err" ||
  fail "no message explained the unusable RYZENADJ path"

if ((failures > 0)); then
  echo "$failures SMU fallback check(s) failed" >&2
  exit 1
fi

echo "SMU fallback checks passed"
