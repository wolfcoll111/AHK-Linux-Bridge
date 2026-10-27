"""v0.3 Natro-driven constructs: switch, for, try, Loop Parse/Files, Map,
subscripts, ternary, compound-assign, Seq, fat-arrow, KeyWait, Ini, Throw."""
import os
import time

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


def test_msgbox_continuation_section_is_one_statement():
    # Natro writes the deprecated-pattern warnings as a bare MsgBox followed
    # by a continuation section.  The section must belong to that command,
    # including when the command is the braceless body of an `if`.
    sc = parse_script(
        "if cond\n"
        "MsgBox\n"
        "(\n"
        "'hello (ok)'\n"
        "), \"Error\", 0x10\n")
    assert len(sc.auto_section) == 1
    node = sc.auto_section[0]
    assert type(node).__name__ == "If"
    assert [type(child).__name__ for child in node.then_body] == ["MsgBox"]
    assert node.then_body[0].text == "hello (ok)"


def test_msgbox_continuation_section_respects_if_condition():
    _sc, rt, _sim = run(
        "cond := 0\n"
        "if cond\n"
        "MsgBox\n"
        "(\n"
        "'hidden text'\n"
        "), \"Error\", 0x10\n"
        "MsgBox\n"
        "(\n"
        "'shown text'\n"
        ")\n")
    rt.run_auto()
    assert not any("hidden text" in line for line in rt.logs)
    assert any("shown text" in line for line in rt.logs)


def test_run_continuation_section_evaluates_concat_expression():
    # Natro builds the Status.ahk command line as `Run` + a parenthesized
    # continuation section whose quoted/var parts form one expression.
    text = (
        'exe := "/bin/echo"\n'
        'word := "hello"\n'
        'Run\n'
        '(\n'
        "'\"' exe '\" ' word\n"
        ')\n'
    )
    sc = parse_script(text)
    assert not any(getattr(node, "name", "") == "__raw__"
                   for node in sc.auto_section)
    _sc, rt, _sim = run(text, allow_processes=False)
    rt.run_auto()
    assert any("process spawning disabled" in entry
               and '"/bin/echo" hello' in entry for entry in rt.logs)


def test_trayseticon_command_style_is_parsed_and_logged():
    # Natro calls `TraySetIcon "path"` without parentheses; the tray is a
    # Windows display surface, so parse the statement and log the no-op
    # instead of leaving it as a raw statement.
    text = 'TraySetIcon "nm_image_assets\\auryn.ico"\n'
    sc, rt, _sim = run(text)
    assert type(sc.auto_section[0]).__name__ == "LegacyCmd"
    rt.run_auto()
    assert any("TraySetIcon" in entry and "no system tray" in entry
               for entry in rt.logs)
    assert not any(entry.startswith("raw:") for entry in rt.logs)


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


def test_strsplit_without_delimiter_splits_characters():
    sc, rt, sim = run(
        'for digit in StrSplit("12345678") {\nSend digit\n}\n')
    rt.run_auto()
    assert types(sim) == list("12345678")


def test_condition_call_with_assignment_inside_args():
    # A call containing `x := 1` must not be mistaken for a top-level
    # comparison; that bug made HashFile DllCall conditions evaluate as
    # strings and throw OSError before the crypto call ran.
    sc, rt, sim = run(
        'F(v) {\n'
        '    return 1\n'
        '}\n'
        'if !F(x := 1)\n'
        '    Send "bad"\n'
        'else\n'
        '    Send "ok"\n')
    rt.run_auto()
    assert types(sim) == ["ok"]
    assert rt.vars["x"] == 1


def test_bitwise_and_hex_literals():
    sc, rt, sim = run(
        'x := (222 & 0xff)\n'
        'y := Format("{:02x}", 0xde)\n'
        'z := 1 << 3 | 1\n'
        'Send x "|" y "|" z\n')
    rt.run_auto()
    assert types(sim) == ["222|de|9"]


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


