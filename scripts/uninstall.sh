#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

REMOVE_GNOME_EXTENSION=0
EXTENSION_UUID="elitebook-thermal-profile@matteopasseri.github.io"

usage() {
  cat >&2 <<'EOF'
Usage: sudo ./scripts/uninstall.sh [--gnome-extension]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gnome-extension)
      REMOVE_GNOME_EXTENSION=1
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
  echo "Run this uninstaller with sudo." >&2
  exit 1
fi

systemctl disable --now elitebook-steam-game-watcher.service >/dev/null 2>&1 || true
systemctl disable --now elitebook-thermal-profile.service >/dev/null 2>&1 || true

rm -f /etc/systemd/system/elitebook-steam-game-watcher.service
rm -f /etc/systemd/system/elitebook-thermal-profile.service
rm -f /etc/udev/rules.d/90-elitebook-thermal-profile.rules
rm -f /etc/systemd/system-sleep/elitebook-thermal-profile
rm -f /usr/local/sbin/elitebook-steam-game-watcher
rm -f /usr/local/sbin/elitebook-thermal-profile
rm -f /run/elitebook-thermal-profile/current
rm -f /run/elitebook-thermal-profile/steam-game-watcher
rmdir /run/elitebook-thermal-profile >/dev/null 2>&1 || true

systemctl daemon-reload
udevadm control --reload-rules

if [[ "$REMOVE_GNOME_EXTENSION" -eq 1 ]]; then
  target_user="${SUDO_USER:-}"
  if [[ -n "$target_user" && "$target_user" != "root" ]]; then
    target_home="$(getent passwd "$target_user" | cut -d: -f6)"
    if [[ "$target_home" = /* && -d "$target_home" ]]; then
      extension_dest="$target_home/.local/share/gnome-shell/extensions/$EXTENSION_UUID"
      if [[ "$extension_dest" == "$target_home"/.local/share/gnome-shell/extensions/"$EXTENSION_UUID" ]]; then
        rm -rf "$extension_dest"
      fi
    fi
  else
    echo "Skipping GNOME extension removal because the desktop user could not be inferred." >&2
  fi
fi

echo "Removed HP EliteBook 845 G8 Ryzen thermal profile files."
