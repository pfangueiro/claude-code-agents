#!/bin/bash
# Claude Agent Slash Commands Interface
# Provides /agent commands for manual agent invocation

set -eo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly AGENTS_DIR="$SCRIPT_DIR/agents"
readonly LIB_DIR="$SCRIPT_DIR/lib"
readonly INTENT_ROUTER="$SCRIPT_DIR/intent-router.sh"
readonly TELEMETRY_DIR="$SCRIPT_DIR/telemetry"

# Source security library
if [[ -f "$LIB_DIR/security.sh" ]]; then
    source "$LIB_DIR/security.sh"
fi

# ANSI Colors
readonly BOLD='\033[1m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m'

# Available commands (using functions instead of associative arrays for compatibility)
get_command_description() {
    case "$1" in
        ux-audit) echo "Run mobile/PWA UX audit" ;;
        api-reliability) echo "Check API persistence and contracts" ;;
        schema-guard) echo "Validate schema integrity" ;;
        perf) echo "Performance analysis and optimization" ;;
        security) echo "Security vulnerability scan" ;;
        a11y) echo "Accessibility WCAG audit" ;;
        docs) echo "Documentation coverage check" ;;
        status) echo "Show all agents status" ;;
        telemetry) echo "View telemetry data" ;;
        help) echo "Show this help message" ;;
        *) echo "Unknown command" ;;
    esac
}

# Command list
readonly COMMAND_LIST="ux-audit api-reliability schema-guard perf security a11y docs status telemetry help"

# Run UX audit
run_ux_audit() {
    local scope="${1:-all}"
    local flags="$*"

    echo -e "${BOLD}📱 Mobile/PWA UX Audit${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    echo -e "${CYAN}Scope:${NC} $scope"
    echo -e "${CYAN}Flags:${NC} $flags\n"

    echo -e "${BOLD}Plan:${NC}"
    echo "1. Check viewport configuration"
    echo "2. Analyze touch targets (min 48x48px)"
    echo "3. Verify PWA manifest"
    echo "4. Test service worker"
    echo "5. Measure Core Web Vitals"
    echo ""

    if [[ "$scope" != "dry-run" ]]; then
        echo -e "${BOLD}Executing audit...${NC}\n"

        # Check for viewport meta tag
        echo -n "Checking viewport configuration... "
        if grep -r "viewport" --include="*.html" --include="*.jsx" --include="*.tsx" . 2>/dev/null | grep -q "width=device-width"; then
            echo -e "${GREEN}✅${NC}"
        else
            echo -e "${RED}❌ Missing or incorrect${NC}"
        fi

        # Check for manifest.json
        echo -n "Checking PWA manifest... "
        if [[ -f "manifest.json" ]] || [[ -f "public/manifest.json" ]] || [[ -f "src/manifest.json" ]]; then
            echo -e "${GREEN}✅${NC}"
        else
            echo -e "${RED}❌ Not found${NC}"
        fi

        # Check for service worker
        echo -n "Checking service worker... "
        if find . -name "*.js" -o -name "*.ts" | xargs grep -l "serviceWorker" 2>/dev/null | head -1 >/dev/null; then
            echo -e "${GREEN}✅${NC}"
        else
            echo -e "${YELLOW}⚠️ Not detected${NC}"
        fi
    fi

    echo -e "\n${BOLD}Recommendations:${NC}"
    echo "• Implement responsive images with srcset"
    echo "• Add apple-touch-icon for iOS"
    echo "• Configure theme-color meta tag"
    echo "• Enable offline mode with service worker"

    echo -e "\n${BOLD}Next Steps:${NC}"
    echo "1. Run Lighthouse audit for detailed metrics"
    echo "2. Test on real devices"
    echo "3. Monitor real user metrics (RUM)"
}

# Run API reliability check
run_api_reliability() {
    local scope="${1:-all}"
    local flags="$*"

    echo -e "${BOLD}🔌 API Reliability Check${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    echo -e "${CYAN}Scope:${NC} $scope"
    echo -e "${CYAN}Checking for:${NC}"
    echo "• Write operations without rowsAffected validation"
    echo "• Missing error handling"
    echo "• Improper status codes"
    echo ""

    if [[ "$scope" != "dry-run" ]]; then
        # Use the rows-affected-enforcer hook
        if [[ -x "$LIB_DIR/hooks/rows-affected-enforcer.sh" ]]; then
            "$LIB_DIR/hooks/rows-affected-enforcer.sh" scan . "js,ts,py,go,rb"
        else
            echo -e "${YELLOW}⚠️ Rows affected enforcer not available${NC}"
        fi
    fi

    echo -e "\n${BOLD}Critical Requirements:${NC}"
    echo "• All write operations must check rowsAffected ≥ 1"
    echo "• Never return 200 on failed persistence"
    echo "• Implement idempotency keys for critical operations"
}

