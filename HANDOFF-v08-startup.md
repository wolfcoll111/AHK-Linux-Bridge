# HANDOFF — v0.8 Natro startup/soak → v1.0 capability matrix

Status: **v0.8 is complete and evidenced on 2026-10-25.** The real Natro
main script starts end-to-end from a disposable copy with **0 startup
errors**, builds its complete main GUI, installs its timers, and runs in
steady state for **600 s**. The **v1.0 capability matrix** is published
with no `unknown` rows. This is a Linux runtime proof, not a live Roblox
or desktop-session proof: vision/window effects were captured, process
spawning was disabled, and the GUI was offscreen.

Repo: `/home/lordhats/Documents/Default Project/ahk-linux-bridge`
Remote: `https://github.com/wolfcoll111/AHK-Linux-Bridge.git` (`main`).
Corpus stays outside the repo at `~/Games/NatroMacro/src` (NatroMacro
v1.1.2, 150 `.ahk` files). PySide6 6.12.0 remains an optional `gui`
extra and is imported lazily.

## 1. Verified v0.8 baseline

- `QT_QPA_PLATFORM=offscreen python -m pytest -q` → **266 passed**
  (~6.4 s). No test performs a live desktop, clipboard, window or vision
  call.
- **Real main startup**, fresh disposable tree (no pre-existing
  `settings/`), from `submacros/natro_macro.ahk`:
  **33 include files, 1,489 auto statements, 620 functions, 1,878,792
  expanded characters**; startup **0 errors** in **9.54 s**; **925
  variables**; **163 logs**; **813 controls**, **9 tab pages**,
  `StartButton` enabled. The startup generated
  `settings/nm_config.ini`, `settings/field_config.ini`,
  `settings/manual_planters.ini` and `settings/imported/`.
- **600 s steady-state soak** on the same kind of fresh disposable tree
  (`soak_s` **600.011**): startup **8.289 s** after a **7.033 s** parse,
  **0 startup errors**, 813 controls, 9 tabs, `StartButton` enabled,
  925 variables. The Natro `Background` timer ran **300 callbacks**
  (299 measured inter-arrival gaps) at a 2 s period: period mean
  **1999.992 ms**, mean absolute drift **3.278 ms**, p95 **7.028 ms**,
  max **10.464 ms**; callback execution mean **9.406 ms**, max
  **12.184 ms**. CPU **7.23 s** over the soak (**1.205 % of one core**);
  RSS **163.8 MB** at soak start, **125.0 MB** at end, peak
  **165.4 MB**; **1 new log** (`nm_nightinterrupt` stub) and **0 timer
  callback errors**.
- **Sandboxed census** (`docs/CENSUS-v0.8.md`): **150 files, 672
  functions, 21,269 nodes, 47 `__raw__` (0.22%), 0 parse crashes;
  150/150 runtime, 0 timeouts, 0 worker-deadline stops, 0 load errors,
  0 unknown load-bearing hits; known gaps 48** (down from 64). Expanded
  main: 33 include files, 22,514 logical lines, 1,489 auto statements,
  620 functions, 6 raw. Verdicts: windows-only 38, language-gap 8,
  setting-noop 7, cross-file 5, external-service 2, parser-raw 1.
- The matrix links every load-bearing surface to one of three explicit
  statuses: **Implemented**, **Implemented with limitation**, or
  **Blocked/external**.

## 2. What landed in v0.8

| Commit | Surface |
|---|---|
| `2c11cb4` | Parser: preserve block structure through continuations and `if`/`else` chains; Natro bodies no longer leak into the auto-section. |
| `db1401d` | Runtime: real `FileOpen` File objects (`Read`, `ReadLine`, `Write`, `WriteLine`, `RawRead`, `Seek`, `Pos`, `Length`, `AtEOF`, `Close`); `FileWrite`/`FileAppend` and settings generation now use real files. |
| `7112a93` | Parser: inline `Case 1: stmt` switch bodies and arrow functions returning object literals; Natro startup reaches its GUI/timers without parser aborts. |
| `c79f8bc` | Runtime: Natro expression/variable semantics — top-level comparisons ignore `:=`, bitwise/hex arithmetic, case-insensitive variables, character `StrSplit`, and operator/call edge cases. |
| `2bc9495` | Runtime: `HashFile` CryptoAPI bridged to Python `hashlib` with synthetic handles; real MD5/SHA-1/SHA-256/SHA-384/SHA-512 over file bytes. |

Every step was tested and committed green; the full suite grew from 252
tests at v0.7 to **266**.

## 3. Exact limitations (documented, not silent)

1. **Native Wayland window handles.** XWayland windows can be targeted;
   native Wayland surfaces have no foreign HWND. The bridge logs the
   limitation and returns falsy/`TargetError`; it never invents a handle.
   Workaround: XWayland or compositor/portal-specific data.
