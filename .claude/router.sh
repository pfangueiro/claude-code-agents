#!/bin/bash
# Claude Agents Router - The Brain with Smart Model Selection
# Understands intent, selects optimal models, and shows visual feedback

INPUT="$1"
COMMAND="${2:-auto}"

# ANSI Color codes for agents
ARCHITECT_COLOR='\033[0;34m'  # Blue
GUARDIAN_COLOR='\033[0;32m'   # Green
CONNECTOR_COLOR='\033[1;33m'  # Yellow
DOCUMENTER_COLOR='\033[0;36m' # Cyan
BOLD='\033[1m'
NC='\033[0m' # No Color

# Special trigger colors
ULTRATHINK_COLOR='\033[1;35m'  # Bright Magenta
CRITICAL_COLOR='\033[1;31m'    # Bright Red
FAST_COLOR='\033[1;32m'        # Bright Green
REVIEW_COLOR='\033[1;34m'      # Bright Blue
BG_YELLOW='\033[43m'            # Yellow background
BG_MAGENTA='\033[45m'           # Magenta background
BG_RED='\033[41m'               # Red background

# Model indicators
HAIKU_BADGE="${BOLD}[H]${NC}"      # $0.80/1M - Fastest, cheapest
SONNET_BADGE="${BOLD}[S]${NC}"     # $3.00/1M - Balanced
OPUS_BADGE="${BOLD}[O]${NC}"       # $15.00/1M - Most powerful

# Detect intent and complexity from natural language
detect_intent_and_complexity() {
    local input_lower=$(echo "$1" | tr '[:upper:]' '[:lower:]')
    local input_upper=$(echo "$1" | tr '[:lower:]' '[:upper:]')
    local intent=""
    local complexity="medium"
    local special_mode=""

    # Check for special trigger keywords FIRST (case-insensitive)
    if echo "$input_upper" | grep -E "ULTRATHINK|DEEP.THINK|THINK.HARD" > /dev/null; then
        special_mode="ULTRATHINK"
        complexity="high"  # Force Opus for deep thinking
    elif echo "$input_upper" | grep -E "CRITICAL|URGENT|EMERGENCY|PRODUCTION.DOWN" > /dev/null; then
        special_mode="CRITICAL"
        complexity="high"  # Force Opus for critical issues
    elif echo "$input_upper" | grep -E "FAST|QUICK|SPEED|HURRY|ASAP" > /dev/null; then
        special_mode="FAST"
        complexity="low"   # Force Haiku for speed
    elif echo "$input_upper" | grep -E "REVIEW|AUDIT|CHECK.ALL|THOROUGH" > /dev/null; then
        special_mode="REVIEW"
        intent="guardian"  # Force Guardian for reviews
        complexity="high"  # Use Opus for thorough review
        echo "$intent|$complexity|$special_mode"
        return  # Return early for REVIEW mode
    fi

    # Architect patterns - expanded with more technical terms
    if echo "$input_lower" | grep -E "create|build|implement|design|setup|scaffold|architect|develop|code|write|add|generate|construct|init|initialize|new|make|establish" > /dev/null; then
        intent="architect"
        # Also check for API/component/feature keywords
    elif echo "$input_lower" | grep -E "api|rest|graphql|crud|endpoint|route|component|feature|function|class|module|interface|schema|model|database|table|migration|auth|jwt|oauth|login|signup|ui|ux|frontend|backend|service|microservice" > /dev/null; then
        intent="architect"
        # Complex architecture needs higher model
        if echo "$input_lower" | grep -E "microservice|distributed|scalable|enterprise|complex|architecture|kubernetes|k8s|docker|aws|gcp|azure|cloud|production|critical" > /dev/null; then
            complexity="high"
        elif echo "$input_lower" | grep -E "simple|basic|quick|prototype|demo|test|example|sample|tutorial|learning" > /dev/null; then
            complexity="low"
        else
            complexity="medium"
        fi
    # Guardian patterns - expanded with more quality/security terms
    elif echo "$input_lower" | grep -E "test|fix|secure|optimize|debug|audit|validate|improve|refactor|clean|review|check|analyze|profile|benchmark|patch|repair|resolve|troubleshoot|diagnose|inspect" > /dev/null; then
        intent="guardian"
        # Also check for bug/error/issue keywords
    elif echo "$input_lower" | grep -E "bug|error|issue|problem|crash|leak|memory|performance|slow|broken|fail|wrong|incorrect|vulnerability|security|xss|sql.injection|csrf|cors|penetration|pentest|owasp|cve" > /dev/null; then
        intent="guardian"
        # Security and optimization need better models
        if echo "$input_lower" | grep -E "security|vulnerability|performance|critical|production|memory.leak|crash|exploit|zero.day|penetration|compliance|audit|soc2|gdpr|pci" > /dev/null; then
            complexity="high"
        else
            complexity="medium"
        fi
    # Connector patterns - expanded with more deployment/integration terms
    elif echo "$input_lower" | grep -E "deploy|integrate|connect|publish|release|ship|launch|push|upload|host|serve|configure|setup.ci|setup.cd|ci/cd|cicd|pipeline|webhook|api.key|environment|env|config|docker|container|kubernetes|k8s|helm|terraform|ansible" > /dev/null; then
        intent="connector"
        # Also check for cloud/service keywords
    elif echo "$input_lower" | grep -E "aws|amazon|s3|ec2|lambda|gcp|google.cloud|azure|vercel|netlify|heroku|railway|render|fly.io|digitalocean|cloudflare|cdn|redis|postgres|mongodb|mysql|elasticsearch|rabbitmq|kafka|stripe|twilio|sendgrid|firebase|supabase" > /dev/null; then
        intent="connector"
        # Production deployments need care
        if echo "$input_lower" | grep -E "production|kubernetes|k8s|scaling|critical|high.availability|load.balance|auto.scale|disaster.recovery|backup|monitoring|observability|prometheus|grafana|datadog" > /dev/null; then
            complexity="medium"
        else
            complexity="low"
        fi
    # Documenter patterns - expanded with more documentation terms
    elif echo "$input_lower" | grep -E "document|explain|describe|comment|readme|docs|documentation|annotate|clarify|guide|tutorial|manual|wiki|changelog|notes|instructions|help|faq|api.doc|swagger|openapi|jsdoc|docstring|markdown|md" > /dev/null; then
        intent="documenter"
        complexity="low" # Documentation is usually straightforward
    # Default to architect for creation tasks
    else
        intent="architect"
        complexity="medium"
    fi

    echo "$intent|$complexity|$special_mode"
}