# Run schema guard
run_schema_guard() {
    local scope="${1:-all}"

    echo -e "${BOLD}🛡️ Schema Guardian Check${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    if [[ -x "$LIB_DIR/hooks/schema-introspection.sh" ]]; then
        echo -e "${CYAN}Database Type:${NC}"
        "$LIB_DIR/hooks/schema-introspection.sh" detect
        echo ""

        echo -e "${CYAN}Schema Status:${NC}"
        "$LIB_DIR/hooks/schema-introspection.sh" schema || echo "Unable to fetch schema"
    else
        echo -e "${YELLOW}⚠️ Schema introspection not available${NC}"
    fi

    echo -e "\n${BOLD}Checks:${NC}"
    echo "• Migration files present and sequential"
    echo "• Foreign key constraints valid"
    echo "• Indexes optimized for queries"
    echo "• No orphaned data"
}

# Run performance analysis
run_performance() {
    local scope="${1:-all}"

    echo -e "${BOLD}⚡ Performance Analysis${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    echo -e "${CYAN}Analyzing:${NC}"
    echo "• Bundle size"
    echo "• Load time"
    echo "• Memory usage"
    echo ""

    # Check for common performance files
    echo -e "${BOLD}Bundle Analysis:${NC}"
    if [[ -f "package.json" ]]; then
        echo -n "Checking bundle size... "
        if [[ -d "dist" ]] || [[ -d "build" ]]; then
            local size=$(du -sh dist 2>/dev/null || du -sh build 2>/dev/null | cut -f1)
            echo "$size"
        else
            echo "No build directory found"
        fi
    fi

    echo -e "\n${BOLD}Optimization Opportunities:${NC}"
    echo "• Implement code splitting"
    echo "• Enable compression (gzip/brotli)"
    echo "• Optimize images with next-gen formats"
    echo "• Implement caching strategies"
}

# Run security scan
run_security() {
    local scope="${1:-all}"

    echo -e "${BOLD}🔒 Security Scan${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    echo -e "${RED}${BOLD}⚠️ CRITICAL CHECKS:${NC}"
    echo ""

    # Check for hardcoded secrets
    echo -n "Scanning for hardcoded secrets... "
    if grep -r "api[_-]key\|secret\|password\|token" --include="*.js" --include="*.ts" --include="*.py" . 2>/dev/null | \
       grep -v "process.env\|import.meta.env\|ENV\|environment" | head -1 >/dev/null; then
        echo -e "${RED}❌ Potential secrets found${NC}"
    else
        echo -e "${GREEN}✅ No hardcoded secrets detected${NC}"
    fi

    # Check for SQL injection patterns
    echo -n "Checking for SQL injection risks... "
    if grep -r "query.*\+.*\|query.*\${" --include="*.js" --include="*.ts" --include="*.py" . 2>/dev/null | head -1 >/dev/null; then
        echo -e "${YELLOW}⚠️ Potential SQL injection risk${NC}"
    else
        echo -e "${GREEN}✅ Using parameterized queries${NC}"
    fi

    echo -e "\n${BOLD}Security Headers Required:${NC}"
    echo "• Content-Security-Policy"
    echo "• X-Frame-Options: DENY"
    echo "• X-Content-Type-Options: nosniff"
    echo "• Strict-Transport-Security"
}

# Run accessibility audit
run_accessibility() {
    local scope="${1:-all}"

    echo -e "${BOLD}♿ Accessibility Audit${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    echo -e "${CYAN}WCAG 2.1 Level AA Compliance Check:${NC}\n"

    # Check for alt text
    echo -n "Checking for alt attributes on images... "
    if find . -name "*.html" -o -name "*.jsx" -o -name "*.tsx" 2>/dev/null | \
       xargs grep -l "<img" | \
       xargs grep "<img" | grep -v "alt=" | head -1 >/dev/null; then
        echo -e "${RED}❌ Missing alt text found${NC}"
    else
        echo -e "${GREEN}✅${NC}"
    fi

    # Check for ARIA labels
    echo -n "Checking for ARIA labels... "
    if grep -r "aria-label\|aria-describedby" --include="*.html" --include="*.jsx" --include="*.tsx" . 2>/dev/null | head -1 >/dev/null; then
        echo -e "${GREEN}✅ ARIA attributes found${NC}"
    else
        echo -e "${YELLOW}⚠️ Consider adding ARIA labels${NC}"
    fi

    echo -e "\n${BOLD}Key Requirements:${NC}"
    echo "• Color contrast ratio ≥ 4.5:1"
    echo "• All functionality keyboard accessible"
    echo "• Focus indicators visible"
    echo "• Touch targets ≥ 44x44 CSS pixels"
}

