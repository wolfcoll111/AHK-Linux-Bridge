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

## AHK v2 subset (v0.1)
Hotkeys (`F1::` block + single-line), hotstrings (`:*:btw::...`), `Send`,
`Click`, `MouseMove`, `Sleep`, `Loop N {}`, `While cond {}`, `x := v`,
`funcs`, `MsgBox`, `WinActivate` (best-effort Linux match). See
`examples/` and `ARCHITECTURE.md`.

## Safety
Master abort `Escape` / `Ctrl+Alt+C` → `Runtime.abort()` unwinds loops.
Infinite `Loop {}` is capped by `max_loop` in tests; production daemon
relies on the abort event + watchdog (v0.2).

## Docs
- `ARCHITECTURE.md` — diagram, stack choices, layout
- `docs/INSTALL.md` — udev/portal setup + troubleshooting

## Roadmap
- v0.2: Rust hot-path crate behind same API, evdev-grab recorder,
  PipeWire ScreenCast capture, Tauri dashboard, per-window Wine targeting.
