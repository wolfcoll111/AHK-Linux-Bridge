"""WinActivate fallback logic (xdotool path) with mocked subprocess.

The live X11/XWayland behavior itself (search/focus via xdotool) is proven on
KDE Plasma 6.7 + Hyprland shells; these tests pin the wrapper branching.
"""
import subprocess
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime
from ahk_bridge.backends.dry_backend import DryBackend


class _Done(Exception):
    pass


def _run_with_fake(monkeypatch, search_out, which=True):
    import ahk_bridge.runtime as Rmod

    def fake_which(name):
        return "/usr/bin/xdotool" if (which and name == "xdotool") else None

    def fake_run(cmd, **kw):
        if cmd[:2] == ["xdotool", "search"]:
            return subprocess.CompletedProcess(cmd, 0, search_out, "")
        if cmd[:2] == ["xdotool", "windowactivate"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:1] == ["hyprctl"]:
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
