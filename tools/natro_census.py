#!/usr/bin/env python3
"""Natro stub-hit census for the AHK-Linux bridge.

Three jobs, per the v0.5 roadmap:

1. Static inventory of all corpus files (parser nodes, functions, raw calls,
   function calls and legacy commands).
2. Runtime auto-section execution of every script in a *sandbox copy* of the
   corpus, with capture/window/Run effects suppressed and a per-file timeout.
3. JSON + Markdown report of stub hits, with a load-bearing triage.

Examples:
    python3 tools/natro_census.py
    python3 tools/natro_census.py --root ~/Games/NatroMacro/src \
        --json /tmp/opencode/census.json --markdown /tmp/opencode/census.md

The harness never touches the real corpus: it copies source/config files to
a temporary directory first and runs child workers with that directory as
their cwd.  Vision and window activation are monkeypatched inside workers.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CORPUS_DEFAULT = Path(os.path.expanduser("~/Games/NatroMacro/src"))

DISPLAY_ONLY = {
    "msgbox", "tooltip", "traytip", "soundbeep", "soundplay",
    "splashimage", "splashtextoff", "progress", "inputbox",
}
EXTERNAL = {
    "run", "runwait", "comobject", "comcall", "objrelease", "urlopen",
    "winhttp", "download", "discord",
}
WINDOWS_ONLY = {
    "dllcall", "processclose", "processexist", "winexist", "winactivate",
    "wingetpos", "wingetclientpos", "wingettitle", "wingettext", "winclose",
    "winkill", "winmove", "winsettransparent", "controlgetpos",
    "controlgettext", "sendmessage", "postmessage", "onmessage",
    # Memory/COM primitives: only meaningful to DllCall/GDI+ consumers.
    "numget", "numput", "strptr", "comvalue", "comobjget", "strget",
}


# --------------------------------------------------------------------------
# AST walk / static inventory
# --------------------------------------------------------------------------
def walk_nodes(nodes):
    """Yield every node once, descending into all block-bearing fields."""
    seen: set[int] = set()

    def walk(items):
        for node in items or []:
            if id(node) in seen:
                continue
            seen.add(id(node))
            yield node
            for attr in ("body", "then_body", "else_body", "try_body",
                         "catch_body", "finally_body"):
                value = getattr(node, attr, None)
                if isinstance(value, list):
                    yield from walk(value)
            for case in getattr(node, "cases", []) or []:
                try:
                    yield from walk(case[1])
                except (TypeError, IndexError):
                    pass
            if hasattr(node, "items") and isinstance(node.items, list):
                yield from walk(node.items)

    yield from walk(nodes)


def static_inventory(root: Path) -> dict:
    from ahk_bridge.parser import parse_script

    files = sorted(root.rglob("*.ahk"))
    calls: collections.Counter = collections.Counter()
    legacy: collections.Counter = collections.Counter()
    methods: collections.Counter = collections.Counter()
    raw: collections.Counter = collections.Counter()
    node_types: collections.Counter = collections.Counter()
    defined: set[str] = set()
    function_count = 0
    crash_files: list[str] = []

    for path in files:
        try:
            sc = parse_script(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001 - census must survive
            crash_files.append(f"{path}: {exc}")
            continue
        function_count += len(sc.functions)
        defined.update(sc.functions)
        nodes = list(walk_nodes(sc.auto_section))
        for fn in sc.functions.values():
            nodes.extend(walk_nodes(fn.body))
        for node in nodes:
            node_types[type(node).__name__] += 1
            if type(node).__name__ == "FuncCall":
                name = getattr(node, "name", "")
                if name == "__raw__":
                    text = str(node.args[0]) if getattr(node, "args", None) else ""
                    key = text.strip().split()[0] if text.strip() else "?"
                    raw[key] += 1
                elif "." in name:
                    methods[name] += 1
                else:
                    calls[name] += 1
            elif type(node).__name__ == "LegacyCmd":
                legacy[getattr(node, "name", "?")] += 1
            elif type(node).__name__ == "DynCall":
                calls[f"dyn:{getattr(node, 'head', '?')}"] += 1

    undefined = {name: n for name, n in calls.items()
                 if name not in defined and not name.startswith("dyn:")}
    return {
        "files": len(files),
        "functions": function_count,
        "nodes": sum(node_types.values()),
        "raw": sum(raw.values()),
        "raw_pct": round(100.0 * sum(raw.values()) / max(1, sum(node_types.values())), 2),
        "crashes": crash_files,
        "defined_functions": len(defined),
        "defined_names": sorted(defined),
        "calls": dict(calls.most_common()),
        "legacy": dict(legacy.most_common()),
        "methods": dict(methods.most_common()),
        "raw_top": dict(raw.most_common(22)),
        "node_types": dict(node_types.most_common()),
        "undefined_calls": dict(sorted(undefined.items(), key=lambda kv: -kv[1])),
    }


def main_expanded_stats(root: Path) -> dict:
    from ahk_bridge.includes import expand_includes

    path = root / "submacros" / "natro_macro.ahk"
    if not path.exists():
        return {"available": False}
    start = time.monotonic()
    ex = expand_includes(str(path), strict=False)
    elapsed = time.monotonic() - start
    sc = ex.parse()
    raw = sum(1 for n in walk_nodes(sc.auto_section)
              if type(n).__name__ == "FuncCall" and n.name == "__raw__")
    return {
        "available": True,
        "files": len(ex.files),
        "lines": len(ex.lines),
        "chars": len(ex.text),
        "expand_seconds": round(elapsed, 3),
        "parse_seconds": round(time.monotonic() - start - elapsed, 3),
        "auto_statements": len(sc.auto_section),
        "functions": len(sc.functions),
        # Case-insensitive (AHK semantics) for cross-file triage.
        "defined_names": sorted(name.lower() for name in sc.functions),
        "raw": raw,
        "include_records": dict(collections.Counter(r.status for r in ex.records)),
        "warnings": ex.warnings[:10],
    }


# --------------------------------------------------------------------------
# Runtime worker
# --------------------------------------------------------------------------
def runtime_worker(path: str, max_loop: int, deadline: float | None = None) -> dict:
    """Run one script's auto-section with all desktop/file effects suppressed."""
    import signal
    import warnings
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    from ahk_bridge import vision
    from ahk_bridge.backends.dry_backend import DryBackend
    from ahk_bridge.includes import load_script
    from ahk_bridge import runtime as R

    saved = {
        "win_activate": R.Runtime._win_activate,
        "pixel_search": R.Runtime._pixel_search,
        "call_value": R.Runtime._call_value,
        "vision": {name: getattr(vision, name) for name in (
            "from_screen", "from_base64", "image_search", "dispose",
            "width", "height", "dimensions")},
    }

    def restore():
        R.Runtime._win_activate = saved["win_activate"]
        R.Runtime._pixel_search = saved["pixel_search"]
        R.Runtime._call_value = saved["call_value"]
        for name, fn in saved["vision"].items():
            setattr(vision, name, fn)

    # Suppress all desktop interaction.  The child inherits a temp cwd.
    R.Runtime._win_activate = lambda self, title: self.logs.append(
        f"census: WinActivate {title!r} suppressed")
    R.Runtime._pixel_search = lambda self, st: self.logs.append(
        "census: PixelSearch suppressed")
    vision.from_screen = lambda *a, **k: 0
    vision.from_base64 = lambda *a, **k: 0
    vision.image_search = lambda *a, **k: (0, "")
    vision.dispose = lambda *a, **k: ""
    vision.width = lambda *a, **k: 0
    vision.height = lambda *a, **k: 0
    vision.dimensions = lambda *a, **k: (0, 0)

    # The real Gdip_Startup helper (in Gdip_All.ahk) DllCalls into GDI+ and
    # throws here; census only needs the rest of the auto-section to run.
    original_call = R.Runtime._call_value

    def census_call(self, call):
        low = str(getattr(call, "name", "")).lower()
        if low == "gdip_startup":
            return 1
        if low == "gdip_shutdown":
            return 0
        return original_call(self, call)

    R.Runtime._call_value = census_call

    started = time.monotonic()

    class _CensusDeadline(BaseException):
        # BaseException, not Exception: the runtime has broad
        # `except Exception` guards around script errors, which must not
        # swallow the census budget signal.
        pass

    def _on_deadline(signum, frame):  # noqa: ARG001
        raise _CensusDeadline

    if deadline:
        signal.signal(signal.SIGALRM, _on_deadline)
        signal.setitimer(signal.ITIMER_REAL, deadline)
    try:
        script, expanded = load_script(path, strict=False)
    except _CensusDeadline:
        if deadline:
            signal.setitimer(signal.ITIMER_REAL, 0)
        restore()
        return {"file": path, "logs": [], "census_errors": [],
                "deadline_hit": True, "seconds": round(time.monotonic() - started, 3),
                "warnings": []}
    except Exception as exc:  # noqa: BLE001
        if deadline:
            signal.setitimer(signal.ITIMER_REAL, 0)
        restore()
        return {"file": path, "load_error": f"{type(exc).__name__}: {exc}",
                "logs": [], "seconds": 0.0, "warnings": []}
    sim = DryBackend()
    rt = R.Runtime(script, sim, max_loop=max_loop, allow_processes=False)
    error = None
    census_errors: list[str] = []
    deadline_hit = False
    # Execute one top-level statement at a time so one unimplemented call
    # cannot hide the rest of the inventory.  This is a census-only mode;
    # the real runtime still aborts on an uncaught script error.
    try:
        for stmt in script.auto_section:
            try:
                rt._exec(stmt)
            except R.Aborted:
                break
            except _CensusDeadline:
                deadline_hit = True
                break
            except Exception as exc:  # noqa: BLE001
                census_errors.append(f"{type(stmt).__name__}: {exc}")
                if len(census_errors) >= 20:
                    break
    except Exception as exc:  # noqa: BLE001 - a bad file must not kill census
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if deadline:
            signal.setitimer(signal.ITIMER_REAL, 0)
        restore()
    return {
        "file": path,
        "logs": rt.logs,
        "error": error,
        "census_errors": census_errors,
        "deadline_hit": deadline_hit,
        "seconds": round(time.monotonic() - started, 3),
        "warnings": expanded.warnings[:5],
    }


