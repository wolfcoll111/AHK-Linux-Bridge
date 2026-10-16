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
    def __init__(self, level: int = 1):
        super().__init__("break")
        self.level = level


class _Continue(Exception):
    def __init__(self, level: int = 1):
        super().__init__("continue")
        self.level = level


class _Return(Exception):
    def __init__(self, value=None):
        super().__init__("return")
        self.value = value


def _has_cmp_op(s: str) -> bool:
    """True when s contains a comparison operator outside string literals
    (`~=`, `<=`, `>=`, `==`, `!=`, or lone `=`/`<`/`>` not part of `:=`)."""
    code, q = [], None
    k = 0
    while k < len(s):
        ch = s[k]
        if ch == "`" and k + 1 < len(s):
            k += 2
            continue
        if q:
            if ch == q:
                q = None
            k += 1
            continue
        if ch in ('"', "'"):
            q = ch
            k += 1
            continue
        code.append(ch)
        k += 1
    t = "".join(code)
    if re.search(r"~=|<=|>=|==|!=", t):
        return True
    # lone = (not :=, ==) / < (not <=) / > (not >=)
    if re.search(r"(?<![=!<>])=(?![=])", t):
        if ":=" not in t.replace(" ", ""):
            return True
        # `:=` present but a LATER lone `=` may still compare: check tail
        tail = t.split(":=", 1)[-1] if ":=" in t else t
        return bool(re.search(r"(?<![=!<>])=(?![=])", tail))
    if re.search(r"<(?!=)", t):
        return True
    if re.search(r">(?!=)", t):
        return True
    return False


