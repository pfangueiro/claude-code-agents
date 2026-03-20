#!/bin/bash
# Auto-save minimal session snapshot before context compaction
# Prevents context loss when conversation is compressed
# Hook event: PreCompact

SESSIONS_DIR="$HOME/.claude/sessions"
mkdir -p "$SESSIONS_DIR"

# Generate snapshot filename from project directory and timestamp
PROJECT_NAME=$(basename "$(pwd)" | tr ' ' '-' | tr '[:upper:]' '[:lower:]')
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
SNAPSHOT_FILE="${SESSIONS_DIR}/auto-${PROJECT_NAME}-${TIMESTAMP}.md"

# Get git context
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
LAST_COMMIT=$(git log -1 --format="%h %s" 2>/dev/null || echo "unknown")
MODIFIED_FILES=$(git diff --name-only 2>/dev/null | head -20)
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null | head -20)

# Write minimal snapshot
cat > "$SNAPSHOT_FILE" << EOF
# Auto-Snapshot (Pre-Compact)

**Date**: $(date '+%Y-%m-%d %H:%M:%S')
**Project**: ${PROJECT_NAME}
**Branch**: ${BRANCH}
**Last commit**: ${LAST_COMMIT}

## Modified Files (unstaged)
${MODIFIED_FILES:-"(none)"}

## Staged Files
${STAGED_FILES:-"(none)"}

## Note
This is an automatic snapshot created before context compaction.
Use /resume-session to load a full session, or /save-session to create a detailed one.
EOF

# Clean up old auto-snapshots (keep last 10 per project)
ls -t "${SESSIONS_DIR}/auto-${PROJECT_NAME}-"*.md 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null

exit 0