# --------------------------------------------------------------------------
# Runtime log classification
# --------------------------------------------------------------------------
RE_STUB_BUILTIN = re.compile(r"^stub builtin (\w+)\(\)")
RE_STUB = re.compile(r"^stub ([\w.]+)\(\)")
RE_RAW = re.compile(r"^raw: (.*)$")
RE_SKIP = re.compile(r"^skip: (.+)$")
RE_METHOD = re.compile(r"^method \.(\w+)\(\) unsupported")
RE_ASSIGN = re.compile(
    r"^assign-target (.+?) (?:unsupported|failed|has no live container)")
RE_FOR = re.compile(r"^for: unsupported enumerable")
RE_CMD_NOOP = re.compile(r"^(\w+)(?:\s.*?)? \((?:OS/window op|noted), linux no-op\)$")
RE_SETTING = re.compile(r"^setting (\S+) ")
RE_INCLUDE = re.compile(r"^#Include (.+?) \(not inlined")
RE_GDIP_ERR = re.compile(r"^(Gdip_\w+) failed")
RE_CENSUS = re.compile(r"^census: ")


def classify_log(line: str):
    if line.startswith("setting "):
        m = RE_SETTING.match(line)
        if m:
            return ("setting", m.group(1), line)
    m = RE_STUB_BUILTIN.match(line)
    if m:
        return ("builtin", m.group(1), line)
    m = RE_STUB.match(line)
    if m:
        name = m.group(1)
        kind = "gdip" if name.lower().startswith("gdip_") else "builtin"
        return (kind, name, line)
    m = RE_RAW.match(line)
    if m:
        text = m.group(1).strip()
        return ("raw", "__raw__", text[:160])
    m = RE_METHOD.match(line)
    if m:
        return ("method", m.group(1), line)
    m = RE_ASSIGN.match(line)
    if m:
        return ("assign-target", m.group(1)[:80], line)
    if RE_FOR.match(line):
        return ("for", "for-in", line)
    m = RE_CMD_NOOP.match(line)
    if m:
        return ("command", m.group(1), line)
    m = RE_SETTING.match(line)
    if m:
        return ("setting", m.group(1), line)
    m = RE_INCLUDE.match(line)
    if m:
        return ("include", m.group(1), line)
    m = RE_GDIP_ERR.match(line)
    if m:
        return ("gdip-error", m.group(1), line)
    if RE_SKIP.match(line):
        text = m.group(1)
        name = text.split("(", 1)[0].strip() if "(" in text else text[:60]
        return ("skip", name, line)
    return None


