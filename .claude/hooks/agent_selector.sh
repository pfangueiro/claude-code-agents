#!/bin/bash
# Agent Selector Hook - Intelligent agent selection with confidence scoring and conflict resolution

# Environment variables from pre_input_analysis.sh:
# $RECOMMENDED_AGENTS - Comma-separated list of recommended agents
# $USER_INTENT - Detected user intent (create, fix, optimize, etc.)
# $DETECTED_TECH - Detected technology keywords
# $PROJECT_CONTEXT_ANALYSIS - Project context information

# Additional Claude Code variables:
# $AVAILABLE_AGENTS - List of available agents
# $CURRENT_WORKLOAD - Current agent workload information

# Create analytics directory
mkdir -p .claude/analytics
mkdir -p .claude/logs

# Generate selection ID and timestamp
SELECTION_ID=$(uuidgen 2>/dev/null || echo "select-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Agent Scoring Function
score_agent() {
    local agent_name="$1"
    local user_intent="$2"
    local tech_keywords="$3"
    local context="$4"
    local score=0
    
    # Read agent configuration
    local agent_file=".claude/agents/${agent_name}.md"
    if [ ! -f "$agent_file" ]; then
        echo "0"
        return
    fi
    
    # Extract agent description and keywords
    local agent_desc=$(grep "description:" "$agent_file" | cut -d'"' -f2)
    
    # Score based on intent matching
    case "$user_intent" in
        "create")
            echo "$agent_desc" | grep -qi "create\|build\|implement\|develop" && score=$((score + 30))
            ;;
        "fix")
            echo "$agent_desc" | grep -qi "fix\|debug\|solve\|repair" && score=$((score + 30))
            ;;
        "optimize")
            echo "$agent_desc" | grep -qi "optimize\|improve\|enhance\|performance" && score=$((score + 30))
            ;;
        "analyze")
            echo "$agent_desc" | grep -qi "analyze\|review\|understand" && score=$((score + 30))
            ;;
    esac
    
    # Score based on technology keywords
    for tech in $tech_keywords; do
        if echo "$agent_desc" | grep -qi "$tech"; then
            score=$((score + 20))
        fi
    done
    
    # Score based on project context
    for ctx in $context; do
        if echo "$agent_desc" | grep -qi "$ctx"; then
            score=$((score + 15))
        fi
    done
    
    # Bonus for MUST BE USED agents
    if echo "$agent_desc" | grep -qi "MUST BE USED"; then
        score=$((score + 25))
    fi
    
    # Bonus for PROACTIVELY agents
    if echo "$agent_desc" | grep -qi "PROACTIVELY"; then
        score=$((score + 10))
    fi
    
    echo "$score"
}

# Score all available agents
AGENT_SCORES=""
for agent in $(ls .claude/agents/*.md 2>/dev/null | xargs -I{} basename {} .md); do
    score=$(score_agent "$agent" "$USER_INTENT" "$DETECTED_TECH" "$PROJECT_CONTEXT_ANALYSIS")
    if [ "$score" -gt 0 ]; then
        AGENT_SCORES="$AGENT_SCORES $agent:$score"
    fi
done

# Sort agents by score (highest first)
SORTED_AGENTS=$(echo "$AGENT_SCORES" | tr ' ' '\n' | sort -t: -k2 -nr | head -10)

# Select top agents based on score thresholds
PRIMARY_AGENTS=""
SECONDARY_AGENTS=""
QUALITY_GATES=""

while IFS=: read -r agent score; do
    if [ "$score" -ge 50 ]; then
        PRIMARY_AGENTS="$PRIMARY_AGENTS $agent"
    elif [ "$score" -ge 30 ]; then
        SECONDARY_AGENTS="$SECONDARY_AGENTS $agent"
    fi
    
    # Add quality gates for certain agents
    case "$agent" in
        "secure-coder"|"test-engineer"|"performance-optimizer")
            if [ "$score" -ge 20 ]; then
                QUALITY_GATES="$QUALITY_GATES $agent"
            fi
            ;;
    esac
done <<< "$SORTED_AGENTS"

# Intelligent conflict resolution
if [ $(echo "$PRIMARY_AGENTS" | wc -w) -gt 3 ]; then
    # Too many primary agents, select top 3
    PRIMARY_AGENTS=$(echo "$PRIMARY_AGENTS" | cut -d' ' -f1-3)
fi

# Multi-agent coordination decision
COORDINATION_TYPE="sequential"
if [ $(echo "$PRIMARY_AGENTS" | wc -w) -gt 1 ]; then
    # Check if agents can work in parallel
    case "$USER_INTENT" in
        "create")
            if echo "$PRIMARY_AGENTS" | grep -q "frontend-architect" && echo "$PRIMARY_AGENTS" | grep -q "api-builder"; then
                COORDINATION_TYPE="parallel"
            fi
            ;;
        "optimize")
            COORDINATION_TYPE="parallel"
            ;;
    esac
fi

# Log selection decision
SELECTION_LOG=".claude/logs/agent-selection.jsonl"
echo "{
  \"timestamp\": \"$TIMESTAMP\",
  \"selection_id\": \"$SELECTION_ID\",
  \"user_intent\": \"$USER_INTENT\",
  \"tech_keywords\": \"$DETECTED_TECH\",
  \"primary_agents\": \"$PRIMARY_AGENTS\",
  \"secondary_agents\": \"$SECONDARY_AGENTS\",
  \"quality_gates\": \"$QUALITY_GATES\",
  \"coordination_type\": \"$COORDINATION_TYPE\",
  \"all_scores\": \"$AGENT_SCORES\"
}" >> "$SELECTION_LOG"

# Generate activation plan
ACTIVATION_PLAN=""
if [ "$COORDINATION_TYPE" = "parallel" ]; then
    ACTIVATION_PLAN="Parallel execution: $PRIMARY_AGENTS"
    if [ ! -z "$QUALITY_GATES" ]; then
        ACTIVATION_PLAN="$ACTIVATION_PLAN | Quality gates: $QUALITY_GATES"
    fi
else
    ACTIVATION_PLAN="Sequential execution: $(echo $PRIMARY_AGENTS | tr ' ' ' → ')"
    if [ ! -z "$QUALITY_GATES" ]; then
        ACTIVATION_PLAN="$ACTIVATION_PLAN → Quality gates: $QUALITY_GATES"
    fi
fi

# Console output for visibility
echo "🎯 [SELECTION] Primary agents: $PRIMARY_AGENTS"
echo "🔄 [COORDINATION] $ACTIVATION_PLAN"

# Set environment variables for agent coordination
export SELECTED_PRIMARY_AGENTS="$PRIMARY_AGENTS"
export SELECTED_SECONDARY_AGENTS="$SECONDARY_AGENTS"
export SELECTED_QUALITY_GATES="$QUALITY_GATES"
export COORDINATION_TYPE="$COORDINATION_TYPE"
export ACTIVATION_PLAN="$ACTIVATION_PLAN"

# Trigger learning from selection
if [ -f ".claude/hooks/selection_learner.sh" ]; then
    .claude/hooks/selection_learner.sh &
fi