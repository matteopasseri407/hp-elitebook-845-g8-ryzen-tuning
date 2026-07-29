#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The version lives in three places: the dispatcher, the RPM spec, and the
# Debian changelog. A support request that starts with "which version are you
# running?" is only useful if they all agree, so this keeps them in step.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

failures=0

fail() {
  echo "FAIL: $*" >&2
  failures=$((failures + 1))
}

script_version="$(sed -n 's/^ELITEBOOK_VERSION="\(.*\)"$/\1/p' "$REPO_DIR/src/elitebook-thermal-profile")"
spec_version="$(sed -n 's/^Version:[[:space:]]*//p' "$REPO_DIR/packaging/rpm/elitebook-thermal-profile.spec" | head -n 1)"
deb_version="$(sed -n '1s/^elitebook-thermal-profile (\([^)]*\)).*/\1/p' "$REPO_DIR/packaging/debian/changelog")"
reported_version="$("$REPO_DIR/src/elitebook-thermal-profile" --version | awk '{print $2}')"

[[ -n "$script_version" ]] || fail "no ELITEBOOK_VERSION found in the dispatcher"
[[ -n "$spec_version" ]] || fail "no Version: found in the RPM spec"
[[ -n "$deb_version" ]] || fail "no version found in the Debian changelog"

[[ "$script_version" = "$spec_version" ]] ||
  fail "dispatcher says '$script_version', RPM spec says '$spec_version'"
[[ "$script_version" = "$deb_version" ]] ||
  fail "dispatcher says '$script_version', Debian changelog says '$deb_version'"
[[ "$script_version" = "$reported_version" ]] ||
  fail "--version prints '$reported_version', source says '$script_version'"

# --version must work without root and without supported hardware, because it
# is the first thing anyone is asked for in a bug report.
if ! ELITEBOOK_DMI_ID_DIR=/nonexistent ELITEBOOK_CPUINFO_PATH=/nonexistent \
  "$REPO_DIR/src/elitebook-thermal-profile" --version >/dev/null 2>&1; then
  fail "--version failed on unsupported hardware; it must always answer"
fi

if ((failures > 0)); then
  echo "$failures version consistency check(s) failed" >&2
  exit 1
fi

echo "version consistency checks passed ($script_version)"