def test_bind_builtin_freezes_args_and_calls_later():
    # Natro builds `petalQuestDisclaimer := Msgbox.Bind(...)` and calls it
    # on demand, exactly like a BoundFunc in AHK v2.
    _sc, rt, _sim = run(
        'petalQuestDisclaimer := MsgBox.Bind("petal warning")\n'
        'petalQuestDisclaimer()\n')
    rt.run_auto()
    assert "MsgBox: petal warning" in rt.logs


def test_bind_user_function_prepends_frozen_args():
    _sc, rt, sim = run(
        "Tag(prefix, value) {\n"
        "    Send prefix value\n"
        "}\n"
        'tagged := Tag.Bind("id:")\n'
        'tagged("seven")\n')
    rt.run_auto()
    assert types(sim) == ["id:seven"]


def test_bind_quoted_string_is_not_a_function_reference():
    _sc, rt, _sim = run('f := "MsgBox".Bind("x")\n')
    rt.run_auto()
    assert "method .bind() unsupported (logged)" in rt.logs


def test_default_params_apply_and_override():
    _sc, rt, sim = run(
        "Add(a, b := 10) {\n"
        "    Send b\n"
        "}\n"
        "Add(5)\n"
        "Add(5, 2)\n")
    rt.run_auto()
    assert types(sim) == ["10", "2"]


def test_default_param_may_reference_earlier_param():
    _sc, rt, sim = run(
        "Echo(a, b := a) {\n"
        "    Send b\n"
        "}\n"
        "Echo(7)\n")
    rt.run_auto()
    assert types(sim) == ["7"]


def test_unset_default_keeps_param_unset():
    _sc, rt, sim = run(
        "Probe(a, b := unset) {\n"
        "    Send IsSet(b)\n"
        "}\n"
        "Probe(1)\n"
        "Probe(1, 2)\n")
    rt.run_auto()
    assert types(sim) == ["0", "1"]


def test_class_brace_on_same_line_and_static_dispatch():
    _sc, rt, sim = run(
        "class MathKit {\n"
        "    static Double(n) {\n"
        "        return n * 2\n"
        "    }\n"
        "}\n"
        "result := MathKit.Double(21)\n"
        "Send result\n")
    rt.run_auto()
    assert any(line.startswith("class MathKit") for line in rt.logs)
    assert types(sim) == ["42"]


def test_instance_method_is_not_dispatched_as_static():
    _sc, rt, _sim = run(
        "class Kit {\n"
        "    Thing() {\n"
        "        return 1\n"
        "    }\n"
        "}\n"
        "x := Kit.Thing()\n")
    rt.run_auto()
    assert "method .thing() unsupported (logged)" in rt.logs


def test_dynamic_dispatch_name_resolves_var_case_insensitively():
    # Another function may have created the key with different casing; the
    # `%c%` substitution must still find it (AHK variables are case-blind).
    _sc, rt, sim = run(
        "C := 2\n"
        "nm_Tab%c%()\n"
        "nm_Tab2() {\n"
        '    Send "dynamic"\n'
        "}\n")
    rt.run_auto()
    assert types(sim) == ["dynamic"]


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
        "    global handledMode, handledMsg\n"
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


def test_fileopen_rawread_and_pos(tmp_path):
    base = str(tmp_path).replace("\\", "/")
    (tmp_path / "raw.bin").write_bytes(bytes([0xDE, 0xAD, 0xBE, 0xEF]))
    sc, rt, sim = run(
        f'f := FileOpen("{base}/raw.bin", "r")\n'
        'buf := Buffer(4, 0)\n'
        'n := f.RawRead(buf, 4)\n'
        'first := NumGet(buf, 0, "UChar")\n'
        "f.Pos := 0\n"
        'n2 := f.RawRead(buf, 2)\n'
        'second := NumGet(buf, 1, "UChar")\n'
        "f.Close()\n")
    rt.run_auto()
    assert rt.vars["n"] == 4
    assert rt.vars["first"] == 0xDE
    assert rt.vars["n2"] == 2
    assert rt.vars["second"] == 0xAD


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


