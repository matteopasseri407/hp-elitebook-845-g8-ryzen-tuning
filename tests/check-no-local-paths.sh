#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

home_pattern="/ho""me/"
vault_pattern="Knowledge""Vault"

if rg -n --hidden \
  -g '!.git' \
  -g '!tests/fixtures/**' \
  -g '!tests/__pycache__/**' \
  -e "$home_pattern" \
  -e "$vault_pattern" \
  .; then
  echo "Local machine path or private vault reference found." >&2
  exit 1
fi
