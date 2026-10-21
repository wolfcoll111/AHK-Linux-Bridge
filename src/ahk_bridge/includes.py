"""AHK v2 ``#Include`` preprocessor.

AutoHotkey inlines include files *textually* before parsing.  This module
implements that for the Linux bridge: includes are expanded line-wise using
the parser's own continuation/string scanner, so directives that live inside
continuation sections (Natro embeds whole generated submacro scripts in
``( ... )`` strings) are left verbatim.  Directives may be indented and may
appear inside function bodies.

Semantics implemented (AHK v2 docs):

* default relative base is the directory of the file containing the
  directive;
* a directory argument (``#Include "%A_ScriptDir%\\..\\lib"``) only changes
  the include base for *subsequent* includes in the current file;
* ``#Include`` includes a file once, ``#IncludeAgain`` re-includes it;
* ``%A_ScriptDir%`` and the other path variables expand, as do environment
  variables; both ``/`` and ``\\`` work;
* quoted, unquoted and ``*i`` (ignore-missing) arguments;
* Windows is case-insensitive, so a case-insensitive fallback is used on
  Linux for real-world trees copied from Windows;
* ``#Include <LibName>`` searches local/user library folders and is
  implemented rather than silently ignored;
* cycles raise :class:`IncludeError` with the includer path and line.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import parser as P

DIRECTIVE_RE = re.compile(r"^#Include(Again)?\b\s*(.*)$", re.IGNORECASE)
VAR_RE = re.compile(r"%([A-Za-z_]\w*)%")


class IncludeError(RuntimeError):
    """A malformed, missing or cyclic include."""


@dataclass
class IncludeRecord:
    directive: str          # "Include" | "IncludeAgain"
    argument: str
    includer: str
    line: int
    resolved: str | None = None
    status: str = "ok"      # ok | directory | once | ignored | library
    detail: str = ""


@dataclass
class ExpandedScript:
    """Expanded source plus enough metadata to map output lines back."""

    text: str
    root: str
    files: list[str] = field(default_factory=list)
    # One (source_path, physical_line) per logical output line.
    line_map: list[tuple[str, int]] = field(default_factory=list)
    records: list[IncludeRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # The logical lines exactly as spliced. Parsing these directly avoids a
    # second continuation pass over lines that are already joined (a joined
    # line can contain embedded `;` comments, which a re-join would mistake
    # for a fresh comment and swallow the rest of the file).
    lines: list[str] = field(default_factory=list)

    def source_of(self, line_index: int) -> tuple[str, int]:
        if 0 <= line_index < len(self.line_map):
            return self.line_map[line_index]
        return (self.root, 0)

    def parse(self) -> P.Script:
        return P.parse_logical_lines(self.lines, source_map=self.line_map)


def default_path_vars(script_path: str, working_dir: str | None = None) -> dict[str, str]:
    """Values for the ``%A_*%`` path variables used by #Include."""
    script = Path(script_path).resolve()
    work = Path(working_dir or os.getcwd()).resolve()
    home = Path.home()
    return {
        "A_ScriptDir": str(script.parent),
        "A_ScriptName": script.name,
        "A_ScriptFullPath": str(script),
        "A_WorkingDir": str(work),
        "A_Temp": os.environ.get("TMPDIR", "/tmp"),
        "A_LineFile": str(script),
        "A_AppData": os.environ.get("XDG_CONFIG_HOME", str(home / ".config")),
        "A_AppDataCommon": "/etc",
        "A_Desktop": str(home / "Desktop"),
        "A_MyDocuments": str(home / "Documents"),
        "A_UserProfile": str(home),
        "A_Home": str(home),
        "A_WinDir": os.environ.get("WINDIR", "C:\\Windows"),
    }


def _expand_vars(text: str, variables: dict[str, str]) -> str:
    """Expand ``%Name%`` using path vars, then environment, then leave it."""
    def repl(m):
        name = m.group(1)
        if name in variables:
            return variables[name]
        if name in os.environ:
            return os.environ[name]
        return m.group(0)

    # A few passes handle `%A_ScriptDir%` expanding to text containing % only
    # in pathological names; four is plenty and bounded.
    for _ in range(4):
        new = VAR_RE.sub(repl, text)
        if new == text:
            break
        text = new
    return text


