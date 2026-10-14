# Field test: NoNameMacro v1.0.5 (SirLuxi) on CachyOS + Hyprland 0.56 + wine-11.19

Date: 2026-10-14. Tester: opencode agent (dogfooding ahk-bridge v0.2).
Goal: install the most popular TDS macro as easily as possible, see where it
breaks on Linux, and feed every finding back into the bridge.

## Setup (what worked)
- `NoNameSetup.exe` (63 MB, Inno Setup 32-bit) silent-installs cleanly:
  `wine NoNameSetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`
  → `AppData/Local/Programs/NoNameMacro/NoNameMacroV1.0.5.exe` (Nuitka, 64-bit).
- `.desktop` launcher (Wine virtual desktop 1280x720) + icon extraction works.

## Problem 1: .NET (fixed)
App is Nuitka Python + pywebview/WinForms via pythonnet. First boot crashes in
`clr_loader` on wine-mono's stub CLR. `PYWEBVIEW_GUI=cef` is ignored (WinForms
hardcoded). Fix: `winetricks -q dotnet48` (prefix already had dotnet40).
After that the pythonnet crash is gone.

## Problem 2: WebView never paints (partially mitigated by the app itself)
pywebview falls back to MSHTML under Wine ("MSHTML is deprecated" warning) and
the window stays blank. Credit to the devs: the updater detects this
(`"WebView UI unavailable — running headless"` in updater.log) and continues
headless — self-update fully works: downloaded TDSMacroV1.3.1.zip (206 MB),
verified and extracted `current/main.exe` (117 MB). Network + zip + Crypto all
fine under Wine.

## Problem 3 (fatal): memory-reading core needs Windows Roblox (unfixable on Linux)
`main.exe` contains `robloxmemoryapi` (memory offsets, Luau bytecode
decrypt/encrypt) and looks for `RobloxPlayerBeta.exe`. It never boots
(updater: "heartbeat timeout — new app did not boot, rolling back"; direct
launch exits silently, no window). On Linux, Roblox runs via Sober (flatpak,
native client): different process, different memory layout, different mount
namespace — invisible to Wine. Windows Roblox under Wine is blocked by
Hyperion anti-cheat, which is why Sober exists. So no memory-based macro can
work on Linux Roblox, regardless of setup effort.

## Consequence for ahk-bridge
OS-level input injection (uinput) works with ANY client, Sober included —
this test confirms the bridge's coordinate-based approach is the only viable
Linux AFK path. Strategy files (`strategies/*/config.json`) are encrypted
(`TDMCFG1:` blobs), so NoName placements cannot be imported; users re-encode
placements as `.ahk` (see `examples/tds_placement.ahk`).

## Bugs this test found in the bridge (all fixed, with regression tests)
- `Send "{Blind}hello"` typed the literal `{Blind}` → `{Blind}` now stripped.
- `Send "{Enter down}"` (named key + down/up) fell through to literal text →
  now holds/releases via `send_key(name, down=...)`.
- `Send "{LButton}/{RButton}/{MButton}"` unsupported → now clicks.
- `Send "{WheelUp}/{WheelDown}"` unsupported → now scrolls.
- `DryBackend` lacked `scroll()` → added for backend parity.
- New: `tests/test_send_sequences.py` (5 tests), `examples/tds_placement.ahk`.
- Timing re-verified: Sleep drift +2 ms over 2 s; TDS burst exact.
