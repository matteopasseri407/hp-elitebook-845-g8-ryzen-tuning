# Btrfs Swapfile Hibernate Preflight

Hibernating to a btrfs swapfile on Linux requires precise alignment: a regenerated swapfile silently changes its physical offset, SELinux relabeling can prevent swap activation, and kernel lockdown blocks the resume path. A stale offset results in failed resume or image corruption.

`elitebook-hibernate-preflight` is an opt-in safety guard (`--with-hibernate-preflight` in `install.sh`). It runs via `ExecStartPre=` in `systemd-hibernate.service` and `systemd-suspend-then-hibernate.service`, aborting the sleep transition unless all safety checks pass.

---

## What It Verifies

Before allowing systemd to hibernate, the preflight checks:
1. **Active swapfile**: The configured path is active swap with capacity for the hibernation image plus 2 GiB headroom.
2. **SELinux context**: When SELinux is in enforcing mode, the swapfile label must be `swapfile_t`.
3. **Btrfs physical offset**: The physical offset derived via `btrfs inspect-internal map-swapfile -r` matches `RESUME_OFFSET`.
4. **Kernel lockdown**: `/sys/kernel/security/lockdown` must be `[none]`.
5. **Boot arguments**: Both the default bootloader entry (via `grubby`) and the running `/proc/cmdline` contain matching `resume=UUID=` and `resume_offset=` arguments.

On success, the script programs `/sys/power/resume`, `/sys/power/resume_offset`, and `/sys/power/image_size` immediately before systemd writes the image.

---

## Configuration

Edit `/etc/elitebook-hibernate.conf`:

```ini
SWAPFILE=/swap/hibernate.swap
RESUME_UUID=12345678-1234-1234-1234-123456789abc
RESUME_OFFSET=1024000
IMAGE_SIZE_BYTES=0
```

### Deriving the values

1. **Swapfile UUID:**
   ```bash
   findmnt -no UUID -T /swap/hibernate.swap
   ```
2. **Btrfs physical offset:**
   ```bash
   sudo btrfs inspect-internal map-swapfile -r /swap/hibernate.swap
   ```
3. **Verify configuration:**
   ```bash
   sudo elitebook-hibernate-preflight check-config
   ```
