# Fedora Notes

Fedora is the primary tested distribution for this repository.

## Packages

```bash
sudo dnf install tuned python3 polkit lm_sensors
```

RyzenAdj is not vendored here. Install it separately and make sure one of these works:

```bash
/usr/local/sbin/ryzenadj -i
/usr/local/bin/ryzenadj -i
/usr/bin/ryzenadj -i
```

## Install

From the repository root:

```bash
sudo ./scripts/install-fedora.sh
```

Without the Steam game watcher:

```bash
sudo ./scripts/install-fedora.sh --without-steam-watcher
```

With the GNOME Shell indicator:

```bash
sudo ./scripts/install-fedora.sh --with-gnome-extension
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

Log out and back in if GNOME Shell does not load the extension immediately.

## Service Checks

```bash
systemctl status elitebook-thermal-profile.service
systemctl status elitebook-steam-game-watcher.service
cat /run/elitebook-thermal-profile/current
```

## AC/Battery Automation

The udev rules trigger when `power_supply` devices with `POWER_SUPPLY_TYPE=Mains` or `POWER_SUPPLY_TYPE=Battery` change state. The battery rule is what lets `auto` switch into `battery-saver` as charge drops, not only when AC is unplugged.

If your laptop exposes a different power supply layout, inspect it with:

```bash
udevadm info --query=property --path=/sys/class/power_supply/AC
udevadm info --query=property --path=/sys/class/power_supply/BAT0
ls /sys/class/power_supply
```

Then adjust `udev/90-elitebook-thermal-profile.rules`.
