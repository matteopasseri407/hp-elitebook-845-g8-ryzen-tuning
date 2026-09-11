# Codebase Map — HP EliteBook 845 G8 Ryzen Tuning

> Generata automaticamente tramite l'infrastruttura di code intelligence (`code-intel` AST) 
> Aggiornata al: 2026-09-11 19:32:21

## 1. Panoramica del Progetto

Stack utente Linux per il tuning termico e di potenza su HP EliteBook 845 G8 (e piattaforme affini AMD Cezanne Zen 3).
Combina limiti hardware SMU tramite RyzenAdj, policy del kernel via AMD P-State EPP e cpufreq, overlay dinamico per idle/gaming, guardie di integrità di sistema ed estensione GNOME Shell.

## 2. Architettura e Flusso dei Dati

```mermaid
flowchart TD
    subgraph Hardware & Kernel
        SMU["AMD SMU (RyzenAdj)"]
        CPUFREQ["/sys/devices/system/cpu/cpufreq (EPP, boost, max_freq)"]
        HWMON["/sys/class/hwmon (k10temp / zenpower)"]
        POWER_SUPPLY["/sys/class/power_supply (AC, Battery)"]
    end

    subgraph Core Daemons & Scripts (Python stdlib)
        COMMON["elitebook_common.py (Shared helpers)"]
        DISPATCHER["elitebook-thermal-profile (Core Dispatcher)"]
        IDLE_WATCHER["elitebook-idle-watcher (Idle Overlay)"]
        STEAM_WATCHER["elitebook-steam-game-watcher (Gaming Overlay)"]
        POWER_GUARD["elitebook-power-guard (Watchdog & Health Guard)"]
        HIBERNATE["elitebook-hibernate-preflight (Swapfile Hibernate Preflight)"]
    end

    subgraph Shared State (/run/elitebook-thermal-profile)
        CURRENT["current (Active profile state & limits)"]
        THERMAL["thermal (Thermal samples & peak record)"]
        GUARD_STATE["guard (Integrity state: ok/degraded)"]
        IDLE_STATE["idle-watcher (Idle overlay status)"]
        LOCK["dispatcher.lock (flock mutual exclusion)"]
    end

    subgraph User Interfaces & System Integrations
        GNOME_EXT["GNOME Shell Extension (elitebook-thermal-profile@...)"]
        SYSTEMD["systemd Units (.service, .timer, sleep hooks)"]
        UDEV["udev Rule (90-elitebook-thermal-profile.rules)"]
    end

    DISPATCHER --> COMMON
    IDLE_WATCHER --> COMMON
    STEAM_WATCHER --> COMMON
    POWER_GUARD --> COMMON
    HIBERNATE --> COMMON

    DISPATCHER --> SMU
    DISPATCHER --> CPUFREQ
    DISPATCHER --> CURRENT
    DISPATCHER -.-> LOCK

    IDLE_WATCHER --> HWMON
    IDLE_WATCHER --> THERMAL
    IDLE_WATCHER --> IDLE_STATE
    IDLE_WATCHER --> DISPATCHER

    STEAM_WATCHER --> DISPATCHER
    POWER_GUARD --> CURRENT
    POWER_GUARD --> GUARD_STATE
    POWER_GUARD --> DISPATCHER

    UDEV --> DISPATCHER
    SYSTEMD --> DISPATCHER
    SYSTEMD --> IDLE_WATCHER
    SYSTEMD --> POWER_GUARD
    GNOME_EXT --> CURRENT
    GNOME_EXT --> IDLE_STATE
    GNOME_EXT --> DISPATCHER
```

## 3. Mappa dei Componenti e Simboli (`src/`)

### [`src/elitebook_common.py`](file:///home/matteo/hp-elitebook-845-g8-ryzen-tuning/src/elitebook_common.py)

Modulo helper stdlib-only condiviso tra tutti i daemon e script.

