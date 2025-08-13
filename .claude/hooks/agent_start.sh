#!/bin/bash
# Agent Start Hook - Tracks when agents begin tasks

# Environment variables provided by Claude Code:
# $AGENT_NAME - Name of the agent starting
# $TASK_ID - Unique task identifier
# $TASK_DESCRIPTION - What the agent is doing
# $PARENT_TASK - Previous task in chain (if any)

# Create logs directory if it doesn't exist
mkdir -p .claude/logs
mkdir -p .claude/metrics

# Generate timestamp
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DATE=$(date +"%Y-%m-%d")

# Log to daily metrics file (CSV format for easy analysis)
METRICS_FILE=".claude/metrics/metrics-${DATE}.csv"

# Create header if file doesn't exist
if [ ! -f "$METRICS_FILE" ]; then
    echo "timestamp,task_id,agent,event,description,parent_task,tokens_used,status" > "$METRICS_FILE"
fi

# Append metrics
echo "${TIMESTAMP},${TASK_ID:-auto-$(uuidgen)},${AGENT_NAME},start,\"${TASK_DESCRIPTION}\",${PARENT_TASK:-none},0,in_progress" >> "$METRICS_FILE"

# Create GitHub issue if GITHUB_TRACKING is enabled
if [ "$GITHUB_TRACKING" = "true" ] && command -v gh &> /dev/null; then
    # Check if issue already exists
    EXISTING_ISSUE=$(gh issue list --label "task:${TASK_ID}" --limit 1 --json number -q ".[0].number" 2>/dev/null)
    
    if [ -z "$EXISTING_ISSUE" ]; then
        # Create new issue
        gh issue create \
            --title "🤖 Task: ${TASK_DESCRIPTION}" \
            --label "agent:${AGENT_NAME},task:${TASK_ID},status:in-progress" \
            --body "## Task Details
            
**Agent**: ${AGENT_NAME}
**Task ID**: ${TASK_ID}
**Started**: ${TIMESTAMP}
**Parent Task**: ${PARENT_TASK:-none}

### Description
${TASK_DESCRIPTION}

### Status
⏳ In Progress

---
*This issue is automatically tracked by Claude Code Agents*" 2>/dev/null &
    fi
fi

# Log to structured JSON for advanced analysis
JSON_LOG=".claude/logs/tasks.jsonl"
echo "{\"timestamp\":\"${TIMESTAMP}\",\"task_id\":\"${TASK_ID}\",\"agent\":\"${AGENT_NAME}\",\"event\":\"start\",\"description\":\"${TASK_DESCRIPTION}\",\"parent_task\":\"${PARENT_TASK}\"}" >> "$JSON_LOG"

# Console output for visibility
echo "📊 [TRACKING] Agent '${AGENT_NAME}' started task ${TASK_ID}"