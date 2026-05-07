#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WITH_GNOME_EXTENSION=0
ENABLE_STEAM_WATCHER=1
ENABLE_IDLE_WATCHER=1
ENABLE_POWER_GUARD=1
FORCE_HARDWARE=0
EXTENSION_UUID="elitebook-thermal-profile@matteopasseri.github.io"
LEGACY_EXTENSION_UUID="elitebook-thermal-profile@matteopasseri.local"
LEGACY_EXTENSION_DETECTED=0

usage() {
  cat >&2 <<'EOF'
Usage: sudo ./scripts/install-fedora.sh [options]

Options:
  --with-gnome-extension   Install the GNOME Shell panel indicator
  --without-steam-watcher  Do not install or enable the Steam game watcher
  --without-idle-watcher   Do not install or enable the idle overlay watcher
  --without-power-guard    Do not install the update guard timer
  --force                  Skip the HP EliteBook 845 G8 / Ryzen 7 PRO 5850U
                           hardware guard. Only use this if you have reviewed
                           the profile values for your machine.

Installs:
  /usr/local/sbin/elitebook-thermal-profile
  /etc/systemd/system/elitebook-thermal-profile.service
  /etc/udev/rules.d/90-elitebook-thermal-profile.rules
  /etc/systemd/system-sleep/elitebook-thermal-profile
  low-battery battery-saver automation at 20%
  low-power idle overlay watcher
  update guard timer that remasks conflicting GNOME power backends

By default it also installs and enables the idle overlay watcher, Steam game watcher,
and update guard timer.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-gnome-extension)
      WITH_GNOME_EXTENSION=1
      shift
      ;;
    --without-steam-watcher)
      ENABLE_STEAM_WATCHER=0
      shift
      ;;
    --without-idle-watcher)
      ENABLE_IDLE_WATCHER=0
      shift
      ;;
    --without-power-guard)
      ENABLE_POWER_GUARD=0
      shift
      ;;
    --force)
      FORCE_HARDWARE=1
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

missing_pkgs=()
command -v python3   >/dev/null 2>&1 || missing_pkgs+=("python3")
command -v tuned-adm >/dev/null 2>&1 || missing_pkgs+=("tuned")
if [[ "$WITH_GNOME_EXTENSION" -eq 1 ]]; then
  command -v pkexec >/dev/null 2>&1 || missing_pkgs+=("polkit")
fi

if [[ "${#missing_pkgs[@]}" -gt 0 ]]; then
  echo "Missing required tools: ${missing_pkgs[*]}" >&2
  echo "Install them first, for example:" >&2
  echo "  sudo dnf install ${missing_pkgs[*]}" >&2
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

if [[ "$FORCE_HARDWARE" -eq 1 ]]; then
  echo "WARNING: --force is set. The HP EliteBook 845 G8 / Ryzen 7 PRO 5850U guard will be skipped." >&2
  echo "Make sure the profile values in src/elitebook-thermal-profile are safe for this machine." >&2
  ELITEBOOK_THERMAL_FORCE=1 "$REPO_DIR/src/elitebook-thermal-profile" --check-hardware >/dev/null || true
else
  "$REPO_DIR/src/elitebook-thermal-profile" --check-hardware >/dev/null
fi

install -D -m 0755 "$REPO_DIR/src/elitebook-thermal-profile" /usr/local/sbin/elitebook-thermal-profile
install -D -m 0644 "$REPO_DIR/systemd/elitebook-thermal-profile.service" /etc/systemd/system/elitebook-thermal-profile.service
install -D -m 0644 "$REPO_DIR/udev/90-elitebook-thermal-profile.rules" /etc/udev/rules.d/90-elitebook-thermal-profile.rules
install -D -m 0755 "$REPO_DIR/system-sleep/elitebook-thermal-profile" /etc/systemd/system-sleep/elitebook-thermal-profile

if [[ "$ENABLE_POWER_GUARD" -eq 1 ]]; then
  install -D -m 0755 "$REPO_DIR/src/elitebook-power-guard" /usr/local/sbin/elitebook-power-guard
  install -D -m 0644 "$REPO_DIR/systemd/elitebook-power-guard.service" /etc/systemd/system/elitebook-power-guard.service
  install -D -m 0644 "$REPO_DIR/systemd/elitebook-power-guard.timer" /etc/systemd/system/elitebook-power-guard.timer
else
  systemctl disable --now elitebook-power-guard.timer >/dev/null 2>&1 || true
  systemctl disable --now elitebook-power-guard.service >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/elitebook-power-guard.service
  rm -f /etc/systemd/system/elitebook-power-guard.timer
  rm -f /usr/local/sbin/elitebook-power-guard
  rm -f /run/elitebook-thermal-profile/guard
  rm -f /run/elitebook-thermal-profile/fallback
fi