| Simbolo | Tipo | Linea | Firma |
|---|---|---|---|
| `read_trimmed` | function | L37 | `def read_trimmed(path) -> str` |
| `is_uint` | function | L46 | `def is_uint(value) -> bool` |
| `read_key_value_file` | function | L50 | `def read_key_value_file(path) -> dict[str, str]` |
| `on_ac_power` | function | L65 | `def on_ac_power(power_supply_dir) -> bool` |
| `battery_device` | function | L90 | `def battery_device(power_supply_dir) -> Path | None` |
| `battery_capacity` | function | L104 | `def battery_capacity(power_supply_dir) -> int | None` |
| `cpu_temperature_c` | function | L115 | `def cpu_temperature_c(hwmon_dir) -> int | None` |
| `find_ryzenadj` | function | L136 | `def find_ryzenadj(configured, search_paths) -> str | None` |
| `kernel_lockdown_mode` | function | L160 | `def kernel_lockdown_mode(lockdown_path) -> str` |
| `acquire_dispatcher_lock` | function | L179 | `def acquire_dispatcher_lock(state_dir, timeout_s) -> typing.TextIO` |
| `sysfs_value_matches` | function | L197 | `def sysfs_value_matches(path, desired) -> bool` |
| `write_atomic` | function | L205 | `def write_atomic(path, content, mode) -> None` |

### [`src/elitebook-thermal-profile`](file:///home/matteo/hp-elitebook-845-g8-ryzen-tuning/src/elitebook-thermal-profile)

Dispatcher principale CLI e daemon: calcola limiti SMU, scrive sysfs idempotenti, espone `status --json`.

| Simbolo | Tipo | Linea | Firma |
|---|---|---|---|
| `die` | function | L146 | `def die(message) -> typing.NoReturn` |
| `warn` | function | L151 | `def warn(message) -> None` |
| `usage` | function | L155 | `def usage() -> None` |
| `truthy` | function | L190 | `def truthy(value) -> bool` |
| `is_supported_product` | function | L194 | `def is_supported_product(product) -> bool` |
| `on_ac_power` | function | L198 | `def on_ac_power() -> bool` |
| `battery_capacity` | function | L202 | `def battery_capacity() -> str | None` |
| `battery_is_low` | function | L207 | `def battery_is_low() -> bool` |
| `cpu_temperature_c` | function | L221 | `def cpu_temperature_c() -> str | None` |
| `read_key_value_file` | function | L226 | `def read_key_value_file(path) -> dict[str, str]` |
| `current_value` | function | L230 | `def current_value(key) -> str` |
| `thermal_value` | function | L234 | `def thermal_value(key) -> str` |
| `print_thermal_record` | function | L238 | `def print_thermal_record() -> None` |
| `print_status` | function | L264 | `def print_status() -> None` |
| `print_status_json` | function | L360 | `def print_status_json() -> None` |
| `find_ryzenadj` | function | L405 | `def find_ryzenadj() -> str | None` |
| `kernel_lockdown_mode` | function | L417 | `def kernel_lockdown_mode() -> str` |
| `detect_cpu_model` | function | L421 | `def detect_cpu_model() -> str` |
| `assert_supported_hardware` | function | L436 | `def assert_supported_hardware() -> None` |
| `detect_profile` | function | L467 | `def detect_profile() -> str` |
| `profile_conf_value` | function | L475 | `def profile_conf_value(key) -> tuple[str | None, int]` |
| `override_uint` | function | L498 | `def override_uint(key, minimum, maximum, current) -> str` |
| `override_epp` | function | L518 | `def override_epp(key, current) -> str` |
| `acquire_dispatcher_lock` | function | L531 | `def acquire_dispatcher_lock() -> typing.TextIO` |
| `apply_tuned_profile` | function | L538 | `def apply_tuned_profile(tuned_profile) -> None` |
| `apply_boost_and_freq` | function | L570 | `def apply_boost_and_freq(boost, max_freq) -> None` |
| `apply_epp` | function | L624 | `def apply_epp(epp) -> None` |
| `write_state` | function | L652 | `def write_state(profile, profile_source, epp, smu_status, stapm, fast, slow, apu, tctl, boost, max_freq) -> None` |
| `reexec_via_sudo` | function | L695 | `def reexec_via_sudo(argv) -> typing.NoReturn` |
| `main` | function | L714 | `def main(argv) -> int` |

