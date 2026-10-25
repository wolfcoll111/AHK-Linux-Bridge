"""X11/XWayland WinTitle criteria (title + ahk_exe/class/pid) with fakes.

No live X server is contacted: ``_run`` is replaced with a tiny in-memory
window table.  These tests pin that every supplied criterion is ANDed and
that an unsupported criterion (ahk_group) is refused instead of ignored.
"""
import os
import re
import subprocess

import pytest

from ahk_bridge import window_ops as wo
from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime

WINDOWS = {
    100: {"title": "Roblox", "class": "roblox", "pid": 4242},
    200: {"title": "Roblox Studio", "class": "roblox", "pid": 999},
    300: {"title": "Terminal", "class": "kitty", "pid": 5151},
    400: {"title": "Roblox Helper", "class": "robloxhelper", "pid": 999},
}

IDENTITIES = {
    4242: {"names": ["RobloxPlayerBet", "RobloxPlayerBeta.exe"],
           "paths": ["C:\\Games\\RobloxPlayerBeta.exe"]},
    999: {"names": ["other"], "paths": ["/usr/bin/other"]},
    5151: {"names": ["kitty"], "paths": ["/usr/bin/kitty"]},
}


@pytest.fixture
def fake_x11(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(
        wo.shutil, "which",
        lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        tool = argv[1] if len(argv) > 1 else ""
        if "xdotool" in str(argv[0]) and tool == "search":
            rest = argv[2:]
            flag = value = None
            for index, token in enumerate(rest):
                if token in ("--pid", "--class", "--name"):
                    flag = token
                    value = rest[index + 1] if index + 1 < len(rest) else ""
                    break
            hits = []
            for wid, info in WINDOWS.items():
                if flag == "--pid" and str(info["pid"]) == value:
                    hits.append(wid)
                elif flag == "--class" and re.search(value, info["class"],
                                                     re.IGNORECASE):
                    hits.append(wid)
                elif flag == "--name" and re.search(value, info["title"],
                                                    re.IGNORECASE):
                    hits.append(wid)
            out = "".join(f"{wid}\n" for wid in hits)
            return subprocess.CompletedProcess(argv, 0 if hits else 1, out, "")
        if tool == "getwindowgeometry":
            return subprocess.CompletedProcess(
                argv, 0, "X=10\nY=20\nWIDTH=800\nHEIGHT=600\n", "")
        action = argv[1] if len(argv) > 1 else ""
        wid = int(argv[-1]) if argv and argv[-1].isdigit() else 0
        info = WINDOWS.get(wid, {})
        if action == "getwindowname":
            return subprocess.CompletedProcess(argv, 0, info.get("title", ""), "")
        if action == "getwindowclassname":
            return subprocess.CompletedProcess(argv, 0, info.get("class", ""), "")
        if action == "getwindowpid":
            return subprocess.CompletedProcess(argv, 0, str(info.get("pid", "")), "")
        if action == "windowactivate":
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"unexpected xdotool call: {argv}")

    monkeypatch.setattr(wo, "_run", fake_run)
    return calls


@pytest.fixture
def fake_proc(monkeypatch):
    monkeypatch.setattr(wo, "_iter_pids", lambda: sorted(IDENTITIES))
    monkeypatch.setattr(
        wo, "_process_identity",
        lambda pid: IDENTITIES.get(int(pid), {"names": [], "paths": []}))
    return IDENTITIES


def _run(code: str):
    rt = Runtime(parse_script(code), DryBackend())
    rt.run_auto()
    return rt


def test_parse_spec_title_and_exe():
    spec = wo.parse_spec("Roblox ahk_exe RobloxPlayerBeta.exe")
    assert spec == {"title": "Roblox", "id": 0, "pid": 0,
                    "exe": "RobloxPlayerBeta.exe", "class": "", "group": ""}


def test_parse_spec_quoted_path_and_bare_criteria():
    spec = wo.parse_spec(
        'ahk_exe "C:\\Program Files\\Game\\game.exe" ahk_class GameClass')
    assert spec["title"] == ""
    assert spec["exe"] == r"C:\Program Files\Game\game.exe"
    assert spec["class"] == "GameClass"


def test_parse_spec_numbers_and_quoted_title():
    spec = wo.parse_spec('"Roblox" ahk_pid 0x1092 ahk_id 12345')
    assert spec["title"] == "Roblox"
    assert spec["pid"] == 0x1092
    assert spec["id"] == 12345


def test_exe_match_requires_full_name_not_substring():
    identity = IDENTITIES[4242]
    assert wo._exe_matches("RobloxPlayerBeta.exe", identity)
    assert wo._exe_matches("robloxplayerbeta.EXE", identity)
    assert wo._exe_matches(r"C:\Games\RobloxPlayerBeta.exe", identity)
    assert not wo._exe_matches("Roblox", identity)
    assert not wo._exe_matches(r"D:\Games\RobloxPlayerBeta.exe", identity)


def test_find_title_and_exe_are_anded(fake_x11, fake_proc):
    # The exact spec used by Natro's GetRobloxClientPos()/Heartbeat.
    assert wo.find("Roblox ahk_exe RobloxPlayerBeta.exe") == 100


def test_find_exe_only_uses_process_pid(fake_x11, fake_proc):
    assert wo.find("ahk_exe RobloxPlayerBeta.exe") == 100
    assert any(os.path.basename(call[0]) == "xdotool"
               and call[1:4] == ["search", "--onlyvisible", "--pid"]
               for call in fake_x11)


def test_find_class_and_title_are_anded(fake_x11, fake_proc):
    assert wo.find("Roblox ahk_class roblox") == 100
    assert wo.find("Missing ahk_class roblox") == 0


def test_ahk_class_is_exact_not_a_substring(fake_x11, fake_proc):
    # `ahk_class AutoHotkey` must not match `AutoHotkeyGUI` (AHK semantics).
    assert wo.find_all("ahk_class roblox") == [100, 200]
    assert wo.find("ahk_class robloxhelper") == 400


def test_find_pid_searches_by_pid(fake_x11, fake_proc):
    assert wo.find("ahk_pid 4242") == 100
    assert wo.find("ahk_pid 31337") == 0


def test_find_ahk_id_still_filters_extra_criteria(fake_x11, fake_proc):
    assert wo.find("Terminal ahk_id 300") == 300
    assert wo.find("Roblox ahk_id 300") == 0


def test_find_ahk_group_is_refused_not_ignored(fake_x11, fake_proc):
    assert wo.find("ahk_group GameWindows") == 0
    assert fake_x11 == []


def test_find_missing_exe_is_zero_and_never_invents_a_window(fake_x11,
                                                             fake_proc):
    assert wo.find("ahk_exe NotRunning.exe") == 0


def test_find_all_returns_every_matching_window(fake_x11, fake_proc):
    assert wo.find_all("ahk_class roblox") == [100, 200]
    assert wo.find_all("ahk_exe RobloxPlayerBeta.exe") == [100]


def test_process_name_prefers_full_exe_name(fake_x11, fake_proc):
    assert wo.process_name(100) == "RobloxPlayerBeta.exe"
    assert wo.process_name(300) == "kitty"


def test_winexist_resolves_exe_only_spec_through_the_bridge(monkeypatch):
    seen = []

    def fake_find(text):
        seen.append(text)
        return 12345

    import ahk_bridge.window_ops as ops
    monkeypatch.setattr(ops, "find", fake_find)
    monkeypatch.setattr(ops, "title", lambda wid: "Roblox")
    rt = _run('found := WinExist("ahk_exe RobloxPlayerBeta.exe")\n')
    assert rt.vars["found"] == 12345
    # Before v0.9 the runtime skipped window_ops entirely for an
    # ahk_exe-only spec because it had no title phrase.
    assert seen == ["ahk_exe RobloxPlayerBeta.exe"]


def test_wingettitle_uses_exe_only_target(fake_x11, fake_proc):
    rt = _run('name := WinGetTitle("ahk_exe RobloxPlayerBeta.exe")\n')
    assert rt.vars["name"] == "Roblox"


def test_wingetcount_counts_external_exe_matches(fake_x11, fake_proc):
    rt = _run('count := WinGetCount("ahk_class roblox")\n')
    assert rt.vars["count"] == 2


def test_winactivate_uses_resolved_window(monkeypatch):
    import ahk_bridge.window_ops as ops
    monkeypatch.setattr(ops, "find", lambda text: 100)
    monkeypatch.setattr(ops, "title", lambda wid: "Roblox")
    activated = []
    monkeypatch.setattr(ops, "activate", lambda wid: activated.append(wid) or True)
    rt = _run('WinActivate "Roblox ahk_exe RobloxPlayerBeta.exe"\n')
    assert activated == [100]
    assert any("X window 100" in line for line in rt.logs)


def test_winactivate_statement_evaluates_concatenated_ahk_id(monkeypatch):
    """Natro uses `WinActivate "ahk_id " hwnd` as a statement."""
    import ahk_bridge.window_ops as ops
    monkeypatch.setattr(ops, "find", lambda text: 0)
    monkeypatch.setattr(ops, "geometry",
                        lambda wid, client=False: (10, 20, 800, 600))
    monkeypatch.setattr(ops, "title", lambda wid: "Roblox")
    activated = []
    monkeypatch.setattr(ops, "activate",
                        lambda wid: activated.append(wid) or True)
    rt = _run('hwnd := 12345\nWinActivate "ahk_id " hwnd\n')
    assert activated == [12345], rt.logs
    assert any("X window 12345" in line for line in rt.logs)


def test_wingetlist_includes_external_matches(monkeypatch):
    import ahk_bridge.window_ops as ops
    monkeypatch.setattr(ops, "find_all", lambda text: [100, 200])
    monkeypatch.setattr(ops, "title",
                        lambda wid: {100: "Roblox", 200: "Studio"}[wid])
    rt = _run('list := WinGetList("ahk_class roblox")\n')
    assert rt.vars["list"] == [100, 200]


def test_wingetlist_enumerates_own_guis_and_excludes_title(monkeypatch):
    pytest.importorskip("PySide6")
    import ahk_bridge.window_ops as ops
    monkeypatch.setattr(ops, "find_all", lambda text: [])
    monkeypatch.setattr(ops, "list_windows", lambda: [])
    rt = _run(
        'g1 := Gui("", "Alpha")\n'
        'g2 := Gui("", "Beta")\n'
        'g1.Show()\n'
        'g2.Show()\n'
        'all := WinGetList("ahk_class AutoHotkeyGUI")\n'
        'filtered := WinGetList("", "", "Beta")\n'
        'count := WinGetCount("ahk_class AutoHotkeyGUI")\n'
    )
    try:
        g1, g2 = rt.vars["g1"], rt.vars["g2"]
        assert g1.hwnd in rt.vars["all"]
        assert g2.hwnd in rt.vars["all"]
        assert g1.hwnd in rt.vars["filtered"]
        assert g2.hwnd not in rt.vars["filtered"]
        assert rt.vars["count"] == 2
    finally:
        for gui in list(rt._guis):
            gui._destroy()


def test_wingetlist_refuses_wintext_instead_of_ignoring_it(monkeypatch):
    rt = _run('list := WinGetList("ahk_class roblox", "Some control text")\n')
    assert rt.vars["list"] == []
    assert any("WinText" in line for line in rt.logs)


def test_wingetlist_refuses_ahk_group(monkeypatch):
    rt = _run('list := WinGetList("ahk_group GameWindows")\n')
    assert rt.vars["list"] == []
    assert any("ahk_group" in line for line in rt.logs)


def test_wingetcount_without_title_lists_own_and_external(monkeypatch):
    pytest.importorskip("PySide6")
    import ahk_bridge.window_ops as ops
    monkeypatch.setattr(ops, "list_windows", lambda: [700])
    rt = _run(
        'MainGui := Gui("", "Counted")\n'
        'MainGui.Show()\n'
        'count := WinGetCount()\n'
    )
    try:
        assert rt.vars["count"] == 2
    finally:
        for gui in list(rt._guis):
            gui._destroy()
