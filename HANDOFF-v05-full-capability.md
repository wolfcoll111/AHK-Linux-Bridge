# HANDOFF — v0.5 → full capability (2026-10-21)

Status: **v0.4 is complete and pushed.** Vision is no longer the bottleneck.
The next job is to turn the engine from "language + eyes + input" into a
runtime that can actually run NatroMacro end-to-end on Linux: builtins,
timers, messages, submacro processes, GUI, window/OS bridge, then a live
Natro proof.

Repo: `/home/lordhats/Documents/Default Project/ahk-linux-bridge`
Remote: `https://github.com/wolfcoll111/AHK-Linux-Bridge.git` (`main`;
v0.4 code milestone `c3b6fd1`, handoff docs on top).
Corpus (NOT in repo, stays on this PC): `~/Games/NatroMacro/src` — 150 ×
`.ahk`, NatroMacro v1.1.2.
Environment: KDE Plasma 6.7.5 / Wayland, uinput backend, KWin ScreenShot2,
Pillow + numpy installed. PySide6 is installed; Tkinter is not; `xvfb-run`,
`wl-copy`, `xdotool` are present; Sober 1.8.0 is installed as a Flatpak.

This document is both the handoff and the paste-prompt (§8). Read
`HANDOFF-v03-natro.md` for the language-engine history and
`HANDOFF-v04-vision.md` for the vision implementation and live proofs.

---

## 1. Verified baseline (measured 2026-10-21)

- `python3 -m pytest -q` → **155 passed** (v0.4's 128 + include,
  parser, census and regression tests).
- Natro corpus: **150 files, 0 crashes, 593 functions, 22,125 nodes, 422
  `__raw__` = 1.91%**. This is the post-dangling-else-fix recount; the old
  handoff numbers (524 / 22,176 / 380) were measured before the parser
  correction and are superseded. The raw nodes remain help-text prose,
  Gdip machine-code blobs, memory/DllCall stubs, and join fragments. **Do
  not chase them** unless a census shows one on a load-bearing path.
- Stub census baseline (`docs/CENSUS-v0.5.md`, generated 2026-10-21):
  **150/150 scripts executed**, 0 timeouts, 1 worker-budget stop
  (`StatMonitor.ahk`, partial inventory), **10 unknown load-bearing
  hits**: `IniRead`, `DateDiff`, `OnExit`, no-arg `OSError`, `SplitPath`,
  `String`, `Number`, `ImageSearch`, and the parser misread of
  `Sleep(...)` as a legacy command. Known language gaps (assign targets,
  `for-in`, parser function-body leakage) are reported separately and are
  the next work queue.
- `python3 -m ahk_bridge.cli check` → `detected_backend: uinput`,
  `/dev/uinput` writable, `session_type: wayland`.
- Live capture: `pixels.screenshot_rgb((0,0,32,32))` returns `(32, 32)`,
  non-black; `pixels.screen_size()` → `(0, 0, 1920, 1080)`. mss reads the
  XWayland root black on this session; KWin `org.kde.KWin.ScreenShot2` is
  the live path. Keep mss as the X11 fallback.
- Live vision proof (2026-10-21): Natro's `royaljelly.png` (108×28) at
  screen `(400,300)`; real runtime returned count **1**, list `100,100`
  (global `400,300`). Logs:
  `/tmp/opencode/vision-live-proof.log` and
  `/tmp/opencode/vision-live-proof-phase3.log`; screenshot:
  `/tmp/opencode/vision-live-proof.png`.
- Image search: 500×500 hay / 50×40 needle → **0.53 ms best, 0.57 ms
  median**; pure-Python slice scan 24.1 ms; naive numpy SAD 2.7 s. Natro's
  tightest cadence is `Sleep 50`; the test budget is 5 ms.
- Real `Gdip_BitmapFromScreen` call sites: **127** (129 textual
  occurrences include the library definition and one commented contract
  line). All 127 argument expressions evaluate to region-shaped values.
- Main `natro_macro.ahk` parsed **without includes**: 1,072 auto-section
  statements, 249 functions, 33 `Include` nodes. Those includes are the
  missing libs, helpers and bitmap tables.

### What is already done

- Parser + runtime: control flow, functions/classes, expressions, ternary,
  implicit concatenation, regex, arrays/maps, file/INI basics, try/catch.
- Vision: bitmap handles, base64, screen capture, image search (variation,
  trans, 8 directions, instances, delimiters, AHK error codes).
- Input: uinput (Wayland) + XTest (X11) + dry backend; live F13 proof;
  window activation on the supported paths.
- Live capture: KWin ScreenShot2 on Wayland; mss fallback.

### What is still missing (load-bearing)

0. **`#Include` resolution** — the parser only logs directives. Natro has
   **104** `#Include` lines (33 in the main auto-section), including
   directory-as-include-base (`#Include "%A_ScriptDir%\..\lib"`),
   `%A_ScriptDir%`, unquoted/backslash paths, and include lines inside
   functions. Until includes are expanded, the main script is missing its
   lib functions, JSON/Roblox helpers, and ~2 MB of
   `bitmaps[...] := Gdip_BitmapFromBase64(...)` tables. This blocks the
   census and end-to-end running; do it first.
1. **Built-in variables** — no `A_*` initialization at all. Corpus uses
   `A_Index` 934, `A_LoopField` 88, `A_PtrSize` 74, `A_WorkingDir` 62,
   `A_Args` 57, `A_ScriptDir` 48, `A_Now`/`A_NowUTC`/time parts, `A_TrayMenu`
   20, `A_Clipboard` 14, `A_ScreenWidth/Height/DPI`, `A_KeyDelay`, etc.
2. **Pure builtins** — partial only. Missing/high-use examples:
   `StrGet`/`StrPut`, `Buffer`, `NumGet`/`NumPut`, `FileOpen`, `FileExist`
   (currently always falsy), `FormatTime`, `DateAdd/Diff`, collection
   methods, `ComObject`/`ComCall`, `OnMessage`, `SetTimer` (currently a
   logged no-op), `Hotkey`, `Run`/`RunWait` (logged no-op), `ProcessClose`,
   clipboard, tray.
