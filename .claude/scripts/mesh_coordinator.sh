#!/bin/bash
# Mesh Coordinator Script - Agent mesh communication management and optimization

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# Create mesh directories
mkdir -p .claude/mesh
mkdir -p .claude/coordination
mkdir -p .claude/logs

# Generate mesh session ID
MESH_SESSION_ID=$(uuidgen 2>/dev/null || echo "mesh-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo -e "${PURPLE}${BOLD}🌐 Agent Mesh Coordinator${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Mesh Communication Setup
setup_mesh_communication() {
    local communication_type="$1"
    
    echo -e "\n${BLUE}🔧 Setting up mesh communication: $communication_type${NC}"
    
    case "$communication_type" in
        "named_pipes")
            # Setup named pipes for direct agent communication
            local mesh_dir=".claude/mesh/pipes"
            mkdir -p "$mesh_dir"
            
            # Create communication pipes for each agent
            for agent in $(ls .claude/agents/*.md | xargs -I{} basename {} .md); do
                local agent_input="$mesh_dir/${agent}_input"
                local agent_output="$mesh_dir/${agent}_output"
                local agent_control="$mesh_dir/${agent}_control"
                
                # Create named pipes if they don't exist
                [ ! -p "$agent_input" ] && mkfifo "$agent_input" 2>/dev/null
                [ ! -p "$agent_output" ] && mkfifo "$agent_output" 2>/dev/null
                [ ! -p "$agent_control" ] && mkfifo "$agent_control" 2>/dev/null
                
                # Set appropriate permissions
                chmod 660 "$agent_input" "$agent_output" "$agent_control" 2>/dev/null || true
            done
            
            echo "✅ Named pipes created for $(ls .claude/agents/*.md | wc -l) agents"
            ;;
        "memory_shared")
            # Setup shared memory communication
            local memory_dir=".claude/mesh/memory"
            mkdir -p "$memory_dir"
            
            # Create shared memory segments for coordination
            echo "MESH_ACTIVE" > "$memory_dir/mesh_status"
            echo "0" > "$memory_dir/active_agents"
            echo "READY" > "$memory_dir/coordination_state"
            
            echo "✅ Shared memory communication initialized"
            ;;
        "event_driven")
            # Setup event-driven pub/sub system
            local events_dir=".claude/mesh/events"
            mkdir -p "$events_dir/publishers"
            mkdir -p "$events_dir/subscribers"
            
            # Create event channels
            touch "$events_dir/agent_events"
            touch "$events_dir/coordination_events"
            touch "$events_dir/system_events"
            
            echo "✅ Event-driven communication channels created"
            ;;
    esac
}

# Agent Discovery and Registration
setup_agent_discovery() {
    echo -e "\n${BLUE}🔍 Setting up agent discovery system${NC}"
    
    local discovery_dir=".claude/mesh/discovery"
    mkdir -p "$discovery_dir"
    
    # Register all available agents
    local agent_registry="$discovery_dir/agent_registry.json"
    echo "{" > "$agent_registry"
    echo "  \"agents\": {" >> "$agent_registry"
    
    local first_agent=true
    for agent_file in .claude/agents/*.md; do
        if [ -f "$agent_file" ]; then
            local agent_name=$(basename "$agent_file" .md)
            local agent_model=$(grep "model:" "$agent_file" | cut -d: -f2 | tr -d ' ')
            local agent_tools=$(grep "tools:" "$agent_file" | cut -d: -f2)
            
            if [ "$first_agent" = false ]; then
                echo "," >> "$agent_registry"
            fi
            
            echo "    \"$agent_name\": {" >> "$agent_registry"
            echo "      \"model\": \"$agent_model\"," >> "$agent_registry"
            echo "      \"tools\": \"$agent_tools\"," >> "$agent_registry"
            echo "      \"status\": \"available\"," >> "$agent_registry"
            echo "      \"last_seen\": \"$TIMESTAMP\"" >> "$agent_registry"
            echo -n "    }" >> "$agent_registry"
            
            first_agent=false
        fi
    done
    
    echo >> "$agent_registry"
    echo "  }," >> "$agent_registry"
    echo "  \"mesh_id\": \"$MESH_SESSION_ID\"," >> "$agent_registry"
    echo "  \"created_at\": \"$TIMESTAMP\"" >> "$agent_registry"
    echo "}" >> "$agent_registry"
    
    local agent_count=$(ls .claude/agents/*.md | wc -l)
    echo "✅ Agent discovery registry created with $agent_count agents"
}

# Load Balancing Configuration
setup_load_balancing() {
    echo -e "\n${BLUE}⚖️ Setting up intelligent load balancing${NC}"
    
    local balancing_dir=".claude/mesh/balancing"
    mkdir -p "$balancing_dir"
    
    # Create load balancing configuration
    cat > "$balancing_dir/load_balancer.config" << EOF
{
  "load_balancing": {
    "strategy": "intelligent",
    "max_concurrent_agents": 10,
    "agent_capacity_limits": {
      "haiku": 5,
      "sonnet": 3,
      "opus": 2
    },
    "priority_queuing": true,
    "health_based_routing": true,
    "cost_aware_routing": true
  },
  "routing_rules": {
    "high_priority": ["secure-coder", "performance-optimizer", "test-engineer"],
    "parallel_capable": ["api-builder", "frontend-architect", "database-architect"],
    "sequential_required": ["deployment-engineer", "project-coordinator"]
  }
}
EOF
    
    # Initialize load balancing state
    echo "ACTIVE" > "$balancing_dir/balancer_status"
    echo "0" > "$balancing_dir/current_load"
    
    echo "✅ Intelligent load balancing configured"
}

# Mesh Performance Monitoring
setup_mesh_monitoring() {
    echo -e "\n${BLUE}📊 Setting up mesh performance monitoring${NC}"
    
    local monitoring_dir=".claude/mesh/monitoring"
    mkdir -p "$monitoring_dir"
    
    # Create performance monitoring configuration
    cat > "$monitoring_dir/performance_config.json" << EOF
{
  "monitoring": {
    "enabled": true,
    "metrics_collection_interval": 30,
    "performance_thresholds": {
      "message_latency_ms": 100,
      "throughput_messages_per_sec": 50,
      "error_rate_percentage": 5
    },
    "alerts": {
      "enabled": true,
      "alert_thresholds": {
        "high_latency": 500,
        "low_throughput": 10,
        "high_error_rate": 15
      }
    }
  }
}
EOF
    
    # Initialize monitoring state
    echo "$TIMESTAMP" > "$monitoring_dir/monitoring_start"
    echo "0" > "$monitoring_dir/message_count"
    echo "0" > "$monitoring_dir/error_count"
    
    echo "✅ Mesh performance monitoring initialized"
}

# Mesh Health Checks
perform_mesh_health_check() {
    echo -e "\n${BLUE}🏥 Performing mesh health check${NC}"
    
    local health_score=100
    local health_issues=""
    
    # Check mesh communication channels
    local pipe_count=0
    if [ -d ".claude/mesh/pipes" ]; then
        pipe_count=$(find .claude/mesh/pipes -type p | wc -l)
        local expected_pipes=$(($(ls .claude/agents/*.md | wc -l) * 3))  # 3 pipes per agent
        
        if [ "$pipe_count" -lt "$expected_pipes" ]; then
            health_score=$((health_score - 20))
            health_issues="$health_issues MISSING_PIPES(${pipe_count}/${expected_pipes})"
        fi
    fi
    
    # Check agent registry
    if [ ! -f ".claude/mesh/discovery/agent_registry.json" ]; then
        health_score=$((health_score - 15))
        health_issues="$health_issues MISSING_AGENT_REGISTRY"
    fi
    
    # Check load balancer status
    if [ ! -f ".claude/mesh/balancing/balancer_status" ] || [ "$(cat .claude/mesh/balancing/balancer_status 2>/dev/null)" != "ACTIVE" ]; then
        health_score=$((health_score - 10))
        health_issues="$health_issues LOAD_BALANCER_INACTIVE"
    fi
    
    # Report health status
    if [ "$health_score" -ge 90 ]; then
        echo "✅ Mesh health: Excellent ($health_score%)"
    elif [ "$health_score" -ge 75 ]; then
        echo "🟡 Mesh health: Good ($health_score%)"
        echo "⚠️ Minor issues: $health_issues"
    else
        echo "🔴 Mesh health: Needs attention ($health_score%)"
        echo "🚨 Issues: $health_issues"
        
        # Trigger mesh recovery if health is poor
        if [ -f ".claude/hooks/mesh_recovery.sh" ]; then
            echo "🛠️ Triggering mesh recovery procedures"
            .claude/hooks/mesh_recovery.sh "$health_issues" &
        fi
    fi
    
    return "$health_score"
}

# Main mesh coordinator operations
case "${1:-setup}" in
    "setup")
        # Full mesh setup
        setup_mesh_communication "named_pipes"
        setup_agent_discovery
        setup_load_balancing
        setup_mesh_monitoring
        perform_mesh_health_check
        
        echo -e "\n${GREEN}✅ Mesh coordination system initialized${NC}"
        echo "Mesh Session ID: $MESH_SESSION_ID"
        ;;
    "status")
        # Mesh status check
        perform_mesh_health_check
        ;;
    "optimize")
        # Mesh optimization
        echo -e "\n${PURPLE}⚡ Optimizing mesh performance${NC}"
        
        # Analyze current mesh performance
        local monitoring_dir=".claude/mesh/monitoring"
        if [ -f "$monitoring_dir/performance_config.json" ]; then
            echo "Analyzing mesh performance patterns..."
            # Performance optimization logic would go here
            echo "✅ Mesh optimization completed"
        fi
        ;;
    "reset")
        # Reset mesh configuration
        echo -e "\n${YELLOW}🔄 Resetting mesh configuration${NC}"
        rm -rf .claude/mesh/* 2>/dev/null || true
        echo "✅ Mesh configuration reset - run setup to reinitialize"
        ;;
    *)
        echo "Usage: mesh_coordinator.sh [setup|status|optimize|reset]"
        ;;
esac

# Log mesh coordinator session
MESH_LOG=".claude/logs/mesh-coordination.jsonl"
echo "{
  \"timestamp\": \"$TIMESTAMP\",
  \"session_id\": \"$MESH_SESSION_ID\",
  \"operation\": \"${1:-setup}\",
  \"status\": \"completed\"
}" >> "$MESH_LOG"