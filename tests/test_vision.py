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


# ---------------------------------------------------------------------------
# Phase 1: search core, synthetic fixtures only.
# ---------------------------------------------------------------------------

def _pattern(w=8, h=6, seed=0):
    image = Image.new("RGB", (w, h))
    pixels = image.load()
    for y in range(h):
        for x in range(w):
            pixels[x, y] = ((17 + seed + 7 * x + 11 * y) % 220 + 20,
                            (31 + seed + 13 * x + 5 * y) % 200 + 25,
                            (47 + seed + 3 * x + 17 * y) % 190 + 30)
    return image


def _paste(canvas, needle, x, y):
    canvas.paste(needle, (x, y))
    return canvas


def _handles(canvas, needle):
    return vision._register(canvas), vision._register(needle)


def test_exact_find_count_and_output_list_bytes():
    needle = _pattern()
    canvas = _paste(Image.new("RGB", (120, 100), (1, 2, 3)), needle, 37, 24)
    hay, ndl = _handles(canvas, needle)
    try:
        count, out = vision.image_search(hay, ndl)
        assert count == 1
        assert out == "37,24"
        assert isinstance(out, str)
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


def test_output_list_custom_delimiters_and_order():
    needle = _pattern(seed=9)
    canvas = Image.new("RGB", (140, 100), (1, 2, 3))
    _paste(canvas, needle, 10, 12)
    _paste(canvas, needle, 90, 60)
    hay, ndl = _handles(canvas, needle)
    try:
        count, out = vision.image_search(
            hay, ndl, instances=0, line_delim="|", coord_delim=";")
        assert count == 2
        assert out == "10;12|90;60"
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


def test_not_present_returns_zero_and_empty_output():
    needle = _pattern(seed=3)
    canvas = Image.new("RGB", (100, 80), (1, 2, 3))
    hay, ndl = _handles(canvas, needle)
    try:
        count, out = vision.image_search(hay, ndl)
        assert (count, out) == (0, "")
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


def test_variation_boundary_inside():
    needle = _pattern(10, 8, seed=5)
    shifted = Image.eval(needle, lambda v: min(255, v + 12))
    canvas = _paste(Image.new("RGB", (120, 90), (1, 2, 3)), shifted, 44, 33)
    hay, ndl = _handles(canvas, needle)
    try:
        count, out = vision.image_search(hay, ndl, variation=12)
        assert (count, out) == (1, "44,33")
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


def test_variation_boundary_outside():
    needle = _pattern(10, 8, seed=5)
    shifted = Image.eval(needle, lambda v: min(255, v + 12))
    canvas = _paste(Image.new("RGB", (120, 90), (1, 2, 3)), shifted, 44, 33)
    hay, ndl = _handles(canvas, needle)
    try:
        count, out = vision.image_search(hay, ndl, variation=11)
        assert (count, out) == (0, "")
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


def test_trans_finds_where_plain_match_fails():
    trans = (255, 0, 255)
    needle = Image.new("RGB", (12, 12), trans)
    pixels = needle.load()
    for y in range(1, 11):
        for x in range(1, 11):
            pixels[x, y] = (10, 200, 30) if (x + y) % 2 else (30, 40, 220)
    canvas = Image.new("RGB", (120, 100), (5, 5, 5))
    # Paste only the opaque core: the transparent border stays background.
    canvas.paste(needle.crop((1, 1, 11, 11)), (50, 40))
    hay, ndl = _handles(canvas, needle)
    try:
        assert vision.image_search(hay, ndl) == (0, "")
        count, out = vision.image_search(hay, ndl, trans=0xFF00FF)
        # The opaque core starts at (50,40); the needle's transparent border
        # means its top-left anchor is one pixel up/left.
        assert (count, out) == (1, "49,39")
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


