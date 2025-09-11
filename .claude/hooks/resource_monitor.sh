#!/bin/bash
# Resource Monitor Hook - Continuous system resource monitoring and scaling triggers

# Environment variables:
# $MONITOR_INTERVAL - Monitoring interval in seconds (default: 60)
# $SCALE_UP_THRESHOLD - CPU threshold for scaling up (default: 80)
# $SCALE_DOWN_THRESHOLD - CPU threshold for scaling down (default: 30)
# $MEMORY_ALERT_THRESHOLD - Memory usage alert threshold (default: 85)

# Set monitoring defaults
MONITOR_INTERVAL=${MONITOR_INTERVAL:-60}
SCALE_UP_THRESHOLD=${SCALE_UP_THRESHOLD:-80}
SCALE_DOWN_THRESHOLD=${SCALE_DOWN_THRESHOLD:-30}
MEMORY_ALERT_THRESHOLD=${MEMORY_ALERT_THRESHOLD:-85}

# Create resource monitoring directories
mkdir -p .claude/resources
mkdir -p .claude/logs
mkdir -p .claude/scaling

# Generate monitoring session ID
MONITOR_ID=$(uuidgen 2>/dev/null || echo "monitor-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# System Resource Collection
collect_system_resources() {
    local cpu_usage=0
    local memory_usage=0
    local disk_usage=0
    local load_average=0
    local active_agents=0
    
    # CPU usage collection
    if command -v top >/dev/null 2>&1; then
        cpu_usage=$(top -l 1 -n 0 | grep "CPU usage" | awk '{print $3}' | sed 's/%//' 2>/dev/null || echo "0")
    elif command -v vmstat >/dev/null 2>&1; then
        cpu_usage=$(vmstat 1 2 | tail -1 | awk '{print 100-$15}' 2>/dev/null || echo "0")
    fi
    
    # Memory usage collection
    if command -v free >/dev/null 2>&1; then
        memory_usage=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
    elif command -v vm_stat >/dev/null 2>&1; then
        # macOS memory calculation
        local pages_free=$(vm_stat | grep "Pages free" | awk '{print $3}' | sed 's/\.//')
        local pages_active=$(vm_stat | grep "Pages active" | awk '{print $3}' | sed 's/\.//')
        if [ "$pages_free" -gt 0 ] && [ "$pages_active" -gt 0 ]; then
            memory_usage=$(echo "scale=0; $pages_active * 100 / ($pages_free + $pages_active)" | bc 2>/dev/null || echo "0")
        fi
    fi
    
    # Disk usage collection
    disk_usage=$(df . | tail -1 | awk '{print $5}' | sed 's/%//')
    
    # Load average collection
    if command -v uptime >/dev/null 2>&1; then
        load_average=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//' 2>/dev/null || echo "0")
    fi
    
    # Active agent count
    active_agents=$(ps aux | grep -c "claude.*agent" 2>/dev/null || echo "0")
    
    echo "$cpu_usage|$memory_usage|$disk_usage|$load_average|$active_agents"
}

# Scaling Decision Logic
analyze_scaling_needs() {
    local cpu_usage="$1"
    local memory_usage="$2"
    local load_average="$3"
    local active_agents="$4"
    
    local scaling_recommendation=""
    local scaling_reason=""
    
    # Scale up triggers
    if [ "${cpu_usage%.*}" -gt "$SCALE_UP_THRESHOLD" ]; then
        scaling_recommendation="scale_up"
        scaling_reason="CPU_HIGH($cpu_usage%)"
    elif [ "${memory_usage%.*}" -gt "$MEMORY_ALERT_THRESHOLD" ]; then
        scaling_recommendation="scale_up"
        scaling_reason="MEMORY_HIGH($memory_usage%)"
    elif [ "$active_agents" -gt 8 ]; then
        scaling_recommendation="scale_up"
        scaling_reason="AGENT_SATURATION($active_agents)"
    fi
    
    # Scale down triggers
    if [ "${cpu_usage%.*}" -lt "$SCALE_DOWN_THRESHOLD" ] && [ "$active_agents" -lt 3 ]; then
        scaling_recommendation="scale_down"
        scaling_reason="RESOURCE_UNDERUTILIZATION(cpu:$cpu_usage%,agents:$active_agents)"
    fi
    
    echo "$scaling_recommendation|$scaling_reason"
}

# Resource Optimization Triggers
detect_resource_optimization_opportunities() {
    local cpu_usage="$1"
    local memory_usage="$2"
    local disk_usage="$3"
    
    local optimizations=""
    
    # Disk optimization opportunities
    if [ "${disk_usage%.*}" -gt 80 ]; then
        optimizations="$optimizations DISK_CLEANUP_NEEDED($disk_usage%)"
    fi
    
    # Memory optimization opportunities
    if [ "${memory_usage%.*}" -gt 75 ]; then
        optimizations="$optimizations MEMORY_OPTIMIZATION_NEEDED($memory_usage%)"
    fi
    
    # Check for resource leaks
    local log_file_count=$(find .claude/logs -name "*.log" -o -name "*.jsonl" | wc -l)
    if [ "$log_file_count" -gt 100 ]; then
        optimizations="$optimizations LOG_ROTATION_NEEDED($log_file_count)"
    fi
    
    # Check coordination overhead
    local coord_dirs=$(find .claude/coordination -type d | wc -l)
    if [ "$coord_dirs" -gt 50 ]; then
        optimizations="$optimizations COORDINATION_CLEANUP_NEEDED($coord_dirs)"
    fi
    
    echo "$optimizations"
}

# Performance Bottleneck Detection
detect_performance_bottlenecks() {
    local current_metrics="$1"
    local bottlenecks=""
    
    # Check for I/O bottlenecks
    local io_wait=0
    if command -v iostat >/dev/null 2>&1; then
        io_wait=$(iostat -c 1 2 2>/dev/null | tail -1 | awk '{print $4}' 2>/dev/null || echo "0")
        if [ "${io_wait%.*}" -gt 20 ]; then
            bottlenecks="$bottlenecks IO_BOTTLENECK($io_wait%)"
        fi
    fi
    
    # Check for coordination bottlenecks
    local pending_handoffs=$(find .claude/coordination -name "sequence_status" -exec grep -l "PENDING" {} \; 2>/dev/null | wc -l)
    if [ "$pending_handoffs" -gt 5 ]; then
        bottlenecks="$bottlenecks COORDINATION_BOTTLENECK($pending_handoffs)"
    fi
    
    # Check for agent queue bottlenecks
    local queued_tasks=$(ps aux | grep "claude.*agent.*waiting" | wc -l 2>/dev/null || echo "0")
    if [ "$queued_tasks" -gt 3 ]; then
        bottlenecks="$bottlenecks AGENT_QUEUE_BOTTLENECK($queued_tasks)"
    fi
    
    echo "$bottlenecks"
}

# Collect current resource metrics
RESOURCE_METRICS=$(collect_system_resources)
CPU_USAGE=$(echo "$RESOURCE_METRICS" | cut -d'|' -f1)
MEMORY_USAGE=$(echo "$RESOURCE_METRICS" | cut -d'|' -f2)
DISK_USAGE=$(echo "$RESOURCE_METRICS" | cut -d'|' -f3)
LOAD_AVERAGE=$(echo "$RESOURCE_METRICS" | cut -d'|' -f4)
ACTIVE_AGENTS=$(echo "$RESOURCE_METRICS" | cut -d'|' -f5)

# Analyze scaling needs
SCALING_ANALYSIS=$(analyze_scaling_needs "$CPU_USAGE" "$MEMORY_USAGE" "$LOAD_AVERAGE" "$ACTIVE_AGENTS")
SCALING_RECOMMENDATION=$(echo "$SCALING_ANALYSIS" | cut -d'|' -f1)
SCALING_REASON=$(echo "$SCALING_ANALYSIS" | cut -d'|' -f2)

# Detect optimization opportunities
OPTIMIZATION_OPPORTUNITIES=$(detect_resource_optimization_opportunities "$CPU_USAGE" "$MEMORY_USAGE" "$DISK_USAGE")

# Detect performance bottlenecks
PERFORMANCE_BOTTLENECKS=$(detect_performance_bottlenecks "$RESOURCE_METRICS")

# Log resource monitoring data
RESOURCE_LOG=".claude/logs/resource-monitoring.jsonl"
echo "{
  \"timestamp\": \"$TIMESTAMP\",
  \"monitor_id\": \"$MONITOR_ID\",
  \"cpu_usage\": $CPU_USAGE,
  \"memory_usage\": $MEMORY_USAGE,
  \"disk_usage\": $DISK_USAGE,
  \"load_average\": $LOAD_AVERAGE,
  \"active_agents\": $ACTIVE_AGENTS,
  \"scaling_recommendation\": \"$SCALING_RECOMMENDATION\",
  \"scaling_reason\": \"$SCALING_REASON\",
  \"optimization_opportunities\": \"$OPTIMIZATION_OPPORTUNITIES\",
  \"performance_bottlenecks\": \"$PERFORMANCE_BOTTLENECKS\"
}" >> "$RESOURCE_LOG"

