# Install & permissions — AHK-Linux-Bridge

Works on Wayland and X11. Injection uses kernel `uinput`; hotkeys use the
XDG GlobalShortcuts portal where available.

## 1. Base install
```bash
pip install -e '.[uinput,portal,pixels]'   # evdev + dbus-next + mss
# X11 sessions only, optionally:
pip install -e '.[x11]'
```

## 2. uinput permission (required once, Wayland + X11)
The kernel device `/dev/uinput` is root-only by default.
```bash
sudo cp udev/99-ahk-linux-bridge-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG input $USER
# IMPORTANT: log out and back in (group membership applies at login)
ls -l /dev/uinput   # expect: crw-rw---- 1 root input ...
```
Rule content grants group `input` + `TAG+="uaccess"` (ACL for the active seat):
```
KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput", TAG+="uaccess"
```

## 3. Verify
```bash
ahk-bridge check
# {"uinput_writable": true, "detected_backend": "uinput", ...}
```

## 4. Global hotkeys (Wayland)
- GNOME 48+ / Plasma 6+ / Hyprland (with portal backend): the app requests
  shortcuts via `org.freedesktop.portal.GlobalShortcuts`; the compositor shows
  a consent dialog. Approve once; triggers persist per app-id.
- Needs a `.desktop` app-id (`io.github.ahk-linux-bridge`) for portal identity.
- Fallbacks: X11 `XGrabKey` under X11; evdev-grab (also needs `input` group)
  for compositors without the portal.

## 5. Run
```bash
ahk-bridge run examples/hello.ahk --backend dry        # no perms needed
ahk-bridge run examples/farm_loop.ahk --hotkey F1      # real run
ahk-bridge run examples/afk_farm_advanced.ahk --hotkey F1 --jitter 0.2  # anti-AFK
ahk-bridge run examples/afk_farm_advanced.ahk --list-hotkeys            # inspect
ahk-bridge windows "ahk_exe RobloxPlayerBeta.exe"      # find game window
ahk-bridge pixels FF8800 --region 800,400,1100,700     # live pixel check
ahk-bridge record --seconds 15                         # evdev capture -> .json + .ahk
```

## 5b. CachyOS / Hyprland integration (verified: Hyprland 0.56, Wayland)
```bash
mkdir -p ~/macros && cp examples/afk_farm_advanced.ahk ~/macros/farm.ahk
cp integrations/ahk-bridge.desktop ~/.local/share/applications/
```
Lua-config users (`hyprland.lua` + `custom.lua`): append the binds from
`integrations/hyprland-snippet.conf` in `hl.bind` / `hl.window_rule` form —
SUPER+F1 fires the farm loop, SUPER+SHIFT+F1 kills looping runs — then
`hyprctl reload`. Keybinds use `SUPER+F1` (not bare `F1`) so in-game F1 keeps
working; the script hotkey stays `F1::` and is fired via `--hotkey F1`.

Optional daemon (one macro kept alive by systemd):
```bash
cp integrations/ahk-bridge-daemon.service ~/.config/systemd/user/ahk-bridge@.service
systemctl --user daemon-reload && systemctl --user enable --now ahk-bridge@farm.service
```

## 5c. Real AHK v2 under Wine (parity checks)
```bash
curl -L -o ahk.zip https://github.com/AutoHotkey/AutoHotkey/releases/download/v2.0.30/AutoHotkey_2.0.30.zip
unzip ahk.zip -d ~/Apps/AutoHotkey-v2
integrations/ahk-wine.sh examples/farm_loop.ahk   # genuine AHK 2.0.30 via Wine
```
Verified with wine-11.19. Run Wine games in a virtual desktop so tiling
window managers never resize the game mid-macro:
`wine explorer /desktop=Game,1280x720 game.exe`.

## 5d. KDE Plasma notes (verified: Plasma 6.7 Wayland)
- Backend auto-detects `uinput` (`ahk-bridge check` → `detected_backend: uinput`).
  KWin needs ~2s to route a fresh virtual device, so startup waits
  ~2.5s (override: `AHK_BRIDGE_UINPUT_WAIT=5.0`); verified live via `xev`
  keycodes, system-volume keys, and Super opening Kickoff.
- `WinActivate` / `windows` fall back to `xdotool` (X11/XWayland windows:
  Wine games, AHK Dash). Native Wayland focus is compositor-gated by design.
- `record` samples the pointer via `hyprctl cursorpos`, else
  `xdotool getmouselocation`.
- AHK Dash (needs the UX scripts, not bare no-args):
  `wine ~/Apps/AutoHotkey-v2/AutoHotkey64.exe UX/ui-dash.ahk`
- KWin window rule (GUI, 30s): System Settings → Window Management →
  Window Rules → Add → Window class `explorer.exe` → Size: Apply initially
  `1280x720`. Keeps macro click coordinates stable.
- Screenshots: `spectacle -b -n -o shot.png` (grim is wlroots-only).

## 6. Troubleshooting
| Symptom | Fix |
|---|---|
| `PermissionError: /dev/uinput not writable` | redo step 2, re-login, run `ahk-bridge check` |
| Portal dialog never appears (old GNOME) | upgrade to GNOME ≥48 / Plasma ≥6, or use X11 session + `--backend x11` |
| Wine/Proton game ignores input | run game in XWayland/virtual-desktop; target via `ahk_exe` proc-name match |
| Macros lock input | hit `Escape` (master abort); loops unwind at next statement |
