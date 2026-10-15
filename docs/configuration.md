# Configuration

The built-in profile values were measured on an HP EliteBook 845 G8 with a
Ryzen 7 PRO 5850U. Every other supported model gets the same numbers, and a
smaller chassis or a 6-core part may not hold them. `profiles.conf` is how you
change that without forking the project or editing a file your package manager
owns.

## Where it lives

```
/etc/elitebook-thermal-profile/profiles.conf
```

Both packages install it fully commented out, and both mark it as a
configuration file, so your edits survive upgrades. The source installer
creates it only when it is not already there.

A reference copy with every key documented is at
[`config/profiles.conf.example`](../config/profiles.conf.example).

## Format

Plain `KEY=VALUE`, one per line. `#` starts a comment. The file is parsed, not
executed: nothing in it can run commands, even though the daemon runs as
root.

Keys are `<PROFILE>_<VALUE>`:

| Part | Accepted |
| --- | --- |
| profile | `AC`, `PERFORMANCE`, `BATTERY`, `BATTERY_SAVER`, `GAMING`, `COOL` |
| power | `STAPM_MW`, `FAST_MW`, `SLOW_MW`, `APU_MW` — milliwatts, 4000-45000 |
| thermal | `TCTL_C` — degrees Celsius, 60-100 |
| policy | `EPP` — `performance`, `balance_performance`, `balance_power`, `power` |
| devices | `RUNTIME_PM` — `auto`, `default`; `PANEL_POWER_SAVINGS` — 0-4 |

Only write down what you want to change. Anything absent keeps its built-in
value, so an empty file behaves exactly like no file.

## What the values mean

- **`SLOW_MW`** is the sustained power envelope, and the one that matters most:
  it decides how much heat the machine produces during long compiles, video
  calls, or anything else that runs for minutes rather than seconds. Lower it
  if the laptop still gets too hot.
- **`FAST_MW`** is the short burst limit. Keeping it high is what makes the
  machine feel responsive; lowering it makes everything feel slower.
- **`APU_MW`** is the sustained limit for the APU as a whole.
- **`STAPM_MW`** is ignored on this platform. The firmware's Skin Temperature
  Tracking controller owns it and rewrites it within a second, which is
  measured in [measurements.md](measurements.md). Changing it does nothing here.
- **`TCTL_C`** is the temperature the firmware aims at.
- **`EPP`** is the hint passed to the CPU scaling driver.
- **`VRMMAX_MA`** is the VRM peak current limit (EDC), in mA. It caps the
  current spike of an all-core burst, such as a local LLM starting a long
  prompt, which on battery can brown the pack out and switch the laptop off.
  `battery` uses 45000 and `battery-saver` 30000. On battery the
  `BATTERY_VRMMAX_MA` value also holds every other profile, including a
  manual choice and a Steam game, so picking `gaming` on battery cannot lift
  it. Profiles without a value use the firmware's own limit, recorded when the
  service first starts after boot.
- **`RUNTIME_PM`** decides whether idle PCI devices may power down on their
  own. `auto` (the default on `battery` and `battery-saver`) lets them; on this
  machine that means the two AMD USB controllers, which wake again on their own
  when a device needs them. `default` puts back what the kernel chose at boot.
  Display drivers and devices without a driver are never touched.
- **`PANEL_POWER_SAVINGS`** is the amdgpu panel power saving level, 0 (off) to
  4: it lowers the backlight and boosts contrast to compensate, so colors shift
  slightly. Defaults: 1 on `battery`, 3 on `battery-saver`, 0 everywhere else.

## Bad values are refused, not applied

A value that is not a number, or outside its range, is reported on stderr and
the built-in default is used instead:

```
elitebook-thermal-profile: warning: /etc/elitebook-thermal-profile/profiles.conf line 12: AC_SLOW_MW=95000 is outside the safe range 4000-45000; keeping 18000
```

The run continues. A typo in this file must never leave the machine untuned,
and the ranges exist so that numbers copied from a desktop tuning guide cannot
ask a thin laptop chassis to dissipate power it has no way of removing.

Raising values above the defaults moves the machine back towards the stock
behaviour this project exists to avoid. Lowering them is the safe direction.

## Applying and checking

The service rereads `profiles.conf` within about five seconds of a change and
applies it. No command is needed. `auto` still works if you want to reapply
at once; it also clears a manual profile choice.

```bash
sudo elitebook-thermal-profile auto     # optional: reapply now and clear a manual choice
elitebook-thermal-profile status        # confirm what is actually in force
```

`status` needs no root. It prints the active profile, whether the SMU limits
really reached the hardware, the CPU policy, the battery state, and the current
package temperature. Scripts should use `status --json` instead of parsing
that text.

```
Profile:      ac (automatic (AC/battery))
SMU limits:   applied
CPU policy:   EPP balance_power, boost on, max frequency uncapped
Power limits: sustained 18 W, burst 30 W, thermal target 90 C
Devices:      kernel defaults, panel power saving off
Idle:         off
Battery:      100% (on AC)
CPU temp:     52 C
Updated:      2026-07-29T18:41:02+02:00
```

If the SMU line says anything other than `applied`, the power limits shown are
what was requested rather than what the hardware is enforcing. See
[troubleshooting.md](troubleshooting.md).

## Is the profile actually holding?

The profiles are open loop: they set limits and never look at the result. A
chassis that cannot dissipate the configured envelope, a hot room, and thermal
paste that has dried out all look identical to a healthy machine from the
inside.

