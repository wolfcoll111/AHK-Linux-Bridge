# HANDOFF — AHK-Linux-Bridge v0.4 (vision: Gdip image-search replacement)

Date: 2026-10-16. All numbers below were re-measured live, not copied.
Repo: `/home/lordhats/Documents/Default Project/ahk-linux-bridge`
Remote: `https://github.com/wolfcoll111/AHK-Linux-Bridge.git` (v0.4 phases
0–3 pushed; v0.3 baseline `a2515bb`: 84 tests, corpus 524f/22176n/380raw/
1.71%, 0 crashes)
Test corpus (NOT in repo, stays on this PC): `~/Games/NatroMacro/src` — 150 ×
`.ahk`, NatroMacro v1.1.2 (Bee Swarm Simulator macro, real-world AHK v2).
Env: KDE Plasma 6.7.5 / Wayland, uinput backend, mss + Pillow 12.3.0 +
numpy 2.5.4 all installed and verified working.

## 1. What this is

v0.3 built the macro LANGUAGE engine (parser 98%+ on real code, runtime
proven on logic, uinput proven live). The engine is blind: every
`Gdip_*` call is a logged stub. NatroMacro finds flowers, mobs, buttons,
and digits **by pixels** — without eyes it cannot farm. v0.4 gives the
bridge eyes: a Linux-native vision layer (`src/ahk_bridge/vision.py`,
new) that reimplements the OBSERVABLE behavior of the Gdip wrapper
functions Natro actually calls. This is a wrapper-level port, NOT a
GDI+ emulation: the 450 `DllCall(` lines (almost all inside
`lib/Gdip_*.ahk` itself) are never ported; the `Gdip_*` function names
Natro calls become real implementations backed by KWin ScreenShot2
(Wayland) or mss (X11) + Pillow (+numpy only where measured necessary —
see §5 perf numbers).

## 2. Current state (measured 2026-10-21)

- `python3 -m pytest -q` → **128 passed** (84 v0.3 + 44 vision).
- Natro corpus: **150 files, 0 crashes, 524 functions, 22176 nodes, 380
  `__raw__` unknowns = 1.71%** (recount after Phase 3: unchanged).
  Remaining raws are help-text prose, Gdip machine-code data blobs,
  memory/DllCall stubs (by decision), 2–3 join fragments. No systematic
  executable-code gap known.
- `vision.py` phase 0+1 done (2026-10-21): handle table + base64/screen
  producers, dispose loop flat over 1000 iterations, and image_search with
  exact/Variation/Trans/direction/Instances/error-code oracles on synthetic
  fixtures. Measured 500×500 region / 50×40 needle: **0.82 ms best, 0.94 ms
  median** (Natro's tightest corpus cadence is `Sleep 50`; budget 5 ms =
  an order of magnitude under it). Runtime wiring done (2026-10-21):
  Gdip_* calls execute through the parser/runtime, `&OutputList` and
  `&w/&h` write `vars`, positional omitted args stay in their slots,
  dispose returns the table to baseline, unknown Gdip_* log one stub each.
- §5.2 live proof (2026-10-21): Natro's `royaljelly.png` (108×28) shown
  1:1 at screen (400,300), window geometry confirmed by xdotool. The AHK
  script captured `300|200|400|300` through the real runtime and
  `Gdip_ImageSearch` returned **count 1, list `100,100`** — global
  (400,300), exactly the shown needle. Log:
  `/tmp/opencode/vision-live-proof.log`; screenshot:
  `/tmp/opencode/vision-live-proof.png`.
- Phase 3 region forms done (2026-10-21): AHK implicit concatenation
  (`windowX "|" windowY ...`) and arithmetic with calls (`Round`, `Max`,
  `Floor`, user functions), `Screen:=`/`Raster:=` named arguments, and
  screen-clamped regions (negative/overflow shrink the crop; a fully
  off-screen region is a 1x1 black frame, never an exception).
  Computed-region live proof: `Screen:=x "|" y "|" w "|" h` through the
  real runtime returned count 1, list `100,100` (global 400,300); log
  `/tmp/opencode/vision-live-proof-phase3.log`.
- `pixels.py` capture: mss reads the XWayland root, which is **all black**
  under this KWin Wayland session (measured: 1920×1080 grab, one color).
  Added KWin `org.kde.KWin.ScreenShot2` capture over dbus-next (raw RGBX,
  no portal prompt): 500×500 region **2.4–3.5 ms**, full screen **~33 ms**,
  pixel-exact against a displayed PNG. mss remains the X11 fallback.
  `dbus-next` added to the `pixels` extra (already used by `portal`).
