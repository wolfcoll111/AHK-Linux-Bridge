# Natro census

Generated: 2026-10-27 20:02:52
Corpus: `/mnt/games/Apps/NatroMacro/src`

> Triage baseline, not a score. `language-gap` rows are known
> parser/runtime holes. The `assign-target` rows come from running
> standalone `nm_image_assets/**/bitmaps.ahk` files whose containers
> are normally established by the including main script (`Shrine` has
> no visible definition anywhere in the corpus), so the target has no
> live container in isolation. The `for`/`method` rows are Natro's
> COM `ComObjGet(...).ExecQuery(...)` loop and are COM-dependent.
> `windows-only` rows are DllCall/GDI+/COM surfaces replaced by the
> Linux vision layer; `unknown` rows are the actionable headless
> builtins. The JSON companion contains every hit and sample.
> All runtime work happens in a temporary corpus copy with desktop
> effects suppressed; the single worker deadline stop is
> `submacros/StatMonitor.ahk`'s `Loop {}` cut at the sandbox cutoff,
> so that file's inventory is partial.

## Static inventory

- files: **150**
- functions parsed: **671**
- nodes: **21127**
- `__raw__`: **28 (0.13%)**
- parse crashes: **0**
- distinct defined functions: **655**

## Expanded main script

- include files: **33**
- logical lines: **22522**
- expand / parse: **0.895 s / 1.696 s**
- auto statements: **1486**
- functions: **621**
- raw in auto-section: **3**
- include records: `{'directory': 3, 'ok': 32, 'ignored': 1}`

## Runtime stub hits

- files executed: **150**
- timeouts: **0**
- worker deadline stops: **1**
- execution/load errors: **0**
- unknown load-bearing hits: **0**
- known gaps (language/windows/external): **47**

Verdict totals: **windows-only** 38, **language-gap** 7, **setting-noop** 7, **cross-file** 5, **external-service** 2, **parser-raw** 1

Triage table: unknown and known-gap hits only (all hits are in the
JSON).  Benign settings, display-only calls, parser raws and
cross-file calls are counted above but not listed row by row.