def test_windows_case_insensitive_file_lookup(tmp_path):
    # Natro builds `paths/gtc-windshrine.ahk` from config, but the file is
    # stored as `gtc-WindShrine.ahk`. Windows resolves that; Linux must
    # mimic the case-insensitive, case-preserving lookup.
    base = str(tmp_path)
    (tmp_path / "paths").mkdir()
    (tmp_path / "paths" / "gtc-WindShrine.ahk").write_text(
        'loaded := "wind"', encoding="utf-8")
    (tmp_path / "patterns").mkdir()
    (tmp_path / "patterns" / "CornerXSnake.ahk").write_bytes(b"x")
    text = (
        f'f := FileOpen("{base}\\paths\\gtc-windshrine.ahk", "r")\n'
        'content := f.Read(), f.Close()\n'
        f'Send FileExist("{base}\\PATHS\\GTC-windshrine.AHK")\n'
        f'Send FileExist("{base}\\patterns\\cornerxsnake.ahk")\n'
        f'Send FileExist("{base}\\paths\\gtc-missing.ahk")\n'
        'Send content\n'
    )
    sc, rt, sim = run(text, working_dir=base)
    rt.run_auto()
    assert types(sim) == ["A", "A", 'loaded := "wind"']
    assert not any("FileOpen failed" in entry for entry in rt.logs)


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


def test_array_length_default_and_capacity_properties():
    # AHK v2 arrays expose Length/Capacity/Default as assignable properties.
    # Natro pads fixed-size arrays (Length := 20) and defines Default := ""
    # so the valueless slots read as blank instead of erroring.
    _sc, rt, _sim = run(
        'a := ["Buff", "Kill"]\n'
        'a.Default := ""\n'
        "a.Length := 4\n"
        "n := a.Length\n"
        "a1 := a[1]\n"
        "a3 := a[3]\n"
        "h3 := a.Has(3)\n"
        "a.Length := 1\n"
        "tn := a.Length\n"
        'b := ["x"]\n'
        "b.Default := 7\n"
        "b.Length := 3\n"
        "b2 := b[2]\n"
        'c := ["a", "b", "c"]\n'
        "c.Capacity := 2\n"
        "cn := c.Length\n"
        'd := []\n'
        'd.Default := ""\n'
        "d.Length := 2\n"
        'd[2] := "tail"\n'
        "d1 := d[1]\n"
        "d2 := d[2]\n"
        "joined := \"\"\n"
        "for v in d\n"
        "    joined .= v\n"
    )
    rt.run_auto()
    assert rt.vars["n"] == 4
    assert rt.vars["a1"] == "Buff"
    assert rt.vars["a3"] == ""
    assert rt.vars["h3"] == 0
    assert rt.vars["tn"] == 1
    assert rt.vars["b2"] == 7
    assert rt.vars["cn"] == 2
    assert rt.vars["d1"] == ""
    assert rt.vars["d2"] == "tail"
    assert rt.vars["joined"] == "tail"
    assert not any("cannot store into list" in line
                   or "assign-target" in line for line in rt.logs)


def test_mondo_action_list_array_properties_apply_in_build_statement():
    # Verbatim Natro build statement: the comma-separated assignments must
    # run against the same array without logging an assign-target failure.
    _sc, rt, _sim = run(
        "PMondoGuid := 0\n"
        'MondoActionList := ["Buff", "Kill"], PMondoGuid && '
        'MondoActionList.Push("Tag", "Guid"), MondoActionList.Default := "", '
        "MondoActionList.Length := 4\n"
        "n := MondoActionList.Length\n"
        "last := MondoActionList[4]\n"
    )
    rt.run_auto()
    assert rt.vars["n"] == 4
    assert rt.vars["last"] == ""
    assert not any("assign-target" in line for line in rt.logs)


def test_array_delete_leaves_a_valueless_index():
    # AHK Array.Delete does not shift; it leaves the index without a value,
    # so Length stays and reads fall back to Default.
    _sc, rt, _sim = run(
        'a := ["a", "b", "c"]\n'
        'a.Default := "?"\n'
        "removed := a.Delete(2)\n"
        "n := a.Length\n"
        "second := a[2]\n"
        "h := a.Has(2)\n"
        "third := a[3]\n"
    )
    rt.run_auto()
    assert rt.vars["removed"] == "b"
    assert rt.vars["n"] == 3
    assert rt.vars["second"] == "?"
    assert rt.vars["h"] == 0
    assert rt.vars["third"] == "c"