- Speed baselines measured live on this PC (1920×1080 desktop):
  pure-Python `find_color` fullscreen **0.42s**; naive numpy
  sliding-window SAD fullscreen **~5.7s**, 500×500 region **~2.7s**.
  Natro searches small regions (100–500px boxes), never fullscreen —
  but even region-scale naive matching is too slow for tight
  capture→search→dispose loops. The port earns its speed via region
  cropping (free: Natro always passes regions), exact-match fast paths,
  and coarse-to-fine — NOT by assuming numpy fixes everything.
- numpy dependency justified and added to the `pixels` extra
  (2026-10-21). Same 500×500 random hay / 50×40 needle fixture:
  optimized `image_search` **0.53 ms best / 0.57 ms median**; pure-Python
  slice scan **24.1 ms** (42× slower, over the 5 ms test budget); naive
  numpy SAD was **2.7 s**. So numpy is required, but only the
  candidate-probe + verify shape is fast enough.

## 3. Measured inventory (what Natro's eyes actually do)

Call counts (`grep -rhoP "\bGdip_[A-Za-z_]+\b"`, corpus-wide):

| uses | function | v0.4 treatment |
| ---: | --- | --- |
| 207 | `Gdip_ImageSearch` | **implement** (§5 Phase 1–2) |
| 130 | `Gdip_BitmapFromScreen` | **implement** (mss crop) |
| 279 | `Gdip_DisposeImage` | **implement** (handle-table free; leaks otherwise) |
| ~630 | `Gdip_BitmapFromBase64` (needle assets in `nm_image_assets/*/bitmaps.ahk`) | **implement** (base64→Pillow; needs zero new deps) |
| 82+119+108+… | `Gdip_TextToGraphics`, brushes, pens, graphics, fills, draws | **stub** (see below — display-only) |
| 11/10/8 | `Gdip_GetImageWidth/Height/Dimensions` | **implement** (trivial from handle table) |
| 9 | `Gdip_LockBits` / `Gdip_MultiLockedBitsSearch` | **stub** (internal fast-path of the .ahk lib; our port searches differently) |
| rest | `Gdip_Startup/Shutdown/CloneBitmap/...` | **implement** trivial ones, stub rest |

Canonical loop (measured at Blender/GUI call sites):
`hay := Gdip_BitmapFromScreen(region)` →
`Gdip_ImageSearch(hay, bitmaps["Name"], ...)` →
`Gdip_DisposeImage(hay)`.

Result consumption (all three shapes must work):
1. `if (Gdip_ImageSearch(ss, bitmaps["CloseGUI"], , , , , , 5) > 0)` —
   presence check on the COUNT return. Return is a NUMBER (0 = none).
