#!/bin/bash
# Advanced Intent Router with Confidence Scoring and Natural Language Processing
# Version 2.0 - Production-grade with telemetry and multi-agent support

set -eo pipefail

# Configuration
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly AGENTS_DIR="$SCRIPT_DIR/agents"
readonly LIB_DIR="$SCRIPT_DIR/lib"
readonly TELEMETRY_DIR="$SCRIPT_DIR/telemetry"
readonly CONFIDENCE_THRESHOLD=0.5
readonly FALLBACK_AGENT="generalist"

# Source security library
if [[ -f "$LIB_DIR/security.sh" ]]; then
    source "$LIB_DIR/security.sh"
else
    echo "Warning: Security library not found. Running without input sanitization." >&2
fi

# Source performance utilities
if [[ -f "$LIB_DIR/performance-utils.sh" ]]; then
    # Temporarily disabled due to compatibility issues
    # source "$LIB_DIR/performance-utils.sh"
    USE_FAST_MODE=false
else
    USE_FAST_MODE=false
fi

# Source color system
if [[ -f "$LIB_DIR/colors.sh" ]]; then
    source "$LIB_DIR/colors.sh"
    USE_COLORS=true
else
    USE_COLORS=false
    # Fallback basic colors
    readonly MOBILE_COLOR='\033[0;35m'    # Magenta
    readonly API_COLOR='\033[0;31m'       # Red
    readonly SCHEMA_COLOR='\033[1;34m'    # Bright Blue
    readonly PERF_COLOR='\033[1;33m'      # Yellow
    readonly SECURITY_COLOR='\033[0;31m'  # Red
    readonly A11Y_COLOR='\033[0;36m'      # Cyan
    readonly DOCS_COLOR='\033[0;32m'      # Green
    readonly NC='\033[0m'                 # No Color
    readonly BOLD='\033[1m'
fi

# Agent list
readonly AGENT_NAMES=("mobile-ux" "api-reliability" "schema-guardian" "performance" "security" "accessibility" "documentation")

# Get agent display name
get_agent_name() {
    case "$1" in
        mobile-ux) echo "Mobile/PWA UX Agent" ;;
        api-reliability) echo "API Reliability Agent" ;;
        schema-guardian) echo "Schema Guardian Agent" ;;
        performance) echo "Performance Agent" ;;
        security) echo "Security Agent" ;;
        accessibility) echo "Accessibility Agent" ;;
        documentation) echo "Documentation Agent" ;;
        *) echo "Unknown Agent" ;;
    esac
}

# Get primary keywords for agent
get_primary_keywords() {
    case "$1" in
        mobile-ux) echo "mobile|pwa|responsive|viewport|touch|gesture|orientation|offline|manifest|service.worker" ;;
        api-reliability) echo "rowsaffected|persist|saved|api.contract|idempotent|retry|circuit.breaker|fallback" ;;
        schema-guardian) echo "schema|migration|ddl|alter.table|column|constraint|index|foreign.key|adr" ;;
        performance) echo "performance|slow|optimize|bundle|chunk|lazy|cache|profil|benchmark|memory.leak" ;;
        security) echo "security|vulnerability|xss|csrf|injection|auth|rbac|permission|encrypt|token" ;;
        accessibility) echo "wcag|aria|a11y|accessible|contrast|keyboard|screen.reader|focus|alt.text" ;;
        documentation) echo "document|readme|changelog|comment|explain|describe|api.doc|swagger|openapi" ;;
        *) echo "" ;;
    esac
}

