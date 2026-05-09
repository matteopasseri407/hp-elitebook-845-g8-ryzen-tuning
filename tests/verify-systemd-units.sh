#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

copy_host_unit() {
  local unit="$1"
  local unit_dir

  for unit_dir in /usr/lib/systemd/system /lib/systemd/system; do
    if [[ -e "$unit_dir/$unit" ]]; then
      install -D -m 0644 "$unit_dir/$unit" "$tmp/usr/lib/systemd/system/$unit"
      return 0
    fi
  done

  return 1
}

install -D -m 0755 src/elitebook-thermal-profile "$tmp/usr/local/sbin/elitebook-thermal-profile"
install -D -m 0755 src/elitebook-idle-watcher "$tmp/usr/local/sbin/elitebook-idle-watcher"
install -D -m 0755 src/elitebook-steam-game-watcher "$tmp/usr/local/sbin/elitebook-steam-game-watcher"
install -D -m 0755 src/elitebook-power-guard "$tmp/usr/local/sbin/elitebook-power-guard"
install -d -m 0755 "$tmp/etc/systemd/system" "$tmp/usr/lib/systemd/system"
cp systemd/*.service systemd/*.timer "$tmp/etc/systemd/system/"

for unit in sysinit.target basic.target multi-user.target timers.target tuned.service; do
  copy_host_unit "$unit" || true
done

systemd-analyze verify --root="$tmp" \
  "$tmp/etc/systemd/system/"*.service \
  "$tmp/etc/systemd/system/"*.timer
