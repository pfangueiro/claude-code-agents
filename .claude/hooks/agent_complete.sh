#!/bin/bash
# Agent Complete Hook - Tracks when agents finish tasks

# Environment variables provided by Claude Code:
# $AGENT_NAME - Name of the agent
# $TASK_ID - Unique task identifier
# $TASK_STATUS - success/failure
# $TOKENS_USED - Number of tokens consumed
# $EXECUTION_TIME - Time taken in seconds
# $OUTPUT_FILES - Files created/modified
# $NEXT_AGENT - Agent to hand off to (if any)

# Create logs directory if it doesn't exist
mkdir -p .claude/logs
mkdir -p .claude/metrics

# Generate timestamp
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DATE=$(date +"%Y-%m-%d")

# Log to daily metrics file
METRICS_FILE=".claude/metrics/metrics-${DATE}.csv"

# Append completion metrics
echo "${TIMESTAMP},${TASK_ID:-unknown},${AGENT_NAME},complete,\"task completed\",none,${TOKENS_USED:-0},${TASK_STATUS:-success}" >> "$METRICS_FILE"

# Update GitHub issue if tracking is enabled
if [ "$GITHUB_TRACKING" = "true" ] && command -v gh &> /dev/null; then
    # Find the issue
    ISSUE_NUMBER=$(gh issue list --label "task:${TASK_ID}" --limit 1 --json number -q ".[0].number" 2>/dev/null)
    
    if [ ! -z "$ISSUE_NUMBER" ]; then
        # Determine status emoji and label
        if [ "$TASK_STATUS" = "success" ]; then
            STATUS_EMOJI="✅"
            STATUS_LABEL="status:completed"
        else
            STATUS_EMOJI="❌"
            STATUS_LABEL="status:failed"
        fi
        
        # Add completion comment
        gh issue comment "$ISSUE_NUMBER" --body "## Task Completed ${STATUS_EMOJI}

**Agent**: ${AGENT_NAME}
**Completed**: ${TIMESTAMP}
**Status**: ${TASK_STATUS}
**Tokens Used**: ${TOKENS_USED:-0}
**Execution Time**: ${EXECUTION_TIME:-0}s

### Output Files
${OUTPUT_FILES:-None}

### Next Agent
${NEXT_AGENT:-None}

---
*Automatically tracked by Claude Code Agents*" 2>/dev/null &
        
        # Update labels
        gh issue edit "$ISSUE_NUMBER" \
            --remove-label "status:in-progress" \
            --add-label "$STATUS_LABEL" 2>/dev/null &
            
        # Close if successful
        if [ "$TASK_STATUS" = "success" ] && [ -z "$NEXT_AGENT" ]; then
            gh issue close "$ISSUE_NUMBER" 2>/dev/null &
        fi
    fi
fi

# Log to structured JSON
JSON_LOG=".claude/logs/tasks.jsonl"
echo "{\"timestamp\":\"${TIMESTAMP}\",\"task_id\":\"${TASK_ID}\",\"agent\":\"${AGENT_NAME}\",\"event\":\"complete\",\"status\":\"${TASK_STATUS}\",\"tokens_used\":${TOKENS_USED:-0},\"execution_time\":${EXECUTION_TIME:-0},\"next_agent\":\"${NEXT_AGENT}\"}" >> "$JSON_LOG"

# Track token costs
if [ ! -z "$TOKENS_USED" ] && [ "$TOKENS_USED" -gt 0 ]; then
    COST_FILE=".claude/metrics/token-costs.csv"
    
    # Create header if needed
    if [ ! -f "$COST_FILE" ]; then
        echo "date,agent,model,tokens,estimated_cost_usd" > "$COST_FILE"
    fi
    
    # Calculate cost based on model (from agent configuration)
    MODEL=$(grep -l "name: ${AGENT_NAME}" .claude/agents/*.md | xargs grep "model:" | cut -d: -f2 | tr -d ' ')
    
    case "$MODEL" in
        "haiku")
            COST=$(echo "scale=6; ${TOKENS_USED} * 0.0000008" | bc)
            ;;
        "sonnet")
            COST=$(echo "scale=6; ${TOKENS_USED} * 0.000003" | bc)
            ;;
        "opus")
            COST=$(echo "scale=6; ${TOKENS_USED} * 0.000015" | bc)
            ;;
        *)
            COST="0"
            ;;
    esac
    
    echo "${DATE},${AGENT_NAME},${MODEL},${TOKENS_USED},${COST}" >> "$COST_FILE"
fi

# Console output
if [ "$TASK_STATUS" = "success" ]; then
    echo "✅ [TRACKING] Agent '${AGENT_NAME}' completed task ${TASK_ID} (${TOKENS_USED:-0} tokens)"
else
    echo "❌ [TRACKING] Agent '${AGENT_NAME}' failed task ${TASK_ID}"
fi

# Hand off to next agent if specified
if [ ! -z "$NEXT_AGENT" ]; then
    echo "🔄 [TRACKING] Handing off to '${NEXT_AGENT}'"
fi