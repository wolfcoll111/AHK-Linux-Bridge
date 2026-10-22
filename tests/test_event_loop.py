"""v0.5 timers, dynamic hotkeys, suspend/pause and the event loop."""
from __future__ import annotations

import time

import pytest

from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Aborted, Runtime


def run_text(text, **kw):
    sim = DryBackend()
    rt = Runtime(parse_script(text), sim, **kw)
    rt.run_auto()
    return rt, sim


def test_positive_timer_recurs_and_can_cancel_itself():
    rt, _ = run_text(
        "count := 0\n"
        "SetTimer Tick, 5\n"
        "Tick() {\n"
        "    global count\n"
        "    count += 1\n"
        '    if (count >= 3)\n'
        '        SetTimer "Tick", 0\n'
        "}\n"
    )
    assert rt._timers
    rt.wait(timeout=1.0)
    assert rt.vars["count"] == 3
    assert rt._timers == {}


def test_negative_timer_is_one_shot():
    rt, _ = run_text(
        "fired := 0\n"
        "SetTimer Once, -10\n"
        "Once() {\n"
        "    global fired\n"
        "    fired += 1\n"
        "}\n"
    )
    started = time.monotonic()
    rt.wait(timeout=1.0)
    assert rt.vars["fired"] == 1
    assert rt._timers == {}
    assert time.monotonic() - started >= 0.008


def test_timer_exception_is_logged_and_loop_continues():
    rt, _ = run_text(
        "ok := 0\n"
        "SetTimer Bad, 5\n"
        "SetTimer Good, 15\n"
        "Bad() {\n"
        '    SetTimer "Bad", 0\n'
        '    throw "timer boom"\n'
        "}\n"
        "Good() {\n"
        "    global ok\n"
        "    ok := 1\n"
        '    SetTimer "Good", 0\n'
        "}\n"
    )
    rt.wait(timeout=1.0)
    assert rt.vars["ok"] == 1
    assert any("timer boom" in line for line in rt.logs)


def test_dynamic_hotkey_command_and_call_syntax():
    rt, _ = run_text(
        "hits := 0\n"
        'Hotkey "F4", Dyn\n'
        'Hotkey("F5", "Dyn")\n'
        "Dyn() {\n"
        "    global hits\n"
        "    hits += 1\n"
        "}\n"
    )
    assert rt.fire_hotkey("F4")
    assert rt.fire_hotkey("f5")
    assert rt.vars["hits"] == 2
    rt._exec(parse_script('Hotkey "F5", Dyn, "Off"\n').auto_section[0])
    assert rt.fire_hotkey("F5") is False


def test_suspend_blocks_dynamic_hotkeys_and_getkeystate_reports_it():
    rt, sim = run_text(
        "hits := 0\n"
        'Hotkey "F6", Dyn\n'
        "Dyn() {\n"
        "    global hits\n"
        "    hits += 1\n"
        "}\n"
        'Suspend "On"\n'
        'Send GetKeyState("Suspend")\n'
        "suspended_fire := 0\n"
        "suspended_fire := Fire()\n"
        'Suspend "Off"\n'
        'Send GetKeyState("Suspend")\n'
        "Fire() {\n"
        "    return 0\n"
        "}\n"
    )
    assert rt.fire_hotkey("F6")
    assert rt.vars["hits"] == 1
    assert [e[1] for e in sim.log if e[0] == "type"] == ["1", "0"]


def test_pause_toggle_updates_state_and_a_is_paused():
    rt, sim = run_text(
        'Pause "On"\n'
        'Send GetKeyState("Pause")\n'
        "Send A_IsPaused\n"
        'Pause "Off"\n'
        "Send A_IsPaused\n"
    )
    assert [e[1] for e in sim.log if e[0] == "type"] == ["1", "1", "0"]
    assert rt.vars["A_IsPaused"] == 0


def test_persistent_directive_keeps_runtime_alive():
    rt, _ = run_text("#Persistent\n")
    assert rt._keep_alive is True
    assert rt.has_pending_events() is True


def test_sendmessage_dispatches_registered_handler_synchronously():
    rt, _ = run_text(
        "got := \"\"\n"
        "OnMessage(0x5551, Handler)\n"
        "SendMessage(0x5551, 7, 9)\n"
        "Handler(w, l, msg, hwnd) {\n"
        "    global got\n"
        "    got := w \"-\" l \"-\" msg\n"
        "}\n"
    )
    assert rt.vars["got"] == "7-9-21841"


