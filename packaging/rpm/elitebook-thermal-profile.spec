Name:           elitebook-thermal-profile
Version:        1.0.0
Release:        1%{?dist}
Summary:        Thermal and power profiles for HP AMD Cezanne laptops

%global upstream_url https://github.com/matteopasseri407/hp-elitebook-845-g8-ryzen-tuning
%global repo_dir hp-elitebook-845-g8-ryzen-tuning-%{version}
%global extension_uuid elitebook-thermal-profile@matteopasseri.github.io

License:        GPL-3.0-or-later
URL:            %{upstream_url}
Source0:        %{upstream_url}/archive/refs/tags/v%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3
BuildRequires:  systemd-rpm-macros

Requires:       python3
Requires:       systemd
Requires:       tuned
Requires:       util-linux-core
Recommends:     ryzenadj >= 0.17.0
Suggests:       gnome-shell-extension-elitebook-thermal-profile

Requires(post):   systemd
Requires(preun):  systemd
Requires(postun): systemd

%{!?_unitdir:%global _unitdir %{_prefix}/lib/systemd/system}

%description
User-space thermal and power profile integration for selected HP EliteBook and
ProBook AMD Cezanne laptops on Linux. It combines AMD P-State EPP, CPU
frequency policy, a systemd service, and RyzenAdj-driven SMU limits. A single
daemon handles AC/battery, idle, Steam and resume, and an update guard timer
keeps conflicting power backends masked.

Full SMU control requires a RyzenAdj binary. Without RyzenAdj, the profile
stack degrades to kernel EPP, boost, and frequency controls where possible.

%package -n gnome-shell-extension-elitebook-thermal-profile
Summary:        GNOME Shell indicator for EliteBook thermal profiles
Requires:       %{name} = %{version}-%{release}
Requires:       gnome-shell >= 45
Requires:       polkit

%description -n gnome-shell-extension-elitebook-thermal-profile
GNOME Shell panel indicator for switching the EliteBook thermal profile between
Auto, Game, and Quiet without exposing lower-level technical profiles in the
daily UI.

%prep
%autosetup -n %{repo_dir}

%build
# Scripts and GNOME Shell files do not need a build step.

%check
python3 -m py_compile \
  src/elitebook-thermal-profile \
  src/elitebook_common.py \
  src/elitebook_profiles.py \
  src/elitebook_engine.py \
  src/elitebook-power-guard \
  src/elitebook-hibernate-preflight

%install
install -Dm0755 src/elitebook-thermal-profile \
  %{buildroot}%{_bindir}/elitebook-thermal-profile
install -Dm0644 src/elitebook_common.py \
  %{buildroot}%{_bindir}/elitebook_common.py
install -Dm0644 src/elitebook_profiles.py \
  %{buildroot}%{_bindir}/elitebook_profiles.py
install -Dm0644 src/elitebook_engine.py \
  %{buildroot}%{_bindir}/elitebook_engine.py
install -Dm0755 src/elitebook-power-guard \
  %{buildroot}%{_bindir}/elitebook-power-guard
install -Dm0755 src/elitebook-hibernate-preflight \
  %{buildroot}%{_bindir}/elitebook-hibernate-preflight

install -Dm0644 systemd/elitebook-thermal-profile.service \
  %{buildroot}%{_unitdir}/elitebook-thermal-profile.service
install -Dm0644 systemd/elitebook-power-guard.service \
  %{buildroot}%{_unitdir}/elitebook-power-guard.service
install -Dm0644 systemd/elitebook-power-guard.timer \
  %{buildroot}%{_unitdir}/elitebook-power-guard.timer

install -d %{buildroot}%{_datadir}/gnome-shell/extensions
cp -a gnome-extension/%{extension_uuid} %{buildroot}%{_datadir}/gnome-shell/extensions/

# Hibernate preflight drop-ins are shipped as inert examples instead of live
# units so installing the RPM never blocks hibernate by itself. Activation
# stays explicit: copy them to /etc/systemd/system/ and create
# /etc/elitebook-hibernate.conf as described in the README.
install -Dm0644 systemd/systemd-hibernate.service.d/10-elitebook-preflight.conf \
  %{buildroot}%{_datadir}/%{name}/examples/systemd-hibernate.service.d/10-elitebook-preflight.conf
install -Dm0644 systemd/systemd-suspend-then-hibernate.service.d/10-elitebook-preflight.conf \
  %{buildroot}%{_datadir}/%{name}/examples/systemd-suspend-then-hibernate.service.d/10-elitebook-preflight.conf
