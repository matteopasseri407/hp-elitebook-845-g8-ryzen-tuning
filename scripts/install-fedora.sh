#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

MODE=install
WITH_GNOME_EXTENSION=0
REMOVE_GNOME_EXTENSION=0
ENABLE_STEAM_WATCHER=1
ENABLE_IDLE_WATCHER=1
ENABLE_POWER_GUARD=1
FORCE_HARDWARE=0
BUILD_RYZENADJ=0
KEEP_RYZENADJ=0

EXTENSION_UUID="elitebook-thermal-profile@matteopasseri.github.io"
LEGACY_EXTENSION_UUID="elitebook-thermal-profile@matteopasseri.local"
LEGACY_EXTENSION_DETECTED=0

RYZENADJ_VERSION="v0.17.0"
RYZENADJ_COMMIT="67aa960e71bf4cdd140b47d42c0c62c4cded68d1"
RYZENADJ_TARBALL_URL="https://github.com/FlyGoat/RyzenAdj/archive/refs/tags/${RYZENADJ_VERSION}.tar.gz"
RYZENADJ_TARBALL_SHA256="848ac9d86ff65d30f5e2c8600aac2613f0f10003b0d6f0e516a54761d7345d44"
RYZENADJ_INSTALL_PATH="/usr/local/sbin/ryzenadj"
RYZENADJ_INSTALL_MARKER="/usr/local/share/elitebook-thermal-profile/ryzenadj-source-build"
RYZENADJ_BUILD_TMPDIR=""

cleanup_build_tmpdir() {
  [[ -z "${RYZENADJ_BUILD_TMPDIR:-}" ]] || rm -rf "$RYZENADJ_BUILD_TMPDIR"
}
trap cleanup_build_tmpdir EXIT

usage() {
  cat >&2 <<EOF
Usage: sudo ./scripts/install-fedora.sh [options]

Options:
  --with-gnome-extension       Install the GNOME Shell panel indicator
  --without-steam-watcher      Do not install or enable the Steam game watcher
  --without-idle-watcher       Do not install or enable the idle overlay watcher
  --without-power-guard        Do not install the update guard timer
  --build-ryzenadj             Build RyzenAdj ${RYZENADJ_VERSION} from a pinned,
                               SHA256-verified upstream source tarball if missing
  --force                      Skip the hardware guard. Only use this if you have
                               reviewed the profile values for your machine.
  --uninstall                  Remove installed files and restore Fedora defaults
  --keep-ryzenadj              With --uninstall, keep a source-built RyzenAdj binary
  --gnome-extension            With --uninstall, also remove the GNOME extension
  -h, --help                   Show this help

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

die() {
  echo "install-fedora.sh: $*" >&2
  exit 1
}

warn() {
  echo "install-fedora.sh: warning: $*" >&2
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
    --build-ryzenadj)
      BUILD_RYZENADJ=1
      shift
      ;;
    --force)
      FORCE_HARDWARE=1
      shift
      ;;
    --uninstall)
      MODE=uninstall
      shift
      ;;
    --keep-ryzenadj)
      KEEP_RYZENADJ=1
      shift
      ;;
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

if [[ "$MODE" != "uninstall" ]]; then
  [[ "$KEEP_RYZENADJ" -eq 0 ]] || die "--keep-ryzenadj is only valid with --uninstall"
  [[ "$REMOVE_GNOME_EXTENSION" -eq 0 ]] || die "--gnome-extension is only valid with --uninstall"
fi

if [[ "${EUID}" -ne 0 ]]; then
  if [[ "$MODE" = "uninstall" ]]; then
    die "run this uninstaller with sudo"
  fi
  die "run this installer with sudo"
fi

