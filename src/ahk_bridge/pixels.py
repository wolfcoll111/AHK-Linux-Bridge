"""Pixel search. Wayland path: PipeWire ScreenCast via portal (needs user consent);
X11 path: mss/shm. v0.1 ships the search math + mss hook; portal capture lands in v0.2."""
from __future__ import annotations


def find_color(pixels: bytes, w: int, h: int, rgb: tuple[int, int, int], tol: int = 0):
    """pixels: RGB bytes row-major. Returns (x, y) or None. Pure-python, tested."""
    return find_color_in_region(pixels, w, h, rgb, 0, 0, w - 1, h - 1, tol)


def find_color_in_region(pixels: bytes, w: int, h: int, rgb: tuple[int, int, int],
                         x1: int = 0, y1: int = 0, x2: int | None = None,
                         y2: int | None = None, tol: int = 0):
    """Search sub-rectangle (inclusive). Returns (x, y) or None."""
    r0, g0, b0 = rgb
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = w - 1 if x2 is None else min(w - 1, x2)
    y2 = h - 1 if y2 is None else min(h - 1, y2)
    if x2 < x1 or y2 < y1:
        return None
    for y in range(y1, y2 + 1):
        idx = (y * w + x1) * 3
        for x in range(x1, x2 + 1):
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
