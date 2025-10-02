#!/bin/bash
# Agent Color System - Visual Identity and Terminal Aesthetics
# Follows ANSI best practices for accessibility and contrast

set -eo pipefail

# =====================================
# ANSI COLOR CODES - 256 Color Support
# =====================================

# Basic Colors (8-bit)
readonly BLACK='\033[0;30m'
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[0;33m'
readonly BLUE='\033[0;34m'
readonly MAGENTA='\033[0;35m'
readonly CYAN='\033[0;36m'
readonly WHITE='\033[0;37m'

# Bright Colors (High Intensity)
readonly BRIGHT_BLACK='\033[1;30m'
readonly BRIGHT_RED='\033[1;31m'
readonly BRIGHT_GREEN='\033[1;32m'
readonly BRIGHT_YELLOW='\033[1;33m'
readonly BRIGHT_BLUE='\033[1;34m'
readonly BRIGHT_MAGENTA='\033[1;35m'
readonly BRIGHT_CYAN='\033[1;36m'
readonly BRIGHT_WHITE='\033[1;37m'

# 256 Color Extended Palette
readonly ORANGE='\033[38;5;208m'      # Orange
readonly PURPLE='\033[38;5;141m'      # Light Purple
readonly PINK='\033[38;5;213m'        # Pink
readonly TEAL='\033[38;5;51m'         # Bright Teal
readonly LIME='\033[38;5;118m'        # Lime Green
readonly GOLD='\033[38;5;220m'        # Gold
readonly CORAL='\033[38;5;203m'       # Coral
readonly INDIGO='\033[38;5;63m'       # Deep Indigo
readonly EMERALD='\033[38;5;48m'      # Emerald Green
readonly RUBY='\033[38;5;196m'        # Ruby Red
readonly SAPPHIRE='\033[38;5;75m'     # Sapphire Blue
readonly AMBER='\033[38;5;214m'       # Amber

# Background Colors
readonly BG_BLACK='\033[40m'
readonly BG_RED='\033[41m'
readonly BG_GREEN='\033[42m'
readonly BG_YELLOW='\033[43m'
readonly BG_BLUE='\033[44m'
readonly BG_MAGENTA='\033[45m'
readonly BG_CYAN='\033[46m'
readonly BG_WHITE='\033[47m'

# Text Styles
readonly BOLD='\033[1m'
readonly DIM='\033[2m'
readonly ITALIC='\033[3m'
readonly UNDERLINE='\033[4m'
readonly BLINK='\033[5m'
readonly REVERSE='\033[7m'
readonly HIDDEN='\033[8m'
readonly STRIKETHROUGH='\033[9m'

# Reset
readonly NC='\033[0m'  # No Color/Reset

# =====================================
# AGENT COLOR IDENTITY SYSTEM
# =====================================

# Each agent has:
# - Primary color (main identity)
# - Secondary color (accents)
# - Icon/emoji
# - Style (bold, italic, etc.)

# 1. Mobile/PWA UX Agent - Purple/Pink gradient feel
readonly MOBILE_PRIMARY="${PURPLE}"
readonly MOBILE_SECONDARY="${PINK}"
readonly MOBILE_ICON="📱"
readonly MOBILE_STYLE="${BOLD}"
readonly MOBILE_NAME="Mobile/PWA UX"

# 2. API Reliability Agent - Orange/Amber for connectivity
readonly API_PRIMARY="${ORANGE}"
readonly API_SECONDARY="${AMBER}"
readonly API_ICON="🔌"
readonly API_STYLE="${BOLD}"
readonly API_NAME="API Reliability"

# 3. Schema Guardian Agent - Deep Indigo/Sapphire for structure
readonly SCHEMA_PRIMARY="${INDIGO}"
readonly SCHEMA_SECONDARY="${SAPPHIRE}"
readonly SCHEMA_ICON="🛡️"
readonly SCHEMA_STYLE="${BOLD}${UNDERLINE}"
readonly SCHEMA_NAME="Schema Guardian"

# 4. Performance Agent - Lime/Gold for speed
readonly PERF_PRIMARY="${LIME}"
readonly PERF_SECONDARY="${GOLD}"
readonly PERF_ICON="⚡"
readonly PERF_STYLE="${BOLD}"
readonly PERF_NAME="Performance"

# 5. Security Agent - Ruby Red for critical importance
readonly SECURITY_PRIMARY="${RUBY}"
readonly SECURITY_SECONDARY="${BRIGHT_RED}"
readonly SECURITY_ICON="🔒"
readonly SECURITY_STYLE="${BOLD}${BLINK}"  # Blink for critical
readonly SECURITY_NAME="Security"

# 6. Accessibility Agent - Teal/Cyan for inclusivity
readonly A11Y_PRIMARY="${TEAL}"
readonly A11Y_SECONDARY="${BRIGHT_CYAN}"
readonly A11Y_ICON="♿"
readonly A11Y_STYLE="${BOLD}"
readonly A11Y_NAME="Accessibility"

# 7. Documentation Agent - Emerald Green for knowledge
readonly DOCS_PRIMARY="${EMERALD}"
readonly DOCS_SECONDARY="${BRIGHT_GREEN}"
readonly DOCS_ICON="📚"
readonly DOCS_STYLE="${ITALIC}"
readonly DOCS_NAME="Documentation"

# Generalist/Fallback Agent - Neutral gray
readonly GENERAL_PRIMARY="${WHITE}"
readonly GENERAL_SECONDARY="${BRIGHT_WHITE}"
readonly GENERAL_ICON="🤖"
readonly GENERAL_STYLE="${DIM}"
readonly GENERAL_NAME="Generalist"

# =====================================
# COLOR UTILITY FUNCTIONS
# =====================================

# Get agent colors and styling
get_agent_colors() {
    local agent="$1"

    case "$agent" in
        mobile-ux)
            echo "${MOBILE_PRIMARY}|${MOBILE_SECONDARY}|${MOBILE_ICON}|${MOBILE_STYLE}|${MOBILE_NAME}"
            ;;
        api-reliability)
            echo "${API_PRIMARY}|${API_SECONDARY}|${API_ICON}|${API_STYLE}|${API_NAME}"
            ;;
        schema-guardian)
            echo "${SCHEMA_PRIMARY}|${SCHEMA_SECONDARY}|${SCHEMA_ICON}|${SCHEMA_STYLE}|${SCHEMA_NAME}"
            ;;
        performance)
            echo "${PERF_PRIMARY}|${PERF_SECONDARY}|${PERF_ICON}|${PERF_STYLE}|${PERF_NAME}"
            ;;
        security)
            echo "${SECURITY_PRIMARY}|${SECURITY_SECONDARY}|${SECURITY_ICON}|${SECURITY_STYLE}|${SECURITY_NAME}"
            ;;
        accessibility)
            echo "${A11Y_PRIMARY}|${A11Y_SECONDARY}|${A11Y_ICON}|${A11Y_STYLE}|${A11Y_NAME}"
            ;;
        documentation)
            echo "${DOCS_PRIMARY}|${DOCS_SECONDARY}|${DOCS_ICON}|${DOCS_STYLE}|${DOCS_NAME}"
            ;;
        generalist|*)
            echo "${GENERAL_PRIMARY}|${GENERAL_SECONDARY}|${GENERAL_ICON}|${GENERAL_STYLE}|${GENERAL_NAME}"
            ;;
    esac
}

