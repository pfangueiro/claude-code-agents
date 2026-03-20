#!/bin/bash
# Auto-lint TypeScript/JavaScript/Python files after Write/Edit
# Also warns about leftover debug statements
# Reads tool result from stdin, extracts file path

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

if [[ -z "$file_path" ]]; then
  exit 0
fi

# --- Lint TS/JS files ---
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

# --- Debug statement detection (non-blocking warning) ---
case "$file_path" in
  *.ts|*.tsx|*.js|*.jsx)
    debug_hits=$(grep -n -E '^\s*(console\.(log|debug|trace)\(|debugger\b)' "$file_path" 2>/dev/null)
    if [[ -n "$debug_hits" ]]; then
      echo "Warning: possible debug statements in $file_path:"
      echo "$debug_hits" | head -5
    fi
    ;;
  *.py)
    debug_hits=$(grep -n -E '^\s*(print\(|breakpoint\(\)|import pdb|pdb\.set_trace\(\))' "$file_path" 2>/dev/null)
    if [[ -n "$debug_hits" ]]; then
      echo "Warning: possible debug statements in $file_path:"
      echo "$debug_hits" | head -5
    fi
    ;;
esac

exit 0
