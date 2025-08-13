#!/bin/bash
# Claude Code Agents - Tracking Management Script

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# Function to show status
show_status() {
    echo -e "${CYAN}${BOLD}📊 Current Task Status${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    DATE=$(date +"%Y-%m-%d")
    METRICS_FILE=".claude/metrics/metrics-${DATE}.csv"
    
    if [ ! -f "$METRICS_FILE" ]; then
        echo "No tasks running today"
        return
    fi
    
    # Show in-progress tasks
    echo -e "\n${YELLOW}⏳ In Progress:${NC}"
    grep ",in_progress$" "$METRICS_FILE" | tail -5 | while IFS=',' read -r time id agent event desc rest; do
        echo "  • ${agent}: ${desc} (${id})"
    done
    
    # Show recent completions
    echo -e "\n${GREEN}✅ Recently Completed:${NC}"
    grep ",complete,.*,success$" "$METRICS_FILE" | tail -5 | while IFS=',' read -r time id agent event desc parent tokens status; do
        echo "  • ${agent}: Task ${id} (${tokens} tokens)"
    done
    
    # Show failures
    FAILURES=$(grep ",complete,.*,fail" "$METRICS_FILE" 2>/dev/null)
    if [ ! -z "$FAILURES" ]; then
        echo -e "\n${RED}❌ Failed Tasks:${NC}"
        echo "$FAILURES" | while IFS=',' read -r time id agent event desc rest; do
            echo "  • ${agent}: Task ${id}"
        done
    fi
}

# Function to show costs
show_costs() {
    echo -e "${CYAN}${BOLD}💰 Token Usage & Cost Analysis${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    COST_FILE=".claude/metrics/token-costs.csv"
    
    if [ ! -f "$COST_FILE" ]; then
        echo "No cost data available yet"
        return
    fi
    
    # Today's costs
    DATE=$(date +"%Y-%m-%d")
    echo -e "\n${BOLD}Today (${DATE}):${NC}"
    
    TODAY_TOTAL=$(grep "^${DATE}," "$COST_FILE" | cut -d, -f5 | awk '{sum+=$1} END {printf "%.4f", sum}')
    TODAY_TOKENS=$(grep "^${DATE}," "$COST_FILE" | cut -d, -f4 | awk '{sum+=$1} END {print sum}')
    
    echo "  Total Tokens: ${TODAY_TOKENS:-0}"
    echo "  Total Cost: \$${TODAY_TOTAL:-0.0000}"
    
    # This week's costs
    echo -e "\n${BOLD}This Week:${NC}"
    WEEK_START=$(date -d "last Sunday" +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d)
    WEEK_TOTAL=$(awk -F, -v start="$WEEK_START" '$1 >= start {sum+=$5} END {printf "%.4f", sum}' "$COST_FILE")
    WEEK_TOKENS=$(awk -F, -v start="$WEEK_START" '$1 >= start {sum+=$4} END {print sum}' "$COST_FILE")
    
    echo "  Total Tokens: ${WEEK_TOKENS:-0}"
    echo "  Total Cost: \$${WEEK_TOTAL:-0.0000}"
    
    # Per model breakdown
    echo -e "\n${BOLD}By Model:${NC}"
    echo "  Model    Tokens      Cost"
    echo "  ──────────────────────────"
    
    for model in haiku sonnet opus; do
        MODEL_TOKENS=$(grep ",${model}," "$COST_FILE" | cut -d, -f4 | awk '{sum+=$1} END {print sum}')
        MODEL_COST=$(grep ",${model}," "$COST_FILE" | cut -d, -f5 | awk '{sum+=$1} END {printf "%.4f", sum}')
        
        if [ ! -z "$MODEL_TOKENS" ] && [ "$MODEL_TOKENS" != "0" ]; then
            printf "  %-7s %8s  \$%.4f\n" "$model" "$MODEL_TOKENS" "$MODEL_COST"
        fi
    done
    
    # Top agents by cost
    echo -e "\n${BOLD}Top Agents by Usage:${NC}"
    echo "  Agent              Tokens"
    echo "  ─────────────────────────"
    
    awk -F, '{agents[$2]+=$4} END {for(a in agents) print a, agents[a]}' "$COST_FILE" | \
        sort -k2 -rn | head -5 | while read agent tokens; do
        printf "  %-16s %8s\n" "$agent" "$tokens"
    done
    
    # Projection
    if [ ! -z "$TODAY_TOKENS" ] && [ "$TODAY_TOKENS" != "0" ]; then
        MONTHLY_PROJECTION=$(echo "scale=2; ${TODAY_TOTAL} * 30" | bc)
        echo -e "\n${BOLD}📈 Monthly Projection:${NC} \$${MONTHLY_PROJECTION} (at current rate)"
    fi
}

