"""MVP parser for an AHK v2 subset.

Supported (v0.1):
  #Requires AutoHotkey v2.0
  F1::            / F1::Send "hi"      (hotkeys, single + block form)
  :*:btw::by the way                  (hotstrings)
  Send "text" / SendInput "text"
  Click [x, y] [left|right|middle]
  MouseMove x, y
  Sleep ms
  Loop N { ... } / Loop { ... } (infinite until abort)
  While cond { ... }  (cond: truthy var or `x < N` simple compare)
  x := expr  (int/str/var)
  Name(args) { ... }  (function def) + Name(...) call
  MsgBox "text"  (-> log line)
  WinActivate "title" / PixelSearch stubs (logged, non-fatal)
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
    ms: int

@dataclass
class Loop:
    count: int | None  # None = infinite
    body: list = field(default_factory=list)

@dataclass
class While:
    cond: str
    body: list = field(default_factory=list)

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
    if s.lower().startswith("sendinput "):
        return Send(_unquote(s[10:]))
    if s.lower().startswith("send "):
        return Send(_unquote(s[5:]))
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
    m = re.match(r'(?i)^sleep\s+(\d+)', s)
    if m:
        return Sleep(int(m.group(1)))
    m = re.match(r'(?i)^msgbox\s*(.*)$', s)
    if m:
        return MsgBox(_unquote(m.group(1)))
    m = re.match(r'(?i)^winactivate\s*(.*)$', s)
    if m:
        return WinActivate(_unquote(m.group(1)))
    m = re.match(r'^\s*([A-Za-z_]\w*)\s*:=\s*(.+)$', s)
    if m:
        val = m.group(2).strip()
        try:
            v: Any = int(val)
        except ValueError:
            v = _unquote(val)
        return Assign(m.group(1), v)
    m = re.match(r'^\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*$', s)
    if m:
        return FuncCall(m.group(1), _parse_args(m.group(2)))
    return FuncCall("__raw__", [s])  # unknown -> logged, non-fatal


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
        mf = FUNCDEF_RE.match(raw)
        if mf:
            params = [p.strip() for p in mf.group(2).split(",") if p.strip()]
            body, i = _parse_block(lines, i + 1)
            stmts.append(FuncDef(mf.group(1), params, body))
            continue
        m = LOOP_RE.match(raw)
        if m:
            cnt = None
            if m.group(1) is not None:
                try:
                    cnt = int(m.group(1))
                except ValueError:
                    cnt = None  # var/∞ -> treat as infinite in v0.1
            body, i = _parse_block(lines, i + 1)
            stmts.append(Loop(cnt, body))
            continue
        m = WHILE_RE.match(raw)
        if m:
            body, i = _parse_block(lines, i + 1)
            stmts.append(While(m.group(1).strip(), body))
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
            body, i = _parse_block(lines, i + 1)
            sc.functions[mf.group(1)] = FuncDef(mf.group(1), params, body)
            continue
        m = LOOP_RE.match(raw)
        if m:
            cnt = None
            if m.group(1) is not None:
                try:
                    cnt = int(m.group(1))
                except ValueError:
                    cnt = None
            body, i = _parse_block(lines, i + 1)
            sc.auto_section.append(Loop(cnt, body))
            continue
        m = WHILE_RE.match(raw)
        if m:
            body, i = _parse_block(lines, i + 1)
            sc.auto_section.append(While(m.group(1).strip(), body))
            continue
        st = parse_statement(raw)
        if st is not None:
            sc.auto_section.append(st)
        i += 1
    return sc