2. **COM / WinRT / WinHttp.** `ComValue`, `ComObjGet`, `ComCall`,
   `ObjRelease`, WinRT activation and WinHTTP are logged stubs. Natro's
   WMI OS-version query, Discord/update HTTP and shell COM paths remain
   external gaps; startup completes without them.
3. **General Windows ABI.** `DllCall` is a whitelist, not a PE loader.
   GDI+ drawing/image-lock calls are display-only/no-ops and are visible
   in the census. `Gdip_All.ahk` DllCall/machine-code bodies are
   deliberately not ported; image processing uses the native vision
   layer instead.
4. **Function-pointer/machine-code calls.** `DllCall(ptr, …)` cannot
   execute Windows machine code here; it is logged once and returns 0.
5. **MD2.** Python/OpenSSL provides no MD2. `HashFile` type 1 uses a
   logged MD5 fallback, so it is an approximation, not exact MD2.
6. **File sharing modes.** `FileOpen` sharing flags are accepted/logged
   but Linux does not enforce Windows share semantics.
7. **External window tools.** X11/XWayland queries need `xdotool`,
   `xwininfo` and `xprop`; missing tools log inability and return falsy.
8. **Global hotkeys.** The runtime implements in-process hotkeys. A
   compositor/portal-level binding (the `hotkeys.py` GlobalShortcuts
   helper or a desktop keybind) is setup work, not automatic.
9. **Runtime scope of this proof.** Offscreen Qt, static capture/window
   effects, mocked GDI+ startup, `allow_processes=False`,
   `A_PtrSize=4`, `A_Is64bitOS=0`, and no real Roblox target. Missing
   Roblox/window targets correctly return `0`/`TargetError`.

## 4. Reproduction

All commands are run from the repo. The corpus is copied; the real tree
is never used as the working directory.

```bash
cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge"
QT_QPA_PLATFORM=offscreen python -m pytest -q

# disposable tree (never cd into ~/Games/NatroMacro/src for these runs)
rm -rf /tmp/opencode/natro-v08
mkdir -p /tmp/opencode/natro-v08
cp -a ~/Games/NatroMacro/src /tmp/opencode/natro-v08/tree

# Startup probe / soak used temporary harnesses outside the repo, with this
# environment; they are described below so the run can be reconstructed:
#   QT_QPA_PLATFORM=offscreen python /tmp/opencode/v08_probe.py
#   SOAK_SECONDS=600 QT_QPA_PLATFORM=offscreen AHK_BRIDGE_CENSUS=1 \
#     python /tmp/opencode/v08_soak.py
#
# Harness behavior: load_script() on submacros/natro_macro.ahk, then
# Runtime(..., allow_processes=False, max_loop=5000), A_PtrSize=4,
# A_Is64bitOS=0, offscreen Qt, vision/window effects replaced by log-only
# stand-ins, and Gdip_Startup/Gdip_Shutdown patched to 1/0. The probe
# executes script.auto_section; the soak then calls rt.wait() until the
# requested duration elapses.

QT_QPA_PLATFORM=offscreen python tools/natro_census.py \
  --json /tmp/opencode/census-v08.json \
  --markdown /tmp/opencode/CENSUS-v08.md
```

The census tool copies the corpus into its own temporary sandbox and sets
`AHK_BRIDGE_CENSUS=1`; it does not touch the real desktop or Natro tree.
The startup/soak harness set `A_PtrSize=4`, `A_Is64bitOS=0`, disabled
process spawning, and replaced capture/window activation with logging
stand-ins.

## 5. Next work

There is no remaining v0.8 startup blocker. Future work is additive and
must preserve the explicit boundaries above:

1. If live desktop/game testing is needed, target an XWayland window or
   add compositor/portal-specific native-Wayland capture/focus support.
2. If Natro's WMI/HTTP/update paths become load-bearing, implement a
   native helper outside the AHK COM/WinHttp stubs rather than faking
   COM success.
3. Keep the census and soak offscreen/sandboxed. Commit one feature at a
   time with a regression test; update the matrix and census when a
   status changes.

## 6. Paste prompt for the next session

> Continue AHK-Linux-Bridge from v0.8. Startup is now proven on a
> disposable Natro tree: 33 files, 1,489 auto statements, 620 functions,
> 0 startup errors, 813 controls, 9 tabs, 600 s soak. The v1.0 capability
> matrix is in `docs/CAPABILITY-MATRIX.md` with no `unknown` rows. Preserve
> the documented boundaries: native Wayland has no foreign HWND, COM/
> WinRT/WinHttp are external gaps, DllCall is a whitelist, GDI+ is
> display-only, and MD2 is a logged MD5 fallback. Never fake a window/COM
> result. One feature per green commit with a regression test; keep
> census/soak sandboxed.
