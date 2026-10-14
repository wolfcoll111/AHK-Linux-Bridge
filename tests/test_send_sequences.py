"""Send-sequence edge cases from real farming macros ({Blind}, mouse buttons,
named down/up, wheel)."""
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime
from ahk_bridge.backends.dry_backend import DryBackend


def run(text, **kw):
    sc = parse_script(text)
    sim = DryBackend()
    return Runtime(sc, sim, **kw), sim


def test_blind_prefix_stripped():
    rt, sim = run('Send "{Blind}hello"\n')
    rt.run_auto()
    assert ("type", "hello") in [(e[0], e[1]) for e in sim.log]
    assert not any("{Blind}" in str(e) for e in sim.log)


def test_lbutton_sends_click():
    rt, sim = run('Send "{LButton}"\n')
    rt.run_auto()
    assert ("click", "left", 1, None, None) in sim.log


def test_named_key_down_up():
    rt, sim = run('Send "{Enter down}{Enter up}"\n')
    rt.run_auto()
    keyed = [(e[1], e[2]) for e in sim.log if e[0] == "key"]
    assert ("Enter", True) in keyed and ("Enter", False) in keyed


def test_wheel_maps_to_scroll():
    rt, sim = run('Send "{WheelUp}"\n')
    rt.run_auto()
    assert ("scroll", 1, False) in sim.log


def test_mixed_text_and_keys_order():
    rt, sim = run('Send "go{Enter}now"\n')
    rt.run_auto()
    kinds = [e[0] for e in sim.log]
    assert kinds == ["type", "key", "type"]
    assert [e[1] for e in sim.log if e[0] == "type"] == ["go", "now"]
