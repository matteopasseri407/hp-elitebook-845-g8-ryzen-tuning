# RPM Packaging Plan

The current install script is source-based. For Fedora distribution, the preferred next step is a proper RPM and COPR repository.

Initial packaging decisions:

- Install executables under `/usr/libexec/elitebook-thermal-profile/`
- Provide small wrapper commands under `/usr/bin/`
- Install systemd units under `%{_unitdir}`
- Install udev rules under `%{_udevrulesdir}`
- Install the system sleep hook under `/usr/lib/systemd/system-sleep/`
- Keep the GNOME Shell extension as an optional subpackage
- Do not vendor RyzenAdj; depend on a packaged RyzenAdj when available

Suggested package split:

- `elitebook-845-g8-ryzen-tuning`
- `elitebook-845-g8-ryzen-tuning-steam`
- `gnome-shell-extension-elitebook-thermal-profile`

COPR is the most practical first distribution channel for Fedora users. Broader Linux packaging can follow after more hardware reports.

