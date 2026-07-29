#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SELF="$(basename -- "$0")"

OS_RELEASE="${ELITEBOOK_OS_RELEASE:-/etc/os-release}"
PACKAGED_BIN="${ELITEBOOK_PACKAGED_BIN:-/usr/bin/elitebook-thermal-profile}"
BACKEND_CONF_DIR="${ELITEBOOK_BACKEND_CONF_DIR:-/etc/elitebook-thermal-profile}"
BACKEND_CONF="$BACKEND_CONF_DIR/backend.conf"

MODE=install
WITH_GNOME_EXTENSION=0
REMOVE_GNOME_EXTENSION=0
ENABLE_STEAM_WATCHER=1
ENABLE_IDLE_WATCHER=1
ENABLE_POWER_GUARD=1
ENABLE_HIBERNATE_PREFLIGHT=0
FORCE_HARDWARE=0
BUILD_RYZENADJ=0
KEEP_RYZENADJ=0

POWER_BACKEND=""

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
Usage: sudo ./scripts/install.sh [options]

Supported distributions: Fedora and Ubuntu/Debian. The installer detects the
distribution, picks the matching package names, and records which power
management backend it configured.

Options:
  --with-gnome-extension       Install the GNOME Shell panel indicator
  --with-hibernate-preflight   Install the btrfs swapfile hibernate preflight
                               and its systemd-hibernate drop-ins
  --without-steam-watcher      Do not install or enable the Steam game watcher
  --without-idle-watcher       Do not install or enable the idle overlay watcher
  --without-power-guard        Do not install the update guard timer
  --build-ryzenadj             Build RyzenAdj ${RYZENADJ_VERSION} from a pinned,
                               SHA256-verified upstream source tarball if missing
  --force                      Skip the hardware guard. Only use this if you have
                               reviewed the profile values for your machine.
  --print-platform             Print the detected distribution and the package
                               names that would be used, then exit. Needs no root.
  --uninstall                  Remove installed files and restore distribution defaults
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
  echo "$SELF: $*" >&2
  exit 1
}

warn() {
  echo "$SELF: warning: $*" >&2
}

# Distribution detection. Only the package-name mapping and the choice of
# power backend depend on this; the profiles themselves are distro agnostic.
distro_family() {
  local ids="" haystack=""

  if [[ -r "$OS_RELEASE" ]]; then
    # Sourced in a subshell so ID/ID_LIKE never leak into the installer.
    # shellcheck disable=SC1090
    ids="$(. "$OS_RELEASE" >/dev/null 2>&1 && printf '%s %s' "${ID:-}" "${ID_LIKE:-}")" || ids=""
  fi
  haystack=" $ids "

  case "$haystack" in
    *" fedora "*|*" rhel "*|*" centos "*)
      echo fedora
      ;;
    *" debian "*|*" ubuntu "*)
      echo debian
      ;;
    *)
      echo unknown
      ;;
  esac
}

DISTRO_FAMILY="$(distro_family)"

package_manager_hint() {
  case "$DISTRO_FAMILY" in
    fedora)
      echo "sudo dnf install"
      ;;
    debian)
      echo "sudo apt install"
      ;;
    *)
      echo "your package manager:"
      ;;
  esac
}

# Maps a logical dependency to the package that ships it on this distribution.
# Package names verified against the Fedora and Ubuntu package archives.
pkg_name() {
  local logical="$1"

  case "$DISTRO_FAMILY:$logical" in
    fedora:flock) echo "util-linux-core" ;;
    debian:flock) echo "util-linux" ;;
    fedora:pkexec) echo "polkit" ;;
    debian:pkexec) echo "pkexec" ;;
    fedora:c++) echo "gcc-c++" ;;
    debian:c++) echo "g++" ;;
    fedora:libpci) echo "pciutils-devel" ;;
    debian:libpci) echo "libpci-dev" ;;
    *:*) echo "$logical" ;;
  esac
}

# Which package, if any, owns a path. Empty when nothing does, or when the
# distribution's query tool is unavailable.
# Both tools report "no package owns this" through their exit status. Trust
# that rather than their message, which is translated: on an Italian system
# rpm answers "non e' posseduto da alcun pacchetto", and matching English text
# would quietly turn that error into a package name.
package_owning() {
  local path="$1" owner="" raw=""

  if command -v dpkg-query >/dev/null 2>&1; then
    if raw="$(LC_ALL=C dpkg-query -S "$path" 2>/dev/null)"; then
      owner="$(printf '%s' "$raw" | head -n 1 | cut -d: -f1)"
    fi
  fi
  if [[ -z "$owner" ]] && command -v rpm >/dev/null 2>&1; then
    if raw="$(LC_ALL=C rpm -qf "$path" 2>/dev/null)"; then
      owner="$(printf '%s' "$raw" | head -n 1)"
    fi
  fi

  printf '%s' "$owner"
}

