"""PySide6 GUI compatibility tests (headless/offscreen only).

These tests exercise the AHK-facing state and event surface; they never touch
the live desktop.  QT_QPA_PLATFORM is set before PySide6 can be imported.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from ahk_bridge.backends.dry_backend import DryBackend  # noqa: E402
from ahk_bridge.parser import parse_script  # noqa: E402
from ahk_bridge.runtime import Runtime  # noqa: E402


def run(text):
    rt = Runtime(parse_script(text), DryBackend())
    rt.run_auto()
    return rt


def close_guis(rt):
    for gui in list(getattr(rt, "_guis", [])):
        try:
            gui._destroy()
        except Exception:
            pass


def test_gui_construct_add_show_submit():
    rt = run(
        'MainGui := Gui("+AlwaysOnTop", "Native title")\n'
        'MainGui.Show("x0 y0 w490 h275")\n'
        'MainGui.SetFont("s8 cDefault Norm", "Tahoma")\n'
        'MainGui.Add("Text", "x5 y241 w80 -Wrap +BackgroundTrans", "Current Field:")\n'
        'MainGui.Add("Button", "x82 y240 w80 h20 Disabled vStartButton", "Start")\n'
        'MainGui.Add("CheckBox", "x65 y83 w50 vCheck1 Checked", "Drift")\n'
        'MainGui.Add("Edit", "x18 y57 w106 vEdit1", "hello")\n'
        'MainGui.Add("UpDown", "x18 y80 w60 vUp1 Range1-9", 4)\n'
        'values := MainGui.Submit()\n'
        'out := values.Edit1 "|" values.Check1 "|" values.Up1\n'
    )
    try:
        gui = rt.vars["MainGui"]
        assert gui.visible is True
        assert rt.vars["out"] == "hello|1|4"
        assert rt.has_pending_events() is True
        assert gui.get_control("StartButton").get_text() == "Start"
        assert gui.get_control("StartButton").ahk_get("Enabled") == 0
        assert gui.get_control("Check1").ahk_get("Value") == 1
        assert gui.get_control("Edit1").ahk_get("Value") == "hello"
        assert gui.get_control("Up1").ahk_get("Value") == 4
        assert len(gui.controls) == 5
        # Controls added before a Tab belong to the main window, not to
        # themselves as hidden top-level windows.
        assert gui.get_control("StartButton").widget.parent() is gui.widget
    finally:
        close_guis(rt)


def test_gui_named_and_arrow_events():
    rt = run(
        'MainGui := Gui("", "Events")\n'
        'btn := MainGui.Add("Button", "x5 y5 w80 h20 vB", "B")\n'
        'btn.OnEvent("Click", OnClick)\n'
        'MainGui.Add("CheckBox", "x5 y30 vC", "C").OnEvent("Change", (*) => (arrow := 1))\n'
        'OnClick(GuiCtrl, *) {\n'
        '    global named, last_type\n'
        '    named := 1\n'
        '    last_type := GuiCtrl.Type\n'
        '}\n'
    )
    try:
        btn = rt.vars["MainGui"].get_control("B")
        btn._fire("Click")
        assert rt.vars["named"] == 1
        assert rt.vars["last_type"] == "Button"
        rt.vars["MainGui"].get_control("C")._fire("Change")
        assert rt.vars["arrow"] == 1
        assert not any("callback error" in e for e in rt.logs)
    finally:
        close_guis(rt)


def test_gui_chains_sections_indexing_and_dynamic_names():
    rt = run(
        'MainGui := Gui("", "Chains")\n'
        'TabArr := ["Gather", "Settings"]\n'
        '(TabCtrl := MainGui.Add("Tab", "x0 y-1 w500 h240 -Wrap", TabArr)).OnEvent("Change", (*) => TabCtrl.Focus())\n'
        'TabCtrl.UseTab("Gather")\n'
        'MainGui.Add("Text", "x5 y10 w80", "Before")\n'
        '(GuiCtrl := MainGui.Add("Text", "x5 y30 w80 vSect", "Sect")).Section := "Gather"\n'
        'MainGui.Add("Text", "x5 y50 w80 vChain", "Chain").Text := "Changed"\n'
        'MainGui["Sect"].Move(, , 123)\n'
        'MainGui["Sect"].GetPos(&gx, &gy, &gw, &gh)\n'
        'GuiCtrl := MainGui.Add("CheckBox", "x5 y70 vDyn1", "D")\n'
        '%GuiCtrl.Name% := "via-dynamic"\n'
        'MainGui[k := StrReplace(GuiCtrl.Name, "Dyn", "Dyn")].Text := "renamed"\n'
        'MainGui["Dyn1"].Value := 1\n'
        'renamed := MainGui["Sect"].Text\n'
    )
    try:
        gui = rt.vars["MainGui"]
        assert rt.vars.get("via-dynamic") == "via-dynamic" or rt.vars.get("Dyn1") == "via-dynamic"
        dyn = gui.get_control("Dyn1")
        assert dyn.get_text() == "renamed"
        assert dyn.get_value() == 1
        assert rt.vars["renamed"] == "Sect"
        assert gui.get_control("Chain").get_text() == "Changed"
        assert rt.vars["gw"] == 123
        assert rt.vars["gx"] == 5
        assert gui.get_control("Sect").ahk_get("Section") == "Gather"
        # The callback is attached even though it was glued to Add(...).
        rt.vars["TabCtrl"]._fire("Change")
        assert not any("unsupported callback" in e for e in rt.logs)
    finally:
        close_guis(rt)


def test_gui_dropdownlist_add_text_value_and_change():
    rt = run(
        'MainGui := Gui("", "DDL")\n'
        'fields := ["Bamboo", "Cactus"]\n'
        'ddl := MainGui.Add("DropDownList", "x5 y5 w106 vField", ["None"])\n'
        'ddl.Add(fields)\n'
        'ddl.Text := "Bamboo"\n'
        'ddl.OnEvent("Change", OnChange)\n'
        'sel := MainGui["Field"].Text\n'
        'idx := MainGui["Field"].Value\n'
        'OnChange(GuiCtrl, *) {\n'
        '    global changed\n'
        '    changed := GuiCtrl.Text\n'
        '}\n'
    )
    try:
        gui = rt.vars["MainGui"]
        ctrl = gui.get_control("Field")
        assert rt.vars["sel"] == "Bamboo"
        assert rt.vars["idx"] == 2
        ctrl._set_value(3)
        assert ctrl.get_text() == "Cactus"
        ctrl._fire("Change")
        assert rt.vars["changed"] == "Cactus"
    finally:
        close_guis(rt)


def test_gui_section_and_relative_positions():
    rt = run(
        'MainGui := Gui("", "Positions")\n'
        'MainGui.Add("Text", "x10 y20 Section vA", "A")\n'
        'MainGui.Add("Text", "xs+5 ys+6 vB", "B")\n'
        'MainGui.Add("Text", "x+7 y+8 vC", "C")\n'
        'TabCtrl := MainGui.Add("Tab", "x0 y-1 w500 h240 vTabs", ["Gather"])\n'
    )
    try:
        gui = rt.vars["MainGui"]
        b = gui.get_control("B")
        c = gui.get_control("C")
        tabs = gui.get_control("Tabs")
        assert (b._x, b._y) == (15, 26)
        # x+ is past the previous control's right edge; y+ past its bottom.
        assert c._x == b._x + b._w + 7
        assert c._y == b._y + b._h + 8
        # A bare minus is an absolute coordinate; Natro's tab is `y-1`.
        assert (tabs._x, tabs._y) == (0, -1)
    finally:
        close_guis(rt)


def test_gui_close_callback_and_destroy():
    rt = run(
        'MainGui := Gui("", "Close")\n'
        'MainGui.OnEvent("Close", (*) => (closed := 1))\n'
        'MainGui.Show()\n'
    )
    try:
        gui = rt.vars["MainGui"]
        assert gui.visible is True
        gui._close()
        assert rt.vars["closed"] == 1
        assert gui.visible is False
        gui._destroy()
        assert gui.destroyed is True
    finally:
        close_guis(rt)


def test_gui_picture_placeholder_does_not_crash():
    rt = run(
        'MainGui := Gui("", "Pictures")\n'
        'MainGui.Add("Picture", "x5 y5 w32 h32", "HBITMAP:*0")\n'
        'MainGui.Add("Picture", "x40 y5 w32 h32", "*w32 *h32 nm_image_assets\\missing.png")\n'
    )
    try:
        assert any("placeholder" in e for e in rt.logs)
    finally:
        close_guis(rt)


def test_gui_visible_keeps_wait_alive_and_pumps():
    rt = run('MainGui := Gui("", "Wait")\nMainGui.Show()\n')
    try:
        assert rt.has_pending_events() is True
        # A visible GUI keeps the loop alive, but the explicit timeout ends
        # this check.  The Qt pump must not raise offscreen.
        rt.wait(timeout=0.05)
    finally:
        close_guis(rt)
        assert rt.has_pending_events() is False


def test_gui_callback_errors_are_logged_not_raised():
    rt = run(
        'MainGui := Gui("", "Errors")\n'
        'btn := MainGui.Add("Button", "vB", "B")\n'
        'btn.OnEvent("Click", Broken)\n'
        'Broken(*) {\n'
        '    throw Error("boom")\n'
        '}\n'
    )
    try:
        rt.vars["MainGui"].get_control("B")._fire("Click")
        assert any("GUI Click callback error" in e for e in rt.logs)
        assert rt._pending_abort is None
    finally:
        close_guis(rt)


def test_gui_headless_fallback_logs_and_stays_falsy():
    import ahk_bridge.gui as gui_mod

    saved = (gui_mod._qt, gui_mod._qt_failed)
    gui_mod._qt = None
    gui_mod._qt_failed = True
    try:
        rt = run(
            'MainGui := Gui("", "Headless")\n'
            'c := MainGui.Add("Edit", "vE", "text")\n'
            'c.Value := "changed"\n'
            'val := c.Value\n'
            'MainGui.Show()\n'
        )
        try:
            assert rt.vars["val"] == "changed"
            assert any("PySide6 unavailable" in e for e in rt.logs)
            assert rt.vars["MainGui"].visible is True
        finally:
            close_guis(rt)
    finally:
        gui_mod._qt, gui_mod._qt_failed = saved


def test_click_identifier_is_not_a_legacy_click_command():
    from ahk_bridge.parser import Assign

    node = parse_script("clicked := 1\n").auto_section[0]
    assert isinstance(node, Assign)
    rt = run("clicked := 1\nresult := clicked\n")
    try:
        assert rt.vars["result"] == 1
    finally:
        close_guis(rt)
