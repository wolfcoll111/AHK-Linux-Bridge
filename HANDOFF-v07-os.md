# HANDOFF — v0.7 OS bridge complete → v0.8 live Natro

Status: **v0.7 (Linux OS bridge) is complete and committed**
(`196a398`). Window/control queries, clipboard, bounded buffers and the
whitelisted `DllCall` surface are real; unsupported Windows ABI calls are
explicitly logged instead of silently returning a plausible value. The
next milestone is v0.8: start the real Natro tree with its config, GUI,
timers, submacros and main loop, then soak and measure it.

Repo: `/home/lordhats/Documents/Default Project/ahk-linux-bridge`
Remote: `https://github.com/wolfcoll111/AHK-Linux-Bridge.git` (`main`).
Corpus stays outside the repo at `~/Games/NatroMacro/src` (NatroMacro
v1.1.2, 150 `.ahk` files). PySide6 6.12.0 is installed here; it remains
an optional `gui` extra and is imported lazily.

## 1. Verified v0.7 baseline (measured 2026-10-23)

- `QT_QPA_PLATFORM=offscreen python -m pytest -q` → **252 passed**
  (~6.2 s). No desktop, clipboard, window or vision call is live in the
  unit tests.
- **Real main GUI:** the Natro source's own `MainGui` block still builds
  offscreen with **805 controls**, 9 tab pages and `StartButton` enabled.
  Screenshot: `docs/screenshots/v06-main-gui.png`.
- **Census** (`docs/CENSUS-v0.7.md`, 2026-10-23):
  **150 files, 590 functions, 23,501 nodes, 409 raw (1.74%), 0 parse
  crashes; 150/150 runtime, 0 timeouts, 0 worker-deadline stops, 0 load
  errors, 0 unknown load-bearing hits.**
  Verdict totals: **windows-only 45, language-gap 17, setting-noop 8,
  cross-file 5, parser-raw 3, external-service 2** (64 known gaps after
  benign rows are filtered).
- Baseline before v0.7 was 229 tests and 35 known gaps. The rise to 64
  is not a runtime regression: DllCall/GDI+/COM exports that previously
  disappeared into a single stub are now individually visible, and
  `DllCall` expression leaks are separated from real Windows calls.
- v0.5/v0.6 surfaces remain intact: includes, hotkeys/hotstrings,
  timers, OnMessage/IPC, Run/RunWait, ProcessClose, ExitApp/OnExit,
  vision/input/capture, PySide6 GUI/control behavior and the sandboxed
  census.

## 2. What landed in v0.7

| Commit | Surface |
|---|---|
| `757b3c8` | Real system clipboard: `wl-paste`/`wl-copy`, then `xclip`, then `xsel`; one-time failure logs and an `AHK_BRIDGE_CENSUS=1` guard. |
| `a5ecadc` | Own-Gui registry plus external X11/XWayland window lookup via `xdotool`/`xwininfo`/`xprop`; `WinExist`, titles, frame/client positions, close/kill/move/transparency, `ControlGet*`, PIDs/process names. |
| `29324ae` | Bounded `AhkBuffer`, synthetic pointers, `NumGet`/`NumPut`, `StrGet`/`StrPut`/`StrPtr`; whitelisted `DllCall` for timing, sleep, process identity, system metrics, locale/date/text and selected structure writes. |
| `f2e641c` | AHK `TargetError` for missing windows/controls. This fixes Natro's `GetRobloxClientPos()` contract: a missing Roblox window makes the helper return `0`, not a false success with a 0×0 client rect. |
| `3c8687c` | Legacy `ControlGetPos , &y, , &h, ctrl` parser semantics: the space before the command comma omits the X output. Verified against real AutoHotkey v2 under Wine. |
| `25fec63`, `196a398` | Census taxonomy: unmodeled DllCall exports stay visible; Buffer/member expressions leaked into auto-sections are `parser-raw`, not fake Windows gaps; genuine function pointers are a separate `windows-only` gap. |
| `8ca6559` | Arithmetic calls keep raw source arguments, so `StrPtr(base64)` is not re-parsed as a comparison expression. This removed the census deadline stop. |

Window targeting rules:

- Own Gui windows use the in-process registry and are authoritative.
- External windows use X11/XWayland tools and report `TargetError` when
  absent.
