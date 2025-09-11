#!/bin/bash
# Performance Profiler Hook - Real-time performance analysis and optimization

# Environment variables:
# $AGENT_NAME - Currently executing agent
# $TASK_ID - Current task identifier
# $EXECUTION_START_TIME - Task start timestamp

# Create performance directories
mkdir -p .claude/performance
mkdir -p .claude/logs

# Generate profiler session ID
PROFILER_ID=$(uuidgen 2>/dev/null || echo "prof-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Performance Metrics Collection
collect_performance_metrics() {
    local agent_name="$1"
    local task_id="$2"
    local start_time="$3"
    
    # Calculate execution time
    local current_time=$(date +%s)
    local execution_time=$((current_time - start_time))
    
    # System resource usage
    local cpu_usage=0
    local memory_usage=0
    
    # Get CPU usage
    if command -v top >/dev/null 2>&1; then
        cpu_usage=$(top -l 1 -n 0 | grep "CPU usage" | awk '{print $3}' | sed 's/%//' 2>/dev/null || echo "0")
    fi
    
    # Get memory usage
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
    
    # I/O metrics
    local disk_io_reads=0
    local disk_io_writes=0
    
    # Get disk I/O if available
    if command -v iostat >/dev/null 2>&1; then
        local io_stats=$(iostat -d 1 2 2>/dev/null | tail -1)
        disk_io_reads=$(echo "$io_stats" | awk '{print $3}' 2>/dev/null || echo "0")
        disk_io_writes=$(echo "$io_stats" | awk '{print $4}' 2>/dev/null || echo "0")
    fi
    
    echo "$execution_time|$cpu_usage|$memory_usage|$disk_io_reads|$disk_io_writes"
}

# Agent-Specific Performance Analysis
analyze_agent_performance() {
    local agent_name="$1"
    local execution_time="$2"
    local cpu_usage="$3"
    local memory_usage="$4"
    
    local performance_assessment="normal"
    local optimization_opportunities=""
    
    # Performance thresholds by agent type
    local expected_time=60  # Default 60 seconds
    local expected_cpu=50   # Default 50% CPU
    local expected_memory=30 # Default 30% memory
    
    # Agent-specific performance expectations
    case "$agent_name" in
        "haiku"*|"directory-scanner"|"documentation-specialist")
            expected_time=30
            expected_cpu=30
            expected_memory=20
            ;;
        "opus"*|"secure-coder"|"deployment-engineer"|"project-coordinator")
            expected_time=120
            expected_cpu=70
            expected_memory=50
            ;;
        *)
            # Sonnet agents - default values
            ;;
    esac
    
    # Performance assessment
    if [ "$execution_time" -gt $((expected_time * 2)) ]; then
        performance_assessment="slow"
        optimization_opportunities="$optimization_opportunities EXECUTION_TIME_HIGH"
    fi
    
    if [ "${cpu_usage%.*}" -gt $((expected_cpu + 20)) ]; then
        performance_assessment="resource-intensive"
        optimization_opportunities="$optimization_opportunities CPU_USAGE_HIGH"
    fi
    
    if [ "${memory_usage%.*}" -gt $((expected_memory + 20)) ]; then
        performance_assessment="memory-intensive"
        optimization_opportunities="$optimization_opportunities MEMORY_USAGE_HIGH"
    fi
    
    echo "$performance_assessment|$optimization_opportunities"
}

# Coordination Performance Analysis
analyze_coordination_performance() {
    local task_id="$1"
    local coordination_overhead=""
    
    # Check coordination session if exists
    if [ -d ".claude/coordination" ]; then
        local coord_sessions=$(find .claude/coordination -name "metadata.json" -mtime 0 | wc -l)
        local active_channels=$(find .claude/coordination -name "*_input" -type p | wc -l)
        
        if [ "$coord_sessions" -gt 10 ]; then
            coordination_overhead="HIGH_COORDINATION_SESSIONS($coord_sessions)"
        elif [ "$active_channels" -gt 20 ]; then
            coordination_overhead="HIGH_COMMUNICATION_CHANNELS($active_channels)"
        fi
    fi
    
    echo "$coordination_overhead"
}

# Real-time Performance Optimization
apply_performance_optimizations() {
    local performance_issues="$1"
    local optimizations_applied=""
    
    # Apply immediate optimizations based on detected issues
    if echo "$performance_issues" | grep -q "EXECUTION_TIME_HIGH"; then
        # Optimize for execution speed
        export CLAUDE_OPTIMIZATION_MODE="speed"
        optimizations_applied="$optimizations_applied SPEED_MODE"
    fi
    
    if echo "$performance_issues" | grep -q "CPU_USAGE_HIGH"; then
        # Reduce CPU intensive operations
        export CLAUDE_CPU_LIMIT="60"
        optimizations_applied="$optimizations_applied CPU_LIMIT"
    fi
    
    if echo "$performance_issues" | grep -q "MEMORY_USAGE_HIGH"; then
        # Enable memory optimization
        export CLAUDE_MEMORY_OPTIMIZATION="true"
        optimizations_applied="$optimizations_applied MEMORY_OPT"
    fi
    
    echo "$optimizations_applied"
}