### [`src/elitebook-power-guard`](file:///home/matteo/hp-elitebook-845-g8-ryzen-tuning/src/elitebook-power-guard)

Watchdog di integrità: verifica servizi mascherati, udev, headroom termico e fallback sysfs diretto.

| Simbolo | Tipo | Linea | Firma |
|---|---|---|---|
| `usage` | function | L37 | `def usage() -> None` |
| `log` | function | L47 | `def log(msg) -> None` |
| `warn` | function | L51 | `def warn(issues, msg) -> None` |
| `unit_exists` | function | L56 | `def unit_exists(unit) -> bool` |
| `unit_enabled_state` | function | L69 | `def unit_enabled_state(unit) -> str` |
| `unit_active_state` | function | L83 | `def unit_active_state(unit) -> str` |
| `os_release_family` | function | L97 | `def os_release_family(os_release_path) -> str` |
| `detect_expected_backend` | function | L118 | `def detect_expected_backend(os_release_path) -> str` |
| `configured_power_backend` | function | L128 | `def configured_power_backend(backend_conf, os_release_path) -> str` |
| `write_guard_state` | function | L147 | `def write_guard_state(status, mode, issues, changed, state_dir, guard_state_file) -> None` |
| `ensure_masked_units` | function | L169 | `def ensure_masked_units(mode, issues) -> int` |
| `ensure_power_backend` | function | L197 | `def ensure_power_backend(mode, backend_conf, os_release_path, issues) -> int` |
| `ensure_enabled_units` | function | L255 | `def ensure_enabled_units(mode, issues) -> int` |
| `ensure_watchers_active` | function | L284 | `def ensure_watchers_active(mode, issues) -> int` |
| `check_static_files` | function | L332 | `def check_static_files(thermal_profile, udev_rule, sleep_hook, issues) -> None` |
| `check_hardware_guard` | function | L354 | `def check_hardware_guard(thermal_profile, issues) -> None` |
| `check_cpufreq_shape` | function | L377 | `def check_cpufreq_shape(cpufreq_dir, issues) -> None` |
| `reload_udev_rules` | function | L409 | `def reload_udev_rules(mode, udev_rule, issues) -> None` |
| `apply_sysfs_fallback` | function | L429 | `def apply_sysfs_fallback(power_supply_dir, cpufreq_dir, state_dir, issues) -> None` |
| `apply_auto_profile` | function | L493 | `def apply_auto_profile(mode, thermal_profile, power_supply_dir, cpufreq_dir, state_dir, issues) -> None` |
| `check_smu_state` | function | L540 | `def check_smu_state(state_dir, issues) -> None` |
| `check_thermal_headroom` | function | L565 | `def check_thermal_headroom(state_dir, min_samples, over_target_percent, issues) -> None` |
| `main` | function | L602 | `def main(argv) -> int` |

### [`src/elitebook-idle-watcher`](file:///home/matteo/hp-elitebook-845-g8-ryzen-tuning/src/elitebook-idle-watcher)

Daemon di campionamento 1 Hz: applica overlay soft/deep idle e traccia i picchi termici.

