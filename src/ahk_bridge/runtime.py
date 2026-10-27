"""Executor with emergency abort. Runs parsed Script against InputSimulator.

v0.2: expression eval (arithmetic, Random(), strings), If/Else, Break/Continue,
Loop/Sleep var resolution, {Key} send-sequences, live PixelSearch + WinActivate.
"""
from __future__ import annotations
import ast
import datetime as _dt
import hashlib
import json
import os
import queue
import random
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from . import parser as P

ABORT_KEYS = ("Escape", "Ctrl+Alt+C")


class TargetError(RuntimeError):
    """AHK `TargetError`: a window/control required by a call was not found."""


class Aborted(RuntimeError):
    def __init__(self, message: str = "", exit_code=None):
        super().__init__(message)
        self.exit_code = exit_code


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


class BoundFunc:
    """AHK v2 ``Fn.Bind(args...)`` result: the bound arguments are evaluated
    once at Bind() time and prepended to every later call."""

    __slots__ = ("runtime", "name", "args")

    def __init__(self, runtime, name: str, args: list):
        self.runtime = runtime
        self.name = name
        self.args = list(args)

    def call(self, raw_args: list):
        return self.runtime._call_value(
            P.FuncCall(self.name, self.args + list(raw_args)))

    def __repr__(self):
        return f"<BoundFunc {self.name}>"


