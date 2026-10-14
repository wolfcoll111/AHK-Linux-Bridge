"""Global hotkeys via XDG Desktop Portal GlobalShortcuts (Wayland-safe).

D-Bus interface: org.freedesktop.portal.GlobalShortcuts
  CreateSession -> BindShortcuts -> Activated/Deactivated signals.
Requires: dbus-next, compositor backend (GNOME 48+, Plasma 6+, Hyprland),
and a .desktop app-id. Falls back to X11 XGrabKey / evdev-grab; see README.
"""
from __future__ import annotations


class GlobalShortcutPortal:
    IFACE = "org.freedesktop.portal.GlobalShortcuts"

    def __init__(self, app_id: str = "io.github.ahk-linux-bridge"):
        self.app_id = app_id

    async def register(self, shortcuts: list[dict], loop=None):
        """Register shortcuts; returns bound list. Needs a running portal."""
        try:
            from dbus_next.aio import MessageBus
        except ImportError as e:
            raise RuntimeError("dbus-next not installed: pip install 'ahk-linux-bridge[portal]'") from e
        bus = await MessageBus().connect()
        introspection = await bus.introspect("org.freedesktop.portal.Desktop",
                                             "/org/freedesktop/portal/desktop")
        obj = bus.get_proxy_object("org.freedesktop.portal.Desktop",
                                   "/org/freedesktop/portal/desktop", introspection)
        iface = obj.get_interface(self.IFACE)
        token = "ahkbridge_session"
        session = await iface.call_create_session({"session_handle_token": token})
        await iface.call_bind_shortcuts(session, shortcuts, self.app_id, {})
        return session
