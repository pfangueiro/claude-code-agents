#!/bin/bash
# Verify session snapshot was saved after context compaction
# Pairs with pre-compact.sh which saves the snapshot before compaction
# Hook event: PostCompact

SESSIONS_DIR="$HOME/.claude/sessions"
PROJECT_NAME=$(basename "$(pwd)" | tr ' ' '-' | tr '[:upper:]' '[:lower:]')

# Check that a recent auto-snapshot exists (created by pre-compact.sh within last 60 seconds)
LATEST=$(ls -t "${SESSIONS_DIR}/auto-${PROJECT_NAME}-"*.md 2>/dev/null | head -1)

if [ -z "$LATEST" ]; then
    echo "Warning: No pre-compact snapshot found for ${PROJECT_NAME}"
    exit 0
fi

# Check the snapshot is recent (within last 60 seconds)
if [ "$(uname)" = "Darwin" ]; then
    FILE_AGE=$(( $(date +%s) - $(stat -f %m "$LATEST") ))
else
    FILE_AGE=$(( $(date +%s) - $(stat -c %Y "$LATEST") ))
fi

if [ "$FILE_AGE" -lt 60 ]; then
    echo "Session snapshot verified: $(basename "$LATEST")"
else
    echo "Warning: Latest snapshot is ${FILE_AGE}s old — pre-compact hook may not have fired"
fi

exit 0
