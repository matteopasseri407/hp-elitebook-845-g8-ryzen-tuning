#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Compatibility shim. The installer became distribution aware in the Ubuntu
# port and now lives in install.sh; this name is kept so existing docs, issue
# templates and muscle memory keep working.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec "$SCRIPT_DIR/install.sh" "$@"
