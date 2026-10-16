# HANDOFF — AHK-Linux-Bridge v0.3 (NatroMacro-hardened)

Date: 2026-10-16. All numbers below were re-measured live, not copied.
Repo: `/home/lordhats/Documents/Default Project/ahk-linux-bridge`
Remote: `https://github.com/wolfcoll111/AHK-Linux-Bridge.git` (last push: v0.2.3 `46df721`; v0.3 work below is committed+pushed on top)
Test corpus (NOT in repo, stays on this PC): `~/Games/NatroMacro/src` — 150 × `.ahk`, NatroMacro v1.1.2 (Bee Swarm Simulator macro, real-world AHK v2).

## 1. What this is

AHK-Linux-Bridge runs a subset of AutoHotkey v2 scripts natively on Linux:
`src/ahk_bridge/parser.py` (1440 lines: `.ahk` → AST) + `runtime.py` (1444 lines:
AST → actions) + backends (`uinput` for Wayland+X11, `XTest`, `dry` for tests).
CLI: `python3 -m ahk_bridge.cli {check|run|windows|pixels|record}`.
This session's job: use NatroMacro's 150 real-world scripts as an integrity
test — parse all of them, fix every systematic gap the corpus exposes, verify
by execution (not just parsing), keep the suite green.

## 2. Current state (measured 2026-10-16, KDE Plasma 6.7.5 / Wayland)

- `python3 -m pytest -q` → **68 passed** (was 30 at v0.2.3).
- Natro corpus: **150 files, 0 crashes, 524 functions, 22136 nodes, 417
  `__raw__` unknowns = 1.88%** (started this session at ~13% + 6 crashes).
- `ahk-bridge check` → `detected_backend: uinput` on this machine.
- Uncommitted at handoff time: NOTHING (everything below is committed).

## 3. What got fixed this session (bug → fix location)

Parser (`src/ahk_bridge/parser.py`):
1. `if (x) {` parsed as **FuncDef named `if`** — `FUNCDEF_RE` matches any
   `Name(...) {`. Fix: `_KEYWORDS` set + guard (~line 40), incl. `__raw__`.
2. Trailing `;` comments broke ALL block openers (`loop 2 { ;Click tile`).
   Fix: match openers against comment-stripped `code` in
   `_parse_case_statement`, `_parse_else_tail`, `_parse_try`, `_parse_block`.
3. `if(`/`else if(`/`while(`/`for(`/`switch(` (no space). Fix: `(?=\s|\()`
   lookahead in `IF/WHILE/FOR/SWITCH/ELSEIF_RE`.
4. Allman `Else If` (brace on next line) — `ELSEIF_RE` demanded same-line
   `{`. Fix: optional brace group; `_parse_else_tail` (~line 764) uses
   `_body_after_opener` for it.
5. Bare `} Else` (no brace), single-line `else <stmt>` (`else throw ...`).
   Fix: new branches in `_parse_else_tail`.
6. Blank/`;` lines between `}` and `else`/`catch`/`until` (Natro writes
   `;is it glitter?` between chain links!). Fix: `_skip_blank` (~line 754),
   wired into else-tail, try-else, catch/finally, until checks.
7. `return` ended BLOCKS (not just the auto-section): any `return` inside an
   If/Loop/Try body truncated the block and leaked `}`/`else` downstream.
   Fix: `_parse_block(..., top=False)` — only `top=True` (hotkey bodies)
   treats `return` as terminator.
8. `try {` Allman fed `{` into the parser (`_parse_block(i+1)` AT the brace).
   Fix: `_parse_block(lines, i + 2)` on the Allman path.
9. `loop { } until cond` (do-until): `} until` wasn't a block follower, so
   the `until` line became raw and the loop infinite. Fix: `UNTIL_RE` is a
   `_parse_block` follower; LOOP/LOOP_BARE/DO branches convert
   (`DoUntil` node + runtime support).
10. `try switch x {` (compound after try). Fix: single-try branch dispatches
    `if|loop|for|while|switch` rests via `_parse_case_statement`.
11. `try/catch/else` (AHK runs `else` when nothing threw — 3 uses in
    lib/Roblox.ahk + Heartbeat.ahk). Fix: `Try.else_body` + `_take_try_else`
    (~line 1083) + runtime try/else (~runtime.py:1031).
12. **Dangling-else** (the big one): after a then-body self-closes on a lone
    `}`, a following `} else` belongs to the OUTER if, but attached inward —
    swallowing whole functions (popStarCheck ate 353 lines incl.
    nm_backpackPercent). Fix: `_parse_block` returns
    `(stmts, ni, self_closed)`; `_parse_single_or_block`/`_body_after_opener`
    propagate; `_parse_else_tail(..., then_closed)` detaches `}`-led else
    lines when `then_closed` (bare `else` still attaches).