def test_negative_array_indexes_address_from_the_end():
    _sc, rt, _sim = run(
        'a := ["a", "b", "c"]\n'
        "last := a[-1]\n"
        "second := a[-2]\n"
        'a[-1] := "z"\n'
        "changed := a[3]\n"
        "h := a.Has(-1)\n"
        "removed := a.RemoveAt(-1)\n"
        "n := a.Length\n"
        'a.InsertAt(-1, "y")\n'
        "i1 := a[1]\n"
        "i2 := a[2]\n"
        "i3 := a[3]\n"
    )
    rt.run_auto()
    assert rt.vars["last"] == "c"
    assert rt.vars["second"] == "b"
    assert rt.vars["changed"] == "z"
    assert rt.vars["h"] == 1
    assert rt.vars["removed"] == "z"
    assert rt.vars["n"] == 2
    assert rt.vars["i1"] == "a"
    assert rt.vars["i2"] == "y"
    assert rt.vars["i3"] == "b"


def test_push_insertat_and_map_set_accept_multiple_values():
    # Natro's Mondo build pushes "Tag", "Guid" in one call; AHK v2 collection
    # methods take variadic values.
    _sc, rt, _sim = run(
        "a := []\n"
        'n := a.Push("Tag", "Guid")\n'
        "first := a[1]\n"
        "second := a[2]\n"
        "m := Map()\n"
        'm.Set("a", 1, "b", 2)\n'
        "mc := m.Count\n"
        "ins := [1]\n"
        'ins.InsertAt(1, "x", "y")\n'
        "i1 := ins[1]\n"
        "i2 := ins[2]\n"
        "i3 := ins[3]\n"
        "tail := []\n"
        'tail.InsertAt(0, "end")\n'
        "t1 := tail[1]\n"
    )
    rt.run_auto()
    assert rt.vars["n"] == 2
    assert rt.vars["first"] == "Tag"
    assert rt.vars["second"] == "Guid"
    assert rt.vars["mc"] == 2
    assert rt.vars["i1"] == "x"
    assert rt.vars["i2"] == "y"
    assert rt.vars["i3"] == 1
    assert rt.vars["t1"] == "end"


def test_map_default_and_count_properties_stay_out_of_key_space():
    # Natro's digit readers do `(digits := Map()).Default := ""` and then
    # branch on digits.Count; neither the Default nor Count property may
    # become a map key.
    _sc, rt, _sim = run(
        "m := Map()\n"
        'm.Default := ""\n'
        "c0 := m.Count\n"
        'm[1] := "a"\n'
        "c1 := m.Count\n"
        "blank := m[2]\n"
        'm.Default := 0\n'
        "zero := m[9]\n"
        "missing := m.Get(7)\n"
        'defined := m.Get(7, "fallback")\n'
    )
    rt.run_auto()
    assert rt.vars["c0"] == 0
    assert rt.vars["c1"] == 1
    assert rt.vars["blank"] == ""
    assert rt.vars["zero"] == 0
    assert rt.vars["missing"] == 0
    assert rt.vars["defined"] == "fallback"


def test_map_casesense_off_resolves_string_keys_case_insensitively():
    _sc, rt, _sim = run(
        "m := Map(), m.CaseSense := 0\n"
        'm["Boost"] := 1\n'
        'found := m["boost"]\n'
        'has := m.Has("BOOST")\n'
        'm["BOOST"] := 2\n'
        "n := m.Count\n"
        "cs := m.CaseSense\n"
        'entry := ""\n'
        "for k, v in m\n"
        "    entry .= k v\n"
        'g := m.Get("bOoSt")\n'
        "f := Map()\n"
        "f.CaseSense := false\n"
        'f["X"] := 1\n'
        'fx := f["x"]\n'
    )
    rt.run_auto()
    assert rt.vars["found"] == 1
    assert rt.vars["has"] == 1
    assert rt.vars["n"] == 1
    assert rt.vars["cs"] == "Off"
    assert rt.vars["entry"] == "Boost2"
    assert rt.vars["g"] == 2
    assert rt.vars["fx"] == 1


