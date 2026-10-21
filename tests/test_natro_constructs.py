"""v0.3 Natro-driven constructs: switch, for, try, Loop Parse/Files, Map,
subscripts, ternary, compound-assign, Seq, fat-arrow, KeyWait, Ini, Throw."""
import os
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
