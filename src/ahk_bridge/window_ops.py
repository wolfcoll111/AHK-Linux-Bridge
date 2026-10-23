"""X11/XWayland window helpers for the OS bridge.

Wayland deliberately gives clients no global window list or foreign window
handles.  This module therefore supports the X11/XWayland windows that KDE,
Wine and many games expose through ``xdotool``/``xprop``.  A native Wayland
surface (for example a game using the Wayland backend) has no equivalent of
an HWND; callers must report that as an exact limitation instead of inventing
a handle.  All functions return ``None``/``0`` on failure and never raise.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

_TIMEOUT = 2.0


def _run(argv, timeout=_TIMEOUT, text=True):
    try:
        return subprocess.run(argv, capture_output=True, text=text,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _xdotool() -> str | None:
    if not os.environ.get("DISPLAY"):
        return None
    return shutil.which("xdotool")


def _window_title_query(text: str) -> str:
    """Extract the title portion from an AHK WinTitle expression."""
    # `Roblox ahk_exe RobloxPlayerBeta.exe` -> `Roblox`.
    phrase = re.split(r"\s+ahk_(?:exe|class|pid|group)\b", text,
                      flags=re.IGNORECASE)[0].strip()
    return phrase.strip().strip('"')


def find(text: str) -> int:
    """Find an X11/XWayland window.  Returns a window id or 0."""
    text = str(text or "").strip()
    tool = _xdotool()
    if not tool:
        return 0
    m = re.match(r"(?i)^ahk_id\s+(\d+)$", text)
    if m:
        wid = int(m.group(1))
        if get_geometry(wid):
            return wid
        return 0
    title = _window_title_query(text)
    if not title:
        # An `ahk_exe`-only spec needs process enumeration, which is not
        # equivalent to matching every visible X window.  Refuse rather than
        # returning an arbitrary window.
        return 0
    argv = [tool, "search", "--onlyvisible", "--name", re.escape(title)]
    proc = _run(argv)
    if proc is None or proc.returncode != 0:
        return 0
    for token in (proc.stdout or "").split():
        if token.isdigit():
            return int(token)
    return 0


def find_all(text: str) -> list[int]:
    text = str(text or "").strip()
    tool = _xdotool()
    if not tool:
        return []
    title = _window_title_query(text)
    if not title:
        return []
    argv = [tool, "search", "--onlyvisible", "--name", re.escape(title)]
    proc = _run(argv)
    if proc is None or proc.returncode != 0:
        return []
    return [int(t) for t in (proc.stdout or "").split() if t.isdigit()]


def geometry(wid: int, client: bool = False):
    """Return ``(x, y, w, h)`` for an X11 window, or None."""
    if not wid:
        return None
    tool = _xdotool()
    if tool:
        proc = _run([tool, "getwindowgeometry", "--shell", str(int(wid))])
        if proc is not None and proc.returncode == 0:
            values = {}
            for line in (proc.stdout or "").splitlines():
                if "=" in line:
                    key, val = line.split("=", 1)
                    values[key.strip()] = val.strip()
            try:
                x = int(values.get("X", 0))
                y = int(values.get("Y", 0))
                w = int(values.get("WIDTH", 0))
                h = int(values.get("HEIGHT", 0))
                if client:
                    # xwininfo reports the client/outer geometry; X11 does
                    # not expose a separate client origin for an arbitrary
                    # foreign window.  Prefer its absolute fields when
                    # present, otherwise keep xdotool's answer.
                    info = _run(["xwininfo", "-id", str(int(wid))])
                    if info is not None and info.returncode == 0:
                        out = info.stdout or ""
                        ax = re.search(r"Absolute upper-left X:\s*(-?\d+)", out)
                        ay = re.search(r"Absolute upper-left Y:\s*(-?\d+)", out)
                        cw = re.search(r"Width:\s*(\d+)", out)
                        ch = re.search(r"Height:\s*(\d+)", out)
                        if ax:
                            x = int(ax.group(1))
                        if ay:
                            y = int(ay.group(1))
                        if cw:
                            w = int(cw.group(1))
                        if ch:
                            h = int(ch.group(1))
                return (x, y, w, h)
            except (TypeError, ValueError):
                return None
    return None


def title(wid: int) -> str:
    tool = _xdotool()
    if not tool or not wid:
        return ""
    proc = _run([tool, "getwindowname", str(int(wid))])
    return (proc.stdout or "").strip() if proc is not None and proc.returncode == 0 else ""


def pid(wid: int) -> int:
    tool = _xdotool()
    if not tool or not wid:
        return 0
    proc = _run([tool, "getwindowpid", str(int(wid))])
    try:
        return int((proc.stdout or "").strip()) if proc is not None and proc.returncode == 0 else 0
    except ValueError:
        return 0


def process_name(wid: int) -> str:
    win_pid = pid(wid)
    if not win_pid:
        return ""
    try:
        with open(f"/proc/{win_pid}/comm", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def active() -> int:
    tool = _xdotool()
    if not tool:
        return 0
    proc = _run([tool, "getactivewindow"])
    try:
        return int((proc.stdout or "").strip()) if proc is not None and proc.returncode == 0 else 0
    except ValueError:
        return 0


def close(wid: int, kill: bool = False) -> bool:
    tool = _xdotool()
    if not tool or not wid:
        return False
    proc = _run([tool, "windowkill" if kill else "windowclose", str(int(wid))])
    return proc is not None and proc.returncode == 0


def move(wid: int, x: int, y: int) -> bool:
    tool = _xdotool()
    if not tool or not wid:
        return False
    proc = _run([tool, "windowmove", str(int(wid)), str(int(x)), str(int(y))])
    return proc is not None and proc.returncode == 0


def set_opacity(wid: int, alpha: int) -> bool:
    """Set EWMH opacity on an X11/XWayland window (0..255)."""
    tool = shutil.which("xprop")
    if not tool or not wid:
        return False
    value = max(0, min(255, int(alpha)))
    argb = (value * 0x01010101) & 0xFFFFFFFF
    proc = _run([tool, "-id", str(int(wid)),
                 "-f", "_NET_WM_WINDOW_OPACITY", "32c",
                 "-set", "_NET_WM_WINDOW_OPACITY", str(argb)])
    return proc is not None and proc.returncode == 0
