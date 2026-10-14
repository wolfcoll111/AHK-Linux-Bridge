# AHK-Linux-Bridge — AHK v2 macro engine for Linux (Wayland + X11)

Run Windows-style AHK v2 farming/productivity macros on Linux with one input
API that routes to **uinput** (universal) or **XTest** (X11 fallback).

## Quickstart
```bash
pip install -e '.[uinput,portal,pixels]'
sudo cp udev/99-ahk-linux-bridge-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG input $USER   # then re-login
ahk-bridge check
ahk-bridge run examples/farm_loop.ahk --hotkey F1
```

## AFK farming (the reason this exists)
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

## AHK v2 subset (v0.2)
Hotkeys (`F1::` block + single-line), hotstrings (`:*:btw::...`),
`Send` family + `{Enter}{F1}{Space}{a down}` sequences, `Click`/`MouseClick`,
`MouseMove`, `Sleep` (int or var), `Loop N-or-var {}` / `Loop {}`,
`While` / `If cond {} Else {}` / `Break` / `Continue`,
`x := expr` (arithmetic, `Random(a,b)`, strings, vars), functions,
`MsgBox`, live `PixelSearch` (mss, result in `FoundX`/`FoundY`),
`WinActivate` (focuses Hyprland match, else logs). See `examples/`.

## Hyprland integration
`integrations/` ships a compositor snippet, `.desktop` entry (portal app-id),
systemd user service, and `ahk-wine.sh` (run scripts with real AHK under Wine
for parity checks). Verified on CachyOS + Hyprland 0.56 (Wayland):
`ahk-bridge check` → `detected_backend: uinput`, SUPER+F1 keybind firing
`~/macros/farm.ahk`. See `docs/INSTALL.md`.

## Real AHK v2 under Wine (parity / fallback)
The bridge covers farming loops natively, but genuine AutoHotkey 2 runs fine
under Wine for anything exotic:
```bash
# portable install (tested: v2.0.30 + wine-11.19)
curl -L -o ahk.zip https://github.com/AutoHotkey/AutoHotkey/releases/download/v2.0.30/AutoHotkey_2.0.30.zip
unzip ahk.zip -d ~/Apps/AutoHotkey-v2
wine ~/Apps/AutoHotkey-v2/AutoHotkey64.exe your.ahk   # or:
integrations/ahk-wine.sh your.ahk
```
Tip: run Wine games in a virtual desktop (`wine explorer /desktop=Game,1280x720`)
so tiling never resizes the game mid-macro.

## Safety
Master abort `Escape` / `Ctrl+Alt+C` → `Runtime.abort()` unwinds loops.
Infinite `Loop {}` is capped by `max_loop`; SUPER+SHIFT+F1 keybind
(`pkill -f 'ahk-bridge run'`) stops looping runs on Hyprland.

## Docs
- `ARCHITECTURE.md` — diagram, stack choices, layout
- `docs/INSTALL.md` — udev/portal setup + troubleshooting
- `integrations/` — Hyprland snippet, desktop entry, systemd unit, Wine wrapper

## Roadmap
- v0.3: Rust hot-path crate behind same API, PipeWire ScreenCast capture,
  Tauri dashboard, per-window Wine targeting, GlobalShortcuts daemon mode.