# Function to enable GitHub tracking
enable_github() {
    echo -e "${CYAN}${BOLD}🔗 Enabling GitHub Issue Tracking${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Check gh CLI
    if ! command -v gh &> /dev/null; then
        echo -e "${RED}❌ GitHub CLI (gh) not installed${NC}"
        echo "Install with: brew install gh"
        return 1
    fi
    
    # Check authentication
    if ! gh auth status &> /dev/null; then
        echo -e "${YELLOW}⚠️  Not authenticated with GitHub${NC}"
        echo "Run: gh auth login"
        return 1
    fi
    
    # Set environment variable
    export GITHUB_TRACKING=true
    echo "export GITHUB_TRACKING=true" >> ~/.bashrc
    echo "export GITHUB_TRACKING=true" >> ~/.zshrc 2>/dev/null
    
    # Create labels if they don't exist
    echo "Creating tracking labels..."
    
    gh label create "agent:api-builder" --color "0969DA" --description "API Builder Agent" 2>/dev/null
    gh label create "agent:test-engineer" --color "FFA500" --description "Test Engineer Agent" 2>/dev/null
    gh label create "agent:secure-coder" --color "00FF00" --description "Secure Coder Agent" 2>/dev/null
    gh label create "status:in-progress" --color "FFFF00" --description "Task in progress" 2>/dev/null
    gh label create "status:completed" --color "00FF00" --description "Task completed" 2>/dev/null
    gh label create "status:failed" --color "FF0000" --description "Task failed" 2>/dev/null
    
    echo -e "${GREEN}✅ GitHub tracking enabled${NC}"
    echo "New tasks will create GitHub issues automatically"
}

