#!/usr/bin/env python3
"""Fullscreen WebKit window for the 5" panel. Loads the local Nudge page.

Used instead of Chromium: the Chromium snap can't launch on the minimized Jetson
image (snap-confine lacks its capabilities), and WebKitGTK is lighter anyway.

    python3 scripts/kiosk_webview.py [http://localhost:8765/]
"""

import sys
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.0")
from gi.repository import Gtk, WebKit2, Gdk, GLib  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765/"


def main() -> None:
    win = Gtk.Window(title="Nudge")
    win.set_decorated(False)
    # no window manager under xinit, so fullscreen() alone does nothing: size it ourselves
    scr = Gdk.Screen.get_default()
    w, h = scr.get_width(), scr.get_height()
    win.set_default_size(w, h)
    win.set_size_request(w, h)
    win.move(0, 0)
    win.fullscreen()
    win.connect("destroy", Gtk.main_quit)

    settings = WebKit2.Settings()
    settings.set_enable_developer_extras(False)
    settings.set_enable_smooth_scrolling(True)
    settings.set_enable_write_console_messages_to_stdout(False)
    # the page is local and trusted; let it play the three words without a tap first
    settings.set_media_playback_requires_user_gesture(False)
    settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)

    ctx = WebKit2.WebContext.get_default()
    ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
    view = WebKit2.WebView.new_with_context(ctx)
    view.set_settings(settings)
    view.set_background_color(Gdk.RGBA(0.06, 0.06, 0.07, 1))
    win.add(view)

    # keep retrying until the service answers; the kiosk may start before it does
    def load(_=None):
        view.load_uri(URL)
        return False

    def on_failed(_view, _event, uri, _err):
        GLib.timeout_add(1500, load)
        return True

    view.connect("load-failed", on_failed)
    win.show_all()
    load()
    Gtk.main()


if __name__ == "__main__":
    main()
