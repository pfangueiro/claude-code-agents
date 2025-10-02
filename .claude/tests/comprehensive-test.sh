#!/bin/bash
# Comprehensive Test Suite for Claude Agent System
# Tests all components: security, performance, routing, agents

set -eo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly CLAUDE_DIR="$(dirname "$SCRIPT_DIR")"
readonly LIB_DIR="$CLAUDE_DIR/lib"
readonly AGENTS_DIR="$CLAUDE_DIR/agents"
readonly TELEMETRY_DIR="$CLAUDE_DIR/telemetry"

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

# ANSI Colors
readonly GREEN='\033[0;32m'
readonly RED='\033[0;31m'
readonly YELLOW='\033[1;33m'
readonly CYAN='\033[0;36m'
readonly BOLD='\033[1m'
readonly NC='\033[0m'

# Test result tracking
declare -a FAILED_TESTS=()

# Assert functions
assert_equals() {
    local expected="$1"
    local actual="$2"
    local test_name="${3:-Test}"

    ((TESTS_RUN++))

    if [[ "$expected" == "$actual" ]]; then
        echo -e "  ${GREEN}✅${NC} $test_name"
        ((TESTS_PASSED++))
    else
        echo -e "  ${RED}❌${NC} $test_name"
        echo -e "     Expected: $expected"
        echo -e "     Actual: $actual"
        ((TESTS_FAILED++))
        FAILED_TESTS+=("$test_name")
    fi
}

assert_contains() {
    local needle="$1"
    local haystack="$2"
    local test_name="${3:-Test}"

    ((TESTS_RUN++))

    if echo "$haystack" | grep -q "$needle"; then
        echo -e "  ${GREEN}✅${NC} $test_name"
        ((TESTS_PASSED++))
    else
        echo -e "  ${RED}❌${NC} $test_name"
        echo -e "     Expected to contain: $needle"
        ((TESTS_FAILED++))
        FAILED_TESTS+=("$test_name")
    fi
}

assert_true() {
    local condition="$1"
    local test_name="${2:-Test}"

    ((TESTS_RUN++))

    if [[ "$condition" == "true" ]] || [[ "$condition" == "0" ]]; then
        echo -e "  ${GREEN}✅${NC} $test_name"
        ((TESTS_PASSED++))
    else
        echo -e "  ${RED}❌${NC} $test_name"
        ((TESTS_FAILED++))
        FAILED_TESTS+=("$test_name")
    fi
}

assert_file_exists() {
    local file="$1"
    local test_name="${2:-File exists}"

    ((TESTS_RUN++))

    if [[ -f "$file" ]]; then
        echo -e "  ${GREEN}✅${NC} $test_name"
        ((TESTS_PASSED++))
    else
        echo -e "  ${RED}❌${NC} $test_name: $file not found"
        ((TESTS_FAILED++))
        FAILED_TESTS+=("$test_name")
    fi
}

# Test security library
test_security() {
    echo -e "\n${BOLD}${CYAN}Testing Security Library${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━"

    if [[ ! -f "$LIB_DIR/security.sh" ]]; then
        echo -e "  ${YELLOW}⚠️${NC} Security library not found - skipping"
        ((TESTS_SKIPPED++))
        return
    fi

    source "$LIB_DIR/security.sh"

    # Test input sanitization
    local dangerous_input='echo "test"; rm -rf /'
    local sanitized=$(sanitize_input "$dangerous_input")
    assert_equals "echo test rm -rf /" "$sanitized" "Command injection prevention"

    # Test validation
    local result=0
    validate_safe_input 'test $(whoami)' 2>/dev/null || result=$?
    assert_equals "1" "$result" "Dangerous pattern detection"

    # Test secret redaction
    local text="api_key=sk-1234567890abcdefghij password=secret123"
    local redacted=$(redact_secrets "$text")
    assert_contains "[REDACTED]" "$redacted" "API key redaction"
    assert_true "[[ '$redacted' != *'secret123'* ]]" "Password redaction"

    # Test path validation
    result=0
    validate_project_path "../../../etc/passwd" "$CLAUDE_DIR" 2>/dev/null || result=$?
    assert_equals "1" "$result" "Path traversal prevention"
}