| kind | name | count | verdict | load-bearing | sample |
|---|---|---:|---|---|---|
| assign-target | `bitmaps[...]` | 777 | language-gap | yes | `assign-target 'bitmaps["gifted"]' has no live container (logged)` |
| assign-target | `buff_bitmaps[...]` | 35 | language-gap | yes | `assign-target 'buff_bitmaps["pBMHaste"]' has no live container (logged)` |
| assign-target | `hBitmapsSBT[...]` | 26 | language-gap | yes | `assign-target 'hBitmapsSBT["Sunflower"]' has no live container (logged)` |
| assign-target | `Shrine[...]` | 25 | language-gap | yes | `assign-target 'Shrine["Sunflower"]' has no live container (logged)` |
| assign-target | `buff_characters[...]` | 10 | language-gap | yes | `assign-target 'buff_characters[0]' has no live container (logged)` |
| gdip | `Gdip_GraphicsFromImage` | 9 | windows-only | yes | `stub Gdip_GraphicsFromImage() -> falsy (Gdip surface not ported)` |
| gdip | `Gdip_DeleteGraphics` | 8 | windows-only | yes | `stub Gdip_DeleteGraphics() -> falsy (Gdip surface not ported)` |
| gdip | `Gdip_GraphicsClear` | 8 | windows-only | yes | `stub Gdip_GraphicsClear() -> falsy (Gdip surface not ported)` |
| builtin | `comvalue` | 3 | windows-only | yes | `stub builtin comvalue() -> falsy (GUI/OS gap)` |
| builtin | `comcall` | 1 | external-service | yes | `stub builtin comcall() -> falsy (GUI/OS gap)` |
| builtin | `comobjget` | 1 | windows-only | yes | `stub builtin comobjget() -> falsy (GUI/OS gap)` |
| builtin | `objrelease` | 1 | external-service | yes | `stub builtin objrelease() -> falsy (GUI/OS gap)` |
| dllcall | `Combase.dll\RoGetActivationFactory` | 1 | windows-only | yes | `DllCall Combase.dll\RoGetActivationFactory: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `Combase.dll\WindowsCreateString` | 1 | windows-only | yes | `DllCall Combase.dll\WindowsCreateString: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `Combase.dll\WindowsDeleteString` | 1 | windows-only | yes | `DllCall Combase.dll\WindowsDeleteString: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `crypt32\CryptStringToBinary` | 1 | windows-only | yes | `DllCall crypt32\CryptStringToBinary: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipCreateBitmapFromScan0` | 1 | windows-only | yes | `DllCall gdiplus\GdipCreateBitmapFromScan0: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipCreateFont` | 1 | windows-only | yes | `DllCall gdiplus\GdipCreateFont: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipCreateFontFamilyFromName` | 1 | windows-only | yes | `DllCall gdiplus\GdipCreateFontFamilyFromName: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipCreatePen1` | 1 | windows-only | yes | `DllCall gdiplus\GdipCreatePen1: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipCreateRegion` | 1 | windows-only | yes | `DllCall gdiplus\GdipCreateRegion: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipCreateSolidFill` | 1 | windows-only | yes | `DllCall gdiplus\GdipCreateSolidFill: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipCreateStringFormat` | 1 | windows-only | yes | `DllCall gdiplus\GdipCreateStringFormat: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDeleteBrush` | 1 | windows-only | yes | `DllCall gdiplus\GdipDeleteBrush: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDeleteGraphics` | 1 | windows-only | yes | `DllCall gdiplus\GdipDeleteGraphics: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDeletePen` | 1 | windows-only | yes | `DllCall gdiplus\GdipDeletePen: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDeleteRegion` | 1 | windows-only | yes | `DllCall gdiplus\GdipDeleteRegion: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDisposeImage` | 1 | windows-only | yes | `DllCall gdiplus\GdipDisposeImage: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDrawEllipse` | 1 | windows-only | yes | `DllCall gdiplus\GdipDrawEllipse: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDrawImageRectRect` | 1 | windows-only | yes | `DllCall gdiplus\GdipDrawImageRectRect: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDrawLine` | 1 | windows-only | yes | `DllCall gdiplus\GdipDrawLine: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipDrawRectangle` | 1 | windows-only | yes | `DllCall gdiplus\GdipDrawRectangle: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipFillEllipse` | 1 | windows-only | yes | `DllCall gdiplus\GdipFillEllipse: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipFillRectangle` | 1 | windows-only | yes | `DllCall gdiplus\GdipFillRectangle: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipGetClip` | 1 | windows-only | yes | `DllCall gdiplus\GdipGetClip: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipGetImageGraphicsContext` | 1 | windows-only | yes | `DllCall gdiplus\GdipGetImageGraphicsContext: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipGetImageHeight` | 1 | windows-only | yes | `DllCall gdiplus\GdipGetImageHeight: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipGetImageWidth` | 1 | windows-only | yes | `DllCall gdiplus\GdipGetImageWidth: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipGraphicsClear` | 1 | windows-only | yes | `DllCall gdiplus\GdipGraphicsClear: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipResetClip` | 1 | windows-only | yes | `DllCall gdiplus\GdipResetClip: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipSetClipRect` | 1 | windows-only | yes | `DllCall gdiplus\GdipSetClipRect: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipSetClipRegion` | 1 | windows-only | yes | `DllCall gdiplus\GdipSetClipRegion: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipSetInterpolationMode` | 1 | windows-only | yes | `DllCall gdiplus\GdipSetInterpolationMode: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `gdiplus\GdipSetSmoothingMode` | 1 | windows-only | yes | `DllCall gdiplus\GdipSetSmoothingMode: Windows ABI not modeled on Linux (returns 0; logged)` |
| dllcall | `ole32\CLSIDFromString` | 1 | windows-only | yes | `DllCall ole32\CLSIDFromString: Windows ABI not modeled on Linux (returns 0; logged)` |
| for | `for-in` | 1 | language-gap | yes | `for: unsupported enumerable 'ComObjGet("winmgmts:").ExecQuery("SELECT * FROM Win32_OperatingSystem")' (skipped` |
| method | `execquery` | 1 | language-gap | yes | `method .execquery() unsupported (logged)` |

## Worker deadline stops (partial inventory)

- submacros/StatMonitor.ahk: stopped at worker deadline (4.0s; partial inventory)

## Static top raw calls

- `(`: 5
- `Gdip_GraphicsClear(G,`: 3
- `{`: 2
- `continue`: 2
- `Monitors["TotalCount"]++`: 1
- `stats[wParam][2]`: 1
- `?`: 1
- `sections[v.section]`: 1
- `embed["description"]`: 1
- `Download`: 1
- `%prefix%fps`: 1
- `(((c>>16)&0xFF)`: 1
- `BlenderIndex%BlenderRot%--`: 1
- `ShrineIndex%shrineRot%--`: 1
- `break`: 1

## Top undefined static calls

- `DllCall`: 214
- `nm_gotoramp`: 122
- `NumPut`: 77
- `nm_gotocannon`: 51
- `OnMessage`: 30
- `send`: 29
- `ComCall`: 27
- `ObjRelease`: 21
- `GuiClose`: 17
- `Hypersleep`: 16
- `Sleep`: 16
- `nm_walk`: 15
- `RegExMatch`: 11
- `sleep`: 5
- `IniWrite`: 5
- `nm_SetStatus`: 5
- `StrPut`: 4
- `hypersleep`: 4
- `OnExit`: 4
- `gdip_disposeimage`: 4
- `nm_autoFieldBoost`: 4
- `VarSetStrCapacity`: 3
- `Run`: 3
- `petalQuestDisclaimer`: 3
- `success`: 3
- `map_set`: 2
- `SendMessage`: 2
- `StrReplace`: 2
- `ProcessClose`: 2
- `UpdateConfig`: 2
- `nm_%RotateQuest%QuestProg`: 2
- `MouseMove`: 2
- `nm_feed`: 2
- `nm_ToAnyBooster`: 2
- `Numput`: 1
- `SplitPath`: 1
- `DirCreate`: 1
- `getHashes`: 1
- `hashDefaults`: 1
- `nm_Tab%tab%%c%`: 1

