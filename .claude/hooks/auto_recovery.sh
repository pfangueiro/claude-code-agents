#!/bin/bash
# Auto Recovery Hook - Autonomous recovery procedures for system issues

# Input parameters from health_checker.sh:
# $1 - Health check ID that triggered recovery
# $2 - Current health score
# $3 - Detected issues string

HEALTH_CHECK_ID="$1"
HEALTH_SCORE="$2"
DETECTED_ISSUES="$3"

# Create recovery directories
mkdir -p .claude/recovery
mkdir -p .claude/logs

# Generate recovery session ID
RECOVERY_ID=$(uuidgen 2>/dev/null || echo "recovery-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "🛠️ [AUTO-RECOVERY] Starting autonomous recovery procedures"
echo "🔍 [TRIGGER] Health check: $HEALTH_CHECK_ID | Score: $HEALTH_SCORE% | Issues: $DETECTED_ISSUES"

# Recovery procedure functions
recover_disk_space() {
    echo "💾 [RECOVERY] Cleaning up disk space..."
    
    # Clean up old log files
    find .claude/logs -name "*.log" -mtime +7 -delete 2>/dev/null || true
    find .claude/logs -name "*.jsonl" -mtime +30 -delete 2>/dev/null || true
    
    # Compress old metrics
    find .claude/metrics -name "*.csv" -mtime +7 -exec gzip {} \; 2>/dev/null || true
    
    # Clean up temporary coordination files
    find .claude/coordination -type d -mtime +1 -exec rm -rf {} \; 2>/dev/null || true
    
    echo "✅ [RECOVERY] Disk cleanup completed"
}

recover_memory_pressure() {
    echo "🧠 [RECOVERY] Addressing memory pressure..."
    
    # Kill hanging agent processes
    local hanging_pids=$(ps aux | grep "claude.*agent" | grep -v grep | awk '$9 ~ /D|Z/ {print $2}')
    if [ ! -z "$hanging_pids" ]; then
        echo "$hanging_pids" | xargs kill -9 2>/dev/null || true
        echo "✅ [RECOVERY] Terminated hanging agent processes"
    fi
    
    # Clean up orphaned processes
    local orphaned_pids=$(ps aux | grep "claude" | grep -v grep | awk '$3 > 50 {print $2}')
    if [ ! -z "$orphaned_pids" ]; then
        echo "$orphaned_pids" | xargs kill -TERM 2>/dev/null || true
        sleep 5
        echo "$orphaned_pids" | xargs kill -9 2>/dev/null || true
        echo "✅ [RECOVERY] Cleaned up high-CPU processes"
    fi
    
    echo "✅ [RECOVERY] Memory pressure relief completed"
}

recover_hanging_processes() {
    echo "🔄 [RECOVERY] Recovering hanging processes..."
    
    # Identify and restart hanging agent processes
    local hanging_agents=$(ps aux | grep "claude.*agent" | grep -v grep | awk '$9 ~ /D|Z/ {print $11}' | sort -u)
    
    for agent in $hanging_agents; do
        if [ ! -z "$agent" ]; then
            echo "🔄 [RECOVERY] Restarting hanging agent: $agent"
            # Kill hanging process
            pkill -f "$agent" 2>/dev/null || true
            sleep 2
            # Note: Agent restart would be handled by the agent management system
        fi
    done
    
    echo "✅ [RECOVERY] Process recovery completed"
}

recover_coordination_failures() {
    echo "🤝 [RECOVERY] Recovering coordination failures..."
    
    # Clean up broken coordination sessions
    find .claude/coordination -name "*.lock" -mtime +1 -delete 2>/dev/null || true
    find .claude/coordination -name "*.tmp" -delete 2>/dev/null || true
    
    # Reset coordination channels
    find .claude/coordination -name "*_input" -type p -delete 2>/dev/null || true
    find .claude/coordination -name "*_output" -type p -delete 2>/dev/null || true
    
    # Clear coordination status files
    find .claude/coordination -name "sequence_status" -exec echo "READY" > {} \; 2>/dev/null || true
    
    echo "✅ [RECOVERY] Coordination recovery completed"
}

recover_integration_failures() {
    echo "🔗 [RECOVERY] Recovering integration failures..."
    
    # Test GitHub CLI connectivity
    if command -v gh >/dev/null 2>&1; then
        if ! gh auth status >/dev/null 2>&1; then
            echo "⚠️ [RECOVERY] GitHub authentication failed - manual intervention required"
        fi
    fi
    
    # Reset circuit breakers (if implemented)
    if [ -d ".claude/circuit-breakers" ]; then
        find .claude/circuit-breakers -name "*.state" -exec echo "CLOSED" > {} \; 2>/dev/null || true
        echo "✅ [RECOVERY] Circuit breakers reset"
    fi
    
    echo "✅ [RECOVERY] Integration recovery completed"
}

# Parse issues and apply appropriate recovery procedures
recovery_procedures_applied=""

if echo "$DETECTED_ISSUES" | grep -q "DISK_CRITICAL"; then
    recover_disk_space
    recovery_procedures_applied="$recovery_procedures_applied disk_cleanup"
fi

if echo "$DETECTED_ISSUES" | grep -q "MEMORY_CRITICAL"; then
    recover_memory_pressure
    recovery_procedures_applied="$recovery_procedures_applied memory_recovery"
fi

if echo "$DETECTED_ISSUES" | grep -q "HANGING_PROCESSES"; then
    recover_hanging_processes
    recovery_procedures_applied="$recovery_procedures_applied process_recovery"
fi

if echo "$DETECTED_ISSUES" | grep -q "HANDOFF_FAILURES"; then
    recover_coordination_failures
    recovery_procedures_applied="$recovery_procedures_applied coordination_recovery"
fi

# Always check integrations if health is low
if [ "$HEALTH_SCORE" -lt 70 ]; then
    recover_integration_failures
    recovery_procedures_applied="$recovery_procedures_applied integration_recovery"
fi

# Post-recovery health check
echo "🔍 [RECOVERY] Performing post-recovery health validation..."
sleep 5

POST_RECOVERY_RESULT=$(check_system_health)
POST_RECOVERY_SCORE=$(echo "$POST_RECOVERY_RESULT" | cut -d'|' -f1)
POST_RECOVERY_ISSUES=$(echo "$POST_RECOVERY_RESULT" | cut -d'|' -f2)

# Calculate recovery effectiveness
RECOVERY_IMPROVEMENT=$((POST_RECOVERY_SCORE - HEALTH_SCORE))

# Log recovery session
RECOVERY_LOG=".claude/logs/recovery-sessions.jsonl"
echo "{
  \"timestamp\": \"$TIMESTAMP\",
  \"recovery_id\": \"$RECOVERY_ID\",
  \"trigger_health_check\": \"$HEALTH_CHECK_ID\",
  \"pre_recovery_score\": $HEALTH_SCORE,
  \"post_recovery_score\": $POST_RECOVERY_SCORE,
  \"recovery_improvement\": $RECOVERY_IMPROVEMENT,
  \"issues_detected\": \"$DETECTED_ISSUES\",
  \"procedures_applied\": \"$recovery_procedures_applied\",
  \"remaining_issues\": \"$POST_RECOVERY_ISSUES\"
}" >> "$RECOVERY_LOG"

