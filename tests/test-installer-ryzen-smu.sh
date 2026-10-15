#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The installer skips its kernel lockdown warning when a ryzen_smu module that
# RyzenAdj accepts is loaded. RyzenAdj's own test is a 0.1 series version with
# a patch level of 6 or more; anything looser would silence the warning on a
# machine where RyzenAdj still falls back to /dev/mem.
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

# The installer runs top to bottom, so take just the two functions involved.
# shellcheck source=/dev/null
source <(sed -n '/^read_trimmed()/,/^}/p;/^ryzen_smu_module_ready()/,/^}/p' \
  "$REPO_DIR/scripts/install.sh")
declare -F ryzen_smu_module_ready >/dev/null || {
  echo "FAIL: ryzen_smu_module_ready not found in scripts/install.sh" >&2
  exit 1
}

export ELITEBOOK_RYZEN_SMU_DIR="$TMPDIR"

if ryzen_smu_module_ready; then
  fail "a missing module counted as loaded"
fi

for version in 0.1.6 0.1.7 0.1.10; do
  printf '%s\n' "$version" >"$TMPDIR/drv_version"
  ryzen_smu_module_ready || fail "version $version was not accepted"
done

for version in 0.1.5 0.2.0 1.1.7 "" garbage 0.1.7-rc1; do
  printf '%s\n' "$version" >"$TMPDIR/drv_version"
  if ryzen_smu_module_ready; then
    fail "version '$version' was accepted, but RyzenAdj would not use it"
  fi
done

if ((failures > 0)); then
  echo "$failures ryzen_smu installer check(s) failed" >&2
  exit 1
fi
echo "ryzen_smu installer checks passed"
