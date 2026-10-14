"""Dry-run backend: records events, used for tests / --check / headless CI."""
from __future__ import annotations
import time


class DryBackend:
    name = "dry"

    def __init__(self):
        self.log: list[tuple] = []

    def send_key(self, key: str, down: bool | None = None):
        self.log.append(("key", key, down))

    def type_text(self, text: str):
        self.log.append(("type", text))

    def move_mouse(self, x: int, y: int, absolute: bool = True):
        self.log.append(("move", x, y, absolute))

    def click(self, button="left", count=1, x=None, y=None):
        self.log.append(("click", button, count, x, y))

    def sleep_ms(self, ms: int):
        self.log.append(("sleep", ms))

    def close(self):
        pass