install -Dm0644 config/elitebook-hibernate.conf.example \
  %{buildroot}%{_datadir}/%{name}/examples/elitebook-hibernate.conf.example

# Profile overrides ship fully commented out, so the file is inert until the
# user edits it. Marked %config(noreplace) so those edits survive upgrades,
# which is the whole point of having it.
install -Dm0644 config/profiles.conf.example \
  %{buildroot}%{_sysconfdir}/%{name}/profiles.conf

sed -i \
  -e 's#/usr/local/sbin#%{_bindir}#g' \
  %{buildroot}%{_unitdir}/elitebook-*.service \
  %{buildroot}%{_datadir}/%{name}/examples/systemd-hibernate.service.d/10-elitebook-preflight.conf \
  %{buildroot}%{_datadir}/%{name}/examples/systemd-suspend-then-hibernate.service.d/10-elitebook-preflight.conf

sed -i \
  -e 's#/usr/local/sbin#%{_bindir}#g' \
  %{buildroot}%{_bindir}/elitebook-power-guard

sed -i \
  -e 's#/usr/local/sbin/elitebook-thermal-profile#%{_bindir}/elitebook-thermal-profile#g' \
  %{buildroot}%{_datadir}/gnome-shell/extensions/%{extension_uuid}/extension.js

%post
%systemd_post elitebook-thermal-profile.service elitebook-power-guard.timer
# Earlier releases shipped separate watcher units. The daemon replaces them,
# and the old units would otherwise keep running after the upgrade.
systemctl disable --now elitebook-idle-watcher.service elitebook-steam-game-watcher.service >/dev/null 2>&1 || :
cat <<'EOF'
elitebook-thermal-profile installed.

Enable it explicitly after reviewing the supported hardware table:
  sudo systemctl enable --now elitebook-thermal-profile.service
  sudo systemctl enable --now elitebook-power-guard.timer
  sudo systemctl start elitebook-power-guard.service

The daemon also runs the idle overlay and Steam game detection. To switch
either off, add Environment=ELITEBOOK_IDLE_OVERLAY=0 or
Environment=ELITEBOOK_STEAM_DETECTION=0 under [Service] in a drop-in for
elitebook-thermal-profile.service.

Full SMU control requires RyzenAdj. Without it, sysfs fallback controls still
cover EPP, boost, and CPU frequency where supported by the kernel.

The btrfs swapfile hibernate preflight is inactive by default; see
/usr/share/elitebook-thermal-profile/examples/ and the README to wire it up.
EOF

%preun
%systemd_preun elitebook-thermal-profile.service elitebook-power-guard.timer

%postun
%systemd_postun_with_restart elitebook-thermal-profile.service elitebook-power-guard.timer
if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules >/dev/null 2>&1 || :
fi

%files
%license LICENSE
%doc README.md docs
%dir %{_sysconfdir}/%{name}
%config(noreplace) %{_sysconfdir}/%{name}/profiles.conf
%{_bindir}/elitebook-thermal-profile
%{_bindir}/elitebook_common.py
%{_bindir}/elitebook_profiles.py
%{_bindir}/elitebook_engine.py
%{_bindir}/elitebook-power-guard
%{_bindir}/elitebook-hibernate-preflight
%{_unitdir}/elitebook-thermal-profile.service
%{_unitdir}/elitebook-power-guard.service
%{_unitdir}/elitebook-power-guard.timer
%{_datadir}/%{name}/

%files -n gnome-shell-extension-elitebook-thermal-profile
%doc README.md
%{_datadir}/gnome-shell/extensions/%{extension_uuid}/

%changelog
* Mon Oct 12 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 1.0.0-1
- Replace the dispatcher, udev rule, sleep hook, idle watcher and Steam
  watcher with one daemon that is the only writer of power settings
- Stop reapplying the profile on every battery level update
- Add RUNTIME_PM and PANEL_POWER_SAVINGS profile keys
- New commands: reassert, daemon, apply-once
- Reread AC and battery on kernel power events instead of every second
- Restore the firmware VRM limit on profiles without one
- Hold battery-saver until the battery climbs 2 points above the threshold
- On battery, hold every profile to the battery VRM current limit
- Stop retrying on configuration errors and after 10 crashes in 10 minutes
- GNOME indicator: support GNOME Shell 51, show when the service is stopped

