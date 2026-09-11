# Contributing

Useful contributions are hardware reports, measured profile adjustments, packaging work, and fixes that keep the project simple.

## Before Changing Profile Values

Open an issue with:

- laptop model
- CPU model
- BIOS version
- distribution and kernel
- ambient temperature if known
- workload
- `sensors` output
- `sudo ryzenadj -i` output before and after
- profile used

Avoid proposing higher limits without measurements. The point of this repository is to preserve real responsiveness while staying inside what this chassis can cool comfortably.

## Coding Style

- Shell scripts use `set -euo pipefail`
- Python code stays dependency-free and targets Python 3.10+
- Keep root-facing scripts readable
- Keep automation low impact on battery
- Do not add passwordless polkit rules by default

## CI

GitHub Actions runs `shellcheck` on the shell scripts and `ruff check` /
`ruff format --check` / `mypy --strict` on the Python sources. Run them
locally before opening a PR:

```bash
shellcheck scripts/*.sh tests/*.sh
ruff check \
  src/elitebook-thermal-profile \
  src/elitebook_common.py \
  src/elitebook-idle-watcher \
  src/elitebook-steam-game-watcher \
  src/elitebook-power-guard \
  src/elitebook-hibernate-preflight \
  system-sleep/elitebook-thermal-profile \
  tests
ruff format --check \
  src/elitebook-thermal-profile \
  src/elitebook_common.py \
  src/elitebook-idle-watcher \
  src/elitebook-steam-game-watcher \
  src/elitebook-power-guard \
  src/elitebook-hibernate-preflight \
  system-sleep/elitebook-thermal-profile \
  tests
mypy --strict --scripts-are-modules \
  src/elitebook-thermal-profile \
  src/elitebook_common.py \
  src/elitebook-idle-watcher \
  src/elitebook-steam-game-watcher \
  src/elitebook-power-guard \
  src/elitebook-hibernate-preflight
mypy --strict system-sleep/elitebook-thermal-profile
```

## Privacy

Do not include private hostnames, tokens, personal paths, raw logs with usernames, or screenshots that reveal unrelated system details.

