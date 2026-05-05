#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WITH_GNOME_EXTENSION=0
EXTENSION_UUID="elitebook-thermal-profile@matteopasseri.github.io"

usage() {
  cat >&2 <<'EOF'
Usage: sudo ./scripts/install-fedora.sh [--with-gnome-extension]

Installs:
  /usr/local/sbin/elitebook-thermal-profile
  /usr/local/sbin/elitebook-steam-game-watcher
  /etc/systemd/system/elitebook-thermal-profile.service
  /etc/systemd/system/elitebook-steam-game-watcher.service
  /etc/udev/rules.d/90-elitebook-thermal-profile.rules
  /etc/systemd/system-sleep/elitebook-thermal-profile
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-gnome-extension)
      WITH_GNOME_EXTENSION=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

have_ryzenadj=0
for candidate in /usr/local/sbin/ryzenadj /usr/local/bin/ryzenadj /usr/bin/ryzenadj; do
  if [[ -x "$candidate" ]]; then
    have_ryzenadj=1
    break
  fi
done

if [[ "$have_ryzenadj" -ne 1 ]] && ! command -v ryzenadj >/dev/null 2>&1; then
  echo "RyzenAdj was not found. Install RyzenAdj before using these profiles." >&2
  echo "Upstream: https://github.com/FlyGoat/RyzenAdj" >&2
  exit 1
fi

"$REPO_DIR/src/elitebook-thermal-profile" --check-hardware >/dev/null

install -D -m 0755 "$REPO_DIR/src/elitebook-thermal-profile" /usr/local/sbin/elitebook-thermal-profile
install -D -m 0755 "$REPO_DIR/src/elitebook-steam-game-watcher" /usr/local/sbin/elitebook-steam-game-watcher
install -D -m 0644 "$REPO_DIR/systemd/elitebook-thermal-profile.service" /etc/systemd/system/elitebook-thermal-profile.service
install -D -m 0644 "$REPO_DIR/systemd/elitebook-steam-game-watcher.service" /etc/systemd/system/elitebook-steam-game-watcher.service
install -D -m 0644 "$REPO_DIR/udev/90-elitebook-thermal-profile.rules" /etc/udev/rules.d/90-elitebook-thermal-profile.rules
install -D -m 0755 "$REPO_DIR/system-sleep/elitebook-thermal-profile" /etc/systemd/system-sleep/elitebook-thermal-profile

if [[ "$WITH_GNOME_EXTENSION" -eq 1 ]]; then
  target_user="${SUDO_USER:-}"
  if [[ -z "$target_user" || "$target_user" = "root" ]]; then
    echo "Cannot infer the desktop user for the GNOME extension. Run with sudo from your user session." >&2
    exit 1
  fi

  target_home="$(getent passwd "$target_user" | cut -d: -f6)"
  target_group="$(id -gn "$target_user")"
  extension_src="$REPO_DIR/gnome-extension/$EXTENSION_UUID"
  extension_dest="$target_home/.local/share/gnome-shell/extensions/$EXTENSION_UUID"

  install -d -m 0755 "$extension_dest/icons"
  install -m 0644 "$extension_src/metadata.json" "$extension_dest/metadata.json"
  install -m 0644 "$extension_src/stylesheet.css" "$extension_dest/stylesheet.css"
  install -m 0644 "$extension_src/extension.js" "$extension_dest/extension.js"
  install -m 0644 "$extension_src"/icons/*.svg "$extension_dest/icons/"
  chown -R "$target_user:$target_group" "$extension_dest"
fi

systemctl daemon-reload
udevadm control --reload-rules
systemctl enable --now elitebook-thermal-profile.service
systemctl enable --now elitebook-steam-game-watcher.service

echo "Installed HP EliteBook 845 G8 Ryzen thermal profiles."
echo "Current state:"
cat /run/elitebook-thermal-profile/current 2>/dev/null || true

if [[ "$WITH_GNOME_EXTENSION" -eq 1 ]]; then
  echo "GNOME extension installed. Enable it with:"
  echo "  gnome-extensions enable $EXTENSION_UUID"
fi

