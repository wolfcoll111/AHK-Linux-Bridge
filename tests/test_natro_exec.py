"""v0.3 batch-2/3: Natro field-test fixes.

Covers the bugs real NatroMacro code exposed, each verified against an
independent oracle before locking in:
- `if (x) {` misparsed as FuncDef named 'if' (keyword guard)
- trailing `;` comments on block openers (`loop 2 { ;Click tile`)
- `if(`/`else if(`/`while(` with no space after the keyword
- Allman `Else If` (brace on next line), bare `} Else`, `else <stmt>`
- `break 2` / `continue 2` levels across nested loops
- `try switch x {` compound after try
- `loop { } until cond` do-until (+ `do` form)
- `Loop {` infinite (brace must not parse as the count)
- `a.b(), c.d()` comma-Sequels (not method chains)
- N-ary `A && B && C` statement guards
- `||` / `&&` and comparisons / `~=` in VALUE position
- `**` power, Floor/Ceil/Sqrt, numeric-string coercion ("00" * 3600 == 0)
- `class` + Allman methods + `static x := v`
- switch `, 0` CaseSense flag strip
"""
from ahk_bridge.parser import parse_script
from ahk_bridge import runtime as R
from ahk_bridge.backends.dry_backend import DryBackend


def run(text, **kw):
    sc = parse_script(text)
    sim = DryBackend()
    return sc, R.Runtime(sc, sim, **kw), sim


def types(sim):
    return [e[1] for e in sim.log if e[0] == "type"]


def test_if_not_funcdef():
    sc, _, _ = run('If (whichFX=1) {\nFXsize := 8\n}\n')
    assert len(sc.functions) == 0
    assert type(sc.auto_section[0]).__name__ == "If"


def test_trailing_comment_openers():
    sc, rt, sim = run('Loop 2 { ;Click tile\nSend "x"\n}\n')
    rt.run_auto()
    assert types(sim) == ["x", "x"]


def test_if_no_space():
    sc, rt, sim = run('x := 1\nif(x = 1){\nSend "hit"\n}\n')
    rt.run_auto()
    assert types(sim) == ["hit"]


def test_allman_else_if_chain():
    t = ('If (a=1)\n{\nSend "one"\n}'
         '\nElse If (a=2)\n{\nSend "two"\n}'
         '\nElse If (a=3)\n{\nSend "three"\n}\n')
    sc, rt, sim = run('a := 3\n' + t)
    rt.run_auto()
    assert types(sim) == ["three"]


def test_bare_else_allman():
    sc, rt, sim = run('x := 0\nif (x) {\nSend "t"\n} Else\n{\nSend "f"\n}\n')
    rt.run_auto()
    assert types(sim) == ["f"]


def test_else_single_statement():
    sc, rt, sim = run('x := 0\nif (x) {\nSend "t"\n}\nelse throw Error("no")\n')
    try:
        rt.run_auto()
    except RuntimeError as e:
        assert str(e) == "no"
    else:
        raise AssertionError("throw did not fire")


def test_break_level_2():
    t = ('Loop 5 {\nSend "a"\nLoop 5 {\nSend "b"\nbreak 2\nSend "never"\n}\n'
         'Send "after"\n}\nSend "done"\n')
    _, rt, sim = run(t)
    rt.run_auto()
    assert types(sim) == ["a", "b", "done"]


def test_try_switch():
    t = ('x := 2\ntry switch x {\ncase 1:\nSend "one"\ncase 2:\nSend "two"\n}\n'
         'catch as e {\nSend "caught"\n}\n')
    _, rt, sim = run(t)
    rt.run_auto()
    assert types(sim) == ["two"]


def test_do_until_loop():
    _, rt, sim = run('n := 0\nloop {\nn += 1\n} until (n >= 3)\nSend n\n')
    rt.run_auto()
    assert rt.vars["n"] == 3
    assert types(sim) == ["3"]


def test_loop_brace_is_not_count():
    sc, rt, sim = run('n := 0\nLoop {\nn += 1\nif (n >= 2) {\nbreak\n}\n}\n')
    rt.run_auto()
    assert rt.vars["n"] == 2
    assert sc.auto_section[1].count is None


def test_comma_calls_are_seq():
    sc, rt, sim = run('points.RemoveAt(1), points.Pop()\n')
    rt.run_auto()
    assert type(sc.auto_section[0]).__name__ == "Seq"


def test_nary_and_chain():
    t = ('x := 1\ny := 1\nIsSet(x) && IsInteger(1) && (y > 0) && x := 42\n')
    _, rt, _ = run(t)
    rt.run_auto()
    assert rt.vars["x"] == 42


def test_logic_and_compare_as_values():
    _, rt, _ = run('a := (1 = 1) || (2 = 3)\nb := (1 = 2) && (3 = 3)\n'
                   'c := ("abc" ~= "^a")\nd := 60**(2-1)\n')
    rt.run_auto()
    assert (rt.vars["a"], rt.vars["b"], rt.vars["c"], rt.vars["d"]) == (1, 0, 1, 60)


def test_numeric_string_coercion():
    _, rt, _ = run('x := "00"*3600\ny := Floor(2.7)\nz := Sqrt(16)\n')
    rt.run_auto()
    assert rt.vars["x"] == 0
    assert rt.vars["y"] == 2
    assert rt.vars["z"] == 4.0


def test_class_allman_methods():
    t = ('class C\n{\nstatic v := 42\nfoo() {\nSend "in-foo"\n}\n}\nSend "after"\n')
    sc, rt, sim = run(t)
    rt.run_auto()
    assert rt.vars["v"] == 42
    assert "foo" in rt.script.functions
    assert types(sim) == ["after"]


def test_switch_casesense_flag_stripped():
    sc, _, _ = run('switch params[2], 0\n{\ncase 1:\nSend "one"\n}\n')
    assert sc.auto_section[0].value == "params[2]"


def test_natro_planter_math_oracle():
    t = ('times := StrSplit("1:30:00", ":")\ntime_delta := 0\n'
         'Loop (m := Min(times.Length, 3))\n{\n'
         '    if ((times[A_Index] ~= "i)^[0-9]+$") && '
         '(times[A_Index] < 24*(3600/(60**(A_Index-1)))))\n'
         '        time_delta += times[A_Index]*(60**(A_Index-1))\n}\n')
    _, rt, _ = run(t)
    rt.run_auto()
    assert rt.vars["time_delta"] == 1 + 30 * 60


def test_dangling_else_attaches_outward():
    # `} else` after a self-closed inner block belongs to the OUTER if.
    t = ('x := 0\ny := 0\nif (x = 1) {\n'
         '    if (y = 1) {\n        y := 9\n    }\n'
         '} else {\n    x := 42\n}\n')
    sc, rt, _ = run(t)
    rt.run_auto()
    outer = sc.auto_section[2]
    assert type(outer).__name__ == "If"
    assert rt.vars["x"] == 42
    assert rt.vars["y"] == 0


def test_try_else_no_throw():
    _, rt, _ = run('x := 0\ntry\n    x := 1\ncatch\n    x := -1\nelse\n    x := 2\n')
    rt.run_auto()
    assert rt.vars["x"] == 2


def test_try_else_on_throw():
    _, rt, _ = run('x := 0\ntry {\n    throw Error("boom")\n} catch {\n'
                   '    x := -1\n} else {\n    x := 2\n}\n')
    rt.run_auto()
    assert rt.vars["x"] == -1