read_trimmed() {
  local path="$1"
  [[ -r "$path" ]] || return 1
  tr -d '\0' <"$path" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

kernel_lockdown_mode() {
  local content
  if [[ ! -r /sys/kernel/security/lockdown ]]; then
    echo "unavailable"
    return
  fi

  content="$(tr -d '\0\n' </sys/kernel/security/lockdown)"
  if [[ "$content" == *"[none]"* ]]; then
    echo "none"
  elif [[ "$content" =~ \[([^]]+)\] ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo "${content:-unknown}"
  fi
}

secure_boot_state() {
  local value var

  for var in /sys/firmware/efi/efivars/SecureBoot-*; do
    [[ -r "$var" ]] || continue
    value="$(od -An -j4 -N1 -t u1 "$var" 2>/dev/null | tr -d '[:space:]' || true)"
    case "$value" in
      1)
        echo "enabled"
        return
        ;;
      0)
        echo "disabled"
        return
        ;;
      *)
        echo "unknown"
        return
        ;;
    esac
  done

  echo "unavailable"
}

confirm_lockdown_if_needed() {
  local lockdown reply secure_boot

  lockdown="$(kernel_lockdown_mode)"
  [[ "$lockdown" = "none" || "$lockdown" = "unavailable" ]] && return

  secure_boot="$(secure_boot_state)"
  cat >&2 <<EOF
WARNING: kernel lockdown is active (${lockdown}); Secure Boot is ${secure_boot}.

RyzenAdj may not be able to control SMU limits through /dev/mem under lockdown.
The installer can still install the profile scripts, and EPP/frequency/boost
sysfs fallback control remains available, but full SMU tuning may degrade.
EOF

  if [[ ! -t 0 ]]; then
    die "refusing to continue non-interactively while kernel lockdown is active"
  fi

  read -r -p "Continue anyway? [y/N] " reply
  case "$reply" in
    y|Y|yes|YES)
      ;;
    *)
      die "aborted because kernel lockdown is active"
      ;;
  esac
}

check_required_tools() {
  local missing_pkgs=()

  command -v python3 >/dev/null 2>&1 || missing_pkgs+=("python3")
  command -v tuned-adm >/dev/null 2>&1 || missing_pkgs+=("tuned")
  command -v flock >/dev/null 2>&1 || missing_pkgs+=("util-linux-core")
  if [[ "$WITH_GNOME_EXTENSION" -eq 1 ]]; then
    command -v pkexec >/dev/null 2>&1 || missing_pkgs+=("polkit")
  fi
  if [[ "$BUILD_RYZENADJ" -eq 1 ]]; then
    command -v curl >/dev/null 2>&1 || missing_pkgs+=("curl")
    command -v sha256sum >/dev/null 2>&1 || missing_pkgs+=("coreutils")
    command -v tar >/dev/null 2>&1 || missing_pkgs+=("tar")
    command -v cmake >/dev/null 2>&1 || missing_pkgs+=("cmake")
    command -v make >/dev/null 2>&1 || missing_pkgs+=("make")
    command -v c++ >/dev/null 2>&1 || missing_pkgs+=("gcc-c++")
  fi

  if [[ "${#missing_pkgs[@]}" -gt 0 ]]; then
    echo "Missing required tools: ${missing_pkgs[*]}" >&2
    echo "Install them first, for example:" >&2
    echo "  sudo dnf install ${missing_pkgs[*]}" >&2
    exit 1
  fi
}

find_ryzenadj() {
  local candidate

  for candidate in /usr/local/sbin/ryzenadj /usr/local/bin/ryzenadj /usr/bin/ryzenadj; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  if command -v ryzenadj >/dev/null 2>&1; then
    command -v ryzenadj
    return 0
  fi

  return 1
}

