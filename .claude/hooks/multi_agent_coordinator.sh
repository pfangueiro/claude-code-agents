#!/bin/bash
# Multi-Agent Coordinator Hook - Automatic coordination of multiple agents for complex tasks

# Environment variables from previous hooks:
# $FINAL_AGENT_SELECTION - Selected agents for coordination
# $COORDINATION_TYPE - parallel or sequential
# $USER_INTENT - Original user intent
# $ACTIVATION_CONFIDENCE - Confidence in agent selection
# $PROJECT_TYPE_DETECTED - Detected project type

# Create coordination directories
mkdir -p .claude/coordination
mkdir -p .claude/logs

# Generate coordination session ID
COORDINATION_ID=$(uuidgen 2>/dev/null || echo "coord-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Multi-Agent Coordination Function
coordinate_agents() {
    local agents="$1"
    local coordination_type="$2"
    local task_intent="$3"
    
    # Create coordination plan
    local coordination_plan=""
    local execution_sequence=""
    
    case "$coordination_type" in
        "parallel")
            # Plan parallel execution
            coordination_plan="Parallel execution of: $agents"
            execution_sequence="parallel"
            
            # Create coordination channels for parallel agents
            for agent in $(echo "$agents" | tr ',' ' '); do
                mkdir -p ".claude/coordination/${COORDINATION_ID}"
                echo "PARALLEL_AGENT:$agent" >> ".claude/coordination/${COORDINATION_ID}/execution_plan"
            done
            ;;
        "sequential")
            # Plan sequential execution with intelligent ordering
            local ordered_agents=$(order_agents_by_dependencies "$agents" "$task_intent")
            coordination_plan="Sequential execution: $(echo $ordered_agents | tr ' ' ' → ')"
            execution_sequence="sequential"
            
            # Create coordination sequence
            local sequence_num=1
            for agent in $ordered_agents; do
                echo "SEQUENCE_${sequence_num}:$agent" >> ".claude/coordination/${COORDINATION_ID}/execution_plan"
                sequence_num=$((sequence_num + 1))
            done
            ;;
    esac
    
    echo "$coordination_plan|$execution_sequence"
}

# Agent Dependency Ordering Function
order_agents_by_dependencies() {
    local agents="$1"
    local intent="$2"
    local ordered=""
    
    # Define dependency patterns based on intent
    case "$intent" in
        "create")
            # Creation workflow: planning → architecture → implementation → testing → security → deployment
            for agent in project-coordinator context-analyzer database-architect api-builder frontend-architect typescript-expert test-engineer secure-coder deployment-engineer; do
                if echo "$agents" | grep -q "$agent"; then
                    ordered="$ordered $agent"
                fi
            done
            ;;
        "fix")
            # Fix workflow: analysis → implementation → testing → validation
            for agent in context-analyzer performance-optimizer refactor-specialist test-engineer secure-coder; do
                if echo "$agents" | grep -q "$agent"; then
                    ordered="$ordered $agent"
                fi
            done
            ;;
        "optimize")
            # Optimization workflow: analysis → optimization → validation → monitoring
            for agent in ai-optimizer performance-optimizer database-architect infrastructure-expert health-monitor; do
                if echo "$agents" | grep -q "$agent"; then
                    ordered="$ordered $agent"
                fi
            done
            ;;
        *)
            # Default ordering
            ordered="$agents"
            ;;
    esac
    
    # Add remaining agents not in predefined order
    for agent in $(echo "$agents" | tr ',' ' '); do
        if ! echo "$ordered" | grep -q "$agent"; then
            ordered="$ordered $agent"
        fi
    done
    
    echo "$ordered"
}

