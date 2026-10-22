"""v0.5 process bridge: Run/RunWait, child tracking and IPC messages."""
from __future__ import annotations

import os

from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime


def run_text(text, **kw):
    sim = DryBackend()
    rt = Runtime(parse_script(text), sim, **kw)
    rt.run_auto()
    return rt, sim


def test_runwait_child_posts_message_back_to_parent(tmp_path):
    child = tmp_path / "child.ahk"
    child.write_text("PostMessage 0x5552, 7, 9\n", encoding="utf-8")
    parent_text = (
        "got := 0\n"
        "OnMessage(0x5552, Handler)\n"
        "Handler(w, l, msg, hwnd) {\n"
        "    global got\n"
        "    got := w + l\n"
        "}\n"
        f'RunWait "{child}"\n'
    )
    rt, _ = run_text(parent_text)
    assert rt.vars["got"] == 16


def test_run_returns_pid_and_processclose_terminates_child():
    rt, _ = run_text('pid := Run("sleep 5")\n')
    pid = rt.vars["pid"]
    assert isinstance(pid, int) and pid > 0
    assert len(rt._children) == 1
    assert rt._children[0].poll() is None
    assert rt._process_close(pid) == 1
    assert rt._children[0].poll() is not None


def test_allow_processes_false_never_spawns():
    rt, _ = run_text('pid := Run("sleep 5")\n', allow_processes=False)
    assert rt.vars["pid"] == 0
    assert rt._children == []
    assert any("process spawning disabled" in line for line in rt.logs)


def test_translate_autohotkey_command_finds_script_and_drops_switches(tmp_path):
    script = tmp_path / "My Script.ahk"
    script.write_text("", encoding="utf-8")
    rt = Runtime(parse_script(""), DryBackend())
    kind, path, args = rt._translate_command(
        f'"/usr/bin/python3" /script "{script}" arg1')
    assert kind == "ahk"
    assert path == str(script)
    assert args == ["arg1"]


def test_windows_executable_is_logged_not_run():
    rt = Runtime(parse_script(""), DryBackend(), allow_processes=False)
    assert rt._execute_run(r'"C:\Tools\update.bat"') == 0
    assert any("Windows executable not supported" in line for line in rt.logs)


def test_url_run_is_refused_when_spawning_disabled():
    rt = Runtime(parse_script(""), DryBackend(), allow_processes=False)
    assert rt._execute_run('"https://example.com/path"') == 0
    assert any("process spawning disabled" in line for line in rt.logs)


def test_autohotkey_switches_without_script_do_not_spawn_python():
    rt = Runtime(parse_script(""), DryBackend(), allow_processes=True)
    assert rt._execute_run('"/usr/bin/python3" /restart') == 0
    assert rt._children == []
    assert any("without an .ahk script" in line for line in rt.logs)