# Collect current performance metrics
if [ ! -z "$AGENT_NAME" ] && [ ! -z "$EXECUTION_START_TIME" ]; then
    PERFORMANCE_METRICS=$(collect_performance_metrics "$AGENT_NAME" "$TASK_ID" "$EXECUTION_START_TIME")
    EXECUTION_TIME=$(echo "$PERFORMANCE_METRICS" | cut -d'|' -f1)
    CPU_USAGE=$(echo "$PERFORMANCE_METRICS" | cut -d'|' -f2)
    MEMORY_USAGE=$(echo "$PERFORMANCE_METRICS" | cut -d'|' -f3)
    DISK_IO_READS=$(echo "$PERFORMANCE_METRICS" | cut -d'|' -f4)
    DISK_IO_WRITES=$(echo "$PERFORMANCE_METRICS" | cut -d'|' -f5)
    
    # Analyze agent performance
    PERFORMANCE_ANALYSIS=$(analyze_agent_performance "$AGENT_NAME" "$EXECUTION_TIME" "$CPU_USAGE" "$MEMORY_USAGE")
    PERFORMANCE_ASSESSMENT=$(echo "$PERFORMANCE_ANALYSIS" | cut -d'|' -f1)
    OPTIMIZATION_OPPORTUNITIES=$(echo "$PERFORMANCE_ANALYSIS" | cut -d'|' -f2)
    
    # Analyze coordination performance
    COORDINATION_OVERHEAD=$(analyze_coordination_performance "$TASK_ID")
    
    # Apply real-time optimizations
    APPLIED_OPTIMIZATIONS=$(apply_performance_optimizations "$OPTIMIZATION_OPPORTUNITIES")
    
    # Log performance data
    PERFORMANCE_LOG=".claude/logs/performance-profiling.jsonl"
    echo "{
      \"timestamp\": \"$TIMESTAMP\",
      \"profiler_id\": \"$PROFILER_ID\",
      \"agent_name\": \"$AGENT_NAME\",
      \"task_id\": \"$TASK_ID\",
      \"execution_time\": $EXECUTION_TIME,
      \"cpu_usage\": $CPU_USAGE,
      \"memory_usage\": $MEMORY_USAGE,
      \"disk_io_reads\": $DISK_IO_READS,
      \"disk_io_writes\": $DISK_IO_WRITES,
      \"performance_assessment\": \"$PERFORMANCE_ASSESSMENT\",
      \"optimization_opportunities\": \"$OPTIMIZATION_OPPORTUNITIES\",
      \"coordination_overhead\": \"$COORDINATION_OVERHEAD\",
      \"applied_optimizations\": \"$APPLIED_OPTIMIZATIONS\"
    }" >> "$PERFORMANCE_LOG"
    
    # Console output for performance monitoring
    if [ "$PERFORMANCE_ASSESSMENT" != "normal" ]; then
        echo "⚡ [PERFORMANCE] Agent $AGENT_NAME: $PERFORMANCE_ASSESSMENT (${EXECUTION_TIME}s, ${CPU_USAGE}% CPU)"
        if [ ! -z "$OPTIMIZATION_OPPORTUNITIES" ]; then
            echo "🔧 [OPTIMIZATION] Opportunities: $OPTIMIZATION_OPPORTUNITIES"
        fi
        if [ ! -z "$APPLIED_OPTIMIZATIONS" ]; then
            echo "✅ [OPTIMIZED] Applied: $APPLIED_OPTIMIZATIONS"
        fi
    else
        echo "✅ [PERFORMANCE] Agent $AGENT_NAME: Optimal performance (${EXECUTION_TIME}s)"
    fi
    
    # Update performance history
    PERFORMANCE_HISTORY=".claude/performance/agent-performance.csv"
    if [ ! -f "$PERFORMANCE_HISTORY" ]; then
        echo "timestamp,agent,task_id,execution_time,cpu_usage,memory_usage,assessment,optimizations" > "$PERFORMANCE_HISTORY"
    fi
    echo "$TIMESTAMP,$AGENT_NAME,$TASK_ID,$EXECUTION_TIME,$CPU_USAGE,$MEMORY_USAGE,$PERFORMANCE_ASSESSMENT,$APPLIED_OPTIMIZATIONS" >> "$PERFORMANCE_HISTORY"
    
    # Set performance environment variables
    export AGENT_PERFORMANCE_SCORE="$POST_RECOVERY_SCORE"
    export PERFORMANCE_OPTIMIZATIONS_APPLIED="$APPLIED_OPTIMIZATIONS"
    export CURRENT_EXECUTION_TIME="$EXECUTION_TIME"
    
    # Trigger performance learning if available
    if [ -f ".claude/hooks/performance_learner.sh" ]; then
        .claude/hooks/performance_learner.sh "$AGENT_NAME" "$PERFORMANCE_ASSESSMENT" &
    fi
fi