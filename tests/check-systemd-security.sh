#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

# systemd-analyze expects the exposure threshold in tenths.
threshold=35

for unit in systemd/*.service; do
  echo "Checking $unit"
  systemd-analyze security --offline=yes --threshold="$threshold" "$unit"
done