# Test performance utilities
test_performance() {
    echo -e "\n${BOLD}${CYAN}Testing Performance Utilities${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [[ ! -f "$LIB_DIR/performance-utils.sh" ]]; then
        echo -e "  ${YELLOW}⚠️${NC} Performance utilities not found - skipping"
        ((TESTS_SKIPPED++))
        return
    fi

    source "$LIB_DIR/performance-utils.sh"

    # Test fast keyword matching
    local text="mobile responsive pwa offline"
    local pattern="mobile|pwa|responsive|touch"
    local count=$(fast_keyword_match "$text" "$pattern")
    assert_equals "3" "$count" "Fast keyword matching"

    # Test fast lowercase
    local result=$(fast_lowercase "HELLO World")
    assert_equals "hello world" "$result" "Fast lowercase conversion"

    # Test fast split
    result=$(fast_split "one|two|three" "|" 2)
    assert_equals "two" "$result" "Fast string splitting"

    # Test keyword cache
    load_keyword_cache
    assert_equals "true" "$KEYWORD_CACHE_LOADED" "Keyword cache loading"
}

# Test fuzzy matching
test_fuzzy_matching() {
    echo -e "\n${BOLD}${CYAN}Testing Fuzzy Matching${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━"

    if [[ ! -f "$LIB_DIR/fuzzy-match.sh" ]]; then
        echo -e "  ${YELLOW}⚠️${NC} Fuzzy matching library not found - skipping"
        ((TESTS_SKIPPED++))
        return
    fi

    source "$LIB_DIR/fuzzy-match.sh"

    # Test Levenshtein distance
    local distance=$(levenshtein_distance "mobile" "mobil")
    assert_equals "1" "$distance" "Levenshtein distance calculation"

    # Test fuzzy match
    local result=$(fuzzy_match "securty" "security" 2)
    local is_match=$(echo "$result" | cut -d'|' -f1)
    assert_equals "true" "$is_match" "Fuzzy match detection"

    # Test keyword expansion
    local expanded=$(expand_keywords "mobile")
    assert_contains "mobil" "$expanded" "Typo expansion"

    # Test semantic expansion
    expanded=$(semantic_expand "slow")
    assert_contains "sluggish" "$expanded" "Semantic expansion"
}

# Test adaptive confidence
test_adaptive_confidence() {
    echo -e "\n${BOLD}${CYAN}Testing Adaptive Confidence${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [[ ! -f "$LIB_DIR/adaptive-confidence.sh" ]]; then
        echo -e "  ${YELLOW}⚠️${NC} Adaptive confidence library not found - skipping"
        ((TESTS_SKIPPED++))
        return
    fi

    source "$LIB_DIR/adaptive-confidence.sh"

    # Test initialization
    init_learning_data
    assert_file_exists "$TELEMETRY_DIR/learning.json" "Learning data initialization"

    # Test threshold retrieval
    local threshold=$(get_adaptive_threshold "security" "0.5")
    assert_true "[[ -n '$threshold' ]]" "Threshold retrieval"

    # Test learning update
    update_learning "security" "0.75" "success"
    assert_equals "0" "$?" "Learning update"
}

