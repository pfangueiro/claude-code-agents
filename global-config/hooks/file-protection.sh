#!/bin/bash
# File protection hook: Block edits to sensitive files
# Runs on PreToolUse for Write/Edit/Read operations

input=$(cat)

# Extract file path from tool input
file_path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

if [[ -z "$file_path" ]]; then
  exit 0
fi

# Patterns to block
BLOCKED_PATTERNS=(
  ".env"
  ".env.*"
  "secrets/"
  "*.key"
  "*.pem"
  "*.p12"
  "*.pfx"
  ".aws/credentials"
  ".ssh/id_"
  "credentials.json"
  "serviceAccount.json"
)

# Check if file matches blocked patterns
for pattern in "${BLOCKED_PATTERNS[@]}"; do
  case "$file_path" in
    *$pattern*)
      echo "🔒 BLOCKED: Cannot modify sensitive file: $file_path"
      echo "This file matches protected pattern: $pattern"
      exit 1
      ;;
  esac
done

exit 0
