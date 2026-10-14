; F1:: anti-AFK farm loop (AHK-Linux-Bridge v0.2 demo)
; Fires from Linux via:  ahk-bridge run afk_farm_advanced.ahk --hotkey F1 --jitter 0.2
; Or under real AHK on Wine for comparison:  ahk-wine.sh afk_farm_advanced.ahk
#Requires AutoHotkey v2.0

F1::
{
    cycles := 3
    delay := 500
    Loop cycles {
        ; small human-like wander before each action
        MouseMove 960, 540
        Sleep delay
        Send "w"
        Sleep 120
        ; jump (space) with slight timing variation
        Send "{Space}"
        Sleep 300
        Click 960, 540 left
        If FoundX >= 0 {
            Send "harvest"
        } Else {
            Send "wait"
        }
    }
    MsgBox "farm run done"
}

F2::Send "hello from linux"

:*:btw::by the way