def verdict_for(name: str, kind: str) -> str:
    low = name.lower()
    if kind in ("setting", "setting-noop"):
        return "setting-noop"
    if kind in ("for", "assign-target", "method"):
        return "language-gap"
    if kind == "raw":
        return "parser-raw"
    if low in DISPLAY_ONLY:
        return "display-only"
    if low in EXTERNAL:
        return "external-service"
    if low in WINDOWS_ONLY or kind in ("gdip", "gdip-error"):
        return "windows-only"
    return "unknown"


# Verdicts that the Linux runtime deliberately does not reproduce.  These stay
# visible in the report but are not part of the unknown-work count.
NON_LOAD_BEARING = {
    "display-only", "setting-noop", "parser-raw", "cross-file",
}


def load_bearing_for(verdict: str) -> bool:
    return verdict not in NON_LOAD_BEARING


# --------------------------------------------------------------------------
# Parent orchestration
# --------------------------------------------------------------------------
COPY_INCLUDE = {".ahk", ".ini", ".txt", ".json", ".md"}


def prepare_sandbox(root: Path) -> Path:
    sandbox = Path(tempfile.mkdtemp(prefix="ahk-census-"))

    def ignore(directory, names):
        ignored = []
        for name in names:
            full = Path(directory) / name
            if name in (".git", "__pycache__"):
                ignored.append(name)
            elif full.is_file() and full.suffix.lower() not in COPY_INCLUDE:
                ignored.append(name)
        return ignored

    shutil.copytree(root, sandbox / "src", ignore=ignore)
    return sandbox


