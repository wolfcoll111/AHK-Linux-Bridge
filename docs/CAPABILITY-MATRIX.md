# Capability matrix — AHK v2 on Linux

Status as of **v0.8** (2026-10-25). Every row is deliberately classified:
there is no `unknown` status. A surface either works natively, works with a
named limitation, or is blocked and reports an explicit logged fallback
instead of pretending success.

| Status | Meaning |
|---|---|
| **Implemented** | Native Linux path, covered by unit tests and exercised by Natro startup or the census. |
| **Implemented with limitation** | Works on the supported surface; the limitation is named in the row and is logged or documented. |
| **Blocked/external** | Cannot be reproduced from this process on Linux. Calls return AHK-falsy, raise the documented error, or are logged once; no fake handle/result. |

## Evidence gate

- `QT_QPA_PLATFORM=offscreen python -m pytest -q` → **266 passed**
  (~6.4 s); no test performs a live desktop, clipboard, window or vision call.
- Real Natro `natro_macro.ahk` from a disposable copy:
  **33 files, 1,489 auto statements, 620 functions, 1,878,792 expanded
  chars**, startup **0 errors**, **813 controls**, **9 tab pages**,
  `StartButton` enabled. Cold startup was **9.54 s** in the probe run.
- 600 s steady-state soak (`soak_s` **600.011**): **0 startup errors**,
  813 controls, 9 tabs, **925 variables**, **300 background-timer
  callbacks**, mean absolute drift **3.278 ms** (p95 **7.028 ms**, max
  **10.464 ms**), CPU **1.205 % of one core**, RSS **163.8 → 125.0 MB**
  (peak **165.4 MB**), **0 timer callback errors**. Details in
  `HANDOFF-v08-startup.md`.
- Sandboxed census (`docs/CENSUS-v0.8.md`): **150 files, 672 functions,
  21,269 nodes, 47 `__raw__` (0.22%), 0 parse crashes; 150/150 runtime,
  0 timeouts, 0 load errors, 0 unknown load-bearing hits; 48 known
  gaps** (windows-only 38, language-gap 8, setting-noop 7, cross-file 5,
  external-service 2, parser-raw 1).