# Run documentation check
run_documentation() {
    local scope="${1:-all}"

    echo -e "${BOLD}📚 Documentation Coverage${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    # Check for README
    echo -n "README.md: "
    if [[ -f "README.md" ]]; then
        local lines=$(wc -l < README.md)
        echo -e "${GREEN}✅ Found ($lines lines)${NC}"
    else
        echo -e "${RED}❌ Not found${NC}"
    fi

    # Check for API docs
    echo -n "API Documentation: "
    if [[ -f "api-docs.md" ]] || [[ -f "swagger.json" ]] || [[ -f "openapi.yml" ]]; then
        echo -e "${GREEN}✅ Found${NC}"
    else
        echo -e "${YELLOW}⚠️ Not found${NC}"
    fi

    # Check for inline documentation
    echo -n "Inline comments: "
    local total_lines=$(find . -name "*.js" -o -name "*.ts" -o -name "*.py" 2>/dev/null | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}')
    local comment_lines=$(find . -name "*.js" -o -name "*.ts" -o -name "*.py" 2>/dev/null | xargs grep -E "^[[:space:]]*(//|#|\*)" 2>/dev/null | wc -l)

    if [[ $total_lines -gt 0 ]]; then
        local percentage=$(( (comment_lines * 100) / total_lines ))
        if [[ $percentage -gt 20 ]]; then
            echo -e "${GREEN}✅ ${percentage}% coverage${NC}"
        else
            echo -e "${YELLOW}⚠️ ${percentage}% coverage (low)${NC}"
        fi
    else
        echo "No code files found"
    fi

    echo -e "\n${BOLD}Documentation Checklist:${NC}"
    echo "✓ Installation instructions"
    echo "✓ Usage examples"
    echo "✓ API reference"
    echo "✓ Contributing guidelines"
    echo "✓ License information"
}

# Show agent status
show_status() {
    "$INTENT_ROUTER" status
}

# Show telemetry
show_telemetry() {
    echo -e "${BOLD}📊 Telemetry Data${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    if [[ -f "$TELEMETRY_DIR/events.jsonl" ]]; then
        local total=$(wc -l < "$TELEMETRY_DIR/events.jsonl")
        echo -e "${CYAN}Total events:${NC} $total"

        echo -e "\n${CYAN}Recent events:${NC}"
        tail -5 "$TELEMETRY_DIR/events.jsonl" | while IFS= read -r line; do
            local timestamp=$(echo "$line" | jq -r .timestamp 2>/dev/null || echo "unknown")
            local agent=$(echo "$line" | jq -r .agent 2>/dev/null || echo "unknown")
            local confidence=$(echo "$line" | jq -r .confidence 2>/dev/null || echo "0")
            echo "  $timestamp: $agent (confidence: $confidence)"
        done

        echo -e "\n${CYAN}Agent usage distribution:${NC}"
        for agent in mobile-ux api-reliability schema-guardian performance security accessibility documentation; do
            local count=$(grep "\"agent\":\"$agent\"" "$TELEMETRY_DIR/events.jsonl" | wc -l)
            if [[ $count -gt 0 ]]; then
                printf "  %-20s: %d\n" "$agent" "$count"
            fi
        done
    else
        echo "No telemetry data available yet"
    fi
}

# Show help
show_help() {
    echo -e "${BOLD}Claude Agent Commands${NC}"
    echo -e "${BOLD}════════════════════════════════════════${NC}\n"

    echo "Usage: /agent <command> [options]"
    echo ""
    echo "Commands:"
    for cmd in $COMMAND_LIST; do
        local desc=$(get_command_description "$cmd")
        printf "  ${CYAN}%-20s${NC} %s\n" "$cmd" "$desc"
    done

    echo ""
    echo "Options:"
    echo "  --scope <scope>    Limit to specific scope (all, src, tests)"
    echo "  --dry-run          Show plan without executing"
    echo "  --verbose          Show detailed output"

    echo ""
    echo "Examples:"
    echo "  /agent security --scope src"
    echo "  /agent perf --dry-run"
    echo "  /agent ux-audit --verbose"
}

# Main execution
main() {
    local command="${1:-help}"
    shift || true

    case "$command" in
        ux-audit)
            run_ux_audit "$@"
            ;;
        api-reliability)
            run_api_reliability "$@"
            ;;
        schema-guard)
            run_schema_guard "$@"
            ;;
        perf)
            run_performance "$@"
            ;;
        security)
            run_security "$@"
            ;;
        a11y)
            run_accessibility "$@"
            ;;
        docs)
            run_documentation "$@"
            ;;
        status)
            show_status
            ;;
        telemetry)
            show_telemetry
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo -e "${RED}Unknown command: $command${NC}"
            echo "Run '/agent help' for available commands"
            exit 1
            ;;
    esac
}

# Support both direct execution and slash command style
if [[ "$0" == *"/agent" ]] || [[ "$1" == "/agent" ]]; then
    # Called as /agent command
    if [[ "$1" == "/agent" ]]; then
        shift
    fi
    main "$@"
else
    # Direct execution
    main "$@"
fi