#!/bin/bash
# Desktop notification when Claude needs attention
# Works on both Linux (notify-send) and macOS (osascript)

if command -v notify-send &>/dev/null; then
  notify-send -u normal -t 5000 "Claude Code" "Needs your attention" 2>/dev/null
elif command -v osascript &>/dev/null; then
  osascript -e 'display notification "Needs your attention" with title "Claude Code"' 2>/dev/null
fi
