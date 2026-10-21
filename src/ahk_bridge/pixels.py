"""Pixel search + live screen capture.

Wayland/KDE: ``org.kde.KWin.ScreenShot2`` over D-Bus returns raw pixels with
no portal prompt.  X11/other: mss/shm.  The KWin path needs ``dbus-next``
(part of the ``pixels`` extra); without it we fall back to mss.

Why not mss on Wayland: mss reads the XWayland root window, which a
compositing Wayland session leaves black.  Measured on this PC: a full
1920x1080 mss grab is 8 MB of zeros, while KWin ScreenShot2 returns the real
desktop (verified pixel-for-pixel against a shown PNG).
"""
from __future__ import annotations

import asyncio
import os
import threading

_kwin_lock = threading.Lock()
_kwin_state = "unknown"  # unknown | ready | unavailable
_kwin_loop = None
_kwin_bus = None
_screen_size = None


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


def _kwin_start() -> bool:
    """Connect to KWin's ScreenShot2 service once, on a daemon event loop."""
    global _kwin_state, _kwin_loop, _kwin_bus
    if _kwin_state != "unknown":
        return _kwin_state == "ready"
    with _kwin_lock:
        if _kwin_state != "unknown":
            return _kwin_state == "ready"
        if not os.environ.get("WAYLAND_DISPLAY"):
            _kwin_state = "unavailable"
            return False
        try:
            from dbus_next.aio import MessageBus
        except ImportError:
            _kwin_state = "unavailable"
            return False
        ready = threading.Event()
        result: dict = {}

        def runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                bus = loop.run_until_complete(
                    MessageBus(negotiate_unix_fd=True).connect())
                result["bus"] = bus
                result["loop"] = loop
            except Exception as exc:  # pragma: no cover - host dependent
                result["error"] = exc
            finally:
                ready.set()
            if "bus" in result:
                loop.run_forever()
                result["bus"].disconnect()
                loop.close()

        threading.Thread(target=runner, daemon=True, name="kwin-capture").start()
        if not ready.wait(timeout=5) or "bus" not in result:
            _kwin_state = "unavailable"
            return False
        _kwin_loop = result["loop"]
        _kwin_bus = result["bus"]
        _kwin_state = "ready"
        return True


def _decode_kwin(data: bytes, width: int, height: int, stride: int,
                 fmt: int) -> tuple[bytes, int, int]:
    """Decode KWin's raw QImage buffer to tightly packed RGB bytes.

    KWin returns QImage formats: 16 is RGBX8888 (observed on Plasma 6.8),
    4/5/6 are BGRA in memory, 13 is RGB888 and 29 is BGR888.
    """
    if width <= 0 or height <= 0:
        raise ValueError("capture has empty size")
    if stride < width * 3 or len(data) < stride * height:
        raise ValueError("short KWin capture buffer")
    from PIL import Image

    if stride == width * 4:
        mode = "BGRA" if fmt in (4, 5, 6) else "RGBA"
        image = Image.frombuffer("RGBA", (width, height), data,
                                 "raw", mode, stride, 1)
        return image.convert("RGB").tobytes(), width, height
    if stride == width * 3:
        mode = "BGR" if fmt == 29 else "RGB"
        image = Image.frombuffer("RGB", (width, height), data,
                                 "raw", mode, stride, 1)
        return image.tobytes(), width, height
    raise ValueError(f"unsupported KWin stride {stride} for width {width}")


