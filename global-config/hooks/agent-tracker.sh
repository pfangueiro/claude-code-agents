#!/bin/bash
# Agent lifecycle tracker: logs SubagentStart/SubagentStop events
# Writes to ~/.claude/analytics/agent-events.jsonl for real-time tracking
#
# Usage (configured in settings.json):
#   SubagentStart: agent-tracker.sh start
#   SubagentStop:  agent-tracker.sh stop

EVENT_TYPE="${1:-start}"
EVENTS_FILE="$HOME/.claude/analytics/agent-events.jsonl"

mkdir -p "$(dirname "$EVENTS_FILE")"

input=$(cat)

# Require jq for safe JSON construction
if ! command -v jq &>/dev/null; then
  exit 0
fi

session_id=$(echo "$input" | jq -r '.session_id // empty' 2>/dev/null)
agent_type=$(echo "$input" | jq -r '.subagent_type // .agent_type // "unknown"' 2>/dev/null)
description=$(echo "$input" | jq -r '.description // empty' 2>/dev/null)
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [[ "$EVENT_TYPE" == "stop" ]]; then
  duration_ms=$(echo "$input" | jq -r '.duration_ms // 0' 2>/dev/null)
  # Validate duration_ms is numeric
  if ! [[ "$duration_ms" =~ ^[0-9]+$ ]]; then
    duration_ms=0
  fi
  status=$(echo "$input" | jq -r '.status // "completed"' 2>/dev/null)

  jq -n \
    --arg event "agent_stop" \
    --arg sid "$session_id" \
    --arg agent "$agent_type" \
    --arg desc "$description" \
    --argjson dur "${duration_ms:-0}" \
    --arg status "$status" \
    --arg ts "$timestamp" \
    '{event: $event, session_id: $sid, agent_type: $agent, description: $desc, duration_ms: $dur, status: $status, timestamp: $ts}' \
    >> "$EVENTS_FILE"
else
  jq -n \
    --arg event "agent_start" \
    --arg sid "$session_id" \
    --arg agent "$agent_type" \
    --arg desc "$description" \
    --arg ts "$timestamp" \
    '{event: $event, session_id: $sid, agent_type: $agent, description: $desc, timestamp: $ts}' \
    >> "$EVENTS_FILE"
fi

exit 0