# The RPM and the .deb install into /usr/bin; this installer writes to
# /usr/local/sbin and drops its units in /etc/systemd/system, which take
# precedence over the packaged ones in /usr/lib/systemd/system. Running both
# therefore leaves two copies of everything, with the packaged one still
# registered but no longer the copy that runs: a later package upgrade would
# appear to do nothing. Refuse instead of creating that state silently.
check_no_packaged_install() {
  local owner

  [[ -e "$PACKAGED_BIN" ]] || return 0

  owner="$(package_owning "$PACKAGED_BIN")"
  cat >&2 <<EOF
$SELF: a packaged installation is already present.

  $PACKAGED_BIN${owner:+ (owned by $owner)}

Installing from source on top of it leaves two copies: the units this installer
writes to /etc/systemd/system override the packaged ones, so the package would
stay registered while a different copy actually runs.

Remove the package first, then run this installer again:
  sudo apt purge elitebook-thermal-profile     # Debian, Ubuntu
  sudo dnf remove elitebook-thermal-profile    # Fedora

Or keep the package and skip this installer entirely; both install the same
software.
EOF
  exit 1
}

# The hibernate preflight verifies a btrfs swapfile against Fedora-style boot
# entries via grubby, and checks an SELinux label. Neither exists on Debian or
# Ubuntu, so refuse it there instead of installing something that cannot work.
check_hibernate_preflight_supported() {
  [[ "$ENABLE_HIBERNATE_PREFLIGHT" -eq 1 ]] || return 0
  [[ "$DISTRO_FAMILY" != "fedora" ]] || return 0

  die "--with-hibernate-preflight is only supported on Fedora-like systems; it relies on grubby and SELinux labels"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-gnome-extension)
      WITH_GNOME_EXTENSION=1
      shift
      ;;
    --with-hibernate-preflight)
      ENABLE_HIBERNATE_PREFLIGHT=1
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
    --print-platform)
      MODE=print-platform
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
  if [[ "$MODE" = "install" ]]; then
    check_hibernate_preflight_supported
    check_no_packaged_install
  fi
fi

# Reports what the installer detected. Kept root-free on purpose: it is the
# first thing to run when an install misbehaves on an untested distribution.
print_platform() {
  local logical

  printf 'distro_family=%s\n' "$DISTRO_FAMILY"
  printf 'package_manager=%s\n' "$(package_manager_hint)"
  for logical in flock pkexec c++ libpci; do
    printf 'pkg.%s=%s\n' "$logical" "$(pkg_name "$logical")"
  done
  printf 'tuned_required=%s\n' "$([[ "$DISTRO_FAMILY" = "fedora" ]] && echo yes || echo no)"
  printf 'hibernate_preflight_supported=%s\n' "$([[ "$DISTRO_FAMILY" = "fedora" ]] && echo yes || echo no)"
}

if [[ "$MODE" = "print-platform" ]]; then
  print_platform
  exit 0
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
  command -v flock >/dev/null 2>&1 || missing_pkgs+=("$(pkg_name flock)")

  # tuned is the expected CPU policy backend on Fedora, where the dispatcher
  # hands it the balanced/powersave profile. Debian and Ubuntu ship
  # power-profiles-daemon instead, and the dispatcher drives CPU policy
  # directly through sysfs and SMU, so tuned is not required there.
  if [[ "$DISTRO_FAMILY" = "fedora" ]]; then
    command -v tuned-adm >/dev/null 2>&1 || missing_pkgs+=("tuned")
  fi

  if [[ "$WITH_GNOME_EXTENSION" -eq 1 ]]; then
    command -v pkexec >/dev/null 2>&1 || missing_pkgs+=("$(pkg_name pkexec)")
  fi

  if [[ "$ENABLE_HIBERNATE_PREFLIGHT" -eq 1 ]]; then
    command -v btrfs >/dev/null 2>&1 || missing_pkgs+=("btrfs-progs")
    command -v grubby >/dev/null 2>&1 || missing_pkgs+=("grubby")
  fi

  if [[ "$BUILD_RYZENADJ" -eq 1 ]]; then
    command -v curl >/dev/null 2>&1 || missing_pkgs+=("curl")
    command -v sha256sum >/dev/null 2>&1 || missing_pkgs+=("coreutils")
    command -v tar >/dev/null 2>&1 || missing_pkgs+=("tar")
    command -v cmake >/dev/null 2>&1 || missing_pkgs+=("cmake")
    command -v make >/dev/null 2>&1 || missing_pkgs+=("make")
    command -v c++ >/dev/null 2>&1 || missing_pkgs+=("$(pkg_name c++)")
    # RyzenAdj links against libpci; without the headers the CMake build
    # fails late with a confusing missing-include error.
    [[ -e /usr/include/pci/pci.h ]] || missing_pkgs+=("$(pkg_name libpci)")
  fi

  if [[ "${#missing_pkgs[@]}" -gt 0 ]]; then
    echo "Missing required tools: ${missing_pkgs[*]}" >&2
    echo "Install them first, for example:" >&2
    echo "  $(package_manager_hint) ${missing_pkgs[*]}" >&2
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
  sudo ./scripts/install.sh --build-ryzenadj

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

  if [[ "$ENABLE_HIBERNATE_PREFLIGHT" -eq 1 ]]; then
    install -D -m 0755 "$REPO_DIR/src/elitebook-hibernate-preflight" /usr/local/sbin/elitebook-hibernate-preflight
    install -D -m 0644 "$REPO_DIR/systemd/systemd-hibernate.service.d/10-elitebook-preflight.conf" \
      /etc/systemd/system/systemd-hibernate.service.d/10-elitebook-preflight.conf
    install -D -m 0644 "$REPO_DIR/systemd/systemd-suspend-then-hibernate.service.d/10-elitebook-preflight.conf" \
      /etc/systemd/system/systemd-suspend-then-hibernate.service.d/10-elitebook-preflight.conf
    if [[ ! -f /etc/elitebook-hibernate.conf ]]; then
      install -D -m 0644 "$REPO_DIR/config/elitebook-hibernate.conf.example" /etc/elitebook-hibernate.conf
      warn "created /etc/elitebook-hibernate.conf from the example; hibernate stays blocked until you fill in your real swapfile values"
    fi
  else
    rm -f /etc/systemd/system/systemd-hibernate.service.d/10-elitebook-preflight.conf
    rm -f /etc/systemd/system/systemd-suspend-then-hibernate.service.d/10-elitebook-preflight.conf
    rmdir /etc/systemd/system/systemd-hibernate.service.d >/dev/null 2>&1 || true
    rmdir /etc/systemd/system/systemd-suspend-then-hibernate.service.d >/dev/null 2>&1 || true
    rm -f /usr/local/sbin/elitebook-hibernate-preflight
  fi
}

