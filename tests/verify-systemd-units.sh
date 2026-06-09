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

write_stub_oneshot_unit() {
  local unit="$1"
  cat >"$tmp/usr/lib/systemd/system/$unit" <<'EOF'
[Unit]
Description=Hermetic stub for drop-in verification

[Service]
Type=oneshot
ExecStart=/usr/bin/true
EOF
}

install -D -m 0755 src/elitebook-thermal-profile "$tmp/usr/local/sbin/elitebook-thermal-profile"
install -D -m 0755 src/elitebook-idle-watcher "$tmp/usr/local/sbin/elitebook-idle-watcher"
install -D -m 0755 src/elitebook-steam-game-watcher "$tmp/usr/local/sbin/elitebook-steam-game-watcher"
install -D -m 0755 src/elitebook-power-guard "$tmp/usr/local/sbin/elitebook-power-guard"
install -D -m 0755 src/elitebook-hibernate-preflight "$tmp/usr/local/sbin/elitebook-hibernate-preflight"
install -d -m 0755 "$tmp/etc/systemd/system" "$tmp/usr/lib/systemd/system"
cp systemd/*.service systemd/*.timer "$tmp/etc/systemd/system/"
cp -a systemd/systemd-hibernate.service.d "$tmp/etc/systemd/system/"
cp -a systemd/systemd-suspend-then-hibernate.service.d "$tmp/etc/systemd/system/"

for unit in sysinit.target basic.target multi-user.target timers.target tuned.service; do
  copy_host_unit "$unit" || true
done

# Verify the hibernate preflight drop-ins against hermetic stub base units so
# the check does not depend on the host's sleep unit graph.
install -D -m 0755 /usr/bin/true "$tmp/usr/bin/true"
write_stub_oneshot_unit systemd-hibernate.service
write_stub_oneshot_unit systemd-suspend-then-hibernate.service

systemd-analyze verify --root="$tmp" \
  "$tmp/etc/systemd/system/"*.service \
  "$tmp/etc/systemd/system/"*.timer \
  "$tmp/usr/lib/systemd/system/systemd-hibernate.service" \
  "$tmp/usr/lib/systemd/system/systemd-suspend-then-hibernate.service"
