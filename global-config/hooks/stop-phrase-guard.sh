#!/bin/bash
# Stop-phrase guard: Detects ownership dodging, permission-seeking, and premature stopping
# Runs on: Stop event
# Based on: Stella Laurenzo's analysis (GitHub #42796) — 173 violations in 16 days
#
# Receives JSON via stdin with:
#   session_id, cwd, transcript_path, stop_hook_active, last_assistant_message
#
# Exit 0 = allow stop (no violation detected)
# Exit 2 = block stop, inject feedback (violation detected — Claude must continue)
#
# Violations logged to ~/.claude/analytics/stop-violations.jsonl

VIOLATIONS_FILE="$HOME/.claude/analytics/stop-violations.jsonl"

mkdir -p "$(dirname "$VIOLATIONS_FILE")"

input=$(cat)

# Require jq
if ! command -v jq &>/dev/null; then
  exit 0
fi

last_message=$(echo "$input" | jq -r '.last_assistant_message // empty' 2>/dev/null)

# No message content — allow stop
if [[ -z "$last_message" ]]; then
  exit 0
fi

# Lowercase for matching
msg_lower=$(echo "$last_message" | tr '[:upper:]' '[:lower:]')

category=""
matched_phrase=""

# --- Category 1: Ownership dodging (Claude deflects work to user) ---
ownership_patterns=(
  "i'd recommend you"
  "i'd suggest you"
  "you might want to"
  "you could try"
  "you should consider"
  "you may want to"
  "i'll leave it to you"
  "you'll need to"
  "i recommend that you"
  "it's up to you to"
  "the next step would be for you to"
)

for phrase in "${ownership_patterns[@]}"; do
  if [[ "$msg_lower" == *"$phrase"* ]]; then
    category="ownership_dodging"
    matched_phrase="$phrase"
    break
  fi
done

# --- Category 2: Permission-seeking (Claude asks instead of acting) ---
if [[ -z "$category" ]]; then
  permission_patterns=(
    "shall i continue"
    "shall i proceed"
    "would you like me to"
    "do you want me to"
    "should i go ahead"
    "should i continue"
    "want me to"
    "let me know if you'd like"
    "let me know if you want"
    "if you'd like me to"
    "if you want me to proceed"
  )

  for phrase in "${permission_patterns[@]}"; do
    if [[ "$msg_lower" == *"$phrase"* ]]; then
      category="permission_seeking"
      matched_phrase="$phrase"
      break
    fi
  done
fi

# --- Category 3: Premature stopping ---
if [[ -z "$category" ]]; then
  stopping_patterns=(
    "that should be enough"
    "this is a good stopping point"
    "i think we're in good shape"
    "that covers the main"
    "i'll stop here"
    "that's all for now"
    "we can stop here"
    "i think that's sufficient"
    "that wraps up"
    "i believe that covers"
  )

  for phrase in "${stopping_patterns[@]}"; do
    if [[ "$msg_lower" == *"$phrase"* ]]; then
      category="premature_stopping"
      matched_phrase="$phrase"
      break
    fi
  done
fi

# --- Category 4: Known-limitation labeling ---
if [[ -z "$category" ]]; then
  limitation_patterns=(
    "this is beyond my capabilities"
    "i'm unable to"
    "i cannot do this"
    "this is outside my scope"
    "i don't have the ability"
    "i'm not able to"
  )

  for phrase in "${limitation_patterns[@]}"; do
    if [[ "$msg_lower" == *"$phrase"* ]]; then
      category="known_limitation"
      matched_phrase="$phrase"
      break
    fi
  done
fi

# No violation — allow stop
if [[ -z "$category" ]]; then
  exit 0
fi

# --- Violation detected ---
session_id=$(echo "$input" | jq -r '.session_id // empty' 2>/dev/null)
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Log to JSONL
jq -n \
  --arg event "stop_violation" \
  --arg cat "$category" \
  --arg phrase "$matched_phrase" \
  --arg sid "$session_id" \
  --arg cwd "$cwd" \
  --arg ts "$timestamp" \
  '{event: $event, category: $cat, matched_phrase: $phrase, session_id: $sid, cwd: $cwd, timestamp: $ts}' \
  >> "$VIOLATIONS_FILE" 2>/dev/null

# Block the stop — exit 2 with feedback message that gets injected back to Claude
echo "STOP VIOLATION [$category]: Detected phrase \"$matched_phrase\". Do not deflect, ask permission, or stop prematurely. Complete the task fully — read files, implement changes, verify results. Continue working."
exit 2