def run_runtime_census(root: Path, files: list[Path], max_loop: int,
                       timeout: float, sandbox: Path) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    timeouts: list[str] = []
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"]
                                    if env.get("PYTHONPATH") else "")
    env["AHK_BRIDGE_CENSUS"] = "1"
    for index, path in enumerate(files, 1):
        rel = path.relative_to(root)
        sandbox_file = sandbox / "src" / rel
        if not sandbox_file.exists():
            timeouts.append(f"{rel}: missing from sandbox")
            continue
        cmd = [sys.executable, str(Path(__file__).resolve()),
               "--worker", str(sandbox_file), "--max-loop", str(max_loop),
               "--deadline", str(max(1.0, timeout - 1.0))]
        try:
            proc = subprocess.run(cmd, cwd=str(sandbox), env=env,
                                  capture_output=True, text=True,
                                  timeout=timeout)
            data = None
            for line in reversed((proc.stdout or "").splitlines()):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
            if data is None:
                timeouts.append(f"{rel}: worker returned no JSON "
                                f"(rc={proc.returncode}, {proc.stderr[-300:]})")
                continue
            data["relative"] = str(rel)
            results.append(data)
        except subprocess.TimeoutExpired:
            timeouts.append(f"{rel}: timeout after {timeout}s")
        if index % 25 == 0:
            print(f"  runtime {index}/{len(files)}", file=sys.stderr)
    return results, timeouts


def group_hit_name(kind: str, name: str) -> str:
    """Collapse indexed assignment variants to one triage row.

    `bitmaps["day"]["ant"]`, `bitmaps["night"]` and `(bitmaps := Map())...`
    are one root cause (`bitmaps`), not thirty.  Full targets stay in the
    sample column and in the JSON.
    """
    if kind != "assign-target":
        return name
    s = name.strip().strip("'\"")
    if s.startswith("("):
        m = re.match(r'\(\s*([A-Za-z_]\w*)', s)
        return "(" + m.group(1) if m else "(expression)"
    m = re.match(r'[A-Za-z_]\w*', s)
    if not m:
        return s[:24] or "?"
    root = m.group(0)
    if "[" in s:
        root += "[...]"
    return root