* Wed Oct 07 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.9.0-1
- Protect against battery brownouts and transient voltage droops under heavy
  multi-core/AVX2 load: set battery profile burst power (FAST) to 22W,
  Tctl thermal target to 80 C, and apply a 45A VRM peak current (EDC) limit
  via RyzenAdj (--vrmmax-current)
- Add --vrmmax-current support to SMU limit application with profiles.conf
  overrides for VRMMAX_MA (15-120A)
- Support BOOST and MAX_FREQ_KHZ overrides in profiles.conf
- Persist and report VRM max current in status and status --json

* Tue Sep 08 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.8.0-1
- Rewrite the dispatcher from bash to stdlib-only Python with identical CLI,
  state files and messages; add status --json for scripts
- Skip sysfs writes when the value is already in force; SMU limits are still
  reapplied every run so firmware resets keep healing
- Share sysfs helpers and CPU policy application among dispatcher,
  watchers and guard in one module
- Rewrite elitebook-power-guard and elitebook-hibernate-preflight from bash
  to the same stdlib-only Python; parse the hibernate config instead of
  sourcing it as root shell, and convert the system-sleep hook to Python
- Name the config file line in refused profile override warnings

* Wed Jul 29 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.7.0-1
- Record the package temperature against the active profile's thermal target
  while the idle watcher runs, reset on every profile change
- Report the peak and the share of time above target in status, and warn from
  elitebook-power-guard check when a profile is not holding its target
- Nothing is adjusted automatically: the firmware owns the control loop

* Wed Jul 29 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.5.0-1
- Apply the CPU-level part of a profile (EPP, boost, frequency cap) even when
  RyzenAdj is missing or blocked by kernel lockdown, rather than refusing to
  run or aborting before the state file is written
- Record the outcome in the state file as smu=ok, unavailable, blocked, or
  failed, and report a degraded machine from elitebook-power-guard check
- Name the detected machine in --check-hardware instead of always naming the
  development laptop

* Wed Jul 29 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.4.2-1
- Refuse to install from source on top of a packaged installation: the source
  units in /etc/systemd/system override the packaged ones, so the two together
  leave the package registered while a different copy runs
- Read package ownership from the query tool's exit status instead of its
  translated message

* Wed Jul 29 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.4.1-1
- Add Debian and Ubuntu packaging under packaging/debian, built and verified
  on Ubuntu runners; the Fedora package is unchanged by this release

* Wed Jul 29 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.4.0-1
- Make the source installer distribution aware: detect the distribution
  family from os-release, map package names per family, and require tuned
  only on Fedora, where it is the stock CPU policy backend
- Rename the source installer to scripts/install.sh and keep
  scripts/install-fedora.sh as a compatibility shim; the RPM is unaffected
- Record the configured power backend in
  /etc/elitebook-thermal-profile/backend.conf so the update guard can tell
  a genuine tuned regression from a system that never had tuned
- Skip masking power backend units the distribution does not ship instead
  of creating dangling masks
- Check for libpci headers before a RyzenAdj source build
- Refuse --with-hibernate-preflight outside Fedora, where grubby and the
  SELinux label it inspects do not exist
- Add scripts/install.sh --print-platform for root-free diagnostics
- Document the experimental Ubuntu and Debian path in docs/ubuntu.md

* Thu Jun 11 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.3.1-1
- Document that STT-enabled platforms (845 G8 included) pin the STAPM
  limit to the fast limit, with measurements and troubleshooting entry;
  no re-assert mechanism is added because the firmware rewrite happens
  in under a second
- Align measured watcher CPUQuota values in the docs with the units (5%)

* Tue Jun 09 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.3.0-1
- Add the btrfs swapfile hibernate preflight with config example and
  systemd-hibernate drop-in examples (inactive by default)
- Disable start rate limiting on the thermal profile unit so udev
  power_supply event bursts no longer drop profile switches
- Keep the dispatcher alive when no cpufreq policy exposes writable EPP
  so SMU limits and state are still applied on non-EPP drivers
- Revert orphaned Steam gaming profiles after a watcher crash or restart
- Raise the idle watcher CPU quota so ryzenadj is not throttled inside
  the dispatcher lock

* Sat May 09 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.2.1-1
- Publish Fedora COPR dependency path with packaged RyzenAdj 0.17.0
- Add Fedora install support template and release-readiness README badges

* Sat May 09 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.2.0-2
- Recommend the packaged RyzenAdj 0.17.0 dependency from COPR

* Sat May 09 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.2.0-1
- Initial COPR-oriented Fedora RPM packaging