def _ci_listing(directory: str) -> tuple[tuple[str, str], ...]:
    """Directory entries lowercased for Windows-style case matching.

    Deliberately not cached: include expansion is a one-shot operation, and
    tests (or a live settings folder) may create directories between loads.
    A stale parent listing would hide a real include.
    """
    try:
        return tuple((entry.lower(), entry) for entry in os.listdir(directory))
    except OSError:
        return ()


def _ci_resolve(path: str) -> str | None:
    """Return an existing path, matching Windows-style case-insensitively."""
    p = Path(path)
    if p.exists():
        return str(p)
    if not p.is_absolute():
        return None
    parts = p.parts
    if not parts:
        return None
    cur = Path(parts[0])
    for part in parts[1:]:
        if not cur.is_dir():
            return None
        want = part.lower()
        match = None
        for low, real in _ci_listing(str(cur)):
            if low == want:
                match = real
                break
        if match is None:
            return None
        cur = cur / match
    return str(cur) if cur.exists() else None


def _strip_arg(raw: str) -> tuple[str, bool, bool]:
    """Parse an include argument -> (path, ignore_missing, is_library)."""
    s = (raw or "").strip()
    if s[:1] in ('"', "'"):
        quote = s[0]
        end = s.find(quote, 1)
        if end > 0:
            s = s[1:end]
    ignore = False
    m = re.match(r"^\*[iI]\s+(.*)$", s, re.DOTALL)
    if m:
        ignore = True
        s = m.group(1).strip()
    # AHK also tolerates *i without whitespace for quoted names? Keep the
    # documented form; a bare `*i` path is malformed and gets a clear error.
    if len(s) >= 2 and s[0] == "<" and s[-1] == ">":
        return s[1:-1].strip(), ignore, True
    return s.strip().strip('"').strip("'"), ignore, False


def _looks_like_directory(path: str) -> bool:
    return os.path.isdir(path)


def _library_candidates(name: str, base: str, script_dir: str) -> list[str]:
    """AHK v2 library search: local Lib next to the script, then parents,
    then the user library. Both ``Lib/Name.ahk`` and ``Lib/Name/Name.ahk``
    are accepted (the latter is a common v2 packaging form)."""
    roots: list[str] = []
    for start in (base, script_dir):
        cur = Path(start)
        for _ in range(8):
            roots.append(str(cur))
            if cur.parent == cur:
                break
            cur = cur.parent
    roots.append(str(Path.home() / ".autohotkey"))
    out: list[str] = []
    for root in roots:
        lib = Path(root) / "Lib"
        out.append(str(lib / f"{name}.ahk"))
        out.append(str(lib / name / f"{name}.ahk"))
    return out


