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
import os
import threading

from PIL import Image

_lock = threading.RLock()
_bitmaps: dict[int, Image.Image] = {}
_rgb_cache: dict[int, object] = {}
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


def from_file(path) -> int:
    """Load an image file into a bitmap handle (native ImageSearch helper).

    Uses a Windows-style case-insensitive fallback so a corpus copied from
    Windows still finds ``nm_image_assets\\Died.png`` for ``died.png``.
    """
    name = str(path)
    if not name:
        raise ValueError("empty image path")
    if not os.path.exists(name):
        # Local import keeps vision usable without the include machinery.
        from .includes import _ci_resolve
        hit = _ci_resolve(os.path.abspath(name))
        if hit:
            name = hit
    try:
        image = Image.open(name)
        image.load()
    except Exception as exc:
        raise ValueError(f"cannot load image {path!r}: {exc}") from exc
    return _register(image)


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
    if len(parts) < 4:
        raise ValueError(f"bad region string: {region!r}")
    # Match the AHK wrapper: StrSplit + S[1..4], so a trailing delimiter
    # (Natro has one real 5-part call) is harmless; an empty first four
    # values is what the wrapper rejects with -1.
    parts = parts[:4]
    if any(p.strip() == "" for p in parts):
        raise ValueError(f"bad region string: {region!r}")
    return tuple(_as_int(p) for p in parts)


def _crop(image: Image.Image, region):
    if region is None:
        return image.copy()
    x, y, w, h = region
    # Clip the far edge before clamping the origin so negative coordinates
    # shrink the crop (same intersection math as pixels.screenshot_rgb).
    x2 = min(image.width, x + max(0, w))
    y2 = min(image.height, y + max(0, h))
    x = max(0, x)
    y = max(0, y)
    if x2 <= x or y2 <= y:
        raise ValueError("region lies outside the bitmap")
    return image.crop((x, y, x2, y2))


def from_screen(region=None, grabber=None) -> int:
    """``Gdip_BitmapFromScreen``: capture a region (or the whole screen).

    ``grabber`` is an injection point for deterministic tests: it returns a
    full-screen PIL image, which is then cropped with the same math used for
    live captures.  Live captures go through ``pixels.screenshot_rgb``, which
    uses KWin ScreenShot2 on Wayland and mss on X11.
    """
    parsed = _parse_region(region)
    if grabber is not None:
        image = grabber()
        if not isinstance(image, Image.Image):
            raise TypeError("grabber must return a Pillow Image")
        return _register(_crop(image, parsed))
    from . import pixels as _pixels
    rgb, width, height = _pixels.screenshot_rgb(parsed)
    image = Image.frombytes("RGB", (width, height), rgb)
    return _register(image)


def dispose(handle) -> int:
    """``Gdip_DisposeImage``: free a handle.  0 = success, 1 = invalid."""
    try:
        key = int(handle)
    except (TypeError, ValueError):
        return 1
    with _lock:
        _rgb_cache.pop(key, None)
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