# Get secondary keywords for agent
get_secondary_keywords() {
    case "$1" in
        mobile-ux) echo "cls|lcp|fid|ttfb|cumulative|layout|paint|interactive|viewport.meta|apple.touch" ;;
        api-reliability) echo "200|201|204|400|401|403|404|500|502|503|put|post|patch|delete" ;;
        schema-guardian) echo "database|table|field|type|nullable|default|unique|primary|relationship" ;;
        performance) echo "webpack|rollup|vite|parcel|esbuild|terser|uglify|minify|compress|gzip" ;;
        security) echo "csp|hsts|cors|samesite|httponly|secure|sanitize|validate|escape|encode" ;;
        accessibility) echo "tab|role|label|describedby|live|hidden|sr.only|announce|semantic" ;;
        documentation) echo "jsdoc|tsdoc|docstring|annotation|example|usage|param|return|throws" ;;
        *) echo "" ;;
    esac
}

# Get context keywords for agent
get_context_keywords() {
    case "$1" in
        mobile-ux) echo "iphone|android|tablet|phone|device|screen|breakpoint|media.query" ;;
        api-reliability) echo "endpoint|route|controller|middleware|request|response|status|header" ;;
        schema-guardian) echo "postgres|mysql|mongodb|sqlite|redis|orm|sequelize|prisma|typeorm" ;;
        performance) echo "speed|fast|quick|slow|lag|delay|bottleneck|optimize|improve" ;;
        security) echo "hack|exploit|breach|leak|expose|attack|threat|risk|audit" ;;
        accessibility) echo "blind|deaf|disabled|impaired|assistive|navigation|usability" ;;
        documentation) echo "help|guide|tutorial|reference|spec|standard|rfc|wiki" ;;
        *) echo "" ;;
    esac
}

# Initialize telemetry
init_telemetry() {
    mkdir -p "$TELEMETRY_DIR"
    if [[ ! -f "$TELEMETRY_DIR/events.jsonl" ]]; then
        touch "$TELEMETRY_DIR/events.jsonl"
    fi
}

# Log telemetry event
log_telemetry() {
    local event_type="$1"
    local agent="$2"
    local confidence="$3"
    local elapsed_ms="$4"
    local outcome="${5:-pending}"

    # Sanitize inputs to prevent log injection
    if type sanitize_input &>/dev/null; then
        event_type=$(sanitize_input "$event_type" 50)
        agent=$(sanitize_input "$agent" 50)
        outcome=$(sanitize_input "$outcome" 50)
    fi

    local timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local event_json=$(cat <<EOF
{"timestamp":"$timestamp","event":"$event_type","agent":"$agent","confidence":$confidence,"elapsed_ms":$elapsed_ms,"outcome":"$outcome"}
EOF
    )

    # Use secure logging if available
    if type secure_log &>/dev/null; then
        secure_log "$TELEMETRY_DIR/events.jsonl" "$event_json" 10000
    else
        echo "$event_json" >> "$TELEMETRY_DIR/events.jsonl"
    fi
}

# Calculate confidence score for an agent
calculate_confidence() {
    local input_lower="$1"
    local agent="$2"

    local primary_score=0
    local secondary_score=0
    local context_score=0
    local total_keywords=0

    # Check primary keywords (weight 1.0)
    local primary_pattern=$(get_primary_keywords "$agent")
    if [[ -n "$primary_pattern" ]]; then
        local matches=$(echo "$input_lower" | grep -oE "$primary_pattern" | wc -l)
        primary_score=$matches
        ((total_keywords += $(echo "$primary_pattern" | tr '|' '\n' | wc -l)))
    fi

    # Check secondary keywords (weight 0.5)
    local secondary_pattern=$(get_secondary_keywords "$agent")
    if [[ -n "$secondary_pattern" ]]; then
        local matches=$(echo "$input_lower" | grep -oE "$secondary_pattern" | wc -l)
        secondary_score=$(echo "scale=2; $matches * 0.5" | bc)
        ((total_keywords += $(echo "$secondary_pattern" | tr '|' '\n' | wc -l)))
    fi

    # Check context keywords (weight 0.3)
    local context_pattern=$(get_context_keywords "$agent")
    if [[ -n "$context_pattern" ]]; then
        local matches=$(echo "$input_lower" | grep -oE "$context_pattern" | wc -l)
        context_score=$(echo "scale=2; $matches * 0.3" | bc)
        ((total_keywords += $(echo "$context_pattern" | tr '|' '\n' | wc -l)))
    fi

    # Calculate final confidence (0.0 to 1.0)
    local total_score=$(echo "scale=4; $primary_score + $secondary_score + $context_score" | bc)

    if [[ $total_keywords -gt 0 ]]; then
        local confidence=$(echo "scale=4; $total_score / $total_keywords * 10" | bc)
        # Cap at 1.0
        if (( $(echo "$confidence > 1.0" | bc -l) )); then
            confidence="1.0000"
        fi
        echo "$confidence"
    else
        echo "0.0000"
    fi
}

