#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

PREFLIGHT="$REPO_DIR/src/elitebook-hibernate-preflight"

write_config() {
  local path="$1"
  shift
  printf '%s\n' "$@" >"$path"
}

expect_check_config_ok() {
  local config="$1"

  ELITEBOOK_HIBERNATE_CONF="$config" "$PREFLIGHT" check-config 2>/dev/null
}

expect_check_config_failure_contains() {
  local config="$1"
  local expected="$2"
  local err="$TMPDIR/err-$RANDOM"

  if ELITEBOOK_HIBERNATE_CONF="$config" "$PREFLIGHT" check-config >/dev/null 2>"$err"; then
    echo "Expected check-config failure for $config" >&2
    exit 1
  fi

  grep -F "$expected" "$err" >/dev/null
}

config="$TMPDIR/valid.conf"
write_config "$config" \
  "SWAPFILE=/swap/hibernate.swap" \
  "RESUME_UUID=00000000-0000-0000-0000-000000000000" \
  "RESUME_OFFSET=12345" \
  "IMAGE_SIZE_BYTES=21474836480"
expect_check_config_ok "$config"

config="$TMPDIR/missing-key.conf"
write_config "$config" \
  "SWAPFILE=/swap/hibernate.swap" \
  "RESUME_UUID=00000000-0000-0000-0000-000000000000" \
  "IMAGE_SIZE_BYTES=21474836480"
expect_check_config_failure_contains "$config" "missing RESUME_OFFSET"

config="$TMPDIR/bad-offset.conf"
write_config "$config" \
  "SWAPFILE=/swap/hibernate.swap" \
  "RESUME_UUID=00000000-0000-0000-0000-000000000000" \
  "RESUME_OFFSET=not-a-number" \
  "IMAGE_SIZE_BYTES=21474836480"
expect_check_config_failure_contains "$config" "RESUME_OFFSET must be an integer"

config="$TMPDIR/relative-swapfile.conf"
write_config "$config" \
  "SWAPFILE=swap/hibernate.swap" \
  "RESUME_UUID=00000000-0000-0000-0000-000000000000" \
  "RESUME_OFFSET=12345" \
  "IMAGE_SIZE_BYTES=21474836480"
expect_check_config_failure_contains "$config" "SWAPFILE must be an absolute path"

if ELITEBOOK_HIBERNATE_CONF="$TMPDIR/does-not-exist.conf" "$PREFLIGHT" check-config >/dev/null 2>&1; then
  echo "Expected failure when the configuration file is missing" >&2
  exit 1
fi

if "$PREFLIGHT" bogus-mode >/dev/null 2>&1; then
  echo "Expected usage failure for an unknown mode" >&2
  exit 1
fi
