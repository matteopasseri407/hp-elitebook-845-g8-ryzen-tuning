Name:           ryzenadj
Version:        0.17.0
Release:        1%{?dist}
Summary:        Adjust power management settings for AMD Ryzen APUs

License:        GPL-2.0-only AND LGPL-3.0-only AND MIT
URL:            https://github.com/FlyGoat/RyzenAdj
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz

%global source_sha256 848ac9d86ff65d30f5e2c8600aac2613f0f10003b0d6f0e516a54761d7345d44

BuildRequires:  cmake
BuildRequires:  gcc-c++
BuildRequires:  make
BuildRequires:  pciutils-devel

%description
RyzenAdj is a userspace command-line tool for adjusting AMD Ryzen mobile APU
SMU power management settings. It can set limits such as sustained package
power and thermal targets on supported Ryzen laptop platforms.

This package builds the upstream FlyGoat RyzenAdj release used by the HP AMD
thermal profile tooling. Kernel lockdown or Secure Boot policies may still
prevent low-level SMU access at runtime.

%prep
printf '%s  %s\n' '%{source_sha256}' '%{SOURCE0}' | sha256sum -c -
%autosetup -n RyzenAdj-%{version}

%build
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel %{?_smp_build_ncpus}

%install
install -Dm0755 build/ryzenadj %{buildroot}%{_bindir}/ryzenadj

%check
test -x %{buildroot}%{_bindir}/ryzenadj

%files
%license LICENSE
%doc README.md
%{_bindir}/ryzenadj

%changelog
* Sat May 09 2026 Matteo Passeri <matteopasseri407@users.noreply.github.com> - 0.17.0-1
- Initial COPR-oriented RyzenAdj package for elitebook-thermal-profile
