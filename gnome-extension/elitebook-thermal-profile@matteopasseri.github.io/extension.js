// SPDX-License-Identifier: GPL-3.0-or-later
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const PROFILE_SCRIPT = '/usr/local/sbin/elitebook-thermal-profile';
const STATE_DIR = '/run/elitebook-thermal-profile';
const STATE_FILE = '/run/elitebook-thermal-profile/current';
const IDLE_STATE_FILE = '/run/elitebook-thermal-profile/idle-watcher';

const PROFILES = {
    ac: {
        label: 'Balanced',
        icon: 'bolt-symbolic.svg',
        detail: 'default daily mode',
    },
    performance: {
        label: 'Performance',
        icon: 'bolt-symbolic.svg',
        detail: 'snappy plugged-in mode',
    },
    gaming: {
        label: 'Gaming',
        icon: 'gamepad-symbolic.svg',
        detail: 'more APU room',
    },
    battery: {
        label: 'Battery',
        icon: 'leaf-symbolic.svg',
        detail: 'normal unplugged mode',
    },
    'battery-saver': {
        label: 'Battery Saver',
        icon: 'leaf-symbolic.svg',
        detail: 'low-battery guard',
    },
    cool: {
        label: 'Cool',
        icon: 'cool-symbolic.svg',
        detail: 'quiet and cool',
    },
};

const PROFILE_ORDER = ['ac', 'performance', 'gaming', 'battery', 'battery-saver', 'cool'];

class ThermalIndicator extends PanelMenu.Button {
    static {
        GObject.registerClass(this);
    }

    constructor(extension) {
        super(0.5, 'EliteBook Thermal Profile');

        this._extension = extension;
        this._profile = 'ac';
        this._items = {};
        this._fallbackTimeoutId = 0;
        this._monitors = [];
        this._coalesceId = 0;

        this._icon = new St.Icon({
            style_class: 'system-status-icon elitebook-thermal-panel-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._icon);

        this._buildMenu();
        this._refresh();
        this._installMonitors();

        // Slow safety-net poll in case a FileMonitor is missed (e.g. tmpfs
        // edge cases or bind-mounts). FileMonitors do the real work.
        this._fallbackTimeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            60,
            () => {
                this._installMonitors();
                this._refresh();
                return GLib.SOURCE_CONTINUE;
            },
        );
    }

    _installMonitors() {
        if (this._monitors.length > 0)
            return;

        try {
            const monitor = Gio.File.new_for_path(STATE_DIR).monitor_directory(
                Gio.FileMonitorFlags.NONE,
                null,
            );
            monitor.set_rate_limit(200);
            monitor.connect('changed', (_monitor, file) => {
                const path = file?.get_path?.();
                if (path === STATE_FILE || path === IDLE_STATE_FILE)
                    this._scheduleRefresh();
            });
            this._monitors.push(monitor);
        } catch (_error) {
            // The state directory may not exist yet at extension start; the
            // fallback timer will pick it up on the next tick.
        }
    }

    _scheduleRefresh() {
        if (this._coalesceId)
            return;

        this._coalesceId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            150,
            () => {
                this._coalesceId = 0;
                this._refresh();
                return GLib.SOURCE_REMOVE;
            },
        );
    }

