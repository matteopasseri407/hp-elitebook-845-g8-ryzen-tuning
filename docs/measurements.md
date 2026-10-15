# Field Measurements

These are practical workstation measurements, not lab benchmarks. They describe the behavior that led to the profiles in this repository.

## Test Machine

- HP EliteBook 845 G8
- AMD Ryzen 7 PRO 5850U
- Fedora Linux 44
- GNOME Shell 50
- Linux 6.19 series
- Workload shape: Electron IDE, AI coding assistant, Node development server, browser automation, and normal desktop activity

## Stock Behavior Observed

RyzenAdj reported the stock/default SMU limits as roughly:

| Limit | Stock value |
| --- | --- |
| STAPM | 30 W |
| FAST | 30 W |
| SLOW | 25 W |
| APU SLOW | 25 W |
| Tctl target | 100 C |

Under sustained development workloads, the machine repeatedly reached about 100-102 C and relied on thermal throttling. The fan behavior was loud and the chassis cooling did not appear able to hold that stock sustained envelope comfortably.

## Earlier Emergency Fixes

Disabling boost dropped temperatures sharply, but it also removed too much performance. A fixed frequency cap was also effective thermally, but it was the wrong tradeoff for this laptop: the CPU has useful burst headroom and should not need to be permanently capped to behave well.

## Current Strategy

The current profiles keep:

- CPU boost enabled
- CPU maximum frequency uncapped
- burst power high enough for responsive work

They reduce the sustained CPU/APU envelope instead. This keeps the machine closer to the cooling system's real capacity while preserving short boost behavior.

Idle behavior is handled as a separate staged overlay instead of baking deep caps into every profile. Soft idle only changes the EPP hint after a few quiet seconds. Deep idle is delayed and then applies the more aggressive boost/frequency/SMU limits. The service leaves idle on the first busy sample, so foreground work should restore the selected profile quickly.

## Profile Notes

| Profile | Observed intent |
| --- | --- |
| `ac` | Main plugged-in work profile. Keeps burst response, uses a calmer EPP hint than the original fast profile, and targets a lower sustained thermal ceiling than stock. |
| `performance` | Manual plugged-in profile that keeps the original responsive AC EPP without the gaming power envelope. |
| `battery` | Keeps performance available on battery but shifts EPP and sustained power for better idle/light-load efficiency. |
| `battery-saver` | Automatic low-battery guard. Drops sustained power sharply, disables boost, and caps frequency so forgotten workloads drain the last battery segment more slowly. |
| `gaming` | Gives the APU more sustained room for Steam games while keeping a lower temperature target than stock. |
| `cool` | Manual quiet/cool fallback for calls, light work, or hot ambient conditions. |

## STT Owns The STAPM Limit

Measured on 2026-06-11 on the test machine, battery profile active, on battery:

- the write succeeds at the SMU mailbox level (`Successfully set
  stapm_limit to 18000`, SMU reply `0x1`)
- the very next read, under half a second later, already reports the STAPM
  limit back at 30 W, which is the profile's fast limit
- transient readings slightly below 30 W (29.1-29.9 W) appear when the chassis
  skin temperature rises, matching the STT controller actively managing the
  value (`STT LIMIT APU` reports 45 C on this machine)
- fast, slow, APU slow, and Tctl limits never drift

Conclusion: on this platform the firmware Skin Temperature Tracking controller
owns STAPM and rewrites it continuously, as documented in the RyzenAdj wiki.
The configured STAPM stage only exists on units with STT disabled; sustained
power is governed by the slow limit either way. During deep idle the
STT-managed STAPM follows the lowered fast limit (12 W), which is why idle
readings can look like the overlay value "held". No dedicated re-assert loop
is used for STAPM, because the rewrite happens in well under a second. The
hourly full rewrite includes STAPM as well, but it does not hold.

## Battery Incident

On 2026-05-05, the test laptop was left unplugged with an Electron IDE, AI coding assistant, and browser workload open. Logs showed low battery at about 20%, then the system disappeared from the journal near 6% without an orderly shutdown sequence. After reconnecting AC, the laptop booted at about 3% charge.

There was no evidence of a kernel panic or thermal shutdown. The practical failure mode was unattended battery drain: the original `battery` profile kept the laptop thermally controlled, but it was still permissive enough to let a forgotten workload run the pack down to firmware cutoff.