# Print colored agent header
print_agent_header() {
    local agent="$1"
    local confidence="${2:-0}"

    local colors=$(get_agent_colors "$agent")
    local primary=$(echo "$colors" | cut -d'|' -f1)
    local secondary=$(echo "$colors" | cut -d'|' -f2)
    local icon=$(echo "$colors" | cut -d'|' -f3)
    local style=$(echo "$colors" | cut -d'|' -f4)
    local name=$(echo "$colors" | cut -d'|' -f5)

    # Print stylized header
    echo -e "${BOLD}${primary}╔════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${primary}║${NC} ${icon} ${style}${primary}${name} Agent${NC} ${BOLD}${primary}║${NC}"
    echo -e "${BOLD}${primary}╚════════════════════════════════════════╝${NC}"

    # Confidence bar
    print_confidence_bar "$confidence" "$secondary"
}

# Print visual confidence bar
print_confidence_bar() {
    local confidence="$1"
    local color="${2:-$GREEN}"

    # Convert to percentage
    local percentage=$(awk "BEGIN {printf \"%.0f\", $confidence * 100}")

    # Calculate bar length (max 40 chars)
    local bar_length=$(( percentage * 40 / 100 ))

    # Build the bar
    local bar=""
    for ((i=0; i<bar_length; i++)); do
        bar="${bar}█"
    done

    # Fill remaining space
    local remaining=$((40 - bar_length))
    for ((i=0; i<remaining; i++)); do
        bar="${bar}░"
    done

    # Color based on confidence level
    local bar_color
    if [[ $percentage -ge 80 ]]; then
        bar_color="${BRIGHT_GREEN}"
    elif [[ $percentage -ge 60 ]]; then
        bar_color="${YELLOW}"
    elif [[ $percentage -ge 40 ]]; then
        bar_color="${ORANGE}"
    else
        bar_color="${RED}"
    fi

    echo -e "Confidence: ${bar_color}${bar}${NC} ${BOLD}${percentage}%${NC}"
}

