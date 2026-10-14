from ahk_bridge.parser import parse_script
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
