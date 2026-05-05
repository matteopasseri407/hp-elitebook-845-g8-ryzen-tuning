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
- Python code stays dependency-free
- Keep root-facing scripts readable
- Keep automation low impact on battery
- Do not add passwordless polkit rules by default

## Privacy

Do not include private hostnames, tokens, personal paths, raw logs with usernames, or screenshots that reveal unrelated system details.