# Find best matching agent
find_best_agent() {
    local input="$1"

    # Use optimized version if available
    if [[ "$USE_FAST_MODE" == true ]]; then
        fast_find_best_agent "$input"
        return
    fi

    # Original implementation as fallback
    local input_lower=$(echo "$input" | tr '[:upper:]' '[:lower:]')

    local best_agent=""
    local best_confidence="0.0000"

    # Calculate confidence for each agent
    for agent in "${AGENT_NAMES[@]}"; do
        local confidence=$(calculate_confidence "$input_lower" "$agent")

        # Track best match
        if (( $(echo "$confidence > $best_confidence" | bc -l) )); then
            best_agent="$agent"
            best_confidence="$confidence"
        fi
    done

    # Tie-breaking rules (priority order)
    local tie_break_order=("security" "schema-guardian" "api-reliability" "performance" "mobile-ux" "accessibility" "documentation")

    # Check for ties by recalculating confidence for tie-break agents
    for agent in "${tie_break_order[@]}"; do
        local agent_confidence=$(calculate_confidence "$input_lower" "$agent")
        if (( $(echo "$agent_confidence == $best_confidence && $agent_confidence > 0" | bc -l) )); then
            best_agent="$agent"
            break
        fi
    done

    # Fallback to generalist if confidence too low
    if (( $(echo "$best_confidence < $CONFIDENCE_THRESHOLD" | bc -l) )); then
        echo "$FALLBACK_AGENT|0.0000|low_confidence"
    else
        echo "$best_agent|$best_confidence|matched"
    fi
}

# Get agent color
get_agent_color() {
    local agent="$1"
    case "$agent" in
        mobile-ux) echo "$MOBILE_COLOR" ;;
        api-reliability) echo "$API_COLOR" ;;
        schema-guardian) echo "$SCHEMA_COLOR" ;;
        performance) echo "$PERF_COLOR" ;;
        security) echo "$SECURITY_COLOR" ;;
        accessibility) echo "$A11Y_COLOR" ;;
        documentation) echo "$DOCS_COLOR" ;;
        *) echo "$NC" ;;
    esac
}