That incident is why `battery-saver` exists and why the service reads the battery level every second, not only AC plug/unplug events.

## Overhead

The idle overlay was built to be cheap:

- 1 second sample interval
- reads only aggregate `/proc/stat` and `/proc/loadavg`
- no per-process scan in the idle path
- no RyzenAdj call during polling; RyzenAdj is called when a target value changes, during the hourly rewrite or after a resume, and every 5 minutes while an SMU write keeps failing
- systemd constraints on the service: `Nice=10`, `IOSchedulingClass=idle`, `CPUQuota=10%`, `MemoryMax=64M`

The figures below were measured on the separate idle and Steam watchers, before they were merged into the service. The merged daemon does the same sampling in its one-second tick, so treat them as a reference for the earlier code, not a fresh measurement.

On the original Fedora test system, the idle watcher used about 48 ms CPU over 60 seconds and about 7.3 MB RAM. Those units ran with `CPUQuota=5%`. During deep idle with background desktop processes still present, the observed APU/PPT sensor dropped to about 4 W and `k10temp` settled around 57-58 C.

Steam detection runs on its own, slower schedule inside the service:

- 30 second scan interval when plugged in and Steam is not running
- 120 second scan interval on battery and Steam is not running
- 20 second interval while Steam is running

While a Steam game is detected (`gaming`), the idle overlay is suppressed entirely. Short low-CPU windows during cutscenes or loading screens would otherwise drop boost and SMU limits and stutter the game on resume.

On the original tuned system, the Steam watcher sample showed roughly 168 ms of CPU over about 65 seconds and around 6-7 MB resident memory. Treat this as an order-of-magnitude reference, not a guarantee across systems.

## Measure It Yourself

Two read-only commands, no root needed, give the numbers to compare profiles,
idle stages and settings with:

```bash
elitebook-thermal-profile measure 300    # 5 minutes, unplugged
elitebook-thermal-profile probe
```

`measure` samples what the battery delivers every two seconds, which is the
whole laptop's draw, so it needs the charger unplugged; it stops early if you
plug in. It reports the average, minimum and maximum, the CPU temperature, how
long a full and the current battery would last at that draw, and the profile
and idle stage in force. `--json` prints the same as one JSON object.

What the first runs on the 845 G8 taught, and how the report handles it:

- **The firmware refreshes the power figure slowly**, sometimes not at all for
  a whole minute (one run read 6.76 W in all 31 samples). The report says how
  often the figure changed, and warns when it stood still for 20 s or half the
  run: the average then rests on few real readings. Prefer runs of 5 minutes
  or more.
- **The stored energy counter moves in steps of about 0.1 Wh**, so the fall
  between start and end is off by up to a step at each end: on the first
  runs it gave 4.1, 14.4 and 3.6 W against 7.2, 6.6 and 6.8 W read directly.
  The report times the steps instead, from the first change seen to the
  last, and shows that figure only as a cross-check: when it lands within
  25% of the direct reading it says they agree, otherwise it shows how far
  apart they are. It needs the counter to move at least three times, so it
  appears only on longer runs. The direct reading is the figure to use.
- **The idle overlay comes and goes while you measure.** Every sample records
  the profile and idle stage in force, and when they change the report gives
  the time spent and the average draw in each, so soft and deep idle can be
  compared from one long run without stopping the service. The power figure
  lags a stage change by up to one firmware refresh, so short phases are
  rough.

To compare two settings, keep the workload the same: same apps open, same
screen brightness, Wi-Fi in the same state, and let the machine settle a
minute before starting. A desktop left alone shows the idle overlay at work;
run `elitebook-thermal-profile status` to see which stage it reached.

`probe` lists every power knob the kernel exposes on this machine, such as
CPU driver and EPP, PCIe ASPM policy, audio codec power saving, amdgpu power
level and panel power saving, USB autosuspend and NVMe power states, with the
current value or `-` where the knob does not exist. It changes nothing; it
says what a profile could change here.

## What Would Make The Data Stronger

Good community test reports should include:

- BIOS version
- kernel version
- distribution
- GNOME/KDE/desktop environment
- ambient temperature if known
- workload description
- `sensors` output
- `ryzenadj -i` output before and after applying a profile
- whether the machine is plugged in or on battery
- `elitebook-thermal-profile probe` output, and `measure` runs on battery
