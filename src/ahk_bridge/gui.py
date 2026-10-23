"""AHK v2 GUI compatibility layer backed by PySide6.

The runtime imports this module lazily when a script calls ``Gui(...)``.
PySide6 is likewise imported lazily, so headless/non-GUI scripts and unit
tests do not pay its import or memory cost.

Layout is intentionally absolute (AHK Gui options are absolute/relative
coordinates).  Values, control names, events and teardown are real; pixel
perfection is not promised on Wayland, where the compositor controls window
placement.
"""

from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------------
# lazy Qt loading / application singleton
# ---------------------------------------------------------------------------

_qt = None
_qt_failed = False
_app = None
_clickable_label_cls = None
_gui_widget_cls = None


def _load_qt():
    global _qt, _qt_failed
    if _qt is not None:
        return _qt
    if _qt_failed:
        return None
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except Exception:  # noqa: BLE001 - optional dependency
        _qt_failed = True
        return None
    _qt = (QtCore, QtGui, QtWidgets)
    return _qt


def _ensure_app():
    global _app
    mods = _load_qt()
    if mods is None:
        return None
    QtWidgets = mods[2]
    if _app is None:
        _app = QtWidgets.QApplication.instance()
        if _app is None:
            _app = QtWidgets.QApplication(["ahk-linux-bridge"])
    return _app


def process_events():
    """Deliver pending Qt events (called from Runtime.wait)."""
    if _app is not None:
        _app.processEvents()


def _clickable_label():
    global _clickable_label_cls
    if _clickable_label_cls is not None:
        return _clickable_label_cls
    QtCore, _QtGui, QtWidgets = _qt

    class ClickableLabel(QtWidgets.QLabel):
        clicked = QtCore.Signal()

        def mousePressEvent(self, event):  # noqa: N802 - Qt API
            self.clicked.emit()
            super().mousePressEvent(event)

    _clickable_label_cls = ClickableLabel
    return ClickableLabel


def _gui_widget():
    global _gui_widget_cls
    if _gui_widget_cls is not None:
        return _gui_widget_cls
    _QtCore, _QtGui, QtWidgets = _qt

    class GuiWidget(QtWidgets.QWidget):
        def __init__(self, owner):
            super().__init__()
            self._owner = owner

        def closeEvent(self, event):  # noqa: N802 - Qt API
            self._owner._on_close_event()
            event.accept()

    _gui_widget_cls = GuiWidget
    return GuiWidget


# ---------------------------------------------------------------------------
# value/options helpers
# ---------------------------------------------------------------------------


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return "|".join(_as_text(v) for v in value)
    return str(value)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (list, dict, tuple)):
        return len(value) > 0
    return bool(value) and str(value) != "0"


def _int(value, default=0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _tokens(text) -> list[str]:
    return re.findall(r"[^\s]+", _as_text(text))


def _picture_source(text) -> str:
    """Pick the path from AHK image syntax (`*w50 *h50 nm_dir\file.png`)."""
    for token in _tokens(text):
        if token.startswith("*") or token.startswith("+"):
            continue
        return token
    return _as_text(text)


def _parse_pos(tok: str):
    """Parse x/y/w/h option token -> (axis, mode, value|None, relative)."""
    m = re.fullmatch(r"([xywh])(p|m|s)?([+-]?\d+)?", tok.lower())
    if not m:
        return None
    raw_value = m.group(3)
    value = int(raw_value) if raw_value not in (None, "") else None
    # AHK uses `x+10` for "10px past the previous control", while `x-1`
    # is an absolute negative coordinate (Natro's Tab is `x0 y-1` so its
    # tab bar overlaps the window's top edge).  `xp-1`/`xs-1` still work
    # because their mode applies the signed delta to the anchor.
    relative = bool(raw_value and raw_value[0] == "+")
    return m.group(1), m.group(2), value, relative


def _parse_options(options) -> dict:
    out = {
        "v": "", "checked": False, "disabled": False, "hidden": False,
        "readonly": False, "multi": False, "password": False,
        "wrap": None, "center": False, "right": False, "border": False,
        "default": False, "range": None, "choose": None, "color": None,
        "pos": {}, "background_trans": False, "style": set(), "tokens": [],
    }
    for tok in _tokens(options):
        out["tokens"].append(tok)
        low = tok.lower()
        pos = _parse_pos(tok)
        if pos is not None:
            out["pos"][pos[0]] = pos
            continue
        if low.startswith("v") and len(tok) > 1 and re.fullmatch(r"v[A-Za-z_]\w*", tok):
            out["v"] = tok[1:]
        elif low.startswith("checked"):
            suffix = low[len("checked"):]
            out["checked"] = _truthy(suffix) if suffix else True
        elif low == "disabled" or low == "-enabled":
            out["disabled"] = True
        elif low == "hidden":
            out["hidden"] = True
        elif low == "readonly":
            out["readonly"] = True
        elif low == "multi":
            out["multi"] = True
        elif low == "password":
            out["password"] = True
        elif low == "-wrap":
            out["wrap"] = False
        elif low in ("+wrap", "wrap"):
            out["wrap"] = True
        elif low in ("+center", "center"):
            out["center"] = True
        elif low in ("+right", "right"):
            out["right"] = True
        elif low in ("+border", "border"):
            out["border"] = True
        elif low == "default":
            out["default"] = True
        elif low in ("+backgroundtrans", "backgroundtrans"):
            out["background_trans"] = True
        elif re.fullmatch(r"range-?\d+-[+-]?\d+", low):
            m = re.fullmatch(r"range(-?\d+)-([+-]?\d+)", low)
            if m:
                out["range"] = (int(m.group(1)), int(m.group(2)))
        elif re.fullmatch(r"choose\d+", low):
            out["choose"] = int(low[len("choose"):])
        elif low.startswith("+c") and len(tok) > 2:
            out["color"] = tok[2:]
        elif re.fullmatch(r"0x[0-9a-f]+", low):
            out["style"].add(low)
        elif low.startswith("+") or low.startswith("-"):
            # Window flags, tabstop/theme and native-style hints are noted but
            # do not change control state.
            out.setdefault("flags", set()).add(low)
        elif low == "section":
            out["section"] = True
        # anything else (e.g. -16 UpDown buddy offset) is safely ignored
    return out


def _parse_range(value, default=(0, 100)):
    if value is None:
        return default
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError, IndexError):
        return default


