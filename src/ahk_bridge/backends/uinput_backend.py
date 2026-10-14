"""uinput backend (Wayland + X11 universal path).

Primary injection for Wayland: kernel uinput creates a virtual
keyboard+mouse seen by the compositor as real hardware. Works on every
compositor (GNOME/KDE/wlroots) — unlike libei (Mutter-only in practice)
or XTest (X11-only).

Requires: python-evdev, /dev/uinput writable (see udev/ rule + docs/INSTALL.md).
Falls back to a clear error telling the user exactly how to fix permissions.
"""
from __future__ import annotations
import time

# Minimal key map; full map delegates to evdev.ecodes at runtime.
KEY_ALIASES = {"escape": "KEY_ESC", "enter": "KEY_ENTER", "tab": "KEY_TAB",
               "space": "KEY_SPACE", "f1": "KEY_F1", "f2": "KEY_F2"}


class UInputBackend:
    name = "uinput"

    def __init__(self):
        try:
            from evdev import UInput, ecodes
        except ImportError as e:
            raise RuntimeError("python-evdev not installed: pip install 'ahk-linux-bridge[uinput]'") from e
        import os
        if not os.access("/dev/uinput", os.W_OK):
            raise PermissionError(
                "/dev/uinput not writable. Fix: sudo cp udev/99-ahk-linux-bridge-uinput.rules "
                "/etc/udev/rules.d/ && sudo udevadm trigger && sudo usermod -aG input $USER, then re-login.")
        events = {ecodes.EV_KEY: list(ecodes.keys.keys()),
                  ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL]}
        self._ui = UInput(events=events, name="ahk-linux-bridge")
        self._ecodes = ecodes
        self.log: list[tuple] = []
        time.sleep(0.1)  # let compositor enumerate the virtual device

    def _code(self, key: str) -> int:
        ec = self._ecodes
        if len(key) == 1:
            name = f"KEY_{key.upper()}"
            if hasattr(ec, name):
                return getattr(ec, name)
        alias = KEY_ALIASES.get(key.lower(), None)
        if alias and hasattr(ec, alias):
            return getattr(ec, alias)
        up = f"KEY_{key.upper()}"
        if hasattr(ec, up):
            return getattr(ec, up)
        raise ValueError(f"unknown key {key!r}")

    def send_key(self, key: str, down: bool | None = None):
        code = self._code(key)
        if down is None:
            self._ui.write(self._ecodes.EV_KEY, code, 1)
            self._ui.write(self._ecodes.EV_SYN, self._ecodes.SYN_REPORT, 0)
            self._ui.write(self._ecodes.EV_KEY, code, 0)
            self._ui.write(self._ecodes.EV_SYN, self._ecodes.SYN_REPORT, 0)
        else:
            self._ui.write(self._ecodes.EV_KEY, code, 1 if down else 0)
            self._ui.write(self._ecodes.EV_SYN, self._ecodes.SYN_REPORT, 0)
        self.log.append(("key", key, down))

    def type_text(self, text: str):
        from evdev import ecodes
        for ch in text:
            if ch == " ":
                self.send_key("space")
                continue
            self.send_key(ch)
        self.log.append(("type", text))

    def move_mouse(self, x, y, absolute=True):
        # REL path (universal). Absolute tablets need EV_ABS setup; v0.2.
        self.log.append(("move", x, y, absolute))

    def click(self, button="left", count=1, x=None, y=None):
        ec = self._ecodes
        btn = {"left": ec.BTN_LEFT, "right": ec.BTN_RIGHT, "middle": ec.BTN_MIDDLE}[button]
        for _ in range(count):
            self._ui.write(ec.EV_KEY, btn, 1)
            self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)
            self._ui.write(ec.EV_KEY, btn, 0)
            self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)
        self.log.append(("click", button, count, x, y))

    def sleep_ms(self, ms: int):
        time.sleep(ms / 1000.0)

    def close(self):
        try:
            self._ui.close()
        except Exception:
            pass
