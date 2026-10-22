"""v0.5 built-in variables, A_Args, and working-directory semantics."""
from __future__ import annotations

import os
import re

from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime


def run_text(text, **kw):
    sim = DryBackend()
    rt = Runtime(parse_script(text), sim, **kw)
    rt.run_auto()
    return rt, sim


def types(sim):
    return [e[1] for e in sim.log if e[0] == "type"]


def test_script_vars_use_script_directory_not_cwd(tmp_path, monkeypatch):
    script_dir = tmp_path / "macro"
    script_dir.mkdir()
    script_path = script_dir / "main.ahk"
    script_path.write_text("", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    rt, _ = run_text("", script_path=str(script_path))

    assert rt.vars["A_ScriptDir"] == str(script_dir)
    assert rt.vars["A_ScriptName"] == "main.ahk"
    assert rt.vars["A_ScriptFullPath"] == str(script_path)
    assert rt.vars["A_WorkingDir"] == str(script_dir)
    assert rt.vars["A_LineFile"] == str(script_path)


def test_a_args_order_length_and_indexing():
    rt, sim = run_text(
        "Send A_Args.Length\n"
        "Send A_Args[1]\n"
        "Send A_Args[2]\n",
        args=["first", "second value"],
    )
    assert types(sim) == ["2", "first", "second value"]
    assert rt.vars["A_Args"] == ["first", "second value"]


def test_time_vars_have_ahk_shapes_and_tick_count_advances():
    rt, sim = run_text(
        "MsgBox {A_Now}\n"
        "MsgBox {A_NowUTC}\n"
        "MsgBox {A_Year}/{A_MM}/{A_DD} {A_Hour}:{A_Min}:{A_Sec}.{A_MSec}\n"
        "MsgBox {A_TickCount}\n"
    )
    now, utc, parts, tick = [line.split(": ", 1)[1] for line in rt.logs]
    assert re.fullmatch(r"\d{14}", now)
    assert re.fullmatch(r"\d{14}", utc)
    assert re.fullmatch(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3}", parts)
    assert int(tick) >= 0


def test_setworkingdir_really_changes_directory_and_variable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "work"
    target.mkdir()
    rt, sim = run_text(
        f'SetWorkingDir "{target}"\n'
        "Send A_WorkingDir\n"
    )
    assert os.getcwd() == str(target)
    assert rt.vars["A_WorkingDir"] == str(target)
    assert types(sim) == [str(target)]


def test_setkeydelay_updates_a_keydelay():
    rt, sim = run_text("SetKeyDelay 25, 10\nSend {A_KeyDelay}\n")
    assert rt.vars["A_KeyDelay"] == 25
    assert types(sim) == ["25"]


def test_relative_iniread_uses_working_directory(tmp_path, monkeypatch):
    script_dir = tmp_path / "script"
    script_dir.mkdir()
    (script_dir / "settings").mkdir()
    (script_dir / "settings" / "nm_config.ini").write_text(
        "[General]\nEnabled=1\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    rt, sim = run_text(
        'Send IniRead("settings\\nm_config.ini", "General", "Enabled", "0")\n',
        script_path=str(script_dir / "main.ahk"),
    )
    assert types(sim) == ["1"]


def test_traymenu_tracks_items_default_and_callbacks():
    rt, sim = run_text(
        'A_TrayMenu.Add("Open Logs", (*) => Send("opened"))\n'
        "A_TrayMenu.Add()\n"
        'A_TrayMenu.Default := "Open Logs"\n'
        'Send A_TrayMenu.Default\n'
        'A_TrayMenu.Click("Open Logs")\n'
        "A_TrayMenu.Show()\n"
    )
    menu = rt.vars["A_TrayMenu"]
    assert [name for name, _ in menu.items] == ["Open Logs", None]
    assert menu.default == "Open Logs"
    assert types(sim) == ["Open Logs", "opened"]
    assert any("A_TrayMenu.Show: Open Logs" in line for line in rt.logs)


def test_screen_and_platform_vars():
    rt, _ = run_text("", screen_size=(2560, 1440))
    assert (rt.vars["A_ScreenWidth"], rt.vars["A_ScreenHeight"]) == (2560, 1440)
    assert rt.vars["A_ScreenDPI"] == 96
    assert rt.vars["A_PtrSize"] in (4, 8)
    assert rt.vars["A_Is64bitOS"] in (0, 1)
    assert rt.vars["A_Space"] == " "
    assert rt.vars["A_Tab"] == "\t"


def test_cli_positional_args_reach_a_args(tmp_path, capsys):
    from ahk_bridge.cli import build_parser, cmd_run

    script = tmp_path / "args.ahk"
    script.write_text(
        "n := A_Args.Length\n"
        "first := A_Args[1]\n"
        "second := A_Args[2]\n"
        "MsgBox {n}\n"
        "MsgBox {first}\n"
        "MsgBox {second}\n",
        encoding="utf-8")
    args = build_parser().parse_args(
        ["run", "--backend", "dry", str(script), "--", "one", "two words"])
    assert cmd_run(args) == 0
    out = capsys.readouterr().out
    assert "MsgBox: 2" in out
    assert "MsgBox: one" in out
    assert "MsgBox: two words" in out
