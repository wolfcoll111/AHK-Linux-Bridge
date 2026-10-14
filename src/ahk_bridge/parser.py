"""MVP parser for an AHK v2 subset.

Supported (v0.2):
  #Requires AutoHotkey v2.0
  F1::            / F1::Send "hi"      (hotkeys, single + block form)
  :*:btw::by the way                  (hotstrings)
  Send/SendInput/SendEvent/SendPlay/SendText "text" (+ {Enter}{F1}... keys)
  Click [x, y] [left|right|middle] / MouseClick [, btn, x, y]
  MouseMove x, y
  Sleep ms-or-var
  Loop N-or-var { ... } / Loop { ... } (infinite until abort)
  While cond { ... }  (cond: truthy var or `x < N` compare, now with expr)
  If cond { ... } [Else { ... }] / Break / Continue
  x := expr  (int arithmetic, strings, Random(), vars)
  Name(args) { ... }  (function def) + Name(...) call
  MsgBox "text"  (-> log line)
  WinActivate "title" / PixelSearch (live via mss)
  Return (block terminator), ; comments
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any

HOTKEY_RE = re.compile(r'^\s*([A-Za-z0-9_^!+#<>*~$ ]+?)::\s*(.*)$')
HOTSTRING_RE = re.compile(r'^\s*:([^:]*):([^:]+)::\s*(.*)$')
FUNCDEF_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{\s*$')
LOOP_RE = re.compile(r'^\s*Loop(?:\s+(\S+))?\s*\{\s*$', re.IGNORECASE)
WHILE_RE = re.compile(r'^\s*While\s+(.+?)\s*\{\s*$', re.IGNORECASE)
IF_RE = re.compile(r'^\s*If\s+(.+?)\s*\{\s*$', re.IGNORECASE)
ELSE_RE = re.compile(r'^\s*(?:\}\s*)?Else\s*\{\s*$', re.IGNORECASE)


@dataclass
class Send:
    text: str

@dataclass
class Click:
    x: int | None = None
    y: int | None = None
    button: str = "left"
    count: int = 1

@dataclass
class MouseMove:
    x: int
    y: int

@dataclass
class Sleep:
    ms: Any  # int or var/expr string (resolved at runtime)


@dataclass
class Loop:
    count: Any  # int | str(var/expr) | None (None = infinite)
    body: list = field(default_factory=list)


@dataclass
class While:
    cond: str
    body: list = field(default_factory=list)


@dataclass
class If:
    cond: str
    then_body: list = field(default_factory=list)
    else_body: list = field(default_factory=list)


@dataclass
class Break:
    pass


@dataclass
class Continue:
    pass


@dataclass
class PixelSearch:
    color: str
    x1: Any = 0
    y1: Any = 0
    x2: Any = 0
    y2: Any = 0

@dataclass
class Assign:
    name: str
    value: Any

@dataclass
class FuncDef:
    name: str
    params: list
    body: list = field(default_factory=list)

@dataclass
class FuncCall:
    name: str
    args: list = field(default_factory=list)

@dataclass
class MsgBox:
    text: str

@dataclass
class WinActivate:
    title: str

@dataclass
class Hotkey:
    key: str
    body: list = field(default_factory=list)

@dataclass
class Hotstring:
    trigger: str
    replacement: str

@dataclass
class Script:
    requires: str | None = None
    auto_section: list = field(default_factory=list)
    hotkeys: list = field(default_factory=list)
    hotstrings: list = field(default_factory=list)
    functions: dict = field(default_factory=dict)


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _parse_args(argstr: str) -> list:
    parts, cur, q = [], "", None
    for ch in argstr:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in ('"', "'"):
            q = ch
            cur += ch
        elif ch == ",":
            parts.append(_unquote(cur))
            cur = ""
        else:
            cur += ch
    if cur.strip() != "" or argstr.strip() == "":
        if argstr.strip() != "":
            parts.append(_unquote(cur))
    return parts


def parse_statement(line: str):
    s = line.strip()
    if not s or s.startswith(";"):
        return None
    low = s.lower()
    if low in ("break", "break 1"):
        return Break()
    if low in ("continue"):
        return Continue()
    # Send family: Send / SendInput / SendEvent / SendPlay / SendText
    for prefix in ("sendtext ", "sendinput ", "sendevent ", "sendplay ", "send "):
        if low.startswith(prefix):
            return Send(_unquote(s[len(prefix):]))
    # bare Send("...") handled as FuncCall below; runtime maps it too.
    m = re.match(r'(?i)^MouseClick\s*(.*)$', s)
    if m:
        rest = m.group(1).strip()
        # MouseClick [, WhichButton, X, Y, ClickCount, ...] -> map to Click
        parts = [p.strip() for p in rest.split(",")] if rest else []
        button = "left"
        x = y = None
        count = 1
        if parts and parts[0].lower() in ("left", "right", "middle"):
            button = parts[0].lower()
            parts = parts[1:]
        nums = re.findall(r'-?\d+', rest)
        if len(nums) >= 2:
            # last two numbers are usually X, Y
            x, y = int(nums[-2]), int(nums[-1])
        if nums and button in rest.lower():
            pass
        return Click(x, y, button, count)
    m = re.match(r'(?i)^click\s*(.*)$', s)
    if m:
        rest = m.group(1).strip()
        x = y = None
        button = "left"
        nums = re.findall(r'-?\d+', rest)
        if len(nums) >= 2:
            x, y = int(nums[0]), int(nums[1])
        low = rest.lower()
        for b in ("right", "middle", "left"):
            if b in low:
                button = b
        return Click(x, y, button)
    m = re.match(r'(?i)^mousemove\s+(-?\d+)\s*,\s*(-?\d+)', s)
    if m:
        return MouseMove(int(m.group(1)), int(m.group(2)))
    m = re.match(r'(?i)^sleep\s+(.+)$', s)
    if m:
        raw_ms = m.group(1).strip().split(";")[0].strip()
        # keep raw for runtime var/expr resolution; int fast-path
        try:
            return Sleep(int(raw_ms))
        except ValueError:
            return Sleep(raw_ms)
    m = re.match(r'(?i)^msgbox\s*(.*)$', s)
    if m:
        return MsgBox(_unquote(m.group(1)))
    m = re.match(r'(?i)^winactivate\s*(.*)$', s)
    if m:
        return WinActivate(_unquote(m.group(1)))
    m = re.match(r'(?i)^pixelsearch\s*(.*)$', s)
    if m:
        # PixelSearch &Ox, &Oy, X1, Y1, X2, Y2, Color [, Variation]
        # v0.2: store color + box; runtime does live search via mss.
        rest = m.group(1).strip()
        parts = _parse_args(rest)
        color = parts[-2] if len(parts) >= 2 else (parts[-1] if parts else "0xFFFFFF")
        nums = re.findall(r'-?\d+|0[xX][0-9a-fA-F]+', rest)
        box = [0, 0, 0, 0]
        if len(nums) >= 5:
            # skip first two (&vars), take X1 Y1 X2 Y2
            try:
                box = [int(x, 0) for x in nums[2:6]]
            except ValueError:
                pass
        return PixelSearch(color=str(color), x1=box[0], y1=box[1], x2=box[2], y2=box[3])
    m = re.match(r'^\s*([A-Za-z_]\w*)\s*:=\s*(.+)$', s)
    if m:
        # Keep RAW expression for runtime eval (arithmetic, Random(), etc.).
        # Strip trailing comment.
        val = m.group(2).split(";")[0].strip()
        return Assign(m.group(1), val)
    m = re.match(r'^\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*$', s)
    if m:
        return FuncCall(m.group(1), _parse_args(m.group(2)))
    return FuncCall("__raw__", [s])  # unknown -> logged, non-fatal


def _parse_loop_count(raw: str | None):
    if raw is None:
        return None
    raw = raw.strip()
    try:
        return int(raw)
    except ValueError:
        # var name or expression -> resolve at runtime
        return raw


def _parse_block(lines: list[str], i: int):
    """Parse statements until `}` / `Return` / EOF. Returns (stmts, next_i)."""
    stmts: list = []
    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith(";"):
            i += 1
            continue
        if s == "}" or s.lower() == "return":
            return stmts, i + 1
        # Else on its own line after a closed If-block is handled by the
        # If-branch below (lookahead); a stray Else here closes this block.
        if re.match(r'(?i)^(?:\}\s*)?else\s*\{\s*$', s):
            return stmts, i  # let caller consume Else
        mf = FUNCDEF_RE.match(raw)
        if mf:
            params = [p.strip() for p in mf.group(2).split(",") if p.strip()]
            # strip & / default values: `&x, y := 1` -> x, y
            clean = []
            for p in params:
                p = p.lstrip("&").strip()
                p = p.split(":=")[0].strip().split("=")[0].strip()
                clean.append(p.split()[0])
            body, i = _parse_block(lines, i + 1)
            stmts.append(FuncDef(mf.group(1), clean, body))
            continue
        m = LOOP_RE.match(raw)
        if m:
            cnt = _parse_loop_count(m.group(1))
            body, i = _parse_block(lines, i + 1)
            stmts.append(Loop(cnt, body))
            continue
        m = WHILE_RE.match(raw)
        if m:
            body, i = _parse_block(lines, i + 1)
            stmts.append(While(m.group(1).strip(), body))
            continue
        m = IF_RE.match(raw)
        if m:
            cond = m.group(1).strip()
            then_body, i = _parse_block(lines, i + 1)
            else_body: list = []
            # consume `} Else {` split across lines: _parse_block stopped
            # BEFORE the Else line (returned i pointing at Else), or the
            # closing brace was consumed and next line is `Else {`.
            if i < n and re.match(r'(?i)^(?:\}\s*)?else\s*\{\s*$', lines[i].strip()):
                i += 1
                else_body, i = _parse_block(lines, i)
            stmts.append(If(cond, then_body, else_body))
            continue
        st = parse_statement(raw)
        if st is not None:
            stmts.append(st)
        i += 1
    return stmts, i


def parse_script(text: str) -> Script:
    sc = Script()
    lines = text.splitlines()
    # hoist #Requires
    for ln in lines:
        if ln.strip().lower().startswith("#requires"):
            sc.requires = ln.strip()
            break
    i, n = 0, len(lines)
    cur_hotkey: Hotkey | None = None
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith(";") or s.lower().startswith("#requires"):
            i += 1
            continue
        mh = HOTSTRING_RE.match(raw)
        if mh and cur_hotkey is None:
            sc.hotstrings.append(Hotstring(mh.group(2), mh.group(3)))
            i += 1
            continue
        mh = HOTKEY_RE.match(raw)
        # avoid misreading `x := ...` (no ::) — HOTKEY_RE needs :: so fine,
        # but guard against hotstring already handled above.
        if mh and cur_hotkey is None:
            key, rest = mh.group(1).strip(), mh.group(2).strip()
            hk = Hotkey(key)
            sc.hotkeys.append(hk)
            if rest:
                st = parse_statement(rest)
                if st is not None:
                    hk.body.append(st)
                i += 1
            else:
                i += 1
                if i < n and lines[i].strip() == "{":
                    i += 1  # brace style: F1::\n{
                body, i = _parse_block(lines, i + 1 - 1)
                hk.body = body
            cur_hotkey = None
            continue
        if s == "}" or s.lower() == "return":
            i += 1
            continue
        mf = FUNCDEF_RE.match(raw)
        if mf:
            params = [p.strip() for p in mf.group(2).split(",") if p.strip()]
            clean = []
            for p in params:
                p = p.lstrip("&").strip()
                p = p.split(":=")[0].strip().split("=")[0].strip()
                clean.append(p.split()[0])
            body, i = _parse_block(lines, i + 1)
            sc.functions[mf.group(1)] = FuncDef(mf.group(1), clean, body)
            continue
        m = LOOP_RE.match(raw)
        if m:
            cnt = _parse_loop_count(m.group(1))
            body, i = _parse_block(lines, i + 1)
            sc.auto_section.append(Loop(cnt, body))
            continue
        m = WHILE_RE.match(raw)
        if m:
            body, i = _parse_block(lines, i + 1)
            sc.auto_section.append(While(m.group(1).strip(), body))
            continue
        m = IF_RE.match(raw)
        if m:
            cond = m.group(1).strip()
            # _parse_block handles the Else lookahead internally when the
            # If is at block level; at top level replicate it here.
            then_body, ni = _parse_block(lines, i + 1)
            else_body: list = []
            if ni < n and re.match(r'(?i)^(?:\}\s*)?else\s*\{\s*$', lines[ni].strip()):
                ni += 1
                else_body, ni = _parse_block(lines, ni)
            sc.auto_section.append(If(cond, then_body, else_body))
            i = ni
            continue
        st = parse_statement(raw)
        if st is not None:
            sc.auto_section.append(st)
        i += 1
    return sc
