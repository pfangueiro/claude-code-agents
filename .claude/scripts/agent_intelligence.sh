#!/bin/bash
# Agent Intelligence Script - Central AI brain for agent coordination and optimization

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# Create intelligence directories
mkdir -p .claude/intelligence
mkdir -p .claude/analytics
mkdir -p .claude/models

# Generate intelligence session ID
INTELLIGENCE_ID=$(uuidgen 2>/dev/null || echo "intel-$(date +%s)-$$")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo -e "${CYAN}${BOLD}🧠 Claude Code Agent Intelligence System${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Intelligence Analysis Function
analyze_system_intelligence() {
    local analysis_type="$1"
    local intelligence_report=""
    
    case "$analysis_type" in
        "activation")
            # Analyze agent activation patterns and effectiveness
            echo -e "\n${BLUE}📊 Activation Intelligence Analysis${NC}"
            echo "─────────────────────────────────────────────────────"
            
            # Get today's activation data
            local today=$(date +%Y-%m-%d)
            local metrics_file=".claude/metrics/metrics-${today}.csv"
            
            if [ -f "$metrics_file" ]; then
                # Calculate activation success rate
                local total_activations=$(grep -c ",start," "$metrics_file" 2>/dev/null || echo "1")
                local successful_completions=$(grep -c ",complete,.*,success" "$metrics_file" 2>/dev/null || echo "0")
                local success_rate=$((successful_completions * 100 / total_activations))
                
                echo "Total Activations: $total_activations"
                echo "Successful Completions: $successful_completions"
                echo "Success Rate: ${success_rate}%"
                
                # Analyze most effective agents
                echo -e "\n${BOLD}Most Effective Agents:${NC}"
                awk -F, '$4=="start" {agents[$3]++} $4=="complete" && $8=="success" {success[$3]++} END {
                    for(a in agents) {
                        rate = (success[a] ? success[a] : 0) * 100 / agents[a]
                        printf "%-20s %3d activations %3d%% success\n", a, agents[a], rate
                    }
                }' "$metrics_file" | sort -k4 -nr | head -10
            fi
            ;;
        "coordination")
            # Analyze coordination patterns and efficiency
            echo -e "\n${BLUE}🤝 Coordination Intelligence Analysis${NC}"
            echo "─────────────────────────────────────────────────────"
            
            local handoff_file=".claude/logs/handoffs-${today}.jsonl"
            if [ -f "$handoff_file" ]; then
                local total_handoffs=$(wc -l < "$handoff_file" 2>/dev/null || echo "1")
                local successful_handoffs=$(grep -c '"validation":"true"' "$handoff_file" 2>/dev/null || echo "0")
                local handoff_success_rate=$((successful_handoffs * 100 / total_handoffs))
                
                echo "Total Handoffs: $total_handoffs"
                echo "Successful Handoffs: $successful_handoffs"
                echo "Handoff Success Rate: ${handoff_success_rate}%"
                
                # Analyze most effective coordination patterns
                echo -e "\n${BOLD}Effective Coordination Patterns:${NC}"
                grep '"from_agent"' "$handoff_file" | sed 's/.*"from_agent": *"\([^"]*\)".*"to_agent": *"\([^"]*\)".*/\1 → \2/' | sort | uniq -c | sort -nr | head -5
            fi
            ;;
        "performance")
            # Analyze performance intelligence and optimization opportunities
            echo -e "\n${BLUE}⚡ Performance Intelligence Analysis${NC}"
            echo "─────────────────────────────────────────────────────"
            
            local performance_file=".claude/performance/agent-performance.csv"
            if [ -f "$performance_file" ]; then
                # Calculate average performance metrics
                local avg_execution_time=$(tail -50 "$performance_file" | cut -d, -f4 | awk '{sum+=$1; count++} END {printf "%.1f", sum/count}')
                local avg_cpu_usage=$(tail -50 "$performance_file" | cut -d, -f5 | awk '{sum+=$1; count++} END {printf "%.1f", sum/count}')
                local avg_memory_usage=$(tail -50 "$performance_file" | cut -d, -f6 | awk '{sum+=$1; count++} END {printf "%.1f", sum/count}')
                
                echo "Average Execution Time: ${avg_execution_time}s"
                echo "Average CPU Usage: ${avg_cpu_usage}%"
                echo "Average Memory Usage: ${avg_memory_usage}%"
                
                # Identify performance trends
                echo -e "\n${BOLD}Performance Trends:${NC}"
                local recent_avg=$(tail -10 "$performance_file" | cut -d, -f4 | awk '{sum+=$1; count++} END {printf "%.1f", sum/count}')
                local older_avg=$(head -10 "$performance_file" | cut -d, -f4 | awk '{sum+=$1; count++} END {printf "%.1f", sum/count}')
                
                if [ ! -z "$recent_avg" ] && [ ! -z "$older_avg" ]; then
                    local trend=$(echo "scale=1; ($recent_avg - $older_avg) * 100 / $older_avg" | bc 2>/dev/null || echo "0")
                    if [ "${trend%.*}" -gt 10 ]; then
                        echo "⚠️ Performance degrading: +${trend}% execution time"
                    elif [ "${trend%.*}" -lt -10 ]; then
                        echo "✅ Performance improving: ${trend}% execution time"
                    else
                        echo "📊 Performance stable: ${trend}% change"
                    fi
                fi
            fi
            ;;
        "cost")
            # Analyze cost intelligence and optimization
            echo -e "\n${BLUE}💰 Cost Intelligence Analysis${NC}"
            echo "─────────────────────────────────────────────────────"
            
            local cost_file=".claude/metrics/token-costs.csv"
            if [ -f "$cost_file" ]; then
                # Calculate cost metrics
                local total_tokens=$(cut -d, -f4 "$cost_file" | awk '{sum+=$1} END {print sum}')
                local total_cost=$(cut -d, -f5 "$cost_file" | awk '{sum+=$1} END {printf "%.4f", sum}')
                local avg_cost_per_1k=$(echo "scale=4; $total_cost * 1000 / $total_tokens" | bc 2>/dev/null || echo "0")
                
                echo "Total Tokens Used: $total_tokens"
                echo "Total Cost: \$$total_cost"
                echo "Average Cost per 1K tokens: \$$avg_cost_per_1k"
                
                # Model usage distribution
                echo -e "\n${BOLD}Model Usage Distribution:${NC}"
                for model in haiku sonnet opus; do
                    local model_tokens=$(grep ",${model}," "$cost_file" | cut -d, -f4 | awk '{sum+=$1} END {print sum+0}')
                    local model_cost=$(grep ",${model}," "$cost_file" | cut -d, -f5 | awk '{sum+=$1} END {printf "%.4f", sum}')
                    local model_percentage=$((model_tokens * 100 / total_tokens))
                    
                    if [ "$model_tokens" -gt 0 ]; then
                        printf "%-8s %8s tokens (%2d%%) \$%.4f\n" "$model" "$model_tokens" "$model_percentage" "$model_cost"
                    fi
                done
                
                # Cost optimization opportunities
                echo -e "\n${BOLD}Cost Optimization Opportunities:${NC}"
                local opus_usage=$(grep ",opus," "$cost_file" | cut -d, -f4 | awk '{sum+=$1} END {print sum+0}')
                local total_opus_percentage=$((opus_usage * 100 / total_tokens))
                
                if [ "$total_opus_percentage" -gt 30 ]; then
                    echo "⚠️ High Opus usage ($total_opus_percentage%) - consider task optimization"
                fi
                
                local haiku_opportunities=$(grep ",sonnet," "$cost_file" | wc -l)
                if [ "$haiku_opportunities" -gt 10 ]; then
                    echo "💡 Potential Haiku downgrade opportunities: $haiku_opportunities tasks"
                fi
            fi
            ;;
        "learning")
            # Analyze learning intelligence and pattern recognition
            echo -e "\n${BLUE}🎓 Learning Intelligence Analysis${NC}"
            echo "─────────────────────────────────────────────────────"
            
            # Analyze learning data sources
            local selection_log=".claude/logs/agent-selection.jsonl"
            local context_log=".claude/logs/context-analysis.jsonl"
            
            if [ -f "$selection_log" ]; then
                local total_selections=$(wc -l < "$selection_log" 2>/dev/null || echo "0")
                local high_confidence=$(grep '"activation_confidence":[8-9][0-9]' "$selection_log" | wc -l 2>/dev/null || echo "0")
                local confidence_rate=$((high_confidence * 100 / total_selections))
                
                echo "Total Agent Selections: $total_selections"
                echo "High Confidence Selections: $high_confidence"
                echo "Selection Confidence Rate: ${confidence_rate}%"
            fi
            
            # Learning effectiveness analysis
            if [ -f "$context_log" ]; then
                echo -e "\n${BOLD}Project Context Learning:${NC}"
                local detected_projects=$(grep '"project_type"' "$context_log" | cut -d'"' -f4 | sort | uniq -c | sort -nr)
                echo "$detected_projects" | head -5
            fi
            ;;
    esac
}

