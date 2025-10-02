#!/bin/bash
# Demonstrate all agent colors

set -eo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "\033[1m\033[38;5;220m"
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           CLAUDE ADVANCED AGENT COLOR SHOWCASE                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo -e "\033[0m"

echo "Testing all 7 agents with their unique color identities..."
echo ""

# Test each agent
test_cases=(
    "mobile responsive PWA offline support needed|Mobile/PWA UX"
    "API returns 200 but rowsAffected shows zero|API Reliability"
    "database schema migration failed|Schema Guardian"
    "performance optimization bundle too slow|Performance"
    "XSS vulnerability security issue found|Security"
    "WCAG accessibility screen reader problems|Accessibility"
    "document README update with examples|Documentation"
)

for test_case in "${test_cases[@]}"; do
    input="${test_case%|*}"
    expected="${test_case#*|}"

    echo -e "\033[2mTesting: \"$input\"\033[0m"
    echo -e "\033[2m════════════════════════════════════════════\033[0m"

    # Route and show colors (filter out the final output line)
    "$SCRIPT_DIR/intent-router.sh" route "$input" 2>&1 | grep -v "^[a-z].*|" || true

    echo ""
    sleep 0.5
done

echo -e "\033[1m\033[38;5;220m"
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    COLOR SYSTEM FEATURES                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo -e "\033[0m"

echo -e "\033[1mEach agent has:\033[0m"
echo "• Unique primary & secondary colors"
echo "• Custom emoji icon"
echo "• Styled header box"
echo "• Color-coded confidence bar"
echo "• Matched keywords highlighting"
echo ""

echo -e "\033[1mAccessibility features:\033[0m"
echo "• High contrast mode available"
echo "• 256-color terminal support"
echo "• Fallback to basic 8 colors"
echo "• Screen reader compatible output"
echo ""

echo -e "\033[1m\033[32m✅ Agent Color System Ready!\033[0m"