"""The button.

The arcade button is wired to a XIAO RP2040 running firmware/xiao_button.ino,
which shows up as a USB keyboard and sends F13 on click, F14 on double-click,
F15 on long-press. On Linux we read it with evdev by device name so it works
with no desktop session. Any other keyboard-like trigger (a BLE clicker, the
touchscreen's on-screen button) can fire the same events.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

Handler = Callable[[str], None]   # receives "click" | "double" | "long"


class Button:
    _handlers: list[Handler] = []
    _lock = threading.Lock()

    @classmethod
    def on(cls, handler: Handler) -> None:
        with cls._lock:
            cls._handlers.append(handler)

    @classmethod
    def fire(cls, event: str) -> None:
        with cls._lock:
            handlers = list(cls._handlers)
        for h in handlers:
            try:
                h(event)
            except Exception:
                log.exception("button handler failed")


KEYMAP = {"KEY_F13": "click", "KEY_F14": "double", "KEY_F15": "long"}


class EvdevButton:
    """Reads the XIAO (or any keyboard) via evdev and fires Button events."""

    def __init__(self, device_name_contains: str = "Nudge", keymap: dict[str, str] | None = None):
        self.match = device_name_contains.lower()
        self.keymap = keymap or KEYMAP
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _find(self):
        import evdev
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            if self.match in dev.name.lower():
                return dev
        return None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="button")
        self._thread.start()

    def _loop(self) -> None:
        import evdev
        from evdev import ecodes
        dev = None
        while not self._stop.is_set():
            if dev is None:
                dev = self._find()
                if dev is None:
                    self._stop.wait(2.0)        # unplugged; keep looking
                    continue
                log.info("button device: %s", dev.name)
            try:
                for ev in dev.read_loop():
                    if self._stop.is_set():
                        return
                    if ev.type == ecodes.EV_KEY and ev.value == 1:     # key down
                        name = ecodes.KEY[ev.code] if ev.code in ecodes.KEY else str(ev.code)
                        if name in self.keymap:
                            Button.fire(self.keymap[name])
            except OSError:
                log.warning("button device went away; rescanning")
                dev = None

    def stop(self) -> None:
        self._stop.set()
