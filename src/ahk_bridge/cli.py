"""CLI: run / check / record / windows / pixels."""
from __future__ import annotations
import argparse
import json
import sys
import time
from .parser import parse_script
from .includes import load_script
from .runtime import Runtime
from .input_abstract import InputSimulator


def cmd_run(args) -> int:
    if args.no_includes:
        script = parse_script(open(args.script, encoding="utf-8-sig").read())
        expanded = None
    else:
        script, expanded = load_script(args.script)
    if args.list_hotkeys:
        for hk in script.hotkeys:
            print(f"{hk.key}: {len(hk.body)} statements")
        for hs in script.hotstrings:
            print(f"hotstring :*:{hs.trigger} -> {hs.replacement}")
        return 0
    try:
        sim = InputSimulator(backend=args.backend)
    except (PermissionError, RuntimeError) as e:
        print(f"backend error: {e}", file=sys.stderr)
        return 2
    script_args = list(getattr(args, "script_args", []) or [])
    if script_args[:1] == ["--"]:
        script_args = script_args[1:]
    screen_size = None
    try:
        from . import pixels
        _, _, width, height = pixels.screen_size()
        if width > 0 and height > 0:
            screen_size = (width, height)
    except Exception:
        pass
    rt = Runtime(script, sim, max_loop=args.max_loop, jitter=args.jitter,
                 seed=args.seed, script_path=args.script,
                 args=script_args, screen_size=screen_size)
    try:
        repeats = max(1, args.repeat)
        for rep in range(repeats):
            if args.hotkey:
                ok = rt.fire_hotkey(args.hotkey)
                if rep == 0:
                    print(f"hotkey {args.hotkey!r}: {'fired' if ok else 'not found'}")
                if not ok:
                    return 1
            else:
                rt.run_auto()
            if args.delay_ms and rep < repeats - 1:
                sim.sleep_ms(args.delay_ms)
        for line in rt.logs:
            print(line)
        if isinstance(getattr(sim, "log", None), list):
            print(f"[backend={sim.backend_name} events={len(sim.log)}]")
        return 0
    except Exception as e:
        print(f"aborted: {e}", file=sys.stderr)
        return 3
    finally:
        sim.close()


def cmd_check(_args) -> int:
    info = InputSimulator.check_permissions()
    print(json.dumps(info, indent=2))
    if not info["uinput_writable"]:
        print("\nHINT: install udev rule per docs/INSTALL.md to enable uinput injection.")
    return 0


def cmd_record(args) -> int:
    """Live-record keyboard/mouse via evdev for N seconds -> JSON + AHK."""
    from .recorder import Recorder
    try:
        import evdev
    except ImportError:
        print("record needs python-evdev: pip install 'ahk-linux-bridge[uinput]'", file=sys.stderr)
        return 2
    import os
    if not os.access("/dev/input/event0", os.R_OK):
        print("record needs read access to /dev/input/event* (add user to 'input' group, then re-login).",
              file=sys.stderr)
        return 2
    rec = Recorder()
    devs = [evdev.InputDevice(p) for p in evdev.list_devices()]
    if not devs:
        print("no input devices found", file=sys.stderr)
        return 1
    print(f"recording {len(devs)} device(s) for {args.seconds}s "
          f"(type/click/move; Ctrl+C to stop early)...")
    deadline = time.monotonic() + args.seconds
    last_pos = [None]
    try:
        from select import select
        while time.monotonic() < deadline:
            r, _, _ = select(devs, [], [], 0.5)
            for dev in r:
                for ev in dev.read():
                    if ev.type == evdev.ecodes.EV_KEY and ev.value == 1:
                        try:
                            name = evdev.ecodes.KEY[ev.code]
                        except KeyError:
                            name = str(ev.code)
                        key = name[4:] if name.startswith("KEY_") else name
                        if key in ("ESC",):
                            print("Escape pressed: stopping.")
                            raise KeyboardInterrupt()
                        rec.key(key.lower() if len(key) == 1 else key)
                    elif ev.type == evdev.ecodes.EV_KEY and ev.code in (
                            evdev.ecodes.BTN_LEFT, evdev.ecodes.BTN_RIGHT,
                            evdev.ecodes.BTN_MIDDLE) and ev.value == 1:
                        btn = {evdev.ecodes.BTN_LEFT: "left",
                               evdev.ecodes.BTN_RIGHT: "right",
                               evdev.ecodes.BTN_MIDDLE: "middle"}[ev.code]
                        rec.click(btn)
                    elif ev.type == evdev.ecodes.EV_REL:
                        pass  # relative motion is too noisy; sampled below
            # sample absolute pointer (Wayland-safe per compositor)
            pos = _cursor_pos()
            if pos is not None:
                x, y = pos
                if last_pos[0] != (x, y):
                    if last_pos[0] is not None:
                        rec.move(x, y)
                    last_pos[0] = (x, y)
    except KeyboardInterrupt:
        pass
    with open(args.out, "w") as f:
        f.write(rec.to_json())
    ahk_text = rec.to_ahk()
    if args.ahk:
        with open(args.ahk, "w") as f:
            f.write(ahk_text)
    print(f"saved {len(rec.events)} events -> {args.out}"
          + (f" + {args.ahk}" if args.ahk else ""))
    print(ahk_text)
    return 0