def _parse_color(value):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            return int(value, 0)
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def image_search(haystack, needle, output=None, outer_x1=0, outer_y1=0,
                 outer_x2=0, outer_y2=0, variation=0, trans=None,
                 direction=1, instances=1, line_delim="\n",
                 coord_delim=",") -> tuple[int, str]:
    """Port of ``Gdip_ImageSearch``.

    Returns ``(count, output_list)``.  ``count`` is negative on the same
    validation errors as the AHK wrapper (-1001 null bitmap, -1002 bad
    variation, -1003 negative start coordinate).  OutputList is the exact
    delimiter-joined byte format callers parse with SubStr/InStr.
    """
    hay = _get(haystack)
    ndl = _get(needle)
    if hay is None or ndl is None:
        return -1001, ""
    variation = _as_int(variation, -1)
    if variation < 0 or variation > 255:
        return -1002, ""
    x1, y1 = _as_int(outer_x1, 0), _as_int(outer_y1, 0)
    if x1 < 0 or y1 < 0:
        return -1003, ""
    x2, y2 = _as_int(outer_x2, 0), _as_int(outer_y2, 0)
    direction = _as_int(direction, 1)
    if direction < 1 or direction > 8:
        direction = 1
    instances = _as_int(instances, 1)
    if instances < 0:
        instances = 0
    line_delim = "\n" if line_delim is None else str(line_delim)
    coord_delim = "," if coord_delim is None else str(coord_delim)

    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "pip install 'ahk-linux-bridge[pixels]' for image search") from exc

    hw, hh = hay.size
    nw, nh = ndl.size
    if nw <= 0 or nh <= 0 or nw > hw or nh > hh:
        return 0, ""
    # The AHK wrapper's x2/y2 are the last haystack pixel a match may touch;
    # internally the upper anchor bound is exclusive and one pixel past it.
    max_x2 = hw - nw + 1
    max_y2 = hh - nh + 1
    x2 = max_x2 if x2 == 0 else min(x2 - nw + 1, max_x2)
    y2 = max_y2 if y2 == 0 else min(y2 - nh + 1, max_y2)
    if x2 <= x1 or y2 <= y1:
        return 0, ""

    hay_key = int(haystack)
    hay_rgb = _rgb_cache.get(hay_key)
    if hay_rgb is None:
        hay_rgb = np.asarray(hay.convert("RGB"), dtype=np.uint8)
        _rgb_cache[hay_key] = hay_rgb
    needle_rgba = np.asarray(ndl, dtype=np.uint8)
    needle_rgb = needle_rgba[:, :, :3]
    mask = needle_rgba[:, :, 3] > 0
    trans_rgb = _parse_color(trans)
    if trans_rgb is not None and 0 <= trans_rgb <= 0xFFFFFF:
        tr = np.array([(trans_rgb >> 16) & 0xFF,
                       (trans_rgb >> 8) & 0xFF,
                       trans_rgb & 0xFF], dtype=np.uint8)
        mask = mask & ~np.all(needle_rgb == tr, axis=2)
    if not mask.any():
        # A fully transparent needle has no pixels to compare.  GDI+ would
        # report a match everywhere; we deliberately report none (no caller
        # in the corpus produces this, and "everything matches" is a trap).
        return 0, ""
    first = np.argwhere(mask)[0]
    probe_y, probe_x = int(first[0]), int(first[1])
    probe = needle_rgb[probe_y, probe_x].astype(np.int16)
    selected = needle_rgb[mask]
    exact_all = variation == 0 and bool(mask.all())

    def matches(y: int, x: int) -> bool:
        patch = hay_rgb[y:y + nh, x:x + nw]
        if variation == 0:
            if exact_all:
                return bool(np.array_equal(patch, needle_rgb))
            return bool(np.array_equal(patch[mask], selected))
        diff = np.abs(patch.astype(np.int16) - needle_rgb.astype(np.int16))
        return bool(np.all(diff[mask] <= variation))

    # Filter candidate anchors by the first opaque needle pixel.  For a
    # transparent border the probe is not at (0,0), so offset the haystack
    # window by the probe position.
    region = hay_rgb[y1 + probe_y:y2 + probe_y,
                     x1 + probe_x:x2 + probe_x]
    # Per-channel comparisons are ~20x faster than np.all(region == probe,
    # axis=2) on this numpy build (broadcast reduction over the last axis).
    if variation == 0:
        anchor_ok = ((region[:, :, 0] == probe[0])
                     & (region[:, :, 1] == probe[1])
                     & (region[:, :, 2] == probe[2]))
    else:
        anchor_ok = ((np.abs(region[:, :, 0].astype(np.int16) - probe[0]) <= variation)
                     & (np.abs(region[:, :, 1].astype(np.int16) - probe[1]) <= variation)
                     & (np.abs(region[:, :, 2].astype(np.int16) - probe[2]) <= variation))

    coords: list[tuple[int, int]] = []
    done = False

    if direction <= 4:
        ys = range(y1, y2) if direction in (1, 4) else range(y2 - 1, y1 - 1, -1)
        x_forward = direction in (1, 2)
        for y in ys:
            xs = np.nonzero(anchor_ok[y - y1])[0]
            if not x_forward:
                xs = xs[::-1]
            for xi in xs:
                x = x1 + int(xi)
                if matches(y, x):
                    coords.append((x, y))
                    if instances and len(coords) >= instances:
                        done = True
                        break
            if done:
                break
    else:
        xs = range(x1, x2) if direction in (5, 6) else range(x2 - 1, x1 - 1, -1)
        y_forward = direction in (5, 8)
        for x in xs:
            ys = np.nonzero(anchor_ok[:, x - x1])[0]
            if not y_forward:
                ys = ys[::-1]
            for yi in ys:
                y = y1 + int(yi)
                if matches(y, x):
                    coords.append((x, y))
                    if instances and len(coords) >= instances:
                        done = True
                        break
            if done:
                break

    output = line_delim.join(f"{x}{coord_delim}{y}" for x, y in coords)
    return len(coords), output


def _table_size() -> int:
    """Test/diagnostic hook: number of live bitmaps."""
    with _lock:
        return len(_bitmaps)
