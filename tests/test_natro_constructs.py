"""v0.3 Natro-driven constructs: switch, for, try, Loop Parse/Files, Map,
subscripts, ternary, compound-assign, Seq, fat-arrow, KeyWait, Ini, Throw."""
import os

import pytest

from ahk_bridge.parser import parse_script
from ahk_bridge import runtime as R
from ahk_bridge.backends.dry_backend import DryBackend


def run(text, **kw):
    sc = parse_script(text)
    sim = DryBackend()
    rt = R.Runtime(sc, sim, **kw)
    return sc, rt, sim


def types(sim):
    return [e[1] for e in sim.log if e[0] == "type"]


def test_switch_matches():
    sc, rt, sim = run('x := 2\nSwitch x {\nCase 1:\nSend "one"\nCase 2:\nSend "two"\nDefault:\nSend "other"\n}\n')
    rt.run_auto()
    assert types(sim) == ["two"]


def test_switch_default():
    sc, rt, sim = run('x := 9\nSwitch x {\nCase 1:\nSend "one"\nDefault:\nSend "other"\n}\n')
    rt.run_auto()
    assert types(sim) == ["other"]


def test_switch_allman_brace_next_line():
    sc, rt, sim = run('x := 1\nSwitch x\n{\nCase 1:\nSend "hit"\n}\n')
    rt.run_auto()
    assert types(sim) == ["hit"]


def test_for_over_strsplit():
    sc, rt, sim = run('for part in StrSplit("a|b|c", "|") {\nSend part\n}\n')
    rt.run_auto()
    assert types(sim) == ["a", "b", "c"]


def test_for_over_list_literal():
    sc, rt, sim = run('for v in [10, 20] {\nSend "{v}"\n}\n')
    rt.run_auto()
    assert types(sim) == ["10", "20"]


def test_try_catch_finally():
    sc, rt, sim = run('try {\nThrow "boom"\n} Catch e {\nSend "caught"\n} Finally {\nSend "fin"\n}\n')
    rt.run_auto()
    assert types(sim) == ["caught", "fin"]
    assert rt.vars["e"] == "boom"


def test_loop_parse_sets_field():
    sc, rt, sim = run('Loop Parse, "a,b,c", "," {\nSend "{A_LoopField}"\n}\n')
    rt.run_auto()
    assert types(sim) == ["a", "b", "c"]


def test_map_and_subscript():
    sc, rt, sim = run('m := Map("k", "v")\nSend m["k"]\n')
    rt.run_auto()
    assert types(sim) == ["v"]


def test_ternary():
    sc, rt, sim = run('x := 5\ny := (x > 3) ? "big" : "small"\nSend y\n')
    rt.run_auto()
    assert types(sim) == ["big"]


def test_compound_and_incdec():
    sc, rt, sim = run('x := 1\nx += 4\nx++\nSend "{x}"\ns := "a"\ns .= "b"\nSend s\n')
    rt.run_auto()
    assert types(sim) == ["6", "ab"]


def test_seq_comma_statements():
    sc, rt, sim = run('Send "a", Send "b"\n')
    rt.run_auto()
    assert types(sim) == ["a", "b"]


def test_fat_arrow_and_return_value():
    sc, rt, sim = run('Double(n) => n * 2\nx := Double(21)\nSend "{x}"\n')
    rt.run_auto()
    assert types(sim) == ["42"]


def test_short_circuit_and():
    sc, rt, sim = run('x := 1\n(x = 1) && Send "yes"\n(x = 2) && Send "no"\n')
    rt.run_auto()
    assert types(sim) == ["yes"]


def test_keywait_timeout_sleeps():
    sc, rt, sim = run('KeyWait "LButton", "D T1"\n')
    rt.run_auto()
    assert ("sleep", 1000) in [(e[0], e[1]) for e in sim.log]


