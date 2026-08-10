MUT_DESC="browser-testing names a tool without the mcp__playwright__ prefix (tool-not-found mid-run)"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 5b)"
MUT_BASELINE_PASS="tool names are mcp__playwright__-prefixed"
MUT_EXPECT="tool name missing mcp__playwright__ prefix"

mutate() {
    mut_replace "$1/.claude/skills/browser-testing/SKILL.md" \
        "1. mcp__playwright__playwright_navigate" "1. playwright_navigate"
}
