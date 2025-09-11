#!/bin/bash
# Health Checker Hook - Continuous health monitoring with predictive alerts and automatic recovery

# Environment variables:
# $HEALTH_CHECK_INTERVAL - Check interval in seconds (default: 30)
# $HEALTH_ALERT_THRESHOLD - Alert threshold percentage (default: 80)
# $AUTO_RECOVERY_ENABLED - Enable automatic recovery (default: true)

# Set defaults
HEALTH_CHECK_INTERVAL=${HEALTH_CHECK_INTERVAL:-30}
HEALTH_ALERT_THRESHOLD=${HEALTH_ALERT_THRESHOLD:-80}
AUTO_RECOVERY_ENABLED=${AUTO_RECOVERY_ENABLED:-true}

# Create health monitoring directories
mkdir -p .claude/health
mkdir -p .claude/logs
mkdir -p .claude/alerts

# Generate health check ID and timestamp
HEALTH_CHECK_ID=$(uuidgen 2>/dev/null || echo "health-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# System Health Assessment Function
check_system_health() {
    local health_score=100
    local issues=""
    local warnings=""
    
    # Check disk space
    local disk_usage=$(df . | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$disk_usage" -gt 90 ]; then
        health_score=$((health_score - 30))
        issues="$issues DISK_CRITICAL($disk_usage%)"
    elif [ "$disk_usage" -gt 80 ]; then
        health_score=$((health_score - 15))
        warnings="$warnings DISK_WARNING($disk_usage%)"
    fi
    
    # Check memory usage
    local memory_usage=0
    if command -v free >/dev/null 2>&1; then
        memory_usage=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
    elif command -v vm_stat >/dev/null 2>&1; then
        # macOS memory check
        local mem_total=$(vm_stat | grep "Pages free" | awk '{print $3}' | sed 's/\.//')
        local mem_used=$(vm_stat | grep "Pages active" | awk '{print $3}' | sed 's/\.//')
        if [ "$mem_total" -gt 0 ]; then
            memory_usage=$(echo "scale=0; $mem_used * 100 / ($mem_total + $mem_used)" | bc 2>/dev/null || echo "0")
        fi
    fi
    
    if [ "$memory_usage" -gt 90 ]; then
        health_score=$((health_score - 25))
        issues="$issues MEMORY_CRITICAL($memory_usage%)"
    elif [ "$memory_usage" -gt 80 ]; then
        health_score=$((health_score - 10))
        warnings="$warnings MEMORY_WARNING($memory_usage%)"
    fi
    
    # Check agent processes
    local hanging_processes=$(ps aux | grep "claude.*agent" | grep -v grep | awk '$9 ~ /D|Z/' | wc -l)
    if [ "$hanging_processes" -gt 0 ]; then
        health_score=$((health_score - 20))
        issues="$issues HANGING_PROCESSES($hanging_processes)"
    fi
    
    # Check log file sizes
    local large_logs=$(find .claude/logs -name "*.log" -size +100M 2>/dev/null | wc -l)
    if [ "$large_logs" -gt 0 ]; then
        health_score=$((health_score - 10))
        warnings="$warnings LARGE_LOGS($large_logs)"
    fi
    
    # Check coordination health
    local failed_handoffs=0
    if [ -f ".claude/logs/handoffs-$(date +%Y-%m-%d).jsonl" ]; then
        failed_handoffs=$(grep -c '"validation":"false"' ".claude/logs/handoffs-$(date +%Y-%m-%d).jsonl" 2>/dev/null || echo "0")
    fi
    
    if [ "$failed_handoffs" -gt 5 ]; then
        health_score=$((health_score - 15))
        issues="$issues HANDOFF_FAILURES($failed_handoffs)"
    fi
    
    echo "$health_score|$issues|$warnings"
}

# Agent Health Assessment
check_agent_health() {
    local agent_health=""
    local agent_issues=""
    
    # Check each agent's recent performance
    local today=$(date +%Y-%m-%d)
    local metrics_file=".claude/metrics/metrics-${today}.csv"
    
    if [ -f "$metrics_file" ]; then
        # Check for failed agents
        local failed_agents=$(grep ",complete,.*,fail" "$metrics_file" | cut -d, -f3 | sort -u)
        if [ ! -z "$failed_agents" ]; then
            agent_issues="FAILED_AGENTS: $failed_agents"
        fi
        
        # Check for slow agents (>10 seconds execution time)
        local slow_agents=$(awk -F, '$8 > 10 {print $3}' "$metrics_file" 2>/dev/null | sort -u | head -3)
        if [ ! -z "$slow_agents" ]; then
            agent_issues="$agent_issues SLOW_AGENTS: $slow_agents"
        fi
    fi
    
    echo "$agent_issues"
}

# Integration Health Check
check_integration_health() {
    local integration_health=""
    local integration_issues=""
    
    # Check GitHub CLI availability
    if ! command -v gh >/dev/null 2>&1; then
        integration_issues="$integration_issues GITHUB_CLI_MISSING"
    elif ! gh auth status >/dev/null 2>&1; then
        integration_issues="$integration_issues GITHUB_AUTH_FAILED"
    fi
    
    # Check MCP server connectivity (basic check)
    local mcp_issues=""
    # This would be enhanced with actual MCP server health checks
    
    echo "$integration_issues"
}

# Predictive Health Analysis
predictive_health_analysis() {
    local current_health="$1"
    local trend_analysis=""
    
    # Analyze health trends from recent data
    local health_history=".claude/health/health-history.csv"
    if [ -f "$health_history" ]; then
        local recent_scores=$(tail -10 "$health_history" | cut -d, -f3)
        local avg_score=$(echo "$recent_scores" | awk '{sum+=$1; count++} END {print sum/count}' 2>/dev/null || echo "$current_health")
        
        if [ "$current_health" -lt "$avg_score" ]; then
            local degradation=$(echo "$avg_score - $current_health" | bc 2>/dev/null || echo "0")
            if [ "${degradation%.*}" -gt 10 ]; then
                trend_analysis="DEGRADATION_TREND(${degradation})"
            fi
        fi
    fi
    
    echo "$trend_analysis"
}

# Perform comprehensive health check
HEALTH_RESULT=$(check_system_health)
HEALTH_SCORE=$(echo "$HEALTH_RESULT" | cut -d'|' -f1)
HEALTH_ISSUES=$(echo "$HEALTH_RESULT" | cut -d'|' -f2)
HEALTH_WARNINGS=$(echo "$HEALTH_RESULT" | cut -d'|' -f3)

# Check agent and integration health
AGENT_ISSUES=$(check_agent_health)
INTEGRATION_ISSUES=$(check_integration_health)

# Predictive analysis
HEALTH_TRENDS=$(predictive_health_analysis "$HEALTH_SCORE")

# Log health status
HEALTH_LOG=".claude/logs/health-monitoring.jsonl"
echo "{
  \"timestamp\": \"$TIMESTAMP\",
  \"health_check_id\": \"$HEALTH_CHECK_ID\",
  \"health_score\": $HEALTH_SCORE,
  \"issues\": \"$HEALTH_ISSUES\",
  \"warnings\": \"$HEALTH_WARNINGS\",
  \"agent_issues\": \"$AGENT_ISSUES\",
  \"integration_issues\": \"$INTEGRATION_ISSUES\",
  \"trends\": \"$HEALTH_TRENDS\"
}" >> "$HEALTH_LOG"

# Update health history
HEALTH_HISTORY=".claude/health/health-history.csv"
if [ ! -f "$HEALTH_HISTORY" ]; then
    echo "timestamp,health_check_id,health_score,issues,warnings" > "$HEALTH_HISTORY"
fi
echo "$TIMESTAMP,$HEALTH_CHECK_ID,$HEALTH_SCORE,\"$HEALTH_ISSUES\",\"$HEALTH_WARNINGS\"" >> "$HEALTH_HISTORY"

# Health-based alerts and recovery
if [ "$HEALTH_SCORE" -lt "$HEALTH_ALERT_THRESHOLD" ]; then
    # Generate health alert
    echo "⚠️ [HEALTH ALERT] System health: ${HEALTH_SCORE}% (threshold: ${HEALTH_ALERT_THRESHOLD}%)"
    echo "🔍 [ISSUES] $HEALTH_ISSUES"
    echo "⚠️ [WARNINGS] $HEALTH_WARNINGS"
    
    # Trigger automatic recovery if enabled
    if [ "$AUTO_RECOVERY_ENABLED" = "true" ] && [ -f ".claude/hooks/auto_recovery.sh" ]; then
        echo "🛠️ [AUTO-RECOVERY] Triggering automatic recovery procedures"
        .claude/hooks/auto_recovery.sh "$HEALTH_CHECK_ID" "$HEALTH_SCORE" "$HEALTH_ISSUES" &
    fi
    
    # Create alert file
    cat > ".claude/alerts/health-alert-${HEALTH_CHECK_ID}.json" << EOF
{
  "alert_type": "health_critical",
  "timestamp": "$TIMESTAMP",
  "health_score": $HEALTH_SCORE,
  "threshold": $HEALTH_ALERT_THRESHOLD,
  "issues": "$HEALTH_ISSUES",
  "warnings": "$HEALTH_WARNINGS",
  "auto_recovery_triggered": $AUTO_RECOVERY_ENABLED
}
EOF
else
    echo "✅ [HEALTH] System health: ${HEALTH_SCORE}% - All systems operational"
fi

# Set health status environment variables
export SYSTEM_HEALTH_SCORE="$HEALTH_SCORE"
export SYSTEM_HEALTH_STATUS="healthy"
export HEALTH_ISSUES_DETECTED="$HEALTH_ISSUES"
export HEALTH_WARNINGS_DETECTED="$HEALTH_WARNINGS"

# Schedule next health check
if [ "$HEALTH_CHECK_INTERVAL" -gt 0 ]; then
    (sleep "$HEALTH_CHECK_INTERVAL" && .claude/hooks/health_checker.sh) &
fi