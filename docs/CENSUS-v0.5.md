# Natro census

Generated: 2026-10-21 19:00:54
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
- functions parsed: **593**
- nodes: **22125**
- `__raw__`: **422 (1.91%)**
- parse crashes: **0**
- distinct defined functions: **574**

## Expanded main script

- include files: **36**
- logical lines: **23575**
- expand / parse: **0.42 s / 1.506 s**
- auto statements: **1758**
- functions: **636**
- raw in auto-section: **59**
- include records: `{'directory': 3, 'ok': 35, 'ignored': 1}`

## Runtime stub hits

- files executed: **150**
- timeouts: **0**
- worker deadline stops: **1**
- execution/load errors: **2**
- unknown load-bearing hits: **10**
- known gaps (language/windows/external): **28**

Verdict totals: **language-gap** 16, **windows-only** 12, **unknown** 10, **setting-noop** 9, **cross-file** 5, **parser-raw** 1

Triage table: unknown and known-gap hits only (all hits are in the
JSON).  Benign settings, display-only calls, parser raws and
cross-file calls are counted above but not listed row by row.

| kind | name | count | verdict | load-bearing | sample |
|---|---|---:|---|---|---|
| assign-target | `Inner` | 1500 | language-gap | yes | `assign-target 'Inner' has no live container (logged)` |
| assign-target | `bitmaps[...]` | 832 | language-gap | yes | `assign-target 'bitmaps["pBMHaste"]' has no live container (logged)` |
| assign-target | `Outer` | 500 | language-gap | yes | `assign-target 'Outer"Y", N := "X"0' has no live container (logged)` |
| assign-target | `settings[...]` | 435 | language-gap | yes | `assign-target 'settings["webhook"]' failed: cannot store into str` |
| for | `for-in` | 201 | language-gap | yes | `for: unsupported enumerable 'ComObjGet("winmgmts:").ExecQuery("SELECT * FROM Win32_OperatingSystem")' (skipped` |
| assign-target | `buff_bitmaps[...]` | 70 | language-gap | yes | `assign-target 'buff_bitmaps["pBMHaste"]' has no live container (logged)` |
| assign-target | `timers[...]` | 37 | language-gap | yes | `assign-target 'timers.mobs.values[1]' failed: invalid literal for int() with base 10: 'values'` |
| gdip-error | `Gdip_CreateBitmap` | 30 | windows-only | yes | `Gdip_CreateBitmap failed: bitmap dimensions must be positive` |
| assign-target | `buff_values[...]` | 28 | language-gap | yes | `assign-target 'buff_values[v]' has no live container (logged)` |
| assign-target | `hBitmapsSBT[...]` | 26 | language-gap | yes | `assign-target 'hBitmapsSBT["Sunflower"]' has no live container (logged)` |
| assign-target | `Shrine[...]` | 25 | language-gap | yes | `assign-target 'Shrine["Sunflower"]' has no live container (logged)` |
| assign-target | `planters[...]` | 13 | language-gap | yes | `assign-target 'planters["blueclayplanter"]' failed: cannot store into str` |
| assign-target | `buff_characters[...]` | 10 | language-gap | yes | `assign-target 'buff_characters[0]' has no live container (logged)` |
| builtin | `dllcall` | 9 | windows-only | yes | `stub builtin dllcall() -> falsy (GUI/OS gap)` |
| command | `Sleep` | 8 | unknown | yes | `Sleep (100) (OS/window op, linux no-op)` |
| builtin | `numget` | 6 | windows-only | yes | `stub builtin numget() -> falsy (GUI/OS gap)` |
| builtin | `numput` | 6 | windows-only | yes | `stub builtin numput() -> falsy (GUI/OS gap)` |
| builtin | `iniread` | 5 | unknown | yes | `stub builtin iniread() -> falsy (GUI/OS gap)` |
| assign-target | `(bitmaps` | 4 | language-gap | yes | `assign-target '(bitmaps' unsupported (logged)` |
| builtin | `onmessage` | 4 | windows-only | yes | `stub builtin onmessage() -> falsy (GUI/OS gap)` |
| builtin | `comvalue` | 3 | windows-only | yes | `stub builtin comvalue() -> falsy (GUI/OS gap)` |
| builtin | `strptr` | 3 | windows-only | yes | `stub builtin strptr() -> falsy (GUI/OS gap)` |
| builtin | `datediff` | 2 | unknown | yes | `stub builtin datediff() -> falsy (GUI/OS gap)` |
| builtin | `onexit` | 2 | unknown | yes | `stub builtin onexit() -> falsy (GUI/OS gap)` |
| builtin | `oserror` | 2 | unknown | yes | `stub builtin oserror() -> falsy (GUI/OS gap)` |
| command | `SplitPath` | 2 | unknown | yes | `SplitPath (A_AhkPath, , &ahkDirectory) (OS/window op, linux no-op)` |
| gdip | `Gdip_GraphicsFromImage` | 2 | windows-only | yes | `stub Gdip_GraphicsFromImage() -> falsy (Gdip surface not ported)` |
| method | `rawread` | 2 | language-gap | yes | `method .rawread() unsupported (logged)` |
| assign-target | `(buff_bitmaps` | 1 | language-gap | yes | `assign-target '(buff_bitmaps' unsupported (logged)` |
| assign-target | `(buff_values` | 1 | language-gap | yes | `assign-target '(buff_values' unsupported (logged)` |
| builtin | `comobjget` | 1 | windows-only | yes | `stub builtin comobjget() -> falsy (GUI/OS gap)` |
| builtin | `imagesearch` | 1 | unknown | yes | `stub builtin imagesearch() -> falsy (GUI/OS gap)` |
| builtin | `number` | 1 | unknown | yes | `stub builtin number() -> falsy (GUI/OS gap)` |
| builtin | `sendmessage` | 1 | windows-only | yes | `stub builtin sendmessage() -> falsy (GUI/OS gap)` |
| builtin | `strget` | 1 | windows-only | yes | `stub builtin strget() -> falsy (GUI/OS gap)` |
| builtin | `string` | 1 | unknown | yes | `stub builtin string() -> falsy (GUI/OS gap)` |
| command | `sleep` | 1 | unknown | yes | `sleep (100) (OS/window op, linux no-op)` |
| gdip | `Gdip_UnlockBits` | 1 | windows-only | yes | `stub Gdip_UnlockBits() -> falsy (Gdip surface not ported)` |

