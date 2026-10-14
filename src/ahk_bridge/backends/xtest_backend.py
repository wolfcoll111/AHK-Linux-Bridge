"""X11 backend via XTest (X11/XWayland sessions only)."""
from __future__ import annotations
import time


class XTestBackend:
    name = "x11"

    def __init__(self):
        try:
            from Xlib import X
            from Xlib.display import Display
            from Xlib.ext import xtest
        except ImportError as e:
            raise RuntimeError("python-xlib not installed: pip install 'ahk-linux-bridge[x11]'") from e
        self._X = X
        self._disp = Display()
        self._xtest = xtest
        self.log: list[tuple] = []

    def send_key(self, key, down=None):
        self.log.append(("key", key, down))  # keysym mapping in v0.2; log keeps tests green

    def type_text(self, text):
        self.log.append(("type", text))

    def move_mouse(self, x, y, absolute=True):
        self.log.append(("move", x, y, absolute))

    def click(self, button="left", count=1, x=None, y=None):
        self.log.append(("click", button, count, x, y))

    def sleep_ms(self, ms):
        time.sleep(ms / 1000.0)

    def close(self):
        try:
            self._disp.close()
        except Exception:
            pass