| Simbolo | Tipo | Linea | Firma |
|---|---|---|---|
| `read_key_value_file` | function | L83 | `def read_key_value_file(path) -> dict[str, str]` |
| `dispatcher_lock` | function | L88 | `def dispatcher_lock() -> Iterator[None]` |
| `read_profile_state` | function | L102 | `def read_profile_state() -> dict[str, str]` |
| `read_idle_state` | function | L106 | `def read_idle_state() -> dict[str, str]` |
| `idle_active` | function | L110 | `def idle_active() -> bool` |
| `write_idle_state` | function | L114 | `def write_idle_state(base_state, stage, values, busy_percent, load1) -> None` |
| `clear_idle_state` | function | L147 | `def clear_idle_state() -> None` |
| `cpu_temperature_c` | function | L154 | `def cpu_temperature_c() -> int | None` |
| `ThermalTracker` | class | L159 | `class ThermalTracker` |
| `  .__init__` | method | L170 | `def __init__(self)` |
| `  ._reset` | method | L181 | `def _reset(self, state)` |
| `  .sample` | method | L194 | `def sample(self, state)` |
| `  .write` | method | L220 | `def write(self)` |
| `cpu_sample` | function | L245 | `def cpu_sample() -> tuple[int, int]` |
| `cpu_busy_percent` | function | L253 | `def cpu_busy_percent(previous, current) -> float` |
| `load1` | function | L261 | `def load1() -> float` |
| `write_sysfs` | function | L268 | `def write_sysfs(path, value) -> None` |
| `set_cpu_policy` | function | L275 | `def set_cpu_policy(epp, boost, max_freq) -> None` |
| `find_ryzenadj` | function | L300 | `def find_ryzenadj() -> Path | None` |
| `apply_ryzen_limits` | function | L308 | `def apply_ryzen_limits(stapm, fast, slow, apu, tctl, enabled) -> None` |
| `profile_state_is_complete` | function | L333 | `def profile_state_is_complete(state) -> bool` |
| `numeric_khz` | function | L348 | `def numeric_khz(value) -> int | None` |
| `conservative_max_freq` | function | L355 | `def conservative_max_freq(overlay_max_freq, base_max_freq) -> str` |
| `overlay_values` | function | L371 | `def overlay_values(base_state, stage) -> tuple[dict[str, str], bool]` |
| `apply_idle_overlay` | function | L409 | `def apply_idle_overlay(base_state, stage, busy_percent, current_load1) -> bool` |
| `restore_base_profile` | function | L439 | `def restore_base_profile(base_state) -> bool` |
| `gaming_profile_active` | function | L465 | `def gaming_profile_active(state) -> bool` |
| `check_once` | function | L471 | `def check_once(previous, idle_count) -> tuple[tuple[int, int], int]` |
| `print_status` | function | L524 | `def print_status() -> None` |
| `main` | function | L533 | `def main() -> int` |

### [`src/elitebook-steam-game-watcher`](file:///home/matteo/hp-elitebook-845-g8-ryzen-tuning/src/elitebook-steam-game-watcher)

Watcher dei processi Steam/gioco: eleva il profilo a `gaming` in modo trasparente.

| Simbolo | Tipo | Linea | Firma |
|---|---|---|---|
| `on_ac_power` | function | L53 | `def on_ac_power() -> bool` |
| `battery_capacity` | function | L59 | `def battery_capacity() -> int | None` |
| `battery_is_low` | function | L63 | `def battery_is_low() -> bool` |
| `read_current_state` | function | L71 | `def read_current_state() -> dict[str, str]` |
| `watcher_active` | function | L83 | `def watcher_active() -> bool` |
| `mark_active` | function | L90 | `def mark_active(game) -> None` |
| `clear_active` | function | L108 | `def clear_active() -> None` |
| `steam_appid_from_environ` | function | L115 | `def steam_appid_from_environ(environ_path) -> str | None` |
| `process_table` | function | L130 | `def process_table() -> dict[int, dict[str, int | str]]` |
| `steam_descendants` | function | L155 | `def steam_descendants(processes) -> set[int]` |
| `find_steam_game` | function | L180 | `def find_steam_game() -> tuple[dict[str, str] | None, bool]` |
| `apply_profile` | function | L202 | `def apply_profile(profile) -> bool` |
| `check_once` | function | L218 | `def check_once() -> bool` |
| `main` | function | L263 | `def main() -> int` |