@pytest.mark.parametrize("direction,expected", [
    (1, (10, 15)),  # top -> left -> right -> bottom
    (2, (60, 70)),  # bottom -> left -> right -> top
    (3, (80, 70)),  # bottom -> right -> left -> top
    (4, (60, 15)),  # top -> right -> left -> bottom
    (5, (10, 15)),  # left -> top -> bottom -> right
    (6, (10, 60)),  # left -> bottom -> top -> right
    (7, (80, 70)),  # right -> bottom -> top -> left
    (8, (80, 20)),  # right -> top -> bottom -> left
])
def test_search_direction_scan_order(direction, expected):
    needle = _pattern(6, 6, seed=13)
    canvas = Image.new("RGB", (100, 90), (1, 2, 3))
    for x, y in ((10, 15), (60, 15), (10, 60), (60, 70), (80, 70), (80, 20)):
        _paste(canvas, needle, x, y)
    hay, ndl = _handles(canvas, needle)
    try:
        count, out = vision.image_search(hay, ndl, direction=direction)
        assert count == 1
        assert out == f"{expected[0]},{expected[1]}"
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


def test_instances_cap_and_find_all():
    needle = _pattern(6, 6, seed=21)
    canvas = Image.new("RGB", (100, 80), (1, 2, 3))
    for x, y in ((10, 10), (50, 30), (80, 60)):
        _paste(canvas, needle, x, y)
    hay, ndl = _handles(canvas, needle)
    try:
        assert vision.image_search(hay, ndl, instances=2) == (2, "10,10\n50,30")
        assert vision.image_search(hay, ndl, instances=0)[0] == 3
        assert vision.image_search(hay, ndl, instances=-4)[0] == 3
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


def test_error_codes_and_null_handles():
    needle = _pattern(5, 5)
    hay, ndl = _handles(Image.new("RGB", (50, 50), (1, 2, 3)), needle)
    try:
        assert vision.image_search(0, ndl) == (-1001, "")
        assert vision.image_search(hay, "") == (-1001, "")
        assert vision.image_search(hay, None) == (-1001, "")
        assert vision.image_search(hay, ndl, variation=-1) == (-1002, "")
        assert vision.image_search(hay, ndl, variation=256) == (-1002, "")
        assert vision.image_search(hay, ndl, outer_x1=-1) == (-1003, "")
        assert vision.image_search(hay, ndl, outer_y1=-2) == (-1003, "")
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