def test_postmessage_command_form_is_processed_by_wait():
    rt, _ = run_text(
        "got := 0\n"
        "OnMessage(0x5552, Handler)\n"
        "Handler(w, l, msg, hwnd) {\n"
        "    global got\n"
        "    got := w + l\n"
        "}\n"
        "i := 4\n"
        "PostMessage 0x5552, 232 + i, 10\n"
    )
    assert rt._message_queue.qsize() == 1
    rt.wait(timeout=0.2)
    assert rt.vars["got"] == 246


def test_onmessage_arrow_callback_and_removal():
    rt, sim = run_text(
        'OnMessage(0x5553, (w, l, msg, hwnd) => Send(w))\n'
        "SendMessage(0x5553, 42, 0)\n"
        "OnMessage(0x5553, 0)\n"
        "SendMessage(0x5553, 43, 0)\n"
    )
    assert [e[1] for e in sim.log if e[0] == "type"] == ["42"]
    assert 0x5553 not in rt._message_handlers


def test_message_handler_exception_is_logged_and_other_handlers_run():
    rt, _ = run_text(
        "ok := 0\n"
        "OnMessage(0x5554, Bad)\n"
        "OnMessage(0x5554, Good)\n"
        "Bad(w, l, msg, hwnd) {\n"
        '    throw "handler boom"\n'
        "}\n"
        "Good(w, l, msg, hwnd) {\n"
        "    global ok\n"
        "    ok := 1\n"
        "}\n"
        "SendMessage(0x5554, 0, 0)\n"
    )
    assert rt.vars["ok"] == 1
    assert any("handler boom" in line for line in rt.logs)


def test_cli_waits_for_pending_timer_and_honors_exit_after(tmp_path, capsys):
    from ahk_bridge.cli import build_parser, cmd_run

    fired = tmp_path / "timer.ahk"
    fired.write_text(
        "SetTimer Done, -20\n"
        "Done() {\n"
        '    MsgBox "timer fired"\n'
        "}\n", encoding="utf-8")
    args = build_parser().parse_args(
        ["run", "--backend", "dry", str(fired)])
    assert cmd_run(args) == 0
    assert "MsgBox: timer fired" in capsys.readouterr().out

    long_timer = tmp_path / "long.ahk"
    long_timer.write_text("SetTimer Tick, 100000\nTick() {\n}\n",
                          encoding="utf-8")
    args = build_parser().parse_args(
        ["run", "--backend", "dry", "--exit-after", "0.02", str(long_timer)])
    started = time.monotonic()
    assert cmd_run(args) == 0
    assert time.monotonic() - started < 1.0


def test_exitapp_function_runs_onexit_once_and_unwinds():
    rt = Runtime(parse_script(
        "calls := 0\n"
        "OnExit(Handler)\n"
        "ExitApp()\n"
        "Handler(reason, code) {\n"
        "    global calls\n"
        "    calls += 1\n"
        "}\n"
    ), DryBackend())
    with pytest.raises(Aborted) as info:
        rt.run_auto()
    assert info.value.exit_code == 0
    assert rt.vars["calls"] == 1
    assert rt._exit_done is True


def test_exitapp_from_timer_unwinds_wait_and_runs_onexit():
    rt = Runtime(parse_script(
        "calls := 0\n"
        "OnExit(Handler)\n"
        "SetTimer Quit, -5\n"
        "Quit() {\n"
        "    ExitApp()\n"
        "}\n"
        "Handler(reason, code) {\n"
        "    global calls\n"
        "    calls += 1\n"
        "}\n"
    ), DryBackend())
    rt.run_auto(exit_callbacks=False)
    with pytest.raises(Aborted) as info:
        rt.wait(timeout=1.0)
    assert info.value.exit_code == 0
    assert rt.vars["calls"] == 1


def test_cli_exitapp_returns_requested_exit_code(tmp_path):
    from ahk_bridge.cli import build_parser, cmd_run

    script = tmp_path / "exit.ahk"
    script.write_text("ExitApp(7)\n", encoding="utf-8")
    args = build_parser().parse_args(["run", "--backend", "dry", str(script)])
    assert cmd_run(args) == 7
