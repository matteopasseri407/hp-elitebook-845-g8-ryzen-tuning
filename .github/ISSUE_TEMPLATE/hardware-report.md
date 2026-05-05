---
name: Hardware report
about: Share measurements from an HP EliteBook 845 G8 or nearby Ryzen 5000U laptop
title: "Hardware report: <model> on <distro> <kernel>"
labels: hardware-report
assignees: ""
---

<!--
The whole point of this template is to make reports comparable across
machines and BIOS revisions. Please fill in every fenced block. If a
field does not apply, write "n/a" rather than leaving it empty.
-->

## Machine

- Laptop model:
- CPU:
- BIOS / firmware version:
- RAM (size, type, speed):
- Distribution and version:
- Kernel:
- Desktop environment / shell version:
- Ambient temperature (°C):
- Plugged in or on battery:

## Workload

Describe what was running while you took the measurements. Be specific:
"Electron IDE + AI assistant + Node dev server + browser with 30 tabs"
is much more useful than "normal use".

```text
<workload description>
```

## Profile Tested

- Profile applied (`ac` / `performance` / `battery` / `battery-saver` /
  `gaming` / `cool` / `auto`):
- Idle overlay watcher enabled (yes / no):
- Steam game watcher enabled (yes / no):
- Manual override or automation source (`manual` / `auto` /
  `system-auto` / `steam-game-watcher`):

## Sensors Output

```text
$ sensors
<paste output here>
```

## RyzenAdj Before Applying The Profile

```text
$ sudo ryzenadj -i
<paste output here>
```

## RyzenAdj After Applying The Profile

```text
$ sudo elitebook-thermal-profile <profile>
$ sudo ryzenadj -i
<paste output here>
```

## Profile State File

```text
$ cat /run/elitebook-thermal-profile/current
<paste output here>
```

## Idle Overlay State (if applicable)

```text
$ cat /run/elitebook-thermal-profile/idle-watcher
<paste output here>
```

## Observed Behavior

- Sustained CPU package temperature (°C):
- Peak CPU package temperature (°C):
- Fan noise (none / quiet / audible / loud):
- Throttling observed (yes / no):
- Battery drain rate, if on battery (e.g. % per hour):
- Subjective responsiveness (snappy / acceptable / sluggish):

## Notes

Anything else worth recording: BIOS-level settings changed, undervolt or
PPT overrides outside this project, observed regressions after a kernel
or BIOS update, gaming behavior, etc.

## Privacy Reminder

Do not paste private hostnames, tokens, raw `journalctl` lines that
include unrelated services, or screenshots that reveal anything beyond
what is necessary to reproduce or compare the measurement.
