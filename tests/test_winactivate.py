"""WinActivate fallback logic (xdotool path) with mocked subprocess.

The live X11/XWayland behavior itself (search/focus via xdotool) is proven on
KDE Plasma 6.7 + Hyprland shells; these tests pin the wrapper branching.
"""
import os
import subprocess
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime
from ahk_bridge.backends.dry_backend import DryBackend


class _Done(Exception):
    pass


def _run_with_fake(monkeypatch, search_out, which=True):
    monkeypatch.setenv("DISPLAY", ":0")

    def fake_which(name):
        return "/usr/bin/xdotool" if (which and name == "xdotool") else None

    def fake_run(cmd, **kw):
        tool = os.path.basename(str(cmd[0]))
        action = cmd[1] if len(cmd) > 1 else ""
        if tool == "xdotool" and action == "search":
            return subprocess.CompletedProcess(cmd, 0, search_out, "")
        if tool == "xdotool" and action == "getwindowgeometry":
            return subprocess.CompletedProcess(
                cmd, 0, "X=10\nY=20\nWIDTH=800\nHEIGHT=600\n", "")
        if tool == "xdotool" and action == "getwindowname":
            return subprocess.CompletedProcess(cmd, 0, "AutoHotkey Dash\n", "")
        if tool == "xdotool" and action == "getwindowclassname":
            return subprocess.CompletedProcess(cmd, 0, "AutoHotkeyGUI\n", "")
        if tool == "xdotool" and action == "getwindowpid":
            return subprocess.CompletedProcess(cmd, 0, str(os.getpid()), "")
        if tool == "xdotool" and action == "windowactivate":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if tool == "hyprctl":
            return subprocess.CompletedProcess(cmd, 1, "", "no hyprland")
        raise AssertionError(f"unexpected: {cmd}")

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("subprocess.run", fake_run)
    sc = parse_script('WinActivate "AutoHotkey Dash"\n')
    sim = DryBackend()
    rt = Runtime(sc, sim)
    rt.run_auto()
    return rt


def test_winactivate_xdotool_hit(monkeypatch):
    rt = _run_with_fake(monkeypatch, "46137347\n")
    assert any("46137347" in line for line in rt.logs), rt.logs


def test_winactivate_xdotool_miss_logs_fallback(monkeypatch):
    rt = _run_with_fake(monkeypatch, "")
    assert any("best-effort" in line for line in rt.logs), rt.logs


def test_winactivate_no_tools_logs_fallback(monkeypatch):
    rt = _run_with_fake(monkeypatch, "", which=False)
    assert any("best-effort" in line for line in rt.logs), rt.logs