def test_onexit_named_callback_fires_once_on_exitapp():
    text = (
        "OnExit(Cleanup)\n"
        "Cleanup(reason, code) {\n"
        '    Send "{reason}:{code}"\n'
        "}\n"
        "ExitApp 7\n"
    )
    sc, rt, sim = run(text)
    with pytest.raises(R.Aborted):
        rt.run_auto()
    assert types(sim) == ["Exit:7"]
    with pytest.raises(R.Aborted):
        rt.run_auto()
    assert types(sim) == ["Exit:7"]


def test_onexit_inline_arrow_and_order():
    text = (
        'OnExit((*) => Send("first"))\n'
        'OnExit((*) => Send("second"), -1)\n'
        "ExitApp\n"
    )
    sc, rt, sim = run(text)
    with pytest.raises(R.Aborted):
        rt.run_auto()
    assert types(sim) == ["second", "first"]


def test_onexit_runs_on_normal_script_end():
    sc, rt, sim = run('OnExit((*) => Send("done"))\n')
    rt.run_auto()
    assert types(sim) == ["done"]
    rt.run_auto()  # exit already handled; must not fire twice
    assert types(sim) == ["done"]


def test_onerror_arrow_suppresses_and_script_continues():
    text = (
        'OnError((e, mode) => (mode = "Return") ? 1 : 0)\n'
        'Throw "boom"\n'
        'Send "after"\n'
    )
    sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["after"]
    assert any("OnError handled: boom" in line for line in rt.logs)


def test_onerror_named_callback_sees_error_object():
    text = (
        "OnError(Handler)\n"
        "Handler(e, mode) {\n"
        "    handledMode := mode\n"
        "    handledMsg := e.Message\n"
        "    return 1\n"
        "}\n"
        'Throw "kaboom"\n'
    )
    sc, rt, sim = run(text)
    rt.run_auto()
    assert rt.vars["handledMode"] == "Return"
    assert rt.vars["handledMsg"] == "kaboom"


def test_onerror_unhandled_still_raises_and_can_be_removed():
    text = (
        "OnError(Handler)\n"
        "OnError(Handler, 0)\n"
        "Handler(e, mode) {\n"
        "    return 1\n"
        "}\n"
        'Throw "boom"\n'
    )
    sc, rt, sim = run(text)
    with pytest.raises(RuntimeError, match="boom"):
        rt.run_auto()


def test_fileopen_file_object_roundtrip(tmp_path):
    base = str(tmp_path).replace("\\", "/")
    text = (
        f'f := FileOpen("{base}/data.txt", "w-d")\n'
        'f.Write("alpha`n")\n'
        'f.WriteLine("beta")\n'
        "size := f.Length\n"
        "f.Close()\n"
        f'f := FileOpen("{base}/data.txt", "r")\n'
        "first := f.ReadLine()\n"
        "rest := f.Read()\n"
        "f.Seek(0)\n"
        "whole := f.Read()\n"
        "pos := f.Pos\n"
        "eof := f.AtEOF\n"
        "f.Close()\n"
        f'f := FileOpen("{base}/data.txt", "a")\n'
        'f.WriteLine("gamma")\n'
        "f.Close()\n"
    )
    sc, rt, sim = run(text, working_dir=base)
    rt.run_auto()
    assert rt.vars["first"] == "alpha"
    assert rt.vars["rest"] == "beta\n"
    assert rt.vars["whole"] == "alpha\nbeta\n"
    assert rt.vars["pos"] == len("alpha\nbeta\n")
    assert rt.vars["eof"] == 1
    assert rt.vars["size"] == len("alpha\nbeta\n")
    assert (tmp_path / "data.txt").read_text().endswith("gamma\n")
    assert not any("stub builtin fileopen" in line for line in rt.logs)


