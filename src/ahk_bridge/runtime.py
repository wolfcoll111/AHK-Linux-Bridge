"""Executor with emergency abort. Runs parsed Script against InputSimulator.

v0.2: expression eval (arithmetic, Random(), strings), If/Else, Break/Continue,
Loop/Sleep var resolution, {Key} send-sequences, live PixelSearch + WinActivate.
"""
from __future__ import annotations
import ast
import random
import re
import threading
from . import parser as P

ABORT_KEYS = ("Escape", "Ctrl+Alt+C")


class Aborted(RuntimeError):
    pass


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


# {Key} tokens that map to a physical key tap instead of typed text.
_SPECIAL_KEYS = {
    "enter": "Enter", "tab": "Tab", "esc": "Escape", "escape": "Escape",
    "space": "Space", "backspace": "BackSpace", "delete": "Delete",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End", "pgup": "Page_Up", "pgdn": "Page_Down",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5",
    "f6": "F6", "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10",
    "f11": "F11", "f12": "F12",
}
_SEND_TOKEN_RE = re.compile(r"\{([^{}]+)\}")


class Runtime:
    def __init__(self, script: P.Script, sim, abort_keys=ABORT_KEYS,
                 max_loop=10_000, jitter: float = 0.0, seed=None):
        self.script = script
        self.sim = sim
        self.vars: dict = {}
        self.logs: list[str] = []
        self._abort = threading.Event()
        self.abort_keys = tuple(abort_keys)
        self.max_loop = max_loop  # safety cap for infinite loops in tests
        self.jitter = jitter  # 0.0..1.0 fraction of Sleep randomization
        self._rng = random.Random(seed)

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
            self._send_text(self._interp(st.text))
        elif isinstance(st, P.Click):
            if st.x is not None and st.y is not None:
                self.sim.move_mouse(st.x, st.y, absolute=True)
            self.sim.click(st.button, st.count)
        elif isinstance(st, P.MouseMove):
            self.sim.move_mouse(st.x, st.y, absolute=True)
        elif isinstance(st, P.Sleep):
            self.sim.sleep_ms(self._resolve_sleep(st.ms))
        elif isinstance(st, P.Loop):
            n = self._resolve_count(st.count)
            for _ in range(max(0, n)):
                self._check()
                try:
                    self._exec_block(st.body)
                except _Continue:
                    continue
                except _Break:
                    break
        elif isinstance(st, P.While):
            guard = 0
            while self._cond(st.cond) and guard < self.max_loop:
                self._check()
                try:
                    self._exec_block(st.body)
                except _Continue:
                    guard += 1
                    continue
                except _Break:
                    break
                guard += 1
        elif isinstance(st, P.If):
            if self._cond(st.cond):
                try:
                    self._exec_block(st.then_body)
                except _Continue:
                    raise
                except _Break:
                    raise
            elif st.else_body:
                self._exec_block(st.else_body)
        elif isinstance(st, (P.Break,)):
            raise _Break()
        elif isinstance(st, (P.Continue,)):
            raise _Continue()
        elif isinstance(st, P.Assign):
            self.vars[st.name] = self._eval_expr(st.value)
        elif isinstance(st, P.FuncDef):
            self.script.functions[st.name] = st
        elif isinstance(st, P.FuncCall):
            self._call(st)
        elif isinstance(st, P.MsgBox):
            self.logs.append("MsgBox: " + self._interp(st.text))
        elif isinstance(st, P.WinActivate):
            self._win_activate(st.title)
        elif isinstance(st, P.PixelSearch):
            self._pixel_search(st)
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
                self.sim.sleep_ms(self._resolve_sleep(c.args[0]))
                return
            if low in ("send", "sendinput", "sendevent", "sendplay", "sendtext") and c.args:
                self._send_text(self._interp(str(c.args[0])))
                return
            if low == "random" and len(c.args) >= 2:
                try:
                    lo, hi = int(self._eval_expr(c.args[0])), int(self._eval_expr(c.args[1]))
                    self.logs.append(f"Random({lo},{hi}) -> use x := Random(...) for value")
                except (TypeError, ValueError):
                    self.logs.append("Random: bad args")
                return
            if low == "winactivate" and c.args:
                self._win_activate(str(c.args[0]))
                return
            self.logs.append(f"call unknown {c.name}")
            return
        saved = dict(self.vars)
        for p, a in zip(fn.params, c.args):
            self.vars[p] = self._eval_expr(a)
        try:
            self._exec_block(fn.body)
        except _Break:
            pass
        except _Continue:
            pass
        finally:
            # keep globals simple: restore only params shadowing
            for p in fn.params:
                if p in saved:
                    self.vars[p] = saved[p]
                else:
                    self.vars.pop(p, None)

    # -- Send with {Key} sequences --
    def _send_text(self, text: str):
        """Type plain runs via type_text; tap {SpecialKey} via send_key.

        Handles AHK Deluxe vocabulary found in real farming macros:
        {Blind} (modifier-release guard, stripped), {LButton}/{RButton}/
        {MButton} (clicks), {WheelUp}/{WheelDown} (scroll), {X down/up}
        for named keys too (e.g. {Enter down}).
        """
        if not _SEND_TOKEN_RE.search(text):
            if text:
                self.sim.type_text(text)
            return
        buf2, last = "", 0
        for m in _SEND_TOKEN_RE.finditer(text):
            buf2 += text[last:m.start()]
            tok = m.group(1).strip()
            low = tok.lower()
            if low == "blind":
                pass  # mode flag only; type the rest normally
            elif low in _SPECIAL_KEYS:
                if buf2:
                    self.sim.type_text(buf2)
                    buf2 = ""
                self.sim.send_key(_SPECIAL_KEYS[low])
            elif low in ("lbutton", "left"):
                if buf2:
                    self.sim.type_text(buf2)
                    buf2 = ""
                self.sim.click("left")
            elif low in ("rbutton", "right"):
                if buf2:
                    self.sim.type_text(buf2)
                    buf2 = ""
                self.sim.click("right")
            elif low in ("mbutton", "middle"):
                if buf2:
                    self.sim.type_text(buf2)
                    buf2 = ""
                self.sim.click("middle")
            elif low in ("wheelup", "wheeldown"):
                if buf2:
                    self.sim.type_text(buf2)
                    buf2 = ""
                scroll = getattr(self.sim, "scroll", None)
                if scroll is not None:
                    scroll(1 if low == "wheelup" else -1)
            else:
                dm = re.match(r"(?i)^(\w+)\s+(down|up)$", tok)
                if dm:
                    name, how = dm.group(1), dm.group(2).lower()
                    code = _SPECIAL_KEYS.get(name.lower(), name)
                    if buf2:
                        self.sim.type_text(buf2)
                        buf2 = ""
                    self.sim.send_key(code, down=(how == "down"))
                elif tok in self.vars:
                    buf2 += str(self.vars[tok])
                else:
                    buf2 += m.group(0)
            last = m.end()
        buf2 += text[last:]
        if buf2:
            self.sim.type_text(buf2)

    # -- WinActivate: best-effort via Hyprland, then log --
    def _win_activate(self, title: str):
        title = self._interp(title)
        try:
            import json
            import subprocess
            out = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True,
                                 text=True, timeout=5)
            if out.returncode == 0:
                clients = json.loads(out.stdout or "[]")
                want = title.lower()
                for c in clients:
                    blob = " ".join(str(c.get(k, "")) for k in
                                    ("title", "class", "initialTitle", "initialClass")).lower()
                    if want and want in blob:
                        addr = c.get("address")
                        if addr:
                            subprocess.run(["hyprctl", "dispatch", "focuswindow",
                                            f"address:{addr}"],
                                           capture_output=True, timeout=5)
                            self.logs.append(f"WinActivate {title!r} -> focused {addr}")
                            return
        except Exception:
            pass
        self.logs.append(f"WinActivate {title!r} (linux match, best-effort)")

    # -- PixelSearch: live capture via mss, log result into vars --
    def _pixel_search(self, st: P.PixelSearch):
        try:
            from . import pixels as px
            rgb_bytes, w, h = px.screenshot_rgb()
            import re as _re
            m = _re.search(r"0[xX]([0-9a-fA-F]{6})", str(st.color))
            if m:
                hx = m.group(1)
                rgb = (int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16))
            else:
                nums = _re.findall(r"\d+", str(st.color))
                rgb = tuple(int(x) % 256 for x in (nums + ["0", "0", "0"])[:3])  # type: ignore
            # crop to box if given
            x1, y1 = int(self._eval_expr(st.x1)), int(self._eval_expr(st.y1))
            x2, y2 = int(self._eval_expr(st.x2)), int(self._eval_expr(st.y2))
            if x2 > x1 and y2 > y1:
                hit = px.find_color_in_region(rgb_bytes, w, h, rgb, x1, y1, x2, y2)
            else:
                hit = px.find_color(rgb_bytes, w, h, rgb)
            if hit:
                self.vars["FoundX"], self.vars["FoundY"] = hit
                self.logs.append(f"PixelSearch {st.color} -> {hit}")
            else:
                self.vars["FoundX"], self.vars["FoundY"] = -1, -1
                self.logs.append(f"PixelSearch {st.color} -> not found")
        except RuntimeError as e:
            self.logs.append(f"PixelSearch skipped: {e}")
        except Exception as e:
            self.logs.append(f"PixelSearch error: {e}")

    # -- expression layer --
    def _eval_expr(self, raw):
        """Eval `x := <expr>`: int, quoted string, var, Random(a,b), arithmetic."""
        if isinstance(raw, (int, float)):
            return raw
        if raw is None:
            return ""
        s = str(raw).strip()
        if s == "":
            return ""
        # quoted string literal
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            inner = s[1:-1]
            return self._interp(inner)
        # Random(a, b) builtin -> int
        m = re.match(r"(?i)^random\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)$", s)
        if m:
            lo = int(self._eval_expr(m.group(1).strip()))
            hi = int(self._eval_expr(m.group(2).strip()))
            lo, hi = (lo, hi) if lo <= hi else (hi, lo)
            return self._rng.randint(lo, hi)
        # bare var
        if re.match(r"^[A-Za-z_]\w*$", s) and s in self.vars:
            return self.vars[s]
        # safe integer arithmetic with vars substituted
        try:
            tree = ast.parse(s, mode="eval")
            val = self._safe_eval(tree.body)
            return val
        except Exception:
            pass
        # dotted string concat with vars: "a" . x  (AHK v2 `.` operator)
        if "." in s:
            parts = [p.strip() for p in s.split(".")]
            try:
                return "".join(str(self._eval_expr(p)) for p in parts if p != "")
            except Exception:
                pass
        # bare int?
        try:
            return int(s)
        except ValueError:
            pass
        # unknown identifier -> 0 (AHK-ish falsy) unless it's a var name to keep
        if re.match(r"^[A-Za-z_]\w*$", s):
            return self.vars.get(s, 0)
        return s

    def _safe_eval(self, node):
        import operator as _op
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            v = self.vars.get(node.id, 0)
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, (int, float)):
                return v
            try:
                return int(v)
            except (TypeError, ValueError):
                raise ValueError(f"non-numeric var {node.id}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = self._safe_eval(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.BinOp) and isinstance(node.op,
                (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
            a, b = self._safe_eval(node.left), self._safe_eval(node.right)
            ops = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
                   ast.FloorDiv: _op.floordiv, ast.Mod: _op.mod}
            return ops[type(node.op)](a, b)
        if isinstance(node, ast.Div):
            raise ValueError("unsupported")
        raise ValueError("unsupported expression")

    def _resolve(self, v):
        if isinstance(v, (int, float)):
            return v
        return self._eval_expr(v)

    def _resolve_count(self, count) -> int:
        if count is None:
            return self.max_loop
        if isinstance(count, int):
            return count
        v = self._eval_expr(count)
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return self.max_loop

    def _resolve_sleep(self, ms) -> int:
        if isinstance(ms, int):
            base = ms
        else:
            v = self._eval_expr(ms)
            try:
                base = int(v)
            except (TypeError, ValueError):
                base = 0
        if self.jitter and base > 0:
            delta = int(base * self.jitter * self._rng.uniform(-1, 1))
            return max(0, base + delta)
        return max(0, base)

    def _interp(self, text: str) -> str:
        def rep(m):
            return str(self.vars.get(m.group(1), m.group(0)))
        return re.sub(r"\{(\w+)\}", rep, str(text))

    def _cond(self, cond: str) -> bool:
        cond = str(cond).strip()
        if not cond:
            return False
        # paren-wrapped or full expressions: (x > 1), FoundX >= 0, etc.
        m = re.match(r"^(.+?)\s*(<=|>=|==|!=|=|<|>)\s*(.+)$", cond)
        if m:
            lhs = self._eval_expr(m.group(1).strip())
            rhs = self._eval_expr(m.group(3).strip())
            op = m.group(2)
            try:
                li, ri = int(lhs), int(rhs)
                cmp = {"<": li < ri, ">": li > ri, "<=": li <= ri,
                       ">=": li >= ri, "=": li == ri, "==": li == ri,
                       "!=": li != ri}[op]
                return cmp
            except (TypeError, ValueError):
                ls, rs = str(lhs), str(rhs)
                if op in ("=", "=="):
                    return ls == rs
                if op == "!=":
                    return ls != rs
                return False
        if cond.isdigit():
            return int(cond) != 0
        v = self._eval_expr(cond) if not cond in self.vars else self.vars.get(cond)
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        return bool(v) and v != "0" and v != 0
