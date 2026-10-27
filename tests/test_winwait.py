"""WinWait / WinWaitClose / WinWaitActive / WinWaitNotActive / WinActive.

Window resolution and the active handle are stubbed, so no X server or live
desktop is contacted.  A virtual clock replaces Runtime._clock: the dry
backend records sleeps instead of performing them, which keeps the polling
loop fast while still exercising timeout arithmetic.
"""
import pytest

from ahk_bridge import window_ops as wo
from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime

TARGET = {"kind": "external", "gui": None, "control": None,
          "hwnd": 777, "title": "Roblox"}


class VirtualClock:
    def __init__(self, step: float = 0.05):
        self.now = 0.0
        self.step = step
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        self.now += self.step
        return self.now


def _runtime(code: str):
    rt = Runtime(parse_script(code), DryBackend())
    clock = VirtualClock()
    rt._clock = clock
    return rt, clock


def test_winwait_returns_hwnd_when_window_appears(monkeypatch):
    rt, _clock = _runtime('found := WinWait("Roblox", , 2)')
    calls = {"n": 0}

    def resolve(_value):
        calls["n"] += 1
        return TARGET if calls["n"] >= 3 else None

    monkeypatch.setattr(rt, "_resolve_window", resolve)
    rt.run_auto()
    assert rt.vars["found"] == 777
    assert calls["n"] == 3


def test_winwait_omitted_middle_slot_keeps_timeout(monkeypatch):
    # WinWait(WinTitle, WinText, Timeout): dropping the empty WinText slot
    # would make Timeout look like WinText and wait forever.
    rt, clock = _runtime('found := WinWait("Roblox", , 0.5)')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: None)
    rt.run_auto()
    assert rt.vars["found"] == 0
    assert clock.now < 1.0


def test_winwait_timeout_zero_checks_once(monkeypatch):
    rt, clock = _runtime('found := WinWait("Roblox", , 0)')
    calls = {"n": 0}

    def resolve(_value):
        calls["n"] += 1
        return None

    monkeypatch.setattr(rt, "_resolve_window", resolve)
    rt.run_auto()
    assert rt.vars["found"] == 0
    assert calls["n"] == 1
    assert clock.now == pytest.approx(0.1)


def test_winwait_close_succeeds_immediately_when_absent(monkeypatch):
    rt, _clock = _runtime('closed := WinWaitClose("Roblox", , 2)')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: None)
    rt.run_auto()
    assert rt.vars["closed"] == 1


def test_winwait_close_waits_until_window_disappears(monkeypatch):
    rt, _clock = _runtime('closed := WinWaitClose("Roblox", , 2)')
    calls = {"n": 0}

    def resolve(_value):
        calls["n"] += 1
        return TARGET if calls["n"] < 4 else None

    monkeypatch.setattr(rt, "_resolve_window", resolve)
    rt.run_auto()
    assert rt.vars["closed"] == 1
    assert calls["n"] == 4


def test_winwait_close_times_out_while_window_remains(monkeypatch):
    rt, _clock = _runtime('closed := WinWaitClose("Roblox", , 0.5)')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: TARGET)
    rt.run_auto()
    assert rt.vars["closed"] == 0


def test_winwait_close_refuses_wintext_instead_of_faking_success(monkeypatch):
    rt, _clock = _runtime('closed := WinWaitClose("Roblox", "Save", 0)')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: TARGET)
    rt.run_auto()
    assert rt.vars["closed"] == 0
    assert any("WinText/ExcludeText" in line for line in rt.logs)


def test_winwait_active_matches_active_handle(monkeypatch):
    rt, _clock = _runtime('active := WinWaitActive("Roblox", , 2)')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: TARGET)
    monkeypatch.setattr(rt, "_active_window_hwnd", lambda: 777)
    rt.run_auto()
    assert rt.vars["active"] == 777


def test_winwait_active_times_out_when_another_window_is_active(monkeypatch):
    rt, _clock = _runtime('active := WinWaitActive("Roblox", , 0.5)')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: TARGET)
    monkeypatch.setattr(rt, "_active_window_hwnd", lambda: 888)
    rt.run_auto()
    assert rt.vars["active"] == 0


def test_winwait_not_active_returns_immediately(monkeypatch):
    rt, _clock = _runtime('inactive := WinWaitNotActive("Roblox", , 2)')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: TARGET)
    monkeypatch.setattr(rt, "_active_window_hwnd", lambda: 888)
    rt.run_auto()
    assert rt.vars["inactive"] == 1


def test_winwait_not_active_times_out_while_window_is_active(monkeypatch):
    rt, _clock = _runtime('inactive := WinWaitNotActive("Roblox", , 0.5)')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: TARGET)
    monkeypatch.setattr(rt, "_active_window_hwnd", lambda: 777)
    rt.run_auto()
    assert rt.vars["inactive"] == 0


def test_winactive_returns_matching_active_handle(monkeypatch):
    rt, _clock = _runtime('active := WinActive("Roblox")')
    monkeypatch.setattr(rt, "_resolve_window", lambda _value: TARGET)
    monkeypatch.setattr(rt, "_active_window_hwnd", lambda: 777)
    rt.run_auto()
    assert rt.vars["active"] == 777


def test_winactive_blank_returns_real_active_handle(monkeypatch):
    rt, _clock = _runtime('active := WinActive()')
    monkeypatch.setattr(wo, "active", lambda: 4321)
    rt.run_auto()
    assert rt.vars["active"] == 4321


def test_legacy_winwaitclose_evaluates_ahk_id_expression(monkeypatch):
    rt, _clock = _runtime(
        'h := 4242\nWinWaitClose "ahk_id " h, , 0')
    seen = []

    def resolve(value):
        seen.append(value)
        return None

    monkeypatch.setattr(rt, "_resolve_window", resolve)
    rt.run_auto()
    assert seen == ["ahk_id 4242"]
    assert not any("stub builtin winwaitclose" in line for line in rt.logs)