class TrayMenu:
    """Minimal ``A_TrayMenu`` object.

    There is no system tray on a headless Linux run, but Natro's startup code
    creates the menu and later may click an item programmatically.  Keeping
    the item list and callbacks real makes those paths work without a GUI;
    ``show()`` writes the menu to the runtime log for display-only runs.
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self.items: list[tuple[str | None, str | None]] = []
        self.checks: set[str] = set()
        self.default: str | None = None

    def dispatch(self, method: str, raw_args: list[str], runtime):
        method = method.lower()
        if method == "add":
            label = ""
            if raw_args:
                label = runtime._to_ahk_string(runtime._eval_expr(raw_args[0]))
            callback = raw_args[1].strip() if len(raw_args) > 1 else None
            self.items.append((label or None, callback))
            return 1
        if method == "addstandard":
            return 1
        if method == "delete":
            self.items.clear()
            self.checks.clear()
            self.default = None
            return 1
        if method == "show":
            labels = ", ".join(name for name, _ in self.items if name)
            runtime.logs.append(f"A_TrayMenu.Show: {labels}")
            return 1
        if method in ("togglecheck", "check", "uncheck"):
            label = runtime._to_ahk_string(
                runtime._eval_expr(raw_args[0])) if raw_args else ""
            if method == "togglecheck":
                if label in self.checks:
                    self.checks.discard(label)
                else:
                    self.checks.add(label)
            elif method == "check":
                self.checks.add(label)
            else:
                self.checks.discard(label)
            return 1 if label in self.checks else 0
        if method in ("click", "invoke"):
            label = runtime._to_ahk_string(
                runtime._eval_expr(raw_args[0])) if raw_args else ""
            for index, (name, callback) in enumerate(self.items):
                if name == label:
                    spec = runtime._callback_spec(callback or "")
                    if spec:
                        runtime._invoke_callback(
                            spec, [label, index + 1, self])
                    return 1
            return 0
        runtime.logs.append(f"A_TrayMenu.{method}() unsupported (logged)")
        return ""


class AhkFile:
    """Minimal AHK v2 File object backed by a real Linux file.

    Natro uses ``FileOpen`` for imported patterns, config snapshots and its
    debug log.  The supported surface is the one those paths need: ``Read``,
    ``ReadLine``, ``Write``, ``WriteLine``, ``Seek``, ``Close`` and the
    ``Length``/``Pos``/``AtEOF`` properties.  AHK's sharing flags (the
    ``-d`` in ``w-d``) only affect Windows sharing modes; Linux has no
    equivalent, so they are accepted and logged once rather than silently
    changing open semantics.
    """

    _ENCODINGS = {
        "utf-8": "utf-8", "utf8": "utf-8",
        "utf-16": "utf-16", "utf16": "utf-16",
        "cp0": "utf-8", "ansi": "utf-8",
    }

    def __init__(self, runtime, path: str, mode: str, encoding: str = ""):
        self.runtime = runtime
        self.path = path
        text = str(mode or "r").strip().lower()
        access, sep, share = text.partition("-")
        if not access:
            access = "r"
        access = "".join(ch for ch in access if ch in "rwa") or "r"
        self.access = access
        self.share = share if sep else ""
        enc = str(encoding or "").strip().strip('"').lower()
        self.encoding = self._ENCODINGS.get(enc, "utf-8")
        self.closed = False
        # In AHK both access and sharing flags share one string; `d` after
        # the dash is a share flag, not "delete on close".
        if self.share:
            runtime._log_once(
                f"FileOpen: sharing flags {self.share!r} advertised, not "
                "enforced on Linux")
        if access == "rw":
            py_mode = "r+" if os.path.exists(path) else "w+"
        elif access == "a":
            py_mode = "a"
        elif access == "w":
            py_mode = "w"
        else:
            py_mode = "r"
        if "b" not in py_mode and py_mode.startswith("r"):
            self._fh = open(path, py_mode, encoding="utf-8-sig")
        else:
            self._fh = open(path, py_mode, encoding=self.encoding,
                            newline="")
        # HashFile uses RawRead to feed the OS crypto API.  Keep a separate
        # binary handle so text decoding (and its BOM handling) cannot change
        # the bytes being hashed.
        self._bfh = None
        self._raw_pos = 0

    # -- File object API -------------------------------------------------
    def _binary_handle(self):
        if self._bfh is None or self._bfh.closed:
            self._bfh = open(self.path, "rb")
            self._bfh.seek(self._raw_pos)
        return self._bfh

    def ahk_dispatch(self, method: str, raw_args: list, runtime):
        m = method.lower()
        if self.closed:
            runtime._log_once(
                f"File.{method} on closed file {self.path!r} (returns falsy)")
            return "" if not m.startswith("read") else ""
        if m == "read":
            if raw_args and str(raw_args[0]).strip():
                try:
                    count = int(runtime._eval_expr(raw_args[0]))
                except (TypeError, ValueError):
                    count = -1
                return self._fh.read(count if count >= 0 else -1)
            return self._fh.read()
        if m == "readline":
            line = self._fh.readline()
            return line.rstrip("\r\n") if line else ""
        if m == "write":
            data = (runtime._to_ahk_string(runtime._eval_expr(raw_args[0]))
                    if raw_args else "")
            written = self._fh.write(data)
            return written
        if m == "writeline":
            data = (runtime._to_ahk_string(runtime._eval_expr(raw_args[0]))
                    if raw_args else "")
            written = self._fh.write(data + "\n")
            return written
        if m == "seek":
            distance = 0
            origin = 0
            if raw_args:
                try:
                    distance = int(runtime._eval_expr(raw_args[0]))
                except (TypeError, ValueError):
                    distance = 0
            if len(raw_args) > 1:
                try:
                    origin = int(runtime._eval_expr(raw_args[1]))
                except (TypeError, ValueError):
                    origin = 0
            whence = {0: os.SEEK_SET, 1: os.SEEK_CUR, 2: os.SEEK_END}.get(
                origin, os.SEEK_SET)
            try:
                return self._fh.seek(distance, whence)
            except (OSError, ValueError) as exc:
                runtime._log_once(f"File.Seek failed: {exc}")
                return 0
        if m == "rawread":
            from . import memory
            if not raw_args:
                return 0
            target = runtime._eval_expr(raw_args[0])
            try:
                count = (int(runtime._eval_expr(raw_args[1]))
                         if len(raw_args) > 1 else 0)
            except (TypeError, ValueError):
                count = 0
            buf, base = memory.resolve(target)
            if buf is None:
                runtime._log_once("File.RawRead: no Buffer target (returns 0)")
                return 0
            try:
                data = self._binary_handle().read(
                    count if count > 0 else buf.size - base)
            except OSError as exc:
                runtime._log_once(f"File.RawRead failed: {exc}")
                return 0
            if count <= 0:
                count = len(data)
            data = data[:max(0, min(count, buf.size - base))]
            buf.data[base:base + len(data)] = data
            self._raw_pos = self._binary_handle().tell()
            return len(data)
        if m == "close":
            self.close()
            return 1
        if m in ("__delete", "destroy"):
            self.close()
            return ""
        runtime._log_once(f"File.{method}() unsupported (logged)")
        return ""

    def ahk_set_property(self, name: str, value):
        prop = str(name).lower()
        if prop in ("pos", "position"):
            try:
                pos = int(value)
            except (TypeError, ValueError):
                pos = 0
            self._raw_pos = max(0, pos)
            try:
                self._fh.seek(pos)
            except (OSError, ValueError):
                pass
            if self._bfh is not None and not self._bfh.closed:
                try:
                    self._bfh.seek(self._raw_pos)
                except (OSError, ValueError):
                    pass
            return 1
        self.runtime._log_once(f"File.{name} property unsupported (logged)")
        return 0

    def ahk_get_property(self, name: str):
        prop = str(name).lower()
        if prop == "length":
            if self.closed:
                try:
                    return os.path.getsize(self.path)
                except OSError:
                    return 0
            try:
                self._fh.flush()
                return os.fstat(self._fh.fileno()).st_size
            except (OSError, ValueError):
                return 0
        if prop == "pos":
            if self.closed:
                return 0
            if self._bfh is not None and not self._bfh.closed:
                try:
                    return self._bfh.tell()
                except (OSError, ValueError):
                    return self._raw_pos
            try:
                return self._fh.tell()
            except (OSError, ValueError):
                return 0
        if prop == "ateof":
            if self.closed:
                return 1
            try:
                if self._bfh is not None and not self._bfh.closed:
                    here = self._bfh.tell()
                    self._bfh.seek(0, os.SEEK_END)
                    end = self._bfh.tell()
                    self._bfh.seek(here)
                    return 1 if here >= end else 0
                here = self._fh.tell()
                self._fh.seek(0, os.SEEK_END)
                end = self._fh.tell()
                self._fh.seek(here)
                return 1 if here >= end else 0
            except (OSError, ValueError):
                return 1
        if prop == "encoding":
            return self.encoding
        if prop == "path":
            return self.path
        return ""

    def close(self):
        if not self.closed:
            for attr in ("_fh", "_bfh"):
                fh = getattr(self, attr, None)
                if fh is not None:
                    try:
                        fh.close()
                    except OSError:
                        pass
            self.closed = True

    def __del__(self):
        self.close()


def _resolve_ci_path(path: str) -> str:
    """Return the on-disk spelling of ``path`` using Windows-style lookup.

    Windows file systems are case-insensitive and case-preserving; Natro
    builds names such as ``paths/gtc-windshrine.ahk`` while the file is
    stored as ``gtc-WindShrine.ahk``.  Exact names win; otherwise each
    component is matched case-insensitively against its parent directory.
    Unresolvable paths are returned unchanged so callers can still create
    files with the requested spelling.
    """
    if os.path.exists(path):
        return path
    prefix = os.sep if os.path.isabs(path) else ""
    parts = path.lstrip(os.sep).split(os.sep)
    current = prefix
    for index, part in enumerate(parts):
        if not part:
            continue
        candidate = os.path.join(current, part) if current else part
        if os.path.exists(candidate):
            current = candidate
            continue
        if any(ch in part for ch in "*?["):
            rest = os.sep.join(parts[index:])
            return os.path.join(current, rest) if current else rest
        try:
            entries = os.listdir(current or ".")
        except OSError:
            return path
        matches = [entry for entry in entries if entry.lower() == part.lower()]
        if len(matches) != 1:
            return path
        current = os.path.join(current, matches[0]) if current else matches[0]
    return current or path


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
                 max_loop=10_000, jitter: float = 0.0, seed=None,
                 script_path: str | None = None, args=(),
                 working_dir: str | None = None, screen_size=None,
                 allow_processes: bool = True):
        self.script = script
        self.sim = sim
        self.vars: dict = {}
        self.logs: list[str] = []
        self._abort = threading.Event()
        # Monotonic clock used by WinWait* polling; tests replace this with a
        # virtual clock so no wall-clock waiting is needed.
        self._clock = time.monotonic
        self.abort_keys = tuple(abort_keys)
        self.max_loop = max_loop  # safety cap for infinite loops in tests
        self.jitter = jitter  # 0.0..1.0 fraction of Sleep randomization
        self._rng = random.Random(seed)
        self._stub_warned: set = set()  # builtin stubs logged once each
        self._exit_callbacks: list[tuple] = []
        self._exit_done = False
        self._error_callbacks: list[tuple] = []
        # -- event surface (v0.5) --
        self.allow_processes = allow_processes
        self._timers: dict[str, dict] = {}
        self._dynamic_hotkeys: dict[str, dict] = {}
        self._suspended = False
        self._paused = False
        self._keep_alive = False
        self._message_handlers: dict[int, list] = {}
        self._message_queue: queue.Queue = queue.Queue()
        self._message_lock = threading.RLock()
        self._children: list[subprocess.Popen] = []
        self._process_lock = threading.RLock()
        self._ipc_path: str | None = None
        self._ipc_dir: str | None = None
        self._ipc_sock = None
        self._ipc_thread: threading.Thread | None = None
        self._ipc_stop = threading.Event()
        # -- GUI surface (v0.6) --
        self._guis: list = []
        self._pending_abort: Aborted | None = None
        # -- OS bridge (v0.7) --
        self._clipboard_loaded = False
        self._active_gui = None
        self._init_builtin_vars(script_path, args, working_dir, screen_size)

    # -- built-in variables --
    def _init_builtin_vars(self, script_path, args, working_dir, screen_size):
        self._start_tick = time.monotonic()
        if script_path:
            full = os.path.abspath(os.path.expanduser(os.fspath(script_path)))
            script_dir = os.path.dirname(full)
            script_name = os.path.basename(full)
        else:
            full = ""
            script_dir = os.getcwd()
            script_name = ""
        work = os.path.abspath(os.path.expanduser(
            os.fspath(working_dir))) if working_dir else script_dir
        home = os.path.expanduser("~")
        temp = os.environ.get("TMPDIR") or "/tmp"
        if screen_size is None:
            try:
                screen_size = (int(os.environ["AHK_SCREEN_WIDTH"]),
                               int(os.environ["AHK_SCREEN_HEIGHT"]))
            except (KeyError, ValueError):
                screen_size = (1920, 1080)
        try:
            from . import __version__ as _version
        except Exception:  # pragma: no cover - version import is optional
            _version = "0.8.0"
        self.vars.update({
            "A_ScriptDir": script_dir,
            "A_ScriptName": script_name,
            "A_ScriptFullPath": full,
            "A_WorkingDir": work,
            "A_LineFile": full,
            "A_LineNumber": 0,
            "A_Temp": temp,
            "A_AppData": os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config")),
            "A_AppDataCommon": "/etc",
            "A_Desktop": os.path.join(home, "Desktop"),
            "A_MyDocuments": os.path.join(home, "Documents"),
            "A_UserProfile": home,
            "A_Home": home,
            "A_AhkPath": os.environ.get("AHK_BRIDGE_EXE") or sys.executable,
            "A_AhkVersion": _version,
            "A_PtrSize": 8 if sys.maxsize > 2**32 else 4,
            "A_Is64bitOS": 1 if sys.maxsize > 2**32 else 0,
            "A_IsAdmin": 1 if hasattr(os, "geteuid") and os.geteuid() == 0 else 0,
            "A_IsCompiled": 0,
            "A_LastError": 0,
            "A_KeyDelay": 10,
            "A_Clipboard": "",
            "A_Space": " ",
            "A_Tab": "\t",
            "A_ScreenWidth": int(screen_size[0]),
            "A_ScreenHeight": int(screen_size[1]),
            "A_ScreenDPI": 96,
            "A_IsPaused": 0,
            "A_IsSuspended": 0,
            "A_ScriptHwnd": 0,
            "A_Args": [str(a) for a in (args or [])],
        })
        self.vars["A_TrayMenu"] = TrayMenu(self)
        self._refresh_builtin_vars()

    def _refresh_builtin_vars(self):
        """Update clock-derived variables; AHK refreshes these on each use."""
        now = _dt.datetime.now()
        utc = _dt.datetime.now(_dt.timezone.utc)
        self.vars.update({
            "A_Now": now.strftime("%Y%m%d%H%M%S"),
            "A_NowUTC": utc.strftime("%Y%m%d%H%M%S"),
            "A_Year": now.strftime("%Y"),
            "A_YYYY": now.strftime("%Y"),
            "A_MM": now.strftime("%m"),
            "A_DD": now.strftime("%d"),
            "A_Hour": now.strftime("%H"),
            "A_Min": now.strftime("%M"),
            "A_Sec": now.strftime("%S"),
            "A_MSec": f"{now.microsecond // 1000:03d}",
            "A_YDay": str(now.timetuple().tm_yday),
            "A_WDay": str((now.weekday() + 1) % 7 + 1),
            "A_TickCount": int((time.monotonic() - self._start_tick) * 1000),
        })

    def _abs_path(self, path) -> str:
        """Resolve a script path against ``A_WorkingDir`` (AHK semantics)."""
        text = str(path).strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
            text = text[1:-1]
        text = os.path.expanduser(text.replace("\\", os.sep))
        if os.path.isabs(text):
            resolved = os.path.normpath(text)
        else:
            base = str(self.vars.get("A_WorkingDir") or os.getcwd())
            resolved = os.path.normpath(os.path.join(base, text))
        return _resolve_ci_path(resolved)

    # -- exit callbacks --
    @staticmethod
    def _callback_spec(raw: str):
        """Parse a callback argument into ("func", name) or ("expr", body)."""
        text = str(raw).strip()
        m = re.match(r'^(\([^)]*\)|[A-Za-z_]\w*)\s*=>\s*(.+)$', text, re.DOTALL)
        if m:
            params = m.group(1).strip()
            if params.startswith("("):
                params = params[1:-1]
            names = [p.strip().lstrip("&").split(":=")[0].strip()
                     for p in params.split(",") if p.strip()]
            names = [n for n in names if n and n != "*"]
            return ("expr", m.group(2).strip(), names)
        if re.fullmatch(r'[A-Za-z_]\w*', text):
            return ("func", text, [])
        return None

    def _invoke_callback(self, spec: tuple, values: list):
        """Invoke a callback spec with already-evaluated argument values.

        Named callbacks receive arguments through temporary variables because
        ``FuncCall`` arguments are raw source expressions; arrows bind their
        parameter names directly for the duration of the call.
        """
        if spec[0] == "func":
            saved: dict[str, object] = {}
            args: list[str] = []
            for index, value in enumerate(values):
                name = f"__ahk_cb_{index}__"
                saved[name] = self.vars.get(name, None)
                has = name in self.vars
                self.vars[name] = value
                args.append(name)
                if not has:
                    # distinguish "was absent" from an existing None value
                    saved.setdefault(f"__ahk_had_{index}__", False)
                else:
                    saved[f"__ahk_had_{index}__"] = True
            try:
                return self._call_value(P.FuncCall(spec[1], args))
            finally:
                for index in range(len(values)):
                    name = f"__ahk_cb_{index}__"
                    had = saved.get(f"__ahk_had_{index}__", False)
                    if had:
                        self.vars[name] = saved[name]
                    else:
                        self.vars.pop(name, None)
        kind, body, names = spec
        saved_vars = {n: self.vars.get(n) for n in names}
        present = {n: n in self.vars for n in names}
        for index, name in enumerate(names):
            self.vars[name] = values[index] if index < len(values) else ""
        try:
            return self._eval_expr(body)
        finally:
            for name in names:
                if present[name]:
                    self.vars[name] = saved_vars[name]
                else:
                    self.vars.pop(name, None)

    def _invoke_gui_callback(self, spec: tuple, control, info, event: str):
        """Run a Gui OnEvent callback without leaking exceptions into Qt."""
        try:
            return self._invoke_callback(spec, [control, info])
        except Aborted as exc:
            # ExitApp may be called from a Close/Click handler. Qt slots must
            # not let this cross the C++ boundary; park it for Runtime.wait.
            self._pending_abort = exc
            return 0
        except Exception as exc:  # noqa: BLE001 - callbacks must not kill GUI
            if not self._dispatch_error(exc):
                self.logs.append(f"GUI {event} callback error: {exc}")
            return 0

    def _run_exit_callbacks(self, reason: str = "Exit", code=0) -> bool:
        """Run OnExit callbacks; return True if one prevented the exit."""
        if self._exit_done:
            return False
        prevented = False
        for spec in list(self._exit_callbacks):
            try:
                result = self._invoke_callback(spec, [reason, code])
                if self._truthy(result):
                    prevented = True
                    break
            except Exception as exc:  # noqa: BLE001 - cleanup must not crash
                self.logs.append(f"OnExit callback failed: {exc}")
        if prevented:
            self.logs.append("OnExit callback returned non-zero; exit prevented")
        else:
            self._exit_done = True
            self._shutdown_ipc()
        return prevented

    def _dispatch_error(self, exc: Exception) -> bool:
        """Offer an uncaught script error to OnError callbacks.

        Returns True when a callback suppressed the error (non-zero result),
        matching AHK: the erroring thread stops but the remaining top-level
        statements continue.
        """
        if not self._error_callbacks:
            return False
        message = str(exc) or exc.__class__.__name__
        error_obj = {
            "Message": message,
            "What": "",
            "Extra": "",
            "File": self.vars.get("A_LineFile", ""),
            "Line": 0,
            "Stack": "",
        }
        for spec in list(self._error_callbacks):
            try:
                result = self._invoke_callback(spec, [error_obj, "Return"])
            except Exception as handler_exc:  # noqa: BLE001 - handler must not crash
                self.logs.append(f"OnError callback failed: {handler_exc}")
                continue
            if self._truthy(result):
                self.logs.append(f"OnError handled: {message}")
                return True
        return False

    def _exec_reporting(self, stmts):
        """Execute statements, giving OnError a chance at uncaught errors."""
        for st in stmts:
            self._check()
            try:
                self._exec(st)
            except Aborted:
                raise
            except Exception as exc:  # noqa: BLE001 - OnError decides
                if not self._dispatch_error(exc):
                    raise

    # -- abort --
    def abort(self):
        self._abort.set()

    @property
    def aborted(self):
        return self._abort.is_set()

    def _exit_app(self, code=0):
        """Implement ExitApp: run OnExit once, then unwind the runtime."""
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = 0
        self.logs.append(f"ExitApp({code}) - clean end of script")
        if self._run_exit_callbacks("Exit", code):
            return 0
        raise Aborted("ExitApp", code)

    def _check(self):
        if self._abort.is_set():
            raise Aborted("aborted via master kill-switch")

    # -- timers, hotkeys and the event loop --
    def _callback_arg(self, raw) -> str:
        """Resolve a callback/key argument without treating bare names as 0.

        AHK callback arguments are function names, not expression lookups:
        `SetTimer Background, 2000` must register ``Background`` even though
        no variable by that name exists.
        """
        text = str(raw).strip()
        if not text:
            return ""
        if "=>" in text:
            return text
        for _ in range(10):
            m = re.search(r"%([A-Za-z_]\w*)%", text)
            if not m:
                break
            text = (text[:m.start()] + str(self._get_var(m.group(1)))
                    + text[m.end():]).strip()
        if re.fullmatch(r"[A-Za-z_]\w*", text):
            key = self._var_key(text)
            return str(self.vars[key]) if key is not None else text
        if self._is_whole_quoted(text):
            return self._interp(text[1:-1])
        try:
            return str(self._eval_expr(text))
        except Exception:
            return text

    def _set_timer(self, name, period):
        """Install/replace/remove a SetTimer entry (AHK period semantics)."""
        label = self._callback_arg(name).strip()
        if not label:
            self.logs.append("SetTimer: empty name ignored")
            return 0
        try:
            period = int(float(period))
        except (TypeError, ValueError):
            self.logs.append(f"SetTimer {label}: non-numeric period {period!r}")
            return 0
        key = label.lower()
        if period == 0:
            existed = self._timers.pop(key, None) is not None
            self.logs.append(f"SetTimer {label} off")
            return 1 if existed else 0
        spec = self._callback_spec(label)
        if spec is None:
            self.logs.append(f"SetTimer {label}: unsupported callback (ignored)")
            return 0
        interval = max(1, abs(period)) / 1000.0
        self._timers[key] = {
            "name": label,
            "period": period,
            "due": time.monotonic() + interval,
            "interval": interval,
            "one_shot": period < 0,
            "spec": spec,
        }
        return 1

    def _process_due_timers(self) -> int:
        """Run due timer callbacks on the script thread; return fire count."""
        if self._paused:
            return 0
        now = time.monotonic()
        fired = 0
        for key, timer in list(self._timers.items()):
            if now < timer["due"]:
                continue
            if timer["one_shot"]:
                self._timers.pop(key, None)
            else:
                nxt = timer["due"] + timer["interval"]
                timer["due"] = nxt if nxt > now else now + timer["interval"]
            try:
                self._invoke_callback(timer["spec"],
                                      [timer["name"], timer["period"]])
            except Aborted:
                raise
            except Exception as exc:  # noqa: BLE001 - a timer must not kill the loop
                if not self._dispatch_error(exc):
                    self.logs.append(f"SetTimer {timer['name']} callback error: {exc}")
            fired += 1
        return fired

    def _register_hotkey(self, raw_args: list):
        """Handle both `Hotkey key, action, options` and call syntax."""
        args = [str(a).strip() for a in raw_args]
        if not args:
            return 0
        key = self._hotkey_key(args[0])
        if not key:
            self.logs.append("Hotkey: empty key ignored")
            return 0
        action_raw = args[1] if len(args) > 1 else ""
        options = ""
        if len(args) > 2:
            try:
                options = str(self._eval_expr(args[2])).strip()
            except Exception:
                options = str(args[2]).strip()
        turning_off = options.lower().startswith("off")
        if not action_raw or action_raw in ("0", '""', "''"):
            self._dynamic_hotkeys.pop(key.lower(), None)
            return 1
        if "=>" in action_raw:
            spec = self._callback_spec(action_raw)
        else:
            action = self._callback_arg(action_raw)
            if not action or action in ("0", ""):
                self._dynamic_hotkeys.pop(key.lower(), None)
                return 1
            spec = self._callback_spec(action) or self._callback_spec(action_raw)
        if spec is None:
            self.logs.append(f"Hotkey {key}: unsupported action {action_raw!r}")
            return 0
        if turning_off:
            self._dynamic_hotkeys.pop(key.lower(), None)
        else:
            self._dynamic_hotkeys[key.lower()] = {
                "key": key, "spec": spec, "options": options}
        return 1

    def _hotkey_key(self, raw: str) -> str:
        return self._callback_arg(raw).strip().strip('"')

    def _set_suspend(self, raw: str):
        arg = str(raw or "").strip().strip('"').lower()
        if arg in ("on", "1", "true"):
            self._suspended = True
        elif arg in ("off", "0", "false"):
            self._suspended = False
        elif arg == "permit":
            return
        else:
            self._suspended = not self._suspended
        self.vars["A_IsSuspended"] = 1 if self._suspended else 0

    def _set_pause(self, raw: str):
        arg = str(raw or "").strip().strip('"').lower()
        if arg in ("on", "1", "true"):
            self._paused = True
        elif arg in ("off", "0", "false"):
            self._paused = False
        elif arg == "toggle":
            self._paused = not self._paused
        else:
            self._paused = True
        self.vars["A_IsPaused"] = 1 if self._paused else 0

    def has_pending_events(self) -> bool:
        """True when the runtime should stay alive to service hooks."""
        if (self._keep_alive or self._timers or self._dynamic_hotkeys
                or self._message_handlers):
            return True
        if any(getattr(g, "visible", False) and not getattr(g, "destroyed", False)
               for g in self._guis):
            return True
        with self._process_lock:
            return any(child.poll() is None for child in self._children)

    def _pump_gui(self):
        """Let Qt deliver widget events, then surface a parked ExitApp."""
        try:
            from . import gui as _gui
            _gui.process_events()
        except Exception as exc:  # noqa: BLE001 - GUI must not kill the loop
            self.logs.append(f"GUI pump failed: {exc}")
        if self._pending_abort is not None:
            exc, self._pending_abort = self._pending_abort, None
            raise exc

    def _drain_messages(self):
        """Dispatch messages queued from timers, IPC or PostMessage."""
        while True:
            try:
                item = self._message_queue.get_nowait()
            except queue.Empty:
                return
            msg, wparam, lparam, hwnd = item
            self._dispatch_message(msg, wparam, lparam, hwnd)

    def wait(self, timeout: float | None = None, poll: float = 0.01) -> int:
        """Service timers, messages and children until nothing keeps us alive.

        Returns the number of timer/message events processed. ``timeout`` is
        wall-clock seconds; without it a persistent script waits indefinitely.
        """
        deadline = time.monotonic() + timeout if timeout is not None else None
        processed = 0
        while True:
            self._check()
            processed += self._process_due_timers()
            self._drain_messages()
            self._pump_gui()
            if not self.has_pending_events():
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(poll)
        return processed

    # -- entry points --
    def run_auto(self, exit_callbacks: bool = True):
        try:
            self._exec_reporting(self.script.auto_section)
        except Aborted:
            raise
        else:
            if exit_callbacks:
                self._run_exit_callbacks("Exit", 0)

    def fire_hotkey(self, key: str):
        for hk in self.script.hotkeys:
            if hk.key.lower() == key.lower():
                self._exec_reporting(hk.body)
                return True
        if self._suspended:
            return False
        dynamic = self._dynamic_hotkeys.get(key.lower())
        if dynamic is not None:
            self._invoke_callback(dynamic["spec"], [])
            return True
        return False

    # -- Windows-message surface (in-process + IPC) --
    @staticmethod
    def _message_int(value, default=0) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip(), 0)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return default

    def _message_id(self, raw) -> int | None:
        try:
            value = self._eval_expr(raw)
        except Exception:
            value = raw
        if isinstance(value, str):
            try:
                return int(value.strip(), 0)
            except ValueError:
                return None
        if isinstance(value, int):
            return value
        return None

    def _register_message(self, raw_args: list):
        if not raw_args:
            return 0
        msg = self._message_id(raw_args[0])
        if msg is None:
            self.logs.append(f"OnMessage: invalid message id {raw_args[0]!r}")
            return 0
        if len(raw_args) < 2:
            self._message_handlers.pop(msg, None)
            return 1
        callback_raw = str(raw_args[1]).strip()
        if not callback_raw or callback_raw in ("0", '""', "''"):
            self._message_handlers.pop(msg, None)
            return 1
        spec = self._callback_spec(callback_raw)
        if spec is None:
            try:
                callback_value = self._eval_expr(callback_raw)
            except Exception:
                callback_value = callback_raw
            if callback_value in (0, "", None):
                self._message_handlers.pop(msg, None)
                return 1
            if isinstance(callback_value, str):
                spec = self._callback_spec(callback_value)
        if spec is None:
            self.logs.append(
                f"OnMessage {msg:#x}: unsupported callback {callback_raw!r}")
            return 0
        handlers = self._message_handlers.setdefault(msg, [])
        if spec not in handlers:
            handlers.append(spec)
        return 1

    def _dispatch_message(self, msg: int, wparam=0, lparam=0, hwnd=0):
        msg = self._message_int(msg)
        wparam = self._message_int(wparam)
        lparam = self._message_int(lparam)
        hwnd = self._message_int(hwnd)
        result = 0
        with self._message_lock:
            for spec in list(self._message_handlers.get(msg, [])):
                try:
                    result = self._invoke_callback(
                        spec, [wparam, lparam, msg, hwnd])
                except Aborted:
                    raise
                except Exception as exc:  # noqa: BLE001 - handler must not kill loop
                    if not self._dispatch_error(exc):
                        self.logs.append(
                            f"OnMessage {msg:#x} callback error: {exc}")
        return result

    def _message_args(self, raw_args: list):
        def val(index, default=0):
            if index >= len(raw_args):
                return default
            try:
                return self._eval_expr(str(raw_args[index]).strip())
            except Exception:
                return default
        return (self._message_int(val(0)),
                self._message_int(val(1)),
                self._message_int(val(2)),
                val(3, ""), val(4, ""))

    def _post_message(self, raw_args: list, synchronous: bool = False):
        """Handle PostMessage/SendMessage command and call syntax.

        Local delivery is real: PostMessage queues and SendMessage dispatches
        immediately.  When this process was launched by another bridge runtime
        (``AHK_BRIDGE_IPC`` set) the message is routed to that parent instead.
        """
        if not raw_args:
            return 0
        msg, wparam, lparam, _control, title = self._message_args(raw_args)
        # SendMessage with no target is a self-send; submacro PostMessage with
        # no target goes to the parent (AHK broadcasts to sibling scripts).
        if synchronous and not str(title).strip():
            return self._dispatch_message(msg, wparam, lparam)
        payload = {"type": "send" if synchronous else "post",
                   "msg": msg, "w": wparam, "l": lparam,
                   "pid": os.getpid()}
        sent, reply = self._send_parent(payload, expect_reply=synchronous)
        if sent:
            if synchronous and isinstance(reply, dict):
                return self._message_int(reply.get("result", 0))
            return 0
        if synchronous:
            return self._dispatch_message(msg, wparam, lparam)
        self._message_queue.put((msg, wparam, lparam, 0))
        return 0

    # -- IPC transport for Run-spawned submacros --
    def _ensure_ipc(self) -> str | None:
        if self._ipc_path:
            return self._ipc_path
        if not self.allow_processes:
            return None
        try:
            self._ipc_dir = tempfile.mkdtemp(prefix="ahk-bridge-ipc-")
            path = os.path.join(self._ipc_dir, "sock")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(path)
            os.chmod(path, 0o600)
            sock.listen(8)
            sock.settimeout(0.2)
        except OSError as exc:
            self._log_once(f"IPC unavailable: {exc}")
            self._ipc_dir = None
            return None
        self._ipc_path = path
        self._ipc_sock = sock
        self._ipc_stop.clear()
        self._ipc_thread = threading.Thread(
            target=self._ipc_loop, name="ahk-bridge-ipc", daemon=True)
        self._ipc_thread.start()
        return path

    def _ipc_loop(self):
        sock = self._ipc_sock
        while not self._ipc_stop.is_set() and sock is not None:
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_ipc_conn, args=(conn,),
                             name="ahk-bridge-ipc-msg", daemon=True).start()

    def _handle_ipc_conn(self, conn):
        try:
            conn.settimeout(2.0)
            buf = b""
            while b"\n" not in buf and len(buf) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
            line = buf.split(b"\n", 1)[0]
            try:
                data = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return
            msg = self._message_int(data.get("msg", 0))
            wparam = self._message_int(data.get("w", 0))
            lparam = self._message_int(data.get("l", 0))
            if data.get("type") == "send":
                result = self._dispatch_message(msg, wparam, lparam)
                conn.sendall((json.dumps({"type": "reply",
                                          "result": result}) + "\n").encode())
            else:
                self._message_queue.put((msg, wparam, lparam, 0))
        except (OSError, ValueError) as exc:
            self._log_once(f"IPC message failed: {exc}")
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _send_parent(self, payload: dict, expect_reply: bool = False):
        """Send one JSON line to ``AHK_BRIDGE_IPC``; ``(ok, reply)``."""
        path = os.environ.get("AHK_BRIDGE_IPC", "")
        if not path or not os.path.exists(path):
            return False, None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(2.0)
                sock.connect(path)
                sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                if not expect_reply:
                    return True, None
                buf = b""
                while b"\n" not in buf:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                if not buf:
                    return True, None
                return True, json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
        except (OSError, ValueError) as exc:
            self._log_once(f"IPC send to parent failed: {exc}")
            return False, None

    def _shutdown_ipc(self):
        self._ipc_stop.set()
        sock, self._ipc_sock = self._ipc_sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        path, self._ipc_path = self._ipc_path, None
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
        directory, self._ipc_dir = self._ipc_dir, None
        if directory:
            try:
                os.rmdir(directory)
            except OSError:
                pass

    # -- process bridge --
    _URL_RE = re.compile(r"^(?:https?://|mailto:|discord:|roblox:)", re.I)

    def _translate_command(self, command: str):
        """Map an AHK Run target to (kind, target, args).

        AutoHotkey invocations are rewritten to this bridge's CLI, including
        Natro's `python /script x.ahk` shape (A_AhkPath is Python here).
        """
        text = str(command).strip()
        if text.startswith("*RunAs"):
            text = text[6:].strip()
            self._log_once("Run: elevation option ignored on Linux")
        if not text:
            return None
        if self._URL_RE.match(text):
            return ("url", text.strip('"'), [])
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
        if not tokens:
            return None
        switches = {"/script", "/restart", "/force", "/debug", "/errorstdout"}
        ahk_index = next((i for i, tok in enumerate(tokens)
                          if tok.lower().endswith(".ahk")), None)
        if ahk_index is not None:
            args = [tok for tok in tokens[ahk_index + 1:]
                    if tok.lower() not in switches]
            return ("ahk", self._abs_path(tokens[ahk_index]), args)
        first = tokens[0]
        first_low = os.path.basename(first).lower()
        if (("autohotkey" in first_low or first_low.startswith("python"))
                and any(tok.lower() in switches for tok in tokens[1:])):
            # An AutoHotkey invocation with no .ahk argument cannot be run on
            # Linux; spawning plain Python with `/restart` would be nonsense.
            return ("ahk-noscript", text, [])
        if first.lower().endswith((".bat", ".cmd", ".exe", ".com")):
            return ("windows", first, tokens[1:])
        return ("exec", tokens, [])

    def _execute_run(self, raw_target, wait: bool = False):
        try:
            target = self._eval_expr(str(raw_target).strip())
        except Exception:
            target = str(raw_target).strip()
        target = str(target).strip()
        if not target:
            self._log_once("Run: empty target ignored")
            return 0
        translated = self._translate_command(target)
        if translated is None:
            return 0
        kind, path, args = translated
        if kind == "ahk-noscript":
            self._log_once("Run: AutoHotkey invocation without an .ahk script ignored")
            return 0
        if kind == "windows":
            self._log_once(f"Run: Windows executable not supported on Linux: {path}")
            return 0
        if not self.allow_processes:
            self._log_once(f"Run: process spawning disabled: {target}")
            return 0
        if kind == "url":
            opener = shutil.which("xdg-open")
            if not opener:
                self._log_once("Run: xdg-open not found; URL ignored")
                return 0
            argv = [opener, path]
        elif kind == "ahk":
            if not os.path.isfile(path):
                self._log_once(f"Run: script not found: {path}")
                return 0
            source_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            argv = [sys.executable, "-m", "ahk_bridge.cli", "run", path]
            if args:
                argv += ["--", *args]
        else:
            argv = list(path)
        return self._spawn(argv, wait=wait, target=target)

    def _spawn(self, argv: list, wait: bool = False, target: str = ""):
        env = os.environ.copy()
        source_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        current = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = source_root + (os.pathsep + current if current else "")
        ipc = self._ensure_ipc()
        if ipc:
            env["AHK_BRIDGE_IPC"] = ipc
        env["AHK_BRIDGE_PARENT_PID"] = str(os.getpid())
        cwd = str(self.vars.get("A_WorkingDir") or os.getcwd())
        if not os.path.isdir(cwd):
            cwd = None
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
        except (OSError, ValueError) as exc:
            self._log_once(f"Run failed ({target or argv[0]}): {exc}")
            return 0
        with self._process_lock:
            self._children.append(proc)
        if not wait:
            return proc.pid
        try:
            while proc.poll() is None:
                self._check()
                self._process_due_timers()
                self._drain_messages()
                time.sleep(0.01)
        except Aborted:
            try:
                proc.terminate()
            except OSError:
                pass
            raise
        self._drain_messages()
        return proc.returncode if proc.returncode is not None else 0

    def _process_close(self, target) -> int:
        try:
            pid = int(str(target).strip())
        except (TypeError, ValueError):
            return 0
        if pid <= 0:
            return 0
        with self._process_lock:
            for proc in list(self._children):
                if proc.pid != pid:
                    continue
                if proc.poll() is not None:
                    return 1
                try:
                    proc.terminate()
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except OSError:
                    return 0
                return 1
        if pid == os.getpid():
            self.abort()
            return 1
        return 0

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
        self._refresh_builtin_vars()
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
            # Our vars are function-global already; static persists too.
            # `global Name := value` still has to perform the initialization.
            for name, raw in getattr(st, "initializers", []) or []:
                self._set_var(name, self._eval_expr(raw))
        elif isinstance(st, P.Setting):
            name = st.name.lower()
            if name == "setworkingdir":
                raw = (st.args or "").strip()
                target = str(self._eval_expr(raw)) if raw else ""
                if not target:
                    target = str(self.vars.get("A_ScriptDir") or os.getcwd())
                path = os.path.expanduser(target.replace("\\", os.sep))
                try:
                    os.chdir(path)
                    self.vars["A_WorkingDir"] = os.getcwd()
                    self.logs.append(f"SetWorkingDir -> {os.getcwd()}")
                except OSError as exc:
                    self.logs.append(f"SetWorkingDir failed: {exc}")
            elif name == "setkeydelay":
                m = re.search(r"-?\d+", st.args or "")
                if m:
                    self.vars["A_KeyDelay"] = int(m.group(0))
            elif name == "#persistent":
                self._keep_alive = True
            elif st.name.lower() != "label":
                self.logs.append(f"setting {st.name} {st.args} (noted, linux no-op)")
        elif isinstance(st, P.Include):
            self.logs.append(f"#Include {st.path} (not inlined; parse+run continues)")
        elif isinstance(st, P.IniOp):
            self._ini(st)
        elif isinstance(st, P.Assign):
            self._set_var(st.name, self._eval_expr(st.value))
        elif isinstance(st, P.AssignTarget):
            self._assign_target(st.target, st.value)
        elif isinstance(st, P.DynCall):
            # main-loop dispatch: head evaluates to a function name.
            name = self._resolve_call_name(st.head)
            if not name:
                self.logs.append(f"dyncall {st.head[:60]!r} unresolvable (logged)")
            else:
                self._call_value(P.FuncCall(name, st.args))
        elif isinstance(st, P.ExprStmt):
            # Ternary dispatch: evaluate branches for side effects, drop
            # the value (AHK v2 expression-statement semantics). Control
            # flow (throw/ExitApp) must never be swallowed here.
            try:
                self._eval_expr(st.expr)
            except (Aborted, RuntimeError):
                raise
            except Exception as e:
                self.logs.append(f"expr {st.expr[:60]!r} eval failed: {e}")
        elif isinstance(st, P.CompoundAssign):
            name = st.name
            # v1 dynamic segments: hour_%status%_time, %j%_time
            for _ in range(10):
                dm = re.search(r"%([A-Za-z_]\w*)%", name)
                if not dm:
                    break
                name = name[:dm.start()] + str(self._get_var(dm.group(1))) + name[dm.end():]
            cur = self._get_var(name)
            val = self._eval_expr(st.value)
            try:
                if st.op == "+=":
                    self._set_var(name, self._numval(cur) + self._numval(val))
                elif st.op == "-=":
                    self._set_var(name, self._numval(cur) - self._numval(val))
                elif st.op == "*=":
                    self._set_var(name, self._numval(cur) * self._numval(val))
                elif st.op in ("//=", "/="):
                    d = self._numval(val)
                    self._set_var(name, (self._numval(cur) // d) if st.op == "//=" else (self._numval(cur) / d))
                elif st.op == ".=":
                    self._set_var(name, str(cur) + str(val))
                elif st.op in ("|=", "&="):
                    a, b = int(self._numval(cur)), int(self._numval(val))
                    self._set_var(name, (a | b) if st.op == "|=" else (a & b))
            except (TypeError, ValueError, ZeroDivisionError):
                self._set_var(name, val if st.op == ".=" else cur)
        elif isinstance(st, P.IncDec):
            try:
                self._set_var(st.name, self._numval(self.vars.get(st.name, 0)) + st.delta)
            except (TypeError, ValueError):
                self._set_var(st.name, st.delta)
        elif isinstance(st, P.Seq):
            for sub in st.items:
                self._check()
                self._exec(sub)
        elif isinstance(st, P.Throw):
            raise RuntimeError(str(self._eval_expr(st.value)) if st.value else "throw")
        elif isinstance(st, P.ExitApp):
            code = st.code
            if isinstance(code, str):
                try:
                    code = self._eval_expr(code) if code.strip() else 0
                except Exception:
                    code = 0
            self._exit_app(code)
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
            # Evaluate expression WinTitles such as `"ahk_id " hwnd`; fall
            # back to the literal text for titles that are not expressions.
            self._win_activate_value(self._window_arg(st.title, st.title))
        elif isinstance(st, P.PixelSearch):
            self._pixel_search(st)
        else:
            self.logs.append(f"skip: {st!r}")

    def _call(self, c: P.FuncCall):
        self._call_value(c)

    def _invoke_method(self, name: str, raw_args: list):
        """Dispatch a dotted method call on a runtime object we model.

        Returns ``(handled, value)`` so ordinary dotted function names still
        fall through to the function/static tables.
        """
        base_expr, method = name.rsplit(".", 1)
        obj = self._eval_expr(base_expr)
        if hasattr(obj, "ahk_dispatch"):
            return True, obj.ahk_dispatch(method, raw_args, self)
        if isinstance(obj, TrayMenu):
            return True, obj.dispatch(method, raw_args, self)
        handled, result = self._class_static_call(base_expr, method, raw_args)
        if handled:
            return True, result
        if method.lower() == "bind":
            handled, result = self._bind_target(obj, raw_args, base_expr)
            if handled:
                return True, result
        return self._collection_method(obj, method, raw_args)

    def _dispatch_object_method(self, obj, method: str, raw_args: list,
                                base_raw: str = ""):
        """Dispatch one link of a `.A(...).B(...)` chain."""
        if hasattr(obj, "ahk_dispatch"):
            return obj.ahk_dispatch(method, raw_args, self)
        if isinstance(obj, TrayMenu):
            return obj.dispatch(method, raw_args, self)
        handled, result = self._class_static_call(base_raw, method, raw_args)
        if handled:
            return result
        if method.lower() == "bind":
            handled, result = self._bind_target(obj, raw_args, base_raw)
            if handled:
                return result
        handled, result = self._collection_method(obj, method, raw_args)
        if handled:
            return result
        self.logs.append(f"method .{method.lower()}() unsupported (logged)")
        return ""

    def _class_static_call(self, base_raw, method: str, raw_args: list):
        """`Class.Method(...)` for a static method declared in that class."""
        name = str(base_raw or "").strip()
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            return False, ""
        fn = self.script.class_statics.get((name.lower(), method.lower()))
        if fn is None:
            return False, ""
        return True, self._call_func(fn, raw_args)

    def _bind_target(self, obj, raw_args: list, base_raw: str = ""):
        """Resolve ``Fn.Bind(...)``: a bare function name (or a variable that
        holds one) becomes a :class:`BoundFunc`.

        A bare identifier evaluates to the numeric fallback when it is not a
        variable, so the raw base expression is the function reference.
        Quoted string values are not function references in AHK and are left
        unhandled, still logging as an unsupported method.
        """
        if isinstance(obj, BoundFunc):
            return False, ""
        raw = str(base_raw or "").strip()
        if self._is_whole_quoted(raw):
            return False, ""
        name = None
        if isinstance(obj, str) and re.fullmatch(r"[A-Za-z_]\w*", obj.strip()):
            name = obj.strip()
        elif re.fullmatch(r"[A-Za-z_]\w*", raw):
            name = raw
        if not name:
            return False, ""
        return True, BoundFunc(self, name,
                               [self._eval_expr(a) for a in raw_args])

    def _collection_method(self, obj, method: str, raw_args: list):
        """AHK v2 Map/Array methods used by the corpus."""
        m = method.lower()

        def val(i, default=None):
            return self._eval_expr(raw_args[i]) if i < len(raw_args) else default

        if isinstance(obj, dict):
            if m == "has":
                try:
                    return True, 1 if val(0) in obj else 0
                except TypeError:
                    return True, 0
            if m in ("delete", "remove"):
                try:
                    existed = val(0) in obj
                    if existed:
                        del obj[val(0)]
                    return True, 1 if existed else 0
                except (TypeError, KeyError):
                    return True, 0
            if m == "clone":
                return True, dict(obj)
            if m == "clear":
                obj.clear()
                return True, ""
            if m == "get":
                key = val(0)
                try:
                    return True, obj[key] if key in obj else val(1, "")
                except TypeError:
                    return True, val(1, "")
            if m == "set":
                obj[val(0)] = val(1)
                return True, obj
            if m in ("count", "length"):
                return True, len(obj)
            if m == "__enum":
                return True, list(obj.items())
        if isinstance(obj, list):
            if m == "push":
                obj.append(val(0))
                return True, len(obj)
            if m == "pop":
                return True, obj.pop() if obj else ""
            if m == "insertat":
                try:
                    index = int(val(0)) - 1
                    if 0 <= index <= len(obj):
                        obj.insert(index, val(1))
                        return True, ""
                except (TypeError, ValueError):
                    pass
                return True, ""
            if m in ("removeat", "delete"):
                try:
                    index = int(val(0)) - 1
                    if 0 <= index < len(obj):
                        return True, obj.pop(index)
                except (TypeError, ValueError):
                    pass
                return True, ""
            if m == "has":
                try:
                    index = int(val(0)) - 1
                    return True, 1 if 0 <= index < len(obj) else 0
                except (TypeError, ValueError):
                    return True, 0
            if m == "clone":
                return True, list(obj)
            if m == "clear":
                obj.clear()
                return True, ""
            if m in ("count", "length"):
                return True, len(obj)
            if m == "__enum":
                return True, list(obj)
        if isinstance(obj, str) and m == "length":
            return True, len(obj)
        return False, None

    def _call_value(self, c: P.FuncCall):
        """Execute call, returning the function's Return value (or builtin)."""
        name = c.name
        if "%" in name:
            # dynamic dispatch: nm_Tab%tab%%c%(), nm_FieldSelect%i%()
            for _ in range(10):
                dm = re.search(r"%([A-Za-z_]\w*)%", name)
                if not dm:
                    break
                name = name[:dm.start()] + str(self._get_var(dm.group(1))) + name[dm.end():]
            if name != c.name:
                c = P.FuncCall(name, c.args)
        if c.name == "__raw__":
            self.logs.append(f"raw: {c.args[0] if c.args else ''}")
            return ""
        if "." in c.name:
            handled, result = self._invoke_method(c.name, c.args)
            if handled:
                return result
        fn = self.script.functions.get(c.name)
        if fn is None:
            key = self._var_key(c.name)
            if key is not None and isinstance(self.vars.get(key), BoundFunc):
                return self.vars[key].call(c.args)
            return self._builtin(c)
        return self._call_func(fn, c.args)

    def _call_func(self, fn, raw_args: list):
        """Run one FuncDef with raw source arguments."""
        saved = dict(self.vars)
        defaults = getattr(fn, "defaults", None) or {}
        for index, p in enumerate(fn.params):
            if index < len(raw_args):
                self.vars[p] = self._eval_expr(raw_args[index])
            elif p in defaults:
                default = defaults[p]
                if str(default).strip().lower() == "unset":
                    # AHK's `p := unset`: omitted means genuinely unset.
                    self.vars.pop(p, None)
                else:
                    self.vars[p] = self._eval_expr(default)
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
        if low.startswith("gdip_"):
            return self._gdip_builtin(c.name, c.args)
        if low == "gui":
            from .gui import Gui as _Gui
            args = c.args

            def gui_arg(index, default=""):
                if index < len(args) and str(args[index]).strip():
                    try:
                        return self._eval_expr(args[index])
                    except Exception:
                        return default
                return default

            return _Gui(self, options=gui_arg(0, ""), title=gui_arg(1, ""))
        if low == "onexit":
            spec = self._callback_spec(c.args[0]) if c.args else None
            addremove = 1
            if len(c.args) > 1:
                try:
                    addremove = int(self._eval_expr(c.args[1]))
                except (TypeError, ValueError):
                    addremove = 1
            if spec is None:
                self.logs.append("OnExit: unsupported callback expression (logged)")
                return 0
            if addremove == 0:
                self._exit_callbacks = [s for s in self._exit_callbacks if s != spec]
            elif addremove == -1:
                self._exit_callbacks.insert(0, spec)
            else:
                self._exit_callbacks.append(spec)
            self.logs.append(f"OnExit registered {spec[1]!r} (AddRemove={addremove})")
            return 1
        if low == "onerror":
            spec = self._callback_spec(c.args[0]) if c.args else None
            addremove = 1
            if len(c.args) > 1:
                try:
                    addremove = int(self._eval_expr(c.args[1]))
                except (TypeError, ValueError):
                    addremove = 1
            if spec is None:
                self.logs.append("OnError: unsupported callback expression (logged)")
                return 0
            if addremove == 0:
                self._error_callbacks = [
                    s for s in self._error_callbacks if s != spec]
            elif addremove == -1:
                self._error_callbacks.insert(0, spec)
            else:
                self._error_callbacks.append(spec)
            self.logs.append(f"OnError registered {spec[1]!r} (AddRemove={addremove})")
            return 1
        if low == "sleep" and c.args:
            self.sim.sleep_ms(self._resolve_sleep(c.args[0]))
            return ""
        if low == "settimer" and c.args:
            period = self._eval_expr(c.args[1]) if len(c.args) > 1 else 250
            return self._set_timer(c.args[0], period)
        if low == "hotkey" and c.args:
            return self._register_hotkey(c.args)
        if low == "onmessage":
            return self._register_message(c.args)
        if low in ("postmessage", "sendmessage"):
            return self._post_message(c.args, synchronous=low == "sendmessage")
        if low in ("run", "runwait"):
            raw = c.args[0] if c.args else ""
            return self._execute_run(raw, wait=(low == "runwait"))
        if low == "fileopen" and c.args:
            try:
                path = self._abs_path(self._eval_expr(c.args[0]))
                mode = (self._eval_expr(c.args[1])
                        if len(c.args) > 1 else "r")
                encoding = (self._eval_expr(c.args[2])
                            if len(c.args) > 2 else "")
                return AhkFile(self, path, str(mode), str(encoding))
            except (OSError, ValueError, TypeError) as exc:
                self._log_once(f"FileOpen failed: {exc} (returns falsy)")
                return 0
        if low == "processclose" and c.args:
            return self._process_close(self._eval_expr(c.args[0]))
        if low == "exitapp":
            code = 0
            if c.args:
                try:
                    code = int(self._eval_expr(c.args[0]))
                except (TypeError, ValueError):
                    code = 0
            return self._exit_app(code)
        if low == "imagesearch":
            return self._image_search(c.args)
        if low in ("send", "sendinput", "sendevent", "sendplay", "sendtext") and c.args:
            self._send_eval(str(c.args[0]))
            return ""
        if low == "msgbox" and c.args:
            self.logs.append("MsgBox: " + self._interp(str(c.args[0])))
            return ""
        if low == "winactivate" and c.args:
            return self._win_activate_value(self._window_arg(c.args[0], ""))
        if low == "wingetpos":
            return self._win_get_pos(c.args, client=False)
        if low == "wingetclientpos":
            return self._win_get_pos(c.args, client=True)
        if low == "wingettitle":
            return self._win_get_title(c.args)
        if low == "winexist":
            return self._win_exist(c.args)
        if low == "wingetcount":
            return self._win_get_count(c.args)
        if low == "wingetlist":
            return self._win_get_list(c.args)
        if low in ("winwait", "winwaitclose", "winwaitactive",
                   "winwaitnotactive"):
            return self._win_wait(low, c.args)
        if low == "winactive":
            return self._win_active(c.args)
        if low in ("winclose", "winkill"):
            return self._win_close(c.args, kill=(low == "winkill"))
        if low == "winmove":
            return self._win_move(c.args)
        if low == "winsettransparent":
            return self._win_set_transparent(c.args)
        if low == "wingetpid":
            return self._win_get_pid(c.args)
        if low == "wingetprocessname":
            return self._win_get_process_name(c.args)
        if low == "controlgetpos":
            return self._control_get_pos(c.args)
        if low == "controlgettext":
            return self._control_get_text(c.args)
        if low == "controlgethwnd":
            return self._control_get_hwnd(c.args)
        if low in ("buffer", "numget", "numput", "strget", "strput",
                   "strptr", "varptr", "objptr"):
            return self._memory_builtin(low, c.args)
        if low == "dllcall":
            return self._dll_call(c.args)
        return self._pure_builtin(low, c.args)

    def _image_search(self, args: list):
        """Native AHK ``ImageSearch`` on top of the vision layer.

        v1/v2 syntax accepted: ``ImageSearch(&X, &Y, X1, Y1, X2, Y2,
        ImageFile)`` with ``*n`` variation, ``*TransN`` and ``*IconN``
        prefixes in ImageFile.  Coordinates are screen coordinates and the
        search rectangle is inclusive, as documented by AHK.
        """
        import os as _os
        from . import vision

        def raw(i):
            return args[i].strip() if i < len(args) else ""

        def value(i, default=None):
            text = raw(i)
            if text == "":
                return default
            return self._eval_expr(text)

        def byref(i):
            text = raw(i)
            if text.startswith("&"):
                target = text[1:].strip()
                if re.fullmatch(r"[A-Za-z_]\w*", target):
                    return target
            return None

        tx, ty = byref(0), byref(1)
        # AHK resets output coordinates to 0 when the image is not found.
        if tx:
            self.vars[tx] = 0
        if ty:
            self.vars[ty] = 0

        file_arg = raw(6)
        if not file_arg:
            self.logs.append("ImageSearch: missing ImageFile (returns 0)")
            return 0
        spec = str(self._eval_expr(file_arg)).strip()
        variation, trans, tokens = 0, None, []
        for token in spec.split():
            if not token.startswith("*"):
                tokens.append(token)
                continue
            m = re.fullmatch(r"\*(\d+)", token)
            if m:
                variation = int(m.group(1))
                continue
            m = re.fullmatch(r"(?i)\*trans(?:=)?(.+)", token)
            if m:
                color = m.group(1).strip().lower()
                trans = {"black": 0x000000, "white": 0xFFFFFF,
                         "silver": 0xC0C0C0, "gray": 0x808080,
                         "red": 0xFF0000, "green": 0x00FF00,
                         "blue": 0x0000FF}.get(color)
                if trans is None:
                    try:
                        trans = int(color, 0)
                    except ValueError:
                        trans = None
                continue
            # *IconN selects an icon resource on Windows; the image file is
            # a normal PNG here, so the option is harmless.
            if re.fullmatch(r"(?i)\*icon\d+", token):
                continue
            self.logs.append(f"ImageSearch: ignoring option {token!r}")
        path = " ".join(tokens).strip().strip('"')
        if not path:
            self.logs.append("ImageSearch: no image file after options (returns 0)")
            return 0
        path = path.replace("\\", _os.sep)
        base = str(self.vars.get("A_WorkingDir") or _os.getcwd())
        if not _os.path.isabs(path):
            path = _os.path.join(base, path)
        path = _os.path.expanduser(path)

        try:
            x1 = int(value(2, 0) or 0)
            y1 = int(value(3, 0) or 0)
            x2 = value(4, None)
            y2 = value(5, None)
            x2 = int(x2) if x2 not in (None, "") else 0
            y2 = int(y2) if y2 not in (None, "") else 0
        except (TypeError, ValueError):
            self.logs.append("ImageSearch: non-numeric coordinates (returns 0)")
            return 0
        screen_w = int(self.vars.get("A_ScreenWidth") or 1920)
        screen_h = int(self.vars.get("A_ScreenHeight") or 1080)
        if x2 <= 0:
            x2 = screen_w - 1
        if y2 <= 0:
            y2 = screen_h - 1
        if x2 < x1 or y2 < y1:
            self.logs.append("ImageSearch: empty search rectangle (returns 0)")
            return 0

        try:
            needle = vision.from_file(path)
        except ValueError as exc:
            key = f"imagesearch:{path}"
            if key not in self._stub_warned:
                self._stub_warned.add(key)
                self.logs.append(f"ImageSearch: {exc} (returns 2)")
            return 2

        hay = 0
        try:
            hay = vision.from_screen(
                f"{x1}|{y1}|{x2 - x1 + 1}|{y2 - y1 + 1}")
            count, text = vision.image_search(
                hay, needle, variation=variation, trans=trans)
        except Exception as exc:  # noqa: BLE001 - script must not crash
            self.logs.append(f"ImageSearch failed: {exc} (returns 0)")
            return 0
        finally:
            vision.dispose(hay)
            vision.dispose(needle)

        tx, ty = byref(0), byref(1)
        found = count > 0 and text != ""
        coords = (0, 0)
        if found:
            first = text.split("\n", 1)[0]
            try:
                cx, cy = first.split(",", 1)
                coords = (x1 + int(cx), y1 + int(cy))
            except ValueError:
                found = False
        if tx:
            self.vars[tx] = coords[0]
        if ty:
            self.vars[ty] = coords[1]
        return 1 if found else 0

    def _gdip_builtin(self, name: str, args: list):
        """Execute the Gdip_* surface Natro's eyes actually use.

        Unknown Gdip_* names stay logged stubs (one line each).  Argument
        positions are preserved by the parser for this namespace because the
        AHK signatures use positional omitted parameters.
        """
        from . import vision
        low = name.lower()

        def raw(i):
            return args[i].strip() if i < len(args) else ""

        def val(i, default=""):
            a = raw(i)
            return default if a == "" else self._eval_expr(a)

        def byref(i):
            a = raw(i)
            if a.startswith("&"):
                target = a[1:].strip()
                if re.fullmatch(r"[A-Za-z_]\w*", target):
                    return target
            return None

        if low == "gdip_bitmapfrombase64":
            try:
                return vision.from_base64(val(0))
            except (TypeError, ValueError) as exc:
                self.logs.append(f"Gdip_BitmapFromBase64 failed: {exc}")
                return 0
        if low == "gdip_bitmapfromscreen":
            # Gdip_BitmapFromScreen(Screen:=0, Raster:="") accepts v1-style
            # named arguments.  Scan instead of evaluating the raw text so
            # `Screen`/`Raster` never leak into script variables.
            screen_arg, named = None, False
            for a in args:
                m = re.match(r"(?i)^\s*Screen\s*:=\s*(.*)$", a, re.DOTALL)
                if m:
                    screen_arg, named = m.group(1).strip(), True
                    break
            if not named:
                first = raw(0)
                if re.match(r"(?i)^\s*Raster\s*:=", first):
                    screen_arg = ""
                else:
                    screen_arg = first
            try:
                region = self._eval_expr(screen_arg) if screen_arg.strip() else None
                return vision.from_screen(region)
            except Exception as exc:
                self.logs.append(f"Gdip_BitmapFromScreen failed: {exc}")
                return 0
        if low == "gdip_createbitmap":
            try:
                return vision.create_bitmap(val(0, 0), val(1, 0))
            except (TypeError, ValueError) as exc:
                self.logs.append(f"Gdip_CreateBitmap failed: {exc}")
                return 0
        if low == "gdip_disposeimage":
            return vision.dispose(val(0, 0))
        if low == "gdip_getimagewidth":
            return vision.width(val(0, 0))
        if low == "gdip_getimageheight":
            return vision.height(val(0, 0))
        if low == "gdip_getimagedimensions":
            dims = vision.dimensions(val(0, 0)) or (0, 0)
            for index, value in ((1, dims[0]), (2, dims[1])):
                target = byref(index)
                if target:
                    self.vars[target] = value
            return 0
        if low == "gdip_imagesearch":
            count, text = vision.image_search(
                val(0, 0), val(1, 0),
                outer_x1=val(3, 0), outer_y1=val(4, 0),
                outer_x2=val(5, 0), outer_y2=val(6, 0),
                variation=val(7, 0), trans=val(8, None),
                direction=val(9, 1), instances=val(10, 1),
                line_delim=val(11, "\n"), coord_delim=val(12, ","),
            )
            target = byref(2)
            if target and count >= 0:
                self.vars[target] = text
            return count

        if low not in self._stub_warned:
            self._stub_warned.add(low)
            self.logs.append(f"stub {name}() -> falsy (Gdip surface not ported)")
        return ""

    def _log_once(self, message: str):
        if message not in self._stub_warned:
            self._stub_warned.add(message)
            self.logs.append(message)

    def _var_key(self, name: str):
        """Canonical key for an AHK variable (names are case-insensitive)."""
        name = str(name)
        if name in self.vars:
            return name
        low = name.lower()
        for key in self.vars:
            if key.lower() == low:
                return key
        return None

    def _get_var(self, name: str):
        """Read a variable, lazily loading the real system clipboard.

        ``A_Clipboard`` is special in AHK.  Read it once on first use so a
        user's existing clipboard is visible, but never overwrite a value the
        script has just assigned (that would race the external helper).
        AHK variable names are case-insensitive; Natro mixes `A_Index` with
        the legacy `A_index` spelling in generated expressions.
        """
        key = self._var_key(name)
        if key is not None:
            name = key
        if name.lower() == "a_clipboard" and not self._clipboard_loaded:
            from . import clipboard as _clipboard
            self.vars[name] = _clipboard.read_text()
            self._clipboard_loaded = True
        return self.vars.get(name, "")

    def _set_var(self, name: str, value):
        key = self._var_key(name)
        if key is not None:
            name = key
        if name.lower() == "a_clipboard":
            from . import clipboard as _clipboard
            try:
                ok = _clipboard.write_text(value)
            except Exception:
                ok = False
            self._clipboard_loaded = True
            if not ok:
                self._log_once(
                    "clipboard: no wl-copy/xclip/xsel helper; "
                    "A_Clipboard kept in-script only (logged)")
        self.vars[name] = value

    # -- Windows and controls (v0.7) -------------------------------------
    def _window_arg(self, raw, default=""):
        """Evaluate an AHK WinTitle/control argument without leaking errors."""
        text = str(raw or "").strip()
        if not text:
            return default
        try:
            return self._eval_expr(text)
        except Exception:
            return default

    def _own_handle(self, hwnd: int):
        for gui in reversed(self._guis):
            if gui.hwnd == hwnd:
                if getattr(gui, "destroyed", False):
                    return None
                return {"kind": "gui", "gui": gui, "control": None,
                        "hwnd": gui.hwnd, "title": gui.title}
            for control in gui.controls:
                if control.hwnd == hwnd:
                    if getattr(gui, "destroyed", False):
                        return None
                    return {"kind": "control", "gui": gui,
                            "control": control, "hwnd": control.hwnd,
                            "title": gui.title}
        return None

    def _resolve_window(self, value):
        """Resolve an AHK WinTitle (or a Gui/GuiControl object) to a target.

        Own Gui windows are authoritative.  X11/XWayland windows are looked
        up through ``xdotool``; native Wayland surfaces have no global handle
        and deliberately return None (the caller logs the exact limitation).
        """
        if value is not None and not isinstance(value, str):
            if hasattr(value, "gui") and hasattr(value, "hwnd"):
                gui = value.gui
                if getattr(gui, "destroyed", False):
                    return None
                return {"kind": "control", "gui": gui, "control": value,
                        "hwnd": getattr(value, "hwnd", 0),
                        "title": getattr(gui, "title", "")}
            if hasattr(value, "controls") and hasattr(value, "hwnd"):
                if getattr(value, "destroyed", False):
                    return None
                return {"kind": "gui", "gui": value, "control": None,
                        "hwnd": getattr(value, "hwnd", 0),
                        "title": getattr(value, "title", "")}
            try:
                value = str(int(value))
            except (TypeError, ValueError):
                value = str(value)

        text = str(value or "").strip()
        if text.lower().startswith("ahk_id "):
            token = text[7:].strip().strip('"')
            try:
                hwnd = int(token, 0)
            except (TypeError, ValueError):
                hwnd = 0
            if not hwnd:
                return None
            own = self._own_handle(hwnd)
            if own is not None:
                return own
            from . import window_ops
            if window_ops.geometry(hwnd):
                return {"kind": "external", "gui": None, "control": None,
                        "hwnd": hwnd, "title": window_ops.title(hwnd)}
            self._log_once(
                f"window ahk_id {hwnd} not found (X11/XWayland limit; "
                "native Wayland surfaces have no HWND)")
            return None

        if text in ("", "A"):
            active = getattr(self, "_active_gui", None)
            if active is not None and not getattr(active, "destroyed", False):
                return {"kind": "gui", "gui": active, "control": None,
                        "hwnd": active.hwnd, "title": active.title}
            for gui in reversed(self._guis):
                if not gui.destroyed and gui.visible:
                    return {"kind": "gui", "gui": gui, "control": None,
                            "hwnd": gui.hwnd, "title": gui.title}
            return None

        low = text.lower()
        # `ahk_class AutoHotkeyGUI` identifies one of our Gui windows.  A
        # leading title phrase is matched as a case-insensitive substring,
        # mirroring AHK's default title matching.
        class_own = "ahk_class autohotkeygui" in low
        phrase = re.split(r"\s+ahk_(?:exe|class|pid|group)\b", text,
                          flags=re.IGNORECASE)[0].strip().strip('"')
        for gui in reversed(self._guis):
            if gui.destroyed:
                continue
            if class_own or (phrase and phrase.lower() in gui.title.lower()):
                return {"kind": "gui", "gui": gui, "control": None,
                        "hwnd": gui.hwnd, "title": gui.title}

        from . import window_ops
        hwnd = window_ops.find(text)
        if hwnd:
            return {"kind": "external", "gui": None, "control": None,
                    "hwnd": hwnd, "title": window_ops.title(hwnd)}
        self._log_once(
            f"window {text!r} not found (X11/XWayland helper or native "
            "Wayland surface; no HWND)")
        return None

    def _window_rect(self, target, client: bool = False):
        if target is None:
            return (0, 0, 0, 0)
        gui = target.get("gui")
        control = target.get("control")
        if gui is not None:
            if control is not None:
                return self._control_rect(gui, control, screen=True)
            widget = getattr(gui, "widget", None)
            if widget is None:
                return (0, 0, 200, 200)
            if client:
                try:
                    from PySide6.QtCore import QPoint
                    point = widget.mapToGlobal(QPoint(0, 0))
                    return (point.x(), point.y(),
                            widget.width(), widget.height())
                except Exception:
                    pass
            geom = widget.frameGeometry()
            return (geom.x(), geom.y(), geom.width(), geom.height())
        from . import window_ops
        return window_ops.geometry(int(target.get("hwnd", 0)),
                                   client=client) or (0, 0, 0, 0)

    def _control_rect(self, gui, control, screen: bool = True):
        widget = getattr(control, "widget", None)
        if widget is None or getattr(gui, "widget", None) is None:
            return (getattr(control, "_x", 0), getattr(control, "_y", 0),
                    getattr(control, "_w", 0), getattr(control, "_h", 0))
        try:
            from PySide6.QtCore import QPoint
            if screen:
                point = widget.mapToGlobal(QPoint(0, 0))
            else:
                point = widget.mapTo(gui.widget, QPoint(0, 0))
            return (point.x(), point.y(), widget.width(), widget.height())
        except Exception:
            return (getattr(control, "_x", 0), getattr(control, "_y", 0),
                    getattr(control, "_w", 0), getattr(control, "_h", 0))

    def _find_control(self, control_value, window_value=""):
        """Resolve a control object, name, `ahk_id`, or ClassNN."""
        if control_value is not None and hasattr(control_value, "gui") \
                and hasattr(control_value, "hwnd"):
            return control_value.gui, control_value
        text = str(control_value or "").strip().strip('"')
        if not text:
            return None
        if text.lower().startswith("ahk_id "):
            try:
                hwnd = int(text[7:].strip(), 0)
            except (TypeError, ValueError):
                return None
            own = self._own_handle(hwnd)
            if own and own.get("control") is not None:
                return own["gui"], own["control"]
            return None
        if re.fullmatch(r"\d+", text):
            own = self._own_handle(int(text))
            if own and own.get("control") is not None:
                return own["gui"], own["control"]
            return None

        target = self._resolve_window(
            self._window_arg(window_value, "") if str(window_value).strip()
            else "A")
        if target is None or target.get("gui") is None:
            self._log_once(
                f"ControlGet*: window {window_value!r} has no accessible "
                "child controls on this Linux surface (logged)")
            return None
        gui = target["gui"]
        direct = gui._by_name.get(text.lower())
        if direct is not None:
            return gui, direct
        m = re.fullmatch(
            r"(?i)(Static|Button|Edit|ComboBox|msctls_updown32|"
            r"SysTabControl32|msctls_trackbar32|msctls_hotkey32)(\d+)",
            text)
        if m:
            class_name, index = m.group(1).lower(), int(m.group(2))
            classes = {
                "static": {"Text", "Picture"},
                "button": {"Button", "CheckBox", "GroupBox"},
                "edit": {"Edit"},
                "combobox": {"DDL"},
                "msctls_updown32": {"UpDown"},
                "systabcontrol32": {"Tab"},
                "msctls_trackbar32": {"Slider"},
                "msctls_hotkey32": {"Hotkey"},
            }
            wanted = classes.get(class_name, set())
            if index > 0:
                seen = 0
                for control in gui.controls:
                    if control.type in wanted:
                        seen += 1
                        if seen == index:
                            return gui, control
        self._log_once(f"control {text!r} not found (logged)")
        return None

    def _win_get_pos(self, args, client=False):
        raw_title = args[4] if len(args) > 4 else ""
        target = self._resolve_window(self._window_arg(raw_title, ""))
        if target is None:
            # Natro's GetRobloxClientPos() relies on this: a missing window is
            # a TargetError, not a successful 0x0 client rectangle.
            raise TargetError(
                f"WinGet{'Client' if client else ''}Pos: target window not found")
        rect = self._window_rect(target, client=client)
        for index, value in enumerate(rect):
            if index < len(args):
                self._assign_output(args[index], value)
        return 1

    def _win_get_title(self, args):
        raw = args[0] if args else ""
        target = self._resolve_window(self._window_arg(raw, ""))
        if target is None:
            raise TargetError("WinGetTitle: target window not found")
        return target.get("title", "")

    def _win_exist(self, args):
        raw = args[0] if args else ""
        target = self._resolve_window(self._window_arg(raw, ""))
        return int(target.get("hwnd", 0)) if target else 0

    def _win_get_count(self, args):
        return len(self._win_get_list(args))

    def _win_get_list(self, args):
        """AHK WinGetList: visible own Guis plus X11/XWayland windows.

        ``WinText``/``ExcludeText`` filter on control text, which the X11
        bridge cannot read for a foreign window; refusing them is logged
        instead of returning windows that do not satisfy the filter.
        """
        title_raw = self._window_arg(args[0], "") if len(args) > 0 else ""
        win_text = self._window_arg(args[1], "") if len(args) > 1 else ""
        excl_title = self._window_arg(args[2], "") if len(args) > 2 else ""
        excl_text = self._window_arg(args[3], "") if len(args) > 3 else ""
        if str(win_text or "").strip() or str(excl_text or "").strip():
            self._log_once(
                "WinGetList: WinText/ExcludeText need foreign control text; "
                "not available on Linux (returns no windows)")
            return []
        from . import window_ops
        spec = window_ops.parse_spec(str(title_raw or ""))
        if spec["group"]:
            self._log_once(
                "WinGetList: ahk_group needs a GroupAdd registry (not "
                "available on Linux; returns no windows)")
            return []
        found = []
        for gui in self._guis:
            if gui.destroyed or not gui.visible:
                continue
            if self._own_gui_matches(gui, spec) and int(gui.hwnd) not in found:
                found.append(int(gui.hwnd))
        if spec["id"]:
            external = [spec["id"]] if window_ops.geometry(spec["id"]) else []
        elif any(spec[key] for key in ("title", "exe", "class", "pid")):
            external = window_ops.find_all(str(title_raw))
        else:
            external = window_ops.list_windows()
        for hwnd in external:
            if int(hwnd) not in found:
                found.append(int(hwnd))
        exclude = str(excl_title or "").strip().strip('"')
        if exclude:
            found = [hwnd for hwnd in found
                     if exclude.lower() not in self._window_title(hwnd).lower()]
        return found

    def _own_gui_matches(self, gui, spec) -> bool:
        """Apply WinTitle criteria to an own Gui window."""
        from . import window_ops
        if spec["group"]:
            return False
        if spec["id"] and int(gui.hwnd) != int(spec["id"]):
            return False
        if spec["pid"] and int(spec["pid"]) != os.getpid():
            return False
        if spec["exe"] and not window_ops._exe_matches(
                spec["exe"], window_ops._process_identity(os.getpid())):
            return False
        if spec["class"] and spec["class"] != "AutoHotkeyGUI":
            return False
        if spec["title"] and spec["title"].lower() not in gui.title.lower():
            return False
        return True

    # -- window waiting (v0.9) --------------------------------------------
    def _active_window_hwnd(self) -> int:
        """The active own-Gui handle, else the X11/XWayland active window."""
        active = getattr(self, "_active_gui", None)
        if (active is not None and not getattr(active, "destroyed", False)
                and getattr(active, "visible", True)):
            return int(getattr(active, "hwnd", 0) or 0)
        from . import window_ops
        return int(window_ops.active() or 0)

    def _wait_args(self, args):
        """Evaluate WinWait*-style arguments, keeping omitted slots.

        Returns (title_raw, win_text, timeout_seconds_or_None, excl_title,
        excl_text).  A blank Timeout means wait forever, 0 means check once.
        """
        title_raw = str(args[0]).strip() if len(args) > 0 else ""
        win_text = str(self._window_arg(args[1], "")
                       if len(args) > 1 else "").strip()
        timeout_raw = args[2] if len(args) > 2 else ""
        excl_title = str(self._window_arg(args[3], "")
                         if len(args) > 3 else "").strip().strip('"')
        excl_text = str(self._window_arg(args[4], "")
                        if len(args) > 4 else "").strip()
        timeout = None
        if str(timeout_raw or "").strip():
            try:
                timeout = max(0.0, float(self._window_arg(timeout_raw, 0)))
            except (TypeError, ValueError):
                timeout = 0.0
        return title_raw, win_text, timeout, excl_title, excl_text

    def _wait_text_unsupported(self, win_text, excl_text) -> bool:
        if str(win_text or "").strip() or str(excl_text or "").strip():
            self._log_once(
                "WinWait*: WinText/ExcludeText need foreign control text; "
                "not available on Linux (no match, never a fake success)")
            return True
        return False

    def _wait_target(self, title_raw, excl_title=""):
        target = self._resolve_window(self._window_arg(title_raw, ""))
        if target is None:
            return None
        if excl_title and excl_title.lower() in str(
                target.get("title", "")).lower():
            return None
        return target

    def _wait_active_match(self, title_raw, excl_title="") -> int:
        target = self._wait_target(title_raw, excl_title)
        if target is None:
            return 0
        hwnd = int(target.get("hwnd", 0) or 0)
        active = self._active_window_hwnd()
        return hwnd if hwnd and active and hwnd == active else 0

    def _wait_poll(self, predicate, timeout):
        """Poll ``predicate`` until truthy, timeout, or the abort signal.

        Timeout is in seconds; None waits indefinitely, 0 checks exactly
        once.  The poll interval matches AHK's WinWait behaviour.
        """
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            self._check()
            value = predicate()
            if value:
                return value
            if deadline is not None and self._clock() >= deadline:
                return 0
            self._wait_sleep(50)

    def _wait_sleep(self, ms: int):
        # Input backends sleep themselves; the dry backend only records it so
        # tests can use a virtual clock instead of wall-clock waits.
        self.sim.sleep_ms(ms)

    def _win_wait(self, low: str, args):
        title_raw, win_text, timeout, excl_title, excl_text = \
            self._wait_args(args)
        if self._wait_text_unsupported(win_text, excl_text):
            return 0
        if low == "winwait":
            def predicate():
                target = self._wait_target(title_raw, excl_title)
                return int(target.get("hwnd", 0)) if target else 0
            return self._wait_poll(predicate, timeout)
        if low == "winwaitactive":
            def predicate():
                return self._wait_active_match(title_raw, excl_title)
            return self._wait_poll(predicate, timeout)
        if low == "winwaitnotactive":
            def predicate():
                return 0 if self._wait_active_match(
                    title_raw, excl_title) else 1
            return self._wait_poll(predicate, timeout)
        # WinWaitClose: succeeds as soon as no matching window exists,
        # including when none exists on the first check.
        def predicate():
            return 0 if self._wait_target(title_raw, excl_title) else 1
        return self._wait_poll(predicate, timeout)

    def _win_active(self, args):
        title_raw, win_text, _timeout, excl_title, excl_text = \
            self._wait_args(args)
        if self._wait_text_unsupported(win_text, excl_text):
            return 0
        if not title_raw.strip() and not excl_title:
            # AHK would use the Last Found Window here; this runtime does not
            # track it, so report the real active handle instead of inventing
            # a match.
            return self._active_window_hwnd()
        return self._wait_active_match(title_raw, excl_title)

    def _window_title(self, hwnd) -> str:
        own = self._own_handle(int(hwnd))
        if own is not None:
            return str(own.get("title", ""))
        from . import window_ops
        return window_ops.title(int(hwnd))

    def _win_close(self, args, kill=False):
        raw = args[0] if args else ""
        target = self._resolve_window(self._window_arg(raw, ""))
        if target is None:
            return 0
        gui = target.get("gui")
        if gui is not None:
            if kill:
                gui._destroy()
            else:
                gui._close()
                # WM_CLOSE destroys a normal window.  A Close handler that
                # requested ExitApp is handled by _close()/the runtime; a
                # plain hidden Gui is not a live window for WinExist().
                if not gui.destroyed and self._pending_abort is None:
                    gui._destroy()
            return 1
        from . import window_ops
        return 1 if window_ops.close(int(target["hwnd"]), kill=kill) else 0

    def _win_move(self, args):
        if len(args) < 2:
            return 0
        try:
            x = int(self._window_arg(args[0], 0))
            y = int(self._window_arg(args[1], 0))
        except (TypeError, ValueError):
            return 0
        raw = args[2] if len(args) > 2 else ""
        target = self._resolve_window(self._window_arg(raw, ""))
        if target is None:
            return 0
        gui = target.get("gui")
        if gui is not None:
            widget = getattr(gui, "widget", None)
            if widget is not None:
                widget.move(x, y)
            return 1
        from . import window_ops
        return 1 if window_ops.move(int(target["hwnd"]), x, y) else 0

    def _win_set_transparent(self, args):
        if not args:
            return 0
        try:
            alpha = int(float(self._window_arg(args[0], 255)))
        except (TypeError, ValueError):
            alpha = 255
        raw = args[1] if len(args) > 1 else ""
        target = self._resolve_window(self._window_arg(raw, ""))
        if target is None:
            return 0
        gui = target.get("gui")
        if gui is not None:
            widget = getattr(gui, "widget", None)
            if widget is not None:
                widget.setWindowOpacity(max(0.0, min(1.0, alpha / 255.0)))
            return 1
        from . import window_ops
        return 1 if window_ops.set_opacity(int(target["hwnd"]), alpha) else 0

    def _win_get_pid(self, args):
        raw = args[0] if args else ""
        target = self._resolve_window(self._window_arg(raw, ""))
        if target is None:
            return 0
        if target.get("gui") is not None:
            import os as _os
            return _os.getpid()
        from . import window_ops
        return window_ops.pid(int(target["hwnd"]))

    def _win_get_process_name(self, args):
        raw = args[0] if args else ""
        target = self._resolve_window(self._window_arg(raw, ""))
        if target is None:
            return ""
        if target.get("gui") is not None:
            import os as _os
            return _os.path.basename(_os.path.abspath(_os.sys.argv[0]))
        from . import window_ops
        return window_ops.process_name(int(target["hwnd"]))

    def _control_get_pos(self, args):
        control_raw = args[4] if len(args) > 4 else ""
        win_raw = args[5] if len(args) > 5 else ""
        found = self._find_control(
            self._window_arg(control_raw, ""), win_raw)
        if found is None:
            raise TargetError("ControlGetPos: target control not found")
        gui, control = found
        rect = self._control_rect(gui, control, screen=False)
        for index, value in enumerate(rect):
            if index < len(args):
                self._assign_output(args[index], value)
        return 1

    def _control_get_text(self, args):
        control_raw = args[0] if args else ""
        win_raw = args[1] if len(args) > 1 else ""
        found = self._find_control(
            self._window_arg(control_raw, ""), win_raw)
        if found is None:
            raise TargetError("ControlGetText: target control not found")
        return found[1].get_text()

    def _control_get_hwnd(self, args):
        control_raw = args[0] if args else ""
        win_raw = args[1] if len(args) > 1 else ""
        found = self._find_control(
            self._window_arg(control_raw, ""), win_raw)
        if found is None:
            raise TargetError("ControlGetHwnd: target control not found")
        return found[1].hwnd

    def _win_activate_value(self, value):
        target = self._resolve_window(value)
        gui = target.get("gui") if target else None
        if gui is not None:
            widget = getattr(gui, "widget", None)
            if widget is not None:
                gui._show("")
                widget.raise_()
                widget.activateWindow()
            self._active_gui = gui
            return 1
        if target is not None:
            from . import window_ops
            hwnd = int(target.get("hwnd", 0))
            if window_ops.activate(hwnd):
                self.logs.append(
                    f"WinActivate {str(value)!r} -> X window {hwnd}")
                return 1
        self._win_activate(str(value or ""))
        return 1

    def _legacy_window(self, low: str, rest: str,
                       omitted_first: bool = False) -> bool:
        parts = [p.strip() for p in P._split_seq(rest)]
        if low == "controlgetpos" and omitted_first:
            parts = [""] + parts
        elif parts and parts[0] == "":
            parts = parts[1:]
        if low == "wingetpos":
            self._win_get_pos(parts, client=False)
            return True
        if low == "wingetclientpos":
            self._win_get_pos(parts, client=True)
            return True
        if low == "wingettitle":
            if len(parts) >= 2:
                self._assign_output(parts[0], self._win_get_title([parts[1]]))
            else:
                self._log_once("WinGetTitle: missing output/window (logged)")
            return True
        if low in ("winclose", "winkill"):
            self._win_close([parts[0] if parts else ""],
                            kill=(low == "winkill"))
            return True
        if low == "winmove":
            self._win_move(parts[:3])
            return True
        if low == "winsettransparent":
            self._win_set_transparent(parts[:2])
            return True
        if low == "controlgetpos":
            self._control_get_pos(parts[:6])
            return True
        if low == "controlgettext":
            if len(parts) >= 2:
                self._assign_output(
                    parts[0], self._control_get_text([parts[1],
                                                      parts[2] if len(parts) > 2 else ""]))
            return True
        if low in ("winwait", "winwaitclose", "winwaitactive",
                   "winwaitnotactive"):
            self._win_wait(low, parts)
            return True
        if low == "winactive":
            self._win_active(parts)
            return True
        return False

    # -- bounded memory / DllCall (v0.7) ----------------------------------
    def _memory_builtin(self, low: str, args: list):
        from . import memory
        ev = lambda i: self._eval_expr(args[i]) if i < len(args) else ""

        if low == "buffer":
            size = ev(0) if args else 0
            fill = ev(1) if len(args) > 1 else 0
            return memory.AhkBuffer(size, fill)

        if low == "numget":
            if not args:
                return 0
            source = ev(0)
            offset, type_name = 0, "UPtr"
            if len(args) == 2:
                second = str(ev(1)).strip()
                if re.fullmatch(
                        r"(?i)(u?char|u?short|u?int(?:8|16|32|64)?|"
                        r"u?ptr|float|double)", second):
                    type_name = second
                else:
                    offset = ev(1)
            elif len(args) >= 3:
                offset, type_name = ev(1), str(ev(2))
            return memory.read(source, offset, type_name)

        if low == "numput":
            if len(args) < 3:
                return 0
            # NumPut(Type, Value, [Type, Value...], Target [, Offset]).
            target_index, offset = None, 0

            def is_target(value):
                if isinstance(value, memory.AhkBuffer):
                    return True
                if isinstance(value, int) and memory.resolve(value)[0] is not None:
                    return True
                return False

            try:
                last = ev(len(args) - 1)
            except Exception:
                last = None
            if is_target(last):
                target_index = len(args) - 1
            elif len(args) >= 4:
                try:
                    prev = ev(len(args) - 2)
                    if is_target(prev):
                        target_index = len(args) - 2
                        offset = ev(len(args) - 1)
                except Exception:
                    target_index = None
            if target_index is None:
                self._log_once("NumPut: target is not a Buffer/known pointer (logged)")
                return 0
            target = ev(target_index)
            written = 0
            for k in range(0, target_index - 1, 2):
                type_name = str(ev(k))
                value = ev(k + 1)
                written += memory.write(target, offset + written, type_name, value)
            return written

        if low == "strget":
            if not args:
                return ""
            source = ev(0)
            length = ev(1) if len(args) > 1 and str(args[1]).strip() else None
            encoding = ev(2) if len(args) > 2 else "UTF-16"
            return memory.read_string(source, length, encoding)

        if low == "strput":
            if not args:
                return 0
            text = ev(0)
            if len(args) == 1:
                raw = memory.allocate_string(text)
                return max(0, raw.size - 2)
            # StrPut(String, Encoding) -> required byte count.
            second = str(ev(1))
            if re.fullmatch(r"(?i)(utf-?8|utf-?16|unicode|cp0|ansi|latin-?1)",
                            second) and len(args) == 2:
                raw = memory.allocate_string(text, second)
                return max(0, raw.size - 2)
            target = ev(1)
            length = ev(2) if len(args) > 2 else None
            encoding = ev(3) if len(args) > 3 else "UTF-16"
            return memory.write_string(target, text, encoding, length)

        if low == "strptr":
            text = ev(0) if args else ""
            return memory.allocate_string(text).ptr

        if low in ("varptr", "objptr"):
            name = str(args[0]).strip().lstrip("&") if args else ""
            buf = getattr(self, "_var_buffers", None)
            if buf is None:
                self._var_buffers = {}
                buf = self._var_buffers
            if name not in buf:
                buf[name] = memory.AhkBuffer(8, 0)
            return buf[name].ptr

        return 0

    def _dll_call(self, args: list):
        """Whitelisted, bounded DllCall.

        The Windows ABI is not reproduced.  Timing, sleep, process identity,
        system metrics and a few structure writes used by Natro are real
        Linux equivalents; GDI/COM calls are explicit display-only stubs that
        log once and return AHK-falsy.
        """
        from . import memory
        if not args:
            return 0
        first_raw = str(args[0]).strip()
        try:
            first = self._eval_expr(args[0])
        except Exception:
            first = ""
        # A valid DllCall target is a library/function name string or a
        # numeric function address.  A Buffer/object here is a source
        # expression leaked outside its function body (or a genuine
        # function-pointer call, which this ABI does not model).
        if isinstance(first, memory.AhkBuffer) or not isinstance(
                first, (str, int, float)):
            source = first_raw.replace("\n", " ")[:96]
            self._log_once(
                f"DllCall expression {source}: evaluated to a non-callable "
                "value (returns 0; logged)")
            return 0
        if isinstance(first, (int, float)) and int(first) != 0:
            self._log_once(
                f"DllCall function pointer 0x{int(first):x}: Windows ABI "
                "not modeled on Linux (returns 0; logged)")
            return 0
        full_name = str(first).strip()
        if not (first_raw[:1] in ('"', "'")):
            # Undefined member access remains a literal string such as
            # `PixelateBitmap.Ptr`; that is not a DLL export name.
            if any(ch in full_name for ch in "().") and first_raw not in self.vars:
                source = first_raw.replace("\n", " ")[:96]
                self._log_once(
                    f"DllCall expression {source}: unresolved source "
                    "expression (returns 0; logged)")
                return 0
        name = full_name.split("\\")[-1].lower()
        if not name:
            self._log_once("DllCall: empty function name (returns 0)")
            return 0

        pairs = []
        index = 1
        while index + 1 < len(args):
            try:
                type_name = str(self._eval_expr(args[index])).strip()
            except Exception:
                type_name = ""
            raw = str(args[index + 1]).strip()
            target = None
            m = re.match(r"^&\s*([A-Za-z_]\w*)\s*(?::=\s*(.*))?$",
                         raw, re.DOTALL)
            if m:
                target = m.group(1)
                if target not in self.vars:
                    try:
                        self.vars[target] = self._eval_expr(m.group(2)) if m.group(2) else 0
                    except Exception:
                        self.vars[target] = 0
                value = self.vars.get(target, 0)
            else:
                try:
                    value = self._eval_expr(raw)
                except Exception:
                    value = 0
            pairs.append({"type": type_name, "raw": raw,
                          "target": target, "value": value})
            index += 2

        def value_at(i, default=0):
            return pairs[i]["value"] if i < len(pairs) else default

        def assign(i, value):
            if i >= len(pairs):
                return
            pair = pairs[i]
            if pair["target"]:
                self.vars[pair["target"]] = value
            elif memory.resolve(pair["value"])[0] is not None:
                memory.write(pair["value"], 0, pair["type"], value)

        if name in {
            "cryptacquirecontextw", "cryptacquirecontexta",
            "cryptcreatehash", "crypthashdata", "cryptgethashparam",
            "cryptdestroyhash", "cryptreleasecontext",
        }:
            return self._crypto_dll(name, pairs, value_at, assign, full_name)
        if name == "sleep":
            self.sim.sleep_ms(int(value_at(0, 0) or 0))
            return 0
        if name in ("getcurrentprocessid", "getcurrentthreadid"):
            return os.getpid() if name == "getcurrentprocessid" else 0
        if name == "getsystemtimeasfiletime":
            # FILETIME: 100 ns intervals since 1601-01-01.
            ticks = (time.time_ns() // 100) + 116444736000000000
            assign(0, ticks)
            return ticks
        if name == "queryperformancecounter":
            ticks = time.monotonic_ns()
            assign(0, ticks)
            return ticks
        if name == "queryperformancefrequency":
            return 1_000_000_000
        if name in ("gettickcount", "gettickcount64"):
            return int(time.monotonic() * 1000)
        if name == "getcommandline":
            return " ".join(sys.argv)
        if name == "getsystemmetrics":
            metric = int(value_at(0, 0) or 0)
            if metric == 0:
                return int(self.vars.get("A_ScreenWidth") or 1920)
            if metric == 1:
                return int(self.vars.get("A_ScreenHeight") or 1080)
            return 0
        if name == "globalmemorystatusex":
            try:
                pages = os.sysconf("SC_PHYS_PAGES")
                page_size = os.sysconf("SC_PAGE_SIZE")
                total = int(pages * page_size)
            except (ValueError, OSError):
                total = 0
            buf = value_at(0)
            memory.write(buf, 0, "UInt", 64)
            memory.write(buf, 8, "UInt64", total)
            return 1
        if name == "getwindowplacement":
            hwnd = int(value_at(0, 0) or 0)
            target = self._own_handle(hwnd)
            rect = self._window_rect(target, client=False) if target else (0, 0, 0, 0)
            buf = value_at(1)
            if memory.resolve(buf)[0] is not None:
                memory.write(buf, 0, "UInt", 44)
                memory.write(buf, 28, "Int", rect[0])
                memory.write(buf, 32, "Int", rect[1])
                memory.write(buf, 36, "Int", rect[0] + rect[2])
                memory.write(buf, 40, "Int", rect[1] + rect[3])
                return 1
            return 0
        if name == "getlocaleinfoex":
            buf = value_at(2)
            text = "M/d/yyyy"
            memory.write_string(buf, text, "UTF-16")
            return len(text) + 1
        if name == "getdateformatex":
            buf = value_at(4)
            text = time.strftime("%m/%d/%Y")
            memory.write_string(buf, text, "UTF-16")
            return len(text) + 1
        if name == "getnumberformatex":
            buf = value_at(5)
            text = str(value_at(2, ""))
            memory.write_string(buf, text, "UTF-16")
            return len(text) + 1
        if name == "getdurationformatex":
            buf = value_at(0)
            memory.write_string(buf, "00:00:00", "UTF-16")
            return 9
        if name == "gettextextentpoint32":
            buf = value_at(3)
            text = str(value_at(1, ""))
            memory.write(buf, 0, "Int", max(1, len(text) * 8))
            memory.write(buf, 4, "Int", 16)
            return 1
        # GDI/COM/user32 calls used only by display-only paths.  These are
        # deliberately no-ops, not fake handles: Natro's vision layer replaces
        # Gdip image processing, and the overlay windows are not recreated.
        if name in {
            "deleteobject", "selectobject", "deletedc", "deleteenhmf",
            "createcompatibledc", "getdc", "releasedc", "bitblt",
            "createdibsection", "setcursor", "loadcursor", "copyshortcut",
            "systemparametersinfo", "virtualprotect", "rtlmovememory",
            "setlasterror", "getlasterror", "createthread", "closehandle",
            "localalloc", "globalalloc", "globallock", "globalunlock",
            "globalfree", "globalsize",
        }:
            self._log_once(f"DllCall {full_name}: display-only/no-op on Linux (logged)")
            return 1 if name not in ("getdc", "createdibsection") else 0
        self._log_once(
            f"DllCall {full_name}: Windows ABI not modeled on Linux "
            "(returns 0; logged)")
        return 0

    @staticmethod
    def _ptr_value(value):
        if isinstance(value, dict):
            for key in ("ptr", "Ptr", "handle"):
                if key in value:
                    try:
                        return int(value[key])
                    except (TypeError, ValueError):
                        return 0
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _store_ptr(value, handle) -> bool:
        if isinstance(value, dict):
            value["ptr"] = handle
            return True
        return False

    def _crypto_dll(self, name: str, pairs: list, value_at, assign,
                    full_name: str):
        """Real hashing for the Advapi32 surface used by HashFile.

        This is a Linux implementation of the *effect* (MD5/SHA hashes of a
        file), not a Windows ABI emulation.  Handles are opaque synthetic
        values and every buffer is a bounded AhkBuffer.
        """
        if not hasattr(self, "_crypto_hashes"):
            self._crypto_hashes: dict[int, object] = {}
            self._crypto_providers: dict[int, bool] = {}
            self._crypto_next = 0x50000000
            self._log_once(
                "DllCall Advapi32 CryptoAPI: bridged to Python hashlib "
                "(Linux implementation, synthetic handles)")

        def new_handle():
            self._crypto_next += 1
            return self._crypto_next

        if name in ("cryptacquirecontextw", "cryptacquirecontexta"):
            handle = new_handle()
            self._crypto_providers[handle] = True
            hprov = value_at(0)
            if self._store_ptr(hprov, handle):
                return 1
            assign(0, handle)
            return 1
        if name == "cryptcreatehash":
            prov = self._ptr_value(value_at(0))
            if prov not in self._crypto_providers:
                self._log_once("CryptCreateHash: stale provider (returns 0)")
                return 0
            alg = int(value_at(1, 0) or 0)
            if alg == 32769:
                # Python/OpenSSL does not provide MD2.  Keep the legacy slot
                # usable but make the approximation visible.
                self._log_once(
                    "CryptCreateHash: MD2 unavailable; using MD5 fallback "
                    "(logged approximation)")
            alg_name = {
                32769: "md5",
                32771: "md5", 32772: "sha1", 32780: "sha256",
                32781: "sha384", 32782: "sha512",
            }.get(alg)
            if not alg_name:
                self._log_once(
                    f"CryptCreateHash: hash algorithm {alg} not modeled "
                    "(returns 0)")
                return 0
            handle = new_handle()
            self._crypto_hashes[handle] = hashlib.new(alg_name)
            if self._store_ptr(value_at(4), handle):
                return 1
            assign(4, handle)
            return 1
        if name == "crypthashdata":
            h = self._ptr_value(value_at(0))
            digest = self._crypto_hashes.get(h)
            if digest is None:
                self._log_once("CryptHashData: stale hash handle (returns 0)")
                return 0
            from . import memory
            buf, base = memory.resolve(value_at(1))
            try:
                size = max(0, int(value_at(2, 0) or 0))
            except (TypeError, ValueError):
                size = 0
            if buf is None:
                # No real memory was supplied: hash nothing rather than
                # pretending bytes were processed.
                self._log_once("CryptHashData: no Buffer data (returns 0)")
                return 0
            data = bytes(buf.data[base:base + size])
            digest.update(data)
            return 1
        if name == "cryptgethashparam":
            h = self._ptr_value(value_at(0))
            digest = self._crypto_hashes.get(h)
            if digest is None:
                self._log_once(
                    "CryptGetHashParam: stale hash handle (returns 0)")
                return 0
            param = int(value_at(1, 0) or 0)
            if param == 4:  # HP_HASHSIZE
                assign(2, digest.digest_size)
                assign(3, 4)
                return 1
            if param == 2:  # HP_HASHVAL
                from . import memory
                raw = digest.digest()
                out, base = memory.resolve(value_at(2))
                if out is None:
                    self._log_once(
                        "CryptGetHashParam: no Buffer output (returns 0)")
                    return 0
                end = min(out.size, base + len(raw))
                out.data[base:end] = raw[:max(0, end - base)]
                assign(3, len(raw))
                return 1
            self._log_once(
                f"CryptGetHashParam: parameter {param} not modeled "
                "(returns 0)")
            return 0
        if name == "cryptdestroyhash":
            self._crypto_hashes.pop(self._ptr_value(value_at(0)), None)
            return 1
        if name == "cryptreleasecontext":
            self._crypto_providers.pop(self._ptr_value(value_at(0)), None)
            return 1
        self._log_once(f"DllCall {full_name}: crypto bridge unhandled "
                       "(returns 0)")
        return 0

    def _pure_builtin(self, low: str, args: list):
        """Side-effect-free builtins usable inside expressions. Unknown GUI/OS
        builtins become logged stubs returning falsy (documented gap)."""
        ev = lambda a: self._eval_expr(a)
        try:
            if low == "getkeystate" and args:
                key = str(ev(args[0])).strip().lower()
                if key in ("pause", "p"):
                    return 1 if self._paused else 0
                if key == "suspend":
                    return 1 if self._suspended else 0
                return 0
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
            if low == "format" and args:
                return self._format_builtin([ev(a) for a in args])
            if low == "regexmatch" and len(args) >= 2:
                return self._regex_match(args, ev)
            if low == "regexreplace" and len(args) >= 2:
                return self._regex_replace([ev(a) for a in args])
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
                    # AHK v2: omitted/blank delimiters split into characters.
                    # Natro relies on this for priorityListNumeric digits.
                    return list(s)
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
            if low in ("error", "typeerror", "valueerror", "oserror"):
                # Error objects: carry the message so `throw Error("msg")`
                # surfaces it; property access beyond .Message is a gap.
                return (str(ev(args[0])) if args
                        else {"error": "Error", "typeerror": "TypeError",
                              "valueerror": "ValueError",
                              "oserror": "OSError"}[low])
            if low == "buffer":
                return ""
            if low == "iniread" and len(args) >= 3:
                default = ev(args[3]) if len(args) > 3 else ""
                return self._read_ini_value(
                    self._abs_path(ev(args[0])), str(ev(args[1])),
                    str(ev(args[2])), default)
            if low == "fileexist" and args:
                import glob as _glob
                path = self._abs_path(ev(args[0]))
                if any(ch in path for ch in "*?["):
                    hits = sorted(_glob.glob(path))
                    if not hits:
                        return ""
                    path = hits[0]
                if os.path.isfile(path):
                    return "A"
                if os.path.isdir(path):
                    return "D"
                return ""
            if low == "fileread" and args:
                try:
                    with open(self._abs_path(ev(args[0])),
                              encoding="utf-8-sig") as fh:
                        return fh.read()
                except (OSError, UnicodeError) as exc:
                    self._log_once(f"FileRead failed: {exc}")
                    return ""
            if low == "fileappend" and len(args) >= 2:
                try:
                    with open(self._abs_path(ev(args[1])), "a",
                              encoding="utf-8") as fh:
                        fh.write(self._to_ahk_string(ev(args[0])))
                    return 1
                except OSError as exc:
                    self._log_once(f"FileAppend failed: {exc}")
                    return 0
            if low == "filedelete" and args:
                import glob as _glob
                path = self._abs_path(ev(args[0]))
                hits = _glob.glob(path) if any(c in path for c in "*?[") else [path]
                removed = 0
                for hit in hits:
                    try:
                        if os.path.isfile(hit):
                            os.remove(hit)
                            removed += 1
                    except OSError as exc:
                        self._log_once(f"FileDelete failed: {exc}")
                return removed
            if low in ("filecopy", "filemove") and len(args) >= 2:
                import shutil as _shutil
                src = self._abs_path(ev(args[0]))
                dst = self._abs_path(ev(args[1]))
                overwrite = bool(int(ev(args[2]))) if len(args) > 2 else False
                try:
                    if os.path.exists(dst) and not overwrite:
                        return 0
                    (_shutil.copy2 if low == "filecopy" else _shutil.move)(src, dst)
                    return 1
                except (OSError, PermissionError) as exc:
                    self._log_once(f"{low} failed: {exc}")
                    return 0
            if low == "dircreate" and args:
                try:
                    os.makedirs(self._abs_path(ev(args[0])), exist_ok=True)
                    return 1
                except OSError as exc:
                    self._log_once(f"DirCreate failed: {exc}")
                    return 0
            if low == "dirdelete" and args:
                import shutil as _shutil
                recurse = bool(int(ev(args[1]))) if len(args) > 1 else False
                path = self._abs_path(ev(args[0]))
                try:
                    (_shutil.rmtree if recurse else os.rmdir)(path)
                    return 1
                except OSError as exc:
                    self._log_once(f"DirDelete failed: {exc}")
                    return 0
            if low == "filegetsize" and args:
                try:
                    size = os.path.getsize(self._abs_path(ev(args[0])))
                except OSError:
                    return 0
                unit = str(ev(args[1])).upper() if len(args) > 1 else "B"
                if unit == "K":
                    size = (size + 1023) // 1024
                elif unit == "M":
                    size = (size + 1024 * 1024 - 1) // (1024 * 1024)
                return size
            if low == "filegettime" and args:
                try:
                    stamp = os.path.getmtime(self._abs_path(ev(args[0])))
                except OSError:
                    return ""
                which = str(ev(args[1])).upper() if len(args) > 1 else "M"
                key = {"C": "st_ctime", "A": "st_atime"}.get(which, "st_mtime")
                dt = _dt.datetime.fromtimestamp(
                    getattr(os.stat(self._abs_path(ev(args[0]))), key))
                return dt.strftime("%Y%m%d%H%M%S")
            if low == "envget" and args:
                return os.environ.get(str(ev(args[0])), "")
            if low == "envset" and len(args) >= 2:
                name = str(ev(args[0]))
                if name:
                    os.environ[name] = self._to_ahk_string(ev(args[1]))
                return 1
            if low == "type" and args:
                v = ev(args[0])
                if isinstance(v, bool):
                    return "Integer"
                if isinstance(v, int):
                    return "Integer"
                if isinstance(v, float):
                    return "Float"
                if isinstance(v, str):
                    return "String"
                if isinstance(v, list):
                    return "Array"
                if isinstance(v, dict):
                    return "Map"
                if isinstance(v, TrayMenu):
                    return "Object"
                return "Object"
            if low in ("integer", "float") and args:
                v = self._to_ahk_number(ev(args[0]))
                return int(float(v)) if low == "integer" else float(v)
            if low == "ord" and args:
                s = str(ev(args[0]))
                return ord(s[0]) if s else 0
            if low == "chr" and args:
                try:
                    return chr(int(ev(args[0])))
                except (TypeError, ValueError, OverflowError):
                    return ""
            if low == "objhasownprop" and len(args) >= 2:
                obj, key = ev(args[0]), str(ev(args[1]))
                return 1 if isinstance(obj, dict) and key in obj else 0
            if low == "objget" and len(args) >= 2:
                obj, key = ev(args[0]), str(ev(args[1]))
                if isinstance(obj, dict):
                    return obj.get(key, ev(args[2]) if len(args) > 2 else "")
                return ""
            if low == "objset" and len(args) >= 3:
                obj, key = ev(args[0]), str(ev(args[1]))
                if isinstance(obj, dict):
                    obj[key] = ev(args[2])
                return 1
            if low == "varsetstrcapacity" and args:
                return 1
            if low == "splitpath" and args:
                return self._split_path_builtin(args)
            if low == "string" and args:
                return self._to_ahk_string(ev(args[0]))
            if low == "number" and args:
                return self._to_ahk_number(ev(args[0]))
            if low in ("dateadd", "datediff") and len(args) >= 3:
                return self._date_builtin(low, ev(args[0]), ev(args[1]), ev(args[2]))
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

    @staticmethod
    def _ahk_regex(pat: str):
        """AHK pattern -> (body, flags): leading `i)`/`m)`/`s)` option
        block (same convention as `~=`), backslash-R newline class (Python
        has no equivalent). Scoped `(?i:...)` groups pass through natively."""
        import re as _re
        flags = 0
        mo = _re.match(r"^([a-zA-Z]+)\)(.*)$", pat, _re.DOTALL)
        if mo:
            opts = mo.group(1).lower()
            if "i" in opts:
                flags |= _re.IGNORECASE
            if "m" in opts:
                flags |= _re.MULTILINE
            if "s" in opts:
                flags |= _re.DOTALL
            pat = mo.group(2)
        return pat.replace("\\R", r"(?:\r\n|\r|\n)"), flags

    @staticmethod
    def _format_one(spec: str, val):
        """One `{n:spec}` substitution. Leading/trailing U/T/L is an AHK
        case flag (`{1:Us}`, `{1:U}`); the rest maps onto Python's format
        mini-language (`02x`, `#x`, `03X`, `s`, `d`, `.2f` ...). Unknown
        specs fall back to the plain string (never throws)."""
        case = None
        if len(spec) > 1 and spec[0] in ("U", "T", "L"):
            case, spec = spec[0], spec[1:]
        elif spec and spec[-1] in ("U", "T", "L"):
            case, spec = spec[-1], spec[:-1]
        if spec == "c":
            try:
                out = chr(int(val))
            except (TypeError, ValueError):
                out = str(val)
        elif not spec:
            out = str(val)
        else:
            try:
                out = ("{0:" + spec + "}").format(val)
            except (TypeError, ValueError):
                try:
                    out = ("{0:" + spec + "}").format(
                        int(val) if isinstance(val, bool) or
                        (isinstance(val, str) and re.fullmatch(r"[+-]?\d+", val.strip()))
                        else float(val))
                except (TypeError, ValueError):
                    out = str(val)
        if case == "U":
            return out.upper()
        if case == "L":
            return out.lower()
        if case == "T":
            return out.title()
        return out

    def _format_builtin(self, vals: list):
        """`Format(fmt, v1, ...)` with `{n:spec}` / `{}` placeholders
        (1-based explicit, sequential empty). Out-of-range indexes stay
        literal (AHK would throw; the bridge keeps running)."""
        if not vals:
            return ""
        fmt, auto = str(vals[0]), [0]

        def _sub(m):
            idx, spec = m.group(1), m.group(2) or ""
            if idx == "":
                auto[0] += 1
                k = auto[0]
            else:
                k = int(idx)
            if 1 <= k < len(vals):
                return self._format_one(spec, vals[k])
            return m.group(0)

        try:
            return re.sub(r"\{(\d*)(?::([^}]*))?\}", _sub, fmt)
        except Exception:
            return fmt

    def _regex_match(self, args: list, ev):
        """`RegExMatch(hay, pat [, &out, start])` -> 1-based pos or 0.
        `&out` receives the full match STRING (AHK fills a match object;
        documented approximation)."""
        import re as _re
        hay = str(ev(args[0]))
        body, flags = self._ahk_regex(str(ev(args[1])))
        try:
            start = int(ev(args[3])) if len(args) > 3 else 1
        except (TypeError, ValueError):
            start = 1
        start = max(1, start)
        try:
            m = _re.search(body, hay[start - 1:], flags)
        except _re.error:
            m = None
        if len(args) > 2:
            _on = str(args[2]).strip()
            if _on.startswith("&") and re.fullmatch(r"&[A-Za-z_]\w*", _on):
                self.vars[_on[1:]] = m.group(0) if m else ""
        return (start - 1) + m.start() + 1 if m else 0

    def _regex_replace(self, vals: list):
        """`RegExReplace(hay, pat, repl [, count])`: `$1` backrefs become
        Python `\\1`, `$0` the whole match; count 0/omitted = replace all."""
        import re as _re
        hay = str(vals[0])
        body, flags = self._ahk_regex(str(vals[1]))
        repl = str(vals[2]) if len(vals) > 2 else ""
        repl = _re.sub(r"\$(\d+)",
                       lambda m: r"\g<0>" if m.group(1) == "0" else "\\" + m.group(1),
                       repl)
        try:
            count = int(vals[3]) if len(vals) > 3 else 0
        except (TypeError, ValueError):
            count = 0
        try:
            return _re.sub(body, repl, hay, count=count, flags=flags)
        except _re.error:
            return hay

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
        if self._var_key(body) is not None:
            return "v"
        if re.match(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$", body):
            base = body.split(".", 1)[0]
            if self._var_key(base) is not None:
                return "v"
        if re.match(r"^[A-Za-z_]\w*\s*\(.*\)$", body, re.DOTALL):
            return "v"
        m = re.match(r"^([A-Za-z_]\w*)(?:\.[A-Za-z_]\w*)+\s*\(.*\)$",
                     body, re.DOTALL)
        if m and self._var_key(m.group(1)) is not None:
            return "v"
        m = re.match(r"^([A-Za-z_]\w*)(?:\[.+?\])+$", body, re.DOTALL)
        if m and self._var_key(m.group(1)) is not None:
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
    def _resolve_call_name(self, head: str) -> str:
        """Evaluate an expression callee to a plain function name.
        `(%"nm_" i%)` strips the outer `%...%` and concatenates the
        juxtaposed `"str"` / var parts (`nm_` + i). Returns "" unless the
        result is a valid bare name."""
        h = str(head).strip()
        if len(h) >= 2 and h.startswith("%") and h.endswith("%"):
            h = h[1:-1]
        for _ in range(10):  # embedded %var% segments first
            dm = re.search(r"%([A-Za-z_]\w*)%", h)
            if not dm:
                break
            h = h[:dm.start()] + str(self._get_var(dm.group(1))) + h[dm.end():]
        parts = self._split_juxta(h)
        if not parts:
            return ""
        out = []
        for quoted, body in parts:
            body = body.strip()
            if quoted:
                out.append(self._interp(body))
            elif body in self.vars:
                out.append(str(self.vars[body]))
            elif re.fullmatch(r"[A-Za-z_]\w*|\d+", body):
                out.append(body)
            else:
                return ""
        name = "".join(out)
        return name if re.fullmatch(r"[A-Za-z_]\w*", name) else ""

    @staticmethod
    def _is_atomic_expr(s: str) -> bool:
        """True when `s` has no top-level whitespace (one concat atom)."""
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
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            elif depth == 0 and ch.isspace():
                return False
            k += 1
        return True

    @staticmethod
    def _has_top_operator(s: str) -> bool:
        """True when an expression has a top-level arithmetic/ternary op."""
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
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            elif depth == 0 and ch in "+-*/?":
                return True
            k += 1
        return False

    @staticmethod
    def _split_index_expr(s: str):
        """Split a final top-level `base[index]` read, or return None."""
        st = s.strip()
        if not st.endswith("]"):
            return None
        depth, q, k, start = 0, None, 0, -1
        while k < len(st):
            ch = st[k]
            if ch == "`" and k + 1 < len(st):
                k += 2
                continue
            if q:
                if ch == q:
                    q = None
            elif ch in ('"', "'"):
                q = ch
            elif ch == "[":
                if depth == 0:
                    start = k
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth < 0:
                    return None
            k += 1
        if depth != 0 or start <= 0:
            return None
        if P._scan_balanced(st, start, "[", "]") != len(st):
            return None
        base, inner = st[:start].strip(), st[start + 1:-1]
        if not base or not Runtime._is_atomic_expr(base):
            return None
        if Runtime._has_top_operator(base):
            return None
        return base, inner

    @staticmethod
    def _split_last_access(lhs: str):
        """Return `(base, (kind, key))` for the final property/index access."""
        st = lhs.strip()
        idx = Runtime._split_index_expr(st)
        if idx is not None:
            return idx[0], ("idx", idx[1])
        depth, q, k, last = 0, None, 0, -1
        while k < len(st):
            ch = st[k]
            if ch == "`" and k + 1 < len(st):
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
                depth = max(0, depth - 1)
            elif ch == "." and depth == 0 and k > 0:
                last = k
            k += 1
        if last > 0:
            prop = st[last + 1:].strip()
            base = st[:last].strip()
            if base and re.fullmatch(r"[A-Za-z_]\w*", prop):
                return base, ("key", prop)
        return None

    def _set_expr_target(self, lhs: str, value):
        """Store into an arbitrary assignment LHS (property/index/dynamic)."""
        lhs = lhs.strip()
        dynamic = re.fullmatch(r"%(.+)%", lhs)
        if dynamic:
            name = self._eval_expr(dynamic.group(1).strip())
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z_]\w*", name.strip()):
                self.vars[name.strip()] = value
            else:
                self.logs.append(f"assign-target {lhs!r} resolved to {name!r} (logged)")
            return
        if re.fullmatch(r"[A-Za-z_]\w*", lhs):
            self.vars[lhs] = value
            return
        access = self._split_last_access(lhs)
        if access is None:
            self.logs.append(f"assign-target {lhs!r} unsupported (logged)")
            return
        base_expr, (kind, key_raw) = access
        try:
            obj = self._eval_expr(base_expr)
            key = self._eval_expr(key_raw) if kind == "idx" else key_raw
            self._store(obj, kind, key, value)
        except (TypeError, ValueError, IndexError, KeyError) as exc:
            self.logs.append(f"assign-target {lhs!r} failed: {exc}")

    @staticmethod
    def _split_method_chain(s: str):
        """Split `base.A(args).B(args)` into `(base, [(A,args), ...])`.

        The previous regex took the first method and swallowed the rest of
        the chain into its argument string, so `Gui.Add(...).OnEvent(...)`
        lost the OnEvent callback. This scans top-level links and uses
        balanced argument groups.
        """
        st = s.strip()
        n = len(st)
        depth, q, k = 0, None, 0
        methods: list[tuple[str, str]] = []
        base_end = -1
        while k < n:
            ch = st[k]
            if ch == "`" and k + 1 < n:
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
            if ch in "([{":
                depth += 1
                k += 1
                continue
            if ch in ")]}":
                depth = max(0, depth - 1)
                k += 1
                continue
            if (depth == 0 and ch == "." and k + 1 < n
                    and (st[k + 1].isalpha() or st[k + 1] == "_")):
                j = k + 1
                while j < n and (st[j].isalnum() or st[j] == "_"):
                    j += 1
                m = re.match(r"\s*\(", st[j:])
                if not m:
                    k += 1
                    continue
                if not methods:
                    base = st[:k].strip()
                    if not base:
                        return None
                elif k != base_end:
                    return None
                paren = j + m.end() - 1
                after = P._scan_balanced(st, paren, "(", ")")
                if after < 0:
                    return None
                methods.append((st[k + 1:j], st[paren + 1:after - 1]))
                k = after
                base_end = k
                if k < n and st[k] != ".":
                    return None
                continue
            k += 1
        if not methods or base_end != n:
            return None
        return base, methods

    def _assign_target(self, target: str, value):
        """Indexed/property assignment: arr[i] := v, a[i][k] := v, obj.p := v."""
        val = self._eval_expr(value)
        # v1 dynamic names: PlanterTime%i% -> resolve before parsing target
        for _ in range(10):
            m = re.search(r"%([A-Za-z_]\w*)%", target)
            if not m:
                break
            target = target[:m.start()] + str(self._get_var(m.group(1))) + target[m.end():]
        if re.fullmatch(r"[A-Za-z_]\w*", target.strip()):
            self._set_var(target.strip(), val)
            return
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

    def _access(self, obj, key):
        if hasattr(obj, "ahk_get"):
            return obj.ahk_get(key)
        if isinstance(obj, (list, tuple)):
            return obj[int(key) - 1]
        if isinstance(obj, str):
            return obj[int(key) - 1]
        if isinstance(obj, dict):
            return obj[key] if key in obj else obj[str(key)]
        if isinstance(obj, TrayMenu):
            return getattr(obj, str(key).lower(), "")
        self._log_once(f"indexing {type(obj).__name__} not modeled (logged)")
        return ""

    @staticmethod
    def _store(obj, kind, key, val):
        if kind == "key" and hasattr(obj, "ahk_set_property"):
            obj.ahk_set_property(key, val)
            return
        if kind == "idx" and hasattr(obj, "ahk_set"):
            obj.ahk_set(key, val)
            return
        if isinstance(obj, list) and kind == "idx":
            i = int(key) - 1
            if 0 <= i < len(obj):
                obj[i] = val
                return
            raise IndexError("list assignment out of range")
        if isinstance(obj, dict):
            obj[key] = val
            return
        if isinstance(obj, TrayMenu) and kind == "key":
            setattr(obj, str(key).lower(), val)
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
        if low == "settimer":
            parts = [p.strip() for p in P._split_seq(rest)]
            name = parts[0] if parts else ""
            period = 250
            if len(parts) > 1:
                try:
                    period = self._eval_expr(parts[1])
                except Exception:
                    period = parts[1]
            self._set_timer(name, period)
            return
        if low == "hotkey":
            self._register_hotkey(P._split_seq(rest))
            return
        if low in ("postmessage", "sendmessage"):
            self._post_message(P._split_seq(rest),
                               synchronous=(low == "sendmessage"))
            return
        if low in ("run", "runwait"):
            parts = [p.strip() for p in P._split_seq(rest)]
            target = parts[0] if parts else ""
            self._execute_run(target, wait=(low == "runwait"))
            return
        if low == "processclose":
            parts = [p.strip() for p in P._split_seq(rest)]
            target = self._eval_expr(parts[0]) if parts else ""
            self._process_close(target)
            return
        if low == "suspend":
            self._set_suspend(rest)
            return
        if low == "pause":
            self._set_pause(rest)
            return
        if low in ("reload", "edit", "listvars", "keyhistory", "exit"):
            self.logs.append(f"{st.name} {rest} (noted, linux no-op)")
            return
        if low == "trayseticon":
            self.logs.append(
                f"TraySetIcon {rest} (no system tray on Linux, ignored)")
            return
        if low in ("wingetpos", "wingetclientpos", "wingettitle",
                   "winclose", "winkill", "winmove", "winsettransparent",
                   "winwait", "winwaitclose", "winwaitactive",
                   "winwaitnotactive", "winactive",
                   "controlgetpos", "controlgettext"):
            if self._legacy_window(low, rest,
                                   getattr(st, "omitted_first", False)):
                return
        if low == "splitpath":
            parts = [p.strip() for p in P._split_seq(rest)]
            path = self._eval_assignment_arg(parts[0]) if parts else ""
            values = self._split_path_parts(path)
            for index, part in enumerate(parts[1:6]):
                self._assign_output(part, values[index])
            return
        if low in ("fileappend", "fileread", "filedelete", "filecopy",
                   "filemove", "dircreate", "dirdelete"):
            parts = [p.strip() for p in P._split_seq(rest)]
            if low == "fileread" and len(parts) >= 2:
                self.vars[parts[0].lstrip("&").strip()] = self._pure_builtin(
                    "fileread", [parts[1]])
                return
            if low == "fileappend":
                if len(parts) >= 2:
                    self._pure_builtin("fileappend", [parts[0], parts[1]])
                elif parts:
                    self._pure_builtin("fileappend", ['"`n"', parts[0]])
                return
            if low in ("filecopy", "filemove") and len(parts) >= 2:
                self._pure_builtin(low, parts[:3])
                return
            if parts:
                self._pure_builtin(low, parts[:2])
                return
        self.logs.append(f"{st.name} {rest} (OS/window op, linux no-op)")

    @staticmethod
    def _split_path_parts(path):
        """AHK SplitPath -> (Name, Dir, Ext, NameNoExt, Drive).

        Accepts both `/` and `\\` separators regardless of host OS.  Dir keeps
        its trailing separator and includes the drive root.
        """
        p = str(path)
        drive, body = "", p
        m = re.match(r'^([A-Za-z]:)(.*)$', p)
        if m:
            drive, body = m.group(1), m.group(2)
        elif p.startswith("\\\\"):
            bits = p.split("\\")
            if len(bits) >= 4 and bits[2]:
                drive = "\\\\" + bits[2] + "\\" + bits[3]
                body = p[len(drive):]
        elif p.startswith("/"):
            drive, body = "/", p[1:]
        cut = max(body.rfind("/"), body.rfind("\\"))
        if cut >= 0:
            dir_out = body[:cut + 1]
            if drive and not dir_out.startswith(drive):
                dir_out = drive + dir_out
            name = body[cut + 1:]
        else:
            dir_out = drive if drive == "/" else ""
            name = body
        dot = name.rfind(".")
        if dot > 0:
            ext, name_no_ext = name[dot + 1:], name[:dot]
        else:
            ext, name_no_ext = "", name
        return name, dir_out, ext, name_no_ext, drive

    def _eval_assignment_arg(self, raw: str):
        """Evaluate an argument that may itself be `var := expr`."""
        text = str(raw).strip()
        m = re.match(r'^([A-Za-z_]\w*)\s*:=\s*(.+)$', text)
        if m:
            value = self._eval_expr(m.group(2))
            self.vars[m.group(1)] = value
            return value
        return self._eval_expr(text)

    def _assign_output(self, raw: str, value):
        """Assign a by-ref output (`&name`, `&name:=""`) or a legacy var."""
        text = str(raw).strip()
        if not text:
            return
        if text.startswith("&"):
            text = text[1:].strip()
        m = re.match(r'^([A-Za-z_]\w*)\s*:=\s*(.+)$', text)
        if m:
            target = m.group(1)
            if target not in self.vars:
                self.vars[target] = self._eval_expr(m.group(2))
        else:
            target = text
        if re.fullmatch(r'[A-Za-z_]\w*', target):
            self._set_var(target, value)

    def _split_path_builtin(self, args):
        path = self._eval_assignment_arg(args[0]) if args and args[0].strip() else ""
        values = self._split_path_parts(path)
        for index, part in enumerate(values, 1):
            if index < len(args):
                self._assign_output(args[index], part)
        return ""

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

    @staticmethod
    def _file_stamp(timestamp) -> str:
        """AHK file-loop time format: YYYYMMDDHH24MISS."""
        try:
            return time.strftime("%Y%m%d%H%M%S",
                                 time.localtime(float(timestamp)))
        except (TypeError, ValueError, OSError):
            return ""

    def _loop_files(self, st: P.LoopFiles):
        """Iterate files matching a glob (AHK `Loop Files`).

        Populates the v2 file-loop specials.  Linux has no 8.3 short names
        and no portable file-creation timestamp, so those stay blank
        instead of being fabricated; size and access/modify times are real
        ``stat`` values.
        """
        import glob as _glob
        import os as _os
        pat = str(self._eval_expr(st.pattern)).replace("\\", _os.sep)
        if not _os.path.isabs(pat):
            pat = _os.path.join(
                str(self.vars.get("A_WorkingDir") or _os.getcwd()), pat)
        try:
            files = sorted(_glob.glob(pat))
        except Exception as e:
            self.logs.append(f"Loop Files error: {e}")
            return
        loop_keys = (
            "A_Index", "A_LoopFileName", "A_LoopFilePath",
            "A_LoopFileFullPath", "A_LoopFileDir", "A_LoopFileExt",
            "A_LoopFileNameNoExt", "A_LoopFileShortPath",
            "A_LoopFileShortName", "A_LoopFileAttrib",
            "A_LoopFileTimeModified", "A_LoopFileTimeCreated",
            "A_LoopFileTimeAccessed", "A_LoopFileSize",
            "A_LoopFileSizeKB", "A_LoopFileSizeMB")
        saved = {k: self.vars.get(k) for k in loop_keys}
        try:
            for ai, fp in enumerate(files, 1):
                base = _os.path.basename(fp)
                name, ext = _os.path.splitext(base)
                try:
                    info = _os.stat(fp)
                except OSError:
                    info = None
                size = info.st_size if info is not None else 0
                created = getattr(info, "st_birthtime", None) \
                    if info is not None else None
                self.vars.update({
                    "A_Index": ai, "A_LoopFileName": base,
                    # v2 renamed v1's A_LoopFileFullPath to A_LoopFilePath;
                    # keep both because the corpus uses each spelling.
                    "A_LoopFilePath": fp,
                    "A_LoopFileFullPath": fp,
                    "A_LoopFileDir": _os.path.dirname(fp),
                    "A_LoopFileExt": ext.lstrip("."),
                    "A_LoopFileNameNoExt": name,
                    # No 8.3 short names on Linux; AHK also leaves these
                    # blank when the file has none.
                    "A_LoopFileShortPath": "",
                    "A_LoopFileShortName": "",
                    # Windows attribute letters have no Linux equivalent.
                    "A_LoopFileAttrib": "",
                    "A_LoopFileTimeModified":
                        self._file_stamp(info.st_mtime) if info else "",
                    "A_LoopFileTimeCreated":
                        self._file_stamp(created) if created else "",
                    "A_LoopFileTimeAccessed":
                        self._file_stamp(info.st_atime) if info else "",
                    "A_LoopFileSize": size,
                    "A_LoopFileSizeKB": size // 1024,
                    "A_LoopFileSizeMB": size // (1024 * 1024)})
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

    def _iter_values(self, expr: str, pairs: bool = False):
        """Resolve `for x in <expr>` to a list of values, or None to skip.

        Map iteration follows AHK: one variable receives each key, two
        variables receive (key, value) pairs.
        """
        val = self._eval_expr(expr)
        if isinstance(val, (list, tuple)):
            return list(val)
        if isinstance(val, dict):
            return list(val.items()) if pairs else list(val.keys())
        if isinstance(val, (int, float)):
            return list(range(1, int(val) + 1))
        return None

    def _for(self, st: P.For):
        targets = st.targets[:2]
        vals = self._iter_values(st.iterable, pairs=len(targets) == 2)
        if vals is None:
            self.logs.append(f"for: unsupported enumerable {st.iterable!r} (skipped)")
            return
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
        fname = self._abs_path(self._eval_expr(st.filename))
        section = str(self._eval_expr(st.section))
        key = str(self._eval_expr(st.key))
        cfg = configparser.ConfigParser(interpolation=None, strict=False,
                                        allow_no_value=True)
        cfg.optionxform = str  # keep key case
        try:
            if os.path.exists(fname):
                with open(fname, encoding="utf-8-sig") as fh:
                    cfg.read_file(fh)
            if st.op == "write":
                if not cfg.has_section(section):
                    cfg.add_section(section)
                cfg.set(section, key, str(self._eval_expr(st.value)))
                with open(fname, "w", encoding="utf-8") as f:
                    cfg.write(f)
                self.logs.append(f"IniWrite [{section}] {key} -> {fname}")
            else:
                v = self._read_ini_value(fname, section, key, "")
                target = str(st.value)
                if re.match(r"^[A-Za-z_]\w*$", target):
                    self.vars[target] = v
                self.logs.append(f"IniRead [{section}] {key} -> {v!r}")
        except OSError as e:
            self.logs.append(f"IniOp error: {e}")

    @staticmethod
    def _to_ahk_string(value) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, float):
            # AHK integer-valued doubles print without a trailing .0.
            return str(int(value)) if value.is_integer() else str(value)
        return str(value)

    @staticmethod
    def _to_ahk_number(value):
        """AHK Number(): numeric strings become int/float; non-numeric values
        throw (callers validate with IsNumber first)."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, bool):
            return int(value)
        s = str(value).strip()
        if re.fullmatch(r"[+-]?\d+", s):
            try:
                return int(s)
            except ValueError:
                pass
        if re.fullmatch(r"[+-]?0[xX][0-9a-fA-F]+", s):
            try:
                return int(s, 16)
            except ValueError:
                pass
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?", s):
            try:
                return float(s)
            except ValueError:
                pass
        raise RuntimeError(f"Number: cannot convert {value!r} to a number")

    @staticmethod
    def _time_unit(unit) -> str | None:
        """AHK TimeUnits: full names or first letter.  `M` is Minutes;
        Months must be spelled out (or `Mo`)."""
        u = str(unit).strip().lower()
        if not u:
            return None
        if u.startswith("mo"):
            return "months"
        if u.startswith("m"):
            return "minutes"
        if u.startswith("s"):
            return "seconds"
        if u.startswith("h"):
            return "hours"
        if u.startswith("d"):
            return "days"
        if u.startswith("y"):
            return "years"
        return None

    @staticmethod
    def _parse_ahk_datetime(value):
        """Parse YYYYMMDDHH24MISS (partial values default to Jan 1 / 00:00)."""
        import datetime as _dt
        digits = re.sub(r"\D", "", str(value))
        if len(digits) < 4:
            return None
        digits = digits.ljust(14, "0")
        try:
            return _dt.datetime(
                int(digits[0:4]), int(digits[4:6]) or 1, int(digits[6:8]) or 1,
                int(digits[8:10]), int(digits[10:12]), int(digits[12:14]))
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _add_months(dt, months: int):
        import calendar
        total = dt.year * 12 + (dt.month - 1) + months
        year, month0 = divmod(total, 12)
        month = month0 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)

    def _date_builtin(self, low: str, dt_arg, time_arg, unit_arg):
        import datetime as _dt
        unit = self._time_unit(unit_arg)
        dt = self._parse_ahk_datetime(dt_arg)
        if unit is None or dt is None:
            return "" if low == "dateadd" else 0
        if low == "dateadd":
            try:
                amount = int(float(time_arg))
            except (TypeError, ValueError):
                amount = 0
            try:
                if unit in ("months", "years"):
                    out = self._add_months(dt, amount * (12 if unit == "years" else 1))
                else:
                    out = dt + _dt.timedelta(**{unit: amount})
            except (ValueError, OverflowError):
                return ""
            return out.strftime("%Y%m%d%H%M%S")
        other = self._parse_ahk_datetime(time_arg)
        if other is None:
            return 0
        if dt >= other:
            a, b, sign = dt, other, 1
        else:
            a, b, sign = other, dt, -1
        if unit in ("months", "years"):
            months = (a.year - b.year) * 12 + (a.month - b.month)
            if self._add_months(b, months) > a:
                months -= 1
            return sign * (months // 12 if unit == "years" else months)
        seconds = (a - b).total_seconds()
        divisor = {"seconds": 1, "minutes": 60, "hours": 3600,
                   "days": 86400}[unit]
        return sign * int(seconds / divisor)

    @staticmethod
    def _read_ini_value(fname: str, section: str, key: str, default=""):
        """AHK IniRead semantics: missing file/section/key -> default.

        Windows profile APIs are case-insensitive for section and key names,
        trim surrounding whitespace, and do not interpolate `%`.  ConfigParser
        is configured to match; a BOM is accepted.
        """
        import configparser
        import os
        try:
            if not os.path.exists(fname):
                return default
            cfg = configparser.ConfigParser(interpolation=None, strict=False,
                                            allow_no_value=True)
            cfg.optionxform = str
            with open(fname, encoding="utf-8-sig") as fh:
                cfg.read_file(fh)
            sec = next((s for s in cfg.sections()
                        if s.lower() == section.lower()), None)
            if sec is None:
                return default
            for name, value in cfg.items(sec, raw=True):
                if name.lower() == key.lower():
                    return "" if value is None else value.strip()
        except (OSError, configparser.Error, UnicodeDecodeError):
            return default
        return default

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
            s = s[:m.start()] + str(self._get_var(m.group(1))) + s[m.end():]
        s = s.strip()
        if s == "":
            return ""
        # quoted string literal (the closing quote must be the last char;
        # `"a" x "b"` is implicit concatenation, not one literal)
        if self._is_whole_quoted(s):
            inner = s[1:-1]
            return self._interp(inner)
        # strip one layer of redundant wrapping parens: ((x)), (go("a")).
        # Same guard as _cond: only when the inside stays balanced, so
        # `(a)+(b)` and `(a) ? b : c` shapes are untouched.
        while len(s) >= 2 and s.startswith("(") and s.endswith(")") \
                and self._balanced(s[1:-1]):
            s = s[1:-1].strip()
        # Random(a, b) builtin -> int
        m = re.match(r"(?i)^random\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)$", s)
        if m:
            lo = int(self._eval_expr(m.group(1).strip()))
            hi = int(self._eval_expr(m.group(2).strip()))
            lo, hi = (lo, hi) if lo <= hi else (hi, lo)
            return self._rng.randint(lo, hi)
        # bare var
        if re.match(r"^[A-Za-z_]\w*$", s) and self._var_key(s) is not None:
            return self._get_var(s)
        # chained assignment in expressions: x := y := 5
        m = re.match(r"^([A-Za-z_]\w*)\s*:=\s*(.+)$", s, re.DOTALL)
        if m:
            val = self._eval_expr(m.group(2).strip())
            self._set_var(m.group(1), val)
            return val
        # complex assignment in an expression: obj.prop := v, arr[i] := v,
        # (ctrl := Gui.Add(...)).Section := "Gather".
        _assign = P._split_top(s, ":=")
        if (len(_assign) == 2 and _assign[0].strip() and _assign[1].strip()
                and not re.fullmatch(r"[A-Za-z_]\w*", _assign[0].strip())):
            lhs = _assign[0].strip()
            val = self._eval_expr(_assign[1].strip())
            self._set_expr_target(lhs, val)
            return val
        # explicit final index read: MainGui["StartButton"], arr[i], a[1][2]
        _idx = self._split_index_expr(s)
        if _idx is not None:
            base, index_raw = _idx
            return self._access(self._eval_expr(base),
                                self._eval_expr(index_raw))
        # method chain: base.A(args).B(args), each link keeps its own args.
        _chain = self._split_method_chain(s)
        if _chain is not None:
            base, methods = _chain
            if not self._is_atomic_expr(base):
                _chain = None
        if _chain is not None:
            base, methods = _chain
            obj = self._eval_expr(base)
            for meth, argstr in methods:
                from .parser import _split_seq as _ss_chain
                raw = [p.strip() for p in _ss_chain(argstr)] if argstr.strip() else []
                if not P._keep_empty_args(meth):
                    raw = [p for p in raw if p != ""]
                obj = self._dispatch_object_method(obj, meth, raw, base)
            return obj
        # function / method call inside expressions (raw args: quotes kept)
        m = re.match(r"^([A-Za-z_]\w*)\s*\((.*)\)$", s, re.DOTALL)
        if m and self._balanced(s):
            from .parser import _split_seq as _ss
            _args = [p.strip() for p in _ss(m.group(2))] if m.group(2).strip() else []
            # Gdip_*/Gui APIs use positional omitted arguments; preserve empties.
            if not P._keep_empty_args(m.group(1)):
                _args = [p for p in _args if p != ""]
            return self._call_value(P.FuncCall(m.group(1), _args))
        m = re.match(r"^(.+?)\.([A-Za-z_]\w*)\s*\((.*)\)$", s, re.DOTALL)
        if m and self._balanced(s):
            obj, meth, argstr = self._eval_expr(m.group(1)), m.group(2), m.group(3)
            from .parser import _split_seq as _ss2
            _raw = [p.strip() for p in _ss2(argstr)] if argstr.strip() else []
            if not P._keep_empty_args(meth):
                _raw = [p for p in _raw if p != ""]
            if hasattr(obj, "ahk_dispatch"):
                return obj.ahk_dispatch(meth, _raw, self)
            if isinstance(obj, TrayMenu):
                return obj.dispatch(meth, _raw, self)
            handled, result = self._class_static_call(m.group(1), meth, _raw)
            if handled:
                return result
            if meth.lower() == "bind":
                handled, result = self._bind_target(obj, _raw, m.group(1))
                if handled:
                    return result
            handled, result = self._collection_method(obj, meth.lower(), _raw)
            if handled:
                return result
            self.logs.append(f"method .{meth.lower()}() unsupported (logged)")
            return ""
        # AHK rule: `a.b` (no spaces) is object access, `a . b` is concat.
        m = re.match(r"^(.+?)\.([A-Za-z_]\w*)$", s, re.DOTALL)
        if (m and re.search(r"\S\.\S", s)
                and self._is_atomic_expr(m.group(1))):
            obj = self._eval_expr(m.group(1))
            prop = m.group(2).lower()
            if prop == "length" and isinstance(obj, (list, str, dict)):
                return len(obj)
            if isinstance(obj, dict):
                return obj.get(m.group(2), obj.get(prop, ""))
            if hasattr(obj, "ahk_get_property"):
                return obj.ahk_get_property(m.group(2))
            if isinstance(obj, TrayMenu):
                if prop == "default":
                    return obj.default or ""
                return getattr(obj, m.group(2), "")
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
        # {...} object literal: {UWP: "UWP Version", Web: x}.
        # Bare keys stay literal strings; values evaluate. On any shape
        # problem fall through (old literal behavior) instead of dying.
        if s.startswith("{") and s.endswith("}") and self._balanced(s[1:-1]):
            try:
                from .parser import _split_seq as _ss4
                _d = {}
                for _p in _ss4(s[1:-1]):
                    _pp = _p.strip()
                    if not _pp:
                        continue
                    _kv = self._split_logic(_pp, ":")
                    if len(_kv) < 2 or not _kv[0].strip():
                        continue
                    _kk = _kv[0].strip()
                    if len(_kk) >= 2 and _kk[0] == _kk[-1] and _kk[0] in ('"', "'"):
                        _kk = _kk[1:-1]
                    _d[_kk] = self._eval_expr(":".join(_kv[1:]).strip())
                return _d
            except Exception:
                pass
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
        # arithmetic containing calls or parenthesized subexpressions:
        # `windowY + GetYOffset(hwnd) + 36`, `windowX + Round(...)`.
        if "(" in s:
            num = self._eval_arith(s)
            if num is not None:
                return num
        # safe integer arithmetic with vars substituted
        try:
            tree = ast.parse(s, mode="eval")
            val = self._safe_eval(tree.body)
            return val
        except Exception:
            pass
        # AHK implicit concatenation: `x "|" y "|" w "|" h`.  Every term
        # must be clearly evaluable, so unknown prose keeps its literal
        # fallback instead of turning into a row of zeros.  Run before the
        # comparison check: a region term may contain `(a >= b ? x : y)`.
        parts = self._split_concat(s)
        if len(parts) > 1 and all(self._term_is_known(p) for p in parts):
            try:
                return "".join(str(self._eval_expr(p)) for p in parts)
            except Exception:
                pass
        # comparisons / regex-match in value position: `ok := (a >= b)`.
        if _has_cmp_op(s):
            try:
                return 1 if self._cond(s) else 0
            except Exception:
                pass
        # dotted string concat with vars: "a" . x  (AHK v2 `.` operator).
        # Split only top-level operator dots (surrounded by whitespace), so
        # periods inside strings (`"empty.**"`), decimals (`1.5`) and
        # property access (`obj.prop`) are left intact.
        dot_parts = self._split_dot_concat(s)
        if dot_parts:
            try:
                return "".join(str(self._eval_expr(p)) for p in dot_parts)
            except Exception:
                pass
        # bare int?
        try:
            return int(s)
        except ValueError:
            pass
        # unknown identifier -> 0 (AHK-ish falsy) unless it's a var name to keep
        if re.match(r"^[A-Za-z_]\w*$", s):
            key = self._var_key(s)
            return self.vars.get(key, 0) if key is not None else 0
        return s

    @staticmethod
    def _split_dot_concat(s: str):
        """Split a top-level AHK ``.`` concat, ignoring quoted/bracketed dots.

        Returns ``None`` unless at least one operator dot is found.  A dot
        counts as an operator only when it is outside quotes/brackets and has
        whitespace on at least one side; that keeps ``1.5`` and ``obj.prop``
        intact while accepting both ``a . b`` and ``a. b``.
        """
        parts: list[str] = []
        cur = ""
        depth, quote, k = 0, None, 0
        found = False
        while k < len(s):
            ch = s[k]
            if ch == "`" and k + 1 < len(s):
                cur += s[k:k + 2]
                k += 2
                continue
            if quote:
                cur += ch
                if ch == quote:
                    quote = None
            elif ch in ('"', "'"):
                quote = ch
                cur += ch
            elif ch in "([":
                depth += 1
                cur += ch
            elif ch in ")]":
                depth = max(0, depth - 1)
                cur += ch
            elif ch == "." and depth == 0:
                before = s[k - 1] if k else ""
                after = s[k + 1] if k + 1 < len(s) else ""
                if before.isspace() or after.isspace():
                    parts.append(cur)
                    cur = ""
                    found = True
                else:
                    cur += ch
            else:
                cur += ch
            k += 1
        if not found:
            return None
        parts.append(cur)
        parts = [p.strip() for p in parts]
        if any(not p for p in parts):
            return None
        return parts

    @staticmethod
    def _is_whole_quoted(s: str) -> bool:
        """True when ``s`` is one quoted literal (closing quote at the end)."""
        if len(s) < 2 or s[0] not in ('"', "'"):
            return False
        quote, k = s[0], 1
        while k < len(s):
            if s[k] == "`" and k + 1 < len(s):
                k += 2
                continue
            if s[k] == quote:
                return k == len(s) - 1
            k += 1
        return False

    @staticmethod
    def _split_concat(s: str) -> list:
        """Split AHK implicit concatenation at top-level spaces.

        A boundary is whitespace between two atom characters (`x "|" y`) and
        never whitespace next to an operator (`a + b` stays one term).
        """
        parts, start, depth, quote = [], 0, 0, None
        k = 0
        while k < len(s):
            ch = s[k]
            if quote:
                if ch == "`" and k + 1 < len(s):
                    k += 2
                    continue
                if ch == quote:
                    quote = None
                k += 1
                continue
            if ch == "`" and k + 1 < len(s):
                k += 2
                continue
            if ch in ('"', "'"):
                quote = ch
                k += 1
                continue
            if ch in "([{":
                depth += 1
                k += 1
                continue
            if ch in ")]}":
                depth = max(0, depth - 1)
                k += 1
                continue
            if ch.isspace() and depth == 0:
                j = k
                while j < len(s) and s[j].isspace():
                    j += 1
                if j >= len(s):
                    break
                prev, nxt = s[k - 1], s[j]
                atom_prev = prev.isalnum() or prev in '_)]}"\''
                atom_next = nxt.isalnum() or nxt in '_([{"\''
                if atom_prev and atom_next:
                    piece = s[start:k].strip()
                    if piece:
                        parts.append(piece)
                    start = j
                k = j
                continue
            k += 1
        if parts:
            piece = s[start:].strip()
            if piece:
                parts.append(piece)
        if any(p.lower() in ("not", "and", "or") for p in parts):
            return []
        return parts

    def _term_is_known(self, term: str) -> bool:
        """True for literals, vars, calls, and arithmetic; false for prose."""
        term = term.strip()
        if not term:
            return False
        if term[0] in ('"', "'", "(", "[", "{"):
            return True
        if re.fullmatch(r"-?\d+(?:\.\d+)?", term):
            return True
        if re.fullmatch(r"[A-Za-z_]\w*", term):
            return self._var_key(term) is not None
        if re.search(r"[+\-*/%]", term):
            return True
        if re.match(r"^[A-Za-z_]\w*\s*\(", term):
            return True
        if re.match(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\s*\(", term):
            return True
        m = re.fullmatch(r"([A-Za-z_]\w*)(?:\.[A-Za-z_]\w*)+", term)
        if m:
            return self._var_key(m.group(1)) is not None
        if re.search(r"\[[^\]]+\]", term):
            return True
        return False

    @staticmethod
    def _find_call(s: str):
        """Return the last (innermost) ``Name(...)`` call outside quotes."""
        quote, found, k = None, [], 0
        while k < len(s):
            ch = s[k]
            if quote:
                if ch == "`" and k + 1 < len(s):
                    k += 2
                    continue
                if ch == quote:
                    quote = None
                k += 1
                continue
            if ch == "`" and k + 1 < len(s):
                k += 2
                continue
            if ch in ('"', "'"):
                quote = ch
                k += 1
                continue
            m = re.match(r"([A-Za-z_]\w*)\s*\(", s[k:])
            if m:
                start = k
                open_idx = k + m.end() - 1
                depth, inner_q, j = 1, None, open_idx + 1
                while j < len(s) and depth:
                    c = s[j]
                    if inner_q:
                        if c == inner_q:
                            inner_q = None
                    elif c in ('"', "'"):
                        inner_q = c
                    elif c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                    j += 1
                if depth == 0:
                    found.append((m.group(1), s[open_idx + 1:j - 1], start, j))
                    k = j
                    continue
            k += 1
        return found[-1] if found else None

    @staticmethod
    def _find_paren_group(s: str):
        """Return the first closed ``(...)`` group outside quotes."""
        quote, stack, k = None, [], 0
        while k < len(s):
            ch = s[k]
            if quote:
                if ch == "`" and k + 1 < len(s):
                    k += 2
                    continue
                if ch == quote:
                    quote = None
                k += 1
                continue
            if ch == "`" and k + 1 < len(s):
                k += 2
                continue
            if ch in ('"', "'"):
                quote = ch
                k += 1
                continue
            if ch == "(":
                stack.append(k)
            elif ch == ")" and stack:
                start = stack.pop()
                return start, k + 1, s[start + 1:k]
            k += 1
        return None

    @staticmethod
    def _num_literal(value):
        """Format a numeric value as an AST literal, or None if non-numeric."""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return repr(value)
        if isinstance(value, str):
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return repr(int(number)) if number.is_integer() else repr(number)
        return None

    def _eval_arith(self, s: str):
        """Evaluate arithmetic with calls/parenthesized groups, else None.

        Python's AST does the operator precedence; this only replaces AHK
        calls (`Round(...)`, `GetYOffset(hwnd)`) and parenthesized
        subexpressions (which may be ternaries) with numeric literals.
        """
        from .parser import _split_seq as _ss
        s = s.strip()
        for _ in range(50):
            call = self._find_call(s)
            if call is None:
                break
            name, argstr, start, end = call
            raw = [p.strip() for p in _ss(argstr)] if argstr.strip() else []
            raw = [p for p in raw if p != ""]
            try:
                # Keep source expressions raw: _call_value evaluates user
                # function args and builtins such as StrPtr/NumGet need the
                # original `&out`/quoted-string position.  Evaluating here
                # turns a base64 variable into a self-referential expression.
                value = self._call_value(P.FuncCall(name, raw))
            except Exception:
                return None
            literal = self._num_literal(value)
            if literal is None:
                return None
            s = s[:start] + literal + s[end:]
        for _ in range(50):
            group = self._find_paren_group(s)
            if group is None:
                break
            start, end, inner = group
            value = self._eval_expr(inner)
            literal = self._num_literal(value)
            if literal is None:
                return None
            s = s[:start] + literal + s[end:]
        out, k, quote = [], 0, None
        while k < len(s):
            ch = s[k]
            if quote:
                out.append(ch)
                if ch == quote:
                    quote = None
                k += 1
                continue
            if ch in ('"', "'"):
                quote = ch
                out.append(ch)
                k += 1
                continue
            # Preserve numeric literals (including hex `0xff`) before
            # treating their letters as variable names.  Without this,
            # `0xff` became `0x` + variable `xff` -> 0.
            mn = re.match(r"0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?", s[k:])
            if mn:
                out.append(mn.group(0))
                k += len(mn.group(0))
                continue
            m = re.match(r"[A-Za-z_]\w*", s[k:])
            if m:
                name = m.group(0)
                literal = self._num_literal(self._get_var(name) or 0)
                if literal is None:
                    return None
                out.append(literal)
                k += len(name)
                continue
            out.append(ch)
            k += 1
        try:
            tree = ast.parse("".join(out), mode="eval")
            return self._safe_eval(tree.body)
        except Exception:
            return None

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
            key = self._var_key(node.id)
            v = self.vars.get(key, 0) if key is not None else 0
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
                (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
                 ast.Pow, ast.BitAnd, ast.BitOr, ast.BitXor,
                 ast.LShift, ast.RShift)):
            a, b = self._safe_eval(node.left), self._safe_eval(node.right)
            # AHK auto-converts numeric strings: "00" * 3600 == 0, never
            # Python-style string repetition.  Bitwise operators (used by
            # HashFile's NumGet hex loop) require integers, not floats.
            try:
                a = self._numval(a) if isinstance(a, str) else a
                b = self._numval(b) if isinstance(b, str) else b
            except (TypeError, ValueError):
                raise ValueError("non-numeric operands")
            ops = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
                   ast.Div: _op.truediv, ast.FloorDiv: _op.floordiv, ast.Mod: _op.mod,
                   ast.Pow: _op.pow, ast.BitAnd: _op.and_,
                   ast.BitOr: _op.or_, ast.BitXor: _op.xor,
                   ast.LShift: _op.lshift, ast.RShift: _op.rshift}
            if isinstance(node.op, (ast.BitAnd, ast.BitOr, ast.BitXor,
                                    ast.LShift, ast.RShift)):
                try:
                    a, b = int(a), int(b)
                except (TypeError, ValueError):
                    raise ValueError("non-integer bitwise operands")
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

    @staticmethod
    def _unescape_ahk(text: str) -> str:
        """Decode AHK backtick escapes (`` `n ``, `` `t ``, `` `" `` ...).

        This is string-literal processing, not a Windows feature: FileWrite,
        Send and MsgBox all need it for Natro's generated pattern/config
        text.  Unknown escapes drop the backtick, matching AHK.
        """
        if "`" not in text:
            return text
        table = {"n": "\n", "r": "\r", "t": "\t", "b": "\b",
                 "a": "\a", "f": "\f", "v": "\v", "`": "`",
                 '"': '"', "'": "'", ";": ";", ",": ",", "%": "%",
                 " ": " "}
        out = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "`" and i + 1 < len(text):
                nxt = text[i + 1]
                out.append(table.get(nxt, nxt))
                i += 2
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    def _interp(self, text: str) -> str:
        text = self._unescape_ahk(str(text))

        def rep(m):
            key = self._var_key(m.group(1))
            return str(self.vars.get(key)) if key is not None else m.group(0)
        return re.sub(r"\{(\w+)\}", rep, text)

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
                # AHK/AutoHotkey short-circuits both operators.  Evaluating
                # every branch eagerly breaks guards such as
                # `A_Args.Has(1) && (A_Args[1] = 1)` on an empty array.
                if any_of:
                    for part in parts:
                        if self._cond(part):
                            return True
                    return False
                for part in parts:
                    if not self._cond(part):
                        return False
                return True
        # leading negation: !x, !FileExist(f)
        if cond.startswith("!") and not cond.startswith("!="):
            return not self._cond(cond[1:].strip())
        # assignment-in-condition: (attr := FileExist(f)) -> assign + test
        m = re.match(r"^([A-Za-z_]\w*)\s*:=\s*(.+)$", cond)
        if m:
            self._set_var(m.group(1), self._eval_expr(m.group(2).strip()))
            return self._truthy(self._get_var(m.group(1)))
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
        # Only split at a TOP-LEVEL comparison operator.  In particular, a
        # function call containing `:=` (HashFile's DllCall arguments) must
        # not be mistaken for `lhs = rhs`; the old regex matched the `=` in
        # `:=` and made the crypto calls evaluate as strings.
        cmp_parts = self._split_comparison(cond)
        if cmp_parts is not None:
            lhs_raw, op, rhs_raw = cmp_parts
            lhs = self._eval_expr(lhs_raw)
            rhs = self._eval_expr(rhs_raw)
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
    def _split_comparison(text: str):
        """Find a top-level comparison operator, ignoring `:=` and nested
        calls.  Returns (lhs, op, rhs) or None."""
        text = str(text)
        depth = 0
        quote = None
        k = 0
        while k < len(text):
            ch = text[k]
            if quote:
                if ch == "`" and k + 1 < len(text):
                    k += 2
                    continue
                if ch == quote:
                    quote = None
                k += 1
                continue
            if ch in ('"', "'"):
                quote = ch
                k += 1
                continue
            if ch in "([{":
                depth += 1
                k += 1
                continue
            if ch in ")]}":
                depth = max(0, depth - 1)
                k += 1
                continue
            if depth == 0:
                two = text[k:k + 2]
                if two in ("<=", ">=", "==", "!=", "~="):
                    return text[:k].strip(), two, text[k + 2:].strip()
                if ch in "<>":
                    return text[:k].strip(), ch, text[k + 1:].strip()
                if ch == "=":
                    prev = text[k - 1] if k else ""
                    nxt = text[k + 1] if k + 1 < len(text) else ""
                    if prev not in (":", "=", "!", "<", ">") and nxt not in ("=", ">"):
                        return text[:k].strip(), "=", text[k + 1:].strip()
            k += 1
        return None

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
