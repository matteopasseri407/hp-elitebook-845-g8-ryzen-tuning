#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The thermal record answers "is this profile actually holding?". It is only
# useful if it stays quiet about normal brief excursions and speaks up when a
# profile is being overrun for a meaningful share of the time.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

failures=0

fail() {
  echo "FAIL: $*" >&2
  failures=$((failures + 1))
}

# $1 scenario, $2 samples, $3 over_target, $4 target_c, $5 peak_c
make_record() {
  local root="$TMPDIR/$1"
  mkdir -p "$root"
  cat >"$root/thermal" <<EOF
profile=ac
profile_updated=t0
target_c=$4
peak_c=$5
peak_at=2026-07-29T19:10:00+0200
current_c=71
samples=$2
over_target=$3
updated=2026-07-29T19:10:00+0200
EOF
  printf 'profile=ac\nsource=system-auto\nepp=balance_power\nsmu=ok\nstapm_mw=22000\nfast_mw=30000\nslow_mw=18000\napu_mw=18000\ntctl_c=%s\nboost=on\nmax_freq=uncapped\nupdated=t0\n' "$4" >"$root/current"
  echo "$root"
}

run_guard() {
  local root="$1"
  ELITEBOOK_THERMAL_STATE_DIR="$root" \
    ELITEBOOK_THERMAL_PROFILE_BIN="$root/absent" \
    "$REPO_DIR/src/elitebook-power-guard" check 2>&1 || true
}

run_status() {
  local root="$1"
  ELITEBOOK_THERMAL_STATE_DIR="$root" \
    ELITEBOOK_DMI_ID_DIR="$root/absent-dmi" \
    "$REPO_DIR/src/elitebook-thermal-profile" status 2>&1 || true
}

# --- sustained overrun is reported -----------------------------------------
root="$(make_record overrun 3600 1400 90 97)"
output="$(run_guard "$root")"
grep -q "not holding its thermal target" <<<"$output" ||
  fail "the guard stayed silent while 38% of samples were above target"
grep -q "peak 97 C" <<<"$output" ||
  fail "the guard did not report the peak temperature"

# --- brief excursions are not reported -------------------------------------
root="$(make_record brief 3600 180 90 93)"
output="$(run_guard "$root")"
if grep -q "not holding its thermal target" <<<"$output"; then
  fail "the guard complained about 5% of samples above target, which is normal"
fi

# --- too few samples to judge ----------------------------------------------
root="$(make_record short 60 55 90 99)"
output="$(run_guard "$root")"
if grep -q "not holding its thermal target" <<<"$output"; then
  fail "the guard drew a conclusion from one minute of samples"
fi

# --- a record without a target is not judged -------------------------------
root="$(make_record notarget 3600 0 0 99)"
output="$(run_guard "$root")"
if grep -q "not holding its thermal target" <<<"$output"; then
  fail "the guard judged a record that has no thermal target"
fi

# --- status surfaces the record --------------------------------------------
root="$(make_record shown 3600 900 90 94)"
output="$(run_status "$root")"
grep -q "Peak:         94 C" <<<"$output" ||
  fail "status did not show the recorded peak: $output"
grep -q "Above target: 25% of 3600 samples" <<<"$output" ||
  fail "status did not show the share of time above target: $output"

# --- status without a record stays quiet -----------------------------------
root="$TMPDIR/norecord"
mkdir -p "$root"
printf 'profile=ac\nsource=manual\nepp=power\nsmu=ok\nslow_mw=18000\nfast_mw=30000\ntctl_c=90\nboost=on\nmax_freq=uncapped\nupdated=t0\n' >"$root/current"
output="$(run_status "$root")"
if grep -q "Peak:" <<<"$output"; then
  fail "status invented a peak with no thermal record present"
fi
grep -q "Profile:      ac" <<<"$output" ||
  fail "status stopped working when no thermal record exists"

if ((failures > 0)); then
  echo "$failures thermal report check(s) failed" >&2
  exit 1
fi

echo "thermal report checks passed"
