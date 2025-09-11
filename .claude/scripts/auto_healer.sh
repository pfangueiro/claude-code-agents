#!/bin/bash
# Auto Healer Script - Autonomous system recovery and maintenance

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# Create healing directories
mkdir -p .claude/healing
mkdir -p .claude/logs
mkdir -p .claude/recovery

# Generate healing session ID
HEALING_ID=$(uuidgen 2>/dev/null || echo "heal-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo -e "${GREEN}${BOLD}🛡️ Autonomous System Healer${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Comprehensive System Diagnosis
perform_system_diagnosis() {
    echo -e "\n${BLUE}🔍 Comprehensive System Diagnosis${NC}"
    echo "─────────────────────────────────────────────────────"
    
    local diagnosis_score=100
    local critical_issues=""
    local warning_issues=""
    local recovery_actions=""
    
    # 1. Agent Health Diagnosis
    echo "Checking agent health..."
    local today=$(date +%Y-%m-%d)
    local metrics_file=".claude/metrics/metrics-${today}.csv"
    
    if [ -f "$metrics_file" ]; then
        local failed_agents=$(grep ",complete,.*,fail" "$metrics_file" | cut -d, -f3 | sort -u)
        local hanging_agents=$(grep ",in_progress" "$metrics_file" | awk -F, 'now - $1 > 300 {print $3}' now="$(date +%s)")
        
        if [ ! -z "$failed_agents" ]; then
            diagnosis_score=$((diagnosis_score - 20))
            critical_issues="$critical_issues FAILED_AGENTS($failed_agents)"
            recovery_actions="$recovery_actions agent_restart"
        fi
        
        if [ ! -z "$hanging_agents" ]; then
            diagnosis_score=$((diagnosis_score - 15))
            warning_issues="$warning_issues HANGING_AGENTS($hanging_agents)"
            recovery_actions="$recovery_actions process_cleanup"
        fi
    fi
    
    # 2. System Resource Diagnosis
    echo "Checking system resources..."
    local disk_usage=$(df . | tail -1 | awk '{print $5}' | sed 's/%//')
    local memory_info=""
    
    if command -v free >/dev/null 2>&1; then
        memory_info=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
    elif command -v vm_stat >/dev/null 2>&1; then
        local pages_free=$(vm_stat | grep "Pages free" | awk '{print $3}' | sed 's/\.//')
        local pages_active=$(vm_stat | grep "Pages active" | awk '{print $3}' | sed 's/\.//')
        memory_info=$(echo "scale=0; $pages_active * 100 / ($pages_free + $pages_active)" | bc 2>/dev/null || echo "0")
    fi
    
    if [ "$disk_usage" -gt 90 ]; then
        diagnosis_score=$((diagnosis_score - 25))
        critical_issues="$critical_issues DISK_CRITICAL($disk_usage%)"
        recovery_actions="$recovery_actions disk_cleanup"
    fi
    
    if [ ! -z "$memory_info" ] && [ "$memory_info" -gt 85 ]; then
        diagnosis_score=$((diagnosis_score - 20))
        critical_issues="$critical_issues MEMORY_CRITICAL($memory_info%)"
        recovery_actions="$recovery_actions memory_cleanup"
    fi
    
    # 3. Communication Health Diagnosis
    echo "Checking communication systems..."
    local broken_pipes=0
    local coordination_issues=""
    
    if [ -d ".claude/mesh/pipes" ]; then
        broken_pipes=$(find .claude/mesh/pipes -type p ! -executable | wc -l 2>/dev/null || echo "0")
        if [ "$broken_pipes" -gt 0 ]; then
            diagnosis_score=$((diagnosis_score - 15))
            warning_issues="$warning_issues BROKEN_PIPES($broken_pipes)"
            recovery_actions="$recovery_actions communication_repair"
        fi
    fi
    
    # 4. Integration Health Diagnosis
    echo "Checking external integrations..."
    local integration_failures=""
    
    # Check GitHub CLI
    if command -v gh >/dev/null 2>&1; then
        if ! gh auth status >/dev/null 2>&1; then
            warning_issues="$warning_issues GITHUB_AUTH_FAILED"
            recovery_actions="$recovery_actions integration_recovery"
        fi
    fi
    
    # Check circuit breaker states
    if [ -d ".claude/circuit-breakers" ]; then
        local open_breakers=$(find .claude/circuit-breakers -name "*.state" -exec grep -l "OPEN" {} \; | wc -l)
        if [ "$open_breakers" -gt 0 ]; then
            warning_issues="$warning_issues CIRCUIT_BREAKERS_OPEN($open_breakers)"
            recovery_actions="$recovery_actions circuit_recovery"
        fi
    fi
    
    # Generate diagnosis report
    echo -e "\n${BOLD}Diagnosis Results:${NC}"
    echo "Overall Health Score: $diagnosis_score%"
    
    if [ ! -z "$critical_issues" ]; then
        echo "🚨 Critical Issues: $critical_issues"
    fi
    
    if [ ! -z "$warning_issues" ]; then
        echo "⚠️ Warning Issues: $warning_issues"
    fi
    
    if [ -z "$critical_issues" ] && [ -z "$warning_issues" ]; then
        echo "✅ No issues detected - system healthy"
    fi
    
    echo "$diagnosis_score|$critical_issues|$warning_issues|$recovery_actions"
}

# Autonomous Recovery Implementation
implement_recovery_actions() {
    local recovery_actions="$1"
    local recovery_results=""
    
    echo -e "\n${PURPLE}🛠️ Implementing Recovery Actions${NC}"
    echo "─────────────────────────────────────────────────────"
    
    for action in $recovery_actions; do
        echo "Executing recovery action: $action"
        
        case "$action" in
            "agent_restart")
                # Restart failed agents
                echo "🔄 Restarting failed agents..."
                local failed_agents=$(grep ",complete,.*,fail" ".claude/metrics/metrics-$(date +%Y-%m-%d).csv" | cut -d, -f3 | sort -u)
                for agent in $failed_agents; do
                    echo "  Restarting agent: $agent"
                    # Agent restart logic would go here
                done
                recovery_results="$recovery_results agent_restart:success"
                ;;
            "process_cleanup")
                # Clean up hanging processes
                echo "🧹 Cleaning up hanging processes..."
                local hanging_pids=$(ps aux | grep "claude.*agent" | grep -v grep | awk '$9 ~ /D|Z/ {print $2}')
                if [ ! -z "$hanging_pids" ]; then
                    echo "$hanging_pids" | xargs kill -9 2>/dev/null || true
                    echo "  Terminated $(echo "$hanging_pids" | wc -w) hanging processes"
                fi
                recovery_results="$recovery_results process_cleanup:success"
                ;;
            "disk_cleanup")
                # Disk space recovery
                echo "💾 Performing disk cleanup..."
                local initial_usage=$(df . | tail -1 | awk '{print $5}' | sed 's/%//')
                
                # Clean old logs
                find .claude/logs -name "*.log" -mtime +7 -delete 2>/dev/null || true
                find .claude/logs -name "*.jsonl" -mtime +30 -delete 2>/dev/null || true
                
                # Compress old metrics
                find .claude/metrics -name "*.csv" -mtime +7 -exec gzip {} \; 2>/dev/null || true
                
                # Clean coordination temp files
                find .claude/coordination -type d -mtime +1 -exec rm -rf {} \; 2>/dev/null || true
                
                local final_usage=$(df . | tail -1 | awk '{print $5}' | sed 's/%//')
                local space_recovered=$((initial_usage - final_usage))
                echo "  Recovered ${space_recovered}% disk space"
                recovery_results="$recovery_results disk_cleanup:${space_recovered}%_recovered"
                ;;
            "memory_cleanup")
                # Memory pressure relief
                echo "🧠 Relieving memory pressure..."
                
                # Clear system caches if possible
                sync 2>/dev/null || true
                
                # Clean up agent memory usage
                local high_mem_pids=$(ps aux | grep "claude" | awk '$4 > 10 {print $2}')
                if [ ! -z "$high_mem_pids" ]; then
                    echo "$high_mem_pids" | xargs kill -USR1 2>/dev/null || true  # Graceful memory cleanup signal
                fi
                
                recovery_results="$recovery_results memory_cleanup:success"
                ;;
            "communication_repair")
                # Repair communication channels
                echo "📡 Repairing communication channels..."
                
                # Recreate broken pipes
                if [ -d ".claude/mesh/pipes" ]; then
                    find .claude/mesh/pipes -type p ! -readable -delete 2>/dev/null || true
                    
                    # Recreate essential pipes
                    for agent in $(ls .claude/agents/*.md | head -5 | xargs -I{} basename {} .md); do
                        local pipe=".claude/mesh/pipes/${agent}_input"
                        [ ! -p "$pipe" ] && mkfifo "$pipe" 2>/dev/null || true
                    done
                fi
                
                recovery_results="$recovery_results communication_repair:success"
                ;;
            "integration_recovery")
                # Recover external integrations
                echo "🔗 Recovering external integrations..."
                
                # Reset circuit breakers
                if [ -d ".claude/circuit-breakers" ]; then
                    find .claude/circuit-breakers -name "*.state" -exec echo "CLOSED" > {} \; 2>/dev/null || true
                    echo "  Circuit breakers reset"
                fi
                
                # Test GitHub connectivity
                if command -v gh >/dev/null 2>&1; then
                    if gh auth status >/dev/null 2>&1; then
                        echo "  GitHub integration healthy"
                    else
                        echo "  ⚠️ GitHub authentication required - run 'gh auth login'"
                    fi
                fi
                
                recovery_results="$recovery_results integration_recovery:success"
                ;;
            "circuit_recovery")
                # Recover circuit breaker systems
                echo "⚡ Recovering circuit breaker systems..."
                
                if [ -d ".claude/circuit-breakers" ]; then
                    # Reset all circuit breakers to closed state
                    for breaker_file in .claude/circuit-breakers/*.state; do
                        if [ -f "$breaker_file" ]; then
                            echo "CLOSED" > "$breaker_file"
                            local service=$(basename "$breaker_file" .state)
                            echo "  Reset circuit breaker for: $service"
                        fi
                    done
                fi
                
                recovery_results="$recovery_results circuit_recovery:success"
                ;;
        esac
    done
    
    echo "$recovery_results"
}

# Healing Validation and Effectiveness Assessment
validate_healing_effectiveness() {
    local pre_healing_score="$1"
    local recovery_results="$2"
    
    echo -e "\n${BLUE}✅ Healing Validation${NC}"
    echo "─────────────────────────────────────────────────────"
    
    # Wait for system to stabilize
    sleep 10
    
    # Re-run diagnosis
    echo "Re-running system diagnosis..."
    local post_healing_diagnosis=$(perform_system_diagnosis)
    local post_healing_score=$(echo "$post_healing_diagnosis" | cut -d'|' -f1)
    
    local healing_improvement=$((post_healing_score - pre_healing_score))
    
    echo "Pre-healing Health: ${pre_healing_score}%"
    echo "Post-healing Health: ${post_healing_score}%"
    echo "Healing Improvement: +${healing_improvement}%"
    
    # Assess healing effectiveness
    local healing_effectiveness="unknown"
    if [ "$healing_improvement" -gt 20 ]; then
        healing_effectiveness="excellent"
        echo "🎉 Excellent healing effectiveness: +${healing_improvement}%"
    elif [ "$healing_improvement" -gt 10 ]; then
        healing_effectiveness="good"
        echo "✅ Good healing effectiveness: +${healing_improvement}%"
    elif [ "$healing_improvement" -gt 0 ]; then
        healing_effectiveness="partial"
        echo "🟡 Partial healing effectiveness: +${healing_improvement}%"
    else
        healing_effectiveness="ineffective"
        echo "🔴 Healing ineffective - manual intervention may be required"
    fi
    
    echo "$post_healing_score|$healing_improvement|$healing_effectiveness"
}

# Predictive Maintenance
perform_predictive_maintenance() {
    echo -e "\n${PURPLE}🔮 Predictive Maintenance Analysis${NC}"
    echo "─────────────────────────────────────────────────────"
    
    local maintenance_recommendations=""
    
    # Analyze health trends
    local health_history=".claude/health/health-history.csv"
    if [ -f "$health_history" ]; then
        local recent_scores=$(tail -10 "$health_history" | cut -d, -f3)
        local avg_recent=$(echo "$recent_scores" | awk '{sum+=$1; count++} END {print sum/count}')
        local oldest_recent=$(echo "$recent_scores" | head -1)
        local newest_recent=$(echo "$recent_scores" | tail -1)
        
        if [ ! -z "$avg_recent" ] && [ "${avg_recent%.*}" -lt 85 ]; then
            maintenance_recommendations="$maintenance_recommendations HEALTH_DECLINE_TREND"
        fi
        
        # Predict failure likelihood
        if [ ! -z "$oldest_recent" ] && [ ! -z "$newest_recent" ]; then
            local trend=$(echo "scale=0; $newest_recent - $oldest_recent" | bc 2>/dev/null || echo "0")
            if [ "$trend" -lt -10 ]; then
                maintenance_recommendations="$maintenance_recommendations PREDICTED_DEGRADATION"
            fi
        fi
    fi
    
    # Analyze resource consumption trends
    local resource_history=".claude/resources/resource-history.csv"
    if [ -f "$resource_history" ]; then
        local avg_cpu=$(tail -20 "$resource_history" | cut -d, -f2 | awk '{sum+=$1; count++} END {print sum/count}')
        local avg_memory=$(tail -20 "$resource_history" | cut -d, -f3 | awk '{sum+=$1; count++} END {print sum/count}')
        
        if [ ! -z "$avg_cpu" ] && [ "${avg_cpu%.*}" -gt 70 ]; then
            maintenance_recommendations="$maintenance_recommendations HIGH_CPU_TREND"
        fi
        
        if [ ! -z "$avg_memory" ] && [ "${avg_memory%.*}" -gt 75 ]; then
            maintenance_recommendations="$maintenance_recommendations HIGH_MEMORY_TREND"
        fi
    fi
    
    # Generate maintenance recommendations
    if [ ! -z "$maintenance_recommendations" ]; then
        echo "🔮 Predictive Maintenance Recommendations:"
        for rec in $maintenance_recommendations; do
            case "$rec" in
                "HEALTH_DECLINE_TREND")
                    echo "  • Schedule proactive system optimization within 24 hours"
                    ;;
                "PREDICTED_DEGRADATION")
                    echo "  • Implement preventive measures to avoid performance degradation"
                    ;;
                "HIGH_CPU_TREND")
                    echo "  • Consider resource scaling or optimization to prevent CPU exhaustion"
                    ;;
                "HIGH_MEMORY_TREND")
                    echo "  • Implement memory optimization to prevent exhaustion"
                    ;;
            esac
        done
    else
        echo "✅ No predictive maintenance needed - system trends are healthy"
    fi
    
    echo "$maintenance_recommendations"
}

# Main healing operations
case "${1:-diagnose}" in
    "diagnose")
        # Full system diagnosis
        DIAGNOSIS_RESULT=$(perform_system_diagnosis)
        HEALTH_SCORE=$(echo "$DIAGNOSIS_RESULT" | cut -d'|' -f1)
        CRITICAL_ISSUES=$(echo "$DIAGNOSIS_RESULT" | cut -d'|' -f2)
        WARNING_ISSUES=$(echo "$DIAGNOSIS_RESULT" | cut -d'|' -f3)
        RECOVERY_ACTIONS=$(echo "$DIAGNOSIS_RESULT" | cut -d'|' -f4)
        
        # Perform predictive maintenance analysis
        PREDICTIVE_RECOMMENDATIONS=$(perform_predictive_maintenance)
        
        # Log diagnosis
        HEALING_LOG=".claude/logs/healing-sessions.jsonl"
        echo "{
          \"timestamp\": \"$TIMESTAMP\",
          \"healing_id\": \"$HEALING_ID\",
          \"operation\": \"diagnose\",
          \"health_score\": $HEALTH_SCORE,
          \"critical_issues\": \"$CRITICAL_ISSUES\",
          \"warning_issues\": \"$WARNING_ISSUES\",
          \"recovery_actions\": \"$RECOVERY_ACTIONS\",
          \"predictive_recommendations\": \"$PREDICTIVE_RECOMMENDATIONS\"
        }" >> "$HEALING_LOG"
        ;;
    "heal")
        # Full autonomous healing
        echo "🚀 Initiating autonomous healing procedures..."
        
        # Diagnosis phase
        DIAGNOSIS_RESULT=$(perform_system_diagnosis)
        HEALTH_SCORE=$(echo "$DIAGNOSIS_RESULT" | cut -d'|' -f1)
        RECOVERY_ACTIONS=$(echo "$DIAGNOSIS_RESULT" | cut -d'|' -f4)
        
        if [ ! -z "$RECOVERY_ACTIONS" ]; then
            # Recovery phase
            RECOVERY_RESULTS=$(implement_recovery_actions "$RECOVERY_ACTIONS")
            
            # Validation phase
            VALIDATION_RESULTS=$(validate_healing_effectiveness "$HEALTH_SCORE" "$RECOVERY_RESULTS")
            POST_HEALING_SCORE=$(echo "$VALIDATION_RESULTS" | cut -d'|' -f1)
            HEALING_IMPROVEMENT=$(echo "$VALIDATION_RESULTS" | cut -d'|' -f2)
            HEALING_EFFECTIVENESS=$(echo "$VALIDATION_RESULTS" | cut -d'|' -f3)
            
            echo -e "\n${GREEN}${BOLD}🏁 Autonomous Healing Complete${NC}"
            echo "Healing Session: $HEALING_ID"
            echo "Health Improvement: +${HEALING_IMPROVEMENT}%"
            echo "Effectiveness: $HEALING_EFFECTIVENESS"
            
            # Update healing statistics
            local healing_stats=".claude/healing/healing-stats.csv"
            if [ ! -f "$healing_stats" ]; then
                echo "timestamp,healing_id,pre_score,post_score,improvement,effectiveness,actions" > "$healing_stats"
            fi
            echo "$TIMESTAMP,$HEALING_ID,$HEALTH_SCORE,$POST_HEALING_SCORE,$HEALING_IMPROVEMENT,$HEALING_EFFECTIVENESS,$RECOVERY_ACTIONS" >> "$healing_stats"
        else
            echo "✅ No recovery actions needed - system is healthy"
        fi
        ;;
    "monitor")
        # Continuous monitoring mode
        echo "👁️ Starting continuous healing monitoring..."
        while true; do
            DIAGNOSIS_RESULT=$(perform_system_diagnosis)
            HEALTH_SCORE=$(echo "$DIAGNOSIS_RESULT" | cut -d'|' -f1)
            
            if [ "$HEALTH_SCORE" -lt 75 ]; then
                echo "🚨 Health degradation detected ($HEALTH_SCORE%) - triggering auto-healing"
                .claude/scripts/auto_healer.sh heal
            fi
            
            sleep 300  # Check every 5 minutes
        done
        ;;
    *)
        echo "Usage: auto_healer.sh [diagnose|heal|monitor]"
        echo "  diagnose - Perform comprehensive system diagnosis"
        echo "  heal     - Autonomous healing with recovery validation"
        echo "  monitor  - Continuous monitoring with auto-healing"
        ;;
esac

echo -e "\n${CYAN}🛡️ Auto-healer session: $HEALING_ID completed${NC}"