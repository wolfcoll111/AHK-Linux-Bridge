# HANDOFF — v1.0 release (language/OS completion)

Status: **v1.0 is complete and evidenced on 2026-10-27.** Version
**1.0.0**. The real Natro main script still starts from a disposable copy
with **0 startup errors** and runs 600 s in steady state, now with the
v1.0 language/OS surface: window waits/list, class statics, parameter
defaults, `Bind`, function scope/statics/nested closures, Array and Map
property semantics, case-insensitive variables/paths, and file-loop v2
specials.

This remains a Linux runtime proof, not a live Roblox or desktop-session
proof: vision/window effects were captured, process spawning was
disabled, and the GUI was offscreen. The documented Windows boundaries
are unchanged and are never faked.

## 1. Verified v1.0 evidence

- `QT_QPA_PLATFORM=offscreen python -m pytest -q` → **345 passed**
  (7.01 s). No test performs a live desktop, clipboard, window or vision
  call.
- **Real main startup** (sandboxed disposable tree, soak harness):
  **33 include files, 1,486 auto statements, 621 functions**; parse
  **2.582 s**, startup **6.672 s**, **0 startup errors**; **813
  controls**, **9 tab pages**, `StartButton` enabled; **843 variables**,
  **101 logs**, `patternlist` **12** (the nested-closure fix now
  populates it).
- **600 s steady-state soak** (`soak_s` **600.021**): **300 timer
  fires** / **300 timer events**, **0 timer callback errors**, **1 new
  log** (`stub builtin nm_nightinterrupt()`) and no startup errors. CPU
  **7.15 s** over the soak (**1.191 % of one core**); RSS **166.5 MB**
  at start, **168.2 MB** at end, peak **168.5 MB**.
- **Sandboxed census** (`docs/CENSUS-v1.0.md`): **150 files, 671
  functions, 21,127 nodes, 28 `__raw__` (0.13 %), 0 parse crashes;
  150/150 runtime, 0 timeouts, 0 load errors, 0 unknown load-bearing
  hits; known gaps 47** (windows-only 38, language-gap 7, setting-noop 7,
  cross-file 5, external-service 2, parser-raw 1). One worker deadline
  stop (`submacros/StatMonitor.ahk`, `Loop {}` cut at 4.0 s) leaves that
  file's inventory partial and is reported, not hidden.
- Expanded main: 33 include files, 22,522 logical lines, **1,486 auto
  statements, 621 functions, 3 raw** in the auto-section.

The 7 `language-gap` hits are not main-script startup failures:

| Rows | Explanation |
|---|---|
| `bitmaps[...]` 777, `buff_bitmaps[...]` 35, `hBitmapsSBT[...]` 26, `Shrine[...]` 25, `buff_characters[...]` 10 | The census executes each standalone `nm_image_assets/**/bitmaps.ahk` in isolation. Their maps are normally created by the including main script (`bitmaps`/`hBitmapsSBT` at `submacros/natro_macro.ahk:2148-2150`, `buff_bitmaps`/`buff_characters` at `submacros/StatMonitor.ahk:47-49`). `Shrine` has **no visible definition anywhere in the corpus**, so it is reported rather than assumed defined. The runtime now says `has no live container` instead of misreporting `cannot store into int`. |
| `for` 1, `method` 1 | Natro's WMI OS-version query `ComObjGet("winmgmts:").ExecQuery(...)`, which depends on the documented COM gap. |

## 2. What landed in v1.0

All 20 commits were separately tested and committed green; the suite grew
from **266** to **345** tests (2,555 insertions / 210 deletions).

| Commit | Surface |
|---|---|
| `919b63b` | X11/XWayland `WinTitle` criteria: exact `ahk_exe` via `/proc` + `_NET_WM_PID`, exact case-sensitive `ahk_class`, `ahk_pid`; `ahk_group` refused instead of ignored. |
| `f1c287c` | `WinGetList`/`WinGetCount` through the shared matcher; `WinText`/`ExcludeText` refused explicitly. |
| `b09ad3f` | `WinWait`/`WinWaitClose`/`WinWaitActive`/`WinWaitNotActive` with omitted/zero timeouts, 50 ms polling, abort support and honest misses. |
| `18b04a1` | v2 `Loop Files` specials (`A_LoopFilePath`, size, modified/accessed times) from `stat`. |
| `a73d667` | Continuation sections attach to `MsgBox` commands, including braceless `if` bodies. |
| `e8f74bd` | Arrow functions with assignment bodies and object-literal returns. |
| `3704c43` | Continuation joining strips per-line `;` comments while preserving quoted text. |
| `806d1c2` | `Run` continuation sections bind as the command expression. |
| `178df0f` | Command-style `TraySetIcon` parses and logs the no-system-tray boundary. |
| `d0c51ca` | `Fn.Bind(...)` freezes bound arguments and dispatches through normal function/builtin paths. |
| `030334a` | Parameter defaults evaluate in declaration order; `p := unset` stays genuinely unset. |
| `c8c2b69` | Brace-on-line class definitions and `Class.Method(...)` static dispatch (Natro `JSON.stringify`). |
| `d2b5fb0` | Case-insensitive variable reads in expressions, concatenation and arithmetic (`A_index` → `A_Index`). |
| `0e17c0e` | Windows case-insensitive path lookup, component by component, for paths passed through `_abs_path()`. |
| `3bfda87` | Function scope: locals restored per call, `global`/`static` declarations, nested closures; `hashDefaults()` now populates `patternlist`. |
| `4f04f5a` | Array `Length`/`Capacity`/`Default` property assignment with valueless padding. |
| `95299b0` | Map `Default`/`CaseSense`/`Count`/`Capacity` without polluting the key space; `AhkMap`. |
| `beec9a3` | Variadic `Push()`, `InsertAt()` and `Map.Set()`. |
| `6675e3a` | Negative array indexes everywhere; `Delete()` leaves a valueless slot; `RemoveAt()` shifts; `Has()`/enumeration respect holes. |
| `40bdcae` | Assignment to an undefined bare container reports `has no live container` instead of evaluating it as falsy `0`. |

