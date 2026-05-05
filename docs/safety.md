# Safety Notes

This project changes low-level power and thermal behavior. Read this before installing or adapting it.

## Hardware Scope

The shipped defaults target:

- HP EliteBook 845 G8
- AMD Ryzen 7 PRO 5850U

The script checks DMI and CPU model before applying a profile. To override the guard, set:

```bash
sudo ELITEBOOK_THERMAL_FORCE=1 elitebook-thermal-profile ac
```

Only do that when you have reviewed the profile values for your own hardware.

## Why It Uses RyzenAdj

RyzenAdj talks to AMD Ryzen SMU controls. That is exactly why it is useful here, and also why this should not be treated like a normal desktop preference toggle.

The profile values in this repository are conservative relative to the stock sustained behavior observed on the tested unit, but they are still low-level firmware-facing settings.

## No Stock Profile

This repository intentionally does not provide a `stock` profile because the stock behavior was the problem on the tested machine. If you want to return to firmware defaults, uninstall the service, reboot, and do not reapply these profiles.

```bash
sudo ./scripts/uninstall.sh
sudo reboot
```

## Manual Overrides

Manual selections win over automation:

- `sudo elitebook-thermal-profile ac`
- `sudo elitebook-thermal-profile battery`
- `sudo elitebook-thermal-profile gaming`
- `sudo elitebook-thermal-profile cool`

To return to automatic AC/battery behavior:

```bash
sudo elitebook-thermal-profile auto
```

## Adapting To Other Laptops

If you adapt this for another laptop, do not start by raising limits. Start by measuring:

```bash
sensors
sudo ryzenadj -i
cat /sys/devices/system/cpu/cpufreq/policy0/scaling_driver
```

Then change one variable at a time:

- sustained CPU limit
- APU slow limit
- temperature target
- EPP

Keep boost and frequency caps separate from SMU tuning so you can understand what each change did.

