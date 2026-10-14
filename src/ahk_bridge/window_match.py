"""Linux window matching: replaces ahk_exe/ahk_class.

Windows AHK          -> Linux equivalent (this module)
ahk_exe foo.exe      -> process name / cmdline match via /proc
ahk_class Notepad    -> X11 WM_CLASS / Wayland app_id
ahk_title "Doc"      -> _NET_WM_NAME / foreign-toplevel title
"""
from __future__ import annotations
import os


def _proc_name(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def list_processes():
    out = []
    try:
        for pid in filter(str.isdigit, os.listdir("/proc")):
            out.append((int(pid), _proc_name(int(pid))))
    except OSError:
        pass
    return out


def match(spec: str, candidate: dict) -> bool:
    """candidate keys: exe, class, title, app_id. Prefix ahk_ optional."""
    s = spec.strip()
    low = s.lower()
    if low.startswith("ahk_exe"):
        want = s.split(None, 1)[1].strip().lower()
        return want in (candidate.get("exe", "") or "").lower()
    if low.startswith("ahk_class"):
        want = s.split(None, 1)[1].strip().lower()
        c = (candidate.get("class", "") or "").lower()
        return want in c or want in (candidate.get("app_id", "") or "").lower()
    # plain substring over title/exe/class/app_id
    blob = " ".join(str(candidate.get(k, "")) for k in ("title", "exe", "class", "app_id")).lower()
    return s.lower() in blob


def find_window(spec: str, windows: list[dict]):
    return [w for w in windows if match(spec, w)]
