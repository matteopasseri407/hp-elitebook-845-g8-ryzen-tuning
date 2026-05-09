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

Optional GNOME Shell indicator:

```bash
sudo dnf install gnome-shell-extension-elitebook-thermal-profile
```

Source installer dependencies:

```bash
sudo dnf install tuned python3 polkit lm_sensors
```

RyzenAdj is not vendored here. Install it separately and make sure one of these works:

```bash
/usr/local/sbin/ryzenadj -i
/usr/local/bin/ryzenadj -i
/usr/bin/ryzenadj -i
```

## Install From Source

From the repository root:

```bash
sudo ./scripts/install-fedora.sh
```

Without the Steam game watcher:

```bash
sudo ./scripts/install-fedora.sh --without-steam-watcher
```

Without the idle overlay watcher:

```bash
sudo ./scripts/install-fedora.sh --without-idle-watcher
```

Without the update guard timer:

```bash
sudo ./scripts/install-fedora.sh --without-power-guard
```

With the GNOME Shell indicator:

```bash
sudo ./scripts/install-fedora.sh --with-gnome-extension
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
systemctl status elitebook-idle-watcher.service
systemctl status elitebook-steam-game-watcher.service
systemctl status elitebook-power-guard.timer
cat /run/elitebook-thermal-profile/current
cat /run/elitebook-thermal-profile/idle-watcher
cat /run/elitebook-thermal-profile/guard
```

The idle watcher is a staged overlay, not a profile replacement. Soft idle starts after a few quiet seconds with low-power EPP and no frequency cap. Deep idle starts only after longer quiet, then disables boost and uses a temporary low max frequency. Any real CPU load restores the current `ac`, `battery`, `gaming`, or manual profile.

The GNOME indicator keeps the manual surface small on purpose: `Auto`, `Game`, and `Quiet`. Battery-specific profiles and the `performance` profile are still active underneath through automation or the CLI, but they are shown as current state instead of extra daily buttons.

## AC/Battery Automation

The udev rules trigger when `power_supply` devices with `POWER_SUPPLY_TYPE=Mains` or `POWER_SUPPLY_TYPE=Battery` change state. The battery rule is what lets `auto` switch into `battery-saver` as charge drops, not only when AC is unplugged.

If your laptop exposes a different power supply layout, inspect it with:

```bash
udevadm info --query=property --path=/sys/class/power_supply/AC
udevadm info --query=property --path=/sys/class/power_supply/BAT0
ls /sys/class/power_supply
```

Then adjust `udev/90-elitebook-thermal-profile.rules`.