While the service is running it records the package temperature against the
active profile's target, and `status` reports it:

```
Peak:         94 C since this profile was applied (target 90 C)
Above target: 25% of 3600 samples
```

Brief excursions above the target are normal — the firmware allows short
bursts on purpose. A large share of the time above it is the signal that the
sustained envelope is too high for this machine. `elitebook-power-guard check`
says so explicitly once a quarter of the samples are above target, over at
least five minutes of data:

```
elitebook-power-guard: WARN: the active profile is not holding its thermal
target: 38% of 3600 samples above 90 C, peak 97 C. Consider lowering the
sustained limit in the profile configuration.
```

The fix is to lower `SLOW_MW` and `APU_MW` for that profile in
`profiles.conf`, then watch the same numbers again.

**Nothing adjusts itself.** The firmware already runs a thermal control loop
of its own, and a second one fighting it produces oscillation rather than a
cooler laptop — the same reason the STAPM limit is left to the firmware. This
measures and reports; the decision stays yours.

The record lives at `/run/elitebook-thermal-profile/thermal`. It starts over
only when the base profile changes (for example from `ac` to `battery`), so a
peak from this morning is never blamed on the profile you are running now.
Reasserts, idle overlays and battery level reports do not restart it. On
battery the record keeps building unless the charge crosses the
`battery-saver` threshold.

Thresholds, if the defaults do not suit your machine:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ELITEBOOK_THERMAL_MIN_SAMPLES` | `300` | Samples needed before the guard judges |
| `ELITEBOOK_THERMAL_OVER_TARGET_PERCENT` | `25` | Share above target that triggers the warning |
| `ELITEBOOK_THERMAL_WRITE_SAMPLES` | `60` | Samples between routine record writes (set on the daemon unit) |

## Environment overrides

A few settings are read from the environment instead, because they belong to
the unit or the session rather than to a profile. The unit file sets them for
the service; the CLI reads them from its own environment when it runs
`apply-once` (see the note below).

| Variable | Default | Meaning |
| --- | --- | --- |
| `ELITEBOOK_LOW_BATTERY_THRESHOLD` | `20` | Battery percentage that triggers `battery-saver` |
| `ELITEBOOK_BATTERY_SAVER_MAX_FREQ_KHZ` | `1800000` | Frequency cap used by `battery-saver` |
| `RYZENADJ` | autodetected | Explicit path to the RyzenAdj binary |

The service's environment is set in its unit. To change one of these for the
running daemon, use a drop-in:

```bash
sudo systemctl edit elitebook-thermal-profile.service
```

```ini
[Service]
Environment=ELITEBOOK_LOW_BATTERY_THRESHOLD=15
```

Then `sudo systemctl restart elitebook-thermal-profile.service`. Variables
passed on the `sudo` command line do not reach the daemon, because profile
commands are sent to it rather than run by the CLI.

### Idle overlay and Steam detection

Both run inside the service. The installer switches them off with these
variables in a drop-in when you pass `--without-idle-watcher` or
`--without-steam-watcher`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ELITEBOOK_IDLE_OVERLAY` | `1` | `0` turns the idle overlay off |
| `ELITEBOOK_STEAM_DETECTION` | `1` | `0` ignores Steam games entirely |
| `ELITEBOOK_IDLE_SAMPLE_INTERVAL` | `1` | Seconds between samples |
| `ELITEBOOK_POWER_POLL_INTERVAL` | `60` | Seconds between safety rereads of AC and battery; changes normally arrive as kernel events |
| `ELITEBOOK_STEAM_WATCH_INTERVAL_ACTIVE` | `20` | Seconds between Steam scans while Steam is open |
| `ELITEBOOK_STEAM_WATCH_INTERVAL_AC` | `30` | Seconds between Steam scans on AC with Steam closed |
| `ELITEBOOK_STEAM_WATCH_INTERVAL_BATTERY` | `120` | Seconds between Steam scans on battery with Steam closed |

The idle thresholds (how many quiet samples start soft and deep idle, and the
busy and load levels that count as quiet or busy) and the values each stage
asks for are in `IdleSettings` in `src/elitebook_profiles.py`. Each one has an
`ELITEBOOK_`-prefixed variable with the same name. The defaults are the values
the separate idle watcher used before it was merged into the service.

## Who may switch profiles

The GNOME indicator switches profiles through the D-Bus front end, and polkit
decides who may: by default the person at the active local session may,
without a password, and anyone else (SSH, an inactive session) needs an
administrator. The command line is unaffected; it still needs root.

To change that, add a rule rather than editing the shipped action file, so
the change survives upgrades. For example, to always ask for an administrator
password, remembered for a few minutes:

```js
// /etc/polkit-1/rules.d/50-elitebook-thermal-profile.rules
polkit.addRule(function(action, subject) {
    if (action.id == "io.github.matteopasseri.EliteBookThermalProfile1.set-profile") {
        return polkit.Result.AUTH_ADMIN_KEEP;
    }
});
```

Or to let only members of one group switch without a password:

```js
// /etc/polkit-1/rules.d/50-elitebook-thermal-profile.rules
polkit.addRule(function(action, subject) {
    if (action.id == "io.github.matteopasseri.EliteBookThermalProfile1.set-profile") {
        return subject.isInGroup("power") && subject.active && subject.local
            ? polkit.Result.YES
            : polkit.Result.AUTH_ADMIN;
    }
});
```

polkit picks up rule files without a restart. A refusal shows up in the
indicator as a notification, not as a fallback to `pkexec`.
