# AHK-Linux-Bridge — AHK v2 macro engine for Linux (Wayland + X11)

Run Windows-style AHK v2 farming/productivity macros on Linux with one
input API that routes to **uinput** (universal) or **XTest** (X11
fallback). The current milestone is **v0.7**: the Linux OS bridge for
windows, controls, clipboard and bounded memory/DllCall, on top of the
v0.6 PySide6 GUI layer.

## Status

- **v0.5 / v0.6:** headless AHK v2 runtime, real vision/input/capture, and
  a PySide6 Gui/control implementation. The real Natro `natro_macro.ahk`
  main GUI constructs offscreen with **805 controls** and 9 tab pages.
- **v0.7:** own-Gui and X11/XWayland window/control queries, real system
  clipboard, bounded buffers and a whitelisted `DllCall` surface.
  Missing targets raise AHK-style `TargetError`; unsupported Windows ABI,
  COM and function-pointer calls are logged explicitly and return falsy.
- **Next (v0.8):** full live Natro startup with its config/timers/
  submacros/main loop, followed by a measured soak. The GUI alone is
  proven; live startup is not claimed yet.
- Native Wayland surfaces have no foreign HWND. Target XWayland windows or
  use compositor/portal data; the bridge reports the limitation instead of
  inventing a handle.

`docs/CAPABILITY-MATRIX.md` (v1.0) is still to come. Current evidence is
in `HANDOFF-v07-os.md`, `docs/CENSUS-v0.7.md` and the test suite.

## Quickstart

```bash
pip install -e '.[uinput,portal,pixels]'
sudo cp udev/99-ahk-linux-bridge-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG input $USER   # then re-login
ahk-bridge check
ahk-bridge run examples/farm_loop.ahk --hotkey F1
```

For AHK macros that build a GUI, install the optional GUI extra:

```bash
pip install -e '.[gui]'   # PySide6
```

## AFK farming

```bash
# fire the farm loop with human-like timing variation (±20% on every Sleep)
ahk-bridge run examples/afk_farm_advanced.ahk --hotkey F1 --jitter 0.2
# repeat a macro 50x with 1s between passes
ahk-bridge run farm.ahk --repeat 50 --delay-ms 1000 --jitter 0.15 --seed 7
# live pixel check before clicking (RRGGBB + optional region)
ahk-bridge pixels FF8800 --region 800,400,1100,700
# find your game window the AHK way
ahk-bridge windows "ahk_exe RobloxPlayerBeta.exe"
# record your own inputs -> macro.json + recorded.ahk
ahk-bridge record --seconds 15 --out macro.json --ahk recorded.ahk
```

## AHK v2 surface (v0.7)

- Hotkeys (`F1::` block + single-line), hotstrings, dynamic hotkeys and
  timers (positive recurring, negative one-shot, `0` off).
- `Send` family + `{Enter}{F1}{Space}{a down}` sequences, `Click`/
  `MouseClick`, `MouseMove`, `Sleep`.
- `Loop N-or-var {}` / `Loop {}`, `While`, `If`/`Else If`/`Else`, `For`,
  `Switch`, `Try`/`Catch`/`Finally`, `Break`/`Continue`, functions,
  classes and includes.
- `x := expr` (arithmetic, `Random(a,b)`, strings, vars), objects,
  arrays, maps.
- `MsgBox`, live `PixelSearch` (mss, `FoundX`/`FoundY`), image search,
  screen capture and `WinActivate` (Hyprland match, else logged).
- GUI: `Gui`, controls, tabs, `Show`/`Submit`, events, absolute and
  relative positioning; lazy PySide6 with headless fallback.
- OS bridge: clipboard, `WinExist`/`WinGetPos`/`WinGetClientPos`/
  `WinGetTitle`, `WinClose`/`WinKill`/`WinMove`/`WinSetTransparent`,
  `ControlGet*`, PIDs/process names, `TargetError` on missing targets.
- Memory/DllCall: bounded `Buffer`, `NumGet`/`NumPut`, string helpers,
  and a documented whitelist for timing, process identity, system
  metrics, locale/date/text and selected structure writes. GDI+/COM are
  explicit display-only/no-op gaps.

## Hyprland integration

`integrations/` ships a compositor snippet, `.desktop` entry (portal
app-id), systemd user service, and `ahk-wine.sh` (run scripts with real
AHK under Wine for parity checks). Verified on CachyOS + Hyprland 0.56
(Wayland): `ahk-bridge check` → `detected_backend: uinput`, SUPER+F1
keybind firing `~/macros/farm.ahk`. See `docs/INSTALL.md`.

## Real AHK v2 under Wine (parity / fallback)

The bridge covers farming loops natively, but genuine AutoHotkey 2 runs
fine under Wine for anything exotic:

```bash
# portable install (tested: v2.0.30 + wine-11.19)
curl -L -o ahk.zip https://github.com/AutoHotkey/AutoHotkey/releases/download/v2.0.30/AutoHotkey_2.0.30.zip
unzip ahk.zip -d ~/Apps/AutoHotkey-v2
wine ~/Apps/AutoHotkey-v2/AutoHotkey64.exe your.ahk   # or:
integrations/ahk-wine.sh your.ahk
```

Tip: run Wine games in a virtual desktop (`wine explorer
/desktop=Game,1280x720`) so tiling never resizes the game mid-macro.

## Safety

Master abort `Escape` / `Ctrl+Alt+C` → `Runtime.abort()` unwinds loops.
Infinite `Loop {}` is capped by `max_loop`; SUPER+SHIFT+F1 keybind
(`pkill -f 'ahk-bridge run'`) stops looping runs on Hyprland. The census
never touches the real Natro tree or live desktop.

## Docs

- `HANDOFF-v07-os.md` — current verified state, limitations, v0.8 plan
- `docs/CENSUS-v0.7.md` — Natro census and known-gap taxonomy
- `docs/CENSUS-v0.6.md` — previous baseline
- `docs/GUI-DECISION.md` — PySide6 measurement and decision
- `docs/INSTALL.md` — udev/portal setup + troubleshooting
- `ARCHITECTURE.md` — diagram, stack choices, layout
- `integrations/` — Hyprland snippet, desktop entry, systemd unit, Wine wrapper

## Roadmap

- **v0.8:** real Natro startup with config/GUI/timers/submacros/main loop,
  then a measured latency/CPU/RSS soak.
- **v1.0:** capability matrix with no `unknown` rows, covering windows,
  clipboard, memory/DllCall, COM/WinHttp, GDI+/vision, timers, IPC and
  input. Documented blockers stay visible.