# Update resource history
RESOURCE_HISTORY=".claude/resources/resource-history.csv"
if [ ! -f "$RESOURCE_HISTORY" ]; then
    echo "timestamp,cpu_usage,memory_usage,disk_usage,load_average,active_agents" > "$RESOURCE_HISTORY"
fi
echo "$TIMESTAMP,$CPU_USAGE,$MEMORY_USAGE,$DISK_USAGE,$LOAD_AVERAGE,$ACTIVE_AGENTS" >> "$RESOURCE_HISTORY"

# Resource-based actions and triggers
if [ ! -z "$SCALING_RECOMMENDATION" ]; then
    echo "📊 [SCALING] Recommendation: $SCALING_RECOMMENDATION ($SCALING_REASON)"
    
    # Trigger scaling if auto-scaling is enabled
    if [ -f ".claude/scripts/scaling_manager.sh" ] && [ "$AUTO_SCALING_ENABLED" = "true" ]; then
        echo "🔄 [AUTO-SCALING] Triggering $SCALING_RECOMMENDATION"
        .claude/scripts/scaling_manager.sh "$SCALING_RECOMMENDATION" "$SCALING_REASON" &
    fi
fi

if [ ! -z "$OPTIMIZATION_OPPORTUNITIES" ]; then
    echo "🔧 [OPTIMIZATION] Opportunities detected: $OPTIMIZATION_OPPORTUNITIES"
    
    # Trigger optimization if auto-optimization is enabled
    if [ -f ".claude/hooks/optimization_trigger.sh" ] && [ "$AUTO_OPTIMIZATION_ENABLED" = "true" ]; then
        echo "⚡ [AUTO-OPTIMIZATION] Triggering resource optimization"
        .claude/hooks/optimization_trigger.sh "resource" "$OPTIMIZATION_OPPORTUNITIES" &
    fi