13. `;...50%` comments end with `%` → joiner read modulo-continuation and
    glued entire if-chains into mega-lines. Fix: `_open_ends` (~line 1250)
    checks comment-STRIPPED text; all `_ends_open` call sites in the joiner
    use it.
14. Leading `,`/`.`/`&&`/`||` lines always join previous (a statement can
    never start with them); leading `(`/`[`/`:` join only when previous is
    open (`_prev_open`/`_colon_continues`, ~lines 1257/1285).
15. `a.b(), c.d()` misread as method chain → `__raw__`. Fix: chains only
    when `rest` starts with `.`; `,` starts Seq.
16. `switch x, 0` CaseSense flag stripped from switch value.
17. `Loop {` captured `{` as the count (lazy `(.+?)?`). Fix: explicit guard.
18. `Loop (expr)` counts (`Loop (m := Min(...))`) now captured whole.
19. N-ary `A && B && C` statement guards nest as `If`s (was binary-only).
20. `class` + Allman `Name(args)` methods + `static x := v` (Discord.ahk).
21. `break 2`/`continue 2` levels (parser + runtime `_Break(level)` unwind).
22. `Hotkey|SetTimer|SplitPath|MouseGetPos|WinGetPos|WinGetClientPos|
    WinSetTransparent|MonitorGetWorkArea|...` → `LegacyCmd` (logged, no-op);
    `#NoTrayIcon|#NoEnv|#Persistent|...` → `Setting`; `(LTrim...` text-block
    openers → `Setting("ContinuationSection")`.
23. `MouseClick(?!Drag)` lookahead (was eating MouseClickDrag).

Runtime (`src/ahk_bridge/runtime.py`):
24. `||`/`&&` inside EXPRESSIONS (`both := (...) || (...)`) → 1/0 via
    `_cond` operands (placed AFTER ternary/`:=`, `&&` binds tighter).
25. Comparisons/`~=` in value position (`ok := (a ~= b)`) via `_has_cmp_op`
    (~line 38) fallback to `_cond`.
26. `~=` regex-match operator in `_cond` (AHK `i)` flags → `re.IGNORECASE`).
27. `**` power in `_safe_eval` BinOp; `Floor/Ceil/Sqrt/Exp/Sin/Cos/Atan/
    Log/Ln` builtins; `Error()/TypeError()/ValueError()` return their message
    (so `throw Error("x")` surfaces it).
28. Numeric-string coercion in BinOp: `"00" * 3600 == 0` (was Python string
    repetition → astronomic garbage; found via execution oracle).
29. `Class`exec (statics run once, methods register); `DoUntil` exec;
    level-aware `_Break/_Continue` in Loop/While/For/LoopParse/LoopFiles/
    Switch (switch re-raises level>1).

Proof (execution, not just parse — `tests/test_natro_exec.py`, 20 tests):
- Planter time math verbatim from Status.ahk → `time_delta == 1801` ✓
- Movespeed guard → matches Python oracle ✓, `60**(2-1) == 60` ✓
- Do-until / try-catch-else both directions / break-2 / class statics ✓
- Live uinput on KDE: device opens, keys send (xev proof PENDING re-run —
  see §5.1).

## 4. Remaining gaps (ranked, honest)

1. **`__raw__` 417 (1.88%)** — top heads: `(` 46 (MsgBox/generated-script
   TEXT blocks, unexecutable by design), prose (`The/-/This/To/Enter/When`,
   ~40, same), `'` 8, `)"` 10, `NumPut(` 5 (multi-line GDI+ mem-pokes),
   `{`/`}` 10 (strays), `MainGui[...].OnEvent` chains 2, hex blobs 4.
   Real code among them: maybe 60–90 nodes (~0.4%). Next systematic target
   (if any): multi-line `DllCall(`/`NumPut(` whose first line is
   balanced-complete.
2. **GUI framework**: `GuiCtrl.*`, `MainGui.Add`, `OnEvent` run as logged
   stubs. A Bee Swarm macro IS a GUI app (buttons, config windows) — the
   bridge cannot render AHK Gui on Linux. Any Natro GUI path is dead-end
   without a GUI re-implementation (out of scope for the engine).
3. **Memory/pointer builtins**: `DllCall` (463 uses), `NumPut/NumGet`,
   `Buffer`, `StrPtr`, Gdip_* image-search (screenshot pixel matching).
   These are the macro's EYES (it finds flowers/mobs by pixels). Linux
   equivalents exist (mss + Pillow are already deps; `pixels.py` has
   `find_color`) but Gdip_bridging 463 call sites is a project of its own.
4. **Roblox-facing**: NoNameMacro needed process-memory reads (impossible
   under Wine/Sober — documented in `docs/NONAME-LINUX-TEST.md`). Natro is
   pure AHK (no memory reads) — that is WHY it is the right test target.