# Intelligence Optimization Recommendations
generate_intelligence_recommendations() {
    echo -e "\n${CYAN}${BOLD}🎯 Intelligence Optimization Recommendations${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    local recommendations=""
    
    # Analyze current intelligence effectiveness
    local today=$(date +%Y-%m-%d)
    local metrics_file=".claude/metrics/metrics-${today}.csv"
    
    if [ -f "$metrics_file" ]; then
        local total_tasks=$(grep -c ",start," "$metrics_file" 2>/dev/null || echo "1")
        local failed_tasks=$(grep -c ",complete,.*,fail" "$metrics_file" 2>/dev/null || echo "0")
        local failure_rate=$((failed_tasks * 100 / total_tasks))
        
        if [ "$failure_rate" -gt 10 ]; then
            recommendations="$recommendations\n• 🔧 High failure rate ($failure_rate%) - improve agent selection intelligence"
        fi
        
        if [ "$total_tasks" -gt 50 ]; then
            recommendations="$recommendations\n• ⚡ High activity ($total_tasks tasks) - consider performance optimization"
        fi
    fi
    
    # Check cost optimization opportunities
    local cost_file=".claude/metrics/token-costs.csv"
    if [ -f "$cost_file" ]; then
        local opus_percentage=$(grep ",opus," "$cost_file" | cut -d, -f4 | awk '{sum+=$1} END {print sum}' | awk -v total="$(cut -d, -f4 "$cost_file" | awk '{sum+=$1} END {print sum}')" '{printf "%.0f", $1*100/total}')
        
        if [ "${opus_percentage:-0}" -gt 40 ]; then
            recommendations="$recommendations\n• 💰 High Opus usage ($opus_percentage%) - implement intelligent model downgrading"
        fi
    fi
    
    # Check learning opportunities
    local selection_log=".claude/logs/agent-selection.jsonl"
    if [ -f "$selection_log" ]; then
        local low_confidence=$(grep '"activation_confidence":[0-6][0-9]' "$selection_log" | wc -l 2>/dev/null || echo "0")
        if [ "$low_confidence" -gt 5 ]; then
            recommendations="$recommendations\n• 🎓 Low confidence selections ($low_confidence) - enhance learning algorithms"
        fi
    fi
    
    if [ ! -z "$recommendations" ]; then
        echo -e "$recommendations"
    else
        echo "✅ System intelligence operating optimally - no immediate recommendations"
    fi
}

