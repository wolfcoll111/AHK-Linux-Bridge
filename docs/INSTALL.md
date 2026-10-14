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
```

## 6. Troubleshooting
| Symptom | Fix |
|---|---|
| `PermissionError: /dev/uinput not writable` | redo step 2, re-login, run `ahk-bridge check` |
| Portal dialog never appears (old GNOME) | upgrade to GNOME ≥48 / Plasma ≥6, or use X11 session + `--backend x11` |
| Wine/Proton game ignores input | run game in XWayland/virtual-desktop; target via `ahk_exe` proc-name match |
| Macros lock input | hit `Escape` (master abort); loops unwind at next statement |