# Print colored status message
print_status() {
    local level="$1"  # info, success, warning, error, critical
    local message="$2"

    case "$level" in
        info)
            echo -e "${CYAN}ℹ${NC} ${message}"
            ;;
        success)
            echo -e "${GREEN}✅${NC} ${message}"
            ;;
        warning)
            echo -e "${YELLOW}⚠️${NC} ${message}"
            ;;
        error)
            echo -e "${RED}❌${NC} ${message}"
            ;;
        critical)
            echo -e "${BLINK}${BG_RED}${WHITE}🚨 CRITICAL${NC} ${BRIGHT_RED}${message}${NC}"
            ;;
        *)
            echo "$message"
            ;;
    esac
}

# Check if terminal supports colors
supports_colors() {
    # Check for various color support indicators
    if [[ -n "${TERM}" ]] && [[ "${TERM}" != "dumb" ]]; then
        # Check for COLORTERM (24-bit color indicator)
        if [[ -n "${COLORTERM}" ]]; then
            echo "24bit"
            return 0
        fi

        # Check term capabilities
        if command -v tput &>/dev/null; then
            local colors=$(tput colors 2>/dev/null || echo 0)
            if [[ $colors -ge 256 ]]; then
                echo "256"
                return 0
            elif [[ $colors -ge 8 ]]; then
                echo "8"
                return 0
            fi
        fi

        # Basic ANSI support
        case "${TERM}" in
            *256color*|*truecolor*)
                echo "256"
                return 0
                ;;
            *color*)
                echo "8"
                return 0
                ;;
        esac

        # Default to 256 colors for modern terminals
        echo "256"
        return 0
    fi

    # No color support
    echo "none"
    return 1
}

# Apply accessibility mode (high contrast, no animations)
apply_accessibility_mode() {
    local enable="${1:-false}"

    if [[ "$enable" == "true" ]]; then
        # Override with high contrast colors only
        readonly MOBILE_PRIMARY="${BRIGHT_MAGENTA}"
        readonly API_PRIMARY="${BRIGHT_YELLOW}"
        readonly SCHEMA_PRIMARY="${BRIGHT_BLUE}"
        readonly PERF_PRIMARY="${BRIGHT_GREEN}"
        readonly SECURITY_PRIMARY="${BRIGHT_RED}"
        readonly A11Y_PRIMARY="${BRIGHT_CYAN}"
        readonly DOCS_PRIMARY="${BRIGHT_WHITE}"

        # Disable animations
        readonly BLINK=""
        readonly DIM=""
    fi
}

# Print color palette demo
show_color_palette() {
    echo -e "${BOLD}Agent Color Palette${NC}"
    echo -e "${BOLD}═══════════════════════════════════════${NC}"
    echo ""

    local agents=("mobile-ux" "api-reliability" "schema-guardian" "performance" "security" "accessibility" "documentation")

    for agent in "${agents[@]}"; do
        local colors=$(get_agent_colors "$agent")
        local primary=$(echo "$colors" | cut -d'|' -f1)
        local secondary=$(echo "$colors" | cut -d'|' -f2)
        local icon=$(echo "$colors" | cut -d'|' -f3)
        local style=$(echo "$colors" | cut -d'|' -f4)
        local name=$(echo "$colors" | cut -d'|' -f5)

        echo -e "${icon} ${style}${primary}${name}${NC}"
        echo -e "   Primary: ${primary}████████${NC} Secondary: ${secondary}████████${NC}"
        echo ""
    done

    echo -e "${BOLD}Text Styles:${NC}"
    echo -e "  ${BOLD}Bold${NC} | ${ITALIC}Italic${NC} | ${UNDERLINE}Underline${NC} | ${STRIKETHROUGH}Strikethrough${NC}"
    echo ""
    echo -e "${BOLD}Status Indicators:${NC}"
    print_status "info" "Information message"
    print_status "success" "Success message"
    print_status "warning" "Warning message"
    print_status "error" "Error message"
    print_status "critical" "Critical message"
}

# Export functions
export -f get_agent_colors
export -f print_agent_header
export -f print_confidence_bar
export -f print_status
export -f supports_colors
export -f apply_accessibility_mode
export -f show_color_palette

# Self-test when run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo -e "${BOLD}${CYAN}Color System Test${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}"
    echo ""

    # Check color support
    echo -n "Terminal color support: "
    color_support=$(supports_colors)
    case "$color_support" in
        24bit)
            echo -e "${GREEN}24-bit (16.7M colors)${NC}"
            ;;
        256)
            echo -e "${GREEN}256 colors${NC}"
            ;;
        8)
            echo -e "${YELLOW}8 colors (basic)${NC}"
            ;;
        none)
            echo -e "No color support detected"
            ;;
    esac
    echo ""

    # Show palette
    show_color_palette

    echo ""
    echo -e "${BOLD}Sample Agent Headers:${NC}"
    echo ""

    # Demo each agent header
    print_agent_header "security" "0.95"
    echo ""
    print_agent_header "mobile-ux" "0.75"
    echo ""
    print_agent_header "performance" "0.60"
    echo ""

    echo -e "${GREEN}✅ Color system ready!${NC}"
fi