def aggregate_runtime(results: list[dict], defined: set[str] | None = None) -> dict:
    # AHK identifiers are case-insensitive.  Keep the set lowered so
    # `nm_Walk` in a path fragment matches `nm_walk` at the call site.
    defined = {name.lower().lstrip("&") for name in (defined or set())}
    hits: dict[tuple[str, str], dict] = {}
    for result in results:
        for line in result.get("logs", []):
            classified = classify_log(line)
            if not classified:
                continue
            kind, raw_name, sample = classified
            name = group_hit_name(kind, raw_name)
            key = (kind, name)
            entry = hits.setdefault(key, {
                "kind": kind, "name": name, "count": 0,
                "files": [], "samples": [],
            })
            entry["count"] += 1
            rel = result.get("relative", result.get("file", "?"))
            if rel not in entry["files"]:
                entry["files"].append(rel)
            if len(entry["samples"]) < 3 and sample not in entry["samples"]:
                entry["samples"].append(sample)
    out = []
    for entry in hits.values():
        verdict = verdict_for(entry["name"], entry["kind"])
        if verdict == "unknown" and entry["name"].lower() in defined:
            # Defined in another corpus file but not included by this one;
            # the main script's include tree supplies it at load time.
            verdict = "cross-file"
        entry["verdict"] = verdict
        entry["load_bearing"] = load_bearing_for(verdict)
        out.append(entry)
    out.sort(key=lambda item: (-item["count"], item["kind"], item["name"]))
    errors = []
    for r in results:
        raw_errors = r.get("census_errors") or []
        counts = collections.Counter(raw_errors)
        summary = "; ".join(f"{msg} x{n}" if n > 1 else msg
                            for msg, n in counts.most_common(6))
        errors.append({
            "file": r.get("relative"),
            "error": r.get("error") or summary,
            "load_error": r.get("load_error"),
        })
    return {
        "hits": out,
        "unknown_load_bearing": [h for h in out
                                 if h["verdict"] == "unknown" and h["load_bearing"]],
        "known_gaps": [h for h in out if h["verdict"] in (
            "language-gap", "windows-only", "external-service", "command")],
        "errors": [e for e in errors
                   if e["error"] or e["load_error"]],
    }


def render_markdown(report: dict) -> str:
    static = report["static"]
    expanded = report["expanded_main"]
    runtime = report["runtime"]
    lines = [
        "# Natro census",
        "",
        f"Generated: {report['generated']}",
        f"Corpus: `{report['root']}`",
        "",
        "> Triage baseline, not a score. `language-gap` rows are known",
        "> parser/runtime gaps (at this baseline, many come from function bodies",
        "> leaking into the auto-section after nested definitions).",
        "> `windows-only` rows are DllCall/GDI+/COM surfaces replaced by the",
        "> Linux vision layer; `unknown` rows are the actionable headless",
        "> builtins. The JSON companion contains every hit and sample.",
        "> All runtime work happens in a temporary corpus copy with desktop",
        "> effects suppressed.",
        "",
        "## Static inventory",
        "",
        f"- files: **{static['files']}**",
        f"- functions parsed: **{static['functions']}**",
        f"- nodes: **{static['nodes']}**",
        f"- `__raw__`: **{static['raw']} ({static['raw_pct']}%)**",
        f"- parse crashes: **{len(static['crashes'])}**",
        f"- distinct defined functions: **{static['defined_functions']}**",
        "",
        "## Expanded main script",
        "",
    ]
    if expanded.get("available"):
        lines += [
            f"- include files: **{expanded['files']}**",
            f"- logical lines: **{expanded['lines']}**",
            f"- expand / parse: **{expanded['expand_seconds']} s / "
            f"{expanded['parse_seconds']} s**",
            f"- auto statements: **{expanded['auto_statements']}**",
            f"- functions: **{expanded['functions']}**",
            f"- raw in auto-section: **{expanded['raw']}**",
            f"- include records: `{expanded['include_records']}`",
            "",
        ]
    else:
        lines += ["- corpus main script not found", ""]
    lines += [
        "## Runtime stub hits",
        "",
        f"- files executed: **{runtime['files_executed']}**",
        f"- timeouts: **{len(runtime['timeouts'])}**",
        f"- worker deadline stops: **{len(runtime.get('deadline_hits', []))}**",
        f"- execution/load errors: **{len(runtime['errors'])}**",
        f"- unknown load-bearing hits: **{len(runtime['unknown_load_bearing'])}**",
        f"- known gaps (language/windows/external): **{len(runtime.get('known_gaps', []))}**",
        "",
    ]
    counts = collections.Counter(hit["verdict"] for hit in runtime["hits"])
    if counts:
        lines += ["Verdict totals: " + ", ".join(
            f"**{name}** {count}" for name, count in counts.most_common()), ""]
    lines += [
        "Triage table: unknown and known-gap hits only (all hits are in the",
        "JSON).  Benign settings, display-only calls, parser raws and",
        "cross-file calls are counted above but not listed row by row.",
        "",
        "| kind | name | count | verdict | load-bearing | sample |",
        "|---|---|---:|---|---|---|",
    ]
    triage = [h for h in runtime["hits"]
              if h["verdict"] not in ("setting-noop", "display-only",
                                      "parser-raw", "cross-file")]
    for hit in triage[:150]:
        sample = (hit["samples"][0] if hit["samples"] else "").replace("|", "\\|")
        lines.append(
            f"| {hit['kind']} | `{hit['name']}` | {hit['count']} | "
            f"{hit['verdict']} | {'yes' if hit['load_bearing'] else 'no'} | "
            f"`{sample[:110]}` |")
    if runtime["errors"]:
        lines += ["", "## Errors", ""]
        for err in runtime["errors"]:
            lines.append(f"- `{err['file']}`: {err['error'] or err['load_error']}")
    if runtime["timeouts"]:
        lines += ["", "## Timeouts", ""]
        lines += [f"- {item}" for item in runtime["timeouts"]]
    if runtime.get("deadline_hits"):
        lines += ["", "## Worker deadline stops (partial inventory)", ""]
        lines += [f"- {item}" for item in runtime["deadline_hits"]]
    lines += ["", "## Static top raw calls", ""]
    for name, count in list(static["raw_top"].items())[:15]:
        lines.append(f"- `{name}`: {count}")
    lines += ["", "## Top undefined static calls", ""]
    for name, count in list(static["undefined_calls"].items())[:40]:
        lines.append(f"- `{name}`: {count}")
    lines.append("")
    return "\n".join(lines)


