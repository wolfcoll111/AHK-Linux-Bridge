; TDS-style tower placement (bridge-compatible template).
; Fill in YOUR coordinates at 1280x720 game resolution, one block per tower.
; Run:  ahk-bridge run tds_placement.ahk --hotkey F1 --jitter 0.1
; Stop: Escape (master abort) or SUPER+SHIFT+F1 on Hyprland.
#Requires AutoHotkey v2.0

F1::
{
    ; -- tower 1: place scout --
    Send "1"
    Sleep 300
    Click 640, 400 left
    Sleep 2500

    ; -- tower 2: place sniper, rotate once --
    Send "2"
    Sleep 300
    Click 700, 420 left
    Sleep 800
    Send "r"
    Sleep 2500

    ; -- upgrade loop: click tower 1 three times with waits --
    Loop 3 {
        Click 640, 400 left
        Sleep 1200
    }
    MsgBox "placement done"
}

; quick single-tower hotkey
F2::
{
    Send "1"
    Sleep 300
    Click 640, 400 left
}