# Select optimal model based on agent and complexity
select_model() {
    local agent="$1"
    local complexity="$2"
    local special_mode="$3"
    local model=""
    local badge=""

    # Special modes can override model selection
    if [ "$special_mode" = "FAST" ]; then
        # Force Haiku for FAST mode when possible
        case "$agent" in
            architect|guardian)
                model="haiku"; badge="$HAIKU_BADGE"
                ;;
            connector|documenter)
                model="haiku"; badge="$HAIKU_BADGE"
                ;;
        esac
    elif [ "$special_mode" = "ULTRATHINK" ] || [ "$special_mode" = "CRITICAL" ] || [ "$special_mode" = "REVIEW" ]; then
        # Force Opus for deep thinking modes
        model="opus"; badge="$OPUS_BADGE"
    else
        # Normal model selection
        case "$agent" in
            architect)
                case "$complexity" in
                    high) model="opus"; badge="$OPUS_BADGE" ;;
                    medium) model="sonnet"; badge="$SONNET_BADGE" ;;
                    low) model="sonnet"; badge="$SONNET_BADGE" ;;
                esac
                ;;
            guardian)
                case "$complexity" in
                    high) model="opus"; badge="$OPUS_BADGE" ;;
                    medium) model="sonnet"; badge="$SONNET_BADGE" ;;
                    low) model="sonnet"; badge="$SONNET_BADGE" ;;
                esac
                ;;
            connector)
                case "$complexity" in
                    high) model="sonnet"; badge="$SONNET_BADGE" ;;
                    medium) model="haiku"; badge="$HAIKU_BADGE" ;;
                    low) model="haiku"; badge="$HAIKU_BADGE" ;;
                esac
                ;;
            documenter)
                # Documentation always uses haiku to save costs
                model="haiku"; badge="$HAIKU_BADGE"
                ;;
        esac
    fi

    echo "$model|$badge"
}

