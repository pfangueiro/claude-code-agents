#!/bin/bash
# Handoff Hook - Tracks agent-to-agent handoffs

# Environment variables:
# $FROM_AGENT - Agent handing off
# $TO_AGENT - Agent receiving
# $HANDOFF_TOKEN - Unique handoff identifier
# $CONTEXT - Context being passed
# $FILES_MODIFIED - Files involved
# $VALIDATION_STATUS - Validation result

# Generate timestamp
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DATE=$(date +"%Y-%m-%d")

# Create handoff log
HANDOFF_LOG=".claude/logs/handoffs-${DATE}.jsonl"

# Log the handoff
echo "{
  \"timestamp\": \"${TIMESTAMP}\",
  \"handoff_token\": \"${HANDOFF_TOKEN}\",
  \"from_agent\": \"${FROM_AGENT}\",
  \"to_agent\": \"${TO_AGENT}\",
  \"validation\": \"${VALIDATION_STATUS}\",
  \"files\": \"${FILES_MODIFIED}\",
  \"context\": \"${CONTEXT}\"
}" | jq -c . >> "$HANDOFF_LOG" 2>/dev/null || echo "{\"timestamp\":\"${TIMESTAMP}\",\"handoff_token\":\"${HANDOFF_TOKEN}\",\"from\":\"${FROM_AGENT}\",\"to\":\"${TO_AGENT}\"}" >> "$HANDOFF_LOG"

# Update metrics
METRICS_FILE=".claude/metrics/metrics-${DATE}.csv"
echo "${TIMESTAMP},${HANDOFF_TOKEN},handoff,handoff,\"${FROM_AGENT} -> ${TO_AGENT}\",none,0,${VALIDATION_STATUS}" >> "$METRICS_FILE"

# Console output
echo "🔄 [HANDOFF] ${FROM_AGENT} → ${TO_AGENT} (Token: ${HANDOFF_TOKEN})"

# Create GitHub issue comment if tracking
if [ "$GITHUB_TRACKING" = "true" ] && command -v gh &> /dev/null; then
    # Find issues for both agents
    FROM_ISSUE=$(gh issue list --label "agent:${FROM_AGENT}" --state open --limit 1 --json number -q ".[0].number" 2>/dev/null)
    
    if [ ! -z "$FROM_ISSUE" ]; then
        gh issue comment "$FROM_ISSUE" --body "🔄 **Handoff to ${TO_AGENT}**
Token: \`${HANDOFF_TOKEN}\`
Files: ${FILES_MODIFIED:-None}
Validation: ${VALIDATION_STATUS}" 2>/dev/null &
    fi
fi