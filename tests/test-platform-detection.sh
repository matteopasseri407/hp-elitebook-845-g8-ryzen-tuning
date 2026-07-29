#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Covers the distribution-aware layer added for the Ubuntu port:
#   - the installer maps package names per distribution family
#   - the power guard treats a missing tuned as normal on Debian and Ubuntu,
#     but still reports it as a regression where tuned is the backend
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

failures=0

fail() {
  echo "FAIL: $*" >&2
  failures=$((failures + 1))
}

write_os_release() {
  local path="$TMPDIR/os-release-$1"
  shift
  printf '%s\n' "$@" >"$path"
  echo "$path"
}

# --- installer platform mapping -------------------------------------------

expect_platform_field() {
  local os_release="$1" field="$2" expected="$3"
  local actual

  actual="$(ELITEBOOK_OS_RELEASE="$os_release" "$REPO_DIR/scripts/install.sh" --print-platform |
    sed -n "s/^${field}=//p")"

  if [[ "$actual" != "$expected" ]]; then
    fail "$field: expected '$expected', got '$actual' (os-release: $os_release)"
  fi
}

fedora_os="$(write_os_release fedora 'ID=fedora' 'VERSION_ID=44')"
ubuntu_os="$(write_os_release ubuntu 'ID=ubuntu' 'ID_LIKE=debian' 'VERSION_ID="26.04"')"
debian_os="$(write_os_release debian 'ID=debian' 'VERSION_ID="13"')"
empty_os="$(write_os_release empty '# no identifying fields')"

expect_platform_field "$fedora_os" distro_family fedora
expect_platform_field "$fedora_os" pkg.flock util-linux-core
expect_platform_field "$fedora_os" pkg.pkexec polkit
expect_platform_field "$fedora_os" pkg.libpci pciutils-devel
expect_platform_field "$fedora_os" tuned_required yes
expect_platform_field "$fedora_os" hibernate_preflight_supported yes

expect_platform_field "$ubuntu_os" distro_family debian
expect_platform_field "$ubuntu_os" pkg.flock util-linux
expect_platform_field "$ubuntu_os" pkg.pkexec pkexec
expect_platform_field "$ubuntu_os" pkg.c++ g++
expect_platform_field "$ubuntu_os" pkg.libpci libpci-dev
expect_platform_field "$ubuntu_os" tuned_required no
expect_platform_field "$ubuntu_os" hibernate_preflight_supported no

expect_platform_field "$debian_os" distro_family debian
expect_platform_field "$debian_os" package_manager "sudo apt install"

# An unreadable or unhelpful os-release must degrade to generic names rather
# than guessing a package manager that is not there.
expect_platform_field "$empty_os" distro_family unknown
expect_platform_field "$TMPDIR/does-not-exist" distro_family unknown

# The hibernate preflight is Fedora-only and must be refused before the
# installer touches anything, including before it asks for root.
if ELITEBOOK_OS_RELEASE="$ubuntu_os" "$REPO_DIR/scripts/install.sh" \
  --with-hibernate-preflight >"$TMPDIR/preflight.out" 2>"$TMPDIR/preflight.err"; then
  fail "installer accepted --with-hibernate-preflight on a Debian-like system"
elif ! grep -qF "only supported on Fedora-like systems" "$TMPDIR/preflight.err"; then
  fail "installer rejected --with-hibernate-preflight without explaining why"
fi

# --- power guard backend handling -----------------------------------------

# Minimal systemctl stub: unit state comes from files in FAKE_SYSTEMCTL_DIR,
# so a test can describe a machine that has no tuned at all.
install_systemctl_stub() {
  local bindir="$1"

  mkdir -p "$bindir"
  cat >"$bindir/systemctl" <<'STUB'
#!/usr/bin/env bash
set -uo pipefail
cmd="${1:-}"
unit="${2:-}"
case "$cmd" in
  cat)
    [[ -f "$FAKE_SYSTEMCTL_DIR/$unit.exists" ]] || exit 1
    printf '# stub unit %s\n' "$unit"
    ;;
  is-enabled)
    [[ -f "$FAKE_SYSTEMCTL_DIR/$unit.enabled" ]] || exit 1
    cat "$FAKE_SYSTEMCTL_DIR/$unit.enabled"
    ;;
  is-active)
    [[ -f "$FAKE_SYSTEMCTL_DIR/$unit.active" ]] || exit 1
    cat "$FAKE_SYSTEMCTL_DIR/$unit.active"
    ;;
  *)
    exit 0
    ;;
