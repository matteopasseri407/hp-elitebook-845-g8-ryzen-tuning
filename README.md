# HP AMD Ryzen Thermal Profiles

[![CI](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/actions/workflows/ci.yml/badge.svg)](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning)](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/releases)
[![Fedora COPR](https://img.shields.io/badge/Fedora_COPR-matteo407%2Felitebook--thermal--profile-51A2DA?logo=fedora)](https://copr.fedorainfracloud.org/coprs/matteo407/elitebook-thermal-profile/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)

> # ⚠️ Secure Boot must be OFF
>
> **With Secure Boot enabled, this project does almost nothing.**
>
> Secure Boot puts the kernel in lockdown mode, and lockdown blocks the SMU
> power-limit writes this entire project is built on. What survives is the EPP
> hint — the sustained power envelope and the thermal target, the parts that
> actually stop a laptop cooking at 100 °C, do not get applied.
>
> Check before you install:
>
> ```bash
> cat /sys/kernel/security/lockdown    # must read: [none] integrity confidentiality
> ```
>
> If it reads anything else, disable Secure Boot in the firmware first. On HP
> business laptops: `F10` at boot → Security → Secure Boot → disable.
>
> The tool still installs and runs with Secure Boot on: it applies what it can,
> writes `smu=blocked` in its state file, and tells you it is degraded rather
> than pretending to work. That is a safety net, not the intended setup.
> Details and the alternatives in [docs/ubuntu.md](docs/ubuntu.md#before-you-start-secure-boot).

**Is your HP business laptop with an AMD Ryzen sitting at 100 °C on Linux, with
the fan never stopping, under nothing heavier than an IDE and a browser?** That
is the problem this repository was built to fix, on real hardware, without
disabling boost or permanently capping the CPU.

Stock firmware on the tested unit allowed sustained 100-102 °C under ordinary
development load and relied on thermal throttling to survive it. These profiles
lower the *sustained* SMU power envelope and the thermal target while leaving
burst performance intact, so the machine still feels fast and stops living at
its thermal ceiling.

Thermal and power profiles for selected HP EliteBook and ProBook AMD Ryzen laptops.

The profile values are field-tested on an HP EliteBook 845 G8 with the AMD Ryzen 7 PRO 5850U. Other HP Cezanne models are accepted by the hardware guard only when they match the validated CPU family listed below. Rembrandt models are recognized but intentionally blocked by default until their SMU behavior is validated.

The goal is not to hard-cap the CPU. The profiles keep boost enabled and leave the maximum CPU frequency uncapped for normal work, then tune the sustained SMU power limits and the AMD P-State energy preference so the laptop can still burst hard without sitting at the stock 100 C thermal edge during sustained workloads.

Idle efficiency is handled separately by a staged idle overlay. The overlay leaves the selected profile intact, moves to a soft idle hint after a few quiet seconds, and only enters a deeper capped state after sustained quiet. Any real CPU load clears the overlay and restores the active profile.

Tested on:

- HP EliteBook 845 G8
- AMD Ryzen 7 PRO 5850U
- Fedora Linux 44
- GNOME Shell 50
- Linux 6.19 series and 7.0.4-200.fc44.x86_64

This is intentionally hardware-scoped. The main script refuses to run on unrecognized hardware unless `ELITEBOOK_THERMAL_FORCE=1` is set.

## Quickstart

**Fedora status:** Fedora 44 x86_64 is the primary supported distribution path.
The public COPR publishes `elitebook-thermal-profile`,
`gnome-shell-extension-elitebook-thermal-profile`, and upstream RyzenAdj
`v0.17.0`. Package installation is intentionally passive: it installs files only
and does not start hardware tuning until you enable the services below.

For Fedora 44 users with a supported HP business Cezanne laptop, the COPR RPM is
the lowest-friction install path:

```bash
sudo dnf copr enable matteo407/elitebook-thermal-profile
sudo dnf install elitebook-thermal-profile
```

The same COPR also packages RyzenAdj `v0.17.0`; with default DNF weak
dependencies, installing `elitebook-thermal-profile` pulls it in automatically.
If your system disables weak dependencies, install it explicitly:

```bash
sudo dnf install elitebook-thermal-profile ryzenadj
```

The RPM deliberately installs files only; it does not start hardware tuning
during package installation. After reviewing the supported hardware table:

```bash
sudo systemctl enable --now elitebook-thermal-profile.service
sudo systemctl enable --now elitebook-idle-watcher.service
sudo systemctl enable --now elitebook-steam-game-watcher.service
sudo systemctl enable --now elitebook-power-guard.timer
sudo systemctl start elitebook-power-guard.service
```

If `ryzenadj` is unavailable on another distribution, the source installer can
build a pinned, SHA256-verified RyzenAdj release with `--build-ryzenadj`.
Without RyzenAdj, the system degrades to sysfs controls for EPP, boost, and CPU
frequency where the kernel exposes them. See [Supported Hardware](#supported-hardware)
before enabling services on any machine. Other distributions are not packaged
yet; see [Related Work](#related-work) and the roadmap.

## Does this apply to your machine?

It probably does if all of these are true:

- an HP EliteBook 835/845 or ProBook 445/455, Ryzen 5000-series PRO APU
  (Cezanne: 5650U, 5750U, 5850U)
- running Linux, on Fedora, Ubuntu, or Debian with systemd
- the CPU package sits at 95-100 °C under sustained load, not just in short
  bursts, and the fan is audible during ordinary work
- `sudo ryzenadj -i` reports a stock sustained (slow) limit near 25 W and a
  Tctl target of 100 °C
- Secure Boot is off, or you are willing to turn it off

What this is **not**:

- **not an undervolting tool.** It does not touch curve optimizer or voltage
  offsets, and it cannot make the silicon more efficient.
- **not a fan-curve controller.** HP firmware owns the fan; this changes how
  much heat the fan has to remove, not how it spins.
- **not a general Ryzen tuner.** The hardware guard refuses machines outside
  the tested list unless you explicitly force it.
- **not a performance mod.** The point is losing less performance to thermal
  throttling, not raising limits above stock.

## Supported Hardware

Validated by default:

| DMI product family | CPU family | Status |
| --- | --- | --- |
| HP EliteBook 835 G7/G8/G9 | Ryzen 5/7 PRO 5650U, 5750U, 5850U | Cezanne profiles enabled |
| HP EliteBook 845 G7/G8/G9 | Ryzen 5/7 PRO 5650U, 5750U, 5850U | Cezanne profiles enabled |
| HP ProBook 445 G8/G9 | Ryzen 5/7 PRO 5650U, 5750U, 5850U | Cezanne profiles enabled |
| HP ProBook 455 G8/G9 | Ryzen 5/7 PRO 5650U, 5750U, 5850U | Cezanne profiles enabled |

Known but not enabled by default:

| DMI product family | CPU family | Status |
| --- | --- | --- |
| HP EliteBook 835/845 G9, HP ProBook 445/455 G9 | Ryzen 5/7 PRO 6650U, 6850U | Rembrandt detected, requires `ELITEBOOK_THERMAL_FORCE=1` after manual review |

The project does not change SMU numbers per model yet. Every enabled model uses the same conservative Cezanne limits shown in the profiles table.

If you run this on a supported HP business Cezanne variant other than the 845 G8 (for example 835 G7/G8/G9, 845 G7/G9, or ProBook 445/455 G8/G9) and it behaves correctly, please open a [Hardware Report](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/issues/new?template=hardware-report.md). Confirmed reports help grow the validated whitelist with real-world data instead of one machine.

## Profiles

| Profile | Use case | Boost | CPU max freq | EPP | Fast limit | Sustained CPU/APU | Tctl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ac` | Plugged in daily work | on | uncapped | `balance_power` | 30 W | 18 W | 90 C |
| `performance` | Manual plugged-in performance | on | uncapped | `balance_performance` | 30 W | 18 W | 90 C |
| `battery` | Unplugged work | on | uncapped | `balance_power` | 30 W | 15 W | 88 C |
| `battery-saver` | Automatic low-battery guard | off | 1.8 GHz | `power` | 15 W | 8 W | 80 C |
| `gaming` | Steam game process detected | on | uncapped | `balance_performance` | 30 W | 23 W | 92 C |
| `cool` | Quiet/cool fallback | on | uncapped | `power` | 22 W | 12 W | 85 C |

There is no `stock` profile. On the tested unit, the stock firmware/SMU behavior allowed sustained 100-102 C operation under real development workloads, which was exactly what this project was built to avoid.

## What It Installs

- `elitebook-thermal-profile`: applies `auto`, `ac`, `performance`, `battery`, `battery-saver`, `gaming`, or `cool`
- systemd oneshot service: reapplies `auto` at boot
- udev rules: reapply `auto` when AC power or battery state changes
- system sleep hook: reapplies `auto` after resume
- idle overlay watcher: applies soft/deep idle hints with near-zero polling overhead
- Steam game watcher: switches to `gaming` only while a real Steam game process is detected
- update guard timer: remasks conflicting GNOME power profile backends, keeps the custom units enabled, and reapplies `auto` after package/kernel changes without pinning updates
- optional btrfs swapfile hibernate preflight (`--with-hibernate-preflight`): validates swap layout, resume offset, kernel lockdown, and SELinux state before systemd enters hibernate
- optional GNOME Shell panel indicator: three human actions (`Auto`, `Game`, `Quiet`) while automatic `ac`, `battery`, `battery-saver`, and idle states remain status-only

Battery capacity changes also emit `power_supply` udev events, so on battery the dispatcher re-runs roughly once per battery percent. This is intentional: it is what detects the low-battery threshold crossing without a polling daemon, and the periodic reapply heals SMU limits that firmware events may have reset. Each run is an idempotent oneshot serialized by a dispatcher lock.

The idle watcher is intentionally cheap. It samples aggregate `/proc/stat` and `/proc/loadavg` once per second, does not scan processes, preserves stricter base frequency caps such as `battery-saver`, and calls RyzenAdj only when entering or leaving deep idle. The Steam watcher scans `/proc` only on long intervals and is constrained with low scheduling priority, `CPUQuota=5%`, and `MemoryMax=64M`.

## Requirements

- Linux with systemd and udev
- AMD P-State or cpufreq sysfs support
- `ryzenadj` installed as `/usr/local/sbin/ryzenadj`, `/usr/local/bin/ryzenadj`, or `/usr/bin/ryzenadj` for full SMU power-limit control
- `tuned` on Fedora, where the dispatcher hands it the balanced/powersave profile. Not required on Ubuntu or Debian, which have no tuned by default; there the dispatcher drives CPU policy directly through sysfs and SMU
- `pkexec` only if using the GNOME Shell switcher
- `flock` from util-linux, normally installed by default
- Kernel lockdown set to `none` for full RyzenAdj SMU control through `/dev/mem`

Secure Boot commonly enables kernel lockdown. When lockdown is active, RyzenAdj may not be able to write SMU limits through `/dev/mem`; the installer warns and asks for confirmation before continuing. EPP, CPU max frequency, and boost sysfs controls still degrade cleanly.

### RyzenAdj And Fallback Mode

This repository does not vendor RyzenAdj. Fedora users can install RyzenAdj from
the same COPR:

```bash
sudo dnf copr enable matteo407/elitebook-thermal-profile
sudo dnf install ryzenadj
```

The COPR package builds upstream FlyGoat RyzenAdj `v0.17.0` from source and
verifies the same SHA256 used by the source installer. Users on other
distributions can install RyzenAdj from their package source, upstream, or let
the Fedora/source installer build the pinned release:

```bash
sudo ./scripts/install.sh --build-ryzenadj
```

The source-build path pins RyzenAdj `v0.17.0` at commit `67aa960e71bf4cdd140b47d42c0c62c4cded68d1` and verifies SHA256 `848ac9d86ff65d30f5e2c8600aac2613f0f10003b0d6f0e516a54761d7345d44` before compiling.

When RyzenAdj works, profiles apply both kernel-level policy and SMU limits:
EPP, boost, CPU max frequency, sustained package power, STAPM/fast/slow limits,
and thermal targets. When RyzenAdj is missing or blocked by kernel lockdown,
the dispatcher still applies the kernel-level controls for the selected
profile — EPP, boost, and CPU max frequency — records the reason in its state
file, and exits successfully. That fallback is intentionally conservative; it
is not a full replacement for SMU tuning.

The state file reports which of the two happened:

```bash
grep smu= /run/elitebook-thermal-profile/current
```

`smu=ok` means the limits were applied. `unavailable` means RyzenAdj is not
installed, `blocked` means kernel lockdown refused the write (Secure Boot is
the usual cause), and `failed` means RyzenAdj ran and returned an error. In
the last three cases the `stapm_mw`, `fast_mw`, `slow_mw`, `apu_mw`, and
`tctl_c` values in that file are what was requested, not what the hardware is
running, and `elitebook-power-guard check` reports the machine as degraded.

One SMU value is special: on platforms with Skin Temperature Tracking (STT)
enabled (the EliteBook 845 G8 itself included), the firmware owns the STAPM
limit and rewrites it within about a second of any write, so the profiles'
STAPM stage only takes effect where STT is disabled. Sustained power is
governed by the slow limit either way. See
[docs/troubleshooting.md](docs/troubleshooting.md) for the details.

## Install On Fedora

### COPR RPM

```bash
sudo dnf copr enable matteo407/elitebook-thermal-profile
sudo dnf install elitebook-thermal-profile
```

If DNF weak dependencies are disabled:

```bash
sudo dnf install elitebook-thermal-profile ryzenadj
```

Optional GNOME Shell indicator:

```bash
sudo dnf install gnome-shell-extension-elitebook-thermal-profile
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

After installing the RPM, enable the runtime services explicitly:

```bash
sudo systemctl enable --now elitebook-thermal-profile.service
sudo systemctl enable --now elitebook-idle-watcher.service
sudo systemctl enable --now elitebook-steam-game-watcher.service
sudo systemctl enable --now elitebook-power-guard.timer
sudo systemctl start elitebook-power-guard.service
```

### Source Installer

```bash
sudo dnf install tuned python3 polkit
git clone https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning.git
cd hp-elitebook-845-g8-ryzen-tuning
sudo ./scripts/install.sh
```

The installer detects the distribution, checks for `python3`, `flock`,
RyzenAdj, and (on Fedora) `tuned-adm`, then prints an install hint using the
right package manager and package names if anything is missing. `pkexec`
is required only when installing the optional GNOME Shell indicator.

To see what it detected without installing anything:

```bash
./scripts/install.sh --print-platform
```

To skip the Steam game watcher:

```bash
sudo ./scripts/install.sh --without-steam-watcher
```

To skip the idle overlay watcher:

```bash
sudo ./scripts/install.sh --without-idle-watcher
```

To skip the update guard timer:

```bash
sudo ./scripts/install.sh --without-power-guard
```

To install on a different laptop after reviewing the profile values:

```bash
sudo ./scripts/install.sh --force
```

To build a pinned RyzenAdj from source when no `ryzenadj` binary is installed:

```bash
sudo dnf install cmake gcc-c++ make pciutils-devel curl tar
sudo ./scripts/install.sh --build-ryzenadj
```

Optional btrfs swapfile hibernate preflight:

```bash
sudo ./scripts/install.sh --with-hibernate-preflight
```

See the Hibernate Preflight section below for the required one-time configuration.

Optional GNOME Shell indicator:

```bash
sudo ./scripts/install.sh --with-gnome-extension
```

After installing the GNOME extension, enable it from the Extensions app or with:

```bash
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

On Wayland, a logout/login may be needed after installing a local extension.

The GNOME indicator intentionally exposes only `Auto`, `Game`, and `Quiet`. `performance`, `battery`, and `battery-saver` remain technical profiles available to automation or the CLI, not primary daily UI choices.

## Install On Ubuntu Or Debian

Experimental. The installer, update guard, and tests are distribution aware and
the platform logic is exercised in CI on Ubuntu runners, but the profiles have
not been validated on a physical Ubuntu machine yet. Fedora stays the primary
validated path.

Download `elitebook-thermal-profile_*_all.deb` and the `ryzenadj_*.deb` matching
your Ubuntu release from the
[latest release](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/releases/latest),
then:

```bash
sudo apt install ./ryzenadj_*.deb ./elitebook-thermal-profile_*.deb
```

Like the RPM, the packages install files without starting hardware tuning;
enable the units explicitly afterwards. RyzenAdj is shipped because neither
Debian nor Ubuntu package it, and without it the SMU layer is unavailable.

To install from source instead:

```bash
sudo apt install python3 util-linux cmake g++ make libpci-dev curl tar
git clone https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning.git
cd hp-elitebook-845-g8-ryzen-tuning
sudo ./scripts/install.sh --build-ryzenadj
```

Two things differ from Fedora and are worth reading before you start:

- **Secure Boot puts the kernel in lockdown**, which blocks the RyzenAdj SMU
  writes this project is built around. Check with
  `cat /sys/kernel/security/lockdown`; it should read `[none] ...`.
- **There is no tuned**, so CPU policy is applied directly through sysfs and
  SMU, and `power-profiles-daemon` is masked, which disables GNOME's power mode
  selector.

Full guide, including verification and uninstall: [docs/ubuntu.md](docs/ubuntu.md).

## Use

```bash
sudo elitebook-thermal-profile auto
sudo elitebook-thermal-profile ac
sudo elitebook-thermal-profile performance
sudo elitebook-thermal-profile battery
sudo elitebook-thermal-profile battery-saver
sudo elitebook-thermal-profile gaming
sudo elitebook-thermal-profile cool
```

`auto` maps to `ac` when plugged in, `battery` when unplugged, and `battery-saver` when unplugged at or below the low-battery threshold. The default threshold is 20% and can be changed with `ELITEBOOK_LOW_BATTERY_THRESHOLD`.

Manual profiles intentionally win over system automation. Running `sudo elitebook-thermal-profile auto` clears the manual override and returns control to AC/battery automation. The Steam watcher also respects manual overrides.

Low-battery protection is the exception: when the systemd/udev automation sees the battery at or below the threshold, it may override an active manual or Steam profile and apply `battery-saver`. This protects unattended systems from continuing a high-power workload until firmware cutoff.

To see what is actually in force, including whether the SMU limits reached the
hardware and the current package temperature:

```bash
elitebook-thermal-profile status
```

That needs no root. The raw state files are also readable directly:

```bash
cat /run/elitebook-thermal-profile/current
cat /run/elitebook-thermal-profile/idle-watcher
cat /run/elitebook-thermal-profile/guard
```

## Changing the profile values

The built-in numbers were measured on one machine. To use different ones, edit
`/etc/elitebook-thermal-profile/profiles.conf` rather than the installed
script: it is a configuration file in both packages, so upgrades will not
overwrite it.

```ini
# a smaller chassis that cannot hold the tested sustained envelope
AC_SLOW_MW=15000
AC_APU_MW=15000
```

```bash
sudo elitebook-thermal-profile auto
elitebook-thermal-profile status
```

Values outside a safe range are refused with a message and the built-in
default is kept. Full reference: [docs/configuration.md](docs/configuration.md).

## Update Guard

`elitebook-power-guard.timer` runs after boot and then periodically. It is deliberately conservative: it does not versionlock Fedora packages, pin kernels, or block upgrades. Instead it repairs the invariants this project owns:

- `tuned-ppd.service` and `power-profiles-daemon.service` stay masked so GNOME's stock Power Mode backend cannot take over EPP policy; units that the distribution does not ship are skipped rather than masked
- `elitebook-thermal-profile`, idle watcher, and Steam watcher stay enabled
- udev power-supply rules are reloaded
- hardware, RyzenAdj presence, and `amd-pstate-epp` sysfs shape are checked
- `auto` is reapplied with `ELITEBOOK_PROFILE_SOURCE=system-auto`, so manual overrides are preserved except for the low-battery `battery-saver` guard

If the full RyzenAdj profile cannot be applied after an update, the guard writes `/run/elitebook-thermal-profile/fallback` and applies a direct sysfs fallback: conservative EPP/frequency on battery, or a moderate 3.0 GHz cap on AC. That fallback is meant to preserve thermals and battery until the RyzenAdj/kernel issue is fixed, not as a normal operating mode.

## Hibernate Preflight

Hibernating to a btrfs swapfile is fragile by default: a regenerated swapfile
silently changes its physical offset, SELinux relabeling can break swap
activation, and kernel lockdown blocks the resume path. A stale
`resume_offset` produces a machine that fails to resume or, worse, resumes
from a corrupted image.

`elitebook-hibernate-preflight` fails closed instead. It runs as
`ExecStartPre=` of `systemd-hibernate.service` and
`systemd-suspend-then-hibernate.service` and aborts the hibernate unless
everything matches the configuration in `/etc/elitebook-hibernate.conf`:

- the configured swapfile is active swap and large enough for the image plus 2 GiB
- its SELinux type is `swapfile_t` when SELinux is enforcing
- its current btrfs physical offset still matches the configured `RESUME_OFFSET`
- kernel lockdown is `none`
- both the default boot entry and the running kernel carry the matching
  `resume=UUID=` and `resume_offset=` arguments

On success it programs `/sys/power/resume`, `/sys/power/resume_offset`, and
`/sys/power/image_size` before systemd continues.

One-time setup after `--with-hibernate-preflight`:

```bash
sudoedit /etc/elitebook-hibernate.conf   # fill in the values for your machine
sudo elitebook-hibernate-preflight check-config
```

The configuration template documents how to derive each value
(`findmnt -no UUID -T /swap`, `btrfs inspect-internal map-swapfile -r ...`).
The preflight intentionally targets Fedora-style setups: it uses `grubby` to
inspect the default boot entry and `btrfs-progs` for the swapfile offset.

## Uninstall

```bash
sudo ./scripts/install.sh --uninstall
```

The compatibility wrapper still works:

```bash
sudo ./scripts/uninstall.sh
```

To keep a RyzenAdj binary installed by `--build-ryzenadj`:

```bash
sudo ./scripts/install.sh --uninstall --keep-ryzenadj
```

To remove the optional GNOME extension as well:

```bash
sudo ./scripts/install.sh --uninstall --gnome-extension
```

Uninstall stops and disables the `elitebook-*` units, removes installed binaries, removes the udev rule, sleep hook, and recorded backend, unmasks the stock power profile services, and hands CPU policy back to the distribution default: `tuned-adm profile balanced` on Fedora, or re-enabled `power-profiles-daemon` on Ubuntu and Debian.

## Related Work

This project does not invent the category of Linux Ryzen power tuning. It builds on existing tools and adds the integration layers needed to run them as a daily driver on an HP business Cezanne laptop.

Prior art and dependencies:

- **[RyzenAdj](https://github.com/FlyGoat/RyzenAdj)** by FlyGoat. The CLI used to write SMU power limits on AMD Ryzen mobile parts. Pinned, SHA256-verified, and optionally built from source by the installer. Not vendored, not forked. Every SMU limit applied by the profiles in this repository goes through RyzenAdj.
- **`ryzen-ppd`** by xsmile. A Python daemon that switches RyzenAdj profiles on AC/battery transitions. This repository covers the same need with a systemd/udev approach, plus the additional layers below.
- **`ryzenadj-control`** by h4us0x. A PyQt6 GUI for sending RyzenAdj commands manually. Complementary scope: this project is service-driven, not a manual cockpit.
- **`SimpleDeckyTDP`**. A Decky plugin focused on the Steam Deck. Same SMU mechanism, different ecosystem and target hardware.
- **`auto-power-profile`**. Switches `power-profiles-daemon` profiles based on CPU usage. Operates one layer above SMU; this project's update guard intentionally remasks `power-profiles-daemon` so the two do not fight over EPP policy.

What this repository adds on top of those building blocks, integrated for HP business Cezanne laptops as a daily driver:

- udev-driven AC/battery profile switching, not a polling daemon
- a two-stage idle overlay watcher that respects stricter base profiles such as `battery-saver`
- a Steam game watcher that scans `/proc` rarely and exits cleanly when no game is running
- an update guard timer that reapplies profile invariants after `dnf upgrade`, including remasking `tuned-ppd` and `power-profiles-daemon`
- an opt-in hibernate preflight check that validates swap layout, lockdown, and SELinux state before allowing hibernation
- a native GNOME Shell extension exposing only three meaningful daily actions (`Auto`, `Game`, `Quiet`)
- hardened systemd sandboxes with `CapabilityBoundingSet`, `SystemCallFilter`, `MemoryDenyWriteExecute`, `PrivateNetwork`, `ProtectSystem=strict`, and related directives applied to every long-running unit

Framing notes:

- This is userland integration on top of RyzenAdj and AMD P-State. It is not a kernel project and does not modify Ryzen firmware behavior.
- Where another project already owns a layer (RyzenAdj for SMU writes, AMD P-State for EPP, GNOME for power UI), this repository delegates to it.
- Development was AI-assisted using Codex and Claude. Profile values, the hardware whitelist, and runtime behavior were validated on real hardware on Fedora.

## Threat Model & Limits

This project does:

- Apply local thermal, EPP, boost, frequency, and SMU power-limit policy for supported HP AMD laptops
- Reapply that policy after boot, AC/battery changes, resume, Steam game detection, idle transitions, and Fedora package updates
- Fail closed on unknown hardware unless `ELITEBOOK_THERMAL_FORCE=1` is set
- Provide an uninstall path that returns Fedora power management to the stock balanced baseline

This project does not:

- Bypass firmware thermal safety limits
- Guarantee support for every Ryzen APU generation or OEM BIOS
- Auto-update itself or download code in the background
- Collect telemetry, analytics, hardware inventory, or usage data

The main trust boundary is root execution on the local machine. Installer and runtime scripts write to systemd, udev, `/run`, CPU sysfs, and RyzenAdj-accessible SMU controls. Review `docs/safety.md` and the profile values before forcing unsupported hardware.

## Safety

This changes Ryzen SMU limits through RyzenAdj and writes CPU policy settings through sysfs. It is provided as a field-tested configuration for one laptop model, not as a universal Ryzen tuning recipe.

Read [docs/safety.md](docs/safety.md) before adapting it to other machines.

## Roadmap

- Consider renaming the public repository to `cezanne-thermal-profile` or `hp-amd-thermal-tuner` before a broader release. The current repository name is accurate for the original test laptop but too narrow for the validated Cezanne hardware table above.
- RPM spec cleanup for `/usr/libexec` and packaged systemd units
- More test reports across BIOS versions
- Validate the Ubuntu path on physical hardware, then drop the experimental label in [docs/ubuntu.md](docs/ubuntu.md)
- Optional AUR and `.deb` packages after usage reports justify the maintenance cost; the source installer already supports Ubuntu and Debian