# Main intelligence analysis
case "${1:-overview}" in
    "activation")
        analyze_system_intelligence "activation"
        ;;
    "coordination") 
        analyze_system_intelligence "coordination"
        ;;
    "performance")
        analyze_system_intelligence "performance"
        ;;
    "cost")
        analyze_system_intelligence "cost"
        ;;
    "learning")
        analyze_system_intelligence "learning"
        ;;
    "all")
        analyze_system_intelligence "activation"
        analyze_system_intelligence "coordination"
        analyze_system_intelligence "performance"
        analyze_system_intelligence "cost"
        analyze_system_intelligence "learning"
        ;;
    "overview"|*)
        # Comprehensive intelligence overview
        echo -e "${BOLD}System Intelligence Overview${NC}"
        echo "Session ID: $INTELLIGENCE_ID"
        echo "Analysis Time: $TIMESTAMP"
        echo
        
        # Quick intelligence metrics
        local today=$(date +%Y-%m-%d)
        local total_tasks=$(grep -c ",start," ".claude/metrics/metrics-${today}.csv" 2>/dev/null || echo "0")
        local success_rate=0
        if [ "$total_tasks" -gt 0 ]; then
            local successful=$(grep -c ",complete,.*,success" ".claude/metrics/metrics-${today}.csv" 2>/dev/null || echo "0")
            success_rate=$((successful * 100 / total_tasks))
        fi
        
        local total_cost=$(cut -d, -f5 ".claude/metrics/token-costs.csv" 2>/dev/null | awk '{sum+=$1} END {printf "%.4f", sum}')
        local agent_count=$(ls .claude/agents/*.md 2>/dev/null | wc -l)
        
        echo "📊 Intelligence Metrics:"
        echo "  • Agents Available: $agent_count"
        echo "  • Today's Tasks: $total_tasks"
        echo "  • Success Rate: ${success_rate}%"
        echo "  • Total Cost: \$${total_cost:-0.0000}"
        
        # Intelligence health assessment
        local intelligence_health="optimal"
        if [ "$success_rate" -lt 80 ]; then
            intelligence_health="needs_improvement"
        elif [ "$success_rate" -lt 90 ]; then
            intelligence_health="good"
        fi
        
        echo "  • Intelligence Health: $intelligence_health"
        
        # Quick analysis of each intelligence component
        echo -e "\n${BOLD}Intelligence Components Status:${NC}"
        
        # Check if intelligence agents are working
        for intel_agent in context-analyzer ai-optimizer workflow-learner health-monitor integration-specialist; do
            local agent_usage=$(grep ",$intel_agent," ".claude/metrics/metrics-${today}.csv" 2>/dev/null | wc -l)
            if [ "$agent_usage" -gt 0 ]; then
                echo "  ✅ $intel_agent: Active ($agent_usage uses)"
            else
                echo "  ⚪ $intel_agent: Available (not yet used)"
            fi
        done
        ;;
esac

# Generate intelligence recommendations
generate_intelligence_recommendations

# Log intelligence session
INTELLIGENCE_LOG=".claude/logs/intelligence-sessions.jsonl"
echo "{
  \"timestamp\": \"$TIMESTAMP\",
  \"session_id\": \"$INTELLIGENCE_ID\",
  \"analysis_type\": \"${1:-overview}\",
  \"intelligence_health\": \"$intelligence_health\",
  \"recommendations_generated\": true
}" >> "$INTELLIGENCE_LOG"

echo -e "\n${CYAN}🧠 Intelligence analysis complete. Session: $INTELLIGENCE_ID${NC}"