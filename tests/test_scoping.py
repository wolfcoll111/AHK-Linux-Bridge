"""AHK v2 function scope: locals are per call, globals/statics persist."""
from __future__ import annotations

from ahk_bridge import runtime as R
from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script


def run(text, **kw):
    sc = parse_script(text)
    sim = DryBackend()
    rt = R.Runtime(sc, sim, **kw)
    return sc, rt, sim


def types(sim):
    return [e[1] for e in sim.log if e[0] == "type"]


def test_function_locals_do_not_leak_between_calls():
    text = (
        "Build() {\n"
        '    out .= "a"\n'
        "    buf := out\n"
        "    return buf\n"
        "}\n"
        "first := Build()\n"
        "second := Build()\n"
        'Send first "|" second\n'
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["a|a"]
    assert "out" not in rt.vars
    assert "buf" not in rt.vars


def test_declared_global_mutation_persists_across_calls():
    text = (
        "counter := 0\n"
        "Bump(step) {\n"
        "    global counter\n"
        "    counter += step\n"
        "    return counter\n"
        "}\n"
        "Bump(2)\n"
        "Bump(3)\n"
        'Send "n=" counter\n'
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["n=5"]
    assert rt.vars.get("counter") == 5


def test_global_with_initializer_declares_and_assigns():
    text = (
        "flag := 0\n"
        "Enable(value) {\n"
        "    global flag := value\n"
        "    return flag\n"
        "}\n"
        "got := Enable(9)\n"
        "Send got flag\n"
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert rt.vars.get("flag") == 9
    assert types(sim) == ["99"]


def test_bare_global_makes_function_variables_global():
    text = (
        "g := 0\n"
        "SetAll() {\n"
        "    global\n"
        '    g := 7\n'
        '    scratch := "kept"\n'
        "}\n"
        "SetAll()\n"
        'Send g "|" scratch\n'
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["7|kept"]
    assert rt.vars.get("scratch") == "kept"


def test_static_variables_persist_between_calls_only():
    text = (
        "NextID() {\n"
        "    static n := 0\n"
        "    n += 1\n"
        "    return n\n"
        "}\n"
        "a := NextID()\n"
        "b := NextID()\n"
        'Send a "|" b\n'
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["1|2"]
    assert "n" not in rt.vars


def test_static_initializer_runs_on_first_execution_only():
    text = (
        "Picker() {\n"
        '    static items := ["a", "b"], i := 0\n'
        "    i += 1\n"
        "    return items[i]\n"
        "}\n"
        "first := Picker()\n"
        "second := Picker()\n"
        "Send first second\n"
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["ab"]


def test_parameters_are_restored_after_calls():
    text = (
        'x := "outer"\n'
        "Touch(x) {\n"
        '    x .= "!"\n'
        "    return x\n"
        "}\n"
        'y := Touch("inner")\n'
        'Send x "|" y\n'
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["outer|inner!"]
    assert rt.vars.get("x") == "outer"


def test_nested_call_declared_global_survives_enclosing_call():
    text = (
        "shared := 1\n"
        "Inner() {\n"
        "    global shared\n"
        "    shared := 42\n"
        "}\n"
        "Outer() {\n"
        "    temp := 0\n"
        "    Inner()\n"
        "    return temp\n"
        "}\n"
        "Outer()\n"
        "Send shared\n"
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["42"]
    assert rt.vars.get("shared") == 42
    assert "temp" not in rt.vars


def test_nested_function_assigns_captured_outer_local():
    # Natro's hashDefaults() is nested in nm_importPatterns() and assigns the
    # outer local installedPatternHashes.  AHK v2 nested functions are
    # closures; the outer variable must see the inner assignment.
    text = (
        "Outer() {\n"
        "    captured := 0\n"
        "    Inner() {\n"
        "        captured := 42\n"
        "        temp := 7\n"
        "    }\n"
        "    Inner()\n"
        "    return captured\n"
        "}\n"
        "value := Outer()\n"
        "Send value\n"
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["42"]
    assert rt.vars.get("value") == 42
    assert "temp" not in rt.vars
    assert "captured" not in rt.vars


def test_nested_function_does_not_capture_unrelated_temporary():
    text = (
        "Outer() {\n"
        "    Inner() {\n"
        '        scratch := "inner"\n'
        "        return scratch\n"
        "    }\n"
        "    first := Inner()\n"
        "    second := Inner()\n"
        '    return first "|" second\n'
        "}\n"
        "value := Outer()\n"
        "Send value\n"
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["inner|inner"]
    assert "scratch" not in rt.vars


def test_nested_function_inherits_assume_global():
    # Docs: nested functions of an assume-global function behave as
    # assume-global by default; GuiClose in Natro's add-planter dialog relies
    # on this when it assigns AddGui.
    text = (
        "g := 0\n"
        "Outer() {\n"
        "    global\n"
        "    Inner() {\n"
        "        g := 5\n"
        "    }\n"
        "    Inner()\n"
        "}\n"
        "Outer()\n"
        "Send g\n"
    )
    _sc, rt, sim = run(text)
    rt.run_auto()
    assert types(sim) == ["5"]
    assert rt.vars.get("g") == 5