# Records which power backend this machine was set up with, so the guard can
# tell a genuine regression (Fedora that lost tuned) from a system that never
# had tuned to begin with (Ubuntu, Debian).
configure_power_backend() {
  local backend=none

  if command -v tuned-adm >/dev/null 2>&1 && systemctl cat tuned.service >/dev/null 2>&1; then
    backend=tuned
  fi

  install -d -m 0755 "$BACKEND_CONF_DIR"
  {
    printf '# Written by %s; consumed by elitebook-power-guard.\n' "$SELF"
    printf '# tuned = CPU policy is coordinated with tuned (Fedora default).\n'
    printf '# none  = the dispatcher drives CPU policy directly via sysfs and SMU.\n'
    printf 'POWER_BACKEND=%s\n' "$backend"
    printf 'DISTRO_FAMILY=%s\n' "$DISTRO_FAMILY"
  } >"$BACKEND_CONF"
  chmod 0644 "$BACKEND_CONF"

  POWER_BACKEND="$backend"
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
  echo "Distribution family: ${DISTRO_FAMILY}; power backend: ${POWER_BACKEND:-unknown}"
  if [[ "$POWER_BACKEND" = "none" ]]; then
    echo "No tuned on this system: CPU policy is applied directly via sysfs and SMU."
  fi
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

  if [[ "$ENABLE_HIBERNATE_PREFLIGHT" -eq 1 ]]; then
    echo "Hibernate preflight installed. Review /etc/elitebook-hibernate.conf and verify with:"
    echo "  sudo elitebook-hibernate-preflight check-config"
  fi
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

# Hands CPU policy back to whatever the distribution normally uses: tuned on
# Fedora, power-profiles-daemon on Debian and Ubuntu. Leaving neither running
# would silently strand the machine on the last profile the dispatcher wrote.
restore_power_backend() {
  if command -v tuned-adm >/dev/null 2>&1; then
    tuned-adm profile balanced >/dev/null || warn "failed to restore tuned balanced profile"
    return
  fi

  if systemctl cat power-profiles-daemon.service >/dev/null 2>&1; then
    if systemctl enable --now power-profiles-daemon.service >/dev/null 2>&1; then
      echo "Restored power-profiles-daemon as the system power backend."
    else
      warn "failed to restart power-profiles-daemon; start it manually to restore default power management"
    fi
    return
  fi

  warn "no tuned or power-profiles-daemon found; this machine has no distribution power backend to restore"
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
  rm -f /etc/systemd/system/systemd-hibernate.service.d/10-elitebook-preflight.conf
  rm -f /etc/systemd/system/systemd-suspend-then-hibernate.service.d/10-elitebook-preflight.conf
  rmdir /etc/systemd/system/systemd-hibernate.service.d >/dev/null 2>&1 || true
  rmdir /etc/systemd/system/systemd-suspend-then-hibernate.service.d >/dev/null 2>&1 || true
  rm -f /usr/local/sbin/elitebook-hibernate-preflight
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

  rm -f "$BACKEND_CONF"
  rmdir "$BACKEND_CONF_DIR" >/dev/null 2>&1 || true

  systemctl unmask power-profiles-daemon.service tuned-ppd.service >/dev/null 2>&1 || true
  systemctl daemon-reload
  udevadm control --reload-rules
  restore_power_backend

  if [[ -f /etc/elitebook-hibernate.conf ]]; then
    echo "Kept /etc/elitebook-hibernate.conf (user configuration); remove it manually if unwanted."
  fi
  echo "Removed HP AMD Ryzen thermal profile files and restored the distribution power defaults."
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
configure_power_backend
install_gnome_extension
enable_services
print_install_summary