# Test intent router
test_intent_router() {
    echo -e "\n${BOLD}${CYAN}Testing Intent Router${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━"

    if [[ ! -f "$CLAUDE_DIR/intent-router.sh" ]]; then
        echo -e "  ${YELLOW}⚠️${NC} Intent router not found - skipping"
        ((TESTS_SKIPPED++))
        return
    fi

    # Test routing for each agent
    local test_cases=(
        "mobile layout broken iPhone|mobile-ux"
        "API returns 200 but data not saved|api-reliability"
        "database migration failed|schema-guardian"
        "bundle size too large|performance"
        "XSS vulnerability found|security"
        "WCAG compliance check|accessibility"
        "update README with examples|documentation"
    )

    for test_case in "${test_cases[@]}"; do
        local input="${test_case%|*}"
        local expected="${test_case#*|}"

        local result=$("$CLAUDE_DIR/intent-router.sh" route "$input" 2>/dev/null | tail -1)
        local agent="${result%|*}"

        assert_equals "$expected" "$agent" "Route: $input → $expected"
    done
}

# Test agent definitions
test_agent_definitions() {
    echo -e "\n${BOLD}${CYAN}Testing Agent Definitions${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━"

    local agents=(
        "mobile-ux.md"
        "api-reliability.md"
        "schema-guardian.md"
        "performance.md"
        "security.md"
        "accessibility.md"
        "documentation.md"
    )

    for agent_file in "${agents[@]}"; do
        assert_file_exists "$AGENTS_DIR/$agent_file" "Agent definition: $agent_file"

        if [[ -f "$AGENTS_DIR/$agent_file" ]]; then
            # Check for required sections
            local content=$(cat "$AGENTS_DIR/$agent_file")
            assert_contains "## Mission" "$content" "$agent_file has Mission section"
            assert_contains "## Capabilities" "$content" "$agent_file has Capabilities section"
            assert_contains "## Model Selection" "$content" "$agent_file has Model Selection"
        fi
    done
}

# Test commands interface
test_commands() {
    echo -e "\n${BOLD}${CYAN}Testing Commands Interface${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [[ ! -f "$CLAUDE_DIR/commands.sh" ]]; then
        echo -e "  ${YELLOW}⚠️${NC} Commands interface not found - skipping"
        ((TESTS_SKIPPED++))
        return
    fi

    # Test help command
    local result=$("$CLAUDE_DIR/commands.sh" help 2>&1)
    assert_contains "Claude Agent Commands" "$result" "Help command"

    # Test status command
    result=$("$CLAUDE_DIR/intent-router.sh" status 2>&1)
    assert_contains "Claude Advanced Agent System Status" "$result" "Status command"
}

# Test telemetry
test_telemetry() {
    echo -e "\n${BOLD}${CYAN}Testing Telemetry System${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━"

    # Check telemetry directory
    assert_true "[[ -d '$TELEMETRY_DIR' ]]" "Telemetry directory exists"

    # Simulate an event
    "$CLAUDE_DIR/intent-router.sh" route "test mobile app" &>/dev/null || true

    # Check if event was logged
    if [[ -f "$TELEMETRY_DIR/events.jsonl" ]]; then
        local events=$(wc -l < "$TELEMETRY_DIR/events.jsonl")
        assert_true "[[ $events -gt 0 ]]" "Events are being logged"
    else
        echo -e "  ${YELLOW}⚠️${NC} No events logged yet"
    fi
}

# Performance benchmark
run_performance_benchmark() {
    echo -e "\n${BOLD}${CYAN}Performance Benchmark${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━"

    local iterations=10
    local total_time=0

    echo -e "  Running $iterations iterations..."

    for i in $(seq 1 $iterations); do
        local start_time=$(date +%s%N)
        "$CLAUDE_DIR/intent-router.sh" route "mobile responsive PWA offline" &>/dev/null
        local end_time=$(date +%s%N)
        local elapsed=$(( ($end_time - $start_time) / 1000000 ))
        ((total_time += elapsed))
        echo -n "."
    done
    echo ""

    local avg_time=$(( total_time / iterations ))
    echo -e "  Average response time: ${BOLD}${avg_time}ms${NC}"

    if [[ $avg_time -lt 50 ]]; then
        echo -e "  ${GREEN}✅ Excellent performance (<50ms)${NC}"
    elif [[ $avg_time -lt 100 ]]; then
        echo -e "  ${GREEN}✅ Good performance (<100ms)${NC}"
    elif [[ $avg_time -lt 150 ]]; then
        echo -e "  ${YELLOW}⚠️ Acceptable performance (<150ms)${NC}"
    else
        echo -e "  ${RED}❌ Poor performance (>150ms)${NC}"
    fi
}