esac
STUB
  chmod 0755 "$bindir/systemctl"
}

run_guard() {
  local scenario="$1" backend_conf="$2" os_release="$3"
  local root="$TMPDIR/guard-$scenario"

  install_systemctl_stub "$root/bin"
  PATH="$root/bin:$PATH" \
    FAKE_SYSTEMCTL_DIR="$TMPDIR/units-$scenario" \
    ELITEBOOK_THERMAL_STATE_DIR="$root/state" \
    ELITEBOOK_THERMAL_PROFILE_BIN="$root/absent-dispatcher" \
    ELITEBOOK_BACKEND_CONF="$backend_conf" \
    ELITEBOOK_OS_RELEASE="$os_release" \
    "$REPO_DIR/src/elitebook-power-guard" check >"$root/out" 2>&1 || true
  cat "$root/out"
}

# Ubuntu-shaped machine: power-profiles-daemon present and running, no tuned,
# no tuned-ppd.
units="$TMPDIR/units-ubuntu"
mkdir -p "$units"
: >"$units/power-profiles-daemon.service.exists"
printf 'enabled\n' >"$units/power-profiles-daemon.service.enabled"
printf 'active\n' >"$units/power-profiles-daemon.service.active"
: >"$units/elitebook-thermal-profile.service.exists"
printf 'enabled\n' >"$units/elitebook-thermal-profile.service.enabled"

printf 'POWER_BACKEND=none\n' >"$TMPDIR/backend-none.conf"
ubuntu_guard="$(run_guard ubuntu "$TMPDIR/backend-none.conf" "$ubuntu_os")"

if grep -qF "tuned.service is missing" <<<"$ubuntu_guard"; then
  fail "guard reported missing tuned on a system that never had tuned"
fi
if ! grep -qF "no tuned backend configured" <<<"$ubuntu_guard"; then
  fail "guard did not report the sysfs-only backend on Ubuntu"
fi
if grep -qF "tuned-ppd.service is not masked" <<<"$ubuntu_guard"; then
  fail "guard asked to mask tuned-ppd, which does not exist on Ubuntu"
fi
if ! grep -qF "power-profiles-daemon.service is not masked" <<<"$ubuntu_guard"; then
  fail "guard did not flag an unmasked power-profiles-daemon"
fi

# Fedora-shaped machine that lost tuned: this is a real regression and must
# still be reported.
units="$TMPDIR/units-fedora"
mkdir -p "$units"
: >"$units/elitebook-thermal-profile.service.exists"
printf 'enabled\n' >"$units/elitebook-thermal-profile.service.enabled"

printf 'POWER_BACKEND=tuned\n' >"$TMPDIR/backend-tuned.conf"
fedora_guard="$(run_guard fedora "$TMPDIR/backend-tuned.conf" "$fedora_os")"

if ! grep -qF "tuned.service is missing" <<<"$fedora_guard"; then
  fail "guard stayed silent about tuned disappearing from a tuned-backed install"
fi

# With no backend.conf at all, the guard falls back to the distribution
# family: Fedora expects tuned, Ubuntu does not.
fallback_guard="$(run_guard fedora "$TMPDIR/absent-backend.conf" "$fedora_os")"
if ! grep -qF "tuned.service is missing" <<<"$fallback_guard"; then
  fail "guard did not fall back to expecting tuned on Fedora without backend.conf"
fi

if ((failures > 0)); then
  echo "$failures platform detection check(s) failed" >&2
  exit 1
fi

echo "platform detection checks passed"