# Function to generate report
generate_report() {
    DATE=${1:-$(date +"%Y-%m-%d")}
    
    echo -e "${CYAN}${BOLD}📋 Task Execution Report - ${DATE}${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    METRICS_FILE=".claude/metrics/metrics-${DATE}.csv"
    
    if [ ! -f "$METRICS_FILE" ]; then
        echo "No data for ${DATE}"
        return
    fi
    
    # Calculate statistics
    TOTAL_TASKS=$(grep -c ",start," "$METRICS_FILE" 2>/dev/null || echo "0")
    COMPLETED=$(grep -c ",complete,.*,success" "$METRICS_FILE" 2>/dev/null || echo "0")
    FAILED=$(grep -c ",complete,.*,fail" "$METRICS_FILE" 2>/dev/null || echo "0")
    HANDOFFS=$(grep -c ",handoff," "$METRICS_FILE" 2>/dev/null || echo "0")
    
    SUCCESS_RATE=0
    if [ $TOTAL_TASKS -gt 0 ]; then
        SUCCESS_RATE=$(echo "scale=1; ${COMPLETED} * 100 / ${TOTAL_TASKS}" | bc)
    fi
    
    # Executive Summary
    echo -e "\n${BOLD}Executive Summary:${NC}"
    echo "• Total Tasks Executed: ${TOTAL_TASKS}"
    echo "• Success Rate: ${SUCCESS_RATE}%"
    echo "• Agent Handoffs: ${HANDOFFS}"
    
    # Cost Analysis
    COST_FILE=".claude/metrics/token-costs.csv"
    if [ -f "$COST_FILE" ]; then
        TOTAL_COST=$(grep "^${DATE}," "$COST_FILE" | cut -d, -f5 | awk '{sum+=$1} END {printf "%.4f", sum}')
        TOTAL_TOKENS=$(grep "^${DATE}," "$COST_FILE" | cut -d, -f4 | awk '{sum+=$1} END {print sum}')
        
        echo "• Total Tokens Used: ${TOTAL_TOKENS:-0}"
        echo "• Total Cost: \$${TOTAL_COST:-0.0000}"
        
        # ROI Calculation (assuming 1 task = 30 min saved)
        TIME_SAVED=$(echo "${COMPLETED} * 0.5" | bc)
        HOURLY_RATE=150  # Assume $150/hour developer cost
        VALUE_GENERATED=$(echo "scale=2; ${TIME_SAVED} * ${HOURLY_RATE}" | bc)
        ROI=$(echo "scale=0; (${VALUE_GENERATED} - ${TOTAL_COST}) / ${TOTAL_COST} * 100" | bc 2>/dev/null || echo "N/A")
        
        echo -e "\n${BOLD}ROI Analysis:${NC}"
        echo "• Time Saved: ${TIME_SAVED} hours"
        echo "• Value Generated: \$${VALUE_GENERATED}"
        echo "• ROI: ${ROI}%"
    fi
    
    # Workflow Patterns
    echo -e "\n${BOLD}Common Workflows:${NC}"
    if [ -f ".claude/logs/handoffs-${DATE}.jsonl" ]; then
        echo "Analyzing handoff patterns..."
        
        # Count handoff patterns
        jq -r '[.from_agent // .from, .to_agent // .to] | join(" → ")' ".claude/logs/handoffs-${DATE}.jsonl" 2>/dev/null | \
            sort | uniq -c | sort -rn | head -5 | while read count pattern; do
            echo "  ${count}x ${pattern}"
        done
    fi
    
    # Recommendations
    echo -e "\n${BOLD}Optimization Recommendations:${NC}"
    
    # Check for high-cost agents
    if [ -f "$COST_FILE" ]; then
        HIGH_COST_AGENT=$(awk -F, '{agents[$2]+=$5} END {for(a in agents) print a, agents[a]}' "$COST_FILE" | \
            sort -k2 -rn | head -1 | cut -d' ' -f1)
        
        if [ ! -z "$HIGH_COST_AGENT" ]; then
            echo "• Consider optimizing ${HIGH_COST_AGENT} - highest token usage"
        fi
    fi
    
    if [ "$SUCCESS_RATE" != "0" ] && [ $(echo "$SUCCESS_RATE < 80" | bc) -eq 1 ]; then
        echo "• Success rate below 80% - review failed tasks for patterns"
    fi
    
    if [ $HANDOFFS -gt $((TOTAL_TASKS * 2)) ]; then
        echo "• High handoff ratio - consider consolidating agent responsibilities"
    fi
    
    echo -e "\n${GREEN}Report generated successfully${NC}"
}

# Main script logic
case "$1" in
    "status")
        show_status
        ;;
    "costs")
        show_costs
        ;;
    "enable")
        if [ "$2" = "github" ]; then
            enable_github
        else
            echo "Usage: $0 enable github"
        fi
        ;;
    "disable")
        if [ "$2" = "github" ]; then
            unset GITHUB_TRACKING
            echo -e "${GREEN}✅ GitHub tracking disabled${NC}"
        else
            echo "Usage: $0 disable github"
        fi
        ;;
    "report")
        generate_report "$2"
        ;;
    "clear")
        echo -e "${YELLOW}⚠️  Clear today's metrics? (y/n)${NC}"
        read -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            DATE=$(date +"%Y-%m-%d")
            mv ".claude/metrics/metrics-${DATE}.csv" ".claude/metrics/metrics-${DATE}.csv.bak" 2>/dev/null
            echo -e "${GREEN}✅ Metrics cleared (backup saved)${NC}"
        fi
        ;;
    *)
        echo "Claude Code Agents - Tracking System"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "Usage: $0 [command] [options]"
        echo
        echo "Commands:"
        echo "  status         Show current task status"
        echo "  costs          Show token usage and costs"
        echo "  enable github  Enable GitHub issue tracking"
        echo "  disable github Disable GitHub issue tracking"
        echo "  report [date]  Generate report for date"
        echo "  clear          Clear today's metrics"
        echo
        echo "Examples:"
        echo "  $0 status"
        echo "  $0 costs"
        echo "  $0 report 2025-01-13"
        ;;
esac