### [`src/elitebook-hibernate-preflight`](file:///home/matteo/hp-elitebook-845-g8-ryzen-tuning/src/elitebook-hibernate-preflight)

Validatore pre-ibernazione: controlla swapfile btrfs, offset, lockdown del kernel e boot args.

| Simbolo | Tipo | Linea | Firma |
|---|---|---|---|
| `usage` | function | L26 | `def usage() -> None` |
| `log` | function | L41 | `def log(msg) -> None` |
| `fail` | function | L45 | `def fail(msg) -> typing.NoReturn` |
| `require_file` | function | L50 | `def require_file(path) -> None` |
| `require_command` | function | L56 | `def require_command(cmd, hint) -> None` |
| `parse_config` | function | L61 | `def parse_config(config_path) -> dict[str, str]` |
| `main` | function | L96 | `def main(argv) -> int` |

## 4. Estensione GNOME Shell (`gnome-extension/`)

Interfaccia grafica integrata nel pannello superiore di GNOME Shell (`elitebook-thermal-profile@matteopasseri.github.io`):
- [`extension.js`](file:///home/matteo/hp-elitebook-845-g8-ryzen-tuning/gnome-extension/elitebook-thermal-profile@matteopasseri.github.io/extension.js):
  - `PROFILE_SCRIPT`: risolto dinamicamente tramite `GLib.file_test` tra `/usr/local/sbin` e `/usr/bin`.
  - `ThermalIndicator`: pulsante pannello con menu a tendina.
  - Monitoraggio real-time: `Gio.File.monitor_directory` su `/run/elitebook-thermal-profile` con debouncing.
  - Esecuzione non bloccante dei profili (`auto`, `gaming`, `cool`) tramite `Gio.Subprocess` e `pkexec`.

## 5. Contratti File di Stato (`/run/elitebook-thermal-profile/`)

| File | Scritto da | Letto da | Scopo |
|---|---|---|---|
| `current` | `elitebook-thermal-profile` | GNOME, power-guard, CLI status | Profilo attivo, SMU status, limiti Watt, EPP, boost, batteria |
| `guard` | `elitebook-power-guard` | Monitoring, health check | Stato integrità (`ok`/`degraded`), numero issue, timestamp |
| `thermal` | `elitebook-idle-watcher` | `status`, `power-guard` | Campioni totali, picco termico, campioni sopra target |
| `idle-watcher` | `elitebook-idle-watcher` | GNOME, `status` | Stato overlay idle (`active=0/1`, `stage=soft/deep`) |
| `fallback` | `elitebook-power-guard` | Debug, system recovery | Stato di emergenza sysfs applicato in caso di guasto dispatcher |
| `dispatcher.lock` | Tutti i componenti | Tutti i componenti | Mutua esclusione flock sulle modifiche ai profili hardware |

## 6. Suite di Test e Verifica

- **Test unitari Python (`pytest`):**
  - `tests/test_dispatcher.py`: verifica riapplicazione sysfs idempotente, serializzazione JSON e parsing configurazione.
  - `tests/test_idle_watcher.py`: verifica logica soglie e transizioni soft/deep idle.
  - `tests/test_steam_game_watcher.py`: verifica rilevamento alimentazione e ripristino profilo orfano.
  - `tests/test_thermal_tracker.py`: verifica campionamento picchi termici e reset a cambio profilo.
  - `tests/test_power_guard.py`: verifica report termico, stati SMU e scrittura atomica guard.
  - `tests/test_hibernate_preflight.py`: verifica validazione file di configurazione btrfs.
- **Integrazione di sistema (`tests/*.sh`):**
  - `test-platform-detection.sh`, `test-hardware-guard.sh`, `test-profile-config.sh`, `test-smu-fallback.sh`, `test-version-consistency.sh`, `verify-systemd-units.sh`.
- **Qualità e Tipizzazione:**
  - `mypy --strict --scripts-are-modules`
  - `ruff check src tests`
  - `ruff format --check src tests`