fi

if [ ! -z "$PERFORMANCE_BOTTLENECKS" ]; then
    echo "🚫 [BOTTLENECKS] Detected: $PERFORMANCE_BOTTLENECKS"
    
    # Trigger bottleneck resolution
    if [ -f ".claude/hooks/bottleneck_resolver.sh" ]; then
        .claude/hooks/bottleneck_resolver.sh "$PERFORMANCE_BOTTLENECKS" &
    fi
fi

# Resource status output
echo "📊 [RESOURCES] CPU: ${CPU_USAGE}% | Memory: ${MEMORY_USAGE}% | Disk: ${DISK_USAGE}% | Agents: $ACTIVE_AGENTS"

# Set resource monitoring environment variables
export CURRENT_CPU_USAGE="$CPU_USAGE"
export CURRENT_MEMORY_USAGE="$MEMORY_USAGE"
export CURRENT_DISK_USAGE="$DISK_USAGE"
export CURRENT_LOAD_AVERAGE="$LOAD_AVERAGE"
export ACTIVE_AGENT_COUNT="$ACTIVE_AGENTS"
export SCALING_RECOMMENDATION="$SCALING_RECOMMENDATION"

# Schedule next monitoring cycle
if [ "$MONITOR_INTERVAL" -gt 0 ] && [ "$1" != "oneshot" ]; then
    (sleep "$MONITOR_INTERVAL" && .claude/hooks/resource_monitor.sh) &
fi