2. `Gdip_ImageSearch(pBMArea, bitmaps["pBMHaste"], &list, x, 14, , , , , 6)`
   then `x := SubStr(list, 1, InStr(list, ",")-1)` — `&OutputList`
   ByRef string `"x1,y1[`n`x2,y2..."` (default `` `n `` line delim, `,`
   coord delim), first pair parsed by the caller. **Byte format matters.**
3. `!= 1` checks — exact-instance-count logic.

`Gdip_ImageSearch` contract (from `lib/Gdip_ImageSearch.ahk:73`):
`Gdip_ImageSearch(hay, needle, &OutputList:="", OuterX1:=0, OuterY1:=0,
OuterX2:=0, OuterY2:=0, Variation:=0, Trans:="", SearchDirection:=1,
Instances:=1, LineDelim:="`n", CoordDelim:=",")`.
Returns instance COUNT, negative error codes (`-1001` null bitmap,
`-1002` bad Variation, `-1003` bad coords, …). **Variation (0–255 shade
tolerance) and Trans (transparent color) are REALLY used in the
corpus** — exact-match-only is NOT faithful. SearchDirection 1–8 sets
scan order (which instance lands first in OutputList). Instances caps
the count. Falsy/zero handles must read as null
(`If !(pBitmapHaystack && pBitmapNeedle)` → `-1001`).

Handle model: Gdip returns integer handles; `0`/`""` = null. Port keeps
`dict[int, PIL.Image]` starting at 1. All bitmap producers
(`FromBase64`, `FromScreen`, `CreateBitmap`) return handles; consumers
take handles; `DisposeImage` frees (279 sites — a macro running hours
that leaks PIL images per loop iteration will OOM; test dispose with a
1000-iteration loop asserting table size stays flat).

`Gdip_BitmapFromScreen` argument forms seen: `(1`, `(Screen:=0,
Raster:="..."`, `(middleX-250 "|" middleY-210 "|500|50"` (pipe-joined
region STRING), `(region`. Port must accept a region string
`"x|y|w|h"` and evaluate coordinate expressions. Multi-monitor: mss
`monitors[0]` today; note the limitation, do not solve it in v0.4.

Why the drawing stack stays stubs: every `TextToGraphics`/`FillRectangle`
site feeds `UpdateLayeredWindow` (Windows layered-window OSD status
bars). Linux has no equivalent surface and NOTHING reads those pixels
back — display-only. Stub them loudly. Same for WinRT/`GetDateFormatEx`/
USkin `DllCall`s outside lib/ (permanent stubs: foreign OS surface).

## 4. What v0.4 delivers (definition of done)

1. `src/ahk_bridge/vision.py`: handle table + producers
   (`from_base64`, `from_screen`, `create_bitmap`), lifecycle
   (`dispose`, `dimensions`), `image_search` with Variation tolerance,
   Trans masking, direction-ordered results, Instances cap, AHK error
   codes, exact OutputList formatting with caller-supplied delims.
2. Runtime wiring: `Gdip_ImageSearch`, `Gdip_BitmapFromScreen`,
   `Gdip_BitmapFromBase64`, `Gdip_CreateBitmap`, `Gdip_DisposeImage`,
   `Gdip_GetImageWidth/Height/Dimensions` execute for real (incl.
   `&OutputList` ByRef writes); all other `Gdip_*` log one stub each.
3. Proof: synthetic oracles (Phase 1) + live desktop proof (Phase 2,
   §5.2) with logs. Suite stays green; corpus recount stays 0 crashes;
   numbers updated below when they move.

## 5. Exact commands and phases

Baseline (paste as-is):
```bash
cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge"
python3 -m pytest -q                       # expect 84 passed
python3 -c "from ahk_bridge import pixels as px; print(px.screenshot_rgb()[1:])"
# expect (1920, 1080) — live capture works on this machine
```

Coverage recount: same `§5`-style script as v0.3 (parser census over
`~/Games/NatroMacro/src/**/*.ahk`).
Baseline 2026-10-16: funcs=524 nodes=22176 raw=380 (1.71%), 0 crashes.

### Phase 0 — bitmap lifecycle (no live screen needed)
`from_base64` (decode the FIRST real needle out of
`nm_image_assets/general/bitmaps.ahk` and assert size/mode),
`create_bitmap`, `from_screen` region-crop math on a SYNTHETIC canvas
(never the live desktop: determinism first), `dispose` +
`dimensions`, 1000-iteration dispose loop asserting flat table size.
Tests in `tests/test_vision.py` (new file). Oracle: Pillow itself
(`Image.open` the same bytes; sizes equal).

### Phase 1 — search core on synthetic fixtures
Build fixtures in-test: solid canvas + pasted needle at KNOWN coords
(never screenshots for correctness oracles — screenshots are
non-deterministic). Required oracles, each a test:
- exact find → count + `"x,y"` OutputList byte-exact (default delims
  AND custom `LineDelim`/`CoordDelim`);
- not-present → `0` and empty OutputList;
- Variation: needle shaded ±N → found iff N ≤ Variation (two tests:
  inside/outside boundary);
- Trans: needle with border color T + `Trans=T` → found; without Trans
  → masked pixels must not false-positive (design the fixture so plain
  matching FAILS and Trans matching SUCCEEDS — else the test proves
  nothing);
- SearchDirection: two needles → first pair in OutputList follows the
  requested scan order (implement 1 + 180°-opposite first; document the
  other 6 as best-effort ONLY with a passing test each, no assertion
  without an oracle);
- Instances cap; `-1001/-1002/-1003` error paths; null-handle falsiness.
- Perf oracle on a 500×500 region with a 50×40 needle: record the time
  IN the test name/log and assert under the budget YOU measure for
  Natro's loop rate (state the budget in the test comment; today naive
  is ~2.7s — ship only when the implementation is an order of
  magnitude under the loop budget, else say so plainly).

### Phase 2 — runtime wiring + live proof
Wire the §4 function list through `runtime.py` (`&OutputList` writes
into `vars`, handles resolve via the table, unknown `Gdip_*` → one
stub log each). Then the live proof — §5.2:
```bash
# terminal 1: show something KNOWN on screen (e.g. open the AHK Dash
# window, or display one of Natro's own needle PNGs at a known spot)
# terminal 2:
python3 -m ahk_bridge.cli run /tmp/opencode/vision-proof.ahk --backend dry
# script: hay := Gdip_BitmapFromScreen(<region covering the known thing>)
#         n := Gdip_ImageSearch(hay, Gdip_BitmapFromBase64("<same needle>"))
#         + MsgBox/log of n and OutputList; Gdip_DisposeImage(hay)
```
Pass = count ≥ 1 AND reported coords land inside the known region
(check with `xdotool getmouselocation` or a screenshot dump with a
drawn marker — evidence, not assertion). Save the log under
`/tmp/opencode/vision-live-proof.log`. Do NOT claim live vision until
the log shows a real count with in-region coords. NOTE: this needs the
desktop to sit still for ~30s; close/mute anything animated first.

### Phase 3 — region forms + hardening (DONE 2026-10-21)
Pipe-string regions (`"x|y|w|h"`), `Screen:=`/`Raster:=` named-arg
forms, implicit string concatenation + arithmetic with calls, negative/
overflow coords (clamp, never throw; `ImageSearch` negative X1/Y1 keeps
the wrapper's -1003 contract), `Gdip_GetImageWidth/Height` consumers.
Re-ran full suite (128 green) + recount (524/22176/380, 0 crashes).

## 6. Rules (same discipline as v0.3)

- No hype. Verify by execution (synthetic oracles, live logs), never by
  assertion. A test that passes on fixtures which cannot fail proves
  nothing — design fixtures that fail without the feature (the Trans
  test above is the template for this thinking).
- Minimal fixes, one phase per commit, regression test per fix in
  `tests/test_vision.py` (runtime wiring tests may join
  `tests/test_natro_exec.py` if they fit its style).
- Perf honesty: if matching cannot hit loop rate on this PC, report
  the measured numbers and stop — do not ship a 3-second eyes module
  and call Natro "supported".
- New deps: numpy is now in the `pixels` extra with the measured
  justification above. Any further dep needs the same before/after
  numbers in the commit message. No OpenCV unless the numbers force it —
  Pillow+numpy first.
- Commit + push every green step (remote `origin`, pushing approved).
  Update THIS doc's numbers when they move.

## 7. After v0.4 (the full-AHK-base roadmap — read before scoping up)

"Full base" means: language engine (done, v0.3) + vision (this doc) +
window/input (done: uinput/XTest/xdotool) + a COMPLETE, documented
builtin inventory where every gap is a named stub, never a crash.
Concretely next: (a) remaining pure builtins the corpus uses that are
still stubs — measure with a stub-hit census, implement the pure ones;
(b) the GUI decision — AHK `Gui` on Linux is the last load-bearing gap
and is NOT a bugfix (needs a toolkit choice: Tk, webview, or
not-at-all with a compat verdict); do NOT start it inside v0.4.
Finish v0.4 only when §5.2 is proven live or a load-bearing gap from
§4/§6 stops you — report that plainly, same as v0.3.

## 8. Paste-prompt for a fresh chat (the next agent starts here)

```
Continue the AHK-Linux-Bridge v0.4 vision work. Context: read
HANDOFF-v04-vision.md in /home/lordhats/Documents/Default Project/
ahk-linux-bridge/ (repo cloned, remote
github.com/wolfcoll111/AHK-Linux-Bridge, corpus at
~/Games/NatroMacro/src, KDE Plasma Wayland, mss+Pillow+numpy installed
and live-verified).

v0.4 phases 0–3 are complete. Verify first: `python3 -m pytest -q` must
show 127 passed; live capture
`python3 -c "from ahk_bridge import pixels as px;
print(px.screenshot_rgb((0,0,32,32))[1:])"` must show (32, 32) and the
pixels must not all be zero (KWin ScreenShot2; mss is black on this
Wayland session); rerun the coverage recount (baseline: 524 funcs,
22176 nodes, 380 raw/1.71%, 0 crashes).

Next work is §7, not another vision phase: (a) stub-hit census for pure
builtins, (b) the GUI decision. Do not reopen v0.4 vision unless a new
load-bearing gap is measured.

Rules: no hype, verify by execution (oracles, live logs) never by
assertion; one phase per commit with regression tests in
tests/test_vision.py; perf honesty over feature claims (report measured
numbers, stop if loop rate is unreachable); add numpy to pyproject
pixels-extra ONLY with before/after justification; commit+push every
green step; update the HANDOFF numbers when they move. Finish only when
§5.2 is proven live or a load-bearing gap from §4/§6 stops you — report
that plainly.
```
