# Troubleshooting

## RyzenAdj Not Found

Install RyzenAdj or set the path explicitly:

```bash
sudo dnf copr enable matteo407/elitebook-thermal-profile
sudo dnf install ryzenadj
sudo RYZENADJ=/path/to/ryzenadj elitebook-thermal-profile ac
```

The script searches:

- `/usr/local/sbin/ryzenadj`
- `/usr/local/bin/ryzenadj`
- `/usr/bin/ryzenadj`
- `ryzenadj` in `PATH`

On Fedora, the project COPR packages upstream FlyGoat RyzenAdj `v0.17.0`.
On other distributions, install RyzenAdj from the distribution, upstream, or
use the pinned source-build path from `scripts/install.sh`.

## RyzenAdj Present But SMU Writes Fail

Secure Boot can enable kernel lockdown. Under lockdown, RyzenAdj may start but
fail to write SMU limits through `/dev/mem`.

Check lockdown state:

```bash
cat /sys/kernel/security/lockdown
```

If lockdown is not `none`, full SMU tuning may be blocked. The EliteBook stack
will still use sysfs fallback controls where available:

- AMD P-State EPP
- CPU boost on/off
- CPU max frequency caps

The fallback is conservative and keeps the machine usable, but it cannot apply
the full sustained watt/temperature profile that RyzenAdj normally handles.

## STAPM Limit Reads Back As The Fast Limit

On platforms with Skin Temperature Tracking enabled, including the HP
EliteBook 845 G8, the firmware STT controller owns the STAPM limit. RyzenAdj
accepts the write and reports success, but the SMU overwrites the value within
about one second: STT replaces the STAPM limit with the fast limit, or with
the STT power value when the chassis skin temperature approaches its limit.

Check whether STT is active:

```bash
sudo ryzenadj -i | grep "STT LIMIT APU"
```

A non-zero STT limit means `--stapm-limit` writes will not stick. Measured on
the 845 G8: a STAPM write of 18 W reads back as 30 W (the fast limit) in under
half a second, so periodic re-assert loops are pointless and this stack does
not attempt them.

This does not weaken the profiles. Sustained package power is governed by the
slow limit, which STT does not touch; the configured STAPM stage simply does
not exist on STT hardware. The profiles keep setting STAPM because it still
works on units that run with STT disabled, and because lowering the fast limit
(as the deep idle overlay does) drags the STT-managed STAPM value down with it.

Upstream reference: the RyzenAdj wiki Renoir tuning guide documents the STT
overwrite of STAPM, and on Zen3 platforms vendors can additionally clamp PM
table values while every write still reports success.

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

If you previously installed the early local UUID, disable it and enable
the public UUID:

```bash
gnome-extensions disable elitebook-thermal-profile@matteopasseri.local
gnome-extensions enable elitebook-thermal-profile@matteopasseri.github.io
```

If GNOME says the public UUID does not exist even though the files are in
`~/.local/share/gnome-shell/extensions`, log out and back in first; the
Shell extension registry is session-cached on Wayland.

## GNOME Stock Power Mode Still Appears

On Fedora, the stock GNOME Power Mode quick setting may be provided by `tuned-ppd` instead of `power-profiles-daemon`.

If you want the EliteBook profile service to be the only power policy surface:

```bash
sudo systemctl mask --now tuned-ppd.service
```

Keep `tuned.service` running. The EliteBook profile script still asks
`tuned-adm` for the matching Fedora tuned profile, but that call is
best-effort and has a 10 second timeout. If `tuned-adm` warns or hangs,
the script continues with the direct EPP, boost, frequency, and RyzenAdj
policy so the laptop does not stay in a half-applied power state.

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

## The profile applies but temperatures do not change

Check whether the SMU limits actually reached the hardware:

```bash
grep smu= /run/elitebook-thermal-profile/current
```

- `smu=ok` — the limits were applied. If temperatures are still high, the
  profile values themselves are the thing to look at.
- `smu=unavailable` — RyzenAdj is not installed. Only EPP, boost, and the
  frequency cap are active. Install RyzenAdj, or point the dispatcher at it
  with `RYZENADJ=/path/to/ryzenadj`.
- `smu=blocked` — kernel lockdown refused the write, which Secure Boot
  normally enables. Confirm with `cat /sys/kernel/security/lockdown`; anything
  other than `[none]` blocks the `/dev/mem` path RyzenAdj falls back to.
  Disabling Secure Boot in the firmware restores full control. See
  [ubuntu.md](ubuntu.md) for the alternatives.
- `smu=failed` — RyzenAdj ran and returned an error with lockdown off. Run it
  by hand to see why: `sudo ryzenadj -i`.

In the last three cases the `stapm_mw`, `fast_mw`, `slow_mw`, `apu_mw`, and
`tctl_c` values in the state file record what was requested, not what the
hardware is enforcing. `sudo elitebook-power-guard check` reports the same
condition and exits non-zero.
