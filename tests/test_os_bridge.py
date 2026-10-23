"""OS integration behavior that does not touch the live desktop in tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime


def run(text):
    rt = Runtime(parse_script(text), DryBackend())
    return rt


def _close_guis(rt):
    for gui in getattr(rt, "_guis", []):
        try:
            gui._destroy()
        except Exception:
            pass


def test_clipboard_read_becomes_a_clipboard_write(monkeypatch):
    import ahk_bridge.clipboard as cb

    writes = []
    monkeypatch.setattr(cb, "read_text", lambda: "from-system")
    monkeypatch.setattr(cb, "write_text", lambda text: writes.append(text) or True)
    rt = run(
        'initial := A_Clipboard\n'
        'A_Clipboard := "new value"\n'
        'after := A_Clipboard\n'
    )
    rt.run_auto()
    assert rt.vars["initial"] == "from-system"
    assert rt.vars["after"] == "new value"
    assert writes == ["new value"]


def test_clipboard_write_failure_is_logged_once(monkeypatch):
    import ahk_bridge.clipboard as cb

    monkeypatch.setattr(cb, "write_text", lambda text: False)
    rt = run(
        'A_Clipboard := "one"\n'
        'A_Clipboard := "two"\n'
    )
    rt.run_auto()
    assert rt.vars["A_Clipboard"] == "two"
    warnings = [e for e in rt.logs if "clipboard:" in e]
    assert len(warnings) == 1


# -- own Gui window/control bridge -----------------------------------------


def test_own_window_position_title_and_existence():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "Window Test")\n'
        'MainGui.Show("x10 y20 w300 h200")\n'
        'MainGui.Add("Button", "x5 y6 w70 h20 vBtn", "Hello")\n'
        'exists := WinExist("ahk_id " MainGui.Hwnd)\n'
        'title := WinGetTitle("A")\n'
        'x := y := w := h := -1\n'
        'ok := WinGetClientPos(&x, &y, &w, &h, "ahk_id " MainGui.Hwnd)\n'
    )
    try:
        rt.run_auto()
        assert rt.vars["exists"] == rt.vars["MainGui"].hwnd
        assert rt.vars["title"] == "Window Test"
        assert rt.vars["ok"] == 1
        assert (rt.vars["w"], rt.vars["h"]) == (300, 200)
        assert (rt.vars["x"], rt.vars["y"]) == (10, 20)
    finally:
        _close_guis(rt)


def test_control_queries_named_and_classnn():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "Controls")\n'
        'MainGui.Show("w300 h200")\n'
        'MainGui.Add("Text", "x4 y5 w80 h16 vLabel", "A label")\n'
        'MainGui.Add("Button", "x5 y25 w70 h20 vBtn", "Press")\n'
        'cx := cy := cw := ch := -1\n'
        'ok := ControlGetPos(&cx, &cy, &cw, &ch, "Btn", "ahk_id " MainGui.Hwnd)\n'
        'text := ControlGetText("Btn", "ahk_id " MainGui.Hwnd)\n'
        'staticText := ControlGetText("Static1", "ahk_id " MainGui.Hwnd)\n'
        'hwnd := ControlGetHwnd("Btn", "ahk_id " MainGui.Hwnd)\n'
    )
    try:
        rt.run_auto()
        btn = rt.vars["MainGui"].get_control("Btn")
        assert rt.vars["ok"] == 1
        assert (rt.vars["cx"], rt.vars["cy"],
                rt.vars["cw"], rt.vars["ch"]) == (5, 25, 70, 20)
        assert rt.vars["text"] == "Press"
        assert rt.vars["staticText"] == "A label"
        assert rt.vars["hwnd"] == btn.hwnd
    finally:
        _close_guis(rt)


def test_wingetpos_function_keeps_empty_output_slots():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "Slots")\n'
        'MainGui.Show("x10 y20 w300 h200")\n'
        'x := y := w := h := -1\n'
        'ok := WinGetPos(&x, &y, , , MainGui)\n'
    )
    try:
        rt.run_auto()
        assert rt.vars["ok"] == 1
        assert rt.vars["x"] != -1 and rt.vars["y"] != -1
        # Omitted positional slots are not shifted into w/h.
        assert rt.vars["w"] == -1 and rt.vars["h"] == -1
    finally:
        _close_guis(rt)


def test_legacy_wingetclientpos_uses_named_output_vars():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "Legacy")\n'
        'MainGui.Show("x10 y20 w300 h200")\n'
        'x := y := w := h := -1\n'
        'WinGetClientPos, x, y, w, h, "A"\n'
    )
    try:
        rt.run_auto()
        assert (rt.vars["x"], rt.vars["y"],
                rt.vars["w"], rt.vars["h"]) == (10, 20, 300, 200)
    finally:
        _close_guis(rt)


def test_win_move_and_opacity_are_real_gui_operations():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "Ops")\n'
        'MainGui.Show("x10 y20 w300 h200")\n'
        'trans := WinSetTransparent(128, "A")\n'
        'moved := WinMove(40, 50, "A")\n'
    )
    try:
        rt.run_auto()
        gui = rt.vars["MainGui"]
        assert rt.vars["trans"] == 1
        assert abs(gui.widget.windowOpacity() - 128 / 255) < 0.01
        assert rt.vars["moved"] == 1
        assert (gui.widget.x(), gui.widget.y()) == (40, 50)
    finally:
        _close_guis(rt)


def test_legacy_transparency_accepts_gui_object():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "LegacyTrans")\n'
        'MainGui.Show("w300 h200")\n'
        'WinSetTransparent 200, MainGui\n'
    )
    try:
        rt.run_auto()
        gui = rt.vars["MainGui"]
        assert abs(gui.widget.windowOpacity() - 200 / 255) < 0.01
    finally:
        _close_guis(rt)


def test_wingetpos_accepts_control_object():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "ControlObject")\n'
        'MainGui.Show("w300 h200")\n'
        'ctrl := MainGui.Add("Button", "x7 y8 w60 h20", "B")\n'
        'x := y := w := h := -1\n'
        'ok := WinGetPos(&x, &y, &w, &h, ctrl)\n'
    )
    try:
        rt.run_auto()
        # WinGetPos on a control handle reports its screen rectangle.
        assert rt.vars["ok"] == 1
        assert rt.vars["w"] == 60 and rt.vars["h"] == 20
        assert rt.vars["x"] >= 7 and rt.vars["y"] >= 8
    finally:
        _close_guis(rt)


def test_win_close_fires_callback_then_destroys():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "Close")\n'
        'MainGui.Show("w300 h200")\n'
        'MainGui.OnEvent("Close", (*) => (closedCallback := 1))\n'
        'closed := WinClose("A")\n'
        'after := WinExist("A")\n'
    )
    try:
        rt.run_auto()
        gui = rt.vars["MainGui"]
        assert rt.vars["closedCallback"] == 1
        assert rt.vars["closed"] == 1
        assert gui.destroyed is True
        assert rt.vars["after"] == 0
    finally:
        _close_guis(rt)


def test_buffer_numput_numget_roundtrip_and_bounds():
    rt = run(
        'b := Buffer(32, 0)\n'
        'NumPut("UInt", 1234, b, 4)\n'
        'a := NumGet(b, 4, "UInt")\n'
        'NumPut("UInt", 7, "UInt", 9, b, 8)\n'
        'c := NumGet(b, 8, "UInt")\n'
        'd := NumGet(b, 12, "UInt")\n'
        'ptr := b.Ptr\n'
        'outOfBounds := NumGet(b, 9999, "UInt")\n'
    )
    rt.run_auto()
    assert rt.vars["a"] == 1234
    assert rt.vars["c"] == 7 and rt.vars["d"] == 9
    assert rt.vars["ptr"] == rt.vars["b"].ptr
    assert rt.vars["outOfBounds"] == 0


def test_strput_strget_and_strptr():
    rt = run(
        'n := StrPut("hello", "UTF-8")\n'
        'buf := Buffer(n)\n'
        'StrPut("hello", buf, n, "UTF-8")\n'
        'roundtrip := StrGet(buf, n, "UTF-8")\n'
        'ptr := StrPtr("world")\n'
        'fromPtr := StrGet(ptr)\n'
    )
    rt.run_auto()
    assert rt.vars["roundtrip"] == "hello"
    assert rt.vars["fromPtr"] == "world"


def test_dllcall_timing_sleep_pid_and_unknown_logging():
    rt = run(
        'ft := 0\n'
        'DllCall("GetSystemTimeAsFileTime", "int64p", &ft := 0)\n'
        'pid := DllCall("GetCurrentProcessId")\n'
        'DllCall("Sleep", "UInt", 5)\n'
        'a := DllCall("totally_missing_api")\n'
        'b := DllCall("totally_missing_api")\n'
    )
    rt.run_auto()
    import os
    assert rt.vars["ft"] > 116444736000000000
    assert rt.vars["pid"] == os.getpid()
    assert ("sleep", 5) in rt.sim.log
    assert rt.vars["a"] == 0 and rt.vars["b"] == 0
    unknown = [line for line in rt.logs if "totally_missing_api" in line]
    assert len(unknown) == 1


def test_dllcall_buffer_structure_write():
    pytest.importorskip("PySide6")
    rt = run(
        'MainGui := Gui("", "Placement")\n'
        'MainGui.Show("x10 y20 w300 h200")\n'
        'wp := Buffer(44)\n'
        'ok := DllCall("GetWindowPlacement", "UInt", MainGui.Hwnd, "Ptr", wp)\n'
        'x := NumGet(wp, 28, "Int")\n'
        'y := NumGet(wp, 32, "Int")\n'
    )
    try:
        rt.run_auto()
        assert rt.vars["ok"] == 1
        assert rt.vars["x"] != 0 or rt.vars["y"] != 0
    finally:
        _close_guis(rt)


def test_missing_external_window_is_logged_and_falsy(monkeypatch):
    import ahk_bridge.window_ops as wo

    monkeypatch.setattr(wo, "find", lambda text: 0)
    rt = run(
        'found := WinExist("No Such Window")\n'
        'title := WinGetTitle("No Such Window")\n'
    )
    rt.run_auto()
    assert rt.vars["found"] == 0
    assert rt.vars["title"] == ""
    assert any("not found" in line for line in rt.logs)
