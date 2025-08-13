#!/bin/bash
# Claude Code Agents Dashboard - Real-time tracking visualization

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Clear screen
clear

echo -e "${BLUE}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}${BOLD}║         Claude Code Agents - Tracking Dashboard              ║${NC}"
echo -e "${BLUE}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo

DATE=${1:-$(date +"%Y-%m-%d")}
METRICS_FILE=".claude/metrics/metrics-${DATE}.csv"
COST_FILE=".claude/metrics/token-costs.csv"

# Check if metrics exist
if [ ! -f "$METRICS_FILE" ]; then
    echo -e "${YELLOW}No metrics found for ${DATE}${NC}"
    echo "Run some agents first or specify a different date: ./dashboard.sh YYYY-MM-DD"
    exit 1
fi

# Today's Summary
echo -e "${CYAN}${BOLD}📊 Today's Summary (${DATE})${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Count events
TOTAL_TASKS=$(grep -c ",start," "$METRICS_FILE" 2>/dev/null || echo "0")
COMPLETED=$(grep -c ",complete,.*,success" "$METRICS_FILE" 2>/dev/null || echo "0")
FAILED=$(grep -c ",complete,.*,fail" "$METRICS_FILE" 2>/dev/null || echo "0")
IN_PROGRESS=$(grep -c ",in_progress" "$METRICS_FILE" 2>/dev/null || echo "0")
HANDOFFS=$(grep -c ",handoff," "$METRICS_FILE" 2>/dev/null || echo "0")

echo -e "Total Tasks:    ${BOLD}${TOTAL_TASKS}${NC}"
echo -e "Completed:      ${GREEN}${BOLD}${COMPLETED}${NC} ✅"
echo -e "Failed:         ${RED}${BOLD}${FAILED}${NC} ❌"
echo -e "In Progress:    ${YELLOW}${BOLD}${IN_PROGRESS}${NC} ⏳"
echo -e "Handoffs:       ${BLUE}${BOLD}${HANDOFFS}${NC} 🔄"

if [ $TOTAL_TASKS -gt 0 ]; then
    SUCCESS_RATE=$(echo "scale=1; ${COMPLETED} * 100 / ${TOTAL_TASKS}" | bc)
    echo -e "Success Rate:   ${BOLD}${SUCCESS_RATE}%${NC}"
fi

echo

# Agent Performance
echo -e "${CYAN}${BOLD}🤖 Agent Performance${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Count tasks per agent
echo "Agent                 Tasks    Completed    Tokens"
echo "─────────────────────────────────────────────────────────"

for agent in $(cut -d, -f3 "$METRICS_FILE" | grep -v "^agent$" | grep -v "^handoff$" | sort -u); do
    if [ "$agent" != "agent" ] && [ "$agent" != "handoff" ]; then
        AGENT_TASKS=$(grep ",${agent},start," "$METRICS_FILE" | wc -l)
        AGENT_COMPLETE=$(grep ",${agent},complete,.*,success" "$METRICS_FILE" | wc -l)
        
        # Get token usage from cost file if exists
        if [ -f "$COST_FILE" ]; then
            AGENT_TOKENS=$(grep "^${DATE},${agent}," "$COST_FILE" | cut -d, -f4 | awk '{sum+=$1} END {print int(sum)}')
        else
            AGENT_TOKENS="0"
        fi
        
        printf "%-20s %5d    %5d       %8s\n" "$agent" "$AGENT_TASKS" "$AGENT_COMPLETE" "${AGENT_TOKENS:-0}"
    fi
done

echo

