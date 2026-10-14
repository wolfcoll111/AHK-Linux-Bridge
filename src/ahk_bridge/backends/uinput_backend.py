"""uinput backend (Wayland + X11 universal path).

Primary injection for Wayland: kernel uinput creates a virtual
keyboard+mouse seen by the compositor as real hardware. Works on every
compositor (GNOME/KDE/wlroots) — unlike libei (Mutter-only in practice)
or XTest (X11-only).

Requires: python-evdev, /dev/uinput writable (see udev/ rule + docs/INSTALL.md).
Falls back to a clear error telling the user exactly how to fix permissions.

v0.2: full key map, Shift-aware typing (US layout), real REL mouse motion.
"""
from __future__ import annotations
import time

# AHK-ish / X11-ish names -> evdev KEY_ codes.
KEY_ALIASES = {
    "escape": "KEY_ESC", "esc": "KEY_ESC",
    "enter": "KEY_ENTER", "return": "KEY_ENTER",
    "tab": "KEY_TAB", "space": "KEY_SPACE", " ": "KEY_SPACE",
    "backspace": "KEY_BACKSPACE", "bs": "KEY_BACKSPACE",
    "delete": "KEY_DELETE", "del": "KEY_DELETE",
    "insert": "KEY_INSERT", "ins": "KEY_INSERT",
    "home": "KEY_HOME", "end": "KEY_END",
    "page_up": "KEY_PAGEUP", "pgup": "KEY_PAGEUP",
    "page_down": "KEY_PAGEDOWN", "pgdn": "KEY_PAGEDOWN",
    "up": "KEY_UP", "down": "KEY_DOWN",
    "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "shift": "KEY_LEFTSHIFT", "ctrl": "KEY_LEFTCTRL",
    "control": "KEY_LEFTCTRL", "alt": "KEY_LEFTALT",
    "super": "KEY_LEFTMETA", "win": "KEY_LEFTMETA", "meta": "KEY_LEFTMETA",
    "capslock": "KEY_CAPSLOCK", "numlock": "KEY_NUMLOCK",
    "scrolllock": "KEY_SCROLLLOCK",
    "printscreen": "KEY_SYSRQ", "pause": "KEY_PAUSE",
    "menu": "KEY_MENU",
}
for _n in list(range(1, 25)):
    KEY_ALIASES[f"f{_n}"] = f"KEY_F{_n}"

