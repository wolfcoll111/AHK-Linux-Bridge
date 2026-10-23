"""OS integration behavior that does not touch the live desktop in tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ahk_bridge.backends.dry_backend import DryBackend
from ahk_bridge.parser import parse_script
from ahk_bridge.runtime import Runtime


def run(text):
    rt = Runtime(parse_script(text), DryBackend())
    return rt


def test_clipboard_read_becomes_a_clipboard_write(monkeypatch):
    import ahk_bridge.clipboard as cb

    writes = []
    monkeypatch.setattr(cb, "read_text", lambda: "from-system")
    monkeypatch.setattr(cb, "write_text", lambda text: writes.append(text) or True)
    rt = run(
        'initial := A_Clipboard\n'
        'A_Clipboard := "new value"\n'
        'after := A_Clipboard\n'
    )
    rt.run_auto()
    assert rt.vars["initial"] == "from-system"
    assert rt.vars["after"] == "new value"
    assert writes == ["new value"]


def test_clipboard_write_failure_is_logged_once(monkeypatch):
    import ahk_bridge.clipboard as cb

    monkeypatch.setattr(cb, "write_text", lambda text: False)
    rt = run(
        'A_Clipboard := "one"\n'
        'A_Clipboard := "two"\n'
    )
    rt.run_auto()
    assert rt.vars["A_Clipboard"] == "two"
    warnings = [e for e in rt.logs if "clipboard:" in e]
    assert len(warnings) == 1
