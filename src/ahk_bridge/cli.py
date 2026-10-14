"""CLI: run / check / record-export."""
from __future__ import annotations
import argparse
import json
import sys
from .parser import parse_script
from .runtime import Runtime
from .input_abstract import InputSimulator


def cmd_run(args) -> int:
    text = open(args.script).read()
    script = parse_script(text)
    try:
        sim = InputSimulator(backend=args.backend)
    except (PermissionError, RuntimeError) as e:
        print(f"backend error: {e}", file=sys.stderr)
        return 2
    rt = Runtime(script, sim)
    try:
        if args.hotkey:
            ok = rt.fire_hotkey(args.hotkey)
            print(f"hotkey {args.hotkey!r}: {'fired' if ok else 'not found'}")
        else:
            rt.run_auto()
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ahk-bridge", description="AHK v2 macro engine for Linux")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run an .ahk script (auto-section or one hotkey)")
    r.add_argument("script")
    r.add_argument("--backend", choices=["x11", "uinput", "dry"], default=None)
    r.add_argument("--hotkey", default=None, help="fire single hotkey instead of auto-section")
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("check", help="show backend + permission status")
    c.set_defaults(fn=cmd_check)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
