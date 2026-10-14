"""Pixel search. Wayland path: PipeWire ScreenCast via portal (needs user consent);
X11 path: mss/shm. v0.1 ships the search math + mss hook; portal capture lands in v0.2."""
from __future__ import annotations


def find_color(pixels: bytes, w: int, h: int, rgb: tuple[int, int, int], tol: int = 0):
    """pixels: RGB bytes row-major. Returns (x, y) or None. Pure-python, tested."""
    r0, g0, b0 = rgb
    idx = 0
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[idx], pixels[idx + 1], pixels[idx + 2]
            idx += 3
            if abs(r - r0) <= tol and abs(g - g0) <= tol and abs(b - b0) <= tol:
                return (x, y)
    return None


def screenshot_rgb():
    """Hook for mss. Raises with install hint if missing."""
    try:
        import mss
    except ImportError as e:
        raise RuntimeError("pip install 'ahk-linux-bridge[pixels]' for live capture") from e
    with mss.mss() as s:
        shot = s.grab(s.monitors[0])
        return bytes(shot.rgb), shot.width, shot.height
