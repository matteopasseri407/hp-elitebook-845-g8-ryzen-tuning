# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in polkit authority for the D-Bus front end tests.

Owns org.freedesktop.PolicyKit1 on the bus at argv[1] and answers
CheckAuthorization with the word in the file at argv[2] ("yes" or "no"),
read on every call so a test can change its mind. Each call is appended to
the file at argv[3] as one JSON line, so a test can assert what was asked.
"""

from __future__ import annotations

import json
import sys
import typing
from pathlib import Path

import gi  # type: ignore[import-untyped, import-not-found, unused-ignore]

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import (  # type: ignore[import-untyped, import-not-found, unused-ignore]  # noqa: E402
    Gio,
    GLib,
)

XML = """<node>
  <interface name="org.freedesktop.PolicyKit1.Authority">
    <method name="CheckAuthorization">
      <arg type="(sa{sv})" name="subject" direction="in"/>
      <arg type="s" name="action_id" direction="in"/>
      <arg type="a{ss}" name="details" direction="in"/>
      <arg type="u" name="flags" direction="in"/>
      <arg type="s" name="cancellation_id" direction="in"/>
      <arg type="(bba{ss})" name="result" direction="out"/>
    </method>
  </interface>
</node>
"""


def main() -> int:
    address, answer_file, log_file = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    connection = Gio.DBusConnection.new_for_address_sync(
        address,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None,
        None,
    )

    def on_call(
        _connection: typing.Any,
        _sender: str,
        _path: str,
        _interface: str,
        _method: str,
        parameters: typing.Any,
        invocation: typing.Any,
    ) -> None:
        subject, action_id, _details, flags, _cancel = parameters.unpack()
        with log_file.open("a", encoding="utf-8") as log:
            log.write(
                json.dumps(
                    {
                        "kind": subject[0],
                        "subject": subject[1],
                        "action": action_id,
                        "flags": flags,
                    }
                )
                + "\n"
            )
        allowed = answer_file.read_text(encoding="utf-8").strip() == "yes"
        invocation.return_value(GLib.Variant("((bba{ss}))", ((allowed, False, {}),)))

    node = Gio.DBusNodeInfo.new_for_xml(XML)
    # register_object is deprecated; its replacement arrived in GLib 2.84.
    if hasattr(connection, "register_object_with_closures2"):
        register = connection.register_object_with_closures2
    else:
        register = connection.register_object
    register(
        "/org/freedesktop/PolicyKit1/Authority", node.interfaces[0], on_call, None, None
    )
    loop = GLib.MainLoop()
    Gio.bus_own_name_on_connection(
        connection,
        "org.freedesktop.PolicyKit1",
        Gio.BusNameOwnerFlags.NONE,
        lambda *_: print("ready", flush=True),
        lambda *_: loop.quit(),
    )
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
