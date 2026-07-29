# Ubuntu and Debian

**Status: experimental.** The installer, the update guard, and the test suite
are distribution aware, and the platform logic runs in CI on Ubuntu runners.
The profiles themselves have not yet been validated on a physical machine
running Ubuntu. Fedora remains the primary validated path; see
[fedora.md](fedora.md).

If you run this on Ubuntu or Debian on supported hardware, please open a
[Hardware Report](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/issues/new?template=hardware-report.md)
with the output of `sudo elitebook-power-guard check`.

## What differs from Fedora

| Area | Fedora | Ubuntu / Debian |
| --- | --- | --- |
| Packaging | COPR RPM | source installer only |
| CPU policy backend | `tuned` plus direct sysfs and SMU | direct sysfs and SMU only |
| Masked backends | `tuned-ppd`, `power-profiles-daemon` | `power-profiles-daemon` |
| RyzenAdj | COPR package or source build | source build (`--build-ryzenadj`) |
| Hibernate preflight | supported (opt-in) | not supported |

The dispatcher hands a `balanced` or `powersave` profile to `tuned` when tuned
is present. Ubuntu and Debian ship `power-profiles-daemon` instead, and there
is no `tuned-ppd`. On those systems the dispatcher drives EPP, boost, CPU
maximum frequency, and the SMU limits directly, which is the same control path
Fedora uses for everything except the tuned handoff.

The installer records what it found in `/etc/elitebook-thermal-profile/backend.conf`,
and `elitebook-power-guard` reads it. That file is why a missing tuned is
reported as a fault on a Fedora install but treated as normal here.

## Before you start: Secure Boot

This is the one thing that decides whether you get full control or a degraded
fallback.

RyzenAdj writes SMU power limits through `/dev/mem`. When the kernel runs in
lockdown mode, that write is blocked. **Secure Boot normally puts the kernel
into lockdown**, and Ubuntu enables Secure Boot by default on most installs.

Check both before installing:

```bash
cat /sys/kernel/security/lockdown
sudo bootctl status | grep -i "secure boot"
```

A healthy setup for this project reads `[none] integrity confidentiality`,
meaning lockdown is off.

If lockdown is active, the installer warns and asks for confirmation. You can
still install: EPP, boost, and CPU maximum frequency keep working through
sysfs. What you lose is the SMU layer, which is where the sustained power
limits and the thermal target live, so the main reason to use this project is
gone. To get it back, disable Secure Boot in the BIOS.

## Install

Base dependencies:

```bash
sudo apt install python3 util-linux
```

RyzenAdj is not packaged in the Ubuntu or Debian archives. The installer can
build a pinned, SHA256-verified upstream release:

```bash
sudo apt install cmake g++ make libpci-dev curl tar
```

Then:

```bash
git clone https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning.git
cd hp-elitebook-845-g8-ryzen-tuning
sudo ./scripts/install.sh --build-ryzenadj
```

For the optional GNOME Shell indicator, add `pkexec` and pass
`--with-gnome-extension`:

```bash
sudo apt install pkexec
sudo ./scripts/install.sh --build-ryzenadj --with-gnome-extension
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

On Wayland, log out and back in after installing the extension.

To see what the installer detected before running it, without root:

```bash
./scripts/install.sh --print-platform
```

## GNOME power modes go away

The update guard masks `power-profiles-daemon.service` so it cannot fight the
dispatcher over EPP policy. GNOME's Balanced / Power Saver / Performance
selector is a front end for that daemon, so once this project is installed the
selector stops working. This is intentional and identical to the Fedora
behavior: profile switching moves to `elitebook-thermal-profile`, the udev
automation, and the optional panel indicator.

Uninstalling restores `power-profiles-daemon` and re-enables it.

## Verify

```bash
cat /etc/elitebook-thermal-profile/backend.conf   # expect POWER_BACKEND=none
cat /run/elitebook-thermal-profile/current
sudo elitebook-power-guard check
sudo ryzenadj -i | head -20
```

`elitebook-power-guard check` exits non-zero and lists what is wrong when a
guardrail is missing. On a healthy Ubuntu install it reports the sysfs-only
backend and says nothing about tuned.

Confirm the CPU driver exposes EPP, which is what the profiles write:

```bash
cat /sys/devices/system/cpu/cpufreq/policy0/scaling_driver   # expect amd-pstate-epp
```

If the driver is `acpi-cpufreq` or `amd-pstate` in passive mode, EPP writes are
skipped with a warning and only boost, frequency caps, and SMU limits apply.

## Not available here

- **`.deb` package.** Source installation only. Fedora has a COPR repository;
  there is no equivalent published for Ubuntu or Debian yet.
- **Hibernate preflight.** It inspects Fedora-style boot entries with `grubby`
  and checks an SELinux label, neither of which exists on Ubuntu or Debian.
  `--with-hibernate-preflight` is refused there rather than installed broken.

## Uninstall

```bash
sudo ./scripts/install.sh --uninstall
```

This removes the units, binaries, udev rule, sleep hook, and
`/etc/elitebook-thermal-profile/backend.conf`, unmasks
`power-profiles-daemon.service`, and enables it again so the system returns to
stock Ubuntu power management.

To keep a RyzenAdj binary built by `--build-ryzenadj`, add `--keep-ryzenadj`.
