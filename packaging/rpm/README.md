# RPM Packaging

The current stable Fedora path is still source-based installation through
`scripts/install-fedora.sh`. The next distribution step is the COPR-oriented
RPM spec in this directory:

```bash
packaging/rpm/elitebook-thermal-profile.spec
```

Do not publish a COPR build until the RyzenAdj dependency story is explicit:
either RyzenAdj is available from a known package source, or this project
documents a safe companion package/installation path. The current spec treats
RyzenAdj as a weak dependency and documents the sysfs-only fallback.

## Package Layout

- Install commands under `/usr/bin/`
- Install systemd units under `%{_unitdir}`
- Install udev rules under `%{_udevrulesdir}`
- Install the system sleep hook under `/usr/lib/systemd/system-sleep/`
- Package the GNOME Shell extension as the optional
  `gnome-shell-extension-elitebook-thermal-profile` subpackage
- Do not vendor RyzenAdj; weakly recommend a packaged RyzenAdj when available

The spec patches packaged unit files, helper scripts, sleep hook, and GNOME
extension away from the source installer's `/usr/local/sbin` paths. This keeps
the RPM-owned install inside normal distribution paths while leaving
`scripts/install-fedora.sh` unchanged for manual installs.

## Manual COPR Flow

After creating the COPR project, build the spec from the reviewed packaging
merge commit. The spec itself still downloads the released `v0.2.0` source
tarball.

```bash
copr-cli create elitebook-thermal-profile \
  --chroot fedora-44-x86_64 \
  --description "Thermal and power profiles for HP AMD Cezanne laptops"

copr-cli buildscm elitebook-thermal-profile \
  --clone-url https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning.git \
  --commit a16d296796a6d845971c0db67909dc6f2d59ccf3 \
  --spec packaging/rpm/elitebook-thermal-profile.spec \
  --method rpkg \
  -r fedora-44-x86_64
```

Adjust the project owner/name if the public COPR namespace differs.

## Post-Install Activation

The package deliberately installs the services but does not start hardware
tuning automatically. Users should enable it explicitly after reading the
supported hardware table:

```bash
sudo systemctl enable --now elitebook-thermal-profile.service
sudo systemctl enable --now elitebook-idle-watcher.service
sudo systemctl enable --now elitebook-steam-game-watcher.service
sudo systemctl enable --now elitebook-power-guard.timer
sudo systemctl start elitebook-power-guard.service
```

This keeps a public package from changing power policy immediately during
installation and makes first activation an intentional user action.

COPR is the most practical first distribution channel for Fedora users. Broader Linux packaging can follow after more hardware reports.
