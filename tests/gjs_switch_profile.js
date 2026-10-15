// SPDX-License-Identifier: GPL-3.0-or-later
//
// Runs the GNOME indicator's real profile switching code under plain gjs:
//   gjs -m gjs_switch_profile.js <module path> <bus address> <profile> <pkexec argv as JSON>
// and prints its result as one line of JSON.
//
// No top-level await: the rest of the module would then run as a promise
// job, and gjs runs no other job until it returns, so the main loop below
// would spin forever without ever resolving a promise.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const [modulePath, address, profile, pkexecJson] = ARGV;

const bus = Gio.DBusConnection.new_for_address_sync(
    address,
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
        Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
    null,
    null);

const loop = new GLib.MainLoop(null, false);
let output = '';
import(Gio.File.new_for_path(modulePath).get_uri())
    .then(({switchProfile}) =>
        switchProfile(profile, {pkexecArgv: JSON.parse(pkexecJson), bus}))
    .then(result => {
        output = JSON.stringify(result);
    })
    .catch(error => {
        output = JSON.stringify({rejected: String(error)});
    })
    .finally(() => loop.quit());
loop.run();
print(output);
