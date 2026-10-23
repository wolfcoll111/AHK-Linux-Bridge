"""Parser regressions for compact Natro/HashFile syntax."""
from ahk_bridge import runtime as R
from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script


def run(text):
    script = parse_script(text)
    sim = DryBackend()
    return R.Runtime(script, sim), sim


def types(sim):
    return [entry[1] for entry in sim.log if entry[0] == "type"]


def test_switch_inline_case_body():
    # HashFile.ahk uses `case 1: hash_alg := ...` on one line.
    rt, sim = run(
        'x := 2\n'
        'Switch x {\n'
        'Case 1: Send "one"\n'
        'Case 2: Send "two"\n'
        'Default: Send "other"\n'
        '}\n')
    rt.run_auto()
    assert types(sim) == ["two"]


def test_arrow_function_returns_object_literal():
    # HCRYPTPROV() => { ptr: 0, __delete: ... } returns a dict, not a block.
    rt, sim = run(
        'make() => {\n'
        '    name: "x", n: 3\n'
        '}\n'
        'o := make()\n'
        'a := o.name\n'
        'b := o.n\n'
        'Send a "|" b\n')
    rt.run_auto()
    assert types(sim) == ["x|3"]