def _kwin_capture(region=None):
    """Capture via KWin ScreenShot2.  Returns (rgb, w, h) or None."""
    if not _kwin_start():
        return None
    from dbus_next import Message, MessageType

    read_fd, write_fd = os.pipe()
    chunks: list[bytes] = []

    def reader():
        try:
            while True:
                chunk = os.read(read_fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(read_fd)

    thread = threading.Thread(target=reader, daemon=True, name="kwin-read")
    thread.start()
    if region is None:
        member, signature, body = "CaptureActiveScreen", "a{sv}h", [{}, 0]
    else:
        x, y, width, height = (int(v) for v in region)
        member, signature, body = (
            "CaptureArea", "iiuua{sv}h", [x, y, width, height, {}, 0])
    try:
        msg = Message(
            destination="org.kde.KWin",
            path="/org/kde/KWin/ScreenShot2",
            interface="org.kde.KWin.ScreenShot2",
            member=member,
            signature=signature,
            body=body,
            unix_fds=[write_fd],
        )
        future = asyncio.run_coroutine_threadsafe(_kwin_bus.call(msg), _kwin_loop)
        reply = future.result(timeout=10)
    except Exception:
        return None
    finally:
        try:
            os.close(write_fd)
        except OSError:
            pass
    thread.join(timeout=5)
    if reply.message_type != MessageType.METHOD_RETURN:
        return None
    try:
        results = reply.body[0]
        width = int(results["width"].value)
        height = int(results["height"].value)
        stride = int(results["stride"].value)
        fmt = int(results["format"].value)
    except (IndexError, KeyError, AttributeError, TypeError):
        return None
    try:
        return _decode_kwin(b"".join(chunks), width, height, stride, fmt)
    except ValueError:
        return None


def _mss_capture(region=None):
    """X11/fallback capture.  Returns (rgb, w, h)."""
    try:
        import mss
    except ImportError as exc:
        raise RuntimeError(
            "pip install 'ahk-linux-bridge[pixels]' for live capture") from exc
    opener = getattr(mss, "MSS", None) or mss.mss
    with opener() as s:
        if region is None:
            shot = s.grab(s.monitors[0])
        else:
            x, y, width, height = region
            shot = s.grab({"left": x, "top": y, "width": width, "height": height})
    return bytes(shot.rgb), shot.width, shot.height


def screen_size():
    """Return ``(left, top, width, height)`` of the virtual desktop.

    Uses mss only for geometry (its pixels are black on Wayland, its monitor
    list is still correct).  ``(0, 0, 0, 0)`` means unknown.
    """
    global _screen_size
    if _screen_size is None:
        try:
            import mss
            opener = getattr(mss, "MSS", None) or mss.mss
            with opener() as s:
                m = s.monitors[0]
            _screen_size = (int(m["left"]), int(m["top"]),
                            int(m["width"]), int(m["height"]))
        except Exception:
            _screen_size = (0, 0, 0, 0)
    return _screen_size


def _clamp_region(region):
    """Clamp ``(x, y, w, h)`` to the desktop; None when fully outside."""
    x, y, width, height = (int(v) for v in region)
    if width <= 0 or height <= 0:
        raise ValueError("capture region must have positive size")
    left, top, desk_w, desk_h = screen_size()
    if desk_w <= 0 or desk_h <= 0:
        return (max(0, x), max(0, y), width, height)
    x2 = min(x + width, left + desk_w)
    y2 = min(y + height, top + desk_h)
    x, y = max(x, left), max(y, top)
    width, height = x2 - x, y2 - y
    if width <= 0 or height <= 0:
        return None
    return (x, y, width, height)


def screenshot_rgb(region=None):
    """Capture RGB pixels.  ``region`` is ``(x, y, w, h)`` or None (full screen).

    Prefers KWin ScreenShot2 on Wayland (mss reads black there); falls back to
    mss on X11 or when dbus-next/KWin are unavailable.  Regions that go off
    the desktop are clamped; a fully off-screen region is a 1x1 black frame
    so callers never throw (Gdip_BitmapFromScreen just gets an empty bitmap).
    """
    if region is not None:
        region = _clamp_region(region)
        if region is None:
            return b"\x00\x00\x00", 1, 1
    shot = _kwin_capture(region)
    if shot is not None:
        return shot
    return _mss_capture(region)
