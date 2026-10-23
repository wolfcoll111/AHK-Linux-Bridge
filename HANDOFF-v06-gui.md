# HANDOFF — v0.6 GUI complete → v0.7 OS bridge

Status: **v0.6 (PySide6 GUI compatibility) is complete and committed**
(`3ba0aeb`). Real Natro `natro_macro.ahk` now constructs its own main GUI
from source, offscreen, including tabs, controls, values and callbacks.
The next milestone is the v0.7 OS/window bridge, then v0.8 live Natro
proof and the v1.0 capability matrix.

Repo: `/home/lordhats/Documents/Default Project/ahk-linux-bridge`
Remote: `https://github.com/wolfcoll111/AHK-Linux-Bridge.git` (`main`).
Corpus stays outside the repo at `~/Games/NatroMacro/src` (NatroMacro
v1.1.2, 150 `.ahk` files). PySide6 6.12.0 is installed here; it remains
an optional `gui` extra and is imported lazily.

## 1. Verified v0.6 baseline (measured 2026-10-23)

- `QT_QPA_PLATFORM=offscreen python -m pytest -q` → **229 passed**
  (~8.0 s). GUI tests are skipped automatically if PySide6 is absent.
- **Real main GUI:** the Natro source's own `MainGui` block (lines
  ~2557–3573) completed offscreen with **805 controls**:
  290 Text, 167 CheckBox, 136 Button, 94 DDL, 46 UpDown, 37 GroupBox,
  18 Picture, 15 Edit, 1 Tab, 1 Slider. `StartButton` finishes enabled,
  the tab control has all **9** pages, and the Gather page is populated.
- Screenshot proof: `docs/screenshots/v06-main-gui.png` (490×275,
  Gather tab selected, the real Natro layout/text/buttons).
- Probe is sandboxed under `/tmp/opencode/natro-gui-sandbox` and
  `/tmp/opencode/natro_gui_probe.py`; it never writes to the real Natro
  tree. The probe deliberately does not supply Natro's personal settings,
  so its remaining logs are missing-config artifacts:
  * `hBitmapsSB[0]` because the config has no Blender/Shrine selection;
  * loop bodies that expect a selected item (Blender/Shrine Add controls);
  * the optional Advanced tab is not built (`BuffDetectReset=0`).
  These are not GUI-construction failures; with a real config the same
  calls have valid keys. They must be resolved as part of v0.8's live
  config proof, not hidden in the GUI layer.
- GUI behavior covered by `tests/test_gui.py`: construction/Show/Submit,
  named and arrow callbacks, chained `Add(...).OnEvent(...)`, Tab pages,
  `.Section`, `xs`/`ys`, `x+`/`y+`, negative absolute coordinates,
  dynamic names, DDL Add/Text/Value/Change, Close/Destroy, Picture
  placeholders, visible-GUI event pumping, callback error isolation, and
  headless fallback when PySide6 is unavailable.
- Parser/runtime fixes required by the real GUI and now regression-tested:
  empty positional arguments, `a.b().c()` link-by-link evaluation,
  generalized property/index/dynamic assignment, `clicked := 1` not
  matching the `Click` command, short-circuit `&&`/`||`, nested
  object/array literals (`slotMove`), and `global Name := value`
  initializers.
- Census (`docs/CENSUS-v0.6.md`, 2026-10-23):
  **150 files, 590 functions, 23,501 nodes, 409 raw (1.74%), 0 parse
  crashes; 150/150 runtime, 0 timeouts, 0 worker stops, 0 load errors,
  0 unknown load-bearing hits.** Known verdicts: 17 language-gap,
  12 windows-only, 8 setting-noop, 5 cross-file, 1 parser-raw. The census
  forces `QT_QPA_PLATFORM=offscreen` in every worker, so it cannot open
  real windows. Many `bitmaps[...]` language-gap hits come from running
  each corpus file standalone; the expanded main script has the live
  containers.
- v0.5's headless surface remains intact: includes, timers, dynamic
  hotkeys, OnMessage/IPC, Run/RunWait, ProcessClose, ExitApp/OnExit,
  vision/input/capture, and the sandboxed census.

## 2. What is still missing (load-bearing)

1. **Window/OS bridge (v0.7)** — `WinGetPos`, `WinGetClientPos`,
   `WinClose`, `WinMove`, `WinSetTransparent`, `ControlGet*`, clipboard,
   a bounds-checked DllCall/memory model, and COM/WinHttp decisions.
   On Wayland, native window handles are compositor-controlled; the
   documented workaround is to target the KWin/XWayland window or use
   compositor portal data, and to report display-only calls as such.
   Never fake an HWND.
2. **Live Natro startup (v0.8)** — start the real tree with its config,
   GUI, timers, submacro processes and main loop, reach a steady state,
   then run a soak and record latency/CPU/memory. The probe already
   proves GUI construction; startup still needs the config/path and
   submacro/IPC pieces exercised together.
3. **Capability matrix (v1.0)** — every subsystem gets Supported /
   Approximated / Documented stub / Impossible here with evidence and a
   reason. No `unknown` rows.
4. **Census follow-up** — cross-file containers (`bitmaps[...]`,
   `buff_*`, `Shrine[...]`) should be measured with the expanded main
   script rather than per-file standalone so the remaining language-gap
   list reflects real load-bearing gaps.

## 3. Reproduction

```bash
cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge"
QT_QPA_PLATFORM=offscreen python -m pytest -q
QT_QPA_PLATFORM=offscreen python tools/natro_census.py \
  --json /tmp/opencode/census-v06.json \
  --markdown /tmp/opencode/CENSUS-v06.md
```

Real-GUI probe (sandbox paths are temporary, not repo artifacts):

```bash
cd /tmp/opencode
QT_QPA_PLATFORM=offscreen python natro_gui_probe.py
```

## 4. Paste prompt for the next session

> Continue AHK-Linux-Bridge from v0.6 to v1.0. v0.5/v0.6 are committed;
> 229 tests pass; the real Natro main GUI builds 805 controls offscreen
> (`docs/screenshots/v06-main-gui.png`); census is 0 crashes, 0 unknown
> load-bearing. Work one feature per commit with a regression test,
> keep the census offscreen and sandboxed, and do not port Gdip/Windows
> DllCall internals. Next: v0.7 OS bridge (window position/close/move,
> control queries, clipboard, bounded memory/DllCall verdicts), then the
> real Natro startup/soak proof (v0.8), then the capability matrix
> (v1.0). Report exact blockers instead of stubs.
