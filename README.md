# HP EliteBook 845 G8 Ryzen Thermal Profiles

Thermal and power profiles for the HP EliteBook 845 G8 with the AMD Ryzen 7 PRO 5850U.

The goal is not to hard-cap the CPU. The profiles keep boost enabled and leave the maximum CPU frequency uncapped, then tune the sustained SMU power limits and the AMD P-State energy preference so the laptop can still burst hard without sitting at the stock 100 C thermal edge during sustained workloads.

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
| `ac` | Plugged in daily work | on | uncapped | `balance_performance` | 30 W | 18 W | 90 C |
| `battery` | Unplugged work | on | uncapped | `balance_power` | 30 W | 15 W | 88 C |
| `gaming` | Steam game process detected | on | uncapped | `balance_performance` | 30 W | 23 W | 92 C |
| `cool` | Quiet/cool fallback | on | uncapped | `power` | 22 W | 12 W | 85 C |

There is no `stock` profile. On the tested unit, the stock firmware/SMU behavior allowed sustained 100-102 C operation under real development workloads, which was exactly what this project was built to avoid.

## What It Installs

- `elitebook-thermal-profile`: applies `auto`, `ac`, `battery`, `gaming`, or `cool`
- systemd oneshot service: reapplies `auto` at boot
- udev rule: reapplies `auto` when AC power changes
- system sleep hook: reapplies `auto` after resume
- optional Steam game watcher: switches to `gaming` only while a real Steam game process is detected
- optional GNOME Shell panel indicator: white bolt/controller/leaf/cool icons with a profile switcher

The Steam watcher is designed to be low impact. It scans `/proc`, uses long idle intervals, and the systemd unit constrains it with low scheduling priority, `CPUQuota=2%`, and `MemoryMax=64M`.

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

Optional GNOME Shell indicator:

```bash
sudo ./scripts/install-fedora.sh --with-gnome-extension
```

After installing the GNOME extension, enable it from the Extensions app or with:

```bash
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

On Wayland, a logout/login may be needed after installing a local extension.

## Use

```bash
sudo elitebook-thermal-profile auto
sudo elitebook-thermal-profile ac
sudo elitebook-thermal-profile battery
sudo elitebook-thermal-profile gaming
sudo elitebook-thermal-profile cool
```

`auto` maps to `ac` when plugged in and `battery` when unplugged.

Manual profiles intentionally win over system automation. Running `sudo elitebook-thermal-profile auto` clears the manual override and returns control to AC/battery automation. The Steam watcher also respects manual overrides.

Current state is exposed at:

```bash
cat /run/elitebook-thermal-profile/current
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

