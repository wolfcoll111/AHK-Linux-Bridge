# GUI toolkit decision (v0.6)

Status: **decided — PySide6 6.12.0**, imported lazily from
`ahk_bridge.gui`. GNU/Linux, Python 3.14, KDE Plasma 6/Wayland host.

## Measured need

Case-normalized Natro v1.1.2 GUI corpus (all 150 `.ahk` files, so this
includes submacro dialogs as well as the main window):

| Control | Count |
|---|---:|
| Text | 395 |
| Button | 207 |
| CheckBox | 184 |
| UpDown | 49 |
| GroupBox | 47 |
| Picture | 40 |
| Edit | 27 |
| DropDownList | 17 |
| Hotkey | 6 |
| Tab | 1 |
| Slider | 1 |

Methods: `Add` 994, `OnEvent` 512, `SetFont` 125, `Destroy` 30, `Move` 27,
`Close` 26, `Show` 24, `UseTab` 10, `Redraw` 10, `Opt` 7, `Focus` 3.
Properties: `Enabled` 800, `Value` 253, `Section` 153, `Text` 138,
`Visible` 23, `Hwnd` 11, `Title` 2. Callbacks use real function
references (`nm_saveConfig(GuiCtrl, *)`) and arrow expressions
(`(*) => ExitApp()`).

The main window is a 490×275 absolute-positioned form with a 9-page tab
control and picture controls. Values and events are load-bearing; pixel
perfection is not (Natro's own `TextExtent` helper is DllCall-based and is
already documented as approximate under the bridge).

## Candidates measured on this machine (2026-10-22)

| Candidate | Installed | Import / startup | RSS | Headless | Verdict |
|---|---:|---|---:|---|---|
| **PySide6 6.12.0** | 52 MB | import 0.146 s; offscreen app 0.16 s | 79 MB import / 86 MB with app | `QT_QPA_PLATFORM=offscreen` works | **choose** |
| PyGObject 3.50 | 1.7 MB (package only) | 0.323 s to fail at GTK import | n/a | n/a | **reject**: `Gtk-4.0.typelib` and `Gtk-3.0.typelib` are absent; installing the full GTK stack is larger and less portable than the already-installed Qt |
| Tkinter | stdlib module present | 0.053 s to fail | n/a | n/a | **reject**: `_tkinter` cannot load `libtk8.6.so`; would require a system Tk install |
| pywebview | missing | n/a | n/a | n/a | **reject**: not installed and needs a browser engine/GTK backend |

PySide6 is already a working system package here, so the marginal install
size is **0 MB** on this machine. It is still declared as the optional
`gui` extra so a fresh checkout has a reproducible dependency; the core
package does not import it. If it is absent, `ahk_bridge.gui` logs one
verdict and keeps a headless object model (states/events still work; no
pixels).

## Why PySide6

- Widgets cover every control in the measured inventory: `QLabel`,
  `QPushButton`, `QCheckBox`, `QSpinBox`, `QGroupBox`, `QLineEdit`,
  `QComboBox`, `QTabWidget`, `QSlider`, `QKeySequenceEdit`, `QPixmap`.
- Signals map cleanly to AHK `OnEvent`: `clicked`, `stateChanged`,
  `currentIndexChanged`, `valueChanged`, `currentChanged`, and a custom
  mouse-press label for clickable Text/Picture controls.
- Offscreen mode is a real, tested Qt platform: construction, values,
  signals and teardown run without a display, so tests remain fast and do
  not touch the live desktop.
- The runtime event loop can pump Qt with `QApplication.processEvents()`
  between timer/message iterations; no second blocking loop is needed.
- Wayland/X11 both work when a display is present; Wayland window
  positioning is compositor-controlled, which only affects display
  fidelity, not control state or events.

## Integration shape

`Runtime` keeps owning time, messages and script state. `gui.py` owns Qt
objects only. GUI callbacks are invoked through
`Runtime._invoke_callback`, so named callbacks and arrows behave exactly
like timers/messages. Exceptions are logged and swallowed (except
`Aborted`, which is parked until the runtime can unwind safely).