def test_map_clone_preserves_default_and_casesense():
    _sc, rt, _sim = run(
        "src := Map()\n"
        "src.CaseSense := 0\n"
        'src.Default := "?"\n'
        'src["Key"] := 1\n'
        "copy := src.Clone()\n"
        'got := copy["key"]\n'
        'miss := copy["nope"]\n'
        "n := copy.Count\n"
    )
    rt.run_auto()
    assert rt.vars["got"] == 1
    assert rt.vars["miss"] == "?"
    assert rt.vars["n"] == 1


def test_static_map_continuation_with_inline_comments_enumerates():
    # Natro's path_names table spans physical lines and carries `;` comments
    # after some entries.  Comments must be dropped per physical line while
    # joining; otherwise the first `;` truncates the whole Map() initializer.
    _sc, rt, sim = run(
        "static path_names := Map(\n"
        '    "gtb", ["blue", "mountain"], ; go to (field) booster\n'
        '    "br", ["red"], ; other\n'
        ")\n"
        "for k, v in path_names {\n"
        "    Send k\n"
        "    Send v[1]\n"
        "}\n")
    rt.run_auto()
    assert types(sim) == ["gtb", "blue", "br", "red"]


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


def test_loop_files_v2_specials_and_fileopen_by_path(tmp_path, monkeypatch):
    """Natro's pattern importer opens A_LoopFilePath, not the v1 name."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "sample.ahk"
    target.write_text("hello")
    info = target.stat()
    sc, rt, sim = run(
        'Loop Files "*.ahk" {\n'
        '    path := A_LoopFilePath\n'
        '    full := A_LoopFileFullPath\n'
        '    size := A_LoopFileSize\n'
        '    kb := A_LoopFileSizeKB\n'
        '    modified := A_LoopFileTimeModified\n'
        '    created := A_LoopFileTimeCreated\n'
        '    short := A_LoopFileShortName\n'
        '    attrib := A_LoopFileAttrib\n'
        '    f := FileOpen(A_LoopFilePath, "r")\n'
        '    content := f.Read()\n'
        '    f.Close()\n'
        '}\n')
    rt.run_auto()
    assert rt.vars["path"] == str(target)
    assert rt.vars["full"] == str(target)
    assert rt.vars["size"] == 5
    assert rt.vars["kb"] == 0
    assert rt.vars["modified"] == time.strftime(
        "%Y%m%d%H%M%S", time.localtime(info.st_mtime))
    birth = getattr(info, "st_birthtime", None)
    assert rt.vars["created"] == (
        time.strftime("%Y%m%d%H%M%S", time.localtime(birth)) if birth else "")
    assert rt.vars["short"] == ""
    assert rt.vars["attrib"] == ""
    assert rt.vars["content"] == "hello"
    assert not any("FileOpen failed" in line for line in rt.logs), rt.logs


def test_deref_and_a_index():
    sc, rt, sim = run('i := 2\nPlanterName2 := "ok"\nSend PlanterName%i%\nLoop 2 {\nSend "{A_Index}"\n}\n')
    rt.run_auto()
    assert types(sim) == ["ok", "1", "2"]


def test_variable_names_are_case_insensitive():
    # Natro mixes the built-in `A_Index` and legacy `A_index` spellings in
    # dynamic variable references (BlenderItem%A_index%).
    sc, rt, sim = run(
        'BlenderItem1 := "None"\n'
        "Loop 1 {\n"
        "value := BlenderItem%A_index%\n"
        "Send value\n"
        "}\n")
    rt.run_auto()
    assert types(sim) == ["None"]


def test_substr_instr_strlen():
    sc, rt, sim = run('s := "hello"\nSend SubStr(s, 2, 3)\nSend "{InStr(s, \'l\')}"\nSend "{StrLen(s)}"\n')
    rt.run_auto()
    assert types(sim) == ["ell", "3", "5"]
