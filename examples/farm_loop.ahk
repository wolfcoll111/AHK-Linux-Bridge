#Requires AutoHotkey v2.0
; Farm loop: press F1 to run 2 cycles
F1::
{
    Loop 2 {
        Send "farm"
        Sleep 100
        Click 960, 540 left
    }
}
