"""X11 backend via XTest (X11/XWayland sessions only).

v0.2: real key/motion/button injection via python-xlib XTest extension.
"""
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
        try:
            disp = Display()
        except Exception as e:
            raise RuntimeError(f"cannot open X display: {e}") from e
        self._X = X
        self._disp = disp
        self._xtest = xtest
        self.log: list[tuple] = []

    def _keycode(self, key: str) -> int:
        from Xlib import XK
        # single char -> keysym; named keys -> XK constant
        if len(key) == 1:
            sym = XK.string_to_keysym(key)
        else:
            name = key if key.startswith("XK_") else "XK_" + key
            sym = getattr(XK, name, 0) or XK.string_to_keysym(key)
        if not sym:
            raise ValueError(f"unknown key {key!r}")
        code = self._disp.keysym_to_keycode(sym)
        if not code:
            raise ValueError(f"no keycode for {key!r}")
        return code

    def send_key(self, key, down=None):
        X = self._X
        try:
            code = self._keycode(key)
        except ValueError:
            self.log.append(("key", key, down))
            return
        if down is None:
            self._xtest.fake_input(self._disp, X.KeyPress, code)
            self._disp.sync()
            self._xtest.fake_input(self._disp, X.KeyRelease, code)
            self._disp.sync()
        else:
            ev = X.KeyPress if down else X.KeyRelease
            self._xtest.fake_input(self._disp, ev, code)
            self._disp.sync()
        self.log.append(("key", key, down))

    def type_text(self, text):
        for ch in text:
            self.send_key(ch)
            time.sleep(0.002)
        self.log.append(("type", text))

    def move_mouse(self, x, y, absolute=True):
        if absolute:
            self._disp.warp_pointer(x, y)
        else:
            # relative: query current position first
            ptr = self._disp.screen().root.query_pointer()
            self._disp.warp_pointer(ptr.root_x + x, ptr.root_y + y)
        self._disp.sync()
        self.log.append(("move", x, y, absolute))

    def click(self, button="left", count=1, x=None, y=None):
        X = self._X
        if x is not None and y is not None:
            self.move_mouse(x, y, absolute=True)
        btn = {"left": 1, "middle": 2, "right": 3}.get(button, 1)
        for _ in range(max(1, int(count))):
            self._xtest.fake_input(self._disp, X.ButtonPress, btn)
            self._disp.sync()
            time.sleep(0.01)
            self._xtest.fake_input(self._disp, X.ButtonRelease, btn)
            self._disp.sync()
            time.sleep(0.01)
        self.log.append(("click", button, count, x, y))

    def sleep_ms(self, ms):
        time.sleep(max(0, ms) / 1000.0)

    def close(self):
        try:
            self._disp.close()
        except Exception:
            pass
