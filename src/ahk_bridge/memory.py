"""Small, bounded AHK-style memory buffers.

Natro uses ``Buffer``/``NumGet``/``NumPut`` for a handful of OS structures
(window placement, RAM status, date strings) and Gdip_All uses them heavily
for bitmap internals.  We do not expose arbitrary process memory: buffers are
Python bytearrays with synthetic pointers, every access is bounds-checked, and
unknown pointers simply read as zero.  That is enough for real struct I/O
without pretending to be ``VirtualAlloc``.
"""
from __future__ import annotations

import struct

_BUFFERS: dict[int, "AhkBuffer"] = {}
_NEXT_PTR = 0x10000000

_TYPE_FORMATS = {
    "char": "b", "uchar": "B", "int8": "b", "uint8": "B",
    "short": "h", "ushort": "H", "int16": "h", "uint16": "H",
    "int": "i", "uint": "I", "int32": "i", "uint32": "I",
    "int64": "q", "uint64": "Q", "ptr": "Q", "uptr": "Q",
    "float": "f", "double": "d",
}


class AhkBuffer:
    """A bounded byte buffer with an AHK-compatible ``.Ptr`` property."""

    def __init__(self, size=0, fill=0):
        global _NEXT_PTR
        try:
            size = max(0, int(size))
        except (TypeError, ValueError):
            size = 0
        try:
            fill = int(fill) & 0xFF
        except (TypeError, ValueError):
            fill = 0
        self.size = size
        self.data = bytearray([fill]) * size
        self.ptr = _NEXT_PTR
        _NEXT_PTR += max(1, size + 16)
        _BUFFERS[self.ptr] = self

    def ahk_get(self, key):
        low = str(key).lower()
        if low == "ptr":
            return self.ptr
        if low == "size":
            return self.size
        return ""

    def ahk_get_property(self, key):
        return self.ahk_get(key)

    def __len__(self):
        return self.size

    def __repr__(self):
        return f"Buffer({self.size}, 0x{self.ptr:x})"


def resolve(source):
    """Return ``(buffer, base_offset)`` for a Buffer or synthetic pointer."""
    if isinstance(source, AhkBuffer):
        return source, 0
    try:
        ptr = int(source)
    except (TypeError, ValueError):
        return None, 0
    for base, buf in _BUFFERS.items():
        if base <= ptr < base + max(1, buf.size):
            return buf, ptr - base
    return None, 0


def read(source, offset=0, type_name="UPtr"):
    buf, base = resolve(source)
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        return 0
    fmt = _TYPE_FORMATS.get(str(type_name).lower(), "Q")
    width = struct.calcsize("<" + fmt)
    if buf is None or base + offset < 0 or base + offset + width > buf.size:
        return 0
    try:
        return struct.unpack_from("<" + fmt, buf.data, base + offset)[0]
    except struct.error:
        return 0


def write(source, offset, type_name, value):
    buf, base = resolve(source)
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        return 0
    fmt = _TYPE_FORMATS.get(str(type_name).lower(), "Q")
    width = struct.calcsize("<" + fmt)
    if buf is None or base + offset < 0 or base + offset + width > buf.size:
        return 0
    try:
        if fmt in ("f", "d"):
            value = float(value)
        else:
            value = int(value)
        struct.pack_into("<" + fmt, buf.data, base + offset, value)
        return width
    except (TypeError, ValueError, OverflowError, struct.error):
        return 0


def read_string(source, length=None, encoding="UTF-16"):
    buf, base = resolve(source)
    if buf is None:
        return ""
    data = bytes(buf.data[base:])
    enc = _encoding(encoding)
    if length is not None:
        try:
            n = max(0, int(length))
        except (TypeError, ValueError):
            n = 0
        # Length is in characters for UTF-16 and bytes for byte encodings.
        if enc == "utf-16-le":
            data = data[:n * 2]
        else:
            data = data[:n]
    try:
        text = data.decode(enc, errors="replace")
    except (LookupError, UnicodeError):
        return ""
    return text.split("\x00", 1)[0]


def write_string(source, text, encoding="UTF-16", length=None):
    buf, base = resolve(source)
    if buf is None:
        return 0
    enc = _encoding(encoding)
    raw = str(text).encode(enc, errors="replace") + (b"\x00\x00" if enc == "utf-16-le" else b"\x00")
    if length is not None:
        try:
            n = max(0, int(length))
        except (TypeError, ValueError):
            n = 0
        raw = raw[:n * 2] if enc == "utf-16-le" else raw[:n]
    end = base + len(raw)
    if end > buf.size:
        raw = raw[:max(0, buf.size - base)]
        end = base + len(raw)
    buf.data[base:end] = raw
    return len(raw)


def allocate_string(text, encoding="UTF-16"):
    enc = _encoding(encoding)
    raw = str(text).encode(enc, errors="replace") + (b"\x00\x00" if enc == "utf-16-le" else b"\x00")
    buf = AhkBuffer(len(raw) + 2, 0)
    buf.data[:len(raw)] = raw
    return buf


def _encoding(name):
    low = str(name or "UTF-16").lower().replace("_", "-")
    if low in ("utf-16", "utf16", "utf-16-le", "unicode", "cp1200"):
        return "utf-16-le"
    if low in ("utf-8", "utf8", "cp65001"):
        return "utf-8"
    if low in ("cp0", "ansi", "acp", "latin-1", "latin1"):
        return "latin-1"
    return "utf-16-le"