## Windows and controls

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| AHK `Gui` window registry, show/hide/destroy, title/position | **Implemented** | `gui.py`; `tests/test_gui.py`, `tests/test_os_bridge.py`; Natro builds 813 controls offscreen | Native window decorations and exact Win32 client metrics differ; offscreen tests use Qt geometry. |
| Named/ClassNN controls, text/enabled/position/HWND, events | **Implemented with limitation** | Own-Gui registry in `runtime.py`; `GuiControl` API; `test_os_bridge.py`, Natro `StartButton`/tabs | Child controls of foreign windows are not enumerable; a missing control raises AHK-style `TargetError`. |
| Foreign X11/XWayland window lookup and operations | **Implemented with limitation** | `window_ops.py`: `xdotool` search, geometry, title, class, PID, close/kill/move/activate, EWMH opacity, `xwininfo`/`xprop`; `tests/test_winactivate.py`, `tests/test_window_specs.py` | Needs `DISPLAY` plus the X11 tools. Only XWayland/X11 windows are visible. Missing tools produce logged inability, not geometry. |
| Native Wayland foreign surfaces / HWND emulation | **Blocked/external** | `_resolve_window()` logs the exact “no HWND” limitation and returns `None`; callers return `0`/`TargetError` | Wayland gives no global foreign-window handle. Workaround: run the target under XWayland, or use compositor/portal-specific data. |
| `WinActivate` / focus | **Implemented with limitation** | Own-Gui activation, X11 `windowactivate`, Hyprland/xdotool fallback; `test_winactivate.py`, `test_window_specs.py` | Statement WinTitles are evaluated as expressions, so `WinActivate "ahk_id " hwnd` works; native Wayland focus remains compositor-gated and a miss is logged rather than reported as success. |
| `WinExist`, title, frame/client position, count, PID/process name | **Implemented with limitation** | Own Gui + X11 path; title/`ahk_exe`/`ahk_class`/`ahk_pid` criteria are ANDed; `ControlGetPos` legacy omitted-slot fix; `tests/test_os_bridge.py`, `tests/test_window_specs.py` | `ahk_exe` resolves exactly the process file name (or full path) through `/proc` plus `_NET_WM_PID`; `ahk_class` is exact/case-sensitive like AHK. `ahk_group` is refused (no `GroupAdd` registry) instead of ignored. A native Wayland-only window still has no X11 handle. |
| `WinGetList` / `WinGetCount` | **Implemented with limitation** | Own Gui + X11 enumeration through the shared matcher; `tests/test_window_specs.py` | Visible windows only (`DetectHiddenWindows` remains a logged no-op). `WinText`/`ExcludeText` need foreign control text and are refused with a log; `ahk_group` is refused. Native Wayland-only windows are absent. |
| `WinWait` / `WinWaitClose` / `WinWaitActive` / `WinWaitNotActive` / `WinActive` | **Implemented with limitation** | `_win_wait()`/`_win_active()` poll the shared matcher every 50 ms and honour abort; timeout omitted waits, `0` checks once; active checks use own-Gui activation then X11 `getactivewindow`; `tests/test_winwait.py` | `WinText`/`ExcludeText` are refused (no foreign control text), so `WinWait*` reports no match and `WinWaitClose` never fakes a close. The Last Found Window is not tracked: blank `WinActive()` returns the real active handle. Native Wayland-only windows never match. |
| `WinClose`, `WinKill`, `WinMove`, `WinSetTransparent` | **Implemented with limitation** | Own Gui operations are real; X11 path uses `xdotool`/`xprop` | Foreign native Wayland windows cannot be controlled this way. |
| `TraySetIcon` / tray notifications | **Blocked/external** | Command-style `TraySetIcon "path"` is parsed by `LEGACY_CMD_RE` and logs `no system tray on Linux, ignored`; `test_trayseticon_command_style_is_parsed_and_logged`; `TrayTip` stays a logged no-op | The bridge never creates a system-tray icon or notification, so these surfaces are logged instead of faked. |

## Clipboard

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| `A_Clipboard` text read/write | **Implemented with limitation** | `clipboard.py` tries `wl-paste`/`wl-copy`, then `xclip`, then `xsel`; `tests/test_os_bridge.py` | Text only. No image/HTML/rich formats. Failures keep the AHK-side value and log once. `AHK_BRIDGE_CENSUS=1` disables live clipboard access. |
| Clipboard as Natro data channel (IDs/URLs/config) | **Implemented with limitation** | Same bridge; one-time failure logs | If no helper is installed the macro still runs with the in-script value; the OS clipboard is not updated. |

## Memory and DllCall

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| `Buffer`, `NumGet`, `NumPut`, `StrGet`, `StrPut`, `StrPtr`, `VarPtr`, `ObjPtr` | **Implemented with limitation** | `memory.py` bounded synthetic pointers; `tests/test_os_bridge.py` | No arbitrary process memory or PE module memory. Buffers are bounded Python objects; invalid reads/writes are clamped/falsy, not Windows crash semantics. |
| Whitelisted `DllCall` equivalents | **Implemented with limitation** | Timing/sleep, PID/TID, system metrics, FILETIME/QPC/tick count, command line, locale/date text, selected structure writes; `_dll_call()` | This is a whitelist, not a Windows ABI/PE loader. Unmodelled exports return `0` and log once. |
| Advapi32 CryptoAPI used by `HashFile` | **Implemented with limitation** | MD5/SHA-1/SHA-256/SHA-384/SHA-512 via Python `hashlib`; real file bytes through `File.RawRead`; `tests/test_hashfile.py` | Synthetic handles and Linux effect, not Windows CryptoAPI. MD2 (type 1) is unavailable and logs an MD5 fallback. |
| Unmodelled GDI/user32/COM exports, drawing and bitmap-lock calls | **Blocked/external** | `_dll_call()` display-only/no-op whitelist; census classifies each exported name | No Windows ABI/machine code execution. Returns Windows-falsy (often `0`/`1` for display-only paths) and logs once. Replaced where possible by the native vision layer. |
| Genuine function pointers / injected machine code | **Blocked/external** | `DllCall(ptr, …)` logs `DllCall function pointer …` and returns `0`; `tests/test_os_bridge.py` | Windows x64/x86 machine code cannot run in this Python process. |
| Arbitrary process/module memory and PE loading | **Blocked/external** | Not implemented; no fabricated handles | Would require a separate Wine/Windows-compatible process and ABI; out of scope for the native Linux runtime. |

