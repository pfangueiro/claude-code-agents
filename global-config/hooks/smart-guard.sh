#!/bin/bash
# Permission request hook: auto-approve safe operations, audit dangerous ones
# Runs on PermissionRequest event
#
# Behavior:
#   - Auto-approves read-only tools when target is not a sensitive file
#   - Logs all other permission requests to audit trail
#   - Lets user decide for non-safe operations (exit 0 with no output)

AUDIT_FILE="$HOME/.claude/analytics/permission-audit.jsonl"

mkdir -p "$(dirname "$AUDIT_FILE")"

input=$(cat)

if ! command -v jq &>/dev/null; then
  exit 0
fi

tool_name=$(echo "$input" | jq -r '.tool_name // empty' 2>/dev/null)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.filePath // .tool_input.path // empty' 2>/dev/null)
session_id=$(echo "$input" | jq -r '.session_id // empty' 2>/dev/null)

# Auto-approve safe read-only operations (but not on sensitive files)
case "$tool_name" in
  Read|Glob|Grep|LSP)
    # Check if target matches sensitive file patterns before approving
    case "$file_path" in
      *.env|*.env.*|*/.env|*/.env.*)
        ;; # Fall through — let user decide
      *secrets/*|*.key|*.pem|*.p12|*.pfx)
        ;; # Fall through — let user decide
      *.aws/credentials*|*.ssh/id_*|*credentials.json|*serviceAccount.json)
        ;; # Fall through — let user decide
      *)
        echo "allow"
        exit 0
        ;;
    esac
    ;;
esac

# Log non-trivial permission requests for audit
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
jq -n \
  --arg event "permission_request" \
  --arg tool "$tool_name" \
  --arg path "$file_path" \
  --arg sid "$session_id" \
  --arg ts "$timestamp" \
  '{event: $event, tool: $tool, file_path: $path, session_id: $sid, timestamp: $ts}' \
  >> "$AUDIT_FILE" 2>/dev/null

# Let user decide for everything else
exit 0
