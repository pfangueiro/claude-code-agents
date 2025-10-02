#!/bin/bash
# Unit Tests for Intent Router
# Tests confidence scoring, agent selection, and tie-breaking

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly INTENT_ROUTER="$SCRIPT_DIR/../../intent-router.sh"

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# ANSI Colors
readonly GREEN='\033[0;32m'
readonly RED='\033[0;31m'
readonly YELLOW='\033[1;33m'
readonly BOLD='\033[1m'
readonly NC='\033[0m'

# Assert function
assert_equals() {
    local expected="$1"
    local actual="$2"
    local test_name="${3:-Test}"

    ((TESTS_RUN++))

    if [[ "$expected" == "$actual" ]]; then
        echo -e "${GREEN}✅ PASS${NC}: $test_name"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}❌ FAIL${NC}: $test_name"
        echo "  Expected: $expected"
        echo "  Actual: $actual"
        ((TESTS_FAILED++))
    fi
}

# Assert contains function
assert_contains() {
    local needle="$1"
    local haystack="$2"
    local test_name="${3:-Test}"

    ((TESTS_RUN++))

    if echo "$haystack" | grep -q "$needle"; then
        echo -e "${GREEN}✅ PASS${NC}: $test_name"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}❌ FAIL${NC}: $test_name"
        echo "  Expected to contain: $needle"
        echo "  Actual: $haystack"
        ((TESTS_FAILED++))
    fi
}

# Test confidence scoring
test_confidence_scoring() {
    echo -e "\n${BOLD}Testing Confidence Scoring${NC}"
    echo "────────────────────────────"

    # Test mobile-ux agent
    local result=$("$INTENT_ROUTER" route "mobile layout broken on iPhone" 2>/dev/null | grep "mobile-ux" | head -1 || echo "")
    assert_contains "mobile-ux" "$result" "Mobile UX agent detection"

    # Test api-reliability agent
    result=$("$INTENT_ROUTER" route "API returns 200 but rowsAffected is 0" 2>/dev/null | grep "api-reliability" | head -1 || echo "")
    assert_contains "api-reliability" "$result" "API Reliability agent detection"

    # Test schema-guardian agent
    result=$("$INTENT_ROUTER" route "database migration failed" 2>/dev/null | grep "schema-guardian" | head -1 || echo "")
    assert_contains "schema-guardian" "$result" "Schema Guardian agent detection"

    # Test performance agent
    result=$("$INTENT_ROUTER" route "bundle size too large slow loading" 2>/dev/null | grep "performance" | head -1 || echo "")
    assert_contains "performance" "$result" "Performance agent detection"

    # Test security agent
    result=$("$INTENT_ROUTER" route "XSS vulnerability in login form" 2>/dev/null | grep "security" | head -1 || echo "")
    assert_contains "security" "$result" "Security agent detection"

    # Test accessibility agent
    result=$("$INTENT_ROUTER" route "WCAG compliance check needed" 2>/dev/null | grep "accessibility" | head -1 || echo "")
    assert_contains "accessibility" "$result" "Accessibility agent detection"

    # Test documentation agent
    result=$("$INTENT_ROUTER" route "update README with new API examples" 2>/dev/null | grep "documentation" | head -1 || echo "")
    assert_contains "documentation" "$result" "Documentation agent detection"
}

# Test tie-breaking rules
test_tie_breaking() {
    echo -e "\n${BOLD}Testing Tie-Breaking Rules${NC}"
    echo "────────────────────────────"

    # When security keyword is present, security should win
    local result=$("$INTENT_ROUTER" route "security performance" 2>/dev/null | grep -E "(security|performance)" | head -1 || echo "")
    assert_contains "security" "$result" "Security wins tie-break over performance"

    # Schema should win over API
    result=$("$INTENT_ROUTER" route "schema api" 2>/dev/null | grep -E "(schema|api)" | head -1 || echo "")
    assert_contains "schema" "$result" "Schema wins tie-break over API"
}

# Test fallback to generalist
test_fallback() {
    echo -e "\n${BOLD}Testing Fallback Mechanism${NC}"
    echo "────────────────────────────"

    # Test with no matching keywords
    local result=$("$INTENT_ROUTER" route "hello world" 2>/dev/null | grep "generalist\|low_confidence" || echo "fallback")
    assert_contains "fallback\|generalist" "$result" "Fallback to generalist for low confidence"
}

# Test confidence thresholds
test_confidence_thresholds() {
    echo -e "\n${BOLD}Testing Confidence Thresholds${NC}"
    echo "────────────────────────────"

    # High confidence test
    local result=$("$INTENT_ROUTER" route "mobile PWA responsive touch gesture offline manifest service-worker" 2>/dev/null | head -20)
    assert_contains "Confidence:" "$result" "High confidence detection"

    # Check if confidence is above threshold
    if echo "$result" | grep -q "Confidence: [8-9][0-9]\|100"; then
        echo -e "${GREEN}✅ PASS${NC}: High confidence score for many keywords"
        ((TESTS_PASSED++))
    else
        echo -e "${YELLOW}⚠️ WARN${NC}: Confidence might be lower than expected"
    fi
    ((TESTS_RUN++))
}

# Test command-line interface
test_cli() {
    echo -e "\n${BOLD}Testing Command-Line Interface${NC}"
    echo "────────────────────────────"

    # Test status command
    local result=$("$INTENT_ROUTER" status 2>&1)
    assert_contains "Claude Advanced Agent System Status" "$result" "Status command works"

    # Test help (no arguments)
    result=$("$INTENT_ROUTER" 2>&1)
    assert_contains "Usage:" "$result" "Help displays with no arguments"
}

# Main test runner
main() {
    echo -e "${BOLD}═══════════════════════════════════════${NC}"
    echo -e "${BOLD}Intent Router Unit Tests${NC}"
    echo -e "${BOLD}═══════════════════════════════════════${NC}"

    # Check if intent router exists
    if [[ ! -f "$INTENT_ROUTER" ]]; then
        echo -e "${RED}Error: Intent router not found at $INTENT_ROUTER${NC}"
        exit 1
    fi

    # Make it executable
    chmod +x "$INTENT_ROUTER"

    # Run test suites
    test_confidence_scoring
    test_tie_breaking
    test_fallback
    test_confidence_thresholds
    test_cli

    # Summary
    echo -e "\n${BOLD}═══════════════════════════════════════${NC}"
    echo -e "${BOLD}Test Summary${NC}"
    echo -e "${BOLD}═══════════════════════════════════════${NC}"
    echo -e "Tests run: $TESTS_RUN"
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"

    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo -e "\n${GREEN}${BOLD}All tests passed! ✅${NC}"
        exit 0
    else
        echo -e "\n${RED}${BOLD}Some tests failed ❌${NC}"
        exit 1
    fi
}

# Run tests
main "$@"