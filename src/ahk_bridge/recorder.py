"""Macro recorder: capture -> JSON + AHK export. Capture needs evdev/XRecord (opt-in)."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict


@dataclass
class Event:
    t: str  # key|click|move|sleep
    ms: int = 0
    data: dict = field(default_factory=dict)


class Recorder:
    def __init__(self):
        self.events: list[Event] = []
        self._last = None

    def _gap(self) -> int:
        now = time.monotonic()
        if self._last is None:
            self._last = now
            return 0
        gap = int((now - self._last) * 1000)
        self._last = now
        return gap

    def key(self, key: str):
        self.events.append(Event("key", self._gap(), {"key": key}))

    def click(self, button="left", x=None, y=None):
        self.events.append(Event("click", self._gap(), {"button": button, "x": x, "y": y}))

    def move(self, x, y):
        self.events.append(Event("move", self._gap(), {"x": x, "y": y}))

    def to_json(self) -> str:
        return json.dumps([asdict(e) for e in self.events], indent=2)

    def to_ahk(self) -> str:
        out = ["#Requires AutoHotkey v2.0", "F1::", "{"]
        for e in self.events:
            if e.ms >= 50:
                out.append(f"    Sleep {e.ms}")
            if e.t == "key":
                out.append(f'    Send "{e.data["key"]}"')
            elif e.t == "click":
                x, y = e.data.get("x"), e.data.get("y")
                if x is not None:
                    out.append(f"    Click {x}, {y} {e.data.get('button', 'left')}")
                else:
                    out.append(f"    Click {e.data.get('button', 'left')}")
            elif e.t == "move":
                out.append(f"    MouseMove {e.data['x']}, {e.data['y']}")
        out.append("}")
        return "\n".join(out) + "\n"
