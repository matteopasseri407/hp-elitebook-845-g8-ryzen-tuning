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
executed: nothing in it can run commands, even though the dispatcher runs as
root.

Keys are `<PROFILE>_<VALUE>`:

| Part | Accepted |
| --- | --- |
| profile | `AC`, `PERFORMANCE`, `BATTERY`, `BATTERY_SAVER`, `GAMING`, `COOL` |
| power | `STAPM_MW`, `FAST_MW`, `SLOW_MW`, `APU_MW` — milliwatts, 4000-45000 |
| thermal | `TCTL_C` — degrees Celsius, 60-100 |
| policy | `EPP` — `performance`, `balance_performance`, `balance_power`, `power` |

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

## Bad values are refused, not applied

A value that is not a number, or outside its range, is reported on stderr and
the built-in default is used instead:

```
elitebook-thermal-profile: warning: /etc/elitebook-thermal-profile/profiles.conf: AC_SLOW_MW=95000 is outside the safe range 4000-45000; keeping 18000
```

The run continues. A typo in this file must never leave the machine untuned,
and the ranges exist so that numbers copied from a desktop tuning guide cannot
ask a thin laptop chassis to dissipate power it has no way of removing.

Raising values above the defaults moves the machine back towards the stock
behaviour this project exists to avoid. Lowering them is the safe direction.

## Applying and checking

```bash
sudo elitebook-thermal-profile auto     # apply
elitebook-thermal-profile status        # confirm what is actually in force
```

`status` needs no root. It prints the active profile, whether the SMU limits
really reached the hardware, the CPU policy, the battery state, and the current
package temperature.

```
Profile:      ac (system automation)
SMU limits:   applied
CPU policy:   EPP balance_power, boost on, max frequency uncapped
Power limits: sustained 18 W, burst 30 W, thermal target 90 C
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

While the idle overlay watcher is running it records the package temperature
against the active profile's target, and `status` reports it:

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

The record lives at `/run/elitebook-thermal-profile/thermal` and resets every
time a profile is applied, so a peak from this morning is never blamed on the
profile you are running now. It requires the idle watcher: installing with
`--without-idle-watcher` leaves `status` showing only the current temperature.

Thresholds, if the defaults do not suit your machine:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ELITEBOOK_THERMAL_MIN_SAMPLES` | `300` | Samples needed before the guard judges |
| `ELITEBOOK_THERMAL_OVER_TARGET_PERCENT` | `25` | Share above target that triggers the warning |
| `ELITEBOOK_THERMAL_WRITE_SAMPLES` | `60` | Samples between routine record writes |

## Environment overrides

A few settings are read from the environment instead, because they belong to
the unit or the session rather than to a profile:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ELITEBOOK_LOW_BATTERY_THRESHOLD` | `20` | Battery percentage that triggers `battery-saver` |
| `ELITEBOOK_BATTERY_SAVER_MAX_FREQ_KHZ` | `1800000` | Frequency cap used by `battery-saver` |
| `RYZENADJ` | autodetected | Explicit path to the RyzenAdj binary |

The idle overlay watcher has its own set, documented in the header of
`src/elitebook-idle-watcher`.