# Route request to agent
route_request() {
    local input="$1"

    # Sanitize input to prevent command injection
    if type sanitize_input &>/dev/null; then
        input=$(sanitize_input "$input" 1000)
    fi

    # Validate input safety
    if type validate_safe_input &>/dev/null; then
        if ! validate_safe_input "$input"; then
            echo "Error: Invalid input detected. Please remove special characters." >&2
            return 1
        fi
    fi

    local start_time=$(date +%s%N)

    # Find best matching agent
    local result=$(find_best_agent "$input")
    local agent=$(echo "$result" | cut -d'|' -f1)
    local confidence=$(echo "$result" | cut -d'|' -f2)
    local reason=$(echo "$result" | cut -d'|' -f3)

    # Calculate elapsed time
    local end_time=$(date +%s%N)
    local elapsed_ms=$(( ($end_time - $start_time) / 1000000 ))

    # Log telemetry
    log_telemetry "agent_activated" "$agent" "$confidence" "$elapsed_ms" "success"

    # Display result with enhanced colors
    if [[ "$USE_COLORS" == true ]]; then
        echo ""
        print_agent_header "$agent" "$confidence"
        echo ""
        echo -e "${DIM}Processing time: ${elapsed_ms}ms${NC}"
        echo -e "${DIM}Decision: $reason${NC}"
    else
        # Fallback display without advanced colors
        local agent_color=$(get_agent_color "$agent")
        local agent_name=$(get_agent_name "$agent")
        if [[ "$agent" == "$FALLBACK_AGENT" ]]; then
            agent_name="Generalist Agent"
        fi

        echo -e "\n${BOLD}════════════════════════════════════════${NC}"
        echo -e "${agent_color}${BOLD}$agent_name${NC}"
        echo -e "${BOLD}────────────────────────────────────────${NC}"
        echo -e "Confidence: ${BOLD}$(printf "%.2f%%" $(echo "$confidence * 100" | bc))${NC}"
        echo -e "Reason: $reason"
        echo -e "Processing time: ${elapsed_ms}ms"
    fi

    if [[ "$agent" != "$FALLBACK_AGENT" ]]; then
        if [[ "$USE_COLORS" == true ]]; then
            echo -e "\n${BOLD}${CYAN}Matched Keywords:${NC}"
            local input_lower=$(echo "$input" | tr '[:upper:]' '[:lower:]')

            # Get agent colors
            local colors=$(get_agent_colors "$agent" 2>/dev/null || echo "")
            local primary_color="${BRIGHT_GREEN}"
            local secondary_color="${YELLOW}"
            local context_color="${CYAN}"

            if [[ -n "$colors" ]]; then
                primary_color=$(echo "$colors" | cut -d'|' -f1)
                secondary_color=$(echo "$colors" | cut -d'|' -f2)
            fi

            # Show which keywords matched with colors
            local primary_pattern=$(get_primary_keywords "$agent")
            if [[ -n "$primary_pattern" ]]; then
                local matches=$(echo "$input_lower" | grep -oE "$primary_pattern" | sort -u | tr '\n' ', ')
                if [[ -n "$matches" ]]; then
                    echo -e "  ${primary_color}● Primary:${NC} ${BOLD}${matches%, }${NC}"
                fi
            fi

            local secondary_pattern=$(get_secondary_keywords "$agent")
            if [[ -n "$secondary_pattern" ]]; then
                local matches=$(echo "$input_lower" | grep -oE "$secondary_pattern" | sort -u | tr '\n' ', ')
                if [[ -n "$matches" ]]; then
                    echo -e "  ${secondary_color}● Secondary:${NC} ${matches%, }"
                fi
            fi

            local context_pattern=$(get_context_keywords "$agent")
            if [[ -n "$context_pattern" ]]; then
                local matches=$(echo "$input_lower" | grep -oE "$context_pattern" | sort -u | tr '\n' ', ')
                if [[ -n "$matches" ]]; then
                    echo -e "  ${context_color}● Context:${NC} ${DIM}${matches%, }${NC}"
                fi
            fi
        else
            # Original display
            echo -e "\n${BOLD}Activation Keywords Matched:${NC}"
            local input_lower=$(echo "$input" | tr '[:upper:]' '[:lower:]')

            # Show which keywords matched
            local primary_pattern=$(get_primary_keywords "$agent")
            if [[ -n "$primary_pattern" ]]; then
                local matches=$(echo "$input_lower" | grep -oE "$primary_pattern" | sort -u | tr '\n' ', ')
                if [[ -n "$matches" ]]; then
                    echo -e "  Primary: ${matches%, }"
                fi
            fi

            local secondary_pattern=$(get_secondary_keywords "$agent")
            if [[ -n "$secondary_pattern" ]]; then
                local matches=$(echo "$input_lower" | grep -oE "$secondary_pattern" | sort -u | tr '\n' ', ')
                if [[ -n "$matches" ]]; then
                    echo -e "  Secondary: ${matches%, }"
                fi
            fi

            local context_pattern=$(get_context_keywords "$agent")
            if [[ -n "$context_pattern" ]]; then
                local matches=$(echo "$input_lower" | grep -oE "$context_pattern" | sort -u | tr '\n' ', ')
                if [[ -n "$matches" ]]; then
                    echo -e "  Context: ${matches%, }"
                fi
            fi
        fi
    fi

    if [[ "$USE_COLORS" == true ]]; then
        echo ""
    else
        echo -e "${BOLD}════════════════════════════════════════${NC}\n"
    fi

    # Return agent for further processing
    echo "$agent|$confidence"
}