class IncludeLoader:
    """Expand a script tree.  One loader instance = one script run."""

    def __init__(self, path: str, *, working_dir: str | None = None,
                 variables: dict[str, str] | None = None,
                 strict: bool = True):
        self.root = str(Path(path).resolve())
        self.script_dir = str(Path(self.root).parent)
        self.working_dir = str(Path(working_dir or os.getcwd()).resolve())
        self.variables = default_path_vars(self.root, self.working_dir)
        if variables:
            self.variables.update({k: str(v) for k, v in variables.items()})
        self.strict = strict
        self._included: set[str] = set()
        self._stack: list[str] = []
        self.files: list[str] = []
        self.records: list[IncludeRecord] = []
        self.warnings: list[str] = []
        self._out: list[str] = []
        self._line_map: list[tuple[str, int]] = []

    # -- public --
    def expand(self) -> ExpandedScript:
        if not os.path.isfile(self.root):
            raise IncludeError(f"script not found: {self.root}")
        self._expand_file(self.root, self.script_dir)
        return ExpandedScript(
            text="\n".join(self._out),
            root=self.root,
            files=list(self.files),
            line_map=list(self._line_map),
            records=list(self.records),
            warnings=list(self.warnings),
            lines=list(self._out),
        )

    # -- internals --
    def _expand_file(self, path: str, base: str):
        real = os.path.realpath(path)
        if real in self._stack:
            chain = " -> ".join(self._stack + [real])
            raise IncludeError(f"#Include cycle detected: {chain}")
        try:
            text = Path(real).read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = Path(real).read_text(encoding="latin-1")
        self._stack.append(real)
        self.files.append(real)
        try:
            logical, starts = P._join_continuations_mapped(text)
            for line, phys in zip(logical, starts):
                match = self._directive(line)
                if match is None:
                    self._out.append(line)
                    self._line_map.append((real, phys))
                    continue
                is_again, arg = match
                status = self._handle_directive(
                    is_again=is_again, arg=arg, current=real,
                    line=phys, base=base)
                # A directory directive emits nothing and changes the base
                # for subsequent includes in this file only.
                if status == "directory":
                    base = self.records[-1].resolved or base
        finally:
            self._stack.pop()

    @staticmethod
    def _directive(line: str):
        if not line.lstrip().startswith("#"):
            return None
        code = P._strip_comment(line).strip()
        m = DIRECTIVE_RE.match(code)
        if not m:
            return None
        return bool(m.group(1)), m.group(2).strip()

    def _handle_directive(self, *, is_again: bool, arg: str, current: str,
                          line: int, base: str) -> str:
        directive = "IncludeAgain" if is_again else "Include"
        record = IncludeRecord(directive, arg, current, line)
        self.records.append(record)
        expand_vars = dict(self.variables)
        expand_vars["A_LineFile"] = current
        expand_vars["A_LineNumber"] = str(line)
        raw = _expand_vars(arg, expand_vars)
        target, ignore, is_lib = _strip_arg(raw)
        if not target:
            record.status = "missing"
            record.detail = "empty include path"
            self._missing(record, ignore)
            return record.status
        target = target.replace("\\", os.sep)
        if is_lib:
            resolved = self._resolve_library(target, base)
        else:
            resolved = self._resolve_path(target, base)
        if resolved is None:
            record.status = "missing"
            record.detail = f"not found (base {base})"
            self._missing(record, ignore)
            return record.status
        record.resolved = resolved
        if _looks_like_directory(resolved):
            record.status = "directory"
            return record.status
        real = os.path.realpath(resolved)
        if not is_again and real in self._included:
            record.status = "once"
            return record.status
        if real in self._stack:
            chain = " -> ".join(self._stack + [real])
            raise IncludeError(
                f"#Include cycle detected at {current}:{line}: {chain}")
        self._included.add(real)
        record.status = "library" if is_lib else "ok"
        self._expand_file(real, os.path.dirname(real))
        return record.status

    def _missing(self, record: IncludeRecord, ignore: bool):
        if ignore:
            record.status = "ignored"
            self.warnings.append(
                f"#Include *i ignored missing file: {record.argument}")
            return
        msg = (f"#Include not found: {record.argument!r} "
               f"(from {record.includer}:{record.line})")
        if self.strict:
            raise IncludeError(msg)
        self.warnings.append(msg)

    def _resolve_path(self, target: str, base: str) -> str | None:
        expanded = os.path.expanduser(target)
        candidate = expanded if os.path.isabs(expanded) else os.path.join(base, expanded)
        candidate = os.path.normpath(candidate)
        hit = _ci_resolve(candidate)
        if hit is None and not os.path.splitext(candidate)[1]:
            # AHK appends .ahk when the include has no extension.
            hit = _ci_resolve(candidate + ".ahk")
        return hit

    def _resolve_library(self, name: str, base: str) -> str | None:
        for candidate in _library_candidates(name, base, self.script_dir):
            hit = _ci_resolve(candidate)
            if hit is not None:
                return hit
        # Explicit user library env override (documented extension).
        override = os.environ.get("AHK_LIB")
        if override:
            hit = _ci_resolve(os.path.join(override, name + ".ahk"))
            if hit is not None:
                return hit
        return None


def expand_includes(path: str, **kwargs) -> ExpandedScript:
    return IncludeLoader(path, **kwargs).expand()


def load_script(path: str, **kwargs) -> tuple[P.Script, ExpandedScript]:
    """Convenience: expand includes, then parse.  Returns (script, expanded)."""
    expanded = expand_includes(path, **kwargs)
    return expanded.parse(), expanded
