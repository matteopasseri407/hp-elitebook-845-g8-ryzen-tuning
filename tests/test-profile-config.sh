#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Profile overrides let a user change power limits without editing a file the
# package owns. Because those numbers decide how hard a laptop is allowed to
# run, a bad value must be refused rather than applied, and refusing it must
# leave the built-in default in place instead of leaving the machine untuned.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TMPDIR="$(mktemp -d)"

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

if [[ "$EUID" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
  echo "SKIP: needs root or passwordless sudo to exercise the dispatcher"
  exit 0
fi

# $1 scenario, $2 config file contents ("" for no file), $3 profile
run_with_config() {
  local scenario="$1" conf_body="$2" profile="$3"
  local root="$TMPDIR/$scenario" policy
  local -a env_args

  mkdir -p "$root/cpufreq" "$root/dmi" "$root/power-supply" "$root/emptybin"
  printf '1\n' >"$root/cpufreq/boost"
  for policy in policy0 policy1; do
    mkdir -p "$root/cpufreq/$policy"
    printf '4500000\n' >"$root/cpufreq/$policy/cpuinfo_max_freq"
    printf '4500000\n' >"$root/cpufreq/$policy/scaling_max_freq"
    printf 'balance_performance\n' >"$root/cpufreq/$policy/energy_performance_preference"
  done
  printf 'HP\n' >"$root/dmi/sys_vendor"
  printf 'HP EliteBook 845 G8 Notebook PC\n' >"$root/dmi/product_name"
  printf 'model name\t: AMD Ryzen 7 PRO 5850U with Radeon Graphics\n' >"$root/cpuinfo"

  printf '#!/bin/sh\nexit 0\n' >"$root/ryzenadj"
  chmod 0755 "$root/ryzenadj"

  env_args=(
    "ELITEBOOK_THERMAL_STATE_DIR=$root/state"
    "ELITEBOOK_CPUFREQ_DIR=$root/cpufreq"
    "ELITEBOOK_DMI_ID_DIR=$root/dmi"
    "ELITEBOOK_CPUINFO_PATH=$root/cpuinfo"
    "ELITEBOOK_POWER_SUPPLY_DIR=$root/power-supply"
    "RYZENADJ=$root/ryzenadj"
    "PATH=$root/emptybin:/usr/bin:/bin"
  )

  if [[ -n "$conf_body" ]]; then
    printf '%s\n' "$conf_body" >"$root/profiles.conf"
    env_args+=("ELITEBOOK_PROFILE_CONF=$root/profiles.conf")
  else
    env_args+=("ELITEBOOK_PROFILE_CONF=$root/absent.conf")
  fi

  if [[ "$EUID" -eq 0 ]]; then
    env "${env_args[@]}" "$REPO_DIR/src/elitebook-thermal-profile" "$profile" \
      >"$root/out" 2>"$root/err" && echo 0 >"$root/rc" || echo $? >"$root/rc"
  else
    # shellcheck disable=SC2024
    sudo -n env "${env_args[@]}" "$REPO_DIR/src/elitebook-thermal-profile" "$profile" \
      >"$root/out" 2>"$root/err" && echo 0 >"$root/rc" || echo $? >"$root/rc"
  fi
}

state_value() {
  local scenario="$1" key="$2"
  awk -F= -v k="$key" '$1 == k {print $2; exit}' "$TMPDIR/$scenario/state/current" 2>/dev/null || true
}

# --- baseline: no config file ----------------------------------------------
run_with_config baseline "" ac
[[ "$(cat "$TMPDIR/baseline/rc")" = "0" ]] ||
  fail "dispatcher failed with no configuration file present"
[[ "$(state_value baseline slow_mw)" = "18000" ]] ||
  fail "built-in ac sustained limit changed: got '$(state_value baseline slow_mw)'"

# --- a valid override is applied -------------------------------------------
run_with_config lowered "AC_SLOW_MW=15000
AC_APU_MW=15000
AC_EPP=power" ac
[[ "$(state_value lowered slow_mw)" = "15000" ]] ||
  fail "AC_SLOW_MW override was ignored: got '$(state_value lowered slow_mw)'"
[[ "$(state_value lowered apu_mw)" = "15000" ]] ||
  fail "AC_APU_MW override was ignored"
[[ "$(state_value lowered epp)" = "power" ]] ||
  fail "AC_EPP override was ignored: got '$(state_value lowered epp)'"
[[ "$(cat "$TMPDIR/lowered/cpufreq/policy0/energy_performance_preference")" = "power" ]] ||
  fail "the overridden EPP was recorded but never written to sysfs"
[[ "$(state_value lowered fast_mw)" = "30000" ]] ||
  fail "an unset key should keep its built-in value"

# --- comments and whitespace ------------------------------------------------
run_with_config tidy "# a comment
   AC_SLOW_MW = 16000   # trailing comment

" ac
[[ "$(state_value tidy slow_mw)" = "16000" ]] ||
  fail "comments or whitespace broke parsing: got '$(state_value tidy slow_mw)'"

# --- out-of-range values are refused ---------------------------------------
run_with_config toohigh "AC_SLOW_MW=95000" ac
[[ "$(state_value toohigh slow_mw)" = "18000" ]] ||
  fail "an out-of-range power limit was accepted: got '$(state_value toohigh slow_mw)'"
grep -q "outside the safe range" "$TMPDIR/toohigh/err" ||
  fail "no message explained the refused out-of-range value"
[[ "$(cat "$TMPDIR/toohigh/rc")" = "0" ]] ||
  fail "a bad config value must not stop the machine being tuned"

run_with_config toohot "COOL_TCTL_C=115" cool
[[ "$(state_value toohot tctl_c)" = "85" ]] ||
  fail "an out-of-range thermal target was accepted: got '$(state_value toohot tctl_c)'"

# --- non-numeric and invalid EPP -------------------------------------------
run_with_config garbage "AC_SLOW_MW=abc
AC_EPP=turbo" ac
[[ "$(state_value garbage slow_mw)" = "18000" ]] ||
  fail "a non-numeric power limit was accepted"
[[ "$(state_value garbage epp)" = "balance_power" ]] ||
  fail "an invalid EPP hint was accepted: got '$(state_value garbage epp)'"
grep -q "is not an integer" "$TMPDIR/garbage/err" ||
  fail "no message explained the non-numeric value"
grep -q "is not a valid EPP hint" "$TMPDIR/garbage/err" ||
  fail "no message explained the invalid EPP hint"

# --- overrides are per profile ---------------------------------------------
run_with_config scoped "COOL_SLOW_MW=9000" ac
[[ "$(state_value scoped slow_mw)" = "18000" ]] ||
  fail "a COOL_ override leaked into the ac profile"

run_with_config applied "COOL_SLOW_MW=9000" cool
[[ "$(state_value applied slow_mw)" = "9000" ]] ||
  fail "the COOL_ override was not applied to the cool profile"

# --- battery-saver maps to BATTERY_SAVER_ ----------------------------------
run_with_config saver "BATTERY_SAVER_TCTL_C=70" battery-saver
[[ "$(state_value saver tctl_c)" = "70" ]] ||
  fail "the battery-saver profile did not read BATTERY_SAVER_ keys"

# --- the shipped example parses as a no-op ---------------------------------
# Every line in it is commented out, so it must change nothing.
run_with_config example "$(cat "$REPO_DIR/config/profiles.conf.example")" ac
[[ "$(state_value example slow_mw)" = "18000" ]] ||
  fail "the shipped example file changes behaviour; it should be inert"
[[ -s "$TMPDIR/example/err" ]] &&
  fail "the shipped example produced warnings: $(cat "$TMPDIR/example/err")"

if ((failures > 0)); then
  echo "$failures profile configuration check(s) failed" >&2
  exit 1
fi

echo "profile configuration checks passed"
