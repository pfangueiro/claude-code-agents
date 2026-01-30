#!/bin/bash
# Auto-lint TypeScript/JavaScript files after Write/Edit
# Reads tool result from stdin, extracts file path

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

if [[ -z "$file_path" ]]; then
  exit 0
fi

# Only lint TS/JS files
case "$file_path" in
  *.ts|*.tsx|*.js|*.jsx)
    # Find nearest node_modules with eslint
    dir=$(dirname "$file_path")
    while [[ "$dir" != "/" ]]; do
      if [[ -f "$dir/node_modules/.bin/eslint" ]]; then
        "$dir/node_modules/.bin/eslint" --fix --quiet "$file_path" 2>/dev/null
        break
      fi
      dir=$(dirname "$dir")
    done
    ;;
esac

exit 0