def _make_font(options, family=None, base=None):
    mods = _load_qt()
    if mods is None:
        return None
    _QtCore, QtGui, _QtWidgets = mods
    font = QtGui.QFont(base) if base is not None else QtGui.QFont()
    if family:
        font.setFamily(str(family))
    size = 8
    for tok in _tokens(options):
        low = tok.lower()
        if low.startswith("s") and low[1:].isdigit():
            size = max(1, int(low[1:]))
        elif low.startswith("w") and low[1:].isdigit():
            font.setBold(int(low[1:]) >= 600)
        elif low in ("bold", "+bold"):
            font.setBold(True)
        elif low in ("norm", "normal"):
            font.setBold(False)
            font.setItalic(False)
            font.setUnderline(False)
        elif low in ("italic", "+italic"):
            font.setItalic(True)
        elif low in ("underline", "+underline"):
            font.setUnderline(True)
        elif low in ("strike", "+strike"):
            font.setStrikeOut(True)
    font.setPointSize(size)
    return font


def _color_token(token):
    mods = _load_qt()
    if mods is None or not token:
        return None
    _QtCore, QtGui, _QtWidgets = mods
    low = str(token).lower()
    if low in ("default", "norm"):
        return None
    named = {
        "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
        "black": "#000000", "white": "#ffffff", "gray": "#808080",
        "grey": "#808080", "silver": "#c0c0c0", "maroon": "#800000",
        "purple": "#800080", "teal": "#008080", "navy": "#000080",
        "yellow": "#ffff00", "lime": "#00ff00", "aqua": "#00ffff",
        "fuchsia": "#ff00ff", "olive": "#808000",
    }
    if low in named:
        low = named[low]
    if low.startswith("0x"):
        low = low[2:]
    if re.fullmatch(r"[0-9a-f]{6}", low):
        return "#" + low
    if re.fullmatch(r"[0-9a-f]{8}", low):
        return "#" + low[2:]
    return None


# ---------------------------------------------------------------------------
# GuiControl
# ---------------------------------------------------------------------------