if [[ "$ENABLE_IDLE_WATCHER" -eq 1 ]]; then
  install -D -m 0755 "$REPO_DIR/src/elitebook-idle-watcher" /usr/local/sbin/elitebook-idle-watcher
  install -D -m 0644 "$REPO_DIR/systemd/elitebook-idle-watcher.service" /etc/systemd/system/elitebook-idle-watcher.service
else
  systemctl disable --now elitebook-idle-watcher.service >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/elitebook-idle-watcher.service
  rm -f /usr/local/sbin/elitebook-idle-watcher
  rm -f /run/elitebook-thermal-profile/idle-watcher
fi

if [[ "$ENABLE_STEAM_WATCHER" -eq 1 ]]; then
  install -D -m 0755 "$REPO_DIR/src/elitebook-steam-game-watcher" /usr/local/sbin/elitebook-steam-game-watcher
  install -D -m 0644 "$REPO_DIR/systemd/elitebook-steam-game-watcher.service" /etc/systemd/system/elitebook-steam-game-watcher.service
else
  systemctl disable --now elitebook-steam-game-watcher.service >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/elitebook-steam-game-watcher.service
  rm -f /usr/local/sbin/elitebook-steam-game-watcher
fi

if [[ "$WITH_GNOME_EXTENSION" -eq 1 ]]; then
  target_user="${SUDO_USER:-}"
  if [[ -z "$target_user" || "$target_user" = "root" ]]; then
    echo "Cannot infer the desktop user for the GNOME extension. Run with sudo from your user session." >&2
    exit 1
  fi

  target_home="$(getent passwd "$target_user" | cut -d: -f6)"
  if [[ -z "$target_home" || ! -d "$target_home" ]]; then
    echo "Cannot find the home directory for $target_user." >&2
    exit 1
  fi

  target_group="$(id -gn "$target_user")"
  extension_src="$REPO_DIR/gnome-extension/$EXTENSION_UUID"
  extension_dest="$target_home/.local/share/gnome-shell/extensions/$EXTENSION_UUID"
  legacy_extension_dest="$target_home/.local/share/gnome-shell/extensions/$LEGACY_EXTENSION_UUID"
  [[ -d "$legacy_extension_dest" ]] && LEGACY_EXTENSION_DETECTED=1

  install -d -m 0755 -o "$target_user" -g "$target_group" \
    "$target_home/.local" \
    "$target_home/.local/share" \
    "$target_home/.local/share/gnome-shell" \
    "$target_home/.local/share/gnome-shell/extensions" \
    "$extension_dest" \
    "$extension_dest/icons"
  install -m 0644 "$extension_src/metadata.json" "$extension_dest/metadata.json"
  install -m 0644 "$extension_src/stylesheet.css" "$extension_dest/stylesheet.css"
  install -m 0644 "$extension_src/extension.js" "$extension_dest/extension.js"
  install -m 0644 "$extension_src"/icons/*.svg "$extension_dest/icons/"
  chown -R "$target_user:$target_group" "$extension_dest"
fi

systemctl daemon-reload
udevadm control --reload-rules
systemctl enable elitebook-thermal-profile.service
systemctl restart elitebook-thermal-profile.service

if [[ "$ENABLE_IDLE_WATCHER" -eq 1 ]]; then
  systemctl enable elitebook-idle-watcher.service
  systemctl restart elitebook-idle-watcher.service
fi

if [[ "$ENABLE_STEAM_WATCHER" -eq 1 ]]; then
  systemctl enable elitebook-steam-game-watcher.service
  systemctl restart elitebook-steam-game-watcher.service
fi

if [[ "$ENABLE_POWER_GUARD" -eq 1 ]]; then
  systemctl enable --now elitebook-power-guard.timer
  systemctl restart elitebook-power-guard.service
fi

echo "Installed HP EliteBook 845 G8 Ryzen thermal profiles."
echo "Current state:"
cat /run/elitebook-thermal-profile/current 2>/dev/null || true
cat /run/elitebook-thermal-profile/guard 2>/dev/null || true

if [[ "$WITH_GNOME_EXTENSION" -eq 1 ]]; then
  echo "GNOME extension installed. Enable it with:"
  if [[ "$LEGACY_EXTENSION_DETECTED" -eq 1 ]]; then
    echo "  gnome-extensions disable $LEGACY_EXTENSION_UUID"
  fi
  echo "  gnome-extensions enable $EXTENSION_UUID"
  echo "On Wayland, log out and back in after changing the extension UUID."
fi

if [[ "$ENABLE_STEAM_WATCHER" -ne 1 ]]; then
  echo "Steam game watcher skipped."
fi

if [[ "$ENABLE_IDLE_WATCHER" -ne 1 ]]; then
  echo "Idle overlay watcher skipped."
fi

if [[ "$ENABLE_POWER_GUARD" -ne 1 ]]; then
  echo "Update guard timer skipped."
fi
