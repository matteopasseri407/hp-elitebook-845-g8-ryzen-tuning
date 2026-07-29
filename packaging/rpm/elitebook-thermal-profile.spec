Name:           elitebook-thermal-profile
Version:        0.7.0
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

Requires:       bash
Requires:       python3
Requires:       systemd
Requires:       systemd-udev
Requires:       tuned
Requires:       util-linux-core
Recommends:     ryzenadj >= 0.17.0
Suggests:       gnome-shell-extension-elitebook-thermal-profile

Requires(post):   systemd
Requires(preun):  systemd
Requires(postun): systemd

%{!?_unitdir:%global _unitdir %{_prefix}/lib/systemd/system}
%{!?_udevrulesdir:%global _udevrulesdir %{_prefix}/lib/udev/rules.d}
%global _systemd_sleepdir %{_prefix}/lib/systemd/system-sleep

%description
User-space thermal and power profile integration for selected HP EliteBook and
ProBook AMD Cezanne laptops on Linux. It combines AMD P-State EPP, CPU
frequency policy, service units, udev, and RyzenAdj-driven SMU limits into a
daily-driver profile dispatcher with idle, AC/battery, update guard, and Steam
game automation.

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
bash -n src/elitebook-thermal-profile src/elitebook-power-guard src/elitebook-hibernate-preflight system-sleep/elitebook-thermal-profile
python3 -m py_compile src/elitebook-idle-watcher src/elitebook-steam-game-watcher

%install
install -Dm0755 src/elitebook-thermal-profile \
  %{buildroot}%{_bindir}/elitebook-thermal-profile
install -Dm0755 src/elitebook-idle-watcher \
  %{buildroot}%{_bindir}/elitebook-idle-watcher
install -Dm0755 src/elitebook-power-guard \
  %{buildroot}%{_bindir}/elitebook-power-guard
install -Dm0755 src/elitebook-steam-game-watcher \
  %{buildroot}%{_bindir}/elitebook-steam-game-watcher
install -Dm0755 src/elitebook-hibernate-preflight \
  %{buildroot}%{_bindir}/elitebook-hibernate-preflight

install -Dm0644 systemd/elitebook-thermal-profile.service \
  %{buildroot}%{_unitdir}/elitebook-thermal-profile.service
install -Dm0644 systemd/elitebook-idle-watcher.service \
  %{buildroot}%{_unitdir}/elitebook-idle-watcher.service
install -Dm0644 systemd/elitebook-steam-game-watcher.service \
  %{buildroot}%{_unitdir}/elitebook-steam-game-watcher.service
install -Dm0644 systemd/elitebook-power-guard.service \
  %{buildroot}%{_unitdir}/elitebook-power-guard.service
install -Dm0644 systemd/elitebook-power-guard.timer \
  %{buildroot}%{_unitdir}/elitebook-power-guard.timer

install -Dm0644 udev/90-elitebook-thermal-profile.rules \
  %{buildroot}%{_udevrulesdir}/90-elitebook-thermal-profile.rules
install -Dm0755 system-sleep/elitebook-thermal-profile \
  %{buildroot}%{_systemd_sleepdir}/elitebook-thermal-profile

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
  %{buildroot}%{_systemd_sleepdir}/elitebook-thermal-profile \
  %{buildroot}%{_datadir}/%{name}/examples/systemd-hibernate.service.d/10-elitebook-preflight.conf \
  %{buildroot}%{_datadir}/%{name}/examples/systemd-suspend-then-hibernate.service.d/10-elitebook-preflight.conf

sed -i \
  -e 's#/usr/local/sbin#%{_bindir}#g' \
  -e 's#/etc/udev/rules.d/90-elitebook-thermal-profile.rules#%{_udevrulesdir}/90-elitebook-thermal-profile.rules#g' \
  -e 's#/etc/systemd/system-sleep/elitebook-thermal-profile#%{_systemd_sleepdir}/elitebook-thermal-profile#g' \
  %{buildroot}%{_bindir}/elitebook-power-guard \
  %{buildroot}%{_bindir}/elitebook-steam-game-watcher

sed -i \
  -e 's#/usr/local/sbin/elitebook-thermal-profile#%{_bindir}/elitebook-thermal-profile#g' \
  %{buildroot}%{_datadir}/gnome-shell/extensions/%{extension_uuid}/extension.js

%post
%systemd_post elitebook-thermal-profile.service elitebook-idle-watcher.service elitebook-steam-game-watcher.service elitebook-power-guard.timer
if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules >/dev/null 2>&1 || :
fi
cat <<'EOF'
elitebook-thermal-profile installed.

Enable it explicitly after reviewing the supported hardware table:
  sudo systemctl enable --now elitebook-thermal-profile.service
  sudo systemctl enable --now elitebook-idle-watcher.service
  sudo systemctl enable --now elitebook-steam-game-watcher.service
  sudo systemctl enable --now elitebook-power-guard.timer
  sudo systemctl start elitebook-power-guard.service

Full SMU control requires RyzenAdj. Without it, sysfs fallback controls still
cover EPP, boost, and CPU frequency where supported by the kernel.

The btrfs swapfile hibernate preflight is inactive by default; see
/usr/share/elitebook-thermal-profile/examples/ and the README to wire it up.
EOF

%preun
%systemd_preun elitebook-thermal-profile.service elitebook-idle-watcher.service elitebook-steam-game-watcher.service elitebook-power-guard.timer

%postun
%systemd_postun_with_restart elitebook-thermal-profile.service elitebook-idle-watcher.service elitebook-steam-game-watcher.service elitebook-power-guard.timer
if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules >/dev/null 2>&1 || :
fi

%files
%license LICENSE
%doc README.md docs
%dir %{_sysconfdir}/%{name}
%config(noreplace) %{_sysconfdir}/%{name}/profiles.conf
%{_bindir}/elitebook-thermal-profile
%{_bindir}/elitebook-idle-watcher
%{_bindir}/elitebook-power-guard
%{_bindir}/elitebook-steam-game-watcher
%{_bindir}/elitebook-hibernate-preflight
%{_unitdir}/elitebook-thermal-profile.service
%{_unitdir}/elitebook-idle-watcher.service
%{_unitdir}/elitebook-steam-game-watcher.service
%{_unitdir}/elitebook-power-guard.service
%{_unitdir}/elitebook-power-guard.timer
%{_udevrulesdir}/90-elitebook-thermal-profile.rules
%{_systemd_sleepdir}/elitebook-thermal-profile
%{_datadir}/%{name}/

%files -n gnome-shell-extension-elitebook-thermal-profile
%doc README.md
%{_datadir}/gnome-shell/extensions/%{extension_uuid}/

%changelog
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
