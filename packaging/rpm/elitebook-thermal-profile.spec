Name:           elitebook-thermal-profile
Version:        0.2.1
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
bash -n src/elitebook-thermal-profile src/elitebook-power-guard system-sleep/elitebook-thermal-profile
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

sed -i \
  -e 's#/usr/local/sbin#%{_bindir}#g' \
  %{buildroot}%{_unitdir}/elitebook-*.service \
  %{buildroot}%{_systemd_sleepdir}/elitebook-thermal-profile

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
%{_bindir}/elitebook-thermal-profile
%{_bindir}/elitebook-idle-watcher
%{_bindir}/elitebook-power-guard
%{_bindir}/elitebook-steam-game-watcher
%{_unitdir}/elitebook-thermal-profile.service
%{_unitdir}/elitebook-idle-watcher.service
%{_unitdir}/elitebook-steam-game-watcher.service
%{_unitdir}/elitebook-power-guard.service
%{_unitdir}/elitebook-power-guard.timer
%{_udevrulesdir}/90-elitebook-thermal-profile.rules
%{_systemd_sleepdir}/elitebook-thermal-profile

%files -n gnome-shell-extension-elitebook-thermal-profile
%doc README.md
%{_datadir}/gnome-shell/extensions/%{extension_uuid}/

%changelog
* Sat May 09 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.2.1-1
- Publish Fedora COPR dependency path with packaged RyzenAdj 0.17.0
- Add Fedora install support template and release-readiness README badges

* Sat May 09 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.2.0-2
- Recommend the packaged RyzenAdj 0.17.0 dependency from COPR

* Sat May 09 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.2.0-1
- Initial COPR-oriented Fedora RPM packaging
