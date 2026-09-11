# HP AMD Ryzen Thermal Profiles

[![CI](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/actions/workflows/ci.yml/badge.svg)](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning)](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/releases)
[![Fedora COPR](https://img.shields.io/badge/Fedora_COPR-matteo407%2Felitebook--thermal--profile-51A2DA?logo=fedora)](https://copr.fedorainfracloud.org/coprs/matteo407/elitebook-thermal-profile/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)

Linux thermal management and power tuning for HP EliteBook and ProBook laptops powered by AMD Ryzen Cezanne APUs (5000-series PRO, e.g. 5850U).

Stock firmware allows sustained temperatures around 100 °C under normal development loads, relying on thermal throttling. Rather than disabling boost or hard-capping clocks, this stack tunes sustained SMU power limits (via RyzenAdj) and energy preferences (AMD P-State EPP) so bursts remain fast while fans stay quiet.

Pure Python 3 standard library backend (`/usr/local/sbin/elitebook-*`), zero pip dependencies, typed with `mypy --strict`, atomic state updates, and an optional GNOME Shell top panel indicator.

> [!WARNING]
> **Secure Boot must be disabled for full SMU control.**
> Secure Boot activates kernel lockdown, which blocks `/dev/mem` writes. Check with `cat /sys/kernel/security/lockdown` (must read `[none]`). Without this, the stack degrades to sysfs frequency and EPP controls.

---

## Supported Hardware

Validated by default:
- **HP EliteBook 835 / 845 G7, G8, G9** (Ryzen 5 / 7 PRO 5650U, 5750U, 5850U)
- **HP ProBook 445 / 455 G8, G9** (Ryzen 5 / 7 PRO 5650U, 5750U, 5850U)

Rembrandt models (6000-series) and unlisted hardware require `ELITEBOOK_THERMAL_FORCE=1`.

---

## Profiles

| Profile | Context | Boost | Max Freq | EPP | Fast Limit | Sustained Limit | Tctl Target |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ac` | AC mains power | on | uncapped | `balance_power` | 30 W | 18 W | 90 °C |
| `performance` | Manual plugged-in heavy load | on | uncapped | `balance_performance` | 30 W | 18 W | 90 °C |
| `battery` | Battery normal work | on | uncapped | `balance_power` | 30 W | 15 W | 88 °C |
| `battery-saver` | Low battery (<= 20%) | off | 1.8 GHz | `power` | 15 W | 8 W | 80 °C |
| `gaming` | Steam game running | on | uncapped | `balance_performance` | 30 W | 23 W | 92 °C |
| `cool` | Quiet office or bed use | on | uncapped | `power` | 22 W | 12 W | 85 °C |

Custom limits can be set in `/etc/elitebook-thermal-profile/profiles.conf` without touching code.

---

## Quickstart

### Fedora (COPR RPM)
```bash
sudo dnf copr enable matteo407/elitebook-thermal-profile
sudo dnf install elitebook-thermal-profile ryzenadj
sudo dnf install gnome-shell-extension-elitebook-thermal-profile # optional GNOME indicator
```

### Ubuntu and Debian
Download `.deb` packages from [Releases](https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/releases):
```bash
sudo apt install ./ryzenadj_*.deb ./elitebook-thermal-profile_*.deb
```

### Source Installer
```bash
git clone https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning.git
cd hp-elitebook-845-g8-ryzen-tuning
sudo ./scripts/install.sh --build-ryzenadj --with-gnome-extension
```

### Enable Services
```bash
sudo systemctl enable --now elitebook-thermal-profile.service
sudo systemctl enable --now elitebook-idle-watcher.service
sudo systemctl enable --now elitebook-steam-game-watcher.service
sudo systemctl enable --now elitebook-power-guard.timer
sudo systemctl start elitebook-power-guard.service
```

---

## Daily Usage

```bash
# Check status and thermal headroom
elitebook-thermal-profile status

# JSON status for scripts and status bars
elitebook-thermal-profile status --json

# Manually switch profile (auto follows AC/battery/low-battery rules)
sudo elitebook-thermal-profile auto
sudo elitebook-thermal-profile gaming
sudo elitebook-thermal-profile cool

# Check system health, masked services, and SMU communication
sudo elitebook-power-guard check
```

---

## Documentation Hub

Detailed documentation is organized in `docs/`:

- [CODEBASE_MAP.md](CODEBASE_MAP.md): Full AST symbol map, architecture diagram, and IPC state file contracts.
- [docs/fedora.md](docs/fedora.md): Fedora RPM packaging, tuned coexistence, and GNOME power mode masking.
- [docs/ubuntu.md](docs/ubuntu.md): Ubuntu and Debian installation, secure boot configuration, and systemd setup.
- [docs/configuration.md](docs/configuration.md): Overriding limits via `/etc/elitebook-thermal-profile/profiles.conf`.
- [docs/troubleshooting.md](docs/troubleshooting.md): Diagnosing RyzenAdj errors, STT firmware overrides, and fallback states.
- [docs/measurements.md](docs/measurements.md): Thermal benchmarks, fan noise comparisons, and power curves.
- [docs/hibernate.md](docs/hibernate.md): Opt-in btrfs swapfile hibernate preflight checks.
- [docs/safety.md](docs/safety.md): Threat model, hardware boundaries, and safety limits.

---

## Uninstallation

```bash
sudo ./scripts/install.sh --uninstall --gnome-extension
```
Restores distribution power management defaults (`tuned` on Fedora, `power-profiles-daemon` on Ubuntu/Debian) and removes all system units and runtime state.
