#!/bin/bash
# Setup tracking for Claude Code Agents

echo "🚀 Setting up Claude Code Agents Tracking System"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Create necessary directories
echo "Creating directories..."
mkdir -p .claude/logs
mkdir -p .claude/metrics
mkdir -p .claude/hooks
mkdir -p .claude/scripts

# Set up git ignore for logs
if [ -f .gitignore ]; then
    if ! grep -q ".claude/logs/" .gitignore; then
        echo "" >> .gitignore
        echo "# Claude Code Tracking" >> .gitignore
        echo ".claude/logs/" >> .gitignore
        echo ".claude/metrics/" >> .gitignore
        echo "*.jsonl" >> .gitignore
    fi
fi

# Initialize today's metrics
DATE=$(date +"%Y-%m-%d")
METRICS_FILE=".claude/metrics/metrics-${DATE}.csv"

if [ ! -f "$METRICS_FILE" ]; then
    echo "timestamp,task_id,agent,event,description,parent_task,tokens_used,status" > "$METRICS_FILE"
    echo "✅ Initialized metrics file"
fi

# Initialize cost tracking
COST_FILE=".claude/metrics/token-costs.csv"
if [ ! -f "$COST_FILE" ]; then
    echo "date,agent,model,tokens,estimated_cost_usd" > "$COST_FILE"
    echo "✅ Initialized cost tracking"
fi

# Check for GitHub CLI
if command -v gh &> /dev/null; then
    echo "✅ GitHub CLI detected"
    echo "   To enable GitHub tracking: .claude/scripts/tracking.sh enable github"
else
    echo "ℹ️  GitHub CLI not found (optional)"
    echo "   Install with: brew install gh"
fi

echo ""
echo "✨ Tracking system ready!"
echo ""
echo "Available commands:"
echo "  .claude/scripts/dashboard.sh     - View dashboard"
echo "  .claude/scripts/tracking.sh      - Manage tracking"
echo "  /track status                    - Check task status"
echo "  /track costs                     - View token costs"
echo ""
echo "Tracking will start automatically when agents run."