build_ryzenadj_from_source() {
  local build_jobs source_dir tarball

  RYZENADJ_BUILD_TMPDIR="$(mktemp -d)"
  tarball="$RYZENADJ_BUILD_TMPDIR/ryzenadj-${RYZENADJ_VERSION}.tar.gz"

  echo "Downloading RyzenAdj ${RYZENADJ_VERSION} (${RYZENADJ_COMMIT})..."
  curl -L --fail --show-error --output "$tarball" "$RYZENADJ_TARBALL_URL"
  printf '%s  %s\n' "$RYZENADJ_TARBALL_SHA256" "$tarball" | sha256sum -c -

  tar -xf "$tarball" -C "$RYZENADJ_BUILD_TMPDIR"
  source_dir="$(find "$RYZENADJ_BUILD_TMPDIR" -mindepth 1 -maxdepth 1 -type d | sort | head -n 1)"
  [[ -n "$source_dir" && -d "$source_dir" ]] || die "RyzenAdj source archive did not contain a source directory"

  rm -rf "$source_dir/win32"
  cmake -S "$source_dir" -B "$source_dir/build" -DCMAKE_BUILD_TYPE=Release
  build_jobs="$(nproc 2>/dev/null || echo 1)"
  cmake --build "$source_dir/build" --parallel "$build_jobs"
  install -D -m 0755 "$source_dir/build/ryzenadj" "$RYZENADJ_INSTALL_PATH"
  install -d -m 0755 "$(dirname -- "$RYZENADJ_INSTALL_MARKER")"
  {
    printf 'version=%s\n' "$RYZENADJ_VERSION"
    printf 'commit=%s\n' "$RYZENADJ_COMMIT"
    printf 'tarball_sha256=%s\n' "$RYZENADJ_TARBALL_SHA256"
    printf 'path=%s\n' "$RYZENADJ_INSTALL_PATH"
  } >"$RYZENADJ_INSTALL_MARKER"
  chmod 0644 "$RYZENADJ_INSTALL_MARKER"
  cleanup_build_tmpdir
  RYZENADJ_BUILD_TMPDIR=""
}

ensure_ryzenadj() {
  if find_ryzenadj >/dev/null; then
    return
  fi

  if [[ "$BUILD_RYZENADJ" -eq 1 ]]; then
    build_ryzenadj_from_source
    find_ryzenadj >/dev/null || die "RyzenAdj build completed, but no ryzenadj executable was found"
    return
  fi

  cat >&2 <<EOF
RyzenAdj was not found. Install RyzenAdj before using these profiles, or run:
  sudo ./scripts/install-fedora.sh --build-ryzenadj

The source-build path pins RyzenAdj ${RYZENADJ_VERSION} at commit ${RYZENADJ_COMMIT}
and verifies SHA256 ${RYZENADJ_TARBALL_SHA256} before compiling.
Upstream: https://github.com/FlyGoat/RyzenAdj
EOF
  exit 1
}

check_hardware() {
  if [[ "$FORCE_HARDWARE" -eq 1 ]]; then
    echo "WARNING: --force is set. The hardware guard will be skipped." >&2
    echo "Make sure the profile values in src/elitebook-thermal-profile are safe for this machine." >&2
    ELITEBOOK_THERMAL_FORCE=1 "$REPO_DIR/src/elitebook-thermal-profile" --check-hardware >/dev/null || true
  else
    "$REPO_DIR/src/elitebook-thermal-profile" --check-hardware >/dev/null
  fi
}

install_profile_files() {
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
}

install_gnome_extension() {
  local extension_dest extension_src legacy_extension_dest target_group target_home target_user

  [[ "$WITH_GNOME_EXTENSION" -eq 1 ]] || return 0

  target_user="${SUDO_USER:-}"
  if [[ -z "$target_user" || "$target_user" = "root" ]]; then
    die "cannot infer the desktop user for the GNOME extension; run with sudo from your user session"
  fi

  target_home="$(getent passwd "$target_user" | cut -d: -f6)"
  [[ -n "$target_home" && -d "$target_home" ]] || die "cannot find the home directory for $target_user"

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
}

enable_services() {
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
}

print_install_summary() {
  echo "Installed HP AMD Ryzen thermal profiles."
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

  [[ "$ENABLE_STEAM_WATCHER" -eq 1 ]] || echo "Steam game watcher skipped."
  [[ "$ENABLE_IDLE_WATCHER" -eq 1 ]] || echo "Idle overlay watcher skipped."
  [[ "$ENABLE_POWER_GUARD" -eq 1 ]] || echo "Update guard timer skipped."
}

