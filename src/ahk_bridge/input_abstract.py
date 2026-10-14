"""Unified input abstraction: one API, backend routed by display server."""
from __future__ import annotations
import os
import shutil


def detect_backend(prefer: str | None = None) -> str:
    """Return 'x11' | 'uinput' | 'dry'. Never raises."""
    if prefer in ("x11", "uinput", "dry"):
        return prefer
    if os.environ.get("AHK_BRIDGE_BACKEND") in ("x11", "uinput", "dry"):
        return os.environ["AHK_BRIDGE_BACKEND"]
    session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if session == "x11" or (os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")):
        return "x11"
    if os.access("/dev/uinput", os.W_OK):
        return "uinput"
    # Wayland without uinput permission -> caller must fix perms; dry keeps --check working
    return "dry"


class InputSimulator:
    """Single internal API used by Runtime. Routes to backend automatically."""

    def __init__(self, backend: str | None = None):
        name = detect_backend(backend)
        if name == "x11":
            from .backends.xtest_backend import XTestBackend
            self._b = XTestBackend()
        elif name == "uinput":
            from .backends.uinput_backend import UInputBackend
            self._b = UInputBackend()
        else:
            from .backends.dry_backend import DryBackend
            self._b = DryBackend()
        self.backend_name = self._b.name

    # -- unified API --
    def send_key(self, key: str, down: bool | None = None):
        """key: AHK-ish name ('a', 'F1', 'Escape', ...). down=None -> tap."""
        return self._b.send_key(key, down)

    def type_text(self, text: str):
        return self._b.type_text(text)

    def move_mouse(self, x: int, y: int, absolute: bool = True):
        return self._b.move_mouse(x, y, absolute)

    def click(self, button: str = "left", count: int = 1, x: int | None = None, y: int | None = None):
        return self._b.click(button, count, x, y)

    def sleep_ms(self, ms: int):
        return self._b.sleep_ms(ms)

    @property
    def log(self):
        return getattr(self._b, "log", None)

    def close(self):
        try:
            self._b.close()
        except Exception:
            pass

    @staticmethod
    def check_permissions() -> dict:
        uinput_ok = os.access("/dev/uinput", os.W_OK)
        return {
            "uinput_writable": uinput_ok,
            "display": os.environ.get("DISPLAY", ""),
            "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
            "session_type": os.environ.get("XDG_SESSION_TYPE", ""),
            "has_evdev": shutil.which("python3") is not None and _has_mod("evdev"),
            "has_xlib": _has_mod("Xlib"),
            "has_dbus_next": _has_mod("dbus_next"),
            "detected_backend": detect_backend(),
        }


def _has_mod(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False