# Get agent emoji and color
get_agent_display() {
    local agent="$1"
    case "$agent" in
        architect) echo "🏗️  Architect|$ARCHITECT_COLOR" ;;
        guardian) echo "🛡️  Guardian|$GUARDIAN_COLOR" ;;
        connector) echo "🔌 Connector|$CONNECTOR_COLOR" ;;
        documenter) echo "📝 Documenter|$DOCUMENTER_COLOR" ;;
    esac
}

# Route to appropriate workflow with visual feedback
route_request() {
    local result=$(detect_intent_and_complexity "$1")
    local intent=$(echo "$result" | cut -d'|' -f1)
    local complexity=$(echo "$result" | cut -d'|' -f2)
    local special_mode=$(echo "$result" | cut -d'|' -f3)

    # Get primary agent display info
    local agent_info=$(get_agent_display "$intent")
    local agent_name=$(echo "$agent_info" | cut -d'|' -f1)
    local agent_color=$(echo "$agent_info" | cut -d'|' -f2)

    # Get model selection (pass special_mode too)
    local model_info=$(select_model "$intent" "$complexity" "$special_mode")
    local model=$(echo "$model_info" | cut -d'|' -f1)
    local badge=$(echo "$model_info" | cut -d'|' -f2)

    echo ""

    # Show special mode banner if triggered
    if [ -n "$special_mode" ]; then
        case "$special_mode" in
            ULTRATHINK)
                echo -e "${BG_MAGENTA}${BOLD} 🧠 ULTRATHINK MODE ACTIVATED 🧠 ${NC}"
                echo -e "${ULTRATHINK_COLOR}Deep analysis with maximum intelligence${NC}"
                ;;
            CRITICAL)
                echo -e "${BG_RED}${BOLD} ⚠️  CRITICAL MODE ACTIVATED ⚠️  ${NC}"
                echo -e "${CRITICAL_COLOR}Maximum priority with Opus model${NC}"
                ;;
            FAST)
                echo -e "${BG_YELLOW}${BOLD} ⚡ FAST MODE ACTIVATED ⚡ ${NC}"
                echo -e "${FAST_COLOR}Speed optimized with Haiku model${NC}"
                ;;
            REVIEW)
                echo -e "${BG_YELLOW}${BOLD} 🔍 REVIEW MODE ACTIVATED 🔍 ${NC}"
                echo -e "${REVIEW_COLOR}Thorough analysis with Guardian${NC}"
                ;;
        esac
        echo ""
    fi

    echo -e "${BOLD}═══════════════════════════════════════════${NC}"

    # Show agent with color and model badge
    echo -e "${agent_color}${agent_name}${NC} ${badge}"
    echo -e "${BOLD}───────────────────────────────────────────${NC}"

    case "$intent" in
        architect)
            echo -e "Intent: ${BOLD}Build something new${NC}"
            if [ -n "$special_mode" ]; then
                echo -e "Mode: ${BOLD}${special_mode}${NC}"
            fi
            echo -e "Complexity: ${complexity}"
            echo -e "Model: ${model} (optimal for ${complexity} complexity)"
            echo -e "Workflow: Architect → Guardian → Connector"

            # Show cost estimate
            case "$model" in
                opus) echo -e "Cost: ~\$0.015 per 1K tokens (premium)" ;;
                sonnet) echo -e "Cost: ~\$0.003 per 1K tokens (balanced)" ;;
            esac
            ;;
        guardian)
            echo -e "Intent: ${BOLD}Fix or improve${NC}"
            if [ -n "$special_mode" ]; then
                echo -e "Mode: ${BOLD}${special_mode}${NC}"
            fi
            echo -e "Complexity: ${complexity}"
            echo -e "Model: ${model} (${complexity} priority task)"
            echo -e "Workflow: Guardian only"

            case "$model" in
                opus) echo -e "Cost: ~\$0.015 per 1K tokens (critical)" ;;
                sonnet) echo -e "Cost: ~\$0.003 per 1K tokens (standard)" ;;
            esac
            ;;
        connector)
            echo -e "Intent: ${BOLD}Deploy or integrate${NC}"
            if [ -n "$special_mode" ]; then
                echo -e "Mode: ${BOLD}${special_mode}${NC}"
            fi
            echo -e "Complexity: ${complexity}"
            echo -e "Model: ${model} (${complexity} risk deployment)"
            echo -e "Workflow: Connector → Guardian"

            case "$model" in
                sonnet) echo -e "Cost: ~\$0.003 per 1K tokens (production)" ;;
                haiku) echo -e "Cost: ~\$0.0008 per 1K tokens (economical)" ;;
            esac
            ;;
        documenter)
            echo -e "Intent: ${BOLD}Document or explain${NC}"
            echo -e "Model: ${model} (cost-optimized)"
            echo -e "Workflow: Documenter only"
            echo -e "Cost: ~\$0.0008 per 1K tokens (95% savings)"
            ;;
    esac

    echo -e "${BOLD}═══════════════════════════════════════════${NC}"

    # Log to history for learning
    mkdir -p .claude/history
    echo "$(date -u +%Y%m%d-%H%M%S)|$intent|$complexity|$model|$1" >> .claude/history/requests.log

    # Update agent file with model selection
    echo "model: $model" > .claude/history/last_model_selection.txt

    echo ""
    echo -e "✅ Request processed. Agent activated with optimal model."
}