def cmd_windows(args) -> int:
    """List windows (Hyprland, else X11/XWayland via xdotool) optionally
    filtered by ahk_exe/class/title spec."""
    from . import window_match as wm
    import shutil
    import subprocess
    wins: list[dict] = []
    if shutil.which("hyprctl"):
        # NOTE: hyprctl may exist without a Hyprland session (multi-DE boxes);
        # only trust it when it actually returns clients.
        try:
            out = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True,
                                 text=True, timeout=5)
            if out.returncode == 0:
                clients = json.loads(out.stdout or "[]")
                wins = [{"exe": c.get("initialClass", ""), "class": c.get("class", ""),
                         "title": c.get("title", ""), "app_id": c.get("class", ""),
                         "address": c.get("address", "")} for c in clients]
        except Exception:
            pass
    if not wins and shutil.which("xdotool"):
        # KDE Plasma / GNOME X11 / XWayland: enumerate visible X windows.
        try:
            out = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", ""],
                                 capture_output=True, text=True, timeout=5)
            for wid in (out.stdout or "").split():
                if not wid.strip().isdigit():
                    continue
                name = subprocess.run(["xdotool", "getwindowname", wid],
                                      capture_output=True, text=True,
                                      timeout=5).stdout.strip()
                cls = subprocess.run(["xdotool", "getwindowclassname", wid],
                                     capture_output=True, text=True,
                                     timeout=5).stdout.strip()
                wins.append({"exe": cls, "class": cls, "title": name,
                             "app_id": cls, "address": wid})
        except Exception as e:
            print(f"windows error: {e}", file=sys.stderr)
            return 1
    else:
        print("windows needs hyprctl (Hyprland) or xdotool (X11/XWayland)", file=sys.stderr)
        return 2
    if args.spec:
        wins = wm.find_window(args.spec, wins)
    for w in wins:
        print(f"{w['address']}  [{w['class']}] {w['title'][:80]}")
    if not wins:
        print("(no matches)")
    return 0


def cmd_pixels(args) -> int:
    """Live PixelSearch for RRGGBB color; prints coordinates or not-found."""
    from . import pixels as px
    import re
    color = args.color.strip().lstrip("#")
    m = re.match(r"0[xX]([0-9a-fA-F]{6})$", args.color.strip())
    if m:
        color = m.group(1)
    if not re.match(r"^[0-9a-fA-F]{6}$", color):
        print(f"bad color {args.color!r}: use RRGGBB (e.g. FF8800)", file=sys.stderr)
        return 2
    rgb = (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
    try:
        buf, w, h = px.screenshot_rgb()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.region:
        try:
            x1, y1, x2, y2 = (int(v) for v in args.region.split(","))
        except ValueError:
            print("--region must be x1,y1,x2,y2", file=sys.stderr)
            return 2
        hit = px.find_color_in_region(buf, w, h, rgb, x1, y1, x2, y2, tol=args.tol)
    else:
        hit = px.find_color(buf, w, h, rgb, tol=args.tol)
    if hit:
        print(f"found {color} at {hit[0]},{hit[1]} (screen {w}x{h})")
        return 0
    print(f"color {color} not found (screen {w}x{h})")
    return 1


def _cursor_pos():
    """Current pointer (x, y) or None. Hyprland first, xdotool (X11/XWayland)
    as fallback for KDE Plasma / GNOME."""
    import shutil
    import subprocess
    try:
        out = subprocess.run(["hyprctl", "cursorpos"], capture_output=True,
                             text=True, timeout=2)
        if out.returncode == 0:
            vals = out.stdout.strip().replace(",", " ").split()
            return int(vals[0]), int(vals[1])
    except Exception:
        pass
    if shutil.which("xdotool"):
        try:
            out = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                                 capture_output=True, text=True, timeout=2)
            xy = {}
            for line in (out.stdout or "").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    xy[k.strip()] = v.strip()
            return int(xy["X"]), int(xy["Y"])
        except Exception:
            pass
    return None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ahk-bridge",
                                 description="AHK v2 macro engine for Linux")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run an .ahk script (auto-section or one hotkey)")
    r.add_argument("script")
    r.add_argument("script_args", nargs=argparse.REMAINDER,
                   help="arguments exposed to the script as A_Args "
                        "(use -- before them)")
    r.add_argument("--backend", choices=["x11", "uinput", "dry"], default=None)
    r.add_argument("--no-includes", action="store_true",
                   help="parse the file without expanding #Include directives")
    r.add_argument("--hotkey", default=None, help="fire single hotkey instead of auto-section")
    r.add_argument("--repeat", type=int, default=1, help="repeat whole run N times (AFK loops)")
    r.add_argument("--delay-ms", type=int, default=0, help="sleep between --repeat runs")
    r.add_argument("--jitter", type=float, default=0.0,
                   help="randomize Sleep by fraction, e.g. 0.2 = ±20%% (anti-AFK)")
    r.add_argument("--seed", type=int, default=None, help="RNG seed for --jitter/Random()")
    r.add_argument("--max-loop", type=int, default=10_000, help="cap for infinite Loop{}")
    r.add_argument("--list-hotkeys", action="store_true", help="list hotkeys/hotstrings and exit")
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("check", help="show backend + permission status")
    c.set_defaults(fn=cmd_check)
    rec = sub.add_parser("record", help="record input via evdev -> JSON + AHK")
    rec.add_argument("--out", default="macro.json")
    rec.add_argument("--ahk", default="recorded.ahk")
    rec.add_argument("--seconds", type=int, default=10)
    rec.set_defaults(fn=cmd_record)
    w = sub.add_parser("windows", help="list Hyprland windows, filter by ahk spec")
    w.add_argument("spec", nargs="?", default=None,
                   help='e.g. "ahk_exe RobloxPlayerBeta.exe" or plain title substring')
    w.set_defaults(fn=cmd_windows)
    p = sub.add_parser("pixels", help="live pixel search for RRGGBB color")
    p.add_argument("color", help="RRGGBB, e.g. FF8800")
    p.add_argument("--tol", type=int, default=0)
    p.add_argument("--region", default=None, help="x1,y1,x2,y2")
    p.set_defaults(fn=cmd_pixels)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
