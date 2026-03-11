#!/bin/bash
# Session end hook: logs session completion on Stop event
# Writes to ~/.claude/analytics/session-summaries.jsonl

SUMMARIES_FILE="$HOME/.claude/analytics/session-summaries.jsonl"

mkdir -p "$(dirname "$SUMMARIES_FILE")"

input=$(cat)

if ! command -v jq &>/dev/null; then
  exit 0
fi

session_id=$(echo "$input" | jq -r '.session_id // empty' 2>/dev/null)
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [[ -n "$session_id" ]]; then
  jq -n \
    --arg event "session_end" \
    --arg sid "$session_id" \
    --arg cwd "$cwd" \
    --arg ts "$timestamp" \
    '{event: $event, session_id: $sid, cwd: $cwd, timestamp: $ts}' \
    >> "$SUMMARIES_FILE"
fi

exit 0