3. **Timers / messages / multi-process** — `SetTimer` and `OnMessage` are
   stubs; `PostMessage`/`SendMessage` are legacy no-ops. Natro's main script
   and its submacros (`Status`, `PlanterTimers`, `background`) talk over
   Windows messages (`0x5550`–`0x5560`). Without this, the app cannot run.
4. **GUI** — `Gui`, `GuiCtrl`, `MainGui.Add`, `OnEvent`, `Hwnd`, `SetFont`,
   `Value`, etc. are stubs. This is the last load-bearing AHK surface and is
   a toolkit project, not a bugfix.
5. **Window/OS bridge** — `WinGetPos`, `WinGetClientPos`, `WinClose`,
   `WinMove`, `WinSetTransparent`, `ControlGet*`, `Run`, clipboard,
   `DllCall` whitelist, COM/WinHttp, memory model. Some are display-only;
   the census must separate them.
6. **Natro end-to-end proof** — not attempted. Parsing and isolated logic
   are proven; the app has never started with its GUI, timers, submacros and
   main loop.

---

## 2. Definition of "fully capable"

"Fully capable" is **scoped to the real Natro corpus plus documented AHK
surface**, not "all of Windows". A complete Windows emulator is out of
scope. Fully capable means:

1. All 150 Natro scripts parse with 0 crashes (the main script with its
   `#Include` tree expanded); the raw count is not worse than 380, and no
   raw is load-bearing by census.
2. The engine starts Natro's real `natro_macro.ahk` with its GUI, config,
   timers, hotkeys, submacros and main loop on this Linux box.
3. Every builtin/command reached by the auto-section, GUI handlers, timers
   or submacro entry points is either implemented or returns a **documented
   verdict** (display-only, external-service, or Windows-only). No silent
   wrong values; every unsupported call logs once and returns AHK-falsy.
4. Vision, input, window targeting and capture are proven live, not mocked.
5. A 30-minute soak reaches the main loop and does not crash, deadlock,
   leak unbounded memory, or spin at 100% CPU. Report measured loop latency.
6. `python3 -m pytest -q` is green. Every new feature has a test that fails
   without it. The corpus recount stays at 0 crashes.
7. `docs/CAPABILITY-MATRIX.md` lists every subsystem as **Supported /
   Approximated / Documented stub / Impossible here**, with the evidence
   (test, log, or measured number) and the reason. "Unknown" is not allowed.

If a real blocker is found (for example, no stable way to target a native
Wayland Sober window with an HWND-like API), **stop and report the exact
blocker and the best workaround**. Do not fake a capability or call the
extension done because the unit tests pass.

### Capability matrix today

| Area | Status | Notes |
|---|---|---|
| Parser / AST | Supported | 22,176 nodes, 0 crashes, 380 prose/Gdip raws |
| `#Include` loader | Gap | 104 directives logged, not expanded; blocks the app |
| Core language | Supported | loops, if/else, switch, try, functions, classes |
| Expressions | Supported | arithmetic, ternary, concat, regex, arrays/maps |
| `A_*` variables | Gap | not initialized |
| Pure builtins | Partial | string/math basics only; see census |
| File / INI | Partial | INI read/write real; most file commands stubs |
| Timers / hotkeys | Gap | `SetTimer`, `Hotkey` no-ops |
| Messages / IPC | Gap | `OnMessage` stub, `PostMessage` no-op |
| Submacro processes | Gap | `Run` no-op |
| GUI | Gap | `Gui`/`GuiCtrl`/`OnEvent` stubs |
| Window / process ops | Partial | `WinActivate` works on supported paths |
| Clipboard | Gap | `A_Clipboard`, `ClipWait` stubs |
| Vision / capture | Supported | KWin + mss, live-proven |
| Input | Supported | uinput + XTest, live-proven |
| DllCall / COM / memory | Gap | policy + whitelist needed |
| Natro end-to-end | Unproven | this is the finish line |

---

## 3. Working rules (non-negotiable)

- **Verify first.** Run the baseline commands in §6 before editing.
- **Measure, do not guess.** Build the stub census (after `#Include`
  expansion) before ranking work. A statically-imagined gap is not a
  priority until the runtime hits it.
- **One feature per commit.** Regression test in the right test file,
  showing the feature is absent without the change. Commit + push every
  green step; update this document's numbers when they move.
- **No silent stubs.** Unknown builtins/commands log exactly once with the
  name and return AHK-falsy. Never let a Python traceback escape into a
  macro run.
- **No hype.** Report measured numbers. If a surface is impossible on
  Linux, say so and give the verdict. Do not call the extension "working"
  because parsing passes.
- **Do not regress v0.4.** Keep the 128+ tests green, keep the Natro corpus
  at 0 crashes, keep the live capture path working.
- **Dependencies.** numpy is already justified and in the `pixels` extra.
  Any new dependency (GUI toolkit, clipboard helper, etc.) needs measured
  before/after numbers, install size, and a reason in the commit message.
  No OpenCV unless measurements force it.
- **Do not chase the 380 raws.** They are described in §1. Revisit only if
  the census proves one is reached by the main loop.
- **Do not port Gdip_All.ahk's DllCall code.** The native vision layer
  replaces it. Implement only the DllCall signatures that the census shows
  are reached outside the Gdip library.

---

## 4. Roadmap

Work in order. Do not stop after one milestone: after a green commit, update
the numbers and continue to the next milestone unless a genuine blocker or
a product decision requires the user. Every milestone ends with a census
re-run, a full test run, a commit, and a push.

### v0.5 — Headless completeness (immediate)

**Goal:** every non-GUI Natro path runs under `DryBackend` without unknown
stubs or crashes, including timers, messages and submacro processes.

#### 5.0a — `#Include` loader (do this before the census)

This is load-bearing and currently absent. Natro's main script has 33
include directives in its auto-section and 104 corpus-wide; without them
the main script has no `Gdip_All`, `JSON`, `Roblox`, `Walk`, `HashFile`,
`bitmaps` etc. The census would report false stubs and the app cannot run.

