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

# Criteria recognised in an AHK v2 WinTitle.  Criteria follow the title
# phrase, separated by one space/tab; a criterion value may be quoted when
# it contains spaces (for example a Windows executable under Wine).
_SPEC_RE = re.compile(
    r'(?i)(?:^|\s)ahk_(id|pid|exe|class|group)\s+("(?:[^"]*)"|[^\s"]+)'
)


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


def _as_int(value: str) -> int:
    for base in (0, 10):
        try:
            return int(str(value).strip(), base)
        except (TypeError, ValueError):
            continue
    return 0


def parse_spec(text: str) -> dict:
    """Split a WinTitle into its title phrase and ``ahk_`` criteria.

    The title is everything before the first criterion.  Values are kept
    verbatim apart from one layer of surrounding quotes.  ``ahk_group`` is
    returned as a non-empty string even though this module has no
    ``GroupAdd`` registry: callers must refuse that match rather than
    silently dropping the group and returning an unrelated window.
    """
    text = str(text or "").strip()
    spec = {"title": "", "id": 0, "pid": 0, "exe": "", "class": "",
            "group": ""}
    first = None
    for match in _SPEC_RE.finditer(text):
        if first is None:
            first = match.start()
        key = match.group(1).lower()
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if key in ("id", "pid"):
            spec[key] = _as_int(value)
        else:
            spec[key] = value
    if first is None:
        spec["title"] = text.strip().strip('"').strip()
    else:
        spec["title"] = text[:first].strip().strip('"').strip()
    return spec


def _iter_pids() -> list[int]:
    try:
        return [int(pid) for pid in os.listdir("/proc") if pid.isdigit()]
    except OSError:
        return []


def _process_identity(pid: int) -> dict:
    """Collect the names and paths belonging to ``/proc/<pid>``.

    Native processes expose the executable through ``/proc/pid/exe``.
    Wine's ``comm`` is truncated to 15 characters and its ``exe`` link is
    the Wine loader, so the Windows executable is read from the command
    line as well.  A vanished process simply contributes no names.
    """
    names: list[str] = []
    paths: list[str] = []
    try:
        with open(f"/proc/{int(pid)}/comm", encoding="utf-8",
                  errors="replace") as handle:
            comm = handle.read().strip()
        if comm:
            names.append(comm)
    except OSError:
        pass
    try:
        exe = os.readlink(f"/proc/{int(pid)}/exe")
        if exe:
            paths.append(exe)
            names.append(os.path.basename(exe))
    except OSError:
        pass
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as handle:
            tokens = handle.read().split(b"\0")
    except OSError:
        tokens = []
    for token in tokens:
        if not token:
            continue
        text = token.decode("utf-8", "replace")
        # Wine passes C:\Games\RobloxPlayerBeta.exe as an argument, so split
        # on both separators before taking the basename.
        names.append(re.split(r"[\\/]", text)[-1])
        paths.append(text)
    return {"names": [name for name in names if name],
            "paths": [path for path in paths if path]}


def _exe_matches(want: str, identity: dict) -> bool:
    """Case-insensitive AHK ahk_exe match: file name or full path.

    AHK matches the process name (e.g. ``notepad.exe``) or an exact path,
    never an arbitrary substring.  A path containing a separator is
    compared as a whole; a bare name is compared with each candidate
    basename so a truncated Wine ``comm`` does not hide the real exe.
    """
    wanted = str(want or "").strip().lower().replace("\\", "/")
    if not wanted:
        return False
    if "/" in wanted:
        return any(str(path).lower().replace("\\", "/") == wanted
                   for path in identity.get("paths", ()))
    return any(str(name).lower() == wanted
               for name in identity.get("names", ()))


def _pids_for_exe(want: str) -> list[int]:
    return [pid for pid in _iter_pids()
            if _exe_matches(want, _process_identity(pid))]


def _search_ids(flag: str, value: str) -> list[int]:
    tool = _xdotool()
    if not tool:
        return []
    proc = _run([tool, "search", "--onlyvisible", flag, value])
    if proc is None or proc.returncode != 0:
        return []
    return [int(token) for token in (proc.stdout or "").split()
            if token.isdigit()]


def _candidate_ids(spec: dict) -> list[int]:
    """Narrow the X11 window list with the cheapest available criterion."""
    if spec["pid"]:
        return _search_ids("--pid", str(spec["pid"]))
    if spec["class"]:
        return _search_ids("--class", re.escape(spec["class"]))
    if spec["exe"]:
        found: list[int] = []
        for pid in _pids_for_exe(spec["exe"]):
            for wid in _search_ids("--pid", str(pid)):
                if wid not in found:
                    found.append(wid)
        return found
    if spec["title"]:
        return _search_ids("--name", re.escape(spec["title"]))
    return []


def _window_matches(wid: int, spec: dict) -> bool:
    if spec["group"]:
        # No GroupAdd registry on Linux yet; refusing is truthful.
        return False
    if spec["id"] and int(wid) != int(spec["id"]):
        return False
    if spec["title"] and spec["title"].lower() not in title(wid).lower():
        return False
    if spec["class"] and spec["class"].lower() not in class_name(wid).lower():
        return False
    window_pid = pid(wid) if (spec["pid"] or spec["exe"]) else 0
    if spec["pid"] and window_pid != int(spec["pid"]):
        return False
    if spec["exe"] and not _exe_matches(spec["exe"],
                                        _process_identity(window_pid)):
        return False
    return True


def find(text: str) -> int:
    """Find an X11/XWayland window.  Returns a window id or 0.

    The title phrase and every supplied ``ahk_`` criterion must match; an
    unsupported or unsatisfied criterion returns 0 instead of an
    arbitrary window.
    """
    spec = parse_spec(text)
    if spec["group"]:
        return 0
    candidates = [spec["id"]] if spec["id"] else _candidate_ids(spec)
    for wid in candidates:
        if wid and _window_matches(wid, spec) and geometry(wid):
            return int(wid)
    return 0


def find_all(text: str) -> list[int]:
    spec = parse_spec(text)
    if spec["group"]:
        return []
    candidates = [spec["id"]] if spec["id"] else _candidate_ids(spec)
    return [int(wid) for wid in candidates
            if wid and _window_matches(wid, spec) and geometry(wid)]


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


def class_name(wid: int) -> str:
    tool = _xdotool()
    if not tool or not wid:
        return ""
    proc = _run([tool, "getwindowclassname", str(int(wid))])
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
    """Best available executable name for the window's process.

    Prefer the full name from the command line (Wine reports the Windows
    exe there), then ``/proc/pid/exe``, then ``comm``.  Never invents a
    name when the process no longer exists.
    """
    window_pid = pid(wid)
    if not window_pid:
        return ""
    identity = _process_identity(window_pid)
    for name in identity["names"]:
        if name.lower().endswith(".exe"):
            return name
    if identity["names"]:
        return identity["names"][0]
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


def activate(wid: int) -> bool:
    tool = _xdotool()
    if not tool or not wid:
        return False
    proc = _run([tool, "windowactivate", str(int(wid))])
    return proc is not None and proc.returncode == 0


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
    proc = _run([tool, "windowmove", str(int(wid)), str(int(x)),
                 str(int(y))])
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
