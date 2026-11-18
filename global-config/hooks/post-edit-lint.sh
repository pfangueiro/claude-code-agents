#!/bin/bash
# PostToolUse edit feedback for Write/Edit. For an edited TS/JS file it runs the
# nearest project-local ESLint (node_modules/.bin/eslint) in check-only mode on that
# one file, from the session's working directory (the hook's own cwd, unchanged), so
# ESLint discovers the same configuration as the project's own invocation even when
# the binary is hoisted to an ancestor; for TS/JS and Python it warns about leftover
# debug statements. It never passes --fix or rewrites files, never resolves ESLint
# from PATH or npx (no downloads), never runs a project suite, bounds its output and
# always exits 0. This is fast feedback, not an acceptance gate: required checks
# belong to /quality-gate and the delivery check plan.

MAX_LINES=20

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

if [[ -z "$file_path" ]]; then
  exit 0
fi
# Resolve a relative path against the hook's cwd so discovery uses real ancestors.
if [[ "$file_path" != /* ]]; then
  file_path="$PWD/$file_path"
fi
if [[ ! -f "$file_path" ]]; then
  exit 0
fi

# Print at most MAX_LINES lines of $1 and say when output was cut.
print_bounded() {
  local total
  total=$(printf '%s\n' "$1" | wc -l | tr -d ' ')
  printf '%s\n' "$1" | head -n "$MAX_LINES"
  if (( total > MAX_LINES )); then
    echo "... output truncated ($total lines); run the project's lint command for the full report"
  fi
}

# Print the nearest ancestor of $1 that holds an executable node_modules/.bin/eslint.
find_eslint_root() {
  local dir parent
  dir=$(dirname "$1")
  while true; do
    if [[ -x "$dir/node_modules/.bin/eslint" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    parent=$(dirname "$dir")
    if [[ "$parent" == "$dir" ]]; then
      return 1
    fi
    dir=$parent
  done
}

# Check-only lint of one file; reports problems without blocking the edit. Only the
# binary location comes from the nearest install; the working directory stays the
# session's, so configuration discovery is not moved to the binary's directory.
lint_file() {
  local root output status
  root=$(find_eslint_root "$1") || return 0
  output=$("$root/node_modules/.bin/eslint" --quiet --no-color "$1" </dev/null 2>&1)
  status=$?
  case "$status" in
    0) ;;
    1)
      echo "ESLint feedback (check-only, not an acceptance gate) for $1:"
      print_bounded "$output"
      ;;
    *)
      echo "ESLint could not check $1 (exit $status); the edit was kept:"
      print_bounded "$output"
      ;;
  esac
}

case "$file_path" in
  *.ts|*.tsx|*.js|*.jsx)
    lint_file "$file_path"
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