Implement an AHK-faithful preprocessing loader before parsing. The AHK v2
docs describe `#Include` as "as though the included file's contents are
physically present at the exact position"; match that behavior:

- Expand `#Include`/`#IncludeAgain` textually, before `parse_script`.
  Preserve source file/line metadata for logs and tests.
- Default relative base = directory of the file containing the directive,
  not the main script or CWD. A directory-form `#Include Dir` changes the
  include base for subsequent includes in the **current file** only; e.g.
  Natro line 25 `#Include "%A_ScriptDir%\..\lib"`, then line 26
  `#Include "Gdip_All.ahk"` resolves under `lib/`. A directory argument
  does **not** glob/include every `.ahk` inside it; it only sets the base.
- Support `%A_ScriptDir%` and the other documented path variables, optional
  quote pairs, unquoted paths, `/` and `\`, `*i` ignore-missing, and
  `#Include <LibName>` (implement or give an explicit verdict).
  Windows paths are case-insensitive; add a Linux case-insensitive fallback.
- `#Include` resolves each file once; `#IncludeAgain` repeats it. Detect
  cycles with a clear error and include lines inside function bodies.
- Do not expand directives inside comments or strings; directives are
  line-based, but they **can be indented** (Natro has real `#Include`
  directives inside functions with leading tabs). Do not use a column-0
  heuristic. **Beware continuation strings:** Natro embeds whole generated
  scripts with `#Include` lines inside `(...)` continuation sections (e.g.
  around lines 7147 and 16962). A naive line-based replace will inject the
  Gdip library into those string literals and corrupt the generated
  submacro. Track continuation/string state and leave those lines verbatim.
- The bitmap includes are huge one-line
  `bitmaps["..."] := Gdip_BitmapFromBase64(...)` assignments. Measure
  expansion/parse time and startup memory. If eager decode is too heavy,
  lazy-decode by name but preserve assignment semantics; never truncate.
- Tests: nested include relative to includer; directory-base override;
  include-once vs `#IncludeAgain`; `%A_ScriptDir%`; backslash/unquoted;
  `*i` missing file; include inside a function; cycle detection; a bitmap
  assignment is present after expansion.
- Sizing (measured): main script 892 KB, `nm_image_assets/**/*.ahk`
  1.7 MB in 25 files, `lib/**/*.ahk` 0.2 MB in 16 files; the expanded main
  script is roughly 2.8 MB of source. Measure parse time and memory instead
  of assuming; cache the expanded text if needed.
- Acceptance: load the real `submacros/natro_macro.ahk`; the expanded
  script contains the lib functions and bitmap globals; parse completes in
  measured time; other files keep their current raw count. Commit the
  loader and tests before building the census.

#### 5.0b — Stub-hit census harness (after includes)

Add `tools/natro_census.py` (or `tools/census.py`; keep it small and
re-runnable). It must do three things:

1. **Static inventory:** parse all 150 files; report files/functions/nodes/
   raws (same baseline as §1); list `FuncCall` and `LegacyCmd` names, and
   subtract names defined in the corpus. Include method-call and GUI-API
   inventory separately (the parser represents `MainGui.Add` as a method
   chain, not a `FuncCall`).
2. **Runtime hit census:** execute each script's auto-section with
   `DryBackend`, a no-op sleep, `max_loop` low (e.g. 1000), and a per-file
   timeout (e.g. 5 s) in a subprocess. Capture `rt.logs` and count
   `stub builtin X`, `stub X()`, `... linux no-op`, `unsupported`, and
   `__raw__` execution. Never let a bad file kill the census.
3. **Report:** JSON + Markdown with counts by name and category, and a
   load-bearing flag. Load-bearing = reachable from the auto-section, a
   hotkey, a timer callback, a GUI event, or a submacro entry point and
   affecting input/vision/state/file/window behavior. Display-only =
   help text, update UI, Discord formatting.

**Census safety:** the harness must not touch the real desktop or the real
Natro tree. Run in a temp cwd, disable/ monkeypatch `WinActivate`,
`PixelSearch`/`screenshot_rgb`, `Gdip_BitmapFromScreen`, `Run`/`RunWait`,
`ProcessClose`, and any file writes (or point all config paths at copies).
Record only `rt.logs` and the parsed AST. A census that focuses windows or
writes the user's settings is a failed census.

Commit the harness and the baseline report before implementing. The
harness is the regression oracle: each fix should reduce a named hit count.

Use runtime hits, not the static list, to decide priority. The static list
is context, not a work order.

#### 5.1 — `A_*` variables and CLI args

Populate built-in variables at runtime init. At minimum cover the corpus
frequencies from §1:

- Paths: `A_ScriptDir`, `A_ScriptName`, `A_ScriptFullPath`, `A_WorkingDir`,
  `A_Temp`.
- Time: `A_Now`, `A_NowUTC`, `A_Year`, `A_MM`, `A_DD`, `A_Hour`, `A_Min`,
  `A_Sec`, `A_MSec`, `A_TickCount` (monotonic ms), `A_YYYY` aliases where
  used.
- Screen: `A_ScreenWidth`, `A_ScreenHeight`, `A_ScreenDPI`.
- Process/app: `A_PtrSize`, `A_Is64bitOS`, `A_AhkPath`, `A_AhkVersion`,
  `A_IsAdmin`, `A_LastError` (0 unless a call sets it).
- Input/clipboard: `A_KeyDelay`, `A_Clipboard` (real read/write lands in
  v0.7; setting the variable must not crash before then).
- Args: `A_Args` from the CLI; add `ahk-bridge run script.ahk -- arg1 arg2`
  or positional args after the script.
- Tray: `A_TrayMenu` as a real minimal object (`Add`, `AddStandard`,
  `Show`, `Default`); wire the menu callbacks to the runtime.
- `SetWorkingDir` must really `chdir`; `A_WorkingDir` must reflect it.