def test_file_builtins_and_relative_working_directory(tmp_path):
    base = str(tmp_path)
    text = (
        f'DirCreate "{base}\\sub"\n'
        f'FileAppend "hello", "{base}\\sub\\a.txt"\n'
        f'FileCopy "{base}\\sub\\a.txt", "{base}\\sub\\b.txt"\n'
        f'Send FileExist("{base}\\sub\\b.txt")\n'
        f'Send FileExist("{base}\\sub")\n'
        f'Send FileExist("{base}\\missing.txt")\n'
        f'Send FileRead("{base}\\sub\\b.txt")\n'
        f'Send FileGetSize("{base}\\sub\\b.txt")\n'
        f'FileMove "{base}\\sub\\b.txt", "{base}\\sub\\c.txt"\n'
        f'Send FileExist("{base}\\sub\\c.txt")\n'
        f'FileDelete "{base}\\sub\\c.txt"\n'
        f'Send FileExist("{base}\\sub\\c.txt")\n'
        f'FileDelete "{base}\\sub\\a.txt"\n'
        f'DirDelete "{base}\\sub"\n'
        f'Send FileExist("{base}\\sub")\n'
    )
    sc, rt, sim = run(text, working_dir=base)
    rt.run_auto()
    assert types(sim) == ["A", "D", "hello", "5", "A"]
    assert os.path.exists(tmp_path / "sub") is False


def test_type_conversions_and_environment_builtins(monkeypatch):
    monkeypatch.delenv("AHK_BRIDGE_TEST_VAR", raising=False)
    sc, rt, sim = run(
        "Send Type(1)\n"
        "Send Type(1.5)\n"
        'Send Type("x")\n'
        "Send Type([1])\n"
        "Send Type(Map())\n"
        "Send Integer(\"3.9\")\n"
        "Send Float(\"2.5\")\n"
        'Send Ord("A")\n'
        "Send Chr(66)\n"
        'EnvSet("AHK_BRIDGE_TEST_VAR", "v")\n'
        'Send EnvGet("AHK_BRIDGE_TEST_VAR")\n'
    )
    rt.run_auto()
    assert types(sim) == [
        "Integer", "Float", "String", "Array", "Map",
        "3", "2.5", "65", "B", "v"]


def test_map_and_array_methods_and_for_pairs():
    sc, rt, sim = run(
        'm := Map("a", 1, "b", 2)\n'
        'Send m.Has("a")\n'
        'Send m.Has("z")\n'
        'Send m.Get("b")\n'
        'Send m.Delete("a")\n'
        "Send m.Has(\"a\")\n"
        "arr := [1, 2]\n"
        "arr.Push(3)\n"
        "Send arr.Length\n"
        "Send arr.Pop()\n"
        "arr.InsertAt(2, 9)\n"
        "Send arr[2]\n"
        "Send arr.RemoveAt(1)\n"
        "for k, v in m {\n"
        "    Send k\n"
        "    Send v\n"
        "}\n"
    )
    rt.run_auto()
    assert types(sim) == ["1", "0", "2", "1", "0", "3", "3", "9", "1", "b", "2"]


def test_noarg_oserror_throws_named_error():
    sc, rt, sim = run("Throw OSError()\n")
    with pytest.raises(RuntimeError, match="OSError"):
        rt.run_auto()


def test_splitpath_call_and_command_byref_outputs():
    text = (
        'SplitPath("/home/user/My File.txt", &name, &dir, &ext, &noext, &drive)\n'
        'SplitPath("C:\\My Dir\\File.txt", &wname, &wdir, &wext)\n'
        'SplitPath("relative.txt", , &rdir)\n'
        'SplitPath "C:\\My Dir\\Legacy.txt", , &legacyDir\n'
    )
    sc, rt, sim = run(text)
    rt.run_auto()
    assert rt.vars["name"] == "My File.txt"
    assert rt.vars["dir"] == "/home/user/"
    assert rt.vars["ext"] == "txt"
    assert rt.vars["noext"] == "My File"
    assert rt.vars["drive"] == "/"
    assert rt.vars["wname"] == "File.txt"
    assert rt.vars["wdir"] == "C:\\My Dir\\"
    assert rt.vars["wext"] == "txt"
    assert rt.vars["rdir"] == ""
    assert rt.vars["legacyDir"] == "C:\\My Dir\\"


