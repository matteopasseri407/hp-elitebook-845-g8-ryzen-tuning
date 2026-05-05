# Security Policy

This project ships scripts and a systemd integration that run as root and
talk to AMD SMU controls through RyzenAdj. Bugs in this code can affect
power, thermal, or system stability. Security reports are welcome.

## Reporting a Vulnerability

Please do not open a public GitHub issue for security-sensitive reports.

Use one of:

- GitHub private vulnerability reporting:
  <https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning/security/advisories/new>
- Or email the maintainer listed on the GitHub profile, with a subject line
  starting with `[SECURITY]`.

Include:

- a clear description of the issue and impact
- the affected file(s) and version (commit hash if possible)
- steps to reproduce or a proof of concept
- whether the issue is already public or has a CVE assigned

## Scope

In scope:

- privilege escalation through the installed scripts, watchers, or
  systemd units
- escape from the systemd hardening on the watcher services
- writes to sysfs or RyzenAdj that could damage hardware
- the polkit / pkexec integration used by the GNOME Shell extension

Out of scope:

- bugs that require an attacker who already has root
- issues in third-party dependencies (RyzenAdj, tuned, GNOME Shell, polkit)
  unless this project is misusing them
- general thermal or power tuning disagreements: open a hardware report
  issue instead

## Response Expectations

This is a small community project. There is no guaranteed SLA.

Best-effort targets:

- acknowledgement within 7 days
- a fix or mitigation plan within 30 days for confirmed reports
- coordinated disclosure: the reporter is credited unless they prefer
  to remain anonymous

## Out-of-Band Mitigations

If you suspect a deployed installation is at risk:

```bash
sudo systemctl disable --now \
    elitebook-thermal-profile.service \
    elitebook-idle-watcher.service \
    elitebook-steam-game-watcher.service
sudo ./scripts/uninstall.sh
sudo reboot
```

That returns the machine to firmware defaults until a fix is available.