def test_perf_500x500_50x40_needle_under_loop_budget():
    # Natro's tightest farming cadence in the corpus is Sleep 50 (e.g.
    # natro_macro.ahk:8576), so the loop budget is 50 ms.  The handoff
    # requires an order of magnitude of headroom: assert < 5 ms per search.
    import time
    needle = _pattern(50, 40, seed=31)
    canvas = _paste(Image.new("RGB", (500, 500), (1, 2, 3)), needle, 123, 234)
    hay, ndl = _handles(canvas, needle)
    try:
        vision.image_search(hay, ndl)  # warm caches
        samples = []
        for _ in range(7):
            start = time.perf_counter()
            count, out = vision.image_search(hay, ndl)
            samples.append((time.perf_counter() - start) * 1000)
        assert (count, out) == (1, "123,234")
        best = min(samples)
        median = sorted(samples)[len(samples) // 2]
        print(f"\nperf 500x500/50x40: best={best:.3f}ms median={median:.3f}ms")
        assert best < 5.0, f"search too slow: best {best:.3f}ms"
    finally:
        vision.dispose(hay)
        vision.dispose(ndl)


# ---------------------------------------------------------------------------
# Phase 2: runtime wiring (execution through parser + Runtime).
# ---------------------------------------------------------------------------

def _png_b64(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _run_script(text, monkeypatch, screen):
    from ahk_bridge.parser import parse_script
    from ahk_bridge.runtime import Runtime
    from ahk_bridge.backends.dry_backend import DryBackend

    monkeypatch.setattr(vision, "from_screen",
                        lambda region=None: vision._register(screen))
    script = parse_script(text)
    rt = Runtime(script, DryBackend())
    rt.run_auto()
    return rt


def test_runtime_image_search_writes_byref_and_disposes(monkeypatch):
    needle = _pattern(9, 7, seed=41)
    canvas = _paste(Image.new("RGB", (100, 80), (1, 2, 3)), needle, 31, 22)
    b64 = _png_b64(needle)
    baseline = vision._table_size()
    text = (
        'hay := Gdip_BitmapFromScreen("0|0|100|80")\n'
        f'needle := Gdip_BitmapFromBase64("{b64}")\n'
        'n := Gdip_ImageSearch(hay, needle, &list)\n'
        'MsgBox {n}\n'
        'MsgBox {list}\n'
        'Gdip_DisposeImage(hay)\n'
        'Gdip_DisposeImage(needle)\n'
    )
    rt = _run_script(text, monkeypatch, canvas)
    assert rt.vars["n"] == 1
    assert rt.vars["list"] == "31,22"
    assert "MsgBox: 1" in rt.logs
    assert "MsgBox: 31,22" in rt.logs
    assert vision._table_size() == baseline


def test_runtime_omitted_args_keep_positional_meaning(monkeypatch):
    # Variation is argument 7.  If empty slots were dropped, 12 would land on
    # OuterX1 and this shaded needle would not match (variation would be 0).
    needle = _pattern(10, 8, seed=43)
    shifted = Image.eval(needle, lambda v: min(255, v + 12))
    canvas = _paste(Image.new("RGB", (120, 90), (1, 2, 3)), shifted, 44, 33)
    b64 = _png_b64(needle)
    text = (
        'hay := Gdip_BitmapFromScreen("0|0|120|90")\n'
        f'needle := Gdip_BitmapFromBase64("{b64}")\n'
        'n := Gdip_ImageSearch(hay, needle, &list, , , , , 12)\n'
        'MsgBox {n}\n'
        'MsgBox {list}\n'
    )
    rt = _run_script(text, monkeypatch, canvas)
    assert (rt.vars["n"], rt.vars["list"]) == (1, "44,33")


def test_runtime_direction_and_delimiters_land_in_right_slots(monkeypatch):
    needle = _pattern(6, 6, seed=47)
    canvas = Image.new("RGB", (100, 90), (1, 2, 3))
    for x, y in ((10, 15), (80, 70)):
        _paste(canvas, needle, x, y)
    b64 = _png_b64(needle)
    text = (
        'hay := Gdip_BitmapFromScreen("0|0|100|90")\n'
        f'needle := Gdip_BitmapFromBase64("{b64}")\n'
        'n := Gdip_ImageSearch(hay, needle, &list, , , , , 0, , 3, 0, "|", "~")\n'
        'MsgBox {n}\n'
        'MsgBox {list}\n'
    )
    rt = _run_script(text, monkeypatch, canvas)
    assert rt.vars["n"] == 2
    # direction 3 (bottom->right->left->top) sees the lower needle first
    assert rt.vars["list"] == "80~70|10~15"


def test_runtime_dimensions_and_byref_outputs(monkeypatch):
    canvas = Image.new("RGB", (100, 80), (1, 2, 3))
    text = (
        'hay := Gdip_BitmapFromScreen("0|0|100|80")\n'
        'w := Gdip_GetImageWidth(hay)\n'
        'h := Gdip_GetImageHeight(hay)\n'
        'Gdip_GetImageDimensions(hay, &dw, &dh)\n'
        'MsgBox {w}\n'
        'MsgBox {h}\n'
        'MsgBox {dw}\n'
        'MsgBox {dh}\n'
    )
    rt = _run_script(text, monkeypatch, canvas)
    assert (rt.vars["w"], rt.vars["h"], rt.vars["dw"], rt.vars["dh"]) == (100, 80, 100, 80)
    assert rt.logs[-4:] == ["MsgBox: 100", "MsgBox: 80", "MsgBox: 100", "MsgBox: 80"]


def test_runtime_unknown_gdip_stub_logs_once(monkeypatch):
    canvas = Image.new("RGB", (20, 20), (1, 2, 3))
    text = (
        'hay := Gdip_BitmapFromScreen("0|0|20|20")\n'
        'Gdip_FillRectangle(hay, 1, 2, 3, 4)\n'
        'Gdip_FillRectangle(hay, 1, 2, 3, 4)\n'
    )
    rt = _run_script(text, monkeypatch, canvas)
    hits = [line for line in rt.logs if "stub Gdip_FillRectangle()" in line]
    assert len(hits) == 1
