# HP AMD Ryzen Thermal Profiles

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
- optional GNOME Shell panel indicator: three human actions (`Auto`, `Game`, `Quiet`) while automatic `ac`, `battery`, `battery-saver`, and idle states remain status-only

The idle watcher is intentionally cheap. It samples aggregate `/proc/stat` and `/proc/loadavg` once per second, does not scan processes, preserves stricter base frequency caps such as `battery-saver`, and calls RyzenAdj only when entering or leaving deep idle. The Steam watcher scans `/proc` only on long intervals and is constrained with low scheduling priority, `CPUQuota=2%`, and `MemoryMax=64M`.

## Requirements

- Linux with systemd and udev
- AMD P-State or cpufreq sysfs support
- `ryzenadj` installed as `/usr/local/sbin/ryzenadj`, `/usr/local/bin/ryzenadj`, or `/usr/bin/ryzenadj`
- `tuned` recommended on Fedora
- `pkexec` only if using the GNOME Shell switcher
- `flock` from util-linux, normally installed by default on Fedora
- Kernel lockdown set to `none` for full RyzenAdj SMU control through `/dev/mem`

Secure Boot commonly enables kernel lockdown. When lockdown is active, RyzenAdj may not be able to write SMU limits through `/dev/mem`; the installer warns and asks for confirmation before continuing. EPP, CPU max frequency, and boost sysfs controls still degrade cleanly.

This repository does not vendor RyzenAdj. Install it from your distribution, COPR/AUR if available, from the upstream project, or let the Fedora installer build a pinned source release:

```bash
sudo ./scripts/install-fedora.sh --build-ryzenadj
```

The source-build path pins RyzenAdj `v0.17.0` at commit `67aa960e71bf4cdd140b47d42c0c62c4cded68d1` and verifies SHA256 `848ac9d86ff65d30f5e2c8600aac2613f0f10003b0d6f0e516a54761d7345d44` before compiling.

## Install On Fedora

```bash
sudo dnf install tuned python3 polkit
git clone https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning.git
cd hp-elitebook-845-g8-ryzen-tuning
sudo ./scripts/install-fedora.sh
```

The installer checks for `python3`, `tuned-adm` and RyzenAdj, then
prints an explicit `dnf install` hint if anything is missing. `pkexec`
is required only when installing the optional GNOME Shell indicator.

To skip the Steam game watcher:

```bash
sudo ./scripts/install-fedora.sh --without-steam-watcher
```

To skip the idle overlay watcher:

```bash
sudo ./scripts/install-fedora.sh --without-idle-watcher
```

To skip the update guard timer:

```bash
sudo ./scripts/install-fedora.sh --without-power-guard
```

To install on a different laptop after reviewing the profile values:

```bash
sudo ./scripts/install-fedora.sh --force
```

To build a pinned RyzenAdj from source when no `ryzenadj` binary is installed:

```bash
sudo dnf install cmake gcc-c++ make pciutils-devel curl tar
sudo ./scripts/install-fedora.sh --build-ryzenadj
```

Optional GNOME Shell indicator:

```bash
sudo ./scripts/install-fedora.sh --with-gnome-extension
```

After installing the GNOME extension, enable it from the Extensions app or with:

```bash
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

On Wayland, a logout/login may be needed after installing a local extension.

The GNOME indicator intentionally exposes only `Auto`, `Game`, and `Quiet`. `performance`, `battery`, and `battery-saver` remain technical profiles available to automation or the CLI, not primary daily UI choices.

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

Current state is exposed at:

```bash
cat /run/elitebook-thermal-profile/current
cat /run/elitebook-thermal-profile/idle-watcher
cat /run/elitebook-thermal-profile/guard
```

## Update Guard

`elitebook-power-guard.timer` runs after boot and then periodically. It is deliberately conservative: it does not versionlock Fedora packages, pin kernels, or block upgrades. Instead it repairs the invariants this project owns:

- `tuned-ppd.service` and `power-profiles-daemon.service` stay masked so GNOME's stock Power Mode backend cannot take over EPP policy
- `elitebook-thermal-profile`, idle watcher, and Steam watcher stay enabled
- udev power-supply rules are reloaded
- hardware, RyzenAdj presence, and `amd-pstate-epp` sysfs shape are checked
- `auto` is reapplied with `ELITEBOOK_PROFILE_SOURCE=system-auto`, so manual overrides are preserved except for the low-battery `battery-saver` guard

If the full RyzenAdj profile cannot be applied after an update, the guard writes `/run/elitebook-thermal-profile/fallback` and applies a direct sysfs fallback: conservative EPP/frequency on battery, or a moderate 3.0 GHz cap on AC. That fallback is meant to preserve thermals and battery until the RyzenAdj/kernel issue is fixed, not as a normal operating mode.

## Uninstall

```bash
sudo ./scripts/install-fedora.sh --uninstall
```

The compatibility wrapper still works:

```bash
sudo ./scripts/uninstall.sh
```

To keep a RyzenAdj binary installed by `--build-ryzenadj`:

```bash
sudo ./scripts/install-fedora.sh --uninstall --keep-ryzenadj
```

To remove the optional GNOME extension as well:

```bash
sudo ./scripts/install-fedora.sh --uninstall --gnome-extension
```

Uninstall stops and disables the `elitebook-*` units, removes installed binaries, removes the udev rule and sleep hook, unmasks Fedora's stock power profile services, and restores `tuned-adm profile balanced`.

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
- Fedora COPR packaging once the RyzenAdj dependency path is clean
- RPM spec cleanup for `/usr/libexec` and packaged systemd units
- More test reports across BIOS versions
- Optional install profiles for other Linux distributions