    _buildMenu() {
        this._modeItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this.menu.addMenuItem(this._modeItem);

        this._baseItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this.menu.addMenuItem(this._baseItem);

        this._idleItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this.menu.addMenuItem(this._idleItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._autoItem = new PopupMenu.PopupMenuItem('Return to Auto');
        this._autoItem.connect('activate', () => this._applyProfile('auto'));
        this.menu.addMenuItem(this._autoItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._manualHeader = new PopupMenu.PopupMenuItem('Manual profiles', {reactive: false});
        this.menu.addMenuItem(this._manualHeader);

        for (const profile of PROFILE_ORDER) {
            const data = PROFILES[profile];
            const item = new PopupMenu.PopupImageMenuItem(
                data.label,
                this._iconFor(profile),
                {style_class: 'elitebook-thermal-profile-item'},
            );

            item.connect('activate', () => this._applyProfile(profile));
            this._items[profile] = item;
            this.menu.addMenuItem(item);
        }

        this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen)
                this._refresh();
        });
    }

    _iconFor(profile) {
        const iconName = PROFILES[profile]?.icon ?? PROFILES.ac.icon;
        const path = GLib.build_filenamev([this._extension.path, 'icons', iconName]);
        return Gio.FileIcon.new(Gio.File.new_for_path(path));
    }

    _readKeyValueFile(path) {
        try {
            const [ok, bytes] = GLib.file_get_contents(path);
            if (!ok)
                return null;

            const state = {};
            for (const line of new TextDecoder().decode(bytes).trim().split('\n')) {
                const [key, ...rest] = line.split('=');
                if (key)
                    state[key] = rest.join('=');
            }
            return state;
        } catch (_error) {
            return null;
        }
    }

    _readState() {
        return this._readKeyValueFile(STATE_FILE);
    }

    _readIdleState() {
        return this._readKeyValueFile(IDLE_STATE_FILE);
    }

    _sourceLabel(source) {
        switch (source) {
        case 'manual':
            return 'Manual';
        case 'steam-game-watcher':
            return 'Steam';
        case 'system-auto':
        case 'auto':
            return 'Auto';
        default:
            return source ? source : 'Unknown';
        }
    }

    _idleLabel(idleState) {
        if (idleState?.active !== '1')
            return 'Off';

        if (idleState.stage === 'deep')
            return 'Deep - maximum idle saving';

        return 'Soft - responsive saving';
    }

    _refresh() {
        const state = this._readState();
        const idleState = this._readIdleState();
        const profile = state?.profile in PROFILES ? state.profile : 'ac';
        const idleActive = idleState?.active === '1';
        const idleStage = idleState?.stage ?? '';
        const effectiveIconProfile = idleActive && idleStage === 'deep'
            ? 'battery-saver'
            : profile;
        this._profile = profile;
        this._icon.gicon = this._iconFor(effectiveIconProfile);

        for (const [name, item] of Object.entries(this._items)) {
            item.setOrnament(name === profile
                ? PopupMenu.Ornament.CHECK
                : PopupMenu.Ornament.NONE);
        }

        const source = state?.source ?? '';
        const data = PROFILES[profile];
        this._modeItem.label.text = `Control: ${this._sourceLabel(source)}`;
        this._baseItem.label.text = `Base profile: ${data.label} - ${data.detail}`;
        this._idleItem.label.text = `Idle overlay: ${this._idleLabel(idleState)}`;
        this._autoItem.setOrnament(source === 'manual'
            ? PopupMenu.Ornament.NONE
            : PopupMenu.Ornament.CHECK);
        this.accessible_name = `EliteBook power: ${data.label}, idle ${this._idleLabel(idleState)}`;
    }

    _applyProfile(profile) {
        try {
            const proc = Gio.Subprocess.new(
                ['pkexec', PROFILE_SCRIPT, profile],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
            );

            proc.communicate_utf8_async(null, null, (_proc, result) => {
                try {
                    const [, stdout, stderr] = proc.communicate_utf8_finish(result);
                    if (proc.get_successful()) {
                        this._refresh();
                        Main.notify(
                            'EliteBook Power',
                            stdout.trim().split('\n').pop() ?? 'Profile applied.',
                        );
                    } else {
                        Main.notifyError(
                            'EliteBook Power',
                            stderr.trim() || 'Profile switch failed.',
                        );
                    }
                } catch (error) {
                    Main.notifyError('EliteBook Power', error.message);
                }
            });
        } catch (error) {
            Main.notifyError('EliteBook Power', error.message);
        }
    }

    destroy() {
        if (this._fallbackTimeoutId) {
            GLib.source_remove(this._fallbackTimeoutId);
            this._fallbackTimeoutId = 0;
        }
        if (this._coalesceId) {
            GLib.source_remove(this._coalesceId);
            this._coalesceId = 0;
        }
        for (const monitor of this._monitors)
            monitor.cancel();
        this._monitors = [];
        super.destroy();
    }
}

export default class EliteBookThermalProfileExtension extends Extension {
    enable() {
        this._indicator = new ThermalIndicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