# {Key} tokens that map to a physical key tap instead of typed text.
_SPECIAL_KEYS = {
    "enter": "Enter", "tab": "Tab", "esc": "Escape", "escape": "Escape",
    "space": "Space", "backspace": "BackSpace", "delete": "Delete",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End", "pgup": "Page_Up", "pgdn": "Page_Down",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5",
    "f6": "F6", "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10",
    "f11": "F11", "f12": "F12", "f13": "F13", "f14": "F14",
    "f15": "F15", "f16": "F16", "f17": "F17", "f18": "F18",
    "f19": "F19", "f20": "F20", "f21": "F21", "f22": "F22",
    "f23": "F23", "f24": "F24",
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
        self._stub_warned: set = set()  # builtin stubs logged once each

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
            self._send_eval(st.text)
        elif isinstance(st, P.Click):
            x = self._eval_expr(st.x) if st.x is not None else None
            y = self._eval_expr(st.y) if st.y is not None else None
            try:
                x = int(x) if x is not None else None
                y = int(y) if y is not None else None
            except (TypeError, ValueError):
                x = y = None
            if x is not None and y is not None:
                self.sim.move_mouse(x, y, absolute=True)
            elif getattr(st, "opts", ""):
                self.logs.append(f"Click opts {st.opts!r} (coordless click)")
            self.sim.click(st.button, st.count)
        elif isinstance(st, P.MouseMove):
            x = self._num(st.x)
            y = self._num(st.y)
            self.sim.move_mouse(x, y, absolute=True)
        elif isinstance(st, P.Sleep):
            self.sim.sleep_ms(self._resolve_sleep(st.ms))
        elif isinstance(st, P.Loop):
            n = self._resolve_count(st.count)
            saved_index = self.vars.get("A_Index")
            for ai in range(1, max(0, n) + 1):
                self.vars["A_Index"] = ai
                self._check()
                try:
                    self._exec_block(st.body)
                except _Continue as _c:
                    if _c.level > 1:
                        _c.level -= 1
                        raise
                    continue
                except _Break as _b:
                    if _b.level > 1:
                        _b.level -= 1
                        raise
                    break
            self._restore_index(saved_index)
        elif isinstance(st, P.LoopParse):
            self._loop_parse(st)
        elif isinstance(st, P.LoopFiles):
            self._loop_files(st)
        elif isinstance(st, P.KeyWait):
            self._keywait(st)
        elif isinstance(st, P.For):
            self._for(st)
        elif isinstance(st, P.While):
            guard = 0
            while self._cond(st.cond) and guard < self.max_loop:
                self.vars["A_Index"] = guard + 1
                self._check()
                try:
                    self._exec_block(st.body)
                except _Continue as _c:
                    guard += 1
                    if _c.level > 1:
                        _c.level -= 1
                        raise
                    continue
                except _Break as _b:
                    if _b.level > 1:
                        _b.level -= 1
                        raise
                    break
                guard += 1
            self.vars.pop("A_Index", None)
        elif isinstance(st, P.DoUntil):
            # do { ... } until cond: body runs at least once.
            guard = 0
            while guard < self.max_loop:
                self.vars["A_Index"] = guard + 1
                self._check()
                try:
                    self._exec_block(st.body)
                except _Continue as _c:
                    guard += 1
                    if _c.level > 1:
                        _c.level -= 1
                        raise
                    if self._cond(st.cond):
                        break
                    continue
                except _Break as _b:
                    if _b.level > 1:
                        _b.level -= 1
                        raise
                    break
                guard += 1
                if self._cond(st.cond):
                    break
            self.vars.pop("A_Index", None)
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
        elif isinstance(st, P.Switch):
            self._switch(st)
        elif isinstance(st, P.Try):
            self._try(st)
        elif isinstance(st, (P.Break,)):
            raise _Break(max(1, st.level or 1))
        elif isinstance(st, (P.Continue,)):
            raise _Continue(max(1, st.level or 1))
        elif isinstance(st, P.Return):
            raise _Return(self._eval_expr(st.value) if st.value is not None else None)
        elif isinstance(st, P.ScopeDecl):
            pass  # our vars are function-global already; static persists too
        elif isinstance(st, P.Setting):
            if st.name.lower() != "label":
                self.logs.append(f"setting {st.name} {st.args} (noted, linux no-op)")
        elif isinstance(st, P.Include):
            self.logs.append(f"#Include {st.path} (not inlined; parse+run continues)")
        elif isinstance(st, P.IniOp):
            self._ini(st)
        elif isinstance(st, P.Assign):
            self.vars[st.name] = self._eval_expr(st.value)
        elif isinstance(st, P.AssignTarget):
            self._assign_target(st.target, st.value)
        elif isinstance(st, P.CompoundAssign):
            name = st.name
            # v1 dynamic segments: hour_%status%_time, %j%_time
            for _ in range(10):
                dm = re.search(r"%([A-Za-z_]\w*)%", name)
                if not dm:
                    break
                name = name[:dm.start()] + str(self.vars.get(dm.group(1), "")) + name[dm.end():]
            cur = self.vars.get(name, 0)
            val = self._eval_expr(st.value)
            try:
                if st.op == "+=":
                    self.vars[name] = self._numval(cur) + self._numval(val)
                elif st.op == "-=":
                    self.vars[name] = self._numval(cur) - self._numval(val)
                elif st.op == "*=":
                    self.vars[name] = self._numval(cur) * self._numval(val)
                elif st.op in ("//=", "/="):
                    d = self._numval(val)
                    self.vars[name] = (self._numval(cur) // d) if st.op == "//=" else (self._numval(cur) / d)
                elif st.op == ".=":
                    self.vars[name] = str(cur) + str(val)
                elif st.op in ("|=", "&="):
                    a, b = int(self._numval(cur)), int(self._numval(val))
                    self.vars[name] = (a | b) if st.op == "|=" else (a & b)
            except (TypeError, ValueError, ZeroDivisionError):
                self.vars[name] = val if st.op == ".=" else cur
        elif isinstance(st, P.IncDec):
            try:
                self.vars[st.name] = self._numval(self.vars.get(st.name, 0)) + st.delta
            except (TypeError, ValueError):
                self.vars[st.name] = st.delta
        elif isinstance(st, P.Seq):
            for sub in st.items:
                self._check()
                self._exec(sub)
        elif isinstance(st, P.Throw):
            raise RuntimeError(str(self._eval_expr(st.value)) if st.value else "throw")
        elif isinstance(st, P.ExitApp):
            self.logs.append(f"ExitApp({st.code}) - clean end of script")
            raise Aborted("ExitApp")
        elif isinstance(st, P.LegacyCmd):
            self._legacy(st)
        elif isinstance(st, P.FuncDef):
            self.script.functions[st.name] = st
        elif isinstance(st, P.Class):
            # class scope: run static initializers now; methods register as
            # functions via the FuncDef branch (dotted calls log as stubs).
            self.logs.append(f"class {st.name}" + (f" extends {st.base}" if st.base else "") + " (methods registered, statics run once)")
            self._exec_block(st.body)
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
        self._call_value(c)

    def _call_value(self, c: P.FuncCall):
        """Execute call, returning the function's Return value (or builtin)."""
        if c.name == "__raw__":
            self.logs.append(f"raw: {c.args[0] if c.args else ''}")
            return ""
        fn = self.script.functions.get(c.name)
        if fn is None:
            return self._builtin(c)
        saved = dict(self.vars)
        for p, a in zip(fn.params, c.args):
            self.vars[p] = self._eval_expr(a)
        try:
            self._exec_block(fn.body)
            return ""
        except _Return as r:
            return r.value if r.value is not None else ""
        except (_Break, _Continue):
            return ""
        finally:
            # keep globals simple: restore only params shadowing
            for p in fn.params:
                if p in saved:
                    self.vars[p] = saved[p]
                else:
                    self.vars.pop(p, None)

    def _builtin(self, c: P.FuncCall):
        low = c.name.lower()
        if low == "sleep" and c.args:
            self.sim.sleep_ms(self._resolve_sleep(c.args[0]))
            return ""
        if low in ("send", "sendinput", "sendevent", "sendplay", "sendtext") and c.args:
            self._send_eval(str(c.args[0]))
            return ""
        if low == "msgbox" and c.args:
            self.logs.append("MsgBox: " + self._interp(str(c.args[0])))
            return ""
        if low == "winactivate" and c.args:
            self._win_activate(str(c.args[0]))
            return ""
        return self._pure_builtin(low, c.args)

    def _pure_builtin(self, low: str, args: list):
        """Side-effect-free builtins usable inside expressions. Unknown GUI/OS
        builtins become logged stubs returning falsy (documented gap)."""
        ev = lambda a: self._eval_expr(a)
        try:
            if low == "random" and len(args) >= 2:
                lo, hi = int(ev(args[0])), int(ev(args[1]))
                lo, hi = (lo, hi) if lo <= hi else (hi, lo)
                return self._rng.randint(lo, hi)
            if low == "substr" and len(args) >= 2:
                s = str(ev(args[0]))
                start = int(ev(args[1]))
                length = int(ev(args[2])) if len(args) > 2 else None
                # AHK 1-based; negative start counts from end
                i0 = (start - 1) if start > 0 else max(0, len(s) + start)
                return s[i0:] if length is None else s[i0:i0 + max(0, length)]
            if low == "instr" and len(args) >= 2:
                hay, needle = str(ev(args[0])), str(ev(args[1]))
                cs = not (len(args) > 2 and str(ev(args[2])).lower() in ("0", "false", ""))
                start = int(ev(args[3])) - 1 if len(args) > 3 else 0
                h = hay[start:] if cs else hay[start:].lower()
                n = needle if cs else needle.lower()
                pos = h.find(n)
                return (start + pos + 1) if pos >= 0 else 0
            if low == "strlen" and args:
                return len(str(ev(args[0])))
            if low == "strreplace" and len(args) >= 2:
                return str(ev(args[0])).replace(str(ev(args[1])),
                                                str(ev(args[2])) if len(args) > 2 else "")
            if low in ("trim", "ltrim", "rtrim") and args:
                s = str(ev(args[0]))
                return s.strip() if low == "trim" else (s.lstrip() if low == "ltrim" else s.rstrip())
            if low in ("strupper", "strlower") and args:
                s = str(ev(args[0]))
                return s.upper() if low == "strupper" else s.lower()
            if low == "round" and args:
                return round(float(ev(args[0])), int(ev(args[1])) if len(args) > 1 else 0)
            if low in ("abs",) and args:
                v = ev(args[0])
                return abs(v) if isinstance(v, (int, float)) else abs(float(v))
            if low in ("floor", "ceil") and args:
                import math as _math
                v = float(ev(args[0]))
                return int(_math.floor(v) if low == "floor" else _math.ceil(v))
            if low in ("sqrt", "exp", "sin", "cos", "atan", "log", "ln") and args:
                import math as _math2
                v = float(ev(args[0]))
                fn = {"sqrt": _math2.sqrt, "exp": _math2.exp, "sin": _math2.sin,
                      "cos": _math2.cos, "atan": _math2.atan, "log": _math2.log10,
                      "ln": _math2.log}[low]
                return fn(v)
            if low in ("min", "max") and args:
                vals = [ev(a) for a in args]
                try:
                    return (min if low == "min" else max)(vals)
                except TypeError:
                    return (min if low == "min" else max)(str(v) for v in vals)
            if low == "mod" and len(args) >= 2:
                return int(ev(args[0])) % int(ev(args[1]))
            if low == "strsplit" and args:
                s = str(ev(args[0]))
                delims = str(ev(args[1])) if len(args) > 1 else ""
                if not delims:
                    return [s]
                parts, cur = [], ""
                for ch in s:
                    if ch in delims:
                        parts.append(cur)
                        cur = ""
                    else:
                        cur += ch
                parts.append(cur)
                return parts
            if low == "array" and args:
                return [ev(a) for a in args]
            if low == "map" :
                vals = [ev(a) for a in args]
                return {vals[k]: vals[k + 1] for k in range(0, len(vals) - 1, 2)}
            if low == "isobject" and args:
                return isinstance(ev(args[0]), (list, dict))
            if low == "isset" and args:
                name = str(args[0]).strip().lstrip("&")
                return 1 if name in self.vars else 0
            if low in ("error", "typeerror", "valueerror", "oserror") and args:
                # Error objects: carry the message so `throw Error("msg")`
                # surfaces it; property access beyond .Message is a gap.
                return str(ev(args[0]))
            if low == "buffer":
                return ""
            if low in ("fileexist", "winexist", "wingetcount", "processexist"):
                return ""
            if low in ("isinteger", "isnumber") and args:
                try:
                    int(ev(args[0]))
                    return 1
                except (TypeError, ValueError):
                    return 0
        except (TypeError, ValueError, IndexError):
            return "" if low not in ("instr", "strlen", "isobject",
                                     "isinteger", "isnumber") else 0
        if low not in self._stub_warned:
            self._stub_warned.add(low)
            self.logs.append(f"stub builtin {low}() -> falsy (GUI/OS gap)")
        return ""

    # -- Send with {Key} sequences --
    def _send_eval(self, text: str):
        """AHK v2 Send semantics: {Key} vocabulary, bare vars/calls evaluate,
        juxtaposed parts concatenate, unknown bare words stay literal."""
        t = str(text)
        if _SEND_TOKEN_RE.search(t):
            self._send_text(self._interp(t))
            return
        val = self._eval_concat(t)
        if val is None:
            if t:
                self.sim.type_text(t)
            return
        if _SEND_TOKEN_RE.search(val):
            self._send_text(val)
        elif val:
            self.sim.type_text(val)

    def _eval_concat(self, t: str):
        """Evaluate juxtaposed `"a" var call` concatenation. Returns the string,
        or None when the text is plain literal (no quotes/vars/calls)."""
        parts = self._split_juxta(t)
        if not parts:
            return None
        kinds = [self._part_kind(quoted, body) for quoted, body in parts]
        if all(k == "lit" for k in kinds):
            return None  # plain literal like `Send farm` / `Send hello world`
        out = []
        for (quoted, body), kind in zip(parts, kinds):
            if quoted:
                out.append(self._interp(body))
            elif kind == "v":
                out.append(str(self._eval_expr(body)))
            else:
                out.append(body)
        return "".join(out)

    def _part_kind(self, quoted: bool, body: str) -> str:
        if quoted:
            return "q"
        if re.match(r"^%([A-Za-z_]\w*)%$", body) or "%" in body and re.search(r"%[A-Za-z_]\w*%", body):
            return "v"
        if body in self.vars:
            return "v"
        if re.match(r"^[A-Za-z_]\w*\s*\(.*\)$", body, re.DOTALL):
            return "v"
        m = re.match(r"^([A-Za-z_]\w*)(?:\[.+?\])+$", body, re.DOTALL)
        if m and m.group(1) in self.vars:
            return "v"
        return "lit"

    @staticmethod
    def _split_juxta(t: str):
        """Split juxtaposed text into (quoted: bool, body) parts. Quotes and
        brackets are opaque: splitting happens only on whitespace at depth 0
        outside quotes. A part is 'quoted' only if entirely one string."""
        raw, cur, q, depth = [], "", None, 0
        k = 0
        while k < len(t):
            ch = t[k]
            if ch == "`" and k + 1 < len(t):
                cur += t[k:k + 2]
                k += 2
                continue
            if q:
                cur += ch
                if ch == q:
                    q = None
            elif ch in ('"', "'"):
                cur += ch
                q = ch
            elif ch in "([":
                depth += 1
                cur += ch
            elif ch in ")]":
                depth = max(0, depth - 1)
                cur += ch
            elif ch in (" ", "\t") and depth == 0:
                if cur != "":
                    raw.append(cur)
                    cur = ""
            else:
                cur += ch
            k += 1
        if cur != "":
            raw.append(cur)
        parts = []
        for p in raw:
            ps = p.strip()
            if len(ps) >= 2 and ps[0] == ps[-1] and ps[0] in ('"', "'"):
                parts.append((True, ps[1:-1]))
            elif ps:
                parts.append((False, ps))
        return parts
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
                elif re.match(r"^[A-Za-z_]\w*\s*\(.*\)$", tok, re.DOTALL) or \
                        re.match(r"^[A-Za-z_]\w*(?:\[.+?\])+$", tok, re.DOTALL):
                    # {Func(...)} / {arr[i]} interpolation (juxtaposed-quote safe)
                    try:
                        buf2 += str(self._eval_expr(tok))
                    except Exception:
                        buf2 += m.group(0)
                else:
                    buf2 += m.group(0)
            last = m.end()
        buf2 += text[last:]
        if buf2:
            self.sim.type_text(buf2)

    # -- WinActivate: best-effort across compositors --
    def _win_activate(self, title: str):
        title = self._interp(title)
        if self._win_activate_hyprland(title):
            return
        if self._win_activate_xdotool(title):
            return
        self.logs.append(f"WinActivate {title!r} (linux match, best-effort)")

    def _win_activate_hyprland(self, title: str) -> bool:
        try:
            import json
            import subprocess
            out = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True,
                                 text=True, timeout=5)
            if out.returncode != 0:
                return False
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
                        return True
        except Exception:
            pass
        return False

    def _win_activate_xdotool(self, title: str) -> bool:
        """X11/XWayland path: covers Wine games, AHK Dash, Sober-less setups
        on KDE Plasma, GNOME+X11 and Hyprland alike. Needs DISPLAY + xdotool."""
        import shutil
        import subprocess
        if not shutil.which("xdotool"):
            return False
        try:
            out = subprocess.run(["xdotool", "search", "--onlyvisible",
                                  "--name", title],
                                 capture_output=True, text=True, timeout=5)
            wins = [w for w in (out.stdout or "").split() if w.strip().isdigit()]
            if not wins:
                return False
            subprocess.run(["xdotool", "windowactivate", wins[0]],
                           capture_output=True, timeout=5)
            self.logs.append(f"WinActivate {title!r} -> X window {wins[0]}")
            return True
        except Exception:
            return False

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

    # -- structured statements (v0.3) --
    def _assign_target(self, target: str, value):
        """Indexed/property assignment: arr[i] := v, a[i][k] := v, obj.p := v."""
        val = self._eval_expr(value)
        # v1 dynamic names: PlanterTime%i% -> resolve before parsing target
        for _ in range(10):
            m = re.search(r"%([A-Za-z_]\w*)%", target)
            if not m:
                break
            target = target[:m.start()] + str(self.vars.get(m.group(1), "")) + target[m.end():]
        m = re.match(r"^([A-Za-z_]\w*)(.*)$", target.strip(), re.DOTALL)
        if not m:
            self.logs.append(f"assign-target {target!r} unsupported (logged)")
            return
        base_name, rest = m.group(1), m.group(2).strip()
        if base_name not in self.vars or not rest:
            self.logs.append(f"assign-target {target!r} has no live container (logged)")
            return
        # parse accessors: [idx] or .prop chains
        accs = []
        k = 0
        ok = True
        while k < len(rest):
            if rest[k] == "[":
                depth, q, j = 0, None, k
                while j < len(rest):
                    ch = rest[j]
                    if q:
                        if ch == q:
                            q = None
                    elif ch in ('"', "'"):
                        q = ch
                    elif ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                if depth != 0:
                    ok = False
                    break
                accs.append(("idx", self._eval_expr(rest[k + 1:j].strip())))
                k = j + 1
            elif rest[k] == ".":
                mm = re.match(r"\.([A-Za-z_]\w*)", rest[k:])
                if not mm:
                    ok = False
                    break
                accs.append(("key", mm.group(1)))
                k += len(mm.group(0))
            elif rest[k] in (" ", "\t"):
                k += 1
            else:
                ok = False
                break
        if not ok or not accs:
            self.logs.append(f"assign-target {target!r} unsupported (logged)")
            return
        try:
            obj = self.vars[base_name]
            for kind, key in accs[:-1]:
                obj = self._access(obj, key)
            last_kind, last_key = accs[-1]
            self._store(obj, last_kind, last_key, val)
        except (TypeError, ValueError, IndexError, KeyError) as e:
            self.logs.append(f"assign-target {target!r} failed: {e}")

    @staticmethod
    def _access(obj, key):
        if isinstance(obj, (list, tuple)):
            return obj[int(key) - 1]
        if isinstance(obj, str):
            return obj[int(key) - 1]
        if isinstance(obj, dict):
            return obj[key] if key in obj else obj[str(key)]
        raise TypeError(f"cannot index {type(obj).__name__}")

    @staticmethod
    def _store(obj, kind, key, val):
        if isinstance(obj, list) and kind == "idx":
            i = int(key) - 1
            if 0 <= i < len(obj):
                obj[i] = val
                return
            raise IndexError("list assignment out of range")
        if isinstance(obj, dict):
            obj[key] = val
            return
        raise TypeError(f"cannot store into {type(obj).__name__}")

    def _numval(self, v):
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return v
        try:
            return int(v)
        except (TypeError, ValueError):
            return float(v)

    def _legacy(self, st: P.LegacyCmd):
        low, rest = st.name.lower(), (st.rest or "").strip()
        if low == "tooltip" and rest:
            import re as _re
            m = _re.match(r'^"(.*)"$', rest, re.DOTALL)
            self.logs.append("ToolTip: " + (m.group(1) if m else rest))
            return
        if low in ("soundbeep", "soundplay"):
            self.logs.append(f"{st.name} (no audio on headless bridge)")
            return
        if low in ("reload", "pause", "suspend", "edit", "listvars",
                   "keyhistory", "exit"):
            self.logs.append(f"{st.name} {rest} (noted, linux no-op)")
            return
        self.logs.append(f"{st.name} {rest} (OS/window op, linux no-op)")

    def _num(self, v) -> int:
        try:
            return int(self._eval_expr(v))
        except (TypeError, ValueError):
            return 0

    def _restore_index(self, saved):
        if saved is None:
            self.vars.pop("A_Index", None)
        else:
            self.vars["A_Index"] = saved

    def _loop_parse(self, st: P.LoopParse):
        text = str(self._eval_expr(st.text))
        delims = str(self._eval_expr(st.delims)) if st.delims else ""
        if delims:
            # split on any delim char (AHK Loop Parse semantics, simplified)
            parts, cur = [], ""
            for ch in text:
                if ch in delims:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += ch
            parts.append(cur)
        else:
            parts = [text]
        saved_index, saved_field = self.vars.get("A_Index"), self.vars.get("A_LoopField")
        try:
            for ai, part in enumerate(parts, 1):
                self.vars["A_Index"] = ai
                self.vars["A_LoopField"] = part
                self._check()
                try:
                    self._exec_block(st.body)
                except _Continue as _c:
                    if _c.level > 1:
                        _c.level -= 1
                        raise
                    continue
                except _Break as _b:
                    if _b.level > 1:
                        _b.level -= 1
                        raise
                    break
        finally:
            self._restore_index(saved_index)
            if saved_field is None:
                self.vars.pop("A_LoopField", None)
            else:
                self.vars["A_LoopField"] = saved_field

    def _loop_files(self, st: P.LoopFiles):
        """Iterate files matching a glob (AHK `Loop Files`). Sets
        A_LoopFileName/FullPath/Dir/Ext/NameNoExt + A_Index."""
        import glob as _glob
        import os as _os
        pat = str(self._eval_expr(st.pattern)).replace("\\", _os.sep)
        if not _os.path.isabs(pat):
            pat = _os.path.join(_os.getcwd(), pat)
        try:
            files = sorted(_glob.glob(pat))
        except Exception as e:
            self.logs.append(f"Loop Files error: {e}")
            return
        saved = {k: self.vars.get(k) for k in
                 ("A_Index", "A_LoopFileName", "A_LoopFileFullPath",
                  "A_LoopFileDir", "A_LoopFileExt", "A_LoopFileNameNoExt")}
        try:
            for ai, fp in enumerate(files, 1):
                base = _os.path.basename(fp)
                name, ext = _os.path.splitext(base)
                self.vars.update({
                    "A_Index": ai, "A_LoopFileName": base,
                    "A_LoopFileFullPath": fp, "A_LoopFileDir": _os.path.dirname(fp),
                    "A_LoopFileExt": ext.lstrip("."),
                    "A_LoopFileNameNoExt": name})
                self._check()
                try:
                    self._exec_block(st.body)
                except _Continue as _c:
                    if _c.level > 1:
                        _c.level -= 1
                        raise
                    continue
                except _Break as _b:
                    if _b.level > 1:
                        _b.level -= 1
                        raise
                    break
        finally:
            for k, v in saved.items():
                if v is None:
                    self.vars.pop(k, None)
                else:
                    self.vars[k] = v

    def _keywait(self, st: P.KeyWait):
        """`KeyWait key [, options]`. True global key-state waiting needs an
        evdev grab (roadmap); approximate: honor `Tn` timeout, else brief
        pause. Always logged so macro authors see the approximation."""
        import re as _re
        m = _re.search(r"(?i)T(\d+(?:\.\d+)?)", st.options or "")
        if m:
            self.sim.sleep_ms(int(float(m.group(1)) * 1000))
            self.logs.append(f"KeyWait {st.key} T{m.group(1)} (timed wait)")
        else:
            self.sim.sleep_ms(100)
            self.logs.append(f"KeyWait {st.key} [{st.options}] approximated as 100ms "
                             "(no global key grab on Linux yet)")

    def _iter_values(self, expr: str):
        """Resolve `for x in <expr>` to a list of values, or None to skip."""
        val = self._eval_expr(expr)
        if isinstance(val, (list, tuple)):
            return list(val)
        if isinstance(val, dict):
            return list(val.values())
        if isinstance(val, (int, float)):
            return list(range(1, int(val) + 1))
        return None

    def _for(self, st: P.For):
        vals = self._iter_values(st.iterable)
        if vals is None:
            self.logs.append(f"for: unsupported enumerable {st.iterable!r} (skipped)")
            return
        targets = st.targets[:2]
        saved = {t: self.vars.get(t, None) for t in targets}
        saved_index = self.vars.get("A_Index")
        try:
            for ai, item in enumerate(vals, 1):
                self.vars["A_Index"] = ai
                if len(targets) == 1:
                    self.vars[targets[0]] = item
                else:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        self.vars[targets[0]], self.vars[targets[1]] = item
                    else:
                        self.vars[targets[0]], self.vars[targets[1]] = ai, item
                self._check()
                try:
                    self._exec_block(st.body)
                except _Continue as _c:
                    if _c.level > 1:
                        _c.level -= 1
                        raise
                    continue
                except _Break as _b:
                    if _b.level > 1:
                        _b.level -= 1
                        raise
                    break
        finally:
            self._restore_index(saved_index)
            for t, v in saved.items():
                if v is None:
                    self.vars.pop(t, None)
                else:
                    self.vars[t] = v

    def _switch(self, st: P.Switch):
        val = self._eval_expr(st.value)
        matched = False
        default_body = None
        for cond, body in st.cases:
            if cond is None:
                default_body = body
                continue
            if not matched:
                try:
                    if self._eval_expr(cond) == val or str(self._eval_expr(cond)) == str(val):
                        matched = True
                    else:
                        continue
                except Exception:
                    continue
            if matched:
                try:
                    self._exec_block(body)
                except _Break as _b:
                    if _b.level > 1:
                        _b.level -= 1
                        raise
                    return
                return  # no fallthrough (AHK v2 has no fallthrough)
        if not matched and default_body is not None:
            try:
                self._exec_block(default_body)
            except _Break as _b:
                if _b.level > 1:
                    _b.level -= 1
                    raise
                pass

    def _try(self, st: P.Try):
        try:
            self._exec_block(st.try_body)
        except (_Break, _Continue, Aborted, _Return):
            raise  # control flow is never swallowed
        except Exception as e:
            if st.catch_var:
                self.vars[st.catch_var] = str(e)
            if st.catch_body:
                self._exec_block(st.catch_body)
            else:
                self.logs.append(f"try: caught {e}")
        else:
            # try-`else`: runs only when nothing threw (AHK v2 Else block)
            if getattr(st, "else_body", None):
                self._exec_block(st.else_body)
        finally:
            if st.finally_body:
                self._exec_block(st.finally_body)

    def _ini(self, st: P.IniOp):
        import configparser
        import os
        fname = str(self._eval_expr(st.filename))
        section = str(self._eval_expr(st.section))
        key = str(self._eval_expr(st.key))
        cfg = configparser.ConfigParser()
        cfg.optionxform = str  # keep key case
        try:
            if os.path.exists(fname):
                cfg.read(fname, encoding="utf-8")
            if st.op == "write":
                if not cfg.has_section(section):
                    cfg.add_section(section)
                cfg.set(section, key, str(self._eval_expr(st.value)))
                with open(fname, "w", encoding="utf-8") as f:
                    cfg.write(f)
                self.logs.append(f"IniWrite [{section}] {key} -> {fname}")
            else:
                try:
                    v = cfg.get(section, key)
                except (configparser.NoSectionError, configparser.NoOptionError):
                    v = ""
                target = str(st.value)
                if re.match(r"^[A-Za-z_]\w*$", target):
                    self.vars[target] = v
                self.logs.append(f"IniRead [{section}] {key} -> {v!r}")
        except OSError as e:
            self.logs.append(f"IniOp error: {e}")

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
        # v1-style %var% dereference inside expressions (up to 10 passes)
        for _ in range(10):
            m = re.search(r"%([A-Za-z_]\w*)%", s)
            if not m:
                break
            s = s[:m.start()] + str(self.vars.get(m.group(1), "")) + s[m.end():]
        s = s.strip()
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
        # chained assignment in expressions: x := y := 5
        m = re.match(r"^([A-Za-z_]\w*)\s*:=\s*(.+)$", s, re.DOTALL)
        if m:
            val = self._eval_expr(m.group(2).strip())
            self.vars[m.group(1)] = val
            return val
        # function / method call inside expressions (raw args: quotes kept)
        m = re.match(r"^([A-Za-z_]\w*)\s*\((.*)\)$", s, re.DOTALL)
        if m and self._balanced(s):
            from .parser import _split_seq as _ss
            _args = [p.strip() for p in _ss(m.group(2))] if m.group(2).strip() else []
            return self._call_value(P.FuncCall(m.group(1), [p for p in _args if p != ""]))
        m = re.match(r"^(.+?)\.([A-Za-z_]\w*)\s*\((.*)\)$", s, re.DOTALL)
        if m and self._balanced(s):
            obj, meth, argstr = self._eval_expr(m.group(1)), m.group(2).lower(), m.group(3)
            from .parser import _split_seq as _ss2
            _raw = [p.strip() for p in _ss2(argstr)] if argstr.strip() else []
            args = [p for p in _raw if p != ""]
            if meth == "push" and isinstance(obj, list):
                obj.append(self._eval_expr(args[0]) if args else None)
                return len(obj)
            if meth == "length" and isinstance(obj, (list, str, dict)):
                return len(obj)
            if isinstance(obj, str) and meth in ("length",):
                return len(obj)
            self.logs.append(f"method .{meth}() unsupported (logged)")
            return ""
        # AHK rule: `a.b` (no spaces) is object access, `a . b` is concat.
        m = re.match(r"^(.+?)\.([A-Za-z_]\w*)$", s, re.DOTALL)
        if m and re.search(r"\S\.\S", s):
            obj = self._eval_expr(m.group(1))
            prop = m.group(2).lower()
            if prop == "length" and isinstance(obj, (list, str, dict)):
                return len(obj)
            if isinstance(obj, dict):
                return obj.get(m.group(2), obj.get(prop, ""))
            if isinstance(obj, (list, dict)) or (
                    isinstance(obj, str) and m.group(1).strip() in self.vars):
                return ""
            # unknown base (filenames like t_dbg.ini, versions): literal
            return s
        # [...] array literal (raw elements: quotes kept)
        if s.startswith("[") and s.endswith("]") and self._balanced(s):
            from .parser import _split_seq as _ss3
            return [self._eval_expr(p) for p in
                    (q.strip() for q in _ss3(s[1:-1])) if p != ""]
        # ternary: cond ? a : b (top-level ? only)
        qm = self._split_ternary(s)
        if qm is not None:
            c, a, b = qm
            return self._eval_expr(a) if self._cond(c) else self._eval_expr(b)
        # logical operators in expressions: `a || b`, `a && b` -> 1/0.
        # After ternary/assignment (AHK: `?:` binds loosest). Operands go
        # through _cond so comparisons evaluate instead of leaking as text.
        # (&& binds tighter: split || first, then && inside each branch.)
        _or_parts = self._split_logic(s, "||")
        if len(_or_parts) > 1:
            return 1 if any(self._cond(p) for p in _or_parts) else 0
        _and_parts = self._split_logic(s, "&&")
        if len(_and_parts) > 1:
            return 1 if all(self._cond(p) for p in _and_parts) else 0
        # safe integer arithmetic with vars substituted
        try:
            tree = ast.parse(s, mode="eval")
            val = self._safe_eval(tree.body)
            return val
        except Exception:
            pass
        # comparisons / regex-match in value position: `ok := (a >= b)`.
        if _has_cmp_op(s):
            try:
                return 1 if self._cond(s) else 0
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
        import ast as _ast
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.List):
            return [self._safe_eval(e) for e in node.elts]
        if isinstance(node, ast.Subscript):
            base = self._eval_expr(_ast.unparse(node.value))
            idx = self._eval_expr(_ast.unparse(node.slice))
            try:
                return self._access(base, idx)
            except (TypeError, ValueError, IndexError, KeyError):
                raise ValueError("bad subscript")
        if isinstance(node, ast.Name):
            v = self.vars.get(node.id, 0)
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, (int, float)):
                return v
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
            try:
                return float(v)
            except (TypeError, ValueError):
                raise ValueError(f"non-numeric var {node.id}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = self._safe_eval(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.BinOp) and isinstance(node.op,
                (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)):
            a, b = self._safe_eval(node.left), self._safe_eval(node.right)
            # AHK auto-converts numeric strings: "00" * 3600 == 0, never
            # Python-style string repetition.
            try:
                a = self._numval(a) if isinstance(a, str) else a
                b = self._numval(b) if isinstance(b, str) else b
            except (TypeError, ValueError):
                raise ValueError("non-numeric operands")
            ops = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
                   ast.Div: _op.truediv, ast.FloorDiv: _op.floordiv, ast.Mod: _op.mod,
                   ast.Pow: _op.pow}
            return ops[type(node.op)](a, b)
        raise ValueError("unsupported expression")

    def _resolve(self, v):
        if isinstance(v, (int, float)):
            return v
        return self._eval_expr(v)

    @staticmethod
    def _split_ternary(s: str):
        """Split top-level `cond ? a : b`. Returns (c, a, b) or None."""
        depth, q, qi, ci = 0, None, -1, -1
        k = 0
        while k < len(s):
            ch = s[k]
            if ch == "`" and k + 1 < len(s):
                k += 2
                continue
            if q:
                if ch == q:
                    q = None
            elif ch in ('"', "'"):
                q = ch
            elif ch == "(" or ch == "[":
                depth += 1
            elif ch == ")" or ch == "]":
                depth = max(0, depth - 1)
            elif ch == "?" and depth == 0 and qi < 0:
                qi = k
            elif ch == ":" and depth == 0 and qi >= 0 and k > 0 \
                    and s[k - 1] not in (":", "=") \
                    and not s[k + 1:k + 2] == "=":
                ci = k
                break
            k += 1
        if qi > 0 and ci > qi:
            return s[:qi].strip(), s[qi + 1:ci].strip(), s[ci + 1:].strip()
        return None

    @staticmethod
    def _balanced(s: str) -> bool:
        depth, q = 0, None
        for ch in s:
            if q:
                if ch == q:
                    q = None
            elif ch in ('"', "'"):
                q = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return False
        return depth == 0 and q is None

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
        # strip one layer of wrapping parens: (x > 1)
        while len(cond) >= 2 and cond.startswith("(") and cond.endswith(")") \
                and self._balanced(cond[1:-1]):
            cond = cond[1:-1].strip()
        # || / && at top level (AHK v2 logical ops)
        for op, any_of in (("||", True), ("&&", False)):
            parts = self._split_logic(cond, op)
            if len(parts) > 1:
                vals = [self._cond(p) for p in parts]
                return any(vals) if any_of else all(vals)
        # leading negation: !x, !FileExist(f)
        if cond.startswith("!") and not cond.startswith("!="):
            return not self._cond(cond[1:].strip())
        # assignment-in-condition: (attr := FileExist(f)) -> assign + test
        m = re.match(r"^([A-Za-z_]\w*)\s*:=\s*(.+)$", cond)
        if m:
            self.vars[m.group(1)] = self._eval_expr(m.group(2).strip())
            return self._truthy(self.vars[m.group(1)])
        # regex match: haystack ~= "pattern" (AHK options like i)xxx) convert)
        m = re.match(r"^(.+?)\s*~=\s*(.+)$", cond, re.DOTALL)
        if m:
            import re as _re2
            hay = str(self._eval_expr(m.group(1).strip()))
            pat = str(self._eval_expr(m.group(2).strip()))
            mo = _re2.match(r"^([a-zA-Z]+)\)(.*)$", pat, _re2.DOTALL)
            flags, body = (0, pat)
            if mo:
                flags = _re2.IGNORECASE if "i" in mo.group(1).lower() else 0
                body = mo.group(2)
            try:
                return _re2.search(body, hay, flags) is not None
            except _re2.error:
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
                try:
                    lf, rf = float(lhs), float(rhs)
                    cmp = {"<": lf < rf, ">": lf > rf, "<=": lf <= rf,
                           ">=": lf >= rf, "=": lf == rf, "==": lf == rf,
                           "!=": lf != rf}[op]
                    return cmp
                except (TypeError, ValueError):
                    pass
                ls, rs = str(lhs), str(rhs)
                if op in ("=", "=="):
                    return ls == rs
                if op == "!=":
                    return ls != rs
                return False
        if cond.isdigit():
            return int(cond) != 0
        v = self._eval_expr(cond) if cond not in self.vars else self.vars.get(cond)
        return self._truthy(v)

    @staticmethod
    def _truthy(v) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, (list, dict)):
            return len(v) > 0
        return bool(v) and v != "0" and v != 0

    @staticmethod
    def _split_logic(cond: str, op: str) -> list:
        parts, depth, q, cur = [], 0, None, ""
        k = 0
        while k < len(cond):
            ch = cond[k]
            if q:
                cur += ch
                if ch == q:
                    q = None
            elif ch in ('"', "'"):
                q = ch
                cur += ch
            elif ch == "(":
                depth += 1
                cur += ch
            elif ch == ")":
                depth = max(0, depth - 1)
                cur += ch
            elif depth == 0 and cond.startswith(op, k):
                parts.append(cur)
                cur = ""
                k += len(op)
                continue
            else:
                cur += ch
            k += 1
        parts.append(cur)
        return [p.strip() for p in parts]
