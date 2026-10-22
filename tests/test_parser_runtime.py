from ahk_bridge.parser import parse_logical_lines, parse_script
from ahk_bridge import runtime as R
from ahk_bridge.backends.dry_backend import DryBackend


def run(text, **kw):
    sc = parse_script(text)
    sim = DryBackend()
    rt = R.Runtime(sc, sim, **kw)
    return sc, rt, sim


def test_hotkey_and_loop():
    sc, rt, sim = run('F1::\n{\nSend "hi"\nLoop 3 {\nClick\nSleep 10\n}\n}\n')
    assert len(sc.hotkeys) == 1 and sc.hotkeys[0].key == "F1"
    assert rt.fire_hotkey("F1")
    kinds = [e[0] for e in sim.log]
    assert kinds.count("click") == 3 and kinds.count("sleep") == 3


def test_single_line_hotkey_and_hotstring():
    sc, rt, sim = run('F2::Send "yo"\n:*:btw::by the way\n')
    assert rt.fire_hotkey("f2")
    assert ("type", "yo") in [(e[0], e[1]) for e in sim.log]
    assert rt.expand_hotstring("btw")


def test_while_and_vars():
    sc, rt, sim = run('i := 0\nWhile i < 3 {\nSend "{i}"\ni := 5\n}\n')
    rt.run_auto()
    assert rt.vars["i"] == 5


def test_functions():
    sc, rt, sim = run('Farm() {\nSend "farm"\n}\nFarm()\n')
    rt.run_auto()
    assert ("type", "farm") in [(e[0], e[1]) for e in sim.log]


def test_abort_stops_loop():
    sc, rt, sim = run('Loop {\nSend "x"\n}\n')
    rt.abort()
    try:
        rt.run_auto()
        assert False, "should abort"
    except R.Aborted:
        pass


def test_block_arrow_function_does_not_leak_enclosing_body():
    # HashFile defines HCRYPTPROV() => { ... } inside HashFile.  The arrow
    # body's closing brace used to close HashFile itself, spilling the rest
    # of the function into the auto-execute section.
    text = (
        "Foo() {\n"
        "  x := 1\n"
        "  Bar() => {\n"
        "    ptr: 0,\n"
        '    __delete: this => MsgBox("x")\n'
        "  }\n"
        "  y := 2\n"
        "  if y\n"
        "    z := 3\n"
        "}\n"
        "After() {\n"
        "  return 1\n"
        "}\n"
    )
    sc = parse_script(text)
    assert sc.auto_section == []
    assert "After" in sc.functions
    assert [type(n).__name__ for n in sc.functions["Foo"].body] == [
        "Assign", "FuncDef", "Assign", "If"]
    assert sc.functions["Foo"].body[1].name == "Bar"


def test_block_arrow_function_is_hoisted_for_includes():
    sc = parse_logical_lines([
        "Foo() {",
        "  Bar() => {",
        "    return 7",
        "  }",
        "}",
        "x := Bar()",
    ])
    assert "Bar" in sc.functions
    assert sc.functions["Bar"].body[0].value == "7"


def test_leading_dot_continuation_tracks_open_parentheses():
    # Natro's startup message has `. (cond ? "Enabled (" lang ")" : ...)`
    # split across lines.  The leading `.` used to append the line without
    # noticing the open paren, so the following `:` branch became a raw
    # top-level statement and `Enabled (lang)` looked like a builtin call.
    text = (
        "flag := 1\n"
        'msg := "head"\n'
        '\t. (flag ? "Enabled (" flag ")"\n'
        '\t\t: "Disabled")\n'
        "Send msg\n"
    )
    sc, rt, sim = run(text)
    rt.run_auto()
    assert [e[1] for e in sim.log if e[0] == "type"] == ["headEnabled (1)"]


def test_sleep_call_syntax_is_not_a_legacy_noop():
    # `Sleep(100)` is a function call in AHK v2.  The legacy-command regex
    # used to eat the parenthesized argument and the runtime logged a no-op,
    # so path scripts never actually paused.
    sc, rt, sim = run('Sleep(150), x := 1\n')
    assert type(sc.auto_section[0]).__name__ == "Seq"
    assert type(sc.auto_section[0].items[0]).__name__ == "FuncCall"
    rt.run_auto()
    assert ("sleep", 150) in sim.log
    assert rt.vars["x"] == 1


def test_comma_separated_statements_keep_map_targets_alive():
    # Natro initializes maps with `settings := Map(), settings.CaseSense := 0`.
    # Parsing that as one assignment made `settings` a string, so every
    # later `settings[...] := ...` failed with "cannot store into str".
    text = (
        "settings := Map(), settings.CaseSense := 0\n"
        'settings["x"] := 1\n'
        "bitmaps := Map(), bitmaps.CaseSense := 0\n"
        'bitmaps["day"] := Map("ant", 2)\n'
    )
    sc, rt, sim = run(text)
    assert type(sc.auto_section[0]).__name__ == "Seq"
    rt.run_auto()
    assert rt.vars["settings"]["x"] == 1
    assert rt.vars["bitmaps"]["day"]["ant"] == 2


def test_object_literal_commas_are_not_statement_separators():
    sc, rt, sim = run('x := {a: 1, b: 2}\n')
    assert type(sc.auto_section[0]).__name__ == "Assign"
    assert sc.auto_section[0].value == "{a: 1, b: 2}"


def test_braceless_if_does_not_steal_enclosing_else():
    # Regression: `if atHive()` on its own line followed by `} else {`
    # used to attach the outer else to the braceless if and swallow the
    # enclosing block's closing brace. In Natro's nm_Reset that consumed
    # ~550 lines including the following function definitions.
    text = (
        "outer() {\n"
        "  flag := 0\n"
        "  if flag {\n"
        "    loop 1 {\n"
        "      if false\n"
        "        x := 1\n"
        "    }\n"
        "  } else {\n"
        "    y := 2\n"
        "  }\n"
        "}\n"
        "after() {\n"
        "  return 1\n"
        "}\n"
        "outer()\n"
    )
    sc, rt, sim = run(text)
    assert "outer" in sc.functions
    assert "after" in sc.functions
    outer_if = sc.functions["outer"].body[1]
    inner_loop = outer_if.then_body[0]
    assert inner_loop.body[0].else_body == []      # braceless if has no else
    assert len(outer_if.else_body) == 1            # else belongs to the outer if
    rt.run_auto()
    assert rt.vars.get("y") == 2