# Token Costs
if [ -f "$COST_FILE" ]; then
    echo -e "${CYAN}${BOLD}💰 Token Usage & Costs${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Calculate totals by model
    HAIKU_TOKENS=$(grep "^${DATE},.*,haiku," "$COST_FILE" | cut -d, -f4 | awk '{sum+=$1} END {print int(sum)}')
    SONNET_TOKENS=$(grep "^${DATE},.*,sonnet," "$COST_FILE" | cut -d, -f4 | awk '{sum+=$1} END {print int(sum)}')
    OPUS_TOKENS=$(grep "^${DATE},.*,opus," "$COST_FILE" | cut -d, -f4 | awk '{sum+=$1} END {print int(sum)}')
    
    HAIKU_COST=$(grep "^${DATE},.*,haiku," "$COST_FILE" | cut -d, -f5 | awk '{sum+=$1} END {printf "%.4f", sum}')
    SONNET_COST=$(grep "^${DATE},.*,sonnet," "$COST_FILE" | cut -d, -f5 | awk '{sum+=$1} END {printf "%.4f", sum}')
    OPUS_COST=$(grep "^${DATE},.*,opus," "$COST_FILE" | cut -d, -f5 | awk '{sum+=$1} END {printf "%.4f", sum}')
    
    echo "Model      Tokens        Cost (USD)"
    echo "─────────────────────────────────────"
    [ ! -z "$HAIKU_TOKENS" ] && [ "$HAIKU_TOKENS" != "0" ] && printf "Haiku   %9s      \$%.4f\n" "$HAIKU_TOKENS" "${HAIKU_COST:-0}"
    [ ! -z "$SONNET_TOKENS" ] && [ "$SONNET_TOKENS" != "0" ] && printf "Sonnet  %9s      \$%.4f\n" "$SONNET_TOKENS" "${SONNET_COST:-0}"
    [ ! -z "$OPUS_TOKENS" ] && [ "$OPUS_TOKENS" != "0" ] && printf "Opus    %9s      \$%.4f\n" "$OPUS_TOKENS" "${OPUS_COST:-0}"
    
    TOTAL_COST=$(grep "^${DATE}," "$COST_FILE" | cut -d, -f5 | awk '{sum+=$1} END {printf "%.4f", sum}')
    TOTAL_TOKENS=$(echo "${HAIKU_TOKENS:-0} + ${SONNET_TOKENS:-0} + ${OPUS_TOKENS:-0}" | bc)
    
    echo "─────────────────────────────────────"
    printf "${BOLD}Total   %9s      \$%.4f${NC}\n" "$TOTAL_TOKENS" "$TOTAL_COST"
    echo
fi

# Recent Activity
echo -e "${CYAN}${BOLD}📜 Recent Activity${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Show last 5 events
tail -5 "$METRICS_FILE" | while IFS=',' read -r timestamp task_id agent event description parent tokens status; do
    TIME=$(echo "$timestamp" | cut -d'T' -f2 | cut -d'Z' -f1)
    
    case "$event" in
        "start")
            echo -e "${TIME} ${GREEN}▶${NC}  ${agent} started: ${description}"
            ;;
        "complete")
            if [ "$status" = "success" ]; then
                echo -e "${TIME} ${GREEN}✓${NC}  ${agent} completed (${tokens} tokens)"
            else
                echo -e "${TIME} ${RED}✗${NC}  ${agent} failed"
            fi
            ;;
        "handoff")
            echo -e "${TIME} ${BLUE}→${NC}  Handoff: ${description}"
            ;;
    esac
done

echo

# Workflow Chains
if [ -f ".claude/logs/handoffs-${DATE}.jsonl" ]; then
    echo -e "${CYAN}${BOLD}🔗 Workflow Chains${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Show last 3 handoff chains
    tail -3 ".claude/logs/handoffs-${DATE}.jsonl" 2>/dev/null | while read line; do
        FROM=$(echo "$line" | jq -r '.from_agent // .from' 2>/dev/null)
        TO=$(echo "$line" | jq -r '.to_agent // .to' 2>/dev/null)
        TOKEN=$(echo "$line" | jq -r '.handoff_token' 2>/dev/null | cut -c1-8)
        
        if [ ! -z "$FROM" ] && [ ! -z "$TO" ]; then
            echo -e "${FROM} ${BLUE}→${NC} ${TO} (${TOKEN}...)"
        fi
    done
    echo
fi

# Footer
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${PURPLE}Commands:${NC}"
echo "  ./dashboard.sh [date]     - View metrics for specific date"
echo "  ./tracking.sh status      - Show current tasks"
echo "  ./tracking.sh costs       - Detailed cost breakdown"
echo "  gh issue list -l agent:*  - View GitHub tracked tasks"