class GuiControl:
    """One AHK Gui control plus its optional Qt widget."""

    def __init__(self, gui, kind: str, options="", text="", parent=None,
                 missing=False):
        self.gui = gui
        self.runtime = gui.runtime
        self.kind = kind
        self.type = _canonical_type(kind)
        self.options = _parse_options(options)
        self.name = str(self.options.get("v") or "")
        self.hwnd = gui._new_hwnd()
        self.section = ""
        self.events: dict[str, tuple] = {}
        self.visible = not self.options.get("hidden", False)
        self.enabled = not self.options.get("disabled", False)
        self.destroyed = False
        self.missing = missing
        self.widget = None
        self._text = _as_text(text)
        self._value = text
        self._x = self._y = 0
        self._w = self._h = 0
        self._suppress = False
        self._font = None
        self._style_parts: list[str] = []
        if missing:
            self.runtime._log_once(
                f"GUI control {kind!r} missing (logged, AHK-falsy state)")
            return
        self._build(parent)
        if self.name:
            gui._register_control(self)

    # -- construction -----------------------------------------------------
    def _build(self, parent):
        mods = _load_qt()
        if mods is None:
            self.runtime._log_once(
                "GUI: PySide6 unavailable; using headless control state")
            self._apply_geometry_from_options(parent)
            return
        QtCore, QtGui, QtWidgets = mods
        kind = self.type
        if kind == "Text":
            cls = _clickable_label()
            self.widget = cls(self._text)
        elif kind == "Button":
            self.widget = QtWidgets.QPushButton(self._text)
            self.widget.setAutoDefault(False)
            if self.options.get("default"):
                self.widget.setDefault(True)
        elif kind == "CheckBox":
            self.widget = QtWidgets.QCheckBox(self._text)
            self.widget.setChecked(bool(self.options.get("checked")))
        elif kind == "Edit":
            if self.options.get("multi"):
                self.widget = QtWidgets.QTextEdit()
                self.widget.setPlainText(self._text)
            else:
                self.widget = QtWidgets.QLineEdit(self._text)
                if self.options.get("readonly"):
                    self.widget.setReadOnly(True)
                if self.options.get("password"):
                    self.widget.setEchoMode(QtWidgets.QLineEdit.Password)
        elif kind == "Picture":
            cls = _clickable_label()
            self.widget = cls()
            self._set_pixmap(self._text)
        elif kind == "DDL":
            self.widget = QtWidgets.QComboBox()
            self.widget.setEditable(False)
            self._add_items(self._value)
            choose = self.options.get("choose")
            if choose is not None:
                self.widget.setCurrentIndex(max(0, int(choose) - 1))
        elif kind == "UpDown":
            self.widget = QtWidgets.QSpinBox()
            lo, hi = _parse_range(self.options.get("range"), (0, 100))
            self.widget.setRange(lo, hi)
            self.widget.setValue(_int(self._value, lo))
        elif kind == "GroupBox":
            self.widget = QtWidgets.QGroupBox(self._text)
        elif kind == "Hotkey":
            self.widget = QtWidgets.QKeySequenceEdit()
            if self._text:
                self.widget.setKeySequence(QtGui.QKeySequence(self._text))
        elif kind == "Slider":
            self.widget = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            lo, hi = _parse_range(self.options.get("range"), (0, 100))
            self.widget.setRange(lo, hi)
            self.widget.setValue(_int(self._value, lo))
        elif kind == "Tab":
            self.widget = QtWidgets.QTabWidget()
            self._add_tabs(self._value)
            self.gui._tab_control = self
            self.gui._select_tab(0)
        else:
            self.widget = _clickable_label()(_as_text(self._text))
            self.runtime._log_once(f"GUI control type {kind!r} not modeled (Text placeholder)")
            self.type = "Text"

        if parent is not None and self.widget is not None:
            self.widget.setParent(parent)
        self._apply_common()
        self._apply_font()
        self._connect()
        self._apply_geometry_from_options(parent)
        # Natro calls Show() before it adds most controls.  A child added to
        # an already-visible parent stays hidden by default, and AHK would
        # show it immediately; mirror that instead of leaving the window blank.
        if self.widget is not None:
            if self.gui.visible and self.visible:
                self.widget.show()
            else:
                self.widget.hide()

    def _apply_common(self):
        if self.widget is None:
            return
        if self.options.get("border"):
            self.widget.setStyleSheet("border: 1px solid #888;")
            self._style_parts.append("border: 1px solid #888;")
        color = _color_token(self.options.get("color"))
        if color:
            self._style_parts.append(f"color: {color};")
        if self.options.get("background_trans"):
            self._style_parts.append("background: transparent;")
        if self._style_parts:
            self.widget.setStyleSheet("".join(self._style_parts))
        if self.type == "Text":
            if self.options.get("center"):
                self.widget.setAlignment(_qt[0].Qt.AlignCenter)
            elif self.options.get("right"):
                self.widget.setAlignment(_qt[0].Qt.AlignRight | _qt[0].Qt.AlignVCenter)
            wrap = self.options.get("wrap")
            if wrap is not None:
                self.widget.setWordWrap(bool(wrap))
            elif "\n" in self._text:
                self.widget.setWordWrap(True)
            styles = self.options.get("style", set())
            if "0x7" in styles:
                self.widget.setFrameShape(_qt[2].QFrame.Box)
                self.widget.setLineWidth(1)
            if "0x201" in styles:
                self.widget.setAlignment(_qt[0].Qt.AlignCenter)
        if self.options.get("disabled") or not self.enabled:
            self.widget.setEnabled(False)
        if not self.visible:
            self.widget.hide()

    def _apply_font(self):
        if self.widget is None:
            return
        font = self._font or self.gui._font
        if font is not None:
            self.widget.setFont(font)

    def _apply_geometry_from_options(self, parent):
        self._resolve_geometry(parent)
        if self.widget is not None:
            self.widget.setGeometry(self._x, self._y, self._w, self._h)
        self.gui._remember_pos(parent, (self._x, self._y, self._w, self._h))
        if self.options.get("section"):
            self.gui._remember_section(parent, self._x, self._y)
        if self.type == "Tab":
            self.gui._tab_size = (self._w, self._h)

    def _resolve_geometry(self, parent):
        opts = self.options.get("pos", {})
        last = self.gui._last_pos(parent)
        section = self.gui._section_pos(parent)
        pw, ph = self.gui._parent_size(parent, self)
        # size first so centering can use it
        w = self._resolve_axis("w", opts.get("w"), last[2], pw)
        h = self._resolve_axis("h", opts.get("h"), last[3], ph)
        if not w or w <= 0:
            w = self._default_width()
        if not h or h <= 0:
            h = self._default_height()
        x = self._resolve_axis("x", opts.get("x"), last[0], pw,
                               last_extent=last[2], section=section[0], own_size=w)
        y = self._resolve_axis("y", opts.get("y"), last[1], ph,
                               last_extent=last[3], section=section[1], own_size=h)
        self._x, self._y, self._w, self._h = int(x), int(y), int(w), int(h)

    @staticmethod
    def _resolve_axis(axis, spec, last, parent_size, last_extent=0,
                      section=0, own_size=0):
        if spec is None:
            return 0
        _axis, mode, value, relative = spec
        if mode == "m":
            return max(0, (parent_size - own_size) // 2)
        if mode == "s":
            return section + (value or 0)
        if mode == "p":
            return last + (value or 0)
        if value is None:
            return 0
        if relative:
            if _axis in ("x", "y"):
                # AHK's `x+5` is 5px past the previous control's right edge;
                # `xp+5` is 5px past its x origin.
                return last + last_extent + value
            return last + value
        return value

    def _default_width(self):
        if self.type in ("Tab",):
            return 300
        if self.type in ("GroupBox",):
            return 120
        if self.type == "Text" and self.widget is not None:
            hint = self.widget.sizeHint()
            if hint.width() > 0:
                return max(10, hint.width())
        return 100

    def _default_height(self):
        if self.type == "Tab":
            return 150
        if self.widget is not None:
            hint = self.widget.sizeHint()
            if hint.height() > 0:
                return max(14, hint.height())
        return 23

    # -- signals ----------------------------------------------------------
    def _connect(self):
        if self.widget is None:
            return
        QtCore, _QtGui, QtWidgets = _qt
        w = self.widget
        if isinstance(w, QtWidgets.QPushButton):
            w.clicked.connect(lambda *_: self._fire("Click"))
        elif isinstance(w, QtWidgets.QCheckBox):
            w.clicked.connect(lambda *_: self._fire("Click"))
            w.toggled.connect(lambda *_: self._fire("Change"))
        elif isinstance(w, QtWidgets.QComboBox):
            w.currentIndexChanged.connect(lambda *_: self._fire("Change"))
            w.activated.connect(lambda *_: self._fire("Click"))
        elif isinstance(w, QtWidgets.QSpinBox):
            w.valueChanged.connect(lambda *_: self._fire("Change"))
        elif isinstance(w, QtWidgets.QSlider):
            w.valueChanged.connect(lambda *_: self._fire("Change"))
        elif isinstance(w, QtWidgets.QKeySequenceEdit):
            w.keySequenceChanged.connect(lambda *_: self._fire("Change"))
        elif isinstance(w, QtWidgets.QTabWidget):
            w.currentChanged.connect(lambda *_: self._fire("Change"))
        elif isinstance(w, QtWidgets.QLineEdit):
            w.textChanged.connect(lambda *_: self._fire("Change"))
        elif isinstance(w, QtWidgets.QTextEdit):
            w.textChanged.connect(lambda *_: self._fire("Change"))
        elif isinstance(w, QtWidgets.QLabel) and hasattr(w, "clicked"):
            w.clicked.connect(lambda *_: self._fire("Click"))

    def _fire(self, event: str, info=""):
        if self._suppress or self.destroyed:
            return
        spec = self.events.get(event.lower())
        if spec is None:
            return
        self.runtime._invoke_gui_callback(spec, self, info, event)

    # -- public AHK surface ----------------------------------------------
    def ahk_dispatch(self, method: str, raw_args: list, runtime):
        m = method.lower()
        ev = lambda i, d="": (runtime._eval_expr(raw_args[i])
                              if i < len(raw_args) and str(raw_args[i]).strip() else d)

        if m == "onevent":
            if len(raw_args) < 2:
                self.runtime.logs.append("OnEvent: missing event/callback")
                return 0
            event = _as_text(ev(0))
            callback_raw = str(raw_args[1]).strip()
            text = runtime._callback_arg(callback_raw)
            spec = runtime._callback_spec(text)
            if spec is None:
                self.runtime.logs.append(f"OnEvent {event}: unsupported callback")
                return 0
            self.events[event.lower()] = spec
            return 1
        if m == "setfont":
            self._font = _make_font(ev(0, ""), _as_text(ev(1, "")) or None,
                                    base=self._font or self.gui._font)
            self._apply_font()
            return ""
        if m == "move":
            vals = []
            for i in range(4):
                if i < len(raw_args) and str(raw_args[i]).strip():
                    vals.append(_int(runtime._eval_expr(raw_args[i]), None))
                else:
                    vals.append(None)
            x, y, w, h = vals
            if x is not None:
                self._x = x
            if y is not None:
                self._y = y
            if w is not None:
                self._w = max(0, w)
            if h is not None:
                self._h = max(0, h)
            if self.widget is not None:
                self.widget.setGeometry(self._x, self._y, self._w, self._h)
            self.gui._remember_pos(self.gui._active_parent,
                                   (self._x, self._y, self._w, self._h))
            return ""
        if m == "getpos":
            for i, value in enumerate((self._x, self._y, self._w, self._h)):
                if i < len(raw_args):
                    runtime._assign_output(raw_args[i], value)
            return 1
        if m == "redraw":
            if self.widget is not None:
                self.widget.update()
            return ""
        if m == "focus":
            if self.widget is not None:
                self.widget.setFocus()
            return 1
        if m == "opt":
            self._apply_opt(ev(0, ""))
            return ""
        if m == "add":
            # DropDownList / Tab item append
            value = ev(0, "")
            if self.type == "DDL":
                self._add_items(value)
            elif self.type == "Tab":
                self._add_tabs(value)
            return ""
        if m == "addtext":
            return ""
        if m == "choose":
            self._set_value(ev(0, 0))
            return ""
        if m == "delete":
            if self.type == "DDL" and self.widget is not None:
                if raw_args and str(raw_args[0]).strip():
                    self.widget.removeItem(max(0, _int(ev(0, 1)) - 1))
                else:
                    self.widget.clear()
            return ""
        if m == "clear":
            if self.type == "DDL" and self.widget is not None:
                self.widget.clear()
            elif self.type == "Edit" and self.widget is not None:
                self._set_text("")
            return ""
        if m == "usetab":
            if self.type == "Tab":
                self.gui._select_tab(ev(0, 0))
            return ""
        if m == "setpixmap":
            self._set_pixmap(ev(0, ""))
            return ""
        self.runtime._log_once(f"GUI method .{method}() not modeled (logged)")
        return ""

    def _apply_opt(self, options):
        parsed = _parse_options(options)
        for key in ("disabled", "checked", "readonly", "password", "center",
                    "right", "background_trans"):
            if parsed.get(key):
                self.options[key] = True
        if parsed.get("color"):
            self.options["color"] = parsed["color"]
            self._style_parts.append(f"color: {_color_token(parsed['color'])};")
        if parsed.get("hidden"):
            self.visible = False
        if parsed.get("wrap") is not None:
            self.options["wrap"] = parsed["wrap"]
        self._apply_common()
        if parsed.get("checked") and self.type == "CheckBox":
            self._set_value(1)

    def _add_items(self, value):
        if self.widget is None:
            return
        if isinstance(value, (list, tuple)):
            items = [_as_text(v) for v in value]
        else:
            text = _as_text(value)
            items = text.split("|") if "|" in text else ([text] if text else [])
        old = self._suppress
        self._suppress = True
        try:
            for item in items:
                self.widget.addItem(item)
        finally:
            self._suppress = old

    def _add_tabs(self, value):
        if self.widget is None:
            return
        if isinstance(value, (list, tuple)):
            items = [_as_text(v) for v in value]
        else:
            text = _as_text(value)
            items = text.split("|") if "|" in text else ([text] if text else [])
        old = self._suppress
        self._suppress = True
        try:
            for item in items:
                page = _qt[2].QWidget()
                self.widget.addTab(page, item)
                self.gui._page_by_name[item.lower()] = page
        finally:
            self._suppress = old

    def _set_pixmap(self, text):
        if self.widget is None:
            return
        QtGui = _qt[1]
        text = _as_text(text)
        pix = None
        if text.startswith("HBITMAP:*"):
            self.runtime._log_once(
                "GUI Picture: HBITMAP handle rendered as placeholder")
        elif text:
            path = _picture_source(text)
            if not os.path.isabs(path):
                base = self.runtime.vars.get("A_WorkingDir") or os.getcwd()
                path = os.path.join(str(base), path)
            try:
                pix = QtGui.QPixmap(path)
            except Exception:
                pix = None
        if pix is None or pix.isNull():
            w = max(8, self._w or 16)
            h = max(8, self._h or 16)
            pix = QtGui.QPixmap(w, h)
            pix.fill(QtGui.QColor("#d0d0d0"))
        self.widget.setPixmap(pix)
        self.widget.setScaledContents(True)

    # -- property surface -------------------------------------------------
    def ahk_get(self, key):
        name = str(key)
        low = name.lower()
        if low == "name":
            return self.name
        if low == "type":
            return self.type
        if low == "hwnd":
            return self.hwnd
        if low in ("text", "caption"):
            return self.get_text()
        if low == "value":
            return self.get_value()
        if low == "enabled":
            return 1 if self.enabled else 0
        if low == "visible":
            return 1 if self.visible else 0
        if low == "section":
            return self.section
        if low in ("pos", "position"):
            return f"{self._x} {self._y} {self._w} {self._h}"
        if low == "opt":
            return ""
        if low == "guihwnd":
            return self.gui.hwnd
        self.runtime._log_once(f"GUI control property .{name} not modeled (logged)")
        return ""

    def ahk_get_property(self, key):
        return self.ahk_get(key)

    def ahk_set_property(self, key, value):
        low = str(key).lower()
        if low == "text" or low == "caption":
            self._set_text(value)
        elif low == "value":
            self._set_value(value)
        elif low == "enabled":
            self._set_enabled(value)
        elif low == "visible":
            self._set_visible(value)
        elif low == "section":
            self.section = _as_text(value)
        elif low == "name":
            old = self.name
            self.name = _as_text(value)
            if old:
                self.gui._by_name.pop(old.lower(), None)
            if self.name:
                self.gui._register_control(self)
        elif low == "opt":
            self._apply_opt(value)
        else:
            self.runtime._log_once(
                f"GUI control property .{key} assignment not modeled (logged)")

    def get_text(self) -> str:
        if self.widget is None:
            return self._text
        mods = _qt
        if mods is None:
            return self._text
        QtWidgets = mods[2]
        w = self.widget
        if isinstance(w, (QtWidgets.QLineEdit,)):
            return w.text()
        if isinstance(w, QtWidgets.QTextEdit):
            return w.toPlainText()
        if isinstance(w, QtWidgets.QComboBox):
            return w.currentText()
        if isinstance(w, QtWidgets.QSpinBox):
            return str(w.value())
        if isinstance(w, QtWidgets.QSlider):
            return str(w.value())
        if isinstance(w, QtWidgets.QTabWidget):
            return w.tabText(w.currentIndex()) if w.count() else ""
        if isinstance(w, QtWidgets.QKeySequenceEdit):
            return w.keySequence().toString()
        if isinstance(w, QtWidgets.QLabel):
            return w.text()
        if hasattr(w, "text"):
            try:
                return str(w.text())
            except Exception:
                pass
        return self._text

    def get_value(self):
        if self.widget is None:
            return self._value
        QtWidgets = _qt[2]
        w = self.widget
        if isinstance(w, QtWidgets.QCheckBox):
            return 1 if w.isChecked() else 0
        if isinstance(w, QtWidgets.QComboBox):
            return w.currentIndex() + 1 if w.count() else 0
        if isinstance(w, QtWidgets.QSpinBox):
            return w.value()
        if isinstance(w, QtWidgets.QSlider):
            return w.value()
        if isinstance(w, QtWidgets.QTabWidget):
            return w.currentIndex() + 1 if w.count() else 0
        if isinstance(w, QtWidgets.QKeySequenceEdit):
            return w.keySequence().toString()
        if isinstance(w, QtWidgets.QLineEdit):
            return w.text()
        if isinstance(w, QtWidgets.QTextEdit):
            return w.toPlainText()
        return self.get_text()

    def _set_text(self, value):
        text = _as_text(value)
        self._text = text
        if self.widget is None:
            return
        QtWidgets = _qt[2]
        w = self.widget
        old = self._suppress
        self._suppress = True
        try:
            if isinstance(w, QtWidgets.QComboBox):
                idx = w.findText(text)
                if idx >= 0:
                    w.setCurrentIndex(idx)
                else:
                    self._text = w.currentText()
                    self.runtime._log_once(
                        f"GUI DDL {self.name!r}: text {text!r} not in items")
            elif isinstance(w, QtWidgets.QTabWidget):
                for i in range(w.count()):
                    if w.tabText(i) == text:
                        w.setCurrentIndex(i)
                        break
            elif isinstance(w, QtWidgets.QKeySequenceEdit):
                w.setKeySequence(_qt[1].QKeySequence(text))
            elif isinstance(w, QtWidgets.QSpinBox):
                w.setValue(_int(text, w.value()))
            elif isinstance(w, QtWidgets.QSlider):
                w.setValue(_int(text, w.value()))
            elif isinstance(w, QtWidgets.QTextEdit):
                w.setPlainText(text)
            elif isinstance(w, QtWidgets.QLineEdit):
                w.setText(text)
            elif self.type == "Picture":
                self._set_pixmap(text)
            elif hasattr(w, "setText"):
                w.setText(text)
            elif hasattr(w, "setPixmap"):
                self._set_pixmap(text)
        finally:
            self._suppress = old

    def _set_value(self, value):
        self._value = value
        if self.widget is None:
            return
        QtWidgets = _qt[2]
        w = self.widget
        old = self._suppress
        self._suppress = True
        try:
            if isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(_truthy(value))
            elif isinstance(w, QtWidgets.QComboBox):
                if isinstance(value, str) and not re.fullmatch(r"-?\d+", value.strip()):
                    idx = w.findText(value)
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                else:
                    idx = _int(value, 1) - 1
                    if 0 <= idx < w.count():
                        w.setCurrentIndex(idx)
            elif isinstance(w, QtWidgets.QTabWidget):
                idx = _int(value, 1) - 1
                if 0 <= idx < w.count():
                    w.setCurrentIndex(idx)
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QSlider)):
                w.setValue(_int(value, w.value()))
            elif isinstance(w, QtWidgets.QKeySequenceEdit):
                w.setKeySequence(_qt[1].QKeySequence(_as_text(value)))
            elif isinstance(w, QtWidgets.QTextEdit):
                w.setPlainText(_as_text(value))
            elif isinstance(w, QtWidgets.QLineEdit):
                w.setText(_as_text(value))
            elif self.type == "Picture":
                self._set_pixmap(_as_text(value))
            elif hasattr(w, "setText"):
                w.setText(_as_text(value))
        finally:
            self._suppress = old

    def _set_enabled(self, value):
        self.enabled = _truthy(value)
        if self.widget is not None:
            self.widget.setEnabled(self.enabled)

    def _set_visible(self, value):
        self.visible = _truthy(value)
        if self.widget is not None:
            self.widget.setVisible(self.visible)

    def destroy(self):
        if self.destroyed:
            return
        self.destroyed = True
        self.visible = False
        if self.widget is not None:
            self.widget.hide()
            self.widget.deleteLater()
            self.widget = None