# US-layout chars needing Shift + base key.
_SHIFT_MAP = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
    "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "MINUS", "+": "EQUAL", "{": "LEFTBRACE", "}": "RIGHTBRACE",
    "|": "BACKSLASH", ":": "SEMICOLON", '"': "APOSTROPHE",
    "<": "COMMA", ">": "DOT", "?": "SLASH", "~": "GRAVE",
}
# punctuation char -> KEY_ suffix (evdev names).
_PUNCT_MAP = {
    "-": "MINUS", "=": "EQUAL", "[": "LEFTBRACE", "]": "RIGHTBRACE",
    "\\": "BACKSLASH", ";": "SEMICOLON", "'": "APOSTROPHE",
    "`": "GRAVE", ",": "COMMA", ".": "DOT", "/": "SLASH",
}


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
                  ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL,
                                  ecodes.REL_HWHEEL]}
        self._ui = UInput(events=events, name="ahk-linux-bridge")
        self._ecodes = ecodes
        self.log: list[tuple] = []
        self._await_ready()

    @staticmethod
    def _await_ready():
        """Wait until the compositor has routed the new virtual device.

        A fresh uinput device needs enumeration (udev → libinput → compositor
        keymap/focus setup) before events reach clients. Blind fixed sleeps
        lose the race on Hyprland (verified: 0.2s drops everything, 3s works).
        Strategy: short base sleep for all compositors, then poll Hyprland's
        device list until our keyboard shows up. Override with
        AHK_BRIDGE_UINPUT_WAIT (seconds, float; 0 = no wait).
        """
        import os as _os
        try:
            budget = float(_os.environ.get("AHK_BRIDGE_UINPUT_WAIT", "5.0"))
        except ValueError:
            budget = 5.0
        if budget <= 0:
            return
        # Base settle for all compositors (udev -> libinput thread pickup).
        base = min(1.0, budget)
        time.sleep(base)
        remaining = budget - base
        if remaining <= 0:
            return
        # Hyprland: poll the compositor's device list (fast, exact).
        if _os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            import shutil as _sh
            import subprocess as _sp
            if _sh.which("hyprctl") is None:
                return
            deadline = time.monotonic() + remaining
            while time.monotonic() < deadline:
                try:
                    out = _sp.run(["hyprctl", "devices", "-j"], capture_output=True,
                                  text=True, timeout=2)
                    if out.returncode == 0 and "ahk-linux-bridge" in (out.stdout or ""):
                        return
                except Exception:
                    pass
                time.sleep(0.1)
            return
        # Other Wayland compositors (KWin, Mutter): no queryable device list,
        # and KWin demonstrably needs ~1.5-2.5s (measured live on Plasma 6.7:
        # 0.5s/1.0s probes flaky, >=1.5s reliable when focus is stable).
        if _os.environ.get("WAYLAND_DISPLAY"):
            time.sleep(min(1.5, remaining))

    def _code(self, key: str) -> int:
        ec = self._ecodes
        if len(key) == 1:
            ch = key
            if ch.isalpha():
                name = f"KEY_{ch.upper()}"
                if hasattr(ec, name):
                    return getattr(ec, name)
            if ch.isdigit():
                name = f"KEY_{ch}"
                if hasattr(ec, name):
                    return getattr(ec, name)
            if ch == " ":
                return ec.KEY_SPACE
            suffix = _PUNCT_MAP.get(ch)
            if suffix and hasattr(ec, f"KEY_{suffix}"):
                return getattr(ec, f"KEY_{suffix}")
            base = _SHIFT_MAP.get(ch)
            if base:
                name = f"KEY_{base}" if len(base) > 1 else f"KEY_{base.upper()}"
                if hasattr(ec, name):
                    return getattr(ec, name)
        alias = KEY_ALIASES.get(key.lower(), None)
        if alias and hasattr(ec, alias):
            return getattr(ec, alias)
        up = f"KEY_{key.upper()}"
        if hasattr(ec, up):
            return getattr(ec, up)
        raise ValueError(f"unknown key {key!r}")

    def _tap(self, code: int, hold_s: float = 0.012):
        # NOTE: press and release must be separated by a real hold (~12ms).
        # Back-to-back SYN frames (~50us apart) are coalesced/dropped by
        # libinput before reaching Wayland clients (verified with wev).
        ec = self._ecodes
        self._ui.write(ec.EV_KEY, code, 1)
        self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)
        time.sleep(hold_s)
        self._ui.write(ec.EV_KEY, code, 0)
        self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)

    def _hold(self, code: int, down: bool):
        ec = self._ecodes
        self._ui.write(ec.EV_KEY, code, 1 if down else 0)
        self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)
        time.sleep(0.005)

    def send_key(self, key: str, down: bool | None = None):
        code = self._code(key)
        if down is None:
            self._tap(code)
        else:
            self._hold(code, down)
        self.log.append(("key", key, down))

    def type_text(self, text: str):
        ec = self._ecodes
        shift = ec.KEY_LEFTSHIFT
        for ch in text:
            if ch == " ":
                self._tap(ec.KEY_SPACE)
                continue
            needs_shift = ch.isupper() or ch in _SHIFT_MAP
            base = _SHIFT_MAP.get(ch, ch)
            try:
                code = self._code(base if len(base) > 1 else base)
            except ValueError:
                continue  # skip unmappable chars, keep macro running
            if needs_shift:
                self._hold(shift, True)
                # small delay so the compositor sees Shift before the key
                self._tap(code)
                self._hold(shift, False)
            else:
                # lowercase alpha: _code handles case-insensitively
                self._tap(code)
            time.sleep(0.002)
        self.log.append(("type", text))

    def move_mouse(self, x, y, absolute=True):
        """REL motion (universal). absolute=True is interpreted as a relative
        jump vector from the caller's perspective (same as v0.1 API); the
        compositor applies it as cursor displacement. Chunked to stay within
        the signed 8-bit-ish safe range per event."""
        ec = self._ecodes
        dx, dy = int(x), int(y)
        if not absolute:
            dx, dy = int(x), int(y)
        # Emit in <=127px chunks (some stacks clamp REL payloads).
        while dx != 0 or dy != 0:
            sx = max(-127, min(127, dx))
            sy = max(-127, min(127, dy))
            if sx:
                self._ui.write(ec.EV_REL, ec.REL_X, sx)
            if sy:
                self._ui.write(ec.EV_REL, ec.REL_Y, sy)
            self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)
            dx -= sx
            dy -= sy
            if sx == 0 and sy == 0:
                break
        self.log.append(("move", x, y, absolute))

    def scroll(self, clicks: int, horizontal: bool = False):
        ec = self._ecodes
        axis = ec.REL_HWHEEL if horizontal else ec.REL_WHEEL
        step = 1 if clicks > 0 else -1
        for _ in range(abs(int(clicks))):
            self._ui.write(ec.EV_REL, axis, step)
            self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)
        self.log.append(("scroll", clicks, horizontal))

    def click(self, button="left", count=1, x=None, y=None):
        ec = self._ecodes
        if x is not None and y is not None:
            self.move_mouse(x, y, absolute=True)
        try:
            btn = {"left": ec.BTN_LEFT, "right": ec.BTN_RIGHT,
                   "middle": ec.BTN_MIDDLE}[button]
        except KeyError:
            raise ValueError(f"unknown button {button!r}") from None
        for _ in range(max(1, int(count))):
            self._ui.write(ec.EV_KEY, btn, 1)
            self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)
            time.sleep(0.01)
            self._ui.write(ec.EV_KEY, btn, 0)
            self._ui.write(ec.EV_SYN, ec.SYN_REPORT, 0)
            time.sleep(0.01)
        self.log.append(("click", button, count, x, y))

    def sleep_ms(self, ms: int):
        time.sleep(max(0, ms) / 1000.0)

    def close(self):
        try:
            self._ui.close()
        except Exception:
            pass