Tests: high-frequency vars, missing vars, `A_Args` ordering, and a
regression that `A_ScriptDir` is the script's directory, not the CWD.

#### 5.2 — Pure builtins

Implement by census rank. The expected load-bearing set includes:

- **Strings:** `StrGet`, `StrPut`, `StrPtr`, `VarSetStrCapacity`,
  `SubStr`, `InStr`, `StrLen`, `StrReplace`, `StrSplit`, `Trim`/`LTrim`/
  `RTrim`, `StrUpper`/`StrLower`, `Format`, `RegExMatch`/`RegExReplace`,
  `IsSet`, `Type`, `Integer`, `Float`, `String`, `Ord`, `Chr`.
- **Collections:** `Array`, `Map`, `Push`, `Pop`, `InsertAt`, `RemoveAt`,
  `Has`, `Delete`, `Clone`, `Length`, `__Enum`, and bracket/property access
  used by Natro (`points[i]`, `map[key]`, `.Length`).
- **Files/INI:** `FileRead`, `FileAppend`, `FileDelete`, `FileCopy`,
  `FileMove`, `FileExist`, `FileGetSize`, `FileGetTime`, `FileSetTime`,
  `FileOpen`, `Loop Files`, `SplitPath`, `IniRead`, `IniWrite`,
  `IniDelete`, `DirCreate`, `DirDelete`.
- **Time:** `FormatTime`, `DateAdd`, `DateDiff`, `SetTimer` (5.3),
  `Sleep` (already), `A_Now` parsing/formatting.
- **Environment/process:** `EnvGet`, `EnvSet`, `ProcessExist`,
  `ProcessClose`, `Run`, `RunWait`, `ExitApp`, `ClipWait` (basic).
- **Math:** extend the existing set with `ASin`, `ACos`, `ATan`, `Tan`,
  `Log`, `Ln`, `Ceil`, `Floor`, `Integer`, `Mod`, `Min`, `Max`, `Round`.
  Preserve AHK coercion (`"00" * 3600 == 0`, not Python repetition).
- **Error semantics:** bad input returns AHK-falsy/empty and logs at most
  once; never raises a Python exception into the script. `Error()` objects
  keep their message.

Use Python oracles (`datetime`, `configparser`, `re`, `pathlib`) in tests.
Do not implement a parser inside a builtin if an existing helper fits.

#### 5.3 — Timers, hotkeys, messages, submacro processes

This is the part that turns the engine into an app:

- **Real `SetTimer`:** positive period = recurring, negative = one-shot,
  `0` = off. Callback by function name; schedule on a monotonic clock;
  callback exceptions are logged and do not kill the loop. Add a test that
  counts fires and proves cancellation.
- **Dynamic `Hotkey`:** register/unregister a hotkey at runtime; reuse the
  existing hotkey/CLI plumbing. `Suspend`/`Pause` at least toggle a real
  flag; `GetKeyState` returns a documented approximation.
- **`OnMessage` / `PostMessage` / `SendMessage`:** a real message registry.
  In-process first: `OnMessage(id, fn[, maxThreads])` stores a handler;
  `PostMessage(id, wParam, lParam, control)` enqueues; `SendMessage` calls
  synchronously and returns a value. Then add a Unix-domain-socket transport
  so `Run`-spawned submacros can post to the parent. Natro's custom IDs
  `0x5550`–`0x5560` and `WM_COPYDATA` are the acceptance targets.
- **`Run` / `RunWait`:** for `.ahk` paths, spawn
  `python -m ahk_bridge.cli run <script> [args]` with the right working
  directory and environment; for URLs/files use `xdg-open`. Track children,
  implement `ProcessClose`, and make `ExitApp` stop only the current
  runtime. Pass the IPC socket/endpoint in an environment variable.
- **`OnExit` / `ExitApp`:** 12 `OnExit` and 39 `ExitApp` uses in the
  corpus. `OnExit(fn)` registers cleanup; run callbacks exactly once on
  `ExitApp`, GUI close, SIGTERM or runtime abort; expose the exit code.
  `OnError(fn)` may log or call the handler.
- **Callback references:** AHK passes function names/objects, not values:
  `OnMessage(0x5550, nm_ForceLabel)`, `SetTimer nm_DismissLabel, -1000`,
  `OnEvent("Click", nm_saveConfig)`. Resolve the raw name to a callable; do
  not `_eval_expr` it to `0`. Anonymous arrows are real (`(*) => ExitApp()`,
  `(ctrl, info) => ...`; 31+ in the corpus): parse/evaluate them to a small
  function-reference object that captures the expression and evaluates it
  in the caller's runtime when invoked.
- **Event loop:** today `run_auto()` returns and the CLI exits. Add a
  runtime `wait()` (or `run(wait=True)`) that stays alive while timers,
  hotkeys, GUI events or submacro processes exist; handle abort keys and
  SIGTERM; add `--exit-after`/`--wait` for tests and examples. Preserve the
  current immediate-exit behavior for plain scripts unless a hook exists.
- **Acceptance:** a test parent script starts a child `.ahk` via `Run`, the
  child posts a custom message, the parent handler sets a variable; a timer
  fires 3 times and stops; Natro's startup `OnMessage` block registers all
  12 handlers; a simulated `nm_setShiftLock` path runs; `OnExit` fires once
  on `ExitApp`.

#### 5.4 — v0.5 acceptance

- `natro_macro.ahk` loads with its full include tree; the lib functions and
  bitmap globals are present; include tests pass.
- Census report shows zero unknown **load-bearing** pure builtins/commands;
  every remaining stub is in the documented display-only/external class.
- Full test suite green; new tests cover each group and fail without the
  fix.
- Corpus still has 0 crashes; the post-fix baseline is 593 funcs / 22,125
  nodes / 422 raw (see §1; the expanded main script is counted separately).
- Commit + push; update this doc's baseline and census numbers.

### v0.6 — GUI compatibility layer

**Goal:** Natro's real GUI constructs run, the main window renders, controls
hold values, and events call the real handlers.

#### 6.1 — Toolkit decision record (do this before code)

