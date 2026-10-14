"""v0.2 feature tests: If/Else, Break/Continue, arithmetic, Loop var,
Random(), {Key} send-sequences, Sleep jitter, region pixel search."""
from ahk_bridge.parser import parse_script
from ahk_bridge import runtime as R
from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge import pixels as px


def run(text, **kw):
    sc = parse_script(text)
    sim = DryBackend()
    rt = R.Runtime(sc, sim, **kw)
    return sc, rt, sim


def types(sim):
    return [e[1] for e in sim.log if e[0] == "type"]


def keys(sim):
    return [(e[1], e[2]) for e in sim.log if e[0] == "key"]


def test_if_else_true_branch():
    sc, rt, sim = run('x := 5\nIf x > 3 {\nSend "big"\n} Else {\nSend "small"\n}\n')
    rt.run_auto()
    assert types(sim) == ["big"]


def test_if_else_false_branch():
    sc, rt, sim = run('x := 1\nIf x > 3 {\nSend "big"\n} Else {\nSend "small"\n}\n')
    rt.run_auto()
    assert types(sim) == ["small"]


def test_arithmetic_assign():
    sc, rt, sim = run('a := 2 + 3 * 4\nb := a + 1\nSend "{b}"\n')
    rt.run_auto()
    assert rt.vars["a"] == 14
    assert rt.vars["b"] == 15


def test_counter_loop_with_var():
    sc, rt, sim = run('n := 3\nLoop n {\nSend "x"\n}\n')
    rt.run_auto()
    assert types(sim) == ["x", "x", "x"]


def test_break_stops_loop():
    sc, rt, sim = run('Loop 10 {\nSend "a"\nBreak\nSend "b"\n}\n')
    rt.run_auto()
    assert types(sim) == ["a"]


def test_continue_skips_rest():
    sc, rt, sim = run('i := 0\nLoop 3 {\ni := i + 1\nIf i == 2 {\nContinue\n}\nSend "s"\n}\n')
    rt.run_auto()
    assert rt.vars["i"] == 3
    assert types(sim) == ["s", "s"]


def test_random_in_range():
    sc, rt, sim = run('x := Random(1, 6)\n', seed=42)
    rt.run_auto()
    assert 1 <= rt.vars["x"] <= 6


def test_special_key_send():
    sc, rt, sim = run('Send "hi{Enter}"\n')
    rt.run_auto()
    assert "hi" in types(sim)
    assert ("Enter", None) in keys(sim)


def test_sleep_var_resolution():
    sc, rt, sim = run('d := 50\nSleep d\n')
    rt.run_auto()
    assert ("sleep", 50) in [(e[0], e[1]) for e in sim.log]


def test_jitter_keeps_sleep_nonnegative():
    sc, rt, sim = run('Sleep 100\n', jitter=1.0, seed=1)
    rt.run_auto()
    sleeps = [e[1] for e in sim.log if e[0] == "sleep"]
    assert len(sleeps) == 1 and 0 <= sleeps[0] <= 200


def test_region_search():
    # 3x1: black, red, black -> red at (1,0); region excluding x=1 finds nothing
    buf = bytes([0, 0, 0, 255, 0, 0, 0, 0, 0])
    assert px.find_color_in_region(buf, 3, 1, (255, 0, 0), 0, 0, 2, 0) == (1, 0)
    assert px.find_color_in_region(buf, 3, 1, (255, 0, 0), 0, 0, 0, 0) is None
    assert px.find_color_in_region(buf, 3, 1, (255, 0, 0), 2, 0, 0, 0) is None


def test_while_counter_increments():
    sc, rt, sim = run('i := 0\nWhile i < 3 {\nSend "t"\ni := i + 1\n}\n')
    rt.run_auto()
    assert rt.vars["i"] == 3
    assert types(sim) == ["t", "t", "t"]
