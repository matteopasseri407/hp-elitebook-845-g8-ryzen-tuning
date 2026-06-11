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

Idle behavior is handled as a separate staged overlay instead of baking deep caps into every profile. Soft idle only changes the EPP hint after a few quiet seconds. Deep idle is delayed and then applies the more aggressive boost/frequency/SMU limits. The watcher exits idle on the first active sample, so foreground work should restore the selected profile quickly.

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

- the dispatcher write succeeds at the SMU mailbox level (`Successfully set
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
readings can look like the overlay value "held". No re-assert mechanism is
used because the rewrite happens in well under a second.

## Battery Incident

On 2026-05-05, the test laptop was left unplugged with an Electron IDE, AI coding assistant, and browser workload open. Logs showed low battery at about 20%, then the system disappeared from the journal near 6% without an orderly shutdown sequence. After reconnecting AC, the laptop booted at about 3% charge.

There was no evidence of a kernel panic or thermal shutdown. The practical failure mode was unattended battery drain: the original `battery` profile kept the laptop thermally controlled, but it was still permissive enough to let a forgotten workload run the pack down to firmware cutoff.

That incident is why `battery-saver` exists and why the udev rules listen for battery state changes, not only AC plug/unplug events.

## Watcher Overhead

The idle watcher is intentionally cheaper than a process monitor:

- 1 second sample interval
- reads only aggregate `/proc/stat` and `/proc/loadavg`
- no per-process scan in the idle loop
- no RyzenAdj call during polling; RyzenAdj is called only on deep-idle enter/exit transitions
- systemd constraints: `Nice=10`, `IOSchedulingClass=idle`, `CPUQuota=5%`, `MemoryMax=64M`

On the original Fedora test system, the idle watcher used about 48 ms CPU over 60 seconds and about 7.3 MB RAM. During deep idle with background desktop processes still present, the observed APU/PPT sensor dropped to about 4 W and `k10temp` settled around 57-58 C.

The Steam watcher remains separate and slow:

- 30 second scan interval when plugged in and Steam is not running
- 120 second scan interval on battery and Steam is not running
- 20 second interval while Steam is running
- systemd constraints: `Nice=10`, `IOSchedulingClass=idle`, `CPUQuota=5%`, `MemoryMax=64M`

While a Steam game profile is active the idle overlay watcher is
suppressed entirely. Short low-CPU windows during cutscenes or loading
screens would otherwise drop boost and SMU limits and stutter the game
on resume.

On the original tuned system, the Steam watcher sample showed roughly 168 ms of CPU over about 65 seconds and around 6-7 MB resident memory. Treat this as an order-of-magnitude reference, not a guarantee across systems.

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
