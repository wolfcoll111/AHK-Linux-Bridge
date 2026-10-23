"""System clipboard integration.

Natro uses ``A_Clipboard`` as a real data channel (Discord IDs, config
URLs, field JSON).  Linux has no single clipboard API, so this module
tries the Wayland tools first, then X11 tools.  Every failure is benign:
the caller keeps the AHK-side variable and logs a verdict once.

The census sets ``AHK_BRIDGE_CENSUS=1`` so hundreds of sandboxed workers
never touch the live clipboard.  Unit tests monkeypatch these functions.
"""
from __future__ import annotations

import os
import shutil
import subprocess

_TIMEOUT = 1.5


def _disabled() -> bool:
    return (os.environ.get("AHK_BRIDGE_CENSUS") == "1"
            or os.environ.get("AHK_BRIDGE_NO_CLIPBOARD") == "1")


def read_text() -> str:
    """Return the current text clipboard, or ``""`` if unavailable."""
    if _disabled():
        return ""
    commands = (
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    )
    for cmd in commands:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return proc.stdout
    return ""


def write_text(text) -> bool:
    """Set the text clipboard.  False means no helper could do it."""
    if _disabled():
        return False
    value = "" if text is None else str(text)
    commands = (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    )
    for cmd in commands:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            proc = subprocess.run(cmd, input=value, text=True,
                                  capture_output=True, timeout=_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return True
    return False