## COM, WinRT, WinHttp

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| `ComObject`, `ComValue`, `ComObjGet`, `ComCall`, `ObjRelease` | **Blocked/external** | Runtime logs `stub builtin …` / `.method unsupported`; census keeps `windows-only`/`external-service` rows | No COM/WinRT runtime. Natro’s WMI OS-version query and shell COM calls are therefore explicit gaps. |
| WinHTTP / `WinHttp.WinHttpRequest` / object `.open`/`.send` | **Blocked/external** | Logged stubs (`req.open`, `req.setrequestheader`, `req.send`); no network request is attempted | Use a native HTTP helper or a browser/CLI for integrations; do not report a fake HTTP success. |
| Webhooks, update checks, Discord/API calls | **Blocked/external** | Depend on the WinHTTP/COM gap; Natro startup still completes and logs | A native HTTP implementation is separate work; the macro’s GUI/startup path does not depend on it. |
| DDE, OLE, native Windows message targets | **Blocked/external** | No native bridge; unsupported targets log | Could be revisited with a Wine-side helper; not emulated. |

## GDI+ and vision

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| `PixelSearch`, `ImageSearch`, bitmap from screen/base64, create/dispose/dimensions | **Implemented** | Native `vision.py`/`pixels.py`; `tests/test_vision.py` (search directions, variation, instances, delimiters, dimensions, leaks) | Vision is a Linux effect, not GDI+. It captures the screen/region through KWin or mss; it does not recreate GDI+ handles. |
| Screen capture on Wayland | **Implemented with limitation** | KWin ScreenShot2 D-Bus path preferred; mss fallback; `test_kwin_decode_*`, `test_screenshot_prefers_kwin_then_mss` | KWin-specific. Other compositors fall back to mss (which can be black on native Wayland); failures return an empty bitmap and log. |
| GDI+ drawing, effects, font/clip/region, `GdipBitmapLockBits`/`UnlockBits` | **Blocked/external** | Display-only/no-op whitelist and logged `stub Gdip_*`; `test_runtime_unknown_gdip_stub_logs_once` | Natro’s on-screen image processing uses the native vision layer. `Gdip_All.ahk` machine-code/DllCall bodies are deliberately not ported. |
| Overlay/effects that require GDI+ drawing | **Blocked/external** | Logged no-op; no fake pixels | Visual overlays are not recreated; gameplay logic that only reads pixels remains supported. |

## Timers and the event loop

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| `SetTimer` positive recurring / negative one-shot / `0` off | **Implemented** | `_set_timer()`/`_process_due_timers()`; `tests/test_event_loop.py` | — |
| Monotonic scheduling and drift | **Implemented** | `time.monotonic()`, due-time catch-up; 600 s soak: **300 callbacks** (299 measured inter-arrival gaps), period mean **1999.992 ms**, mean absolute drift **3.278 ms**, p95 **7.028 ms**, max **10.464 ms**; callback mean **9.406 ms**, max **12.184 ms** | Cooperative scheduling in the Python event loop; a long callback delays later timers (as in AHK’s single-thread model). |
| Callback error isolation | **Implemented** | Exceptions logged per callback; `test_timer_exception_is_logged_and_loop_continues`, message-handler tests | The callback’s side effects before the error are not rolled back. |
| `OnExit` / `ExitApp` / clean shutdown | **Implemented** | `_run_exit_callbacks`, `Aborted`; `tests/test_event_loop.py` | Windows process exit codes are mapped to the CLI return code. |