remove_owned_ryzenadj() {
  local installed_path

  if [[ "$KEEP_RYZENADJ" -eq 1 ]]; then
    echo "Keeping RyzenAdj because --keep-ryzenadj is set."
    return
  fi

  if [[ ! -f "$RYZENADJ_INSTALL_MARKER" ]]; then
    echo "No source-build RyzenAdj marker found; leaving any existing ryzenadj binary in place."
    return
  fi

  installed_path="$(awk -F= '$1 == "path" {print $2; exit}' "$RYZENADJ_INSTALL_MARKER")"
  case "$installed_path" in
    /usr/local/sbin/ryzenadj|/usr/local/bin/ryzenadj)
      rm -f "$installed_path"
      ;;
    *)
      warn "not removing unrecognized RyzenAdj path from marker: ${installed_path:-empty}"
      ;;
  esac

  rm -f "$RYZENADJ_INSTALL_MARKER"
}

remove_gnome_extension() {
  local extension_dest target_home target_user

  [[ "$REMOVE_GNOME_EXTENSION" -eq 1 ]] || return 0

  target_user="${SUDO_USER:-}"
  if [[ -z "$target_user" || "$target_user" = "root" ]]; then
    warn "skipping GNOME extension removal because the desktop user could not be inferred"
    return
  fi

  target_home="$(getent passwd "$target_user" | cut -d: -f6)"
  if [[ "$target_home" != /* || ! -d "$target_home" ]]; then
    warn "skipping GNOME extension removal because home for $target_user was not found"
    return
  fi

  extension_dest="$target_home/.local/share/gnome-shell/extensions/$EXTENSION_UUID"
  if [[ "$extension_dest" == "$target_home"/.local/share/gnome-shell/extensions/"$EXTENSION_UUID" ]]; then
    rm -rf "$extension_dest"
  fi
}

uninstall_profiles() {
  systemctl disable --now elitebook-steam-game-watcher.service >/dev/null 2>&1 || true
  systemctl disable --now elitebook-idle-watcher.service >/dev/null 2>&1 || true
  systemctl disable --now elitebook-thermal-profile.service >/dev/null 2>&1 || true
  systemctl disable --now elitebook-power-guard.timer >/dev/null 2>&1 || true
  systemctl disable --now elitebook-power-guard.service >/dev/null 2>&1 || true

  rm -f /etc/systemd/system/elitebook-steam-game-watcher.service
  rm -f /etc/systemd/system/elitebook-idle-watcher.service
  rm -f /etc/systemd/system/elitebook-thermal-profile.service
  rm -f /etc/systemd/system/elitebook-power-guard.service
  rm -f /etc/systemd/system/elitebook-power-guard.timer
  rm -f /etc/udev/rules.d/90-elitebook-thermal-profile.rules
  rm -f /etc/systemd/system-sleep/elitebook-thermal-profile
  rm -f /usr/local/sbin/elitebook-steam-game-watcher
  rm -f /usr/local/sbin/elitebook-idle-watcher
  rm -f /usr/local/sbin/elitebook-thermal-profile
  rm -f /usr/local/sbin/elitebook-power-guard
  rm -f /run/elitebook-thermal-profile/current
  rm -f /run/elitebook-thermal-profile/steam-game-watcher
  rm -f /run/elitebook-thermal-profile/idle-watcher
  rm -f /run/elitebook-thermal-profile/guard
  rm -f /run/elitebook-thermal-profile/fallback
  rm -f /run/elitebook-thermal-profile/dispatcher.lock
  rmdir /run/elitebook-thermal-profile >/dev/null 2>&1 || true

  remove_owned_ryzenadj
  remove_gnome_extension

  systemctl unmask power-profiles-daemon.service tuned-ppd.service >/dev/null 2>&1 || true
  systemctl daemon-reload
  udevadm control --reload-rules
  if command -v tuned-adm >/dev/null 2>&1; then
    tuned-adm profile balanced >/dev/null || warn "failed to restore tuned balanced profile"
  else
    warn "tuned-adm not found; cannot restore tuned balanced profile"
  fi

  echo "Removed HP AMD Ryzen thermal profile files and restored Fedora power defaults."
}

if [[ "$MODE" = "uninstall" ]]; then
  uninstall_profiles
  exit 0
fi

confirm_lockdown_if_needed
check_required_tools
ensure_ryzenadj
check_hardware
install_profile_files
install_gnome_extension
enable_services
print_install_summary
