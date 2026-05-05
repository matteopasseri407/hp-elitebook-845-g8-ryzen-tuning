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
const STATE_FILE = '/run/elitebook-thermal-profile/current';
const IDLE_STATE_FILE = '/run/elitebook-thermal-profile/idle-watcher';

const PROFILES = {
    ac: {
        label: 'AC',
        icon: 'bolt-symbolic.svg',
        detail: '30 W burst, 18 W sustained, efficient EPP',
    },
    performance: {
        label: 'Perf',
        icon: 'bolt-symbolic.svg',
        detail: '30 W burst, 18 W sustained, 90 C',
    },
    gaming: {
        label: 'Gaming',
        icon: 'gamepad-symbolic.svg',
        detail: '30 W burst, 23 W sustained, 92 C',
    },
    battery: {
        label: 'Battery',
        icon: 'leaf-symbolic.svg',
        detail: '30 W burst, 15 W sustained, 88 C',
    },
    'battery-saver': {
        label: 'Saver',
        icon: 'leaf-symbolic.svg',
        detail: '15 W burst, 8 W sustained, boost off',
    },
    cool: {
        label: 'Cool',
        icon: 'cool-symbolic.svg',
        detail: '22 W burst, 12 W sustained, 85 C',
    },
};

class ThermalIndicator extends PanelMenu.Button {
    static {
        GObject.registerClass(this);
    }

    constructor(extension) {
        super(0.5, 'EliteBook Thermal Profile');

        this._extension = extension;
        this._profile = 'ac';
        this._items = {};
        this._timeoutId = 0;

        this._icon = new St.Icon({
            style_class: 'system-status-icon elitebook-thermal-panel-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._icon);

        this._buildMenu();
        this._refresh();
        this._timeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            10,
            () => {
                this._refresh();
                return GLib.SOURCE_CONTINUE;
            },
        );
    }

    _buildMenu() {
        for (const profile of ['ac', 'performance', 'gaming', 'battery', 'battery-saver', 'cool']) {
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

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const autoItem = new PopupMenu.PopupMenuItem('Auto from power state');
        autoItem.connect('activate', () => this._applyProfile('auto'));
        this.menu.addMenuItem(autoItem);

        this._statusItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this.menu.addMenuItem(this._statusItem);

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

    _refresh() {
        const state = this._readState();
        const idleState = this._readIdleState();
        const profile = state?.profile in PROFILES ? state.profile : 'ac';
        const idleActive = idleState?.active === '1';
        this._profile = profile;
        this._icon.gicon = this._iconFor(profile);

        for (const [name, item] of Object.entries(this._items)) {
            item.setOrnament(name === profile
                ? PopupMenu.Ornament.CHECK
                : PopupMenu.Ornament.NONE);
        }

        const data = PROFILES[profile];
        if (idleActive) {
            const stage = idleState.stage === 'deep' ? 'deep idle' : 'soft idle';
            this._statusItem.label.text = `${data.label}: ${stage}, ${idleState.epp ?? 'power'} EPP`;
            this.accessible_name = `EliteBook thermal profile: ${data.label}, ${stage}`;
        } else {
            this._statusItem.label.text = `${data.label}: ${data.detail}`;
            this.accessible_name = `EliteBook thermal profile: ${data.label}`;
        }
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
                            'EliteBook Thermal Profile',
                            stdout.trim().split('\n').pop() ?? 'Profile applied.',
                        );
                    } else {
                        Main.notifyError(
                            'EliteBook Thermal Profile',
                            stderr.trim() || 'Profile switch failed.',
                        );
                    }
                } catch (error) {
                    Main.notifyError('EliteBook Thermal Profile', error.message);
                }
            });
        } catch (error) {
            Main.notifyError('EliteBook Thermal Profile', error.message);
        }
    }

    destroy() {
        if (this._timeoutId) {
            GLib.source_remove(this._timeoutId);
            this._timeoutId = 0;
        }
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
