"""AHK v2 subset parser (v0.3: NatroMacro-hardened).

Single-line hotkeys, hotstrings, Send family + {Key} vocabulary, Click/
MouseClick (expr coords), MouseMove (expr), Sleep (var/expr), Loop N/var +
Loop Parse + v1 `Loop, N` tolerance, While, If (+single-line form, Else If
chains), Break/Continue, Switch/Case/Default, For (int/list/StrSplit, else
skip-log), Try/Catch/Finally (control flow never swallowed), x := expr
(arithmetic, strings, Random(), StrSplit/SubStr/InStr/..., function calls,
[...] literals, .Length), user functions + Return value, MsgBox, IniRead/
IniWrite (real), WinActivate/PixelSearch, CoordMode/SendMode/Set* directives
(logged), #Include (logged), global/static/local (no-ops), labels (skipped),
`;` comments, continuation-line joining.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any

HOTKEY_RE = re.compile(r'^\s*([A-Za-z0-9_^!+#<>*~$ ]+?)::\s*(.*)$')
HOTSTRING_RE = re.compile(r'^\s*:([^:]*):([^:]+)::\s*(.*)$')
FUNCDEF_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{\s*$')
CLASS_RE = re.compile(r'^\s*class\s+([A-Za-z_]\w*)(?:\s+extends\s+([A-Za-z_]\w*))?\s*$', re.IGNORECASE)
METHODDEF_RE = re.compile(r'^\s*(?:static\s+|public\s+|private\s+)*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{\s*$')
STATIC_ASSIGN_RE = re.compile(r'^\s*static\s+([A-Za-z_]\w*\s*:=.+)$', re.IGNORECASE)
LOOP_RE = re.compile(r'^\s*Loop\s*,?\s*(.+?)\s*(\{\s*)?$', re.IGNORECASE)
LOOP_BARE_RE = re.compile(r'^\s*Loop\s*,?\s*(\{\s*)?$', re.IGNORECASE)
LOOPPARSE_RE = re.compile(r'^\s*Loop\s+Parse\s*,?\s*(.*?)\s*(\{\s*)?$', re.IGNORECASE)
LOOPFILES_RE = re.compile(r'^\s*Loop\s+Files\s*,?\s*(.*?)\s*(\{\s*)?$', re.IGNORECASE)
FOR_RE = re.compile(r'^\s*For(?=\s|\()(.+?)\s+in\s+(.+?)\s*(\{\s*)?$', re.IGNORECASE)
WHILE_RE = re.compile(r'^\s*While(?=\s|\()(.+?)\s*(\{\s*)?$', re.IGNORECASE)
DO_RE = re.compile(r'^\s*Do\s*(\{\s*)?$', re.IGNORECASE)
UNTIL_RE = re.compile(r'^\s*(?:\}\s*)?Until\s+(.+?)\s*$', re.IGNORECASE)
IF_RE = re.compile(r'^\s*If(?=\s|\()(.+?)\s*(\{\s*)?$', re.IGNORECASE)
IF_SINGLE_RE = re.compile(r'^\s*If(?=\s|\()(.+?)\s*$', re.IGNORECASE)
ELSEIF_RE = re.compile(r'^\s*(?:\}\s*)?Else\s+If(?=\s|\()(.+?)\s*(\{\s*)?$', re.IGNORECASE)
ELSE_RE = re.compile(r'^\s*(?:\}\s*)?Else\s*\{\s*$', re.IGNORECASE)
SWITCH_RE = re.compile(r'^\s*Switch(?=\s|\()(.+?)\s*(\{\s*)?$', re.IGNORECASE)
CASE_RE = re.compile(r'^\s*Case\s+(.+?)\s*:\s*$', re.IGNORECASE)
DEFAULT_RE = re.compile(r'^\s*Default\s*:\s*$', re.IGNORECASE)
TRY_RE = re.compile(r'^\s*Try\s*(\{\s*)?$', re.IGNORECASE)
CATCH_RE = re.compile(r'^\s*(?:\}\s*)?Catch(?:\s+(?:as\s+)?(\w+))?\s*(\{\s*)?$', re.IGNORECASE)
FINALLY_RE = re.compile(r'^\s*(?:\}\s*)?Finally\s*(\{\s*)?$', re.IGNORECASE)
LABEL_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*:\s*$')
LEGACY_CMD_RE = re.compile(r'^\s*(PostMessage|SendMessage|Run|RunWait|WinShow|WinHide|WinMinimize|WinMaximize|WinRestore|WinClose|WinKill|WinMove|ProcessClose|FileDelete|FileAppend|FileRead|FileCopy|FileMove|FileCreateShortcut|DirCreate|DirDelete|RegRead|RegWrite|RegDelete|ToolTip|TrayTip|SoundBeep|SoundPlay|ClipWait|Reload|Pause|Suspend|Edit|ListVars|KeyHistory|DetectHiddenText|SetCapsLockState|SetNumLockState|SetScrollLockState|BlockInput|Shutdown|Exit|Gosub|Goto|Sleep|Hotkey|Hotstring|SetTimer|SplitPath|SysGet|DriveGet|FileGetTime|FileGetSize|FileSetTime|IniDelete|MouseGetPos|MouseClickDrag|WinGetPos|WinGetTitle|WinGetText|WinGetClientPos|WinSetTransparent|MonitorGetWorkArea|ControlGetPos|ControlGetText|PixelGetColor)\b\s*,?\s*(.*)$', re.IGNORECASE)
SETTING_RE = re.compile(r'^\s*(CoordMode|SendMode|SetWorkingDir|DetectHiddenWindows|SetTitleMatchMode|SetKeyDelay|SetMouseDelay|SetBatchLines|SetDefaultMouseSpeed|SetControlDelay|SetWinDelay|ListLines|ProcessSetPriority|Thread|Critical|KeyHistory|#Warn|#MaxThreads|#SingleInstance|#Requires|#HotIf|#NoTrayIcon|#NoEnv|#Persistent|#UseHook|#InstallKeybdHook|#InstallMouseHook|#MenuMaskKey|#Hotstring|#InputLevel)\b\s*(.*)$', re.IGNORECASE)
INCLUDE_RE = re.compile(r'^\s*#Include(?:Again)?\s+(.*)$', re.IGNORECASE)
DECL_RE = re.compile(r'^\s*(global|static|local)\b\s*(.*)$', re.IGNORECASE)

# Statements that look like `Name(...) {` but are control flow, never a FuncDef.
_KEYWORDS = frozenset({
    "if", "else", "for", "while", "loop", "switch", "case", "default",
    "try", "catch", "finally", "return", "sleep", "send", "sendinput",
    "sendevent", "sendplay", "sendtext", "click", "mouseclick", "mousemove",
    "msgbox", "winactivate", "pixelsearch", "keywait", "iniwrite", "iniread",
    "throw", "exitapp", "class", "__raw__",
})


@dataclass
class Send:
    text: str

@dataclass
class Click:
    x: Any = None
    y: Any = None
    button: str = "left"
    count: int = 1
    opts: str = ""


@dataclass
class MouseMove:
    x: Any
    y: Any
    speed: Any = None

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
class DoUntil:
    cond: str
    body: list = field(default_factory=list)


@dataclass
class If:
    cond: str
    then_body: list = field(default_factory=list)
    else_body: list = field(default_factory=list)


@dataclass
class Break:
    level: int = 1


@dataclass
class Continue:
    level: int = 1


@dataclass
class PixelSearch:
    color: str
    x1: Any = 0
    y1: Any = 0
    x2: Any = 0
    y2: Any = 0


@dataclass
class Return:
    value: Any = None


@dataclass
class ScopeDecl:
    kind: str  # global | static | local
    names: list = field(default_factory=list)


@dataclass
class Switch:
    value: str
    cases: list = field(default_factory=list)  # [(cond_str|None, body)]


@dataclass
class For:
    targets: list  # 1-2 loop var names
    iterable: str
    body: list = field(default_factory=list)


@dataclass
class Try:
    try_body: list = field(default_factory=list)
    catch_var: str | None = None
    catch_body: list = field(default_factory=list)
    finally_body: list = field(default_factory=list)
    else_body: list = field(default_factory=list)


@dataclass
class LoopParse:
    text: str
    delims: str = ""
    body: list = field(default_factory=list)


@dataclass
class LoopFiles:
    pattern: str
    body: list = field(default_factory=list)


@dataclass
class KeyWait:
    key: str
    options: str = ""


@dataclass
class Seq:
    items: list = field(default_factory=list)


@dataclass
class CompoundAssign:
    name: str
    op: str
    value: Any


@dataclass
class IncDec:
    name: str
    delta: int  # +1 / -1


@dataclass
class Throw:
    value: Any = None


@dataclass
class ExitApp:
    code: Any = 0


@dataclass
class LegacyCmd:
    name: str
    rest: str = ""


@dataclass
class IniOp:
    op: str  # read | write
    value: Any = None
    filename: str = ""
    section: str = ""
    key: str = ""


@dataclass
class Setting:
    name: str
    args: str = ""


@dataclass
class Include:
    path: str

@dataclass
class Assign:
    name: str
    value: Any


@dataclass
class AssignTarget:
    target: str  # e.g. arr[i], obj.prop, a[i][k]
    value: Any


@dataclass
class ExprStmt:
    """Side-effecting expression statement: `cond ? A() : B()`.
    Evaluated and discarded (AHK v2 expression-statement semantics)."""
    expr: str


@dataclass
class DynCall:
    """Expression callee: `(%"nm_" i%)()` — head evaluates to a function
    name (main-loop dispatch over priorityList)."""
    head: str
    args: list

@dataclass
class FuncDef:
    name: str
    params: list
    body: list = field(default_factory=list)


@dataclass
class Class:
    name: str
    base: str | None = None
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
    parts, cur, q, depth = [], "", None, 0
    for ch in argstr:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in ('"', "'"):
            q = ch
            cur += ch
        elif ch in "([":
            depth += 1
            cur += ch
        elif ch in ")]":
            depth = max(0, depth - 1)
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(_unquote(cur))
            cur = ""
        else:
            cur += ch
    if cur.strip() != "" or argstr.strip() == "":
        if argstr.strip() != "":
            parts.append(_unquote(cur))
    return parts


def _strip_comment(line: str) -> str:
    """Cut `;` comments (AHK: `;` starts a comment at line start or after
    whitespace, never inside quotes; backtick escapes honored)."""
    q = None
    k = 0
    while k < len(line):
        ch = line[k]
        if ch == "`" and k + 1 < len(line):
            k += 2
            continue
        if q:
            if ch == q:
                q = None
        elif ch in ('"', "'"):
            q = ch
        elif ch == ";" and (k == 0 or line[k - 1] in (" ", "\t")):
            return line[:k]
        k += 1
    return line


def _is_dyn_target(t: str) -> bool:
    """Linear check: target is `Name` / `%Name%` segments glued together
    (`hour_%status%_time`, `%j%_time`, `Style`). Each branch consumes at
    least one char with no ambiguity, so no backtracking blowup."""
    if not t:
        return False
    k, n = 0, len(t)
    while k < n:
        ch = t[k]
        if ch == "%":
            j = t.find("%", k + 1)
            if j < 0:
                return False
            if not re.fullmatch(r"[A-Za-z_]\w*", t[k + 1:j]):
                return False
            k = j + 1
        elif ch.isalpha() or ch == "_":
            k += 1
            while k < n and (t[k].isalnum() or t[k] == "_"):
                k += 1
        else:
            return False
    return True


def _split_top_ternary(s: str):
    """Top-level `cond ? a : b` STATEMENT shape (dispatch with side
    effects). Conservative: exactly one top-level `?` and one top-level
    `:` with all parts non-empty; `:=`/`::` in the head disqualify
    (assigns, labels). Nested/mixed shapes stay raw (status quo)."""
    qparts = _split_top(s, "?")
    if len(qparts) != 2 or not qparts[0].strip():
        return None
    if ":=" in qparts[0] or "::" in qparts[0]:
        return None
    cparts = _split_top(qparts[1], ":")
    if len(cparts) != 2 or not cparts[0].strip() or not cparts[1].strip():
        return None
    return s.strip()


def _scan_balanced(s: str, k: int, open_ch: str, close_ch: str):
    """Index just past the matching closer for the opener at s[k]
    (quote- and backtick-aware), or -1. Linear, no nesting."""
    depth, q = 0, None
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
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return k + 1
        k += 1
    return -1


def _is_bare_index_read(s: str) -> bool:
    """`Name[...][...]` covering the whole statement (linear scan).
    Anything with parens/operators beyond the brackets is not bare."""
    k = 0
    while k < len(s) and s[k] in " \t":
        k += 1
    if k >= len(s) or not (s[k].isalpha() or s[k] == "_"):
        return False
    k += 1
    while k < len(s) and (s[k].isalnum() or s[k] == "_"):
        k += 1
    if k >= len(s) or s[k] != "[":
        return False
    while k < len(s) and s[k] == "[":
        after = _scan_balanced(s, k, "[", "]")
        if after < 0:
            return False
        k = after
    return s[k:].strip() == ""


def _match_call(s: str):
    """Match `Name(args)` / `Obj.Method(args)` with balanced parens.
    Returns (name, argstr, rest) or None. Trailing `.Method(...)` chains are
    kept as part of rest for the caller to decide.

    The head is scanned linearly (not regexed): besides `Name` and
    `.Name` segments it accepts v1 `%Name%` segments
    (`nm_Tab%tab%%c%()`) and `[...]` indexers
    (`MainGui["X"].OnEvent(...)`). A regex alternation here would nest
    quantifiers and backtrack catastrophically on long lines."""
    k = 0
    while k < len(s) and s[k] in " \t":
        k += 1
    if k >= len(s) or not (s[k].isalpha() or s[k] == "_"):
        return None
    start = k
    while k < len(s):
        ch = s[k]
        if ch.isalpha() or ch == "_":
            k += 1
            while k < len(s) and (s[k].isalnum() or s[k] == "_"):
                k += 1
        elif ch == "%":
            j = s.find("%", k + 1)
            if j < 0 or not re.fullmatch(r"[A-Za-z_]\w*", s[k + 1:j]):
                return None
            k = j + 1
        elif ch == "[":
            after = _scan_balanced(s, k, "[", "]")
            if after < 0:
                return None
            k = after
        elif ch == "." and k + 1 < len(s) and (s[k + 1].isalpha() or s[k + 1] == "_"):
            k += 1  # `.Name` glued (a `.` with space after is concat, not a call)
        else:
            break
    head = s[start:k]
    m = re.match(r"\s*\(", s[k:])
    if not m:
        return None
    paren = k + m.end() - 1
    after = _scan_balanced(s, paren, "(", ")")
    if after < 0:
        return None
    return head, s[paren + 1:after - 1], s[after:].strip()


def _match_dyncall(s: str):
    """Expression callee `(head_expr)(args)` with balanced groups, or None.
    `(cond) ? a : b` / `(a)+(b)` do not match (tail must open with `(` and
    close at the end). Linear scans only."""
    st = s.strip()
    if not st.startswith("("):
        return None
    head_end = _scan_balanced(st, 0, "(", ")")
    if head_end < 0:
        return None
    rest = st[head_end:].strip()
    if not rest.startswith("("):
        return None
    args_end = _scan_balanced(rest, 0, "(", ")")
    if args_end < 0 or rest[args_end:].strip() != "":
        return None
    head = st[1:head_end - 1].strip()
    if not head:
        return None
    argstr = rest[1:args_end - 1]
    args = [p.strip() for p in _split_seq(argstr)] if argstr.strip() else []
    return head, [p for p in args if p != ""]


def _scan_chain(rest: str):
    """Consume leading `.Method(...)` groups from a call tail with balanced
    paren scans (linear). Returns ([method names], remainder index).
    Unlike the old greedy regex, a trailing `, next()` Seq is preserved
    instead of being swallowed into the chain."""
    names, k, n = [], 0, len(rest)
    while k < n:
        dm = re.match(r"\.([A-Za-z_]\w*)\s*\(", rest[k:])
        if not dm:
            break
        after = _scan_balanced(rest, k + dm.end() - 1, "(", ")")
        if after < 0:
            break
        names.append(dm.group(1))
        k = after
    return names, k


def _split_seq(s: str) -> list:
    """Split top-level comma-separated statements (AHK `a(), b()`)."""
    parts, depth, q, cur = [], 0, None, ""
    k = 0
    while k < len(s):
        ch = s[k]
        if ch == "`" and k + 1 < len(s):
            cur += s[k:k + 2]
            k += 2
            continue
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in ('"', "'"):
            q = ch
            cur += ch
        elif ch in "([":
            depth += 1
            cur += ch
        elif ch in ")]":
            depth = max(0, depth - 1)
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        k += 1
    parts.append(cur)
    return parts


def _balanced_parens(s: str) -> bool:
    depth, q = 0, None
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
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return False
        k += 1
    return depth == 0 and q is None


def _is_wrapping_parens(s: str) -> bool:
    """True only when the FIRST `(` pairs with the LAST char (linear).
    `(x)` wraps; `(a) && b` and `(cond) ? a : b` do not, even though
    both are balanced overall."""
    if len(s) < 2 or not s.startswith("(") or not s.endswith(")"):
        return False
    depth, q, k = 0, None, 0
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
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
            if depth == 0 and k < len(s) - 1:
                return False  # closed before the end: not wrapping
        k += 1
    return depth == 0 and q is None


def _split_top(s: str, op: str):
    """Split on operator at depth 0 outside quotes (backtick-aware)."""
    parts, depth, q, cur = [], 0, None, ""
    k = 0
    while k < len(s):
        ch = s[k]
        if ch == "`" and k + 1 < len(s):
            cur += s[k:k + 2]
            k += 2
            continue
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in ('"', "'"):
            q = ch
            cur += ch
        elif ch in "([":
            depth += 1
            cur += ch
        elif ch in ")]":
            depth = max(0, depth - 1)
            cur += ch
        elif depth == 0 and s.startswith(op, k):
            parts.append(cur)
            cur = ""
            k += len(op)
            continue
        else:
            cur += ch
        k += 1
    parts.append(cur)
    return parts


def parse_statement(line: str):
    s = _strip_comment(line).strip()
    if not s or s.startswith(";"):
        return None
    low = s.lower()
    m = re.match(r'(?i)^(break|continue)(?:\s+(\d+))?$', s)
    if m:
        try:
            lvl = int(m.group(2)) if m.group(2) else 1
        except ValueError:
            lvl = 1
        return (Break(lvl) if m.group(1).lower() == "break" else Continue(lvl))
    # AHK continuation-section text block opener: `(LTrim Join...` etc.
    # After line-joining the whole block is one logical line; its content is
    # literal text (MsgBox bodies, generated scripts), not executable code.
    if re.match(r'^\((LTrim|RTrim|Join|Comments?)(?:\s|\)|,)', s, re.IGNORECASE):
        return Setting("ContinuationSection", s[:60])
    # Send family: Send / SendInput / SendEvent / SendPlay / SendText
    for prefix in ("sendtext ", "sendinput ", "sendevent ", "sendplay ", "send "):
        if low.startswith(prefix):
            rest = s[len(prefix):]
            chunks = [c.strip() for c in _split_seq(rest)]
            chunks = [c for c in chunks if c != ""]
            if len(chunks) > 1:
                items = []
                items.append(Send(_unquote(chunks[0])))
                for chunk in chunks[1:]:
                    sub = parse_statement(chunk)
                    if sub is not None:
                        items.append(sub)
                return Seq(items)
            return Send(_unquote(rest))
    # bare Send("...") handled as FuncCall below; runtime maps it too.
    m = re.match(r'(?i)^MouseClick(?!Drag)\s*(.*)$', s)
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
        count = 1
        # coords may be literals or var/expr (kept raw, resolved at runtime)
        parts = [p.strip() for p in rest.split(",")] if rest else []
        nums = [p for p in parts if re.match(r'^-?\d+$', p)]
        exprs = [p for p in parts if not re.match(r'^-?\d+$', p)
                 and p.lower() not in ("left", "right", "middle")]
        if len(nums) >= 2:
            x, y = int(nums[0]), int(nums[1])
        elif len(exprs) >= 2:
            x, y = exprs[0], exprs[1]
        elif rest and not parts:
            pass
        if re.match(r'^[A-Za-z_]\w*$', rest):
            return Click(None, None, button, count, opts=rest)
        low2 = rest.lower()
        for b in ("right", "middle", "left"):
            if b in low2:
                button = b
        return Click(x, y, button, count)
    m = re.match(r'(?i)^mousemove\s+(.+)$', s)
    if m:
        parts = [p.strip().split(";")[0].strip() for p in m.group(1).split(",")]
        def _num_or_raw(p):
            try:
                return int(p)
            except (ValueError, TypeError):
                return p
        x = _num_or_raw(parts[0]) if len(parts) > 0 else 0
        y = _num_or_raw(parts[1]) if len(parts) > 1 else 0
        spd = _num_or_raw(parts[2]) if len(parts) > 2 else None
        return MouseMove(x, y, spd)
    m = re.match(r'(?i)^sleep\s+(.+)$', s)
    if m:
        raw_ms = m.group(1).strip().split(";")[0].strip()
        # keep raw for runtime var/expr resolution; int fast-path
        try:
            return Sleep(int(raw_ms))
        except ValueError:
            return Sleep(raw_ms)
    m = re.match(r'(?i)^keywait\s*(.*)$', s)
    if m:
        parts = _parse_args(m.group(1))
        return KeyWait(_unquote(parts[0]) if parts else "",
                       _unquote(parts[1]) if len(parts) > 1 else "")
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
    m = re.match(r'(?i)^return\b\s*(.*)$', s)
    if m:
        val = m.group(1).split(";")[0].strip()
        return Return(val if val else None)
    m = DECL_RE.match(s)
    if m:
        names = [p.strip().lstrip("&").split(":=")[0].split("=")[0].strip()
                 for p in m.group(2).split(",") if p.strip()]
        return ScopeDecl(m.group(1).lower(), [x for x in names if x])
    m = re.match(r'(?i)^iniwrite\s+(.*)$', s)
    if m:
        # _split_seq (not _parse_args): keeps quotes so runtime evals values
        parts = [p.strip() for p in _split_seq(m.group(1))]
        while len(parts) < 4:
            parts.append("")
        return IniOp("write", parts[0], parts[1],
                     parts[2], parts[3].split()[0] if parts[3].split() else "")
    m = re.match(r'(?i)^iniread\s+(.*)$', s)
    if m:
        parts = [p.strip() for p in _split_seq(m.group(1))]
        while len(parts) < 4:
            parts.append("")
        return IniOp("read", parts[0], parts[1],
                     parts[2], parts[3].split()[0] if parts[3].split() else "")
    m = SETTING_RE.match(s)
    if m:
        return Setting(m.group(1), m.group(2).strip())
    m = INCLUDE_RE.match(s)
    if m:
        return Include(_unquote(m.group(1).strip()))
    m = LABEL_RE.match(s)
    if m and m.group(1).lower() not in ("if", "else", "for", "while", "loop",
                                        "switch", "case", "default", "try",
                                        "catch", "finally", "return"):
        # Gosub-style label: execution target only, skip at runtime.
        return Setting("Label", m.group(1))
    m = re.match(r'(?i)^throw\b\s*(.*)$', s)
    if m:
        val = m.group(1).strip()
        return Throw(val if val else None)
    m = re.match(r'(?i)^exitapp\b\s*(.*)$', s)
    if m:
        val = m.group(1).strip()
        try:
            return ExitApp(int(val) if val else 0)
        except ValueError:
            return ExitApp(val if val else 0)
    # Compound assignment, incl. v1 dynamic `%var%` segments in the target
    # (`hour_%status%_time += m-i`, `PlanterHarvestTime%A_Index% += ...`)
    # and bitwise `|=` / `&=` (`Style |= 8` in Gdip text rendering).
    # NOTE: the target match below is deliberately a flat char class —
    # a nested `(?:Name|%Name%)+` group backtracks catastrophically on
    # long lines (3.4s on 73 chars, measured). Structure is validated
    # by the linear scan in _is_dyn_target.
    m = re.match(r'^\s*([A-Za-z_%][\w%]*)\s*(\+=|-=|\*=|//=|/=|\.=|\|=|&=)\s*(.+)$', s)
    if m and _is_dyn_target(m.group(1)):
        return CompoundAssign(m.group(1), m.group(2), m.group(3).strip())
    m = re.match(r'^\s*([A-Za-z_]\w*)\s*(\+\+|--)\s*$', s)
    if m:
        return IncDec(m.group(1), 1 if m.group(2) == "++" else -1)
    m = re.match(r'^\s*(\+\+|--)\s*([A-Za-z_]\w*)\s*$', s)
    if m:
        return IncDec(m.group(2), 1 if m.group(1) == "++" else -1)
    m = LEGACY_CMD_RE.match(s)
    if m and not re.match(r'^\s*:?=', m.group(2)):
        return LegacyCmd(m.group(1), m.group(2).strip())
    # short-circuit statement forms: A && B / A || B, incl. N-ary chains
    # (`IsSet(x) && ok && cleanup()` runs cleanup only if all hold).
    # Skipped when the head is an assignment: `x := a && b` assigns the
    # whole conjunction. (A trailing `&& x := v` guard-target is fine.)
    for _op, _neg in (("||", True), ("&&", False)):
        _parts = _split_top(s, _op)
        if len(_parts) >= 2 and all(p.strip() for p in _parts) \
                and len(_split_top(_parts[0], ":=")) == 1:
            _codes = [_strip_comment(p).strip() for p in _parts]
            if all(_codes):
                _node = parse_statement(_codes[-1])
                for _p in reversed(_codes[:-1]):
                    _c = f"!({_p})" if _neg else _p
                    _node = If(_c, [_node] if _node is not None else [])
                return _node
    # fully parenthesized statement: (stmt) -> inner, but ONLY when the
    # outer parens are a true wrapping pair. `_balanced_parens(s)` alone
    # is not enough: `(cond) ? a : b` is balanced yet stripping mangles
    # it into `cond) ? a : b(`. The first `(` must not close before the
    # final char (linear scan, no nesting).
    if s.startswith("(") and s.endswith(")") and _is_wrapping_parens(s):
        _inner = parse_statement(s[1:-1].strip())
        if _inner is not None and not (
                isinstance(_inner, FuncCall) and _inner.name == "__raw__"):
            return _inner
    m = re.match(r'^\s*([A-Za-z_]\w*)\s*:=\s*(.+)$', s)
    if m:
        # Keep RAW expression for runtime eval (arithmetic, Random(), etc.).
        # Strip trailing comment.
        val = m.group(2).split(";")[0].strip()
        return Assign(m.group(1), val)
    # Ternary dispatch statement: `(v.type = "str") ? UpdateStr(...) : ...`
    # (Status.ahk command router). Evaluated for side effects at runtime.
    t3 = _split_top_ternary(s)
    if t3 is not None:
        return ExprStmt(t3)
    # Bare indexed read as existence probe: `MainGui[var]` inside
    # try/catch (evaluated and discarded; never throws here, so a
    # following try-`else` takes the same path as AHK's no-throw case).
    if re.match(r"^[A-Za-z_]\w*\[", s) and _is_bare_index_read(s):
        return ExprStmt(s.strip())
    mc = _match_call(s)
    if mc is not None:
        name, argstr, rest = mc
        # NOTE: _split_seq (not _parse_args): keeps quotes so runtime eval
        # sees "str" vs identifier. All call args are evaluated at runtime.
        raw_args = [p.strip() for p in _split_seq(argstr)] if argstr.strip() else []
        # Gdip_* signatures are positional and callers omit middle arguments
        # (`Gdip_ImageSearch(hay, needle, &out, , , , , 5)`).  Keep the empty
        # slots so 5 lands on Variation, not on OuterX1.
        if not name.startswith("Gdip_"):
            raw_args = [p for p in raw_args if p != ""]
        if rest.startswith("=>"):
            # fat-arrow definition: Name(params) => expr
            _params = []
            for _a in _parse_args(argstr):
                _seg = str(_a).lstrip("&").strip().split(":=")[0].split("=")[0].strip()
                _seg = _seg.rstrip("?*").strip()
                if _seg.split():
                    _params.append(_seg.split()[0])
            _expr = rest[2:].strip()
            return FuncDef(name, _params, [Return(_expr if _expr else None)])
        # dotted method chain glued to THIS call: `obj.M().N()` (rest starts
        # with `.`). A `.` appearing later (`, obj.M()`) is a new statement,
        # handled by the `,` branch below — never a chain.
        if rest.startswith("."):
            chained, _rk = _scan_chain(rest)
            if chained:
                name = name + "+" + "+".join(chained)
                rest = rest[_rk:].strip()
            if rest.startswith(","):
                pass  # chain + more statements: fall into Seq below
            elif rest:
                return FuncCall("__raw__", [s])
        if rest.startswith(","):
            items = [FuncCall(name, raw_args)]
            for chunk in _split_seq(rest[1:]):
                sub = parse_statement(chunk.strip())
                if sub is not None:
                    items.append(sub)
            if len(items) > 1:
                return Seq(items)
            return items[0]
        if rest:
            return FuncCall("__raw__", [s])
        # plain + dotted calls (Obj.Method), balanced nested parens included
        return FuncCall(name, raw_args)
    m = re.match(r'^(.+?)\s*:=\s*(.+)$', s)
    if m and ":=" not in m.group(1):
        # complex targets: arr[i] := v, obj.prop := v (calls handled above)
        return AssignTarget(m.group(1).strip(), m.group(2).split(";")[0].strip())
    # expression callee: `(%"nm_" i%)()` main-loop dispatch.
    dc = _match_dyncall(s)
    if dc is not None:
        return DynCall(dc[0], dc[1])
    return FuncCall("__raw__", [s])  # unknown -> logged, non-fatal


def _parse_loop_count(raw: str | None):
    if raw is None:
        return None
    raw = raw.strip().lstrip(",").strip()
    # v1 legacy %var% deref
    if len(raw) >= 2 and raw.startswith("%") and raw.endswith("%"):
        raw = raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        # var name or expression -> resolve at runtime
        return raw


def _parse_single_or_block(lines: list[str], i: int):
    """Body is either `{ ... }` or the single next statement.
    Returns (body, next_i, self_closed): self_closed is True only when the
    body consumed its own lone-`}` closer (matters for dangling-else)."""
    n = len(lines)
    while i < n and (not lines[i].strip() or lines[i].strip().startswith(";")):
        i += 1
    if i < n and lines[i].strip() == "{":
        return _parse_block(lines, i + 1)
    if i < n:
        # `{ <stmt> ...` — brace and first statement share one line.
        mo = re.match(r'^\{\s*(.+)$', _strip_comment(lines[i]).strip())
        if mo:
            first = parse_statement(mo.group(1))
            rest, ni, closed = _parse_block(lines, i + 1)
            return ([first] if first is not None else []) + rest, ni, closed
        node, ni = _parse_case_statement(lines, i)
        return ([node] if node is not None else [], ni, False)
    return [], i, False


def _skip_blank(lines: list[str], i: int) -> int:
    """Next index holding real code (skips blanks and `;` comment lines).
    Follower keywords (`else`, `catch`, `until`...) routinely sit behind
    blank lines or `;` remarks in the wild."""
    n = len(lines)
    while i < n and (not lines[i].strip() or lines[i].strip().startswith(";")):
        i += 1
    return i


def _parse_else_tail(lines: list[str], i: int, then_closed: bool = False,
                     braceless: bool = False):
    """Consume `} Else If .. {`, `} Else {`, or bare `Else` (+ single stmt).
    Returns (else_body, next_i). ElseIf chains recurse into If nodes.

    then_closed: the then-body already consumed its own lone-`}` closer. A
    `}`-led else line then closes the ENCLOSING block instead — it is not
    ours (dangling-else). Bare `else` (no leading brace) still attaches.
    braceless: the then-body was a single statement (`if x` newline `y`). A
    following `} else {` belongs to the enclosing block, never to this
    braceless if (otherwise the outer else is stolen and the enclosing
    block's closing brace is consumed — this swallowed Natro's nm_Reset
    following functions)."""
    n = len(lines)
    i = _skip_blank(lines, i)
    if i >= n:
        return [], i
    code = _strip_comment(lines[i]).strip()
    if code.startswith("}") and (then_closed or braceless):
        return [], i
    m = ELSEIF_RE.match(code)
    if m:
        cond = m.group(1).strip()
        then_body, i, closed = _body_after_opener(lines, i + 1, _has_brace(code))
        tail, i = _parse_else_tail(lines, i, closed,
                                    braceless=not _has_brace(code))
        return [If(cond, then_body, tail)], i
    if ELSE_RE.match(code):
        return _parse_block(lines, i + 1)[:2]
    # braceless `else if (cond)` + single statement (also `else if(`)
    me = re.match(r'^\s*(?:\}\s*)?Else\s+If(?=\s|\()(.+?)\s*$', code, re.IGNORECASE)
    if me and not _has_brace(code):
        body, i, closed = _parse_single_or_block(lines, i + 1)
        tail, i = _parse_else_tail(lines, i, closed)
        return [If(me.group(1).strip(), body, tail)], i
    # single-line `else <statement>` (not else-if): `else throw ...`
    me2 = re.match(r'^\s*(?:\}\s*)?Else\s+(.+)$', code, re.IGNORECASE)
    if me2 and not re.match(r'(?i)^\s*if\b', me2.group(1)) and not _has_brace(code):
        st = parse_statement(me2.group(1))
        return ([st] if st is not None else []), i + 1
    s = code
    if re.match(r'^\s*(?:\}\s*)?else\s*$', code, re.IGNORECASE):
        body, ni, _ = _parse_single_or_block(lines, i + 1)
        return body, ni
    return [], i


def _parse_switch(lines: list[str], i: int, value: str):
    """After `Switch expr [{]`. Returns (Switch, next_i)."""
    cases: list = []
    cur_cond = None
    cur_body: list = []
    started = False
    n = len(lines)
    # Allman brace on the next line
    while i < n and (not lines[i].strip() or lines[i].strip().startswith(";")):
        i += 1
    if i < n and lines[i].strip() == "{":
        i += 1
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith(";"):
            i += 1
            continue
        if s == "}":
            i += 1
            break
        code = _strip_comment(raw).strip()
        mc = CASE_RE.match(code)
        md = DEFAULT_RE.match(code)
        if mc or md:
            if started:
                cases.append((cur_cond, cur_body))
            cur_cond = mc.group(1).strip() if mc else None
            cur_body = []
            started = True
            i += 1
            continue
        # nested structures inside case bodies: reuse statement parsing by
        # delegating one compound at a time via _parse_block_chunks below.
        sub, i = _parse_case_statement(lines, i)
        if sub is not None:
            cur_body.append(sub)
    if started:
        cases.append((cur_cond, cur_body))
    return Switch(value, cases), i


def _body_after_opener(lines: list[str], i: int, same_line_brace: bool):
    """Body after an opener line: `{` consumed already (same_line_brace), or
    `{` on the next line (Allman), or a single following statement.
    Returns (body, next_i, self_closed)."""
    if same_line_brace:
        return _parse_block(lines, i)
    return _parse_single_or_block(lines, i)


def _has_brace(raw: str) -> bool:
    return raw.rstrip().endswith("{") or re.search(r'\{\s*(;.*)?$', raw) is not None


def _parse_case_statement(lines: list[str], i: int):
    """Parse exactly one statement/compound starting at i (for switch bodies
    and other nested contexts). Returns (node_or_None, next_i)."""
    raw = lines[i]
    # Block openers tolerate trailing `;` comments (very common in the wild:
    # `loop 2 { ;Click tile`). Match against the comment-stripped form.
    code = _strip_comment(raw).strip()
    mf = FUNCDEF_RE.match(code)
    if mf and mf.group(1).lower() not in _KEYWORDS:
        params = [p.strip() for p in mf.group(2).split(",") if p.strip()]
        clean = []
        for p in params:
            p = p.lstrip("&").strip()
            p = p.split(":=")[0].strip().split("=")[0].strip()
            p = p.rstrip("?*").strip()
            if p.split():
                clean.append(p.split()[0])
        body, i, _ = _parse_block(lines, i + 1)
        return FuncDef(mf.group(1), clean, body), i
    mc = CLASS_RE.match(code)
    if mc:
        body, i, _ = _body_after_opener(lines, i + 1, _has_brace(code))
        return Class(mc.group(1), mc.group(2), body), i
    mm = METHODDEF_RE.match(code)
    if mm and mm.group(1).lower() not in _KEYWORDS:
        params = [p.strip() for p in mm.group(2).split(",") if p.strip()]
        clean = []
        for p in params:
            p = p.lstrip("&").strip()
            p = p.split(":=")[0].strip().split("=")[0].strip()
            p = p.rstrip("?*").strip()
            if p.split():
                clean.append(p.split()[0])
        body, i, _ = _parse_block(lines, i + 1)
        return FuncDef(mm.group(1), clean, body), i
    # Allman method form: `Name(args)` / `static Name(args)` + `{` next line.
    _mcode = re.sub(r'^(?:static|public|private)\s+', '', code, flags=re.IGNORECASE)
    _mmc = _match_call(_mcode)
    if _mmc is not None and not _mmc[2]:
        _mname = _mmc[0].split(".")[-1]
        if re.match(r'^[A-Za-z_]\w*$', _mname or "") and _mname.lower() not in _KEYWORDS:
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith(";")):
                j += 1
            if j < len(lines) and lines[j].strip() == "{":
                _raw_args = [p.strip() for p in _split_seq(_mmc[1])] if _mmc[1].strip() else []
                fn_params = []
                for a in _raw_args:
                    seg = str(a).lstrip("&").strip().split(":=")[0].split("=")[0].strip()
                    seg = seg.rstrip("?*").strip()
                    if seg.split():
                        fn_params.append(seg.split()[0])
                body, k, _ = _parse_block(lines, j + 1)
                return FuncDef(_mname, fn_params, body), k
    ms = STATIC_ASSIGN_RE.match(code)
    if ms:
        st = parse_statement(ms.group(1))
        return (st if st is not None else Setting("Static", ms.group(1))), i + 1
    m = LOOPPARSE_RE.match(code)
    if m:
        return _parse_loopparse(lines, i, m)
    m = LOOPFILES_RE.match(code)
    if m:
        rest = m.group(1).strip().lstrip(",").strip()
        body, i, _ = _body_after_opener(lines, i + 1, _has_brace(code))
        return LoopFiles(_unquote(rest), body), i
    m = LOOP_RE.match(code)
    if m and not re.match(r'(?i)^\s*Loop\s+Parse\b', code) \
            and not re.match(r'(?i)^\s*Loop\s+Files\b', code):
        # `Loop {` (infinite): the brace is structure, never a count. The
        # greedy `(.+?)` would otherwise swallow `{` as the count.
        cnt_raw = (m.group(1) or "").strip()
        if cnt_raw in ("", "{"):
            body, i, _ = _body_after_opener(lines, i + 1, True)
            node = Loop(None, body)
        else:
            body, i, _ = _body_after_opener(lines, i + 1, _has_brace(code))
            node = Loop(_parse_loop_count(cnt_raw), body)
        # `loop { ... } until cond` (do-until): the block stopped at a
        # `} until ...` follower instead of a bare `}`.
        if node.count is None and i < len(lines):
            i = _skip_blank(lines, i)
            mu = UNTIL_RE.match(_strip_comment(lines[i]).strip()) if i < len(lines) else None
            if mu:
                node = DoUntil(mu.group(1).strip(), node.body)
                i += 1
        return node, i
    m = LOOP_BARE_RE.match(code)
    if m:
        body, i, _ = _body_after_opener(lines, i + 1, _has_brace(code))
        node = Loop(None, body)
        if i < len(lines):
            i = _skip_blank(lines, i)
            mu = UNTIL_RE.match(_strip_comment(lines[i]).strip()) if i < len(lines) else None
            if mu:
                node = DoUntil(mu.group(1).strip(), node.body)
                i += 1
        return node, i
    m = FOR_RE.match(code)
    if m:
        targets = [t.strip() for t in m.group(1).split(",") if t.strip()]
        body, i, _ = _body_after_opener(lines, i + 1, _has_brace(code))
        return For(targets, m.group(2).strip(), body), i
    m = WHILE_RE.match(code)
    if m:
        body, i, _ = _body_after_opener(lines, i + 1, _has_brace(code))
        return While(m.group(1).strip(), body), i
    if DO_RE.match(code):
        body, i, _ = _body_after_opener(lines, i + 1, _has_brace(code))
        cond = ""
        if i < len(lines):
            i = _skip_blank(lines, i)
            mu = UNTIL_RE.match(_strip_comment(lines[i]).strip()) if i < len(lines) else None
            if mu:
                cond = mu.group(1).strip()
                i += 1
        return DoUntil(cond, body), i
    m = IF_RE.match(code)
    if m and _has_brace(code):
        then_body, i, closed = _parse_block(lines, i + 1)
        tail, i = _parse_else_tail(lines, i, closed)
        return If(m.group(1).strip(), then_body, tail), i
    m = IF_SINGLE_RE.match(code)
    if m and not _has_brace(code):
        body, i, closed = _parse_single_or_block(lines, i + 1)
        tail, i = _parse_else_tail(lines, i, closed, braceless=True)
        return If(m.group(1).strip(), body, tail), i
    m = SWITCH_RE.match(code)
    if m:
        value = re.sub(r',\s*[01]\s*$', '', m.group(1).strip())
        return _parse_switch(lines, i + 1, value)
    if TRY_RE.match(code):
        return _parse_try(lines, i, code)
    # single-line `try <statement>` (TRY_RE only allows bare/brace forms).
    # The statement may itself be a compound (`try switch x {`): parse it
    # with full dispatch against the following lines. (A trailing `{` that
    # belongs to the inner compound must not read as `Try {`.)
    mt = re.match(r'(?i)^\s*Try\s+(.+)$', code)
    if mt:
        rest = mt.group(1).strip()
        _compound_head = re.match(r'(?i)^\s*(if|loop|for|while|switch)\b', rest)
        if _compound_head or not _has_brace(code):
            sub, ni2 = _parse_case_statement([rest] + lines[i + 1:], 0)
            stmts2 = [sub] if sub is not None else []
            i = i + ni2  # rest + (ni2-1) following lines consumed
        else:
            st = parse_statement(rest)
            stmts2 = [st] if st is not None else []
            i += 1
        catch_var, catch_body, finally_body, else_body = None, [], [], []
        i = _skip_blank(lines, i)
        if i < len(lines) and CATCH_RE.match(_strip_comment(lines[i])):
            mc = CATCH_RE.match(_strip_comment(lines[i]))
            catch_var = mc.group(1)
            i += 1
            catch_body, i, _ = _parse_single_or_block(lines, i)
        else_body, i = _take_try_else(lines, i)
        return Try(stmts2, catch_var, catch_body, finally_body, else_body), i
    # `name :=` with empty value: expression continues on following lines
    # (e.g. `movement :=` + Map/array literal block). Gather while unbalanced.
    me = re.match(r'^\s*([A-Za-z_]\w*)\s*:=\s*$', code)
    if me:
        j = i + 1
        n = len(lines)
        while j < n and (not lines[j].strip() or lines[j].strip().startswith(";")):
            j += 1
        if j < n and lines[j].strip() not in ("{", "}") and not re.match(
                r'(?i)^\s*(if|else|for|while|loop|switch|case|default|try|catch|finally|return|break|continue)\b', lines[j]):
            parts = []
            depth = 0
            k = j
            while k < min(n, j + 30):
                ln = lines[k].strip()
                if not ln or ln.startswith(";"):
                    k += 1
                    continue
                parts.append(ln)
                seg = re.sub(r'"[^"]*"|\'[^\']*\'', '', ln)
                depth += seg.count("(") + seg.count("[") + seg.count("{")
                depth -= seg.count(")") + seg.count("]") + seg.count("}")
                k += 1
                if depth <= 0 and not ln.rstrip().endswith((",", "+", "-", "*", "/", ".", "=", "|", "&", "?", "`")):
                    break
            if parts:
                return Assign(me.group(1), " ".join(parts)), k
        return Assign(me.group(1), ""), i + 1
    # Multi-line object literal: `Name := {` + `k: v` lines + `}`.
    # (`RobloxTypes := {UWP: ..., ...}` — Map()/arrays are single-line,
    # but brace literals span lines.) Gathered only when the closer is a
    # lone `}` within 40 lines and the inside holds `:` pairs; otherwise
    # fall through untouched.
    mo = re.match(r'^\s*([A-Za-z_]\w*)\s*:=\s*\{\s*(;.*)?$', code)
    if mo:
        j = i + 1
        inner = []
        n = len(lines)
        while j < n and len(inner) < 40:
            ln = _strip_comment(lines[j]).strip()
            if ln == "}":
                break
            if ln and not ln.startswith(";"):
                inner.append(ln)
            j += 1
        if j < n and lines[j].strip() == "}" and inner and any(":" in p for p in inner):
            return Assign(mo.group(1), "{" + " ".join(inner) + "}"), j + 1
    st = parse_statement(raw)
    if isinstance(st, FuncCall) and re.match(r'^[A-Za-z_]\w*$', st.name or ""):
        # Allman function definition: `Name(args)` + `{` on the next line.
        # (A bare call is never directly followed by a brace block in AHK.)
        if st.name.lower() not in _KEYWORDS:
            fn_params = []
            for a in (st.args or []):
                seg = str(a).lstrip("&").strip().split(":=")[0].split("=")[0].strip()
                seg = seg.rstrip("?*").strip()
                if seg.split():
                    fn_params.append(seg.split()[0])
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith(";")):
                j += 1
            if j < len(lines) and lines[j].strip() == "{":
                body, k, _ = _parse_block(lines, j + 1)
                # params from the def line: re-derive from raw call text
                mc0 = _match_call(raw)
                if mc0 is not None:
                    fn_params = []
                    for a in _parse_args(mc0[1]):
                        seg = str(a).lstrip("&").strip().split(":=")[0].split("=")[0].strip()
                        seg = seg.rstrip("?*").strip()
                        if seg.split():
                            fn_params.append(seg.split()[0])
                return FuncDef(st.name, fn_params, body), k
    return st, i + 1


def _parse_loopparse(lines: list[str], i: int, m):
    rest = m.group(1).strip().lstrip(",").strip()
    parts = _parse_args(rest)
    text = parts[0] if len(parts) > 0 else ""
    delims = _unquote(parts[1]) if len(parts) > 1 else ""
    body, i, _ = _body_after_opener(lines, i + 1, _has_brace(lines[i]))
    return LoopParse(text, delims, body), i


def _take_try_else(lines: list[str], i: int):
    """Consume a trailing try-`else` (runs when nothing threw): bare `else`
    or `} else`, each with a `{...}` block or a single statement."""
    n = len(lines)
    i = _skip_blank(lines, i)
    if i >= n:
        return [], i
    code = _strip_comment(lines[i]).strip()
    # else-if is an If-else, never a try-else
    if re.match(r'^\s*(?:\}\s*)?else\s+if\b', code, re.IGNORECASE):
        return [], i
    m = re.match(r'^\s*(?:\}\s*)?else\s*(\{\s*)?$', code, re.IGNORECASE)
    if not m:
        return [], i
    i += 1
    if m.group(1) or (i < n and lines[i].strip() == "{"):
        if i < n and lines[i].strip() == "{":
            i += 1
        body, i, _ = _parse_block(lines, i)
        return body, i
    body, i, _ = _parse_single_or_block(lines, i)
    return body, i


def _parse_try(lines: list[str], i: int, raw: str):
    n = len(lines)
    code = _strip_comment(raw).strip()
    if code.lower() == "try":
        # bare `try` + single statement (no brace)
        if i + 1 < n and lines[i + 1].strip() != "{":
            try_body, i, _ = _parse_single_or_block(lines, i + 1)
        elif i + 1 < n:
            try_body, i, _ = _parse_block(lines, i + 2)
        else:
            try_body, i, _ = [], i + 1, False
    else:
        try_body, i, _ = _parse_block(lines, i + 1)
    catch_var, catch_body, finally_body = None, [], []
    i = _skip_blank(lines, i)
    if i < n and CATCH_RE.match(_strip_comment(lines[i])):
        mc = CATCH_RE.match(_strip_comment(lines[i]))
        catch_var = mc.group(1)
        has_brace = bool(mc.group(2))
        i += 1
        if has_brace:
            catch_body, i, _ = _parse_block(lines, i)
        else:
            catch_body, i, _ = _parse_single_or_block(lines, i)
    else_body, i = _take_try_else(lines, i)
    i = _skip_blank(lines, i)
    if i < n and FINALLY_RE.match(_strip_comment(lines[i])):
        mf2 = FINALLY_RE.match(_strip_comment(lines[i]))
        i += 1
        if mf2.group(1):
            finally_body, i, _ = _parse_block(lines, i)
        else:
            finally_body, i, _ = _parse_single_or_block(lines, i)
    return Try(try_body, catch_var, catch_body, finally_body, else_body), i


def _parse_block(lines: list[str], i: int, top: bool = False):
    """Parse statements until `}` / EOF. Returns (stmts, next_i, self_closed).

    self_closed is True only when the block consumed its own lone-`}` closer
    (needed for dangling-else: a following `} else` then belongs outward).

    `top=True` only for hotkey bodies and the auto-execute flow, where a
    bare `return` ends the section (AHK semantics). Inside `{...}` blocks
    (functions, If/Loop/Try bodies) `return` is an ordinary statement —
    treating it as a terminator there leaks `}`/`else` and breaks every
    switch/case below the leak."""
    stmts: list = []
    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith(";"):
            i += 1
            continue
        # Block-end followers belong to the enclosing If/Try/Switch/Loop caller.
        # (`} Else` without a same-line brace is a follower too: the `{` or
        # the single statement comes on the following lines.)
        code = _strip_comment(raw).strip()
        if s == "}" or code == "}":
            return stmts, i + 1, True
        mret = re.match(r'(?i)^return\b\s*(.*)$', s)
        if mret and top:
            val = mret.group(1).split(";")[0].strip()
            stmts.append(Return(val if val else None))
            return stmts, i + 1, False
        if ELSEIF_RE.match(code) or ELSE_RE.match(code) or CATCH_RE.match(code) \
                or FINALLY_RE.match(code) or CASE_RE.match(code) or DEFAULT_RE.match(code) \
                or UNTIL_RE.match(code):
            return stmts, i, False
        if code.lower() == "else" or re.match(r'^\s*\}\s*else\s*$', code, re.IGNORECASE):
            return stmts, i, False
        node, i = _parse_case_statement(lines, i)
        if node is not None:
            # FuncDef at block level registers globally; keep node too so
            # nested defs still execute (runtime re-registers, harmless).
            stmts.append(node)
    return stmts, i, False


def parse_script(text: str, *, source_map: list | None = None) -> Script:
    """Parse source text. ``source_map`` (optional) has one
    ``(file, line)`` entry per *logical* line and is used to tag top-level
    nodes with ``_source`` metadata."""
    lines = _join_continuations(text)
    if source_map is not None and len(source_map) != len(lines):
        # Callers normally pass a map produced by the same join algorithm;
        # a mismatch must never mislabel statements.
        source_map = None
    return _parse_lines(lines, source_map)


def parse_logical_lines(lines: list[str], *, source_map: list | None = None,
                        hoist_functions: bool = True) -> Script:
    """Parse already-joined logical lines (used by the #Include expander,
    which joins each file with this module's scanner before splicing).

    ``hoist_functions`` registers function definitions found in nested
    blocks globally.  Natro places several ``#Include`` directives inside
    GUI handlers (e.g. ``nm_NectarPriority`` includes ``nm_OpenMenu.ahk``);
    AHK still exposes those definitions at load time, and the macro calls
    them from everywhere."""
    sc = _parse_lines(list(lines), source_map)
    if hoist_functions:
        _hoist_nested_functions(sc, sc.auto_section)
        for fn in list(sc.functions.values()):
            _hoist_nested_functions(sc, fn.body)
    return sc


def _hoist_nested_functions(sc: Script, nodes: list):
    """Walk statement bodies and register nested FuncDefs globally."""
    seen: set[int] = set()

    def walk(items):
        for node in items or []:
            if id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, FuncDef):
                sc.functions.setdefault(node.name, node)
            for attr in ("body", "then_body", "else_body", "try_body",
                         "catch_body", "finally_body"):
                value = getattr(node, attr, None)
                if isinstance(value, list):
                    walk(value)
            for attr in ("cases",):
                for case in getattr(node, attr, []) or []:
                    try:
                        walk(case[1])
                    except (TypeError, IndexError):
                        pass

    walk(nodes)


def _parse_lines(lines: list[str], source_map: list | None = None) -> Script:
    sc = Script()
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
                body, i, _ = _parse_block(lines, i + 1 - 1, top=True)
                hk.body = body
            cur_hotkey = None
            continue
        if s == "}":
            i += 1
            continue
        mret = re.match(r'(?i)^return\b\s*(.*)$', s)
        if mret:
            i += 1  # top-level return: end of auto-execute section
            continue
        node, ni = _parse_case_statement(lines, i)
        if node is not None:
            if source_map is not None and 0 <= i < len(source_map):
                try:
                    node._source = source_map[i]
                except Exception:
                    pass
            if isinstance(node, FuncDef):
                sc.functions[node.name] = node
            else:
                sc.auto_section.append(node)
            i = ni
            continue
        st = parse_statement(raw)
        if st is not None:
            if source_map is not None and 0 <= i < len(source_map):
                try:
                    st._source = source_map[i]
                except Exception:
                    pass
            sc.auto_section.append(st)
        i += 1
    return sc


def _open_ends(s: str) -> bool:
    """Continuation check on comment-stripped text. A `%` (or operator) inside
    a trailing `;` comment — e.g. `;less or equal to 50%` — must never glue
    the next line onto this one."""
    return _ends_open(_strip_comment(s).strip())


def _prev_open(prev: str) -> bool:
    """Is the previous logical line an unfinished expression? True when it
    ends open (trailing operator) or has unbalanced `(`/`[` (string-aware)."""
    if _open_ends(prev):
        return True
    depth = 0
    q = None
    k = 0
    while k < len(prev):
        ch = prev[k]
        if ch == "`" and k + 1 < len(prev):
            k += 2
            continue
        if q:
            if ch == q:
                q = None
        elif ch in ('"', "'"):
            q = ch
        elif ch == ";":
            break  # rest is a comment, not structure
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        k += 1
    return depth > 0


def _colon_continues(prev: str, ln: str) -> bool:
    """Fresh `:` line continues a dangling multi-line ternary (`? a` / `: b`).
    Never fires for hotstrings (`:*:x::`), `::` hotkeys, or case/default."""
    s = ln.strip()
    if not s.startswith(":") or s.startswith("::"):
        return False
    if HOTSTRING_RE.match(ln):
        return False
    if re.match(r'(?i)^\s*(case|default)\b', prev):
        return False
    qpos = prev.rfind("?")
    if qpos < 0:
        return False
    # dangling when no `:` after the last `?` (ignoring `::`/`:=`/`?` ops)
    tail = prev[qpos + 1:]
    tail = re.sub(r'"[^"]*"|\'[^\']*\'', '', tail)
    if re.search(r'::|:=', tail):
        return False
    return ":" not in tail


def _join_continuations(text: str) -> list[str]:
    """Merge AHK continuation lines: open parens/brackets across lines, lines
    ending with an operator (`, + - * / . = | & ?`), and lines starting with
    `.` / `,` (method chains / arg continuations). Brace blocks are NOT joined
    (they are real block structure). Returns logical lines."""
    return _join_continuations_mapped(text)[0]


def _join_continuations_mapped(text: str) -> tuple[list[str], list[int]]:
    """Same as :func:`_join_continuations`, plus the 1-based physical line
    number where each returned logical line starts. The include loader uses
    this to preserve source metadata without re-scanning the file."""
    out: list[str] = []
    starts: list[int] = []
    buf = ""
    buf_start = 1
    paren = brack = 0

    def _strip_code(ln: str, q0=None) -> tuple:
        # remove strings + line comment for structure scanning.
        # AHK escapes with BACKTICK (`" `; `, `` `n): skip escaped pairs.
        # Quote state carries across lines inside continuations (AHK joins
        # continuation sections before parsing, so strings may span lines).
        res, q = [], q0
        k = 0
        while k < len(ln):
            ch = ln[k]
            if ch == "`" and k + 1 < len(ln):
                res.append("  ")
                k += 2
                continue
            if q:
                res.append(" ")
                if ch == q:
                    q = None
            elif ch in ('"', "'"):
                q = ch
                res.append(" ")
            elif ch == ";" and (k == 0 or ln[k - 1] in (" ", "\t")):
                break
            else:
                res.append(ch)
            k += 1
        return "".join(res), q

    cont_q = None
    in_block_comment = False
    for lineno, ln in enumerate(text.splitlines(), 1):
        s = ln.strip()
        if in_block_comment:
            if "*/" in s:
                in_block_comment = False
            continue
        if s.startswith("/*"):
            if "*/" not in s[len("/*"):]:
                in_block_comment = True
            continue
        if not s or s.startswith(";"):
            if buf and paren <= 0 and brack <= 0:
                out.append(buf)
                starts.append(buf_start)
                buf = ""
                paren = brack = 0
            if not buf:
                out.append(ln)
                starts.append(lineno)
            continue
        # Quote state carries across ALL lines: multi-line strings are legal
        # (continuation sections), and balanced lines are unaffected by carry.
        code, cont_q = _strip_code(s, cont_q)
        if buf:
            # continuing previous logical line
            if s.startswith((")", "]")):
                buf += " " + s
            else:
                buf += " " + s
            paren += code.count("(") - code.count(")")
            brack += code.count("[") - code.count("]")
            if paren <= 0 and brack <= 0 and not _open_ends(buf):
                out.append(buf)
                starts.append(buf_start)
                buf = ""
                paren = brack = 0
            continue
        paren = code.count("(") - code.count(")")
        brack = code.count("[") - code.count("]")
        # Fresh lines starting with `,` `.` `(` `[` are AHK continuations of
        # the previous expression (arg lists, string concat, call chains) —
        # but only when the previous logical line is actually open, so a
        # stray line can never corrupt a neighboring statement.
        # Fresh `:` lines (single colon, never `::`/hotstrings/case labels)
        # continue a multi-line ternary whose `?` branch is still dangling.
        if out and not buf:
            lead = s[0]
            if lead in (",", "."):
                # A statement can never START with `,`/`.` in AHK — always
                # an argument-list / string-concat continuation.
                out[-1] = out[-1] + " " + s
                continue
            if s.startswith(("&&", "||")):
                # Leading-operator continuation (`&&`/`||` first): same rule.
                out[-1] = out[-1] + " " + s
                continue
            if lead in ("(", "[") and _prev_open(out[-1]):
                out[-1] = out[-1] + " " + s
                continue
            if lead == ":" and _colon_continues(out[-1], ln):
                out[-1] = out[-1] + " " + s
                continue
        if paren > 0 or brack > 0 or _open_ends(s):
            buf = s
            buf_start = lineno
            continue
        out.append(ln)
        starts.append(lineno)
    if buf:
        out.append(buf)
        starts.append(buf_start)
    return out, starts


def _ends_open(s: str) -> bool:
    t = s.rstrip()
    if not t:
        return False
    # explicit AHK continuation: lone backtick at end of line
    if t.endswith("`") and not t.endswith("``"):
        return True
    if t.endswith(("++", "--")):
        return False  # IncDec suffix, never a continuation
    if t.endswith("%") and re.search(r"%[A-Za-z_]\w*%$", t):
        return False  # v1 %var% deref ending, not modulo continuation
    # trailing comma or operator -> continuation (but not `::`, `:=`, `==`)
    if t.endswith(","):
        return True
    if t[-1:] in ("+", "-", "*", "/", ".", "=", "|", "&", "?", "^", "%"):
        if t[-2:] in ("::", ":=", "==", "!=", "<=", ">="):
            return False
        return True
    # trailing single `:` continues a dangling ternary (`cond ? a :` + `b`
    # on the next line). `Case 1:` / labels / `::` / `:=` never continue.
    if t.endswith(":") and not t.endswith("::") and ":=" not in t[-3:]:
        no_str = re.sub(r'"[^"]*"|\'[^\']*\'', '', t)
        qpos = no_str.rfind("?")
        if qpos >= 0 and ":" not in no_str[qpos + 1:]:
            return True
        return False
    if t.endswith("(") or t.endswith("["):
        return True
    return False