5. `WinActivate`/window ops work via xdotool on KDE/X11; GlobalShortcuts
   portal on KDE needs the `.desktop` + user consent flow (unverified).

## 5. Exact commands for the next agent

```bash
cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge"
python3 -m pytest -q                       # expect 68 passed
python3 -m ahk_bridge.cli check            # expect detected_backend: uinput
```

Coverage recount (paste as-is; ~1 min):
```bash
cd "/home/lordhats/Documents/Default Project/ahk-linux-bridge" && timeout 180 python3 -c "
from ahk_bridge import parser as P
import glob, collections
files = sorted(glob.glob('/home/lordhats/Games/NatroMacro/src/**/*.ahk', recursive=True))
total=collections.Counter(); raws=collections.Counter(); nfunc=0
def walk(nodes):
    for st in nodes:
        if id(st) in walk.seen: continue
        walk.seen.add(id(st))
        total[type(st).__name__]+=1
        if type(st).__name__=='FuncCall' and getattr(st,'name','')=='__raw__':
            a=str(st.args[0]) if st.args else ''
            raws[a.strip().split()[0] if a.strip().split() else '?']+=1
        for attr in ('body','then_body','else_body','try_body','catch_body','finally_body'):
            if hasattr(st,attr):
                b=getattr(st,attr)
                if isinstance(b,list) and b: walk(b)
        if hasattr(st,'else_body') and type(st).__name__=='Try': walk(st.else_body)
        if hasattr(st,'cases'):
            try:
                for c,b in st.cases: walk(b)
            except: pass
        if type(st).__name__=='Seq': walk(st.items)
        if type(st).__name__ in ('FuncDef','Class'): walk(st.body)
for f in files:
    sc=P.parse_script(open(f, encoding='utf-8-sig').read()); nfunc+=len(sc.functions)
    walk.seen=set(); walk(sc.auto_section)
    for fn in sc.functions.values():
        walk.seen=set(); walk(fn.body)
nraw=sum(raws.values()); tot=sum(total.values())
print(f'funcs={nfunc} nodes={tot} raw={nraw} ({100.0*nraw/tot:.2f}%)')
print(dict(raws.most_common(16)))
"
# baseline 2026-10-16: funcs=524 nodes=22136 raw=417 (1.88%), 0 crashes
```

### 5.1 Live uinput proof (KDE) — INTERRUPTED, redo this first

```bash
pkill -f "[x]ev -event" 2>/dev/null   # NOTE brackets: plain "xev" matches YOUR OWN shell and kills it
rm -f /tmp/opencode/xev-kde2.log
DISPLAY=:0 setsid -f xev -event keyboard > /tmp/opencode/xev-kde2.log 2>&1
sleep 2
export DISPLAY=:0
XW=$(xdotool search --name "Event Tester" | tail -1)
xdotool windowfocus --sync $XW
printf 'Send "{F13}"\n' > /tmp/opencode/f13only.ahk
python3 -m ahk_bridge.cli run /tmp/opencode/f13only.ahk --backend uinput
grep -a "keysym" /tmp/opencode/xev-kde2.log   # want keycode 191 / keysym 0xffca (F13)
```
Last attempt showed focus drift (a Wine "FitGirl" window stole focus mid-run)
and possibly literal `{F13}` text instead of the key — unverified, do NOT
claim it works until the log shows 0xffca.

## 6. Suggested next tasks (in order)

1. Redo §5.1. If `{F13}` types literally, the bug is in `_send_text` brace
   handling (runtime.py ~line 500-570), not the parser (parser emits
   `Send("{F13}")` correctly).
2. Remaining `}` (5) / `{` (5) / `else` (≤2) stragglers: locate per-file
   (census groups by file), fix only if a systematic cause appears; do NOT
   chase singletons.
3. `NumPut(`/multi-line `DllCall(`: check whether they are balanced-complete
   first lines (then: join-or-log decision).
4. Commit + push (remote is `origin`, user already approved pushing).
5. Then the honest roadmap: GUI + Gdip image-search are the two load-bearing
   gaps for actually RUNNING Natro (see §4 + §7).

## 7. Brutal honesty (no hype)

- The engine is real: parsing is at 98.1% with zero crashes, and the runtime
  executes Natro's actual math/state logic correctly (oracle-verified). That
  part is genuinely close to "AutoHotkey for Linux".
- But "runs NatroMacro" is NOT close: Natro without its GUI (config windows,
  buttons) and without Gdip image-search (its eyes) cannot farm. Those two
  are each weeks of work, not bugfixes. What exists is a correct macro
  LANGUAGE engine + Linux input layer, proven on logic — not a working game
  bot.
- Claiming "first AutoHotkey for Linux" is fair for the language-engine
  claim; claiming it "runs Bee Swarm macros" today would be false.
