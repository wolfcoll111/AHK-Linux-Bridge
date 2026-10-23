# Natro census

Generated: 2026-10-23 15:52:21
Corpus: `/mnt/games/Apps/NatroMacro/src`

> Triage baseline, not a score. `language-gap` rows are known
> parser/runtime gaps (at this baseline, many come from function bodies
> leaking into the auto-section after nested definitions).
> `windows-only` rows are DllCall/GDI+/COM surfaces replaced by the
> Linux vision layer; `unknown` rows are the actionable headless
> builtins. The JSON companion contains every hit and sample.
> All runtime work happens in a temporary corpus copy with desktop
> effects suppressed.

## Static inventory

- files: **150**
- functions parsed: **590**
- nodes: **23501**
- `__raw__`: **409 (1.74%)**
- parse crashes: **0**
- distinct defined functions: **572**

## Expanded main script

- include files: **35**
- logical lines: **23392**
- expand / parse: **0.59 s / 2.37 s**
- auto statements: **1744**
- functions: **632**
- raw in auto-section: **60**
- include records: `{'directory': 3, 'ok': 34, 'ignored': 1}`

## Runtime stub hits

- files executed: **150**
- timeouts: **0**
- worker deadline stops: **0**
- execution/load errors: **0**
- unknown load-bearing hits: **0**
- known gaps (language/windows/external): **29**

Verdict totals: **language-gap** 17, **windows-only** 12, **setting-noop** 8, **cross-file** 5, **parser-raw** 1

Triage table: unknown and known-gap hits only (all hits are in the
JSON).  Benign settings, display-only calls, parser raws and
cross-file calls are counted above but not listed row by row.

| kind | name | count | verdict | load-bearing | sample |
|---|---|---:|---|---|---|
| assign-target | `bitmaps[...]` | 777 | language-gap | yes | `assign-target 'bitmaps["gifted"]' failed: cannot store into int` |
| assign-target | `v[...]` | 100 | language-gap | yes | `assign-target 'v[i]' failed: cannot store into int` |
| command | `WinGetClientPos` | 100 | windows-only | yes | `WinGetClientPos &windowX, &windowY, &windowWidth, &windowHeight, "ahk_id " hwnd (OS/window op, linux no-op)` |
| assign-target | `buff_bitmaps[...]` | 35 | language-gap | yes | `assign-target 'buff_bitmaps["pBMHaste"]' failed: cannot store into int` |
| assign-target | `hBitmapsSBT[...]` | 26 | language-gap | yes | `assign-target 'hBitmapsSBT["Sunflower"]' failed: cannot store into int` |
| assign-target | `Shrine[...]` | 25 | language-gap | yes | `assign-target 'Shrine["Sunflower"]' failed: cannot store into int` |
| assign-target | `&_Rect` | 12 | language-gap | yes | `assign-target '&_Rect' unsupported (logged)` |
| assign-target | `buff_characters[...]` | 10 | language-gap | yes | `assign-target 'buff_characters[0]' failed: cannot store into int` |
| gdip | `Gdip_GraphicsFromImage` | 9 | windows-only | yes | `stub Gdip_GraphicsFromImage() -> falsy (Gdip surface not ported)` |
| builtin | `dllcall` | 8 | windows-only | yes | `stub builtin dllcall() -> falsy (GUI/OS gap)` |
| gdip | `Gdip_DeleteGraphics` | 8 | windows-only | yes | `stub Gdip_DeleteGraphics() -> falsy (Gdip surface not ported)` |
| gdip | `Gdip_GraphicsClear` | 8 | windows-only | yes | `stub Gdip_GraphicsClear() -> falsy (Gdip surface not ported)` |
| assign-target | `&BitmapData1` | 6 | language-gap | yes | `assign-target '&BitmapData1' unsupported (logged)` |
| assign-target | `&BitmapData2` | 6 | language-gap | yes | `assign-target '&BitmapData2' unsupported (logged)` |
| assign-target | `&Height` | 6 | language-gap | yes | `assign-target '&Height' unsupported (logged)` |
| assign-target | `&Scan01` | 6 | language-gap | yes | `assign-target '&Scan01' unsupported (logged)` |
| assign-target | `&Scan02` | 6 | language-gap | yes | `assign-target '&Scan02' unsupported (logged)` |
| assign-target | `&Stride1` | 6 | language-gap | yes | `assign-target '&Stride1' unsupported (logged)` |
| assign-target | `&Stride2` | 6 | language-gap | yes | `assign-target '&Stride2' unsupported (logged)` |
| assign-target | `&Width` | 6 | language-gap | yes | `assign-target '&Width' unsupported (logged)` |
| builtin | `numget` | 6 | windows-only | yes | `stub builtin numget() -> falsy (GUI/OS gap)` |
| builtin | `numput` | 6 | windows-only | yes | `stub builtin numput() -> falsy (GUI/OS gap)` |
| builtin | `comvalue` | 3 | windows-only | yes | `stub builtin comvalue() -> falsy (GUI/OS gap)` |
| builtin | `comobjget` | 1 | windows-only | yes | `stub builtin comobjget() -> falsy (GUI/OS gap)` |
| builtin | `strget` | 1 | windows-only | yes | `stub builtin strget() -> falsy (GUI/OS gap)` |
| builtin | `strptr` | 1 | windows-only | yes | `stub builtin strptr() -> falsy (GUI/OS gap)` |
| for | `for-in` | 1 | language-gap | yes | `for: unsupported enumerable 'ComObjGet("winmgmts:").ExecQuery("SELECT * FROM Win32_OperatingSystem")' (skipped` |
| gdip | `Gdip_UnlockBits` | 1 | windows-only | yes | `stub Gdip_UnlockBits() -> falsy (Gdip surface not ported)` |
| method | `execquery` | 1 | language-gap | yes | `method .execquery() unsupported (logged)` |

## Static top raw calls

- `(`: 46
- `}`: 27
- `{`: 24
- `The`: 12
- `-`: 11
- `This`: 9
- `)",`: 6
- `NumPut(`: 5
- `)"`: 4
- `To`: 4
- `Gdip_GraphicsClear(G,`: 3
- `Enter`: 3
- `When`: 3
- `Enabling`: 2
- `1.`: 2

## Top undefined static calls

- `DllCall`: 231
- `nm_gotoramp`: 124
- `NumPut`: 71
- `nm_gotocannon`: 52
- `nm_updateAction`: 42
- `OnMessage`: 30
- `send`: 29
- `ComCall`: 27
- `ObjRelease`: 21
- `SetLoadingProgress`: 19
- `Sleep`: 17
- `GuiClose`: 17
- `Hypersleep`: 16
- `nm_walk`: 15
- `RegExMatch`: 11
- `mp_UpdateCycles`: 10
- `nm_PlanterTimeUpdate`: 6
- `sleep`: 5
- `IniWrite`: 5
- `nm_SetStatus`: 5
- `StrPut`: 4
- `hypersleep`: 4
- `OnExit`: 4
- `nm_setStats`: 4
- `gdip_disposeimage`: 4
- `nm_autoFieldBoost`: 4
- `VarSetStrCapacity`: 3
- `RunDeeplink`: 3
- `petalQuestDisclaimer`: 3
- `success`: 3
- `map_set`: 2
- `SendMessage`: 2
- `nm_AdvancedGUI`: 2
- `mp_SaveConfig`: 2
- `CloseBrowserTabs`: 2
- `Run`: 2
- `mp_UpdateControls`: 2
- `StrReplace`: 2
- `ProcessClose`: 2
- `nm_ContributorsImage`: 2
