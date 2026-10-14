import os
from ahk_bridge.input_abstract import detect_backend, InputSimulator
from ahk_bridge import window_match as wm
from ahk_bridge import pixels as px
from ahk_bridge.recorder import Recorder


def test_detect_backend_env(monkeypatch):
    monkeypatch.setenv("AHK_BRIDGE_BACKEND", "dry")
    assert detect_backend() == "dry"


def test_simulator_dry():
    sim = InputSimulator(backend="dry")
    sim.type_text("hi")
    sim.click("left")
    sim.move_mouse(10, 20)
    assert sim.backend_name == "dry"
    assert len(sim.log) == 3
    sim.close()


def test_window_match():
    w = {"exe": "RobloxPlayerBeta.exe", "class": "roblox", "title": "Roblox", "app_id": "roblox"}
    assert wm.match("ahk_exe RobloxPlayerBeta.exe", w)
    assert wm.match("ahk_class roblox", w)
    assert wm.match("roblox", w)
    assert not wm.match("ahk_exe notepad.exe", w)


def test_find_color():
    # 2x2 RGB: black, red, green, blue
    pxbuf = bytes([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255])
    assert px.find_color(pxbuf, 2, 2, (255, 0, 0)) == (1, 0)
    assert px.find_color(pxbuf, 2, 2, (9, 9, 9), tol=10) == (0, 0)
    assert px.find_color(pxbuf, 2, 2, (1, 2, 3)) is None


def test_recorder_export():
    r = Recorder()
    r.key("a")
    r.click("left", 100, 200)
    ahk = r.to_ahk()
    assert "Send" in ahk and "Click 100, 200 left" in ahk
    assert "F1::" in ahk