# ---------------------------------------------------------------------------
# Gui
# ---------------------------------------------------------------------------


def _canonical_type(kind: str) -> str:
    low = str(kind).strip().lower()
    return {
        "text": "Text", "button": "Button", "checkbox": "CheckBox",
        "edit": "Edit", "picture": "Picture", "dropdownlist": "DDL",
        "ddl": "DDL", "updown": "UpDown", "groupbox": "GroupBox",
        "hotkey": "Hotkey", "slider": "Slider", "tab": "Tab",
    }.get(low, str(kind).strip() or "Text")


_HWND_NEXT = 0x10000


class Gui:
    def __init__(self, runtime, options="", title="", name=""):
        global _HWND_NEXT
        self.runtime = runtime
        self.name = _as_text(name)
        self.options = _as_text(options)
        self.title = _as_text(title)
        self.hwnd = _HWND_NEXT
        _HWND_NEXT += 4
        self.visible = False
        self.destroyed = False
        self.controls: list[GuiControl] = []
        self._by_name: dict[str, GuiControl] = {}
        self._missing: dict[str, GuiControl] = {}
        self._pages: list = []
        self._page_by_name: dict[str, object] = {}
        self._active_parent = None
        self._tab_control = None
        self._tab_size = (None, None)
        self._last_pos_by_parent: dict[int, tuple] = {}
        self._section_by_parent: dict[int, tuple] = {}
        self._font = None
        self._events: dict[str, tuple] = {}
        self._custom_flags = self._window_flags_from_options(self.options)
        self.widget = None
        mods = _load_qt()
        self._app = _ensure_app() if mods is not None else None
        if self._app is None:
            runtime._log_once("GUI: PySide6 unavailable; running headless GUI state")
        else:
            QtWidgets = mods[2]
            cls = _gui_widget()
            self.widget = cls(self)
            self.widget.resize(200, 200)
            self.widget.setWindowTitle(self.title)
            self._apply_window_options(self.options)
        runtime._guis.append(self)

    # -- handles/pages ----------------------------------------------------
    def _new_hwnd(self) -> int:
        global _HWND_NEXT
        value = _HWND_NEXT
        _HWND_NEXT += 4
        return value

    def _register_control(self, control: GuiControl):
        if control.name:
            self._by_name[control.name.lower()] = control

    def _parent_size(self, parent, control=None):
        if parent is not None and self._tab_control is not None:
            tw, th = self._tab_size
            if tw:
                return int(tw), int(th or 240)
        if self.widget is not None:
            return self.widget.width(), self.widget.height()
        return 490, 275

    def _last_pos(self, parent):
        key = id(parent)
        if key not in self._last_pos_by_parent:
            self._last_pos_by_parent[key] = (0, 0, 0, 0)
        return self._last_pos_by_parent[key]

    def _remember_pos(self, parent, pos):
        self._last_pos_by_parent[id(parent)] = pos

    def _section_pos(self, parent):
        return self._section_by_parent.get(id(parent), (0, 0))

    def _remember_section(self, parent, x, y):
        self._section_by_parent[id(parent)] = (x, y)

    # -- control construction --------------------------------------------
    def add(self, type_raw, options_raw="", text_raw=""):
        kind = _canonical_type(_as_text(self.runtime._eval_expr(type_raw)))
        options = self.runtime._eval_expr(options_raw) if str(options_raw).strip() else ""
        text = self.runtime._eval_expr(text_raw) if str(text_raw).strip() else ""
        # Controls added before a Tab belong to the main window; after a Tab
        # the active page becomes their parent.  Without this they would be
        # top-level widgets and never paint inside the Gui.
        parent = self._active_parent or self.widget
        control = GuiControl(self, kind, options, text, parent=parent)
        self.controls.append(control)
        if control.type == "Tab" and control.widget is not None:
            # AHK selects the first tab page automatically.
            self._active_parent = self._pages[0] if self._pages else None
        return control

    def _apply_window_options(self, options):
        if self.widget is None:
            return
        QtCore, _QtGui, QtWidgets = _qt
        flags = self.widget.windowFlags()
        for tok in _tokens(options):
            low = tok.lower()
            if low == "+alwaysontop":
                flags |= QtCore.Qt.WindowStaysOnTopHint
            elif low in ("-caption", "+frameless"):
                flags |= QtCore.Qt.FramelessWindowHint
            elif low == "+toolwindow":
                flags |= QtCore.Qt.Tool
            elif low.startswith("+minsize"):
                m = re.match(r"\+minsize(\d+)x(\d+)", low)
                if m:
                    self.widget.setMinimumSize(int(m.group(1)), int(m.group(2)))
            elif low == "+resize":
                self.widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                          QtWidgets.QSizePolicy.Expanding)
        self.widget.setWindowFlags(flags)

    def _window_flags_from_options(self, options):
        return set()

    # -- tab pages --------------------------------------------------------
    def _select_tab(self, which):
        if self._tab_control is None or self._tab_control.widget is None:
            return
        w = self._tab_control.widget
        if isinstance(which, str) and not re.fullmatch(r"-?\d+", which.strip()):
            idx = -1
            for i in range(w.count()):
                if w.tabText(i).lower() == which.lower():
                    idx = i
                    break
        else:
            idx = _int(which, 1) - 1
        if 0 <= idx < w.count():
            w.setCurrentIndex(idx)
            self._active_parent = w.widget(idx)
            self._pages = [w.widget(i) for i in range(w.count())]
            self._page_by_name = {w.tabText(i).lower(): w.widget(i)
                                  for i in range(w.count())}

    # -- AHK dispatch -----------------------------------------------------
    def ahk_dispatch(self, method: str, raw_args: list, runtime):
        m = method.lower()
        ev = lambda i, d="": (runtime._eval_expr(raw_args[i])
                              if i < len(raw_args) and str(raw_args[i]).strip() else d)

        if m == "add":
            return self.add(*[raw_args[i] if i < len(raw_args) else ""
                              for i in range(3)])
        if m == "show":
            return self._show(_as_text(ev(0, "")))
        if m in ("hide",):
            return self._hide()
        if m in ("destroy", "delete"):
            return self._destroy()
        if m == "close":
            return self._close()
        if m in ("minimize",):
            if self.widget is not None:
                self.widget.showMinimized()
            return ""
        if m in ("maximize",):
            if self.widget is not None:
                self.widget.showMaximized()
            return ""
        if m in ("restore",):
            if self.widget is not None:
                self.widget.showNormal()
            return ""
        if m == "setfont":
            self._font = _make_font(ev(0, ""), _as_text(ev(1, "")) or None,
                                    base=self._font)
            return ""
        if m == "onevent":
            if len(raw_args) < 2:
                self.runtime.logs.append("Gui.OnEvent: missing event/callback")
                return 0
            event = _as_text(ev(0))
            text = runtime._callback_arg(str(raw_args[1]).strip())
            spec = runtime._callback_spec(text)
            if spec is None:
                self.runtime.logs.append(f"Gui.OnEvent {event}: unsupported callback")
                return 0
            self._events[event.lower()] = spec
            return 1
        if m == "opt":
            self._apply_window_options(_as_text(ev(0, "")))
            return ""
        if m == "move":
            vals = []
            for i in range(4):
                if i < len(raw_args) and str(raw_args[i]).strip():
                    vals.append(_int(runtime._eval_expr(raw_args[i]), None))
                else:
                    vals.append(None)
            if self.widget is not None:
                g = self.widget.geometry()
                x = g.x() if vals[0] is None else vals[0]
                y = g.y() if vals[1] is None else vals[1]
                w = g.width() if vals[2] is None else max(0, vals[2])
                h = g.height() if vals[3] is None else max(0, vals[3])
                self.widget.setGeometry(x, y, w, h)
            return ""
        if m == "getpos":
            if self.widget is not None:
                g = self.widget.geometry()
                values = (g.x(), g.y(), g.width(), g.height())
            else:
                values = (0, 0, 0, 0)
            for i, value in enumerate(values):
                if i < len(raw_args):
                    runtime._assign_output(raw_args[i], value)
            return 1
        if m in ("redraw",):
            if self.widget is not None:
                self.widget.update()
            return ""
        if m == "submit":
            return self._submit()
        if m == "usetab":
            self._select_tab(ev(0, 1))
            return ""
        self.runtime._log_once(f"GUI method .{method}() not modeled (logged)")
        return ""

    # -- window operations ------------------------------------------------
    def _show(self, options=""):
        mods = _load_qt()
        self.visible = True
        # WinExist("A") / WinGetPos(..., "A") target the last shown Gui.
        self.runtime._active_gui = self
        if self.widget is None or mods is None:
            return ""
        QtCore, _QtGui, QtWidgets = mods
        self._apply_show_geometry(options)
        self.widget.show()
        self.widget.raise_()
        if any(t.lower() in ("center",) for t in _tokens(options)):
            screen = self.widget.screen()
            if screen is not None:
                g = self.widget.frameGeometry()
                g.moveCenter(screen.availableGeometry().center())
                self.widget.move(g.topLeft())
        return ""

    def _apply_show_geometry(self, options):
        if self.widget is None:
            return
        g = self.widget.geometry()
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        for tok in _tokens(options):
            pos = _parse_pos(tok)
            if pos is None:
                continue
            axis, mode, value, _relative = pos
            if axis == "x" and value is not None:
                x = value
            elif axis == "y" and value is not None:
                y = value
            elif axis == "w" and value is not None:
                w = max(1, value)
            elif axis == "h" and value is not None:
                h = max(1, value)
        self.widget.setGeometry(x, y, w, h)

    def _hide(self):
        self.visible = False
        if self.widget is not None:
            self.widget.hide()
        return ""

    def _destroy(self):
        if self.destroyed:
            return ""
        for control in self.controls:
            control.destroy()
        self.destroyed = True
        self.visible = False
        if self.widget is not None:
            self.widget.hide()
            self.widget.deleteLater()
            self.widget = None
        return ""

    def _close(self):
        self._fire("Close")
        if self.runtime._pending_abort is None:
            self._hide()
        return ""

    def _on_close_event(self):
        self._fire("Close")
        if self.runtime._pending_abort is None:
            self.visible = False

    def _fire(self, event: str, info=""):
        spec = self._events.get(event.lower())
        if spec is None:
            return
        self.runtime._invoke_gui_callback(spec, self, info, event)

    def _submit(self):
        values = {}
        for control in self.controls:
            if control.name:
                values[control.name] = control.get_value()
        return values

    # -- property surface -------------------------------------------------
    def ahk_get(self, key):
        name = str(key)
        low = name.lower()
        if low == "hwnd":
            return self.hwnd
        if low == "title":
            return self.title
        if low == "name":
            return self.name
        if low in ("pos", "position"):
            if self.widget is not None:
                g = self.widget.geometry()
                return f"{g.x()} {g.y()} {g.width()} {g.height()}"
            return "0 0 0 0"
        if low == "focusedctrl":
            return ""
        found = self._by_name.get(low)
        if found is not None:
            return found
        if name in self._by_name:
            return self._by_name[name]
        self.runtime._log_once(f"GUI control {name!r} not found (logged)")
        missing = self._missing.get(low)
        if missing is None:
            missing = GuiControl(self, "Text", "", "", missing=True)
            missing.name = name
            self._missing[low] = missing
        return missing

    def ahk_get_property(self, key):
        if str(key).lower() == "title":
            return self.title
        if str(key).lower() == "hwnd":
            return self.hwnd
        return self.ahk_get(key)

    def ahk_set_property(self, key, value):
        low = str(key).lower()
        if low == "title":
            self.title = _as_text(value)
            if self.widget is not None:
                self.widget.setWindowTitle(self.title)
        elif low == "name":
            self.name = _as_text(value)
        elif low in ("visible",):
            self._set_visible(value)
        else:
            self.runtime._log_once(
                f"GUI property .{key} assignment not modeled (logged)")

    def _set_visible(self, value):
        if _truthy(value):
            self._show("")
        else:
            self._hide()

    def get_control(self, name):
        return self.ahk_get(name)