Inventory the exact surface from the corpus and write
`docs/GUI-DECISION.md` with measurements:

- Current GUI usage (measured, case-normalized): `Text` 395, `Button` 207,
  `CheckBox` 184, `UpDown` 49, `GroupBox` 47, `Edit` 27, `Picture` 40,
  `DropDownList` 17, `Hotkey` 6, `Tab` 1, `Slider` 1. Some `.Add` calls
  are tray/menu items, not controls. Properties/uses: `Enabled` 800,
  `Value` 253, `Text` 138, `Visible` 23, `SetFont` 12, `Hwnd` 11,
  `Redraw` 8, `Move` 6, `Opt` 4.
  Events: `Click`, `Change`, `Close`; callbacks use `(ctrl, info)` and
  `(*)`.
- Candidates: **PySide6** (installed; Qt widgets; `QT_QPA_PLATFORM=offscreen`
  for CI; signals/slots; tray; pictures; tabs; sizable dependency),
  **GTK4/PyGObject** (`gi` is importable here; verify the GTK4 typelib;
  packaging is less portable),
  **Tkinter** (not installed here), **webview** (not installed).
- Measure: import/startup time, RSS, install footprint, headless test
  viability, Wayland behavior, and event-loop integration with runtime
  timers. Prefer the option that is already installed and testable; do not
  add a 200 MB dependency without recording why.
- If the decision is "not feasible", deliver the verdict and a headless
  config path — but only after the measurement, not as an excuse.

#### 6.2 — API layer

Implement a `src/ahk_bridge/gui.py` compatibility layer (toolkit behind it):

- `Gui()` / `Gui(name)` / default GUI; `Add(type, options, text)` returns a
  control; `MainGui["name"]` lookup; control properties `Value`, `Text`,
  `Enabled`, `Visible`, `Hwnd`, `Opt` get/set. GUI call sites omit middle
  arguments (`Add("Text",, "x")`); preserve empty positional slots for the
  GUI API the same way `Gdip_*` args are preserved.
- Methods: `SetFont`, `Show`, `Hide`, `Destroy`, `Move`, `GetPos`,
  `Redraw`, `Opt`, `OnEvent`.
- Controls: Text, Button, CheckBox, Edit, Picture, DropDownList, UpDown,
  GroupBox, Hotkey, Slider, Tab/`UseTab`; add ListView/TreeView only if the
  census finds them.
- `Picture`: load PNG/base64 into the widget; keep Natro's asset paths
  working; scale/position approximations are acceptable if documented.
- `UpDown`: buddy edit control; `Value` shared.
- `Tab`: `UseTab` routes subsequent controls; `TabCtrl` access works.
- Tray: `A_TrayMenu` / `Menu` with `Add`, `AddStandard`, `Show`, `Default`;
  `TrayTip` logs or uses a desktop notification.
- `Hwnd`: return a stable synthetic handle mapped to the widget; route
  `PostMessage`/`SendMessage` by handle internally. Do not pretend it is a
  real Win32 HWND.
- Event loop: one loop owns Qt; runtime timers and message posts are queued
  onto it. No cross-thread Qt calls. `Sleep` in a callback is allowed but
  must not deadlock the event loop; document the tradeoff.

#### 6.3 — Acceptance

- A test constructs every GUI in the corpus (or the main GUI + representative
  settings/timers/updater GUIs) with `DryBackend`, under
  `QT_QPA_PLATFORM=offscreen`, with no GUI-related unknown stubs.
- Synthetic `Click`/`Change` events call the real Natro handlers and mutate
  state; `Close` runs `GuiClose`; `Destroy` is clean.
- Live proof: launch Natro's main GUI on KDE, screenshot it, click Start/Stop,
  close it; save the screenshot/log under `/tmp/opencode/`.
- Tests fail without `gui.py`; full suite green; commit + push.

### v0.7 — OS bridge, DllCall whitelist, COM/memory

**Goal:** every load-bearing window/file/clipboard/COM/DllCall surface either
works or has a named verdict; no crashes.

- **Window/process ops:** `WinExist`, `WinActivate`, `WinGetPos`,
  `WinGetClientPos`, `WinGetTitle`, `WinClose`, `WinKill`, `WinMove`,
  `WinSetTransparent`, `WinGetText`, `ControlGetPos/Text`,
  `ProcessExist/Close`. Reuse `window_match.py`; add a KWin D-Bus backend
  for native Wayland windows if xdotool cannot see them. A synthetic handle
  registry is acceptable if documented.
- **Clipboard:** `A_Clipboard`, `ClipWait`, read/write via `wl-copy`/
  `wl-paste` (Wayland) or `xclip` (X11); test with a round-trip.
- **`Run` external:** URLs via `xdg-open`; commands via `subprocess` with
  explicit args; never shell-inject script text.
- **Memory model:** `Buffer`, `NumGet`, `NumPut`, `StrGet`, `StrPut`,
  `StrPtr`, `A_PtrSize`; bounds-checked, little-endian, no segfaults. This
  unlocks the remaining Gdip/helper code without porting Windows memory.
- **DllCall policy:** classify all 457 corpus calls. Implement the
  load-bearing pure/timing/window/clipboard ones (e.g.
  `GetSystemTimeAsFileTime`, `QueryPerformanceCounter/Frequency`, `Sleep`,
  `GetSystemMetrics`, `GetCurrentProcessId`, `GetWindowPlacement`,
  `SystemParametersInfo`, `GlobalMemoryStatusEx`, `RtlMoveMemory` on
  `Buffer`, `LoadLibrary`/`GetProcAddress` as fake handles, crypto via
  `hashlib`). Everything else logs one named stub with its signature and
  returns falsy. Do not build a general Windows API emulator.
- **COM/WinHttp:** `ComObject("WinHttp.WinHttpRequest.5.1")` mapped to a
  `urllib`/`http.client` object with `Open`, `SetRequestHeader`, `Send`,
  `WaitForResponse`, `Status`, `ResponseText`; `ComCall`/`ObjRelease`
  minimal/no-op. Mock the network in tests; optionally one real Discord
  webhook dry-run if the user provides a URL.
