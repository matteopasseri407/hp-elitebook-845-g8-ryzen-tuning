# Fedora Notes

Fedora is the primary tested distribution for this repository.

Current distribution status: Fedora 44 COPR/RPM packaging is published and
tested. The source installer remains supported, especially when you want it to
build the pinned RyzenAdj release locally.

## Packages

COPR RPM:

```bash
sudo dnf copr enable matteo407/elitebook-thermal-profile
sudo dnf install elitebook-thermal-profile
```

With default DNF weak dependencies, the RPM install also pulls `ryzenadj` from
the same COPR. If weak dependencies are disabled:

```bash
sudo dnf install elitebook-thermal-profile ryzenadj
```

Optional GNOME Shell indicator:

```bash
sudo dnf install gnome-shell-extension-elitebook-thermal-profile
```

Source installer dependencies:

```bash
sudo dnf install tuned python3 polkit lm_sensors
```

RyzenAdj is not vendored into this repository, but it is packaged in the same
COPR from upstream FlyGoat `v0.17.0`. Make sure one of these works before
expecting full SMU power-limit control:

```bash
/usr/local/sbin/ryzenadj -i
/usr/local/bin/ryzenadj -i
/usr/bin/ryzenadj -i
```

If RyzenAdj is missing or blocked by Secure Boot/kernel lockdown, this project
still applies the sysfs fallback controls for EPP, boost, and CPU max frequency.
That fallback is useful, but it is not equivalent to full SMU tuning.

## Install From Source

From the repository root:

```bash
sudo ./scripts/install.sh
```

Without Steam game detection:

```bash
sudo ./scripts/install.sh --without-steam-watcher
```

Without the idle overlay:

```bash
sudo ./scripts/install.sh --without-idle-watcher
```

Both flags are still accepted. Steam detection and the idle overlay now run
inside the one service, so these flags do not skip a separate unit. They add a
systemd drop-in that sets `ELITEBOOK_STEAM_DETECTION=0` or
`ELITEBOOK_IDLE_OVERLAY=0` for the service.

Without the update guard timer:

```bash
sudo ./scripts/install.sh --without-power-guard
```

With the GNOME Shell indicator:

```bash
sudo ./scripts/install.sh --with-gnome-extension
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

Log out and back in if GNOME Shell does not load the extension immediately.

On Wayland, GNOME Shell can keep an already-loaded extension module cached even after copying a newer `extension.js`. If the menu still shows the previous UI after an update, log out and back in. A simple disable/enable cycle may not be enough.

## GNOME Stock Power Mode

Fedora may expose the stock GNOME Power Mode quick setting through `tuned-ppd`, even when `power-profiles-daemon` is not installed. This repository keeps `tuned` as the tuning backend, but the extra GNOME Power Mode selector can become confusing because the EliteBook profile service is already managing EPP, RyzenAdj limits, and the idle overlay.

To remove that stock GNOME selector while keeping `tuned` active:

```bash
sudo systemctl mask --now tuned-ppd.service
```

To restore it:

```bash
sudo systemctl unmask tuned-ppd.service
sudo systemctl enable --now tuned-ppd.service
```

The default Fedora install also enables `elitebook-power-guard.timer`. The timer
keeps `tuned-ppd.service` and `power-profiles-daemon.service` masked after future
package changes, but it does not pin Fedora packages or block kernel updates.

## Service Checks

```bash
systemctl status elitebook-thermal-profile.service
systemctl status elitebook-power-guard.timer
cat /run/elitebook-thermal-profile/current
cat /run/elitebook-thermal-profile/idle-watcher
cat /run/elitebook-thermal-profile/guard
```

The idle overlay is a staged step inside the service, not a profile replacement. Soft idle starts after a few quiet seconds with low-power EPP and no frequency cap. Deep idle starts only after longer quiet, then caps the frequency at 1.8 GHz (below the base clock, so boost cannot engage) and lowers the SMU limits. Any real CPU load restores the profile in force: `ac`, `battery`, `gaming`, or the manual choice. The state file keeps the name `idle-watcher` from the earlier separate watcher, and the GNOME indicator reads it.

The GNOME indicator keeps the manual surface small on purpose: `Auto`, `Game`, and `Quiet`. Battery-specific profiles and the `performance` profile are still active underneath through automation or the CLI, but they are shown as current state instead of extra daily buttons.

## AC/Battery Automation

The service reads the power source and the battery level itself, once a second.
It does not depend on udev events. A charge that drops to the `battery-saver`
threshold (20% by default) switches the profile in the same way as unplugging
the charger does.

If your laptop exposes a different power supply layout, inspect it with:

```bash
ls /sys/class/power_supply
cat /sys/class/power_supply/*/type
```

The daemon takes AC state from `AC/online` or the first `Mains` supply, and the
charge level from the first `Battery` supply (`on_ac_power` and
`battery_device` in `src/elitebook_common.py`). When none of them answers, the
daemon treats the machine as running on battery.