## Errors

- `lib/HashFile.ahk`: If:  x4
- `submacros/natro_macro.ahk`: If:  x4

## Worker deadline stops (partial inventory)

- submacros/StatMonitor.ahk: stopped at worker deadline (4.001s; partial inventory)

## Static top raw calls

- `(`: 46
- `}`: 27
- `{`: 25
- `The`: 12
- `-`: 11
- `This`: 9
- `'`: 8
- `)",`: 6
- `NumPut(`: 5
- `)"`: 4
- `To`: 4
- `Enter`: 3
- `When`: 3
- `)`: 2
- `Enabling`: 2

## Top undefined static calls

- `DllCall`: 219
- `nm_gotoramp`: 124
- `NumPut`: 69
- `nm_gotocannon`: 52
- `nm_updateAction`: 42
- `OnMessage`: 30
- `send`: 29
- `ComCall`: 27
- `ObjRelease`: 21
- `GuiClose`: 17
- `Hypersleep`: 16
- `nm_walk`: 15
- `RegExMatch`: 11
- `mp_UpdateCycles`: 10
- `nm_PlanterTimeUpdate`: 6
- `nm_SetStatus`: 5
- `hypersleep`: 4
- `OnExit`: 4
- `nm_setStats`: 4
- `gdip_disposeimage`: 4
- `nm_autoFieldBoost`: 4
- `VarSetStrCapacity`: 3
- `RunDeeplink`: 3
- `petalQuestDisclaimer`: 3
- `IniWrite`: 3
- `success`: 3
- `nm_AdvancedGUI`: 2
- `mp_SaveConfig`: 2
- `CloseBrowserTabs`: 2
- `mp_UpdateControls`: 2
- `StrReplace`: 2
- `nm_ContributorsImage`: 2
- `UpdateConfig`: 2
- `nm_%RotateQuest%QuestProg`: 2
- `MouseMove`: 2
- `nm_feed`: 2
- `nm_ToAnyBooster`: 2
- `Numput`: 1
- `map_set`: 1
- `RunBrowser`: 1