## IPC and messages

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| `OnMessage`, `PostMessage`, `SendMessage` within this runtime | **Implemented** | In-process message table and synchronous/asynchronous dispatch; `tests/test_event_loop.py` | Message IDs and HWNDs are local objects, not Windows window-manager messages. |
| `RunWait` child → parent message bridge | **Implemented** | Child process protocol in `runtime.py`; `tests/test_process_bridge.py` | The child must be an AHK-Linux-Bridge/Python child using the bridge; arbitrary Windows processes do not participate. |
| External HWND / native Wayland IPC / DDE | **Blocked/external** | Unsupported targets log and return falsy | No foreign Wayland IPC surface; use a native socket/CLI helper if needed. |

## Input and automation

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| Keyboard/mouse injection | **Implemented with limitation** | `uinput` (Wayland + X11, needs `/dev/uinput` permissions) or XTest (X11); `InputSimulator`; `tests/test_send_sequences.py`, `tests/test_bridge.py` | Requires udev/input-group setup for uinput. XTest is X11-only. No Roblox-specific injection; it injects at the OS level. |
| `Send`/`SendInput` family, `Click`, `MouseMove`, wheel, key down/up | **Implemented with limitation** | Parser/backend sequences; `test_send_sequences.py`, Natro execution tests | Some Windows `Send` modes/scan-code nuances are approximated by the Linux backend. |
| `Hotkey`/hotstring definitions and dynamic hotkeys | **Implemented with limitation** | Runtime hotkey tables and `fire_hotkey()`; `tests/test_event_loop.py` | These are in-process hotkeys, not a Windows keyboard hook. Global registration needs a desktop keybind or a separate portal integration. |
| Global compositor hotkeys on Wayland | **Implemented with limitation** | `hotkeys.py` has an XDG GlobalShortcuts helper; Hyprland/desktop keybind + CLI `--hotkey` is the verified integration path | The portal helper is not automatically registered by the runtime and needs a running portal/app-id. Automatic global registration remains separate setup work. |
| Clipboard-based input / typing helpers | **Implemented with limitation** | Uses the clipboard bridge where scripts do; `A_Clipboard` tests | Text-only clipboard and helper dependency. |

## Files, INI, process and GUI execution

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| `FileOpen`/File object (`Read`, `ReadLine`, `Write`, `WriteLine`, `RawRead`, `Seek`, `Pos`, `Length`, `AtEOF`, `Close`) | **Implemented with limitation** | Real Linux files; `tests/test_natro_constructs.py`; HashFile uses binary `RawRead` | Sharing flags (`w-d`) are accepted/logged but not enforced. Text encoding defaults to UTF-8; Windows ANSI/UTF-16 BOM edge cases are approximated. |
| `FileRead`, `FileAppend`, `FileDelete`, `FileCopy`, `FileMove`, `DirCreate`, `Loop Files` | **Implemented with limitation** | Real filesystem operations; v2 file-loop specials (`A_LoopFilePath`, size, modified/accessed times) come from `stat`; `test_file_builtins_and_relative_working_directory`, `test_loop_files`, `test_loop_files_v2_specials_and_fileopen_by_path` | Windows path/attribute semantics and sharing modes are not reproduced exactly. 8.3 short names and file creation time have no portable Linux value and are blank, not invented; `A_LoopFileAttrib` is blank. |
| `IniRead`/`IniWrite`/`IniDelete` | **Implemented** | Real INI files; `tests/test_natro_constructs.py`, Natro-generated settings | Case/section formatting follows Python’s INI handling; unusual Windows INI encodings may differ. |
| `Run`/`RunWait`, `ProcessClose`, `ProcessExist`, `A_Args` | **Implemented with limitation** | `subprocess`, child IPC; `tests/test_process_bridge.py` | Windows `.exe` targets are refused/logged, not run. `allow_processes=False` is used for census/soak. AutoHotkey command translation is for this bridge, not a Windows shell. |
| PySide6 `Gui`/controls/tabs/events | **Implemented with limitation** | Optional `gui` extra; lazy import; offscreen fallback; Natro 813 controls/9 tabs | GUI look/layout is Qt, not Win32. Some Natro control types/tabs/placeholders are logged (`SecretButton`, `Text`, Blender controls, etc.). |

