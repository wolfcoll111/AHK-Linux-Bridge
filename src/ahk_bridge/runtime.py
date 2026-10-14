"""Executor with emergency abort. Runs parsed Script against InputSimulator."""
from __future__ import annotations
import re
import threading
import time
from . import parser as P

ABORT_KEYS = ("Escape", "Ctrl+Alt+C")


class Aborted(RuntimeError):
    pass


class Runtime:
    def __init__(self, script: P.Script, sim, abort_keys=ABORT_KEYS, max_loop=10_000):
        self.script = script
        self.sim = sim
        self.vars: dict = {}
        self.logs: list[str] = []
        self._abort = threading.Event()
        self.abort_keys = tuple(abort_keys)
        self.max_loop = max_loop  # safety cap for infinite loops in tests

    # -- abort --
    def abort(self):
        self._abort.set()

    @property
    def aborted(self):
        return self._abort.is_set()

    def _check(self):
        if self._abort.is_set():
            raise Aborted("aborted via master kill-switch")

    # -- entry points --
    def run_auto(self):
        self._exec_block(self.script.auto_section)

    def fire_hotkey(self, key: str):
        for hk in self.script.hotkeys:
            if hk.key.lower() == key.lower():
                self._exec_block(hk.body)
                return True
        return False

    def expand_hotstring(self, trigger: str):
        for hs in self.script.hotstrings:
            if hs.trigger == trigger:
                self.sim.type_text(hs.replacement)
                self.logs.append(f"hotstring {trigger!r} -> {hs.replacement!r}")
                return True
        return False

    # -- statements --
    def _exec_block(self, stmts):
        for st in stmts:
            self._check()
            self._exec(st)

    def _exec(self, st):
        if isinstance(st, P.Send):
            self.sim.type_text(self._interp(st.text))
        elif isinstance(st, P.Click):
            if st.x is not None and st.y is not None:
                self.sim.move_mouse(st.x, st.y, absolute=True)
            self.sim.click(st.button, st.count)
        elif isinstance(st, P.MouseMove):
            self.sim.move_mouse(st.x, st.y, absolute=True)
        elif isinstance(st, P.Sleep):
            self.sim.sleep_ms(st.ms)
        elif isinstance(st, P.Loop):
            n = st.count if st.count is not None else self.max_loop
            for _ in range(max(0, n)):
                self._check()
                self._exec_block(st.body)
        elif isinstance(st, P.While):
            guard = 0
            while self._cond(st.cond) and guard < self.max_loop:
                self._check()
                self._exec_block(st.body)
                guard += 1
        elif isinstance(st, P.Assign):
            self.vars[st.name] = self._resolve(st.value)
        elif isinstance(st, P.FuncDef):
            self.script.functions[st.name] = st
        elif isinstance(st, P.FuncCall):
            self._call(st)
        elif isinstance(st, P.MsgBox):
            self.logs.append("MsgBox: " + self._interp(st.text))
        elif isinstance(st, P.WinActivate):
            self.logs.append(f"WinActivate {st.title!r} (linux match, best-effort)")
        else:
            self.logs.append(f"skip: {st!r}")

    def _call(self, c: P.FuncCall):
        if c.name == "__raw__":
            self.logs.append(f"raw: {c.args[0] if c.args else ''}")
            return
        fn = self.script.functions.get(c.name)
        if fn is None:
            # builtins usable from scripts
            low = c.name.lower()
            if low == "sleep" and c.args:
                self.sim.sleep_ms(int(c.args[0]))
                return
            if low in ("send", "sendinput") and c.args:
                self.sim.type_text(self._interp(str(c.args[0])))
                return
            self.logs.append(f"call unknown {c.name}")
            return
        saved = dict(self.vars)
        for p, a in zip(fn.params, c.args):
            self.vars[p] = self._resolve(a)
        try:
            self._exec_block(fn.body)
        finally:
            # keep globals simple: restore only params shadowing
            for p in fn.params:
                if p in saved:
                    self.vars[p] = saved[p]
                else:
                    self.vars.pop(p, None)

    # -- tiny expression layer --
    def _resolve(self, v):
        if isinstance(v, str) and v in self.vars:
            return self.vars[v]
        return v

    def _interp(self, text: str) -> str:
        def rep(m):
            return str(self.vars.get(m.group(1), m.group(0)))
        return re.sub(r'\{(\w+)\}', rep, text)

    def _cond(self, cond: str) -> bool:
        cond = cond.strip()
        m = re.match(r'^(\w+)\s*(<|>|<=|>=|=|==|!=)\s*(-?\d+)\s*$', cond)
        if m:
            lhs = self.vars.get(m.group(1), 0)
            try:
                lhs = int(lhs)
            except (TypeError, ValueError):
                return False
            rhs, op = int(m.group(2)) if False else int(m.group(3)), m.group(2)
            return {"<": lhs < rhs, ">": lhs > rhs, "<=": lhs <= rhs,
                    ">=": lhs >= rhs, "=": lhs == rhs, "==": lhs == rhs,
                    "!=": lhs != rhs}[op]
        if cond.isdigit():
            return int(cond) != 0
        v = self.vars.get(cond, False)
        return bool(v) and v != "0" and v != 0