# Resource Allocation Planning
plan_resource_allocation() {
    local agents="$1"
    local coordination_type="$2"
    local workload="$3"
    
    local agent_count=$(echo "$agents" | tr ',' ' ' | wc -w)
    local resource_allocation="standard"
    
    # Adjust resource allocation based on coordination type and workload
    if [ "$coordination_type" = "parallel" ] && [ "$agent_count" -gt 3 ]; then
        resource_allocation="high-parallel"
    elif [ "$workload" = "high" ]; then
        resource_allocation="high-load"
    fi
    
    # Create resource allocation plan
    case "$resource_allocation" in
        "high-parallel")
            echo "HIGH_PARALLEL:max_concurrent=5,resource_limit=80%,timeout=300s"
            ;;
        "high-load")
            echo "HIGH_LOAD:max_concurrent=3,resource_limit=60%,timeout=600s"
            ;;
        *)
            echo "STANDARD:max_concurrent=3,resource_limit=70%,timeout=180s"
            ;;
    esac
}

# Execute coordination planning
COORDINATION_RESULT=$(coordinate_agents "$FINAL_AGENT_SELECTION" "$COORDINATION_TYPE" "$USER_INTENT")
COORDINATION_PLAN=$(echo "$COORDINATION_RESULT" | cut -d'|' -f1)
EXECUTION_SEQUENCE=$(echo "$COORDINATION_RESULT" | cut -d'|' -f2)

# Plan resource allocation
RESOURCE_PLAN=$(plan_resource_allocation "$FINAL_AGENT_SELECTION" "$COORDINATION_TYPE" "$SYSTEM_WORKLOAD")

# Create coordination session
COORDINATION_DIR=".claude/coordination/${COORDINATION_ID}"
mkdir -p "$COORDINATION_DIR"

# Write coordination metadata
cat > "$COORDINATION_DIR/metadata.json" << EOF
{
  "coordination_id": "$COORDINATION_ID",
  "timestamp": "$TIMESTAMP",
  "agents": "$FINAL_AGENT_SELECTION",
  "coordination_type": "$COORDINATION_TYPE",
  "user_intent": "$USER_INTENT",
  "project_type": "$PROJECT_TYPE_DETECTED",
  "activation_confidence": $ACTIVATION_CONFIDENCE,
  "resource_plan": "$RESOURCE_PLAN",
  "execution_plan": "$COORDINATION_PLAN"
}
EOF

# Setup coordination channels
case "$COORDINATION_TYPE" in
    "parallel")
        # Create named pipes for parallel communication
        for agent in $(echo "$FINAL_AGENT_SELECTION" | tr ',' ' '); do
            mkfifo "$COORDINATION_DIR/${agent}_input" 2>/dev/null || true
            mkfifo "$COORDINATION_DIR/${agent}_output" 2>/dev/null || true
        done
        ;;
    "sequential")
        # Create sequence coordination files
        touch "$COORDINATION_DIR/sequence_status"
        echo "READY" > "$COORDINATION_DIR/sequence_status"
        ;;
esac

# Log coordination decision
COORDINATION_LOG=".claude/logs/coordination.jsonl"
echo "{
  \"timestamp\": \"$TIMESTAMP\",
  \"coordination_id\": \"$COORDINATION_ID\",
  \"agents\": \"$FINAL_AGENT_SELECTION\",
  \"coordination_type\": \"$COORDINATION_TYPE\",
  \"execution_plan\": \"$COORDINATION_PLAN\",
  \"resource_allocation\": \"$RESOURCE_PLAN\",
  \"confidence\": $ACTIVATION_CONFIDENCE
}" >> "$COORDINATION_LOG"

# Console output for coordination
echo "🚀 [COORDINATION] Session: $COORDINATION_ID"
echo "🔄 [EXECUTION] $COORDINATION_PLAN"
echo "💾 [RESOURCES] $RESOURCE_PLAN"

# Set coordination environment variables
export COORDINATION_SESSION_ID="$COORDINATION_ID"
export COORDINATION_PLAN="$COORDINATION_PLAN"
export EXECUTION_SEQUENCE="$EXECUTION_SEQUENCE"
export RESOURCE_ALLOCATION_PLAN="$RESOURCE_PLAN"

# Start coordination monitoring
if [ -f ".claude/hooks/coordination_monitor.sh" ]; then
    .claude/hooks/coordination_monitor.sh "$COORDINATION_ID" &
fi

# Trigger learning from coordination setup
if [ -f ".claude/hooks/coordination_learner.sh" ]; then
    .claude/hooks/coordination_learner.sh "$COORDINATION_ID" &
fi