# Recovery results output
if [ "$RECOVERY_IMPROVEMENT" -gt 0 ]; then
    echo "✅ [RECOVERY SUCCESS] Health improved: ${HEALTH_SCORE}% → ${POST_RECOVERY_SCORE}% (+${RECOVERY_IMPROVEMENT}%)"
    echo "🛠️ [PROCEDURES] Applied: $recovery_procedures_applied"
    
    # Create recovery success record
    echo "$TIMESTAMP,$RECOVERY_ID,success,$RECOVERY_IMPROVEMENT,$recovery_procedures_applied" >> ".claude/recovery/recovery-history.csv"
else
    echo "⚠️ [RECOVERY PARTIAL] Health: ${HEALTH_SCORE}% → ${POST_RECOVERY_SCORE}%"
    echo "🔍 [REMAINING ISSUES] $POST_RECOVERY_ISSUES"
    
    # Create recovery partial record
    echo "$TIMESTAMP,$RECOVERY_ID,partial,0,$recovery_procedures_applied" >> ".claude/recovery/recovery-history.csv"
    
    # Escalate if recovery failed
    if [ "$POST_RECOVERY_SCORE" -lt 50 ]; then
        echo "🚨 [RECOVERY ESCALATION] Critical health status requires manual intervention"
        
        # Create escalation alert
        cat > ".claude/alerts/recovery-escalation-${RECOVERY_ID}.json" << EOF
{
  "alert_type": "recovery_escalation",
  "timestamp": "$TIMESTAMP",
  "recovery_id": "$RECOVERY_ID",
  "pre_recovery_score": $HEALTH_SCORE,
  "post_recovery_score": $POST_RECOVERY_SCORE,
  "remaining_issues": "$POST_RECOVERY_ISSUES",
  "requires_manual_intervention": true
}
EOF
    fi
fi

# Update system health status
export POST_RECOVERY_HEALTH_SCORE="$POST_RECOVERY_SCORE"
export RECOVERY_EFFECTIVENESS="$RECOVERY_IMPROVEMENT"
export RECOVERY_PROCEDURES_APPLIED="$recovery_procedures_applied"

echo "🏁 [RECOVERY] Recovery session $RECOVERY_ID completed"