- **Acceptance:** DllCall/COM census has no unknown load-bearing hit; live
  window activation + clipboard proofs; `HashFile`/`DurationFromSeconds`
  helper paths execute; no crash.

### v0.8 — End-to-end Natro proof

**Goal:** run the real app, not just its functions.

- Build a controlled fixture: a PySide6 window that mimics the Roblox
  client geometry and displays Natro screenshots/needles at known
  coordinates. Give it a stable title/class and make the window matcher find
  it. This exercises capture → search → move/click without needing a game
  account.
- Launch the real `submacros/natro_macro.ahk` (and its submacros) via
  `ahk-bridge run --wait`, with the GUI extra. Verify: config loads/saves,
  GUI opens, Start starts the main loop, timers fire, submacros launch,
  `OnMessage` paths exchange `0x5550`–`0x5560`, vision finds fixture
  needles, input reaches the fixture (DryBackend log or live uinput to a
  harmless target).
- If Sober 1.8.0 can be launched and a real Roblox session is already
  available, repeat with Sober. Do not automate account login. If the
  native Wayland window cannot be targeted (no HWND), record the blocker,
  test the XWayland/workaround path, and document exactly what is required.
- Soak: 30 minutes; report crash count, memory growth, CPU, and
  capture→search→act latency (p50/p95). Target: no crash, no unbounded
  growth, loop under Natro's 50 ms cadence budget where applicable.
- Evidence: logs + screenshots under `/tmp/opencode/`, a `PROOF-v0.8.md`
  with the exact commands and observed output.
- If a load-bearing feature remains impossible (e.g. native-Wayland HWND
  semantics), stop and report the blocker + workaround. Do not call it
  fully capable.

### v1.0 — Capability freeze / release

- Write `docs/CAPABILITY-MATRIX.md` with every subsystem and evidence.
- Update README, INSTALL, ARCHITECTURE, and this handoff with the final
  numbers.
- Package extras cleanly (`pixels`, `uinput`, `x11`, `portal`, `gui`),
  verify a clean install in a venv, and run the suite from that venv.
- CI/lint/type checks if practical; keep the test suite fast.
- Tag the release. State plainly what works, what is approximated, what is
  a stub, and what is impossible on Linux. No "first AutoHotkey" claims
  beyond the evidence.

---

## 5. Measured inventory (targets, not orders)

### 5.1 GUI / app surface (from `grep -rhoP` over the corpus)

- `MainGui.Add` 674; `.OnEvent` 512 total (Click 400, Change 88, Close 21,
  Escape 3); `TimersGui.Add` 86; `MainGui.SetFont` 67; `AFBGui.Add` 52;
  `MainGui.Hwnd` 40; `AddGui.Add` 39.
- Control types (case-normalized): Text 395, Button 207, CheckBox 184,
  UpDown 49, GroupBox 47, Edit 27, Picture 40, DropDownList 17, Hotkey 6,
  Tab 1, Slider 1. Some `.Add` calls are tray/menu items, not controls.
- Properties: `Enabled` 800, `Value` 253, `Text` 138, `Visible` 23,
  `SetFont` 12, `Hwnd` 11, `Redraw` 8, `Move` 6, `Opt` 4.
- The GUI is not optional for Natro: it is how the user configures and
  starts the macro. Do not ship a headless-only verdict without saying
  exactly what the user loses.

### 5.2 Built-in variables (corpus counts)

`A_Index` 934, `A_LoopField` 88, `A_PtrSize` 74, `A_WorkingDir` 62,
`A_Args` 57, `A_ScriptDir` 48, `A_Min` 21, `A_TrayMenu` 20, `A_Space` 17,
`A_Sec` 17, `A_NowUTC` 17, `A_Clipboard` 14, `A_Tab` 9, `A_ScreenWidth` 8,
`A_ScreenHeight` 8, `A_KeyDelay` 8, `A_Now` 7, `A_AhkVersion` 7,
`A_AhkPath` 7, `A_Hour` 6, `A_ScreenDPI` 5, `A_Temp` 3, `A_IsAdmin` 3,
`A_Is64bitOS` 3, `A_ScriptHwnd` 2, `A_LineNumber` 2, `A_IsPaused` 2,
`A_MSec` 1, `A_MM` 1, `A_DD` 1, `A_ScriptFullPath` 1.

### 5.3 DllCall / COM (outside the replaced Gdip library)

Top signatures: `GetSystemTimeAsFileTime` 41, `DeleteObject` 25, `Sleep`
15, `SelectObject` 12, `ole32\CLSIDFromString` 8, `GetSystemMetrics` 8,
`GetCurrentProcessId` 8, `SendMessage` 5, `RtlMoveMemory` 5,
`QueryPerformanceCounter` 5, `GlobalLock`/`GlobalUnlock`/`GlobalSize`/
`GlobalAlloc`/`GlobalFree` 5 each, `GetWindowPlacement` 5, `GetObject` 5,
`CreateCompatibleDC`/`DeleteDC` 5, `LoadLibrary`/`GetProcAddress` 3,
`VirtualProtect` 3, `SystemParametersInfo` 3, `CopyImage` 3,
`CreateDIBSection` 3, `WideCharToMultiByte` 2, `MultiByteToWideChar` 2,
clipboard/`OpenClipboard` 2, `QueryPerformanceFrequency` 2,
`GlobalMemoryStatusEx` 2, crypto (`CryptAcquireContextW`, `CryptHashData`,
`CryptGetHashParam`, `CryptDestroyHash`, `CryptReleaseContext`) in
`lib/HashFile.ahk`.
COM: `ComObject` 18, `ComCall` 27, `ObjRelease` 21; `WinHttp` request
object used by `lib/Discord.ahk` (`wr.Open`, `wr.Send`, `wr.WaitForResponse`,
`ResponseText`, `SetRequestHeader`).

### 5.4 Legacy commands (corpus counts)

`PostMessage` 66, `Hotkey` 24, `SendMessage` 16, `Run` 15, `ProcessClose`
13, `SplitPath` 7, `SetTimer` 6, `WinClose` 6, `MouseClickDrag` 5,
`MouseGetPos` 4, `WinGetClientPos` 3, `WinSetTransparent` 3, `RunWait` 2,
`FileDelete` 2, `MonitorGetWorkArea` 2, `DirCreate` 2, `Pause` 2,
`WinGetPos` 1, `WinKill` 1, `WinMinimize` 1, `Shutdown` 1,
`FileAppend` 1, `RegWrite`/`RegDelete` 1 each.

### 5.5 Do not chase

- The 380 `__raw__`: help-text prose, Gdip machine-code data blobs,
  multi-line `NumPut(`/`DllCall(` memory pokes, stray braces, 2–3 join
  fragments. They have no execution value unless the census proves a
  load-bearing hit.
- Full Windows GDI+ / `Gdip_All.ahk` DllCall port. Native vision replaces
  the observed Gdip surface.
- A general Windows API/COM emulator. Implement the load-bearing whitelist,
  name the rest, move on.

---

## 6. Exact commands

```bash
cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge"
git status --short                 # expect clean
python3 -m pytest -q               # expect 128 passed at handoff
python3 -m ahk_bridge.cli check    # expect detected_backend: uinput
```

Live capture sanity:

```bash
python3 - <<'PY'
from ahk_bridge import pixels as px
raw, w, h = px.screenshot_rgb((0, 0, 32, 32))
print((w, h), "nonblack", any(raw), "screen", px.screen_size())
PY
# expect (32, 32) nonblack True screen (0, 0, 1920, 1080)
```

Corpus recount: reuse the snippet in `HANDOFF-v03-natro.md` §5 (it walks
`auto_section`, function bodies, `cases`, `Seq`, `Try.else_body`). Expected:

```text
files=150 funcs=524 nodes=22176 raw=380 (1.71%) crashes=0
```

Include-gap baseline (main script, unexpanded):

```bash
python3 - <<'PY'
from ahk_bridge.parser import parse_script
p = "/home/lordhats/Games/NatroMacro/src/submacros/natro_macro.ahk"
sc = parse_script(open(p, encoding="utf-8-sig").read())
print(len(sc.auto_section), len(sc.functions),
      sum(type(x).__name__ == "Include" for x in sc.auto_section))
PY
# expect: 1072 249 33
```

Vision proof (only if you need to re-prove after touching capture):

```bash
python3 -m ahk_bridge.cli run /tmp/opencode/vision-proof.ahk --backend dry
python3 -m ahk_bridge.cli run /tmp/opencode/vision-proof-phase3.ahk --backend dry
# both: MsgBox: 1 / MsgBox: 100,100
```

GUI headless test pattern (once the GUI extra exists):

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_gui.py
```

---

## 7. Known traps (from v0.3/v0.4)

- **mss is black on this Wayland session.** Keep KWin ScreenShot2 first;
  mss only as X11 fallback. Do not "fix" capture by switching to mss.
- **`pixels.screenshot_rgb` clamps regions.** Fully off-screen is a 1×1
  black frame; never throw from a macro.
- **`Gdip_BitmapFromScreen` accepts 4+ pipe parts** because the AHK wrapper
  ignores extras; one Natro call has a trailing `|`. Empty first four values
  are rejected.
- **`Screen:=` / `Raster:=` are named args**, not script variables. Do not
  let them leak into `vars`.
- **The test suite is fast.** Keep it that way; no live desktop calls in
  unit tests. Use synthetic fixtures and monkeypatch capture.
- **uinput delivery has a compositor enumeration delay.** The backend
  already waits for the device; do not shorten that blindly.
- **`pkill` footgun:** never put `pkill` and a literal `xev` path in the
  same `bash -c` line; it can kill its own shell.
- **Parser performance:** avoid nested ambiguous regexes; one v0.3 attempt
  took 3.4 s on a 73-char line. Keep the 150-file parse fast.

---

## 8. Paste-prompt for the next agent

Copy the block below into the fresh chat. It is self-contained; the full
detail is in this file.

```text
You are taking over AHK-Linux-Bridge in
/home/lordhats/Documents/Default Project/ahk-linux-bridge (remote
github.com/wolfcoll111/AHK-Linux-Bridge, branch main; v0.4 code milestone
c3b6fd1, handoff docs on top). Read HANDOFF-v05-full-capability.md in that
repo first, and keep
HANDOFF-v03-natro.md + HANDOFF-v04-vision.md nearby for history. The test
corpus is ~/Games/NatroMacro/src (150 .ahk files, NatroMacro v1.1.2, not in
the repo). Environment: KDE Plasma Wayland, uinput, KWin ScreenShot2,
Pillow+numpy; PySide6 installed, Tkinter not; xvfb-run/wl-copy/xdotool
present; Sober 1.8.0 installed.

MISSION: take the bridge from "language + vision + input" to a runtime that
runs NatroMacro end-to-end on Linux, with every load-bearing AHK surface
implemented or given a documented verdict. Work the roadmap in order and
DO NOT STOP after v0.5 just because tests pass. After each green commit,
update the handoff numbers and continue to the next milestone unless a real
blocker or a product decision requires the user.

VERIFY FIRST (before editing):
  cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge"
  git status --short                  # must be clean
  python3 -m pytest -q                # must be 128 passed
  python3 -m ahk_bridge.cli check     # must detect uinput
  python3 -c "from ahk_bridge import pixels as px; r,w,h=px.screenshot_rgb((0,0,32,32)); print((w,h), any(r), px.screen_size())"
  # must print (32, 32) True (0, 0, 1920, 1080)
  # corpus recount: 150 files / 524 funcs / 22176 nodes / 380 raw (1.71%) / 0 crashes
  # known blocker: #Include is logged only; 104 directives / 33 in the
  # main auto-section, so natro_macro.ahk is missing all libs and bitmaps.
If any baseline is different, investigate before changing code. The live
vision logs are /tmp/opencode/vision-live-proof.log and
/tmp/opencode/vision-live-proof-phase3.log (count 1, list 100,100).

DEFINITION OF FULLY CAPABLE (scoped to the Natro corpus, not all Windows):
1) all 150 scripts parse with 0 crashes (main script include tree
   expanded) and no load-bearing __raw__;
2) Natro's real natro_macro.ahk starts with its GUI, config, timers,
   hotkeys, submacros and main loop on this box;
3) every builtin/command reached from the auto-section, GUI handlers,
   timers or submacros is implemented or logs one documented verdict
   (display-only / external-service / Windows-only) and returns AHK-falsy;
4) vision, input, window targeting and capture are proven live;
5) a 30-minute soak reaches the main loop with no crash, deadlock, unbounded
   memory growth or 100% CPU spin, with measured latency;
6) pytest is green and each new feature has a test that fails without it;
7) docs/CAPABILITY-MATRIX.md has no "unknown" rows; every row has status,
   evidence and reason.

ROADMAP (full detail in HANDOFF-v05-full-capability.md):
- v0.5 headless completeness: FIRST implement the #Include loader (104
  directives; textual expansion, per-file relative/dir base, once/again,
  %A_ScriptDir%, backslashes, cycles, includes inside functions, huge bitmap
  assignments; directives can be indented and appear inside functions, so
  do NOT use a column-0 heuristic; do NOT expand #Include text inside
  continuation strings, e.g. Natro's generated-script blocks). THEN build
  tools/natro_census.py (static + DryBackend
  runtime stub hits + load-bearing triage; sandbox it with a temp cwd and no
  WinActivate/capture/Run/file writes), then A_* variables and CLI A_Args,
  pure builtins (strings/collections/file/INI/time/env), real SetTimer,
  Hotkey, OnMessage/PostMessage/SendMessage, OnExit/ExitApp, callback
  references + `(*) => ...` arrows, Run/RunWait submacro processes, and a
  runtime wait/event loop. Acceptance: natro_macro.ahk loads with its full
  include tree; no unknown load-bearing pure builtins; a parent/child AHK
  message test; timer test; Natro's 12 OnMessage handlers register; corpus
  unchanged.
- v0.6 GUI: write docs/GUI-DECISION.md with measured toolkit comparison
  (PySide6 is installed; Tk is not; PyGObject is importable; webview not).
  Then implement a Gui/GuiCtrl compatibility layer: Add, SetFont, Show/Hide/
  Destroy, Move/GetPos, Value/Text/Enabled/Visible/Hwnd/Opt, OnEvent
  (Click/Change/Close), Text/Button/CheckBox/Edit/Picture/DropDownList/
  UpDown/GroupBox/Hotkey/Slider/Tab, Tab.UseTab, A_TrayMenu, Hwnd-to-widget
  mapping. Headless tests under QT_QPA_PLATFORM=offscreen; live Natro main
  GUI screenshot + Start/Stop click proof. No GUI-related unknown stubs on
  construction.
- v0.7 OS bridge: window/process ops (WinExist/Activate/GetPos/
  GetClientPos/Title/Close/Move/Transparent/Text, ControlGet*, Process*),
  clipboard via wl-copy/wl-paste or xclip, Run URLs/commands, a bounds-
  checked Buffer/NumGet/NumPut/StrGet/StrPut/StrPtr model, a DllCall
  whitelist for load-bearing signatures, and minimal ComObject
  (WinHttp -> urllib) / ComCall / ObjRelease. Everything else logs one
  named stub, never crashes. Live window + clipboard proof.
- v0.8 end-to-end: controlled PySide6 "Roblox-like" fixture window with
  Natro screenshots at known coordinates; run the real natro_macro.ahk +
  submacros with the GUI extra; verify config, Start, timers, 0x5550-0x5560
  messages, vision, input; 30-minute soak with p50/p95 latency, memory and
  CPU. If Sober/Roblox is usable, repeat; do not automate login. Record any
  native-Wayland HWND blocker and the workaround honestly.
- v1.0: capability matrix, docs, extras packaging, clean-venv install, tag.

MEASURED TARGETS FROM THE CORPUS (use the census, not this list alone):
A_* vars: A_Index 934, A_LoopField 88, A_PtrSize 74, A_WorkingDir 62,
A_Args 57, A_ScriptDir 48, A_TrayMenu 20, A_Clipboard 14, A_ScreenWidth 8,
A_KeyDelay 8, A_Now 7, A_AhkPath 7, A_Hour 6; GUI Add counts (normalized):
Text 395, Button 207, CheckBox 184, UpDown 49, GroupBox 47, Edit 27,
Picture 40, DropDownList 17; properties: Enabled 800, Value 253, Text 138,
Visible 23;
legacy/commands: PostMessage 66, Hotkey 24, SendMessage 16, Run 15,
ProcessClose 13, SplitPath 7, SetTimer 6, WinClose 6; DllCall outside Gdip:
GetSystemTimeAsFileTime 41, DeleteObject 25, Sleep 15, SelectObject 12,
GetSystemMetrics 8, QueryPerformanceCounter 5, GlobalMemoryStatusEx 2,
crypto hash in lib/HashFile.ahk; COM: ComObject 18, ComCall 27,
ObjRelease 21.

RULES: no hype; verify by execution (oracles, logs, live proofs), not
assertion. One feature per commit with a regression test that fails without
it; commit+push every green step; update the handoff numbers when they move.
No silent stubs: log once and return AHK-falsy. Do not regress vision/input/
capture. Do not chase the 380 prose/Gdip __raw__ or port Gdip_All.ahk's
DllCall code. New deps need measured before/after numbers and install-size
justification. Keep the test suite fast (no live desktop calls in unit
tests). If a load-bearing surface is genuinely impossible on Linux, stop and
report the exact blocker + workaround; do not fake it.

START NOW: baseline verification, then implement the #Include loader with
tests and commit it, then build the census harness and commit it before
touching builtins. Work through v0.5 and continue into v0.6, v0.7, v0.8 and
v1.0 in order until the capability matrix is complete.
```
