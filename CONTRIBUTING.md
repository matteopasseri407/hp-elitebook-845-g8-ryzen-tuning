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

GitHub Actions runs `shellcheck` on the bash scripts and `ruff check` /
`ruff format --check` on the Python watchers. Run them locally before
opening a PR:

```bash
shellcheck src/elitebook-thermal-profile scripts/*.sh \
           system-sleep/elitebook-thermal-profile
ruff check src/elitebook-idle-watcher src/elitebook-steam-game-watcher
ruff format --check src/elitebook-idle-watcher \
                    src/elitebook-steam-game-watcher
```

## Privacy

Do not include private hostnames, tokens, personal paths, raw logs with usernames, or screenshots that reveal unrelated system details.

