"""v0.4 vision layer: Gdip-compatible bitmap handles backed by Pillow.

This is a wrapper-level port of the observable Gdip_* behaviour NatroMacro
uses.  It does not emulate GDI+: images live in a process-local handle table
(integer handles starting at 1) and are released explicitly by ``dispose``,
exactly like ``Gdip_DisposeImage`` in the AHK source.
"""
from __future__ import annotations

import base64
import binascii
import io
import threading

from PIL import Image

_lock = threading.RLock()
_bitmaps: dict[int, Image.Image] = {}
_next_handle = 1


def _register(image: Image.Image) -> int:
    """Store an image and return its integer handle (1-based, never 0)."""
    global _next_handle
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    else:
        image = image.copy()
    image.load()
    with _lock:
        handle = _next_handle
        _next_handle += 1
        _bitmaps[handle] = image
    return handle


def _get(handle) -> Image.Image | None:
    """Resolve an AHK bitmap handle; falsy/unknown handles read as null."""
    try:
        key = int(handle)
    except (TypeError, ValueError):
        return None
    if key <= 0:
        return None
    with _lock:
        return _bitmaps.get(key)


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _looks_like_image(raw: bytes) -> bool:
    return (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")
            or raw.startswith(b"GIF8") or raw.startswith(b"BM"))


def from_base64(data) -> int:
    """``Gdip_BitmapFromBase64``: decode PNG/JPEG bytes into a bitmap handle.

    Accepts a str (raw base64 or a ``data:...;base64,`` URI) or bytes.
    """
    if isinstance(data, str):
        raw = data.strip()
        if raw.startswith("data:"):
            comma = raw.find(",")
            raw = raw[comma + 1:] if comma >= 0 else ""
        raw = "".join(raw.split())
        raw = raw.encode("ascii", "ignore")
    else:
        raw = bytes(data)
    if not raw:
        raise ValueError("empty base64 image data")
    if not _looks_like_image(raw):
        try:
            raw = base64.b64decode(raw + b"=" * (-len(raw) % 4), validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"invalid base64 image data: {exc}") from exc
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise ValueError(f"cannot decode image: {exc}") from exc
    return _register(image)


def create_bitmap(width, height) -> int:
    """``Gdip_CreateBitmap``: blank 32-bit bitmap (transparent black)."""
    w, h = _as_int(width, 0), _as_int(height, 0)
    if w <= 0 or h <= 0:
        raise ValueError("bitmap dimensions must be positive")
    return _register(Image.new("RGBA", (w, h), (0, 0, 0, 0)))


def _parse_region(region):
    """Normalise ``"x|y|w|h"`` / ``(x, y, w, h)`` / None / screen number."""
    if region is None or region == "" or region == 0:
        return None
    if isinstance(region, (tuple, list)):
        if len(region) != 4:
            raise ValueError("region needs four values")
        return tuple(_as_int(v) for v in region)
    if isinstance(region, int):
        # Screen number: 0 = whole virtual desktop, 1 = primary monitor.
        return None
    text = str(region).strip()
    if not text:
        return None
    if "|" in text:
        parts = text.split("|")
    elif "," in text:
        parts = text.split(",")
    else:
        # A bare number is a screen selector, same as the AHK form.
        return None
    if len(parts) != 4:
        raise ValueError(f"bad region string: {region!r}")
    return tuple(_as_int(p) for p in parts)


def _crop(image: Image.Image, region):
    if region is None:
        return image.copy()
    x, y, w, h = region
    x = max(0, x)
    y = max(0, y)
    x2 = min(image.width, x + max(0, w))
    y2 = min(image.height, y + max(0, h))
    if x2 <= x or y2 <= y:
        raise ValueError("region lies outside the bitmap")
    return image.crop((x, y, x2, y2))


def from_screen(region=None, grabber=None) -> int:
    """``Gdip_BitmapFromScreen``: capture a region (or the whole screen).

    ``grabber`` is an injection point for deterministic tests: it returns a
    full-screen PIL image, which is then cropped with the same math used for
    live captures.  Live captures use mss directly on the requested region.
    """
    parsed = _parse_region(region)
    if grabber is not None:
        image = grabber()
        if not isinstance(image, Image.Image):
            raise TypeError("grabber must return a Pillow Image")
        return _register(_crop(image, parsed))
    try:
        import mss
    except ImportError as exc:  # pragma: no cover - depends on host install
        raise RuntimeError(
            "pip install 'ahk-linux-bridge[pixels]' for live capture") from exc
    with mss.mss() as s:
        if parsed is None:
            shot = s.grab(s.monitors[0])
        else:
            x, y, w, h = parsed
            x, y = max(0, x), max(0, y)
            if w <= 0 or h <= 0:
                raise ValueError("capture region must have positive size")
            shot = s.grab({"left": x, "top": y, "width": w, "height": h})
    image = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
    return _register(image)


def dispose(handle) -> int:
    """``Gdip_DisposeImage``: free a handle.  0 = success, 1 = invalid."""
    try:
        key = int(handle)
    except (TypeError, ValueError):
        return 1
    with _lock:
        if key in _bitmaps:
            del _bitmaps[key]
            return 0
    return 1


def dimensions(handle) -> tuple[int, int] | None:
    """``Gdip_GetImageDimensions``: (width, height) or None for a null handle."""
    image = _get(handle)
    return None if image is None else image.size


def width(handle) -> int:
    dims = dimensions(handle)
    return dims[0] if dims else 0


def height(handle) -> int:
    dims = dimensions(handle)
    return dims[1] if dims else 0


def _table_size() -> int:
    """Test/diagnostic hook: number of live bitmaps."""
    with _lock:
        return len(_bitmaps)