## 3. Exact limitations (documented, not silent)

1. **Native Wayland window handles.** XWayland windows can be targeted;
   native Wayland surfaces have no foreign HWND. The bridge logs the
   limitation and returns falsy/`TargetError`; it never invents a handle.
2. **COM / WinRT / WinHttp.** `ComValue`, `ComObjGet`, `ComCall`,
   `ObjRelease`, WinRT activation and WinHTTP remain logged stubs.
   Natro's WMI OS-version query, Discord/update HTTP and shell COM paths
   are external gaps; startup completes without them.
3. **General Windows ABI.** `DllCall` is a whitelist, not a PE loader.
   GDI+ drawing/image-lock calls are display-only/no-ops and stay visible
   in the census. `Gdip_All.ahk` machine-code bodies are deliberately not
   ported; image processing uses the native vision layer.
4. **Function-pointer/machine-code calls.** `DllCall(ptr, …)` cannot
   execute Windows machine code here; it is logged once and returns 0.
5. **MD2.** Python/OpenSSL provides no MD2. `HashFile` type 1 uses a
   logged MD5 fallback, so it is an approximation, not exact MD2.
6. **File sharing modes.** `FileOpen` sharing flags are accepted/logged
   but Linux does not enforce Windows share semantics.
7. **External window tools.** X11/XWayland queries need `xdotool`,
   `xwininfo` and `xprop`; missing tools log inability and return falsy.
8. **Global hotkeys.** The runtime implements in-process hotkeys. A
   compositor/portal-level binding is setup work, not automatic.
9. **Array/Map edge semantics.** Reading a valueless Array slot without
   a `Default` returns blank instead of raising `UnsetItemError`;
   `Map.Get()` likewise returns blank when no supplied or map default
   exists; `CaseSense` on a non-empty Map is logged and ignored; unknown
   Map property names still become pairs; CaseSense Off uses a linear
   case-folded scan on misses.
10. **Function scope edges.** Undeclared reads fall back to the global
    table instead of raising an uninitialized-variable error; a closure
    returned and called after its creator exits does not retain captured
    cells; enclosing-function `static` slots are not shared into nested
    functions; dynamic (`%name%`) assignment targets are not restored
    per scope.
11. **Classes.** No object instances, `new`/constructors, `this`,
    inheritance or static properties. Instance methods invoked as
    statics keep the explicit unsupported-method log.
12. **Runtime scope of this proof.** Offscreen Qt, static
    capture/window effects, mocked GDI+ startup, `allow_processes=False`,
    `A_PtrSize=4`, `A_Is64bitOS=0`, and no real Roblox target. Missing
    Roblox/window targets correctly return `0`/`TargetError`.

## 4. Reproduction

All commands run from the repo. The corpus is copied; the real tree is
never the working directory.

```bash
cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge"
QT_QPA_PLATFORM=offscreen python -m pytest -q

QT_QPA_PLATFORM=offscreen python tools/natro_census.py \
  --json /tmp/opencode/census-v10.json \
  --markdown /tmp/opencode/CENSUS-v10.md

# Startup + 600 s soak (harness kept outside the repo, like v0.8):
QT_QPA_PLATFORM=offscreen python /tmp/opencode/v10_soak.py --seconds 600
```

Harness behavior: copies the Natro tree into a temporary directory,
loads `submacros/natro_macro.ahk`, runs `Runtime(..., allow_processes=False,
max_loop=5000)` with `A_PtrSize=4`, `A_Is64bitOS=0`, offscreen Qt,
vision/window effects replaced by log-only stand-ins, and
`Gdip_Startup`/`Gdip_Shutdown` patched to `1`/`0`. It executes the auto
section, then calls `rt.wait(timeout=600)` while sampling CPU, RSS, timer
fires and callback errors, and writes `/tmp/opencode/v10_soak.json`.

The census tool copies the corpus into its own temporary sandbox and sets
`AHK_BRIDGE_CENSUS=1`; it does not touch the real desktop or Natro tree.

## 5. Next work

There is no remaining v1.0 blocker. Work past v1.0 is additive and must
keep the boundaries above:

1. Live desktop/game validation on an XWayland window, or native-Wayland
   capture/focus support through compositor/portal data.
2. Native helpers for any Natro WMI/HTTP/update path that becomes
   load-bearing — never fake COM success.
3. Closure capture that survives the creating call, and stricter
   uninitialized-read/`UnsetItemError` semantics.
4. Keep the census and soak offscreen/sandboxed; one feature per green
   commit with a regression test.

## 6. Paste prompt for the next session

> Continue AHK-Linux-Bridge from v1.0 (version 1.0.0). Startup and a 600 s
> soak are proven on a disposable Natro tree: 33 files, 1,486 auto
> statements, 621 functions, 0 startup errors, 813 controls, 9 tabs, 300
> timer fires with 0 callback errors. The capability matrix in
> `docs/CAPABILITY-MATRIX.md` has no `unknown` rows and 47 known gaps (0
> unknown load-bearing). Preserve the documented boundaries: native
> Wayland has no foreign HWND, COM/WinRT/WinHttp are external gaps,
> DllCall is a whitelist, GDI+ is display-only, and MD2 is a logged MD5
> fallback. Never fake a window/COM result. One feature per green commit
> with a regression test; keep census/soak sandboxed.
