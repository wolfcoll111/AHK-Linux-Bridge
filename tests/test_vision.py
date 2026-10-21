"""v0.4 vision regression tests.

Phase 0: bitmap lifecycle (handles, base64 decode, synthetic region crop,
dispose loop).  Oracles are Pillow itself and a synthetic canvas, never the
live desktop.
"""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import pytest
from PIL import Image

from ahk_bridge import vision

CORPUS = Path.home() / "Games" / "NatroMacro" / "src"
BITMAPS = CORPUS / "nm_image_assets" / "general" / "bitmaps.ahk"


def _first_bitmap():
    if not BITMAPS.exists():
        pytest.skip("Natro corpus not present on this machine")
    text = BITMAPS.read_text(encoding="utf-8-sig")
    match = re.search(
        r'bitmaps\["([^"]+)"\]\s*:=\s*Gdip_BitmapFromBase64\("([^"]+)"\)',
        text,
    )
    assert match, "no base64 bitmap found in the real asset file"
    return match.group(1), match.group(2)


def _canvas():
    image = Image.new("RGB", (100, 80))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
    return image


def _handle_image(handle):
    image = vision._get(handle)
    assert image is not None
    return image


def test_from_base64_matches_pillow_oracle():
    name, encoded = _first_bitmap()
    raw = base64.b64decode(encoded)
    oracle = Image.open(io.BytesIO(raw))
    oracle.load()

    handle = vision.from_base64(encoded)
    try:
        assert handle > 0
        assert vision.dimensions(handle) == oracle.size
        expected = oracle.convert("RGBA")
        assert _handle_image(handle).tobytes() == expected.tobytes(), name
    finally:
        assert vision.dispose(handle) == 0


def test_from_base64_data_uri_and_bytes():
    image = Image.new("RGB", (7, 5), (12, 34, 56))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    raw = buf.getvalue()
    for payload in (raw, base64.b64encode(raw).decode(),
                    "data:image/png;base64," + base64.b64encode(raw).decode()):
        handle = vision.from_base64(payload)
        try:
            assert vision.dimensions(handle) == (7, 5)
            assert _handle_image(handle).convert("RGB").getpixel((0, 0)) == (12, 34, 56)
        finally:
            vision.dispose(handle)


def test_from_base64_invalid_raises():
    with pytest.raises(ValueError):
        vision.from_base64("not an image")
    with pytest.raises(ValueError):
        vision.from_base64("")


def test_create_bitmap_dimensions_and_pixels():
    handle = vision.create_bitmap(13, 9)
    try:
        assert vision.dimensions(handle) == (13, 9)
        assert _handle_image(handle).getpixel((0, 0)) == (0, 0, 0, 0)
        assert vision.width(handle) == 13
        assert vision.height(handle) == 9
    finally:
        vision.dispose(handle)
    with pytest.raises(ValueError):
        vision.create_bitmap(0, 5)


def test_from_screen_region_crop_math_synthetic():
    canvas = _canvas()
    handle = vision.from_screen("10|20|30|40", grabber=lambda: canvas)
    try:
        expected = canvas.crop((10, 20, 40, 60)).convert("RGBA")
        assert vision.dimensions(handle) == (30, 40)
        assert _handle_image(handle).tobytes() == expected.tobytes()
    finally:
        vision.dispose(handle)


def test_from_screen_full_and_tuple_region():
    canvas = _canvas()
    full = vision.from_screen(None, grabber=lambda: canvas)
    part = vision.from_screen((5, 6, 10, 11), grabber=lambda: canvas)
    try:
        assert vision.dimensions(full) == canvas.size
        assert vision.dimensions(part) == (10, 11)
        expected = canvas.crop((5, 6, 15, 17)).convert("RGBA")
        assert _handle_image(part).tobytes() == expected.tobytes()
    finally:
        vision.dispose(full)
        vision.dispose(part)


def test_dimensions_and_dispose_null_handles():
    for null in (0, "", None, "nope", -5, 999999):
        assert vision.dimensions(null) is None
        assert vision.width(null) == 0
        assert vision.height(null) == 0
        assert vision.dispose(null) == 1


def test_dispose_1000_iteration_table_stays_flat():
    baseline = vision._table_size()
    for _ in range(1000):
        handle = vision.create_bitmap(4, 4)
        assert vision.dispose(handle) == 0
    assert vision._table_size() == baseline