# Show all agents status
show_status() {
    echo -e "${BOLD}Claude Advanced Agent System Status${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    for agent in "${AGENT_NAMES[@]}"; do
        local color=$(get_agent_color "$agent")
        local name=$(get_agent_name "$agent")
        echo -e "${color}$name${NC}"
        echo -e "  ID: $agent"
        local primary=$(get_primary_keywords "$agent")
        echo -e "  Primary keywords: $(echo "${primary:-none}" | tr '|' ', ')"
        echo ""
    done

    # Show telemetry stats
    if [[ -f "$TELEMETRY_DIR/events.jsonl" ]]; then
        local total_events=$(wc -l < "$TELEMETRY_DIR/events.jsonl")
        echo -e "${BOLD}Telemetry Statistics:${NC}"
        echo -e "  Total events: $total_events"

        # Show agent usage distribution
        echo -e "\n  Agent usage:"
        for agent in "${AGENT_NAMES[@]}"; do
            local count=$(grep "\"agent\":\"$agent\"" "$TELEMETRY_DIR/events.jsonl" | wc -l)
            if [[ $count -gt 0 ]]; then
                echo -e "    $agent: $count"
            fi
        done
    fi
}

# Main execution
main() {
    local command="${1:-}"
    local input="${2:-}"

    # Initialize
    init_telemetry

    case "$command" in
        route)
            if [[ -z "$input" ]]; then
                echo "Usage: $0 route \"your natural language request\""
                exit 1
            fi
            route_request "$input"
            ;;
        status)
            show_status
            ;;
        test)
            # Run self-test
            echo "Running confidence scoring tests..."
            test_confidence_scoring
            ;;
        *)
            echo "Advanced Intent Router v2.0"
            echo "Usage:"
            echo "  $0 route \"your request\"  - Route to best matching agent"
            echo "  $0 status                 - Show all agents and stats"
            echo "  $0 test                   - Run self-tests"
            ;;
    esac
}

# Self-test function
test_confidence_scoring() {
    local test_cases=(
        "mobile layout is broken on iPhone|mobile-ux"
        "API returns 200 but data not saved|api-reliability"
        "schema migration failed|schema-guardian"
        "bundle size too large|performance"
        "XSS vulnerability found|security"
        "WCAG compliance check|accessibility"
        "update README with examples|documentation"
    )

    echo -e "${BOLD}Running confidence scoring tests...${NC}\n"

    for test_case in "${test_cases[@]}"; do
        local input=$(echo "$test_case" | cut -d'|' -f1)
        local expected=$(echo "$test_case" | cut -d'|' -f2)

        local result=$(find_best_agent "$input")
        local agent=$(echo "$result" | cut -d'|' -f1)
        local confidence=$(echo "$result" | cut -d'|' -f2)

        if [[ "$agent" == "$expected" ]]; then
            echo -e "✅ PASS: \"$input\" → $agent ($(printf "%.2f%%" $(echo "$confidence * 100" | bc)))"
        else
            echo -e "❌ FAIL: \"$input\" → $agent (expected: $expected)"
        fi
    done
}

# Run main function
main "$@"