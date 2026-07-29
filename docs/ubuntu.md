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
| Packaging | COPR RPM | `.deb` on the release page, or the source installer |
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

## Install from the .deb packages

Download both packages from the
[latest release](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/releases/latest):

- `elitebook-thermal-profile_*_all.deb` — architecture independent, so the same
  file works on any Ubuntu or Debian release.
- `ryzenadj_*ubuntu24.04_amd64.deb` or `ryzenadj_*ubuntu26.04_amd64.deb` — pick
  the one matching your release. RyzenAdj is compiled, so the binary is tied to
  the release it was built on. The package version uses a tilde
  (`0.17.0-1~ubuntu26.04`); GitHub shows a dot in the asset name instead.
  On Debian, or on an Ubuntu release with no matching build, use the source
  installer's `--build-ryzenadj` below.

```bash
sudo apt install ./ryzenadj_*.deb ./elitebook-thermal-profile_*.deb
```

Installing deliberately does not start anything. After checking that your
machine is on the supported hardware list:

```bash
sudo systemctl enable --now elitebook-thermal-profile.service
sudo systemctl enable --now elitebook-idle-watcher.service
sudo systemctl enable --now elitebook-steam-game-watcher.service
sudo systemctl enable --now elitebook-power-guard.timer
sudo systemctl start elitebook-power-guard.service
```

Optional GNOME Shell indicator:

```bash
sudo apt install ./gnome-shell-extension-elitebook-thermal-profile_*.deb
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

On Wayland, log out and back in after installing the extension.

There is no APT repository or PPA, so these packages will not update
themselves. Watch the releases page, or use the source installer below.

## Install from source

Base dependencies, plus the toolchain to build RyzenAdj:

```bash
sudo apt install python3 util-linux
sudo apt install cmake g++ make libpci-dev curl tar
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

The source installer writes `/etc/elitebook-thermal-profile/backend.conf`; the
packages do not, because they cannot know which distribution they will land on.
Without that file the update guard falls back to reading `os-release`, which
reaches the same conclusion on Ubuntu and Debian.

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

## Do not mix the package and the source installer

They install to different places: the package uses `/usr/bin` and
`/usr/lib/systemd/system`, the source installer uses `/usr/local/sbin` and
`/etc/systemd/system`. Units in `/etc` take precedence, so a source install on
top of a packaged one keeps the package registered while a different copy
actually runs, and a later package upgrade changes nothing.

The installer refuses to run when it finds a packaged install, and the package
warns when it finds a source install. Pick one: the package for a normal
install, the source tree when developing or when no `.deb` matches your system.

## Steam detection with the Snap package

The Steam watcher finds games by locating the `steam` and `steamwebhelper`
processes and walking down to their children. This is verified against a
system Steam package. Ubuntu also ships Steam as a Snap, where the processes
start under `snap-confine` and the tree has an extra level; that has not been
tested.

If it does not work there, the failure is harmless: the watcher simply never
switches to the `gaming` profile, and everything else keeps working. Check with:

```bash
cat /run/elitebook-thermal-profile/steam-game-watcher
```

## Not available here

- **APT repository or PPA.** The `.deb` packages are attached to GitHub
  releases, so `apt` will not upgrade them for you. Fedora has a COPR
  repository; there is no equivalent for Ubuntu or Debian, and publishing one
  needs a Launchpad account and a signing key.
- **Hibernate preflight.** It inspects Fedora-style boot entries with `grubby`
  and checks an SELinux label, neither of which exists on Ubuntu or Debian.
  `--with-hibernate-preflight` is refused there rather than installed broken.

## Uninstall

If you installed the packages:

```bash
sudo apt purge elitebook-thermal-profile
sudo systemctl unmask power-profiles-daemon.service
sudo systemctl enable --now power-profiles-daemon.service
```

The package removes its own files, but unmasking `power-profiles-daemon` is
manual: the update guard masked it at runtime, so it is not something package
removal can be expected to know about.

If you installed from source:

```bash
sudo ./scripts/install.sh --uninstall
```

That removes the units, binaries, udev rule, sleep hook, and
`/etc/elitebook-thermal-profile/backend.conf`, unmasks
`power-profiles-daemon.service`, and enables it again so the system returns to
stock Ubuntu power management. To keep a RyzenAdj binary built by
`--build-ryzenadj`, add `--keep-ryzenadj`.
