MUT_DESC="browser-testing visual regression stops asserting identical dimensions (size mismatch scores AE=0, exit 0)"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 5c)"
MUT_BASELINE_PASS="browser-testing assert_response examples pass 'value'"
MUT_EXPECT="compares without asserting identical dimensions first"

mutate() {
    mut_replace_all "$1/.claude/skills/browser-testing/SKILL.md" \
        "identify -format '%wx%h'" "identify -format '%w'"
}