- Native Wayland surfaces have no foreign HWND. A compositor/portal
  route is not implemented; the bridge reports the limitation and never
  invents a handle.

## 3. Exact limitations (documented, not silent)

1. **Native Wayland window handles.** XWayland windows can be targeted;
   native Wayland surfaces cannot be treated as Windows HWNDs. The
   actionable workaround is XWayland or compositor-specific/portal data.
   The current implementation logs the limitation and returns falsy.
2. **COM / WinRT / WinHttp.** `ComValue`, `ComObjGet`, `ComCall`,
   `ObjRelease`, WinRT activation and WinHTTP have no Linux-native
   reproduction. They are logged stubs with `windows-only` or
   `external-service` verdicts. Natro's WMI OS-version query is therefore
   a known gap, not a success.
3. **General Windows ABI.** `DllCall` is a whitelist, not a PE loader.
   Structures are written only at the offsets used by the supported
   calls. GDI+ drawing/image-lock calls are display-only no-ops; the
   Linux vision layer replaces image processing and `Gdip_All.ahk` is
   deliberately not ported.
4. **Function-pointer/machine-code calls.** Calls such as
   `DllCall(PixelateBitmap.Ptr, ...)` cannot execute Windows x64 machine
   code here. Any reachable function pointer is logged as
   `DllCall function pointer …` and returns 0. Body-leak expressions such
   as an undefined `PixelateBitmap.Ptr` are separately logged as
   `DllCall expression …` and classified `parser-raw`.
5. **External window tools.** X11/XWayland queries need `xdotool`,
   `xwininfo` and `xprop` installed. Missing tools produce a logged
   inability to query, not fabricated geometry.

## 4. Reproduction

```bash
cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge"
QT_QPA_PLATFORM=offscreen python -m pytest -q
QT_QPA_PLATFORM=offscreen python tools/natro_census.py \
  --json /tmp/opencode/census-v07.json \
  --markdown /tmp/opencode/CENSUS-v07.md
```

Real-GUI probe (temporary, outside the repo):

```bash
cd /tmp/opencode
QT_QPA_PLATFORM=offscreen python natro_gui_probe.py
```

The probe still reports missing personal-config artifacts: `pre 107
IndexError` (`priorityListNumeric`), `KeyError: '0'` for the
Blender/Shrine config, and missing bitmap keys `babylovegui`,
`kingbeetleamu`, `supremeshellamu`. These are config-data gaps, not GUI
construction failures; v0.8 must resolve them with a real config.

## 5. Next move: v0.8 live Natro proof

1. Create a disposable copy of the complete Natro tree (source **and**
   config/settings/assets) under `/tmp/opencode`; never run the live
   macro against the real tree.
2. Start `natro_macro.ahk` with its own config, GUI, timers, hotkeys,
   submacro definitions, image assets and main loop. Resolve startup
   errors in this order: missing config keys → include paths → parser
   body leaks → submacro/IPC handoff.
3. Do not fake Roblox: with no game window, startup should reach the UI
   and report the missing target, not crash. If a real/Roblox window is
   available, use the XWayland path.
4. Run a soak (target at least 10–15 minutes of idle/steady-state macro)
   and record latency, CPU, RSS and timer drift before/after; include the
   exact command and environment.
5. Build the v1.0 capability matrix from evidence: window/control,
   clipboard, memory/DllCall, COM/WinHttp, Gdip/vision, timers, IPC and
   input. No `unknown` rows.

Commit each green step with a regression test; keep the census
offscreen/sandboxed and do not chase the 410 prose/`Gdip_All.ahk`
`__raw__` nodes.

## 6. Paste prompt for the next session

> Continue AHK-Linux-Bridge from v0.7 to v1.0. v0.7 is committed at
> `196a398`; 252 tests pass in ~6 s; the real Natro main GUI builds
> 805 controls offscreen; census is 150/150 files, 0 parse crashes,
> 0 timeouts, 0 deadline stops, 0 unknown load-bearing hits. Next: v0.8
> real Natro startup with a disposable full tree and its config, then a
> measured soak. One feature per commit with a regression test. Preserve
> the documented limitations: native Wayland has no foreign HWND, COM/
> WinRT/WinHttp are external gaps, DllCall is a whitelist and GDI+ is
> display-only. Never fake a window/COM result. Then produce the v1.0
> capability matrix with no unknown rows.
