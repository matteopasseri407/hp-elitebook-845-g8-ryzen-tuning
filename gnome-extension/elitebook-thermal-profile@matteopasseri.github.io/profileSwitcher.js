// SPDX-License-Identifier: GPL-3.0-or-later
//
// Switches the profile through the D-Bus front end, where polkit lets the
// person at the active session do it without a password, and falls back to
// pkexec whenever the front end cannot answer: not installed, not running,
// an older version, a timeout. An answer from the front end itself (refused,
// not authorized, unknown profile) is final and never retried through
// pkexec, so a refusal is reported once instead of becoming a password
// prompt.
//
// Only Gio and GLib are used here, so the module also runs under plain gjs
// for the tests.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export const BUS_NAME = 'io.github.matteopasseri.EliteBookThermalProfile1';
const OBJECT_PATH = '/io/github/matteopasseri/EliteBookThermalProfile1';
const INTERFACE = BUS_NAME;
const ERROR_PREFIX = `${BUS_NAME}.Error.`;
// Long enough for a polkit password prompt plus the daemon's own 30 s.
const CALL_TIMEOUT_MS = 5 * 60 * 1000;

function callFrontEnd(bus, profile) {
    return new Promise((resolve, reject) => {
        bus.call(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            'SetProfile',
            new GLib.Variant('(s)', [profile]),
            new GLib.VariantType('(s)'),
            Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
            CALL_TIMEOUT_MS,
            null,
            (connection, result) => {
                try {
                    const [message] = connection.call_finish(result).deepUnpack();
                    resolve(message);
                } catch (error) {
                    reject(error);
                }
            });
    });
}

// The error name when the front end itself answered, otherwise null.
function frontEndErrorName(error) {
    if (!(error instanceof GLib.Error))
        return null;
    const name = Gio.DBusError.get_remote_error(error);
    return name?.startsWith(ERROR_PREFIX) ? name : null;
}

function runPkexec(argv) {
    return new Promise(resolve => {
        let proc;
        try {
            proc = Gio.Subprocess.new(
                argv,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        } catch (error) {
            resolve({ok: false, message: error.message, via: 'pkexec'});
            return;
        }
        proc.communicate_utf8_async(null, null, (_proc, result) => {
            try {
                const [, stdout, stderr] = proc.communicate_utf8_finish(result);
                if (proc.get_successful()) {
                    resolve({
                        ok: true,
                        message: stdout.trim().split('\n').pop() ?? '',
                        via: 'pkexec',
                    });
                } else {
                    resolve({ok: false, message: stderr.trim(), via: 'pkexec'});
                }
            } catch (error) {
                resolve({ok: false, message: error.message, via: 'pkexec'});
            }
        });
    });
}

// Resolves to {ok, message, via}; never rejects. `bus` defaults to the
// system bus and is a parameter only for the tests.
export async function switchProfile(profile, {pkexecArgv, bus = null}) {
    try {
        const message = await callFrontEnd(bus ?? Gio.DBus.system, profile);
        return {ok: true, message, via: 'dbus'};
    } catch (error) {
        if (frontEndErrorName(error) !== null) {
            Gio.DBusError.strip_remote_error(error);
            return {ok: false, message: error.message, via: 'dbus'};
        }
    }
    return runPkexec(pkexecArgv);
}