## Language and expressions

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| `Fn.Bind(args...)` / BoundFunc partial application | **Implemented with limitation** | `_bind_target()` and `BoundFunc` evaluate the bound arguments once, prepend them to every later call, and dispatch through the normal function/builtin path; `test_bind_builtin_freezes_args_and_calls_later`, `test_bind_user_function_prepends_frozen_args` | Function references are name-based rather than real AHK Func objects. A quoted string is not a function reference and still logs `.bind() unsupported`; binding an undefined name defers to the normal explicit `stub builtin` log; nested `Bind` on a BoundFunc is not modelled. |
| Multi-line continuations with inline comments | **Implemented** | `_join_continuations_mapped()` joins open parens/brackets, trailing operators and leading `.`/`,`/operator lines, stripping each physical line's `;` comment while preserving quoted text; `test_static_map_continuation_with_inline_comments_enumerates` | — |
| Function/method parameter defaults | **Implemented** | `FuncDef.defaults` is captured for normal, arrow, nested and class-method definitions; omitted arguments evaluate their default in declaration order (`Echo(a, b := a)` works); `test_default_params_apply_and_override`, `test_default_param_may_reference_earlier_param`, `test_unset_default_keeps_param_unset` | `p := unset` leaves the parameter genuinely unset so `IsSet(p)` is `0`. Required-parameter arity is still not enforced; missing required parameters simply stay unset. |
| Class definitions and static method calls | **Implemented with limitation** | `class Name {` (same-line or Allman brace) parses as a class node; the parser records static methods per `(class, method)` and `Class.Method(...)` runs that exact FuncDef; `test_class_brace_on_same_line_and_static_dispatch`, `test_instance_method_is_not_dispatched_as_static`; Natro's `JSON.stringify` now executes | No object instances, constructors/`new`, `this`, inheritance or static properties. Instance methods invoked as statics keep the explicit unsupported-method log. |
| `%var%` dynamic call names | **Implemented** | Substitution resolves variable names case-insensitively, like AHK variables; `test_dynamic_dispatch_name_resolves_var_case_insensitively` | Only simple `%name%` segments are substituted (up to 10 passes), matching the corpus. |
| Case-insensitive variable reads | **Implemented** | Expression evaluation, implicit-concatenation classification, `Send` concatenation and arithmetic (`_safe_eval`) resolve names through `_var_key()`, so Natro's legacy `A_index` spelling reads the loop's `A_Index`; `test_implicit_concat_resolves_mixed_case_vars`, `test_send_concat_resolves_mixed_case_vars`, `test_gui_options_concat_mixed_case_loop_var` | The flagged paths are unified; `IsSet()` and assignment-target spellings still compare exactly. |

## Safety, observability and non-goals

| Capability | Status | Linux implementation / evidence | Limitation |
|---|---|---|---|
| No silent stubs | **Implemented** | Every unsupported builtin/DllCall/control logs once and returns AHK-falsy; v0.8 census has **0 unknown load-bearing hits** and 48 explicit known gaps | Logs may be numerous for deliberately unported display/COM paths; they remain visible. |
| Missing window/control semantics | **Implemented** | `TargetError` on missing target; Natro `GetRobloxClientPos()` returns `0`; `test_missing_*` | No fake geometry. |
| Census sandbox | **Implemented** | Copies the corpus to a temp tree, runs offscreen, disables clipboard/process spawning/desktop effects; `tools/natro_census.py` | Census results describe the corpus at that commit; they are not a live Roblox test. |
| Native Windows ABI, PE loading, COM/WinRT, WinHttp, GDI+ rendering | **Blocked/external** | Documented in the rows above | Use Wine/AutoHotkey for parity when a surface genuinely requires Windows. This is a design boundary, not a hidden stub. |
