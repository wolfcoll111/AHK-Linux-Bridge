#!/usr/bin/env bash
# ahk-wine.sh — run an .ahk script with REAL AutoHotkey v2 under Wine.
# Use for parity checks: does the macro behave the same under genuine AHK
# (Wine) vs the native bridge (`ahk-bridge run`)?
#
#   ahk-wine.sh examples/farm_loop.ahk [ahk-args...]
#
# Requires: ~/Apps/AutoHotkey-v2/AutoHotkey64.exe (portable zip from
# github.com/AutoHotkey/AutoHotkey releases). Override with AHK_EXE.
set -euo pipefail
AHK_EXE="${AHK_EXE:-$HOME/Apps/AutoHotkey-v2/AutoHotkey64.exe}"
if [[ ! -f "$AHK_EXE" ]]; then
  echo "ahk-wine.sh: AutoHotkey not found at $AHK_EXE" >&2
  echo "  download AutoHotkey_2.x.zip and extract to ~/Apps/AutoHotkey-v2/" >&2
  exit 2
fi
if [[ $# -lt 1 ]]; then
  echo "usage: ahk-wine.sh <script.ahk> [args...]" >&2
  exit 2
fi
SCRIPT="$1"; shift
# Convert to Wine path (Z: maps to /) so AHK sees a Windows path.
WIN_SCRIPT="$(winepath -w "$SCRIPT")"
exec wine "$AHK_EXE" "$WIN_SCRIPT" "$@"