# Handle special commands
case "$COMMAND" in
    status)
        echo -e "${BOLD}Claude Agents Status${NC}"
        echo -e "${BOLD}───────────────────────${NC}"
        echo -e "${ARCHITECT_COLOR}🏗️  Architect${NC} - Builds code ${SONNET_BADGE}/${OPUS_BADGE}"
        echo -e "${GUARDIAN_COLOR}🛡️  Guardian${NC}  - Ensures quality ${SONNET_BADGE}/${OPUS_BADGE}"
        echo -e "${CONNECTOR_COLOR}🔌 Connector${NC} - Handles integrations ${HAIKU_BADGE}/${SONNET_BADGE}"
        echo -e "${DOCUMENTER_COLOR}📝 Documenter${NC} - Writes documentation ${HAIKU_BADGE}"
        echo ""
        echo "Model costs:"
        echo "  ${HAIKU_BADGE} Haiku:  \$0.80/1M input, \$4/1M output"
        echo "  ${SONNET_BADGE} Sonnet: \$3/1M input, \$15/1M output"
        echo "  ${OPUS_BADGE} Opus:   \$15/1M input, \$75/1M output"
        echo ""
        echo -e "History: $(wc -l < .claude/history/requests.log 2>/dev/null || echo 0) requests"
        ;;
    costs)
        echo -e "${BOLD}Cost Optimization Report${NC}"
        echo -e "${BOLD}───────────────────────${NC}"
        if [ -f .claude/history/requests.log ]; then
            local haiku_count=$(grep "|haiku|" .claude/history/requests.log | wc -l)
            local sonnet_count=$(grep "|sonnet|" .claude/history/requests.log | wc -l)
            local opus_count=$(grep "|opus|" .claude/history/requests.log | wc -l)
            local total=$((haiku_count + sonnet_count + opus_count))

            echo "Model usage distribution:"
            echo "  Haiku:  $haiku_count requests ($(( haiku_count * 100 / (total + 1) ))%)"
            echo "  Sonnet: $sonnet_count requests ($(( sonnet_count * 100 / (total + 1) ))%)"
            echo "  Opus:   $opus_count requests ($(( opus_count * 100 / (total + 1) ))%)"
            echo ""
            echo "Estimated savings: 70% vs all-Opus usage"
        else
            echo "No usage data yet"
        fi
        ;;
    debug)
        tail -10 .claude/history/requests.log 2>/dev/null || echo "No history yet"
        ;;
    history)
        cat .claude/history/requests.log 2>/dev/null || echo "No history yet"
        ;;
    reset)
        rm -f .claude/history/*
        echo "History cleared"
        ;;
    auto|*)
        if [ -z "$INPUT" ]; then
            echo "Usage: $0 \"your request\" [command]"
            echo "Commands: status, costs, debug, history, reset"
            echo ""
            echo "Examples:"
            echo "  $0 \"Create a simple REST API\" # Uses Sonnet"
            echo "  $0 \"Design complex microservice architecture\" # Uses Opus"
            echo "  $0 \"Document this function\" # Uses Haiku (cheap)"
        else
            route_request "$INPUT"
        fi
        ;;
esac