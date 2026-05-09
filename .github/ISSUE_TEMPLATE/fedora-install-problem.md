---
name: Fedora install problem
about: Report COPR, RPM, dependency, or activation problems on Fedora
title: "Fedora install: "
labels: bug
assignees: ""
---

## Install Path

- Fedora version:
- Install command used:
- Package versions:

```text
rpm -q elitebook-thermal-profile ryzenadj
```

## Problem

What failed?

## Expected Behavior

What did you expect to happen?

## System

- Laptop model:
- CPU:
- Kernel:
- Secure Boot enabled (yes / no / unsure):
- Kernel lockdown state:

```text
cat /sys/kernel/security/lockdown
```

## Service State

```text
systemctl status elitebook-thermal-profile.service
systemctl status elitebook-idle-watcher.service
systemctl status elitebook-steam-game-watcher.service
systemctl status elitebook-power-guard.timer
cat /run/elitebook-thermal-profile/current
cat /run/elitebook-thermal-profile/guard
```

## RyzenAdj

```text
command -v ryzenadj
sudo ryzenadj -i
```

## Notes

Do not paste tokens, private hostnames, unrelated logs, or screenshots that
show private data.