def test_string_and_number_conversions():
    text = (
        "a := String(42)\n"
        "b := String(1.5)\n"
        "c := String(1.0)\n"
        'd := Number("08")\n'
        'e := Number("1.25")\n'
        'f := Number(" 42 ")\n'
        'g := Number("0x10")\n'
    )
    sc, rt, sim = run(text)
    rt.run_auto()
    assert rt.vars["a"] == "42"
    assert rt.vars["b"] == "1.5"
    assert rt.vars["c"] == "1"
    assert rt.vars["d"] == 8
    assert rt.vars["e"] == 1.25
    assert rt.vars["f"] == 42
    assert rt.vars["g"] == 16
    with pytest.raises(RuntimeError):
        rt._to_ahk_number("not a number")


def test_dateadd_datediff_ahk_units_and_calendar_months():
    text = (
        'a := DateDiff("20240102030405", "20240101000000", "S")\n'
        'b := DateDiff("20240102030405", "20240101000000", "Hours")\n'
        'c := DateDiff("20240102030405", "20240101000000", "Days")\n'
        'd := DateDiff("20240102030405", "20240101000000", "m")\n'
        'e := DateAdd("20240131235959", 1, "Months")\n'
        'f := DateAdd("20240101", -1, "Days")\n'
        'g := DateAdd("20240101", -10, "m")\n'
        'h := DateDiff("20240228", "20240131", "Months")\n'
        'i := DateDiff("20240101", "20250101", "Years")\n'
    )
    sc, rt, sim = run(text)
    rt.run_auto()
    assert rt.vars["a"] == 97445
    assert rt.vars["b"] == 27
    assert rt.vars["c"] == 1
    assert rt.vars["d"] == 1624
    assert rt.vars["e"] == "20240229235959"
    assert rt.vars["f"] == "20231231000000"
    assert rt.vars["g"] == "20231231235000"
    assert rt.vars["h"] == 0
    assert rt.vars["i"] == -1


def test_iniread_builtin_matches_ahk_semantics(tmp_path):
    ini = tmp_path / "nm_config.ini"
    ini.write_text(
        "\ufeff[Settings]\n"
        "GuiTheme = Dark\n"
        "Percent = 100% done\n"
        "[Planters]\n"
        "TimerX=12\n",
        encoding="utf-8",
    )
    path = str(ini).replace("\\", "/")
    missing = str(tmp_path / "absent.ini").replace("\\", "/")
    text = (
        f'a := IniRead("{path}", "settings", "guitheme", "fallback")\n'
        f'b := IniRead("{path}", "Settings", "missing", 42)\n'
        f'c := IniRead("{missing}", "Settings", "GuiTheme", "dflt")\n'
        f'd := IniRead("{path}", "Settings", "Percent")\n'
        f'e := IniRead("{path}", "Planters", "TimerX")\n'
    )
    sc, rt, sim = run(text)
    rt.run_auto()
    assert rt.vars["a"] == "Dark"
    assert rt.vars["b"] == 42
    assert rt.vars["c"] == "dflt"
    assert rt.vars["d"] == "100% done"
    assert rt.vars["e"] == "12"


def test_ini_write_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sc, rt, sim = run('IniWrite "hello", "t.ini", "S", "K"\nv := ""\nIniRead v, "t.ini", "S", "K"\nSend v\n')
    rt.run_auto()
    assert types(sim) == ["hello"]


def test_loop_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.ahk").write_text("x")
    (tmp_path / "b.ahk").write_text("y")
    sc, rt, sim = run('Loop Files "*.ahk" {\nSend "{A_LoopFileName}"\n}\n')
    rt.run_auto()
    assert sorted(types(sim)) == ["a.ahk", "b.ahk"]


def test_deref_and_a_index():
    sc, rt, sim = run('i := 2\nPlanterName2 := "ok"\nSend PlanterName%i%\nLoop 2 {\nSend "{A_Index}"\n}\n')
    rt.run_auto()
    assert types(sim) == ["ok", "1", "2"]


def test_substr_instr_strlen():
    sc, rt, sim = run('s := "hello"\nSend SubStr(s, 2, 3)\nSend "{InStr(s, \'l\')}"\nSend "{StrLen(s)}"\n')
    rt.run_auto()
    assert types(sim) == ["ell", "3", "5"]
