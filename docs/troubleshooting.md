# Troubleshooting

## RyzenAdj Not Found

Install RyzenAdj or set the path explicitly:

```bash
sudo RYZENADJ=/path/to/ryzenadj elitebook-thermal-profile ac
```

The script searches:

- `/usr/local/sbin/ryzenadj`
- `/usr/local/bin/ryzenadj`
- `/usr/bin/ryzenadj`
- `ryzenadj` in `PATH`

## Unsupported Hardware

The default guard only allows the tested HP EliteBook 845 G8 with Ryzen 7 PRO 5850U.

To inspect what the machine reports:

```bash
cat /sys/class/dmi/id/sys_vendor
cat /sys/class/dmi/id/product_name
grep -m1 'model name' /proc/cpuinfo
```

To override the guard:

```bash
sudo ELITEBOOK_THERMAL_FORCE=1 elitebook-thermal-profile ac
```

## GNOME Extension Does Not Appear

Check:

```bash
gnome-extensions list | grep elitebook
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

On Wayland, log out and back in after installing a local extension.

If the extension appears but still shows an older menu after updating files, log out and back in. GNOME Shell can keep the old extension module cached for the current Wayland session; disable/enable may not reload the JavaScript code.

## GNOME Stock Power Mode Still Appears

On Fedora, the stock GNOME Power Mode quick setting may be provided by `tuned-ppd` instead of `power-profiles-daemon`.

If you want the EliteBook profile service to be the only power policy surface:

```bash
sudo systemctl mask --now tuned-ppd.service
```

Keep `tuned.service` running. The EliteBook profile script still uses `tuned-adm`.

## GNOME Button Asks For A Password

That is expected. The extension uses `pkexec` to run the profile switcher as root. This repository does not install a passwordless polkit rule by default.

## Steam Watcher Does Not Switch To Gaming

Run one scan manually:

```bash
sudo elitebook-steam-game-watcher once
```

Then check:

```bash
systemctl status elitebook-steam-game-watcher.service
cat /run/elitebook-thermal-profile/current
cat /run/elitebook-thermal-profile/steam-game-watcher
```

The watcher detects Steam game processes by reading process environment variables such as `SteamGameId`, `SteamAppId`, and `STEAM_COMPAT_APP_ID` from descendants of the Steam process. It intentionally does not switch just because the Steam client is open.

## Manual Profile Does Not Change Automatically

This is by design. Manual profile selections win until you run:

```bash
sudo elitebook-thermal-profile auto
```

The exception is low-battery protection. If the battery is at or below the configured threshold, system automation can override manual or Steam-driven profiles and apply `battery-saver`.