# Generate test report
generate_test_report() {
    local report_file="$CLAUDE_DIR/tests/test_report_$(date +%Y%m%d_%H%M%S).txt"

    {
        echo "Claude Agent System Test Report"
        echo "Generated: $(date)"
        echo "================================"
        echo ""
        echo "Test Summary:"
        echo "  Total Tests: $TESTS_RUN"
        echo "  Passed: $TESTS_PASSED"
        echo "  Failed: $TESTS_FAILED"
        echo "  Skipped: $TESTS_SKIPPED"
        echo ""

        if [[ ${#FAILED_TESTS[@]} -gt 0 ]]; then
            echo "Failed Tests:"
            for test in "${FAILED_TESTS[@]}"; do
                echo "  • $test"
            done
            echo ""
        fi

        echo "Component Status:"
        echo "  Security Library: $([ -f "$LIB_DIR/security.sh" ] && echo "✓" || echo "✗")"
        echo "  Performance Utils: $([ -f "$LIB_DIR/performance-utils.sh" ] && echo "✓" || echo "✗")"
        echo "  Fuzzy Matching: $([ -f "$LIB_DIR/fuzzy-match.sh" ] && echo "✓" || echo "✗")"
        echo "  Adaptive Confidence: $([ -f "$LIB_DIR/adaptive-confidence.sh" ] && echo "✓" || echo "✗")"
        echo "  Intent Router: $([ -f "$CLAUDE_DIR/intent-router.sh" ] && echo "✓" || echo "✗")"
        echo "  Commands Interface: $([ -f "$CLAUDE_DIR/commands.sh" ] && echo "✓" || echo "✗")"
        echo ""

        echo "System Health:"
        if [[ $TESTS_FAILED -eq 0 ]]; then
            echo "  Status: ✅ All systems operational"
        elif [[ $TESTS_FAILED -lt 5 ]]; then
            echo "  Status: ⚠️ Minor issues detected"
        else
            echo "  Status: ❌ Critical issues found"
        fi

    } > "$report_file"

    echo -e "\n${BOLD}Test report saved to: $report_file${NC}"
}

# Main test runner
main() {
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════${NC}"
    echo -e "${BOLD}${CYAN}   Claude Agent System Test Suite${NC}"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════${NC}"

    # Create test environment
    mkdir -p "$CLAUDE_DIR/tests"
    mkdir -p "$TELEMETRY_DIR"

    # Run all test suites
    test_security
    test_performance
    test_fuzzy_matching
    test_adaptive_confidence
    test_intent_router
    test_agent_definitions
    test_commands
    test_telemetry

    # Run performance benchmark
    run_performance_benchmark

    # Display summary
    echo -e "\n${BOLD}${CYAN}═══════════════════════════════════════${NC}"
    echo -e "${BOLD}Test Summary${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "Total Tests: ${BOLD}$TESTS_RUN${NC}"
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    echo -e "${YELLOW}Skipped: $TESTS_SKIPPED${NC}"

    local pass_rate=0
    if [[ $TESTS_RUN -gt 0 ]]; then
        pass_rate=$(( (TESTS_PASSED * 100) / TESTS_RUN ))
    fi
    echo -e "Pass Rate: ${BOLD}${pass_rate}%${NC}"

    # Generate report
    generate_test_report

    # Exit status
    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo -e "\n${GREEN}${BOLD}✅ All tests passed!${NC}"
        exit 0
    else
        echo -e "\n${RED}${BOLD}❌ Some tests failed${NC}"
        exit 1
    fi
}

# Run tests
main "$@"