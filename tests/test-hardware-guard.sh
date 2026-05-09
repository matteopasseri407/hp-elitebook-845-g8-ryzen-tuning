#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

make_fixture() {
  local cpu="$3"
  local product="$2"
  local root="$1"
  local vendor="$4"

  mkdir -p "$root/dmi"
  printf '%s\n' "$vendor" >"$root/dmi/sys_vendor"
  printf '%s\n' "$product" >"$root/dmi/product_name"
  printf 'model name\t: %s\n' "$cpu" >"$root/cpuinfo"
}

expect_success() {
  local cpu="$2"
  local product="$1"
  local root="$TMPDIR/success-$RANDOM"

  make_fixture "$root" "$product" "$cpu" HP
  ELITEBOOK_DMI_ID_DIR="$root/dmi" \
    ELITEBOOK_CPUINFO_PATH="$root/cpuinfo" \
    "$REPO_DIR/src/elitebook-thermal-profile" --check-hardware >/dev/null
}

expect_failure_contains() {
  local cpu="$2"
  local expected="$3"
  local product="$1"
  local root="$TMPDIR/failure-$RANDOM"

  make_fixture "$root" "$product" "$cpu" HP
  if ELITEBOOK_DMI_ID_DIR="$root/dmi" \
    ELITEBOOK_CPUINFO_PATH="$root/cpuinfo" \
    "$REPO_DIR/src/elitebook-thermal-profile" --check-hardware >"$root/out" 2>"$root/err"; then
    echo "Expected hardware guard failure for $product / $cpu" >&2
    exit 1
  fi

  grep -F "$expected" "$root/err" >/dev/null
}

expect_success "HP EliteBook 845 G8 Notebook PC" "AMD Ryzen 7 PRO 5850U with Radeon Graphics"
expect_success "HP EliteBook 835 G9 Notebook PC" "AMD Ryzen 5 PRO 5650U with Radeon Graphics"
expect_success "HP ProBook 455 G8 Notebook PC" "AMD Ryzen 7 PRO 5750U with Radeon Graphics"
expect_failure_contains \
  "HP EliteBook 845 G9 Notebook PC" \
  "AMD Ryzen 7 PRO 6850U with Radeon Graphics" \
  "Rembrandt hardware"
