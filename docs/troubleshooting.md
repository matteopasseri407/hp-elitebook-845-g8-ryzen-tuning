# Troubleshooting

## RyzenAdj Not Found

Install RyzenAdj or point the service at it explicitly:

```bash
sudo dnf copr enable matteo407/elitebook-thermal-profile
sudo dnf install ryzenadj
sudo systemctl edit elitebook-thermal-profile.service
```

In the editor that opens, add:

```ini
[Service]
Environment=RYZENADJ=/path/to/ryzenadj
```

Then restart the service with `sudo systemctl restart elitebook-thermal-profile.service`.
The daemon is the process that calls RyzenAdj, so the variable has to be set
for the service, not on the command line of a profile command.

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
half a second. The service does not run a re-assert loop for STAPM. Its
hourly full rewrite includes STAPM too, but that write does not last either.

This does not weaken the profiles. Sustained package power is governed by the
slow limit, which STT does not touch; the configured STAPM stage simply does
not exist on STT hardware. The profiles keep setting STAPM because it still
works on units that run with STT disabled, and because lowering the fast limit
(as the deep idle overlay does) drags the STT-managed STAPM value down with it.

Upstream reference: the RyzenAdj wiki Renoir tuning guide documents the STT
overwrite of STAPM, and on Zen3 platforms vendors can additionally clamp PM
table values while every write still reports success.

## The Service Stopped And Does Not Restart

The service gives up instead of retrying forever when retrying cannot help:

- exit status 78: unsupported hardware, a `RYZENADJ` path that is not
  executable, or a second daemon started while one is already running. The
  journal says which. Fix the cause, then
  `sudo systemctl restart elitebook-thermal-profile.service`.
- more than 10 crashes in 10 minutes: systemd stops restarting it so a
  crashing daemon does not drain the battery. The power guard timer starts it
  again within six hours. Run `journalctl -u elitebook-thermal-profile -b` and
  report the traceback.

While it is stopped, the last applied limits stay in force (the SMU keeps
them), and the GNOME indicator shows "Control: service not running".

## Unsupported Hardware

The default guard only allows the tested HP EliteBook 845 G8 with Ryzen 7 PRO 5850U.

To inspect what the machine reports:

```bash
cat /sys/class/dmi/id/sys_vendor
cat /sys/class/dmi/id/product_name
grep -m1 'model name' /proc/cpuinfo
```

The service checks the hardware when it starts and refuses to run on
unsupported machines. To override the guard, set the variable for the service:

```bash
sudo systemctl edit elitebook-thermal-profile.service
```

```ini
[Service]
Environment=ELITEBOOK_THERMAL_FORCE=1
```

Then restart the service. For a single test run without the service, use
`sudo ELITEBOOK_THERMAL_FORCE=1 elitebook-thermal-profile apply-once ac`
(this needs the service to be stopped).

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

Keep `tuned.service` running. The daemon still asks
`tuned-adm` for the matching Fedora tuned profile, but that call is
best-effort and has a 10 second timeout. If `tuned-adm` warns or hangs,
the daemon continues with the direct EPP, boost, frequency, and RyzenAdj
policy so the laptop does not stay in a half-applied power state.

## GNOME Button Asks For A Password

That is expected. The extension uses `pkexec` to run the profile switcher as root. This repository does not install a passwordless polkit rule by default.

## Steam Game Does Not Switch To Gaming

Check what the service has seen:

```bash
elitebook-thermal-profile status
grep source= /run/elitebook-thermal-profile/current
journalctl -u elitebook-thermal-profile.service -n 50
```

A game shows up as `source=steam-game-watcher` in the state file. The name is
kept from the earlier separate watcher because the GNOME indicator matches on
it. The journal logs `Steam game detected` when a game is found and `Steam game
ended` when it stops.

The daemon detects games by reading process environment variables such as `SteamGameId`, `SteamAppId`, and `STEAM_COMPAT_APP_ID` from descendants of the Steam process. It scans every 20 seconds while Steam is open, and every 30 seconds on AC or every 120 seconds on battery while Steam is closed, so a game can take that long to be noticed. It intentionally does not switch just because the Steam client is open.

If Steam detection is switched off, the service never switches to `gaming`.
Check the drop-in for `ELITEBOOK_STEAM_DETECTION=0`, which the installer writes
when it is run with `--without-steam-watcher`.

## Manual Profile Does Not Change Automatically

This is by design. A manual profile choice (for example `sudo elitebook-thermal-profile cool`) wins until you run:

```bash
sudo elitebook-thermal-profile auto
```

A manual choice survives a restart of the service, but not a reboot.

The exception is low-battery protection. If the battery is at or below the configured threshold, the service overrides the manual choice and any Steam-driven profile, applies `battery-saver`, and clears the manual choice.

## The profile applies but temperatures do not change

Check whether the SMU limits actually reached the hardware:

```bash
grep smu= /run/elitebook-thermal-profile/current
```

- `smu=ok` — the limits were applied. If temperatures are still high, the
  profile values themselves are the thing to look at.
- `smu=unavailable` — RyzenAdj is not installed. Only EPP, boost, and the
  frequency cap are active. Install RyzenAdj, or point the service at it with
  `RYZENADJ` (see [RyzenAdj Not Found](#ryzenadj-not-found)).
- `smu=blocked` — kernel lockdown refused the write, which Secure Boot
  normally enables. Confirm with `cat /sys/kernel/security/lockdown`; anything
  other than `[none]` blocks the `/dev/mem` path RyzenAdj falls back to.
  Disabling Secure Boot in the firmware restores full control. See
  [ubuntu.md](ubuntu.md) for the alternatives.
- `smu=failed` — RyzenAdj ran and returned an error with lockdown off. Run it
  by hand to see why: `sudo ryzenadj -i`.

For the last two states the service retries the SMU write every five minutes,
so a fixed cause takes effect without a restart.

In the last three cases the `stapm_mw`, `fast_mw`, `slow_mw`, `apu_mw`, and
`tctl_c` values in the state file record what was requested, not what the
hardware is enforcing. `sudo elitebook-power-guard check` reports the same
condition and exits non-zero.