def census(root: Path, max_loop: int, timeout: float,
           max_files: int | None = None) -> dict:
    root = root.resolve()
    files = sorted(root.rglob("*.ahk"))
    if max_files:
        files = files[:max_files]
    print(f"static inventory: {len(files)} files", file=sys.stderr)
    static = static_inventory(root)
    print("expanded main script", file=sys.stderr)
    expanded = main_expanded_stats(root)
    sandbox = prepare_sandbox(root)
    print(f"runtime census in {sandbox}", file=sys.stderr)
    try:
        results, timeouts = run_runtime_census(
            root, files, max_loop=max_loop, timeout=timeout, sandbox=sandbox)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    runtime = aggregate_runtime(
        results, set(static["defined_names"]) | set(expanded.get("defined_names", [])))
    runtime["files_executed"] = len(results)
    runtime["timeouts"] = timeouts
    runtime["deadline_hits"] = [
        f"{r.get('relative')}: stopped at worker deadline "
        f"({r.get('seconds')}s; partial inventory)" for r in results
        if r.get("deadline_hit")]
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "static": static,
        "expanded_main": expanded,
        "runtime": runtime,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Natro stub-hit census")
    ap.add_argument("--root", default=str(CORPUS_DEFAULT))
    ap.add_argument("--json", default=None)
    ap.add_argument("--markdown", default=None)
    ap.add_argument("--max-loop", type=int, default=100)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--max-files", type=int, default=None)
    ap.add_argument("--worker", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--deadline", type=float, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.worker:
        result = runtime_worker(args.worker, args.max_loop, args.deadline)
        print(json.dumps(result))
        return 0
    root = Path(args.root)
    if not root.exists():
        print(f"corpus not found: {root}", file=sys.stderr)
        return 2
    report = census(root, max_loop=args.max_loop, timeout=args.timeout,
                    max_files=args.max_files)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.json}", file=sys.stderr)
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(render_markdown(report), encoding="utf-8")
        print(f"wrote {args.markdown}", file=sys.stderr)
    runtime = report["runtime"]
    print(f"files={report['static']['files']} "
          f"funcs={report['static']['functions']} "
          f"nodes={report['static']['nodes']} "
          f"raw={report['static']['raw']} "
          f"crashes={len(report['static']['crashes'])}")
    print(f"runtime={runtime['files_executed']} "
          f"timeouts={len(runtime['timeouts'])} "
          f"errors={len(runtime['errors'])} "
          f"unknown_load_bearing={len(runtime['unknown_load_bearing'])}")
    for hit in runtime["unknown_load_bearing"][:25]:
        print(f"  unknown {hit['kind']:12s} {hit['name']:28s} "
              f"x{hit['count']} in {len(hit['files'])} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
