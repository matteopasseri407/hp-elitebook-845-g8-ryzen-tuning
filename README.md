# HP EliteBook 845 G8 Ryzen Thermal Profiles

Thermal and power profiles for the HP EliteBook 845 G8 with the AMD Ryzen 7 PRO 5850U.

The goal is not to hard-cap the CPU. The profiles keep boost enabled and leave the maximum CPU frequency uncapped for normal work, then tune the sustained SMU power limits and the AMD P-State energy preference so the laptop can still burst hard without sitting at the stock 100 C thermal edge during sustained workloads.

Idle efficiency is handled separately by a staged idle overlay. The overlay leaves the selected profile intact, moves to a soft idle hint after a few quiet seconds, and only enters a deeper capped state after sustained quiet. Any real CPU load clears the overlay and restores the active profile.

Tested on:

- HP EliteBook 845 G8
- AMD Ryzen 7 PRO 5850U
- Fedora Linux 44
- GNOME Shell 50
- Linux 6.19 series

This is intentionally hardware-scoped. The main script refuses to run on unrecognized hardware unless `ELITEBOOK_THERMAL_FORCE=1` is set.

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
- optional GNOME Shell panel indicator: three human actions (`Auto`, `Game`, `Quiet`) while automatic `ac`, `battery`, `battery-saver`, and idle states remain status-only

The idle watcher is intentionally cheap. It samples aggregate `/proc/stat` and `/proc/loadavg` once per second, does not scan processes, and calls RyzenAdj only when entering or leaving deep idle. The Steam watcher scans `/proc` only on long intervals and is constrained with low scheduling priority, `CPUQuota=2%`, and `MemoryMax=64M`.

## Requirements

- Linux with systemd and udev
- AMD P-State or cpufreq sysfs support
- `ryzenadj` installed as `/usr/local/sbin/ryzenadj`, `/usr/local/bin/ryzenadj`, or `/usr/bin/ryzenadj`
- `tuned` recommended on Fedora
- `pkexec` only if using the GNOME Shell switcher

This repository does not vendor RyzenAdj. Install it from your distribution, COPR/AUR if available, or from the upstream project: <https://github.com/FlyGoat/RyzenAdj>

## Install On Fedora

```bash
sudo dnf install tuned python3 polkit
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

To install on a different laptop after reviewing the profile values:

```bash
sudo ./scripts/install-fedora.sh --force
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
```

## Uninstall

```bash
sudo ./scripts/uninstall.sh
```

To remove the optional GNOME extension as well:

```bash
sudo ./scripts/uninstall.sh --gnome-extension
```

## Safety

This changes Ryzen SMU limits through RyzenAdj and writes CPU policy settings through sysfs. It is provided as a field-tested configuration for one laptop model, not as a universal Ryzen tuning recipe.

Read [docs/safety.md](docs/safety.md) before adapting it to other machines.

## Roadmap

- Fedora COPR packaging
- RPM spec cleanup for `/usr/libexec` and packaged systemd units
- More test reports across BIOS versions
- Optional install profiles for other Linux distributions
