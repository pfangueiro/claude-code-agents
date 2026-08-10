MUT_DESC="/optimize GUARD_RAN_RE reverted to [0-9]+ — '0 passed' reads GREEN through the zero-test gate"
MUT_CLAIM="validate.sh: 'Gap-tested by mutation: default reverted to \`[0-9]+ ...\` -> FAIL'"
MUT_BASELINE_PASS="/optimize GUARD_RAN_RE rejects zero-test output and accepts a real run"
MUT_EXPECT="GUARD_RAN_RE matches a zero-test run"

mutate() {
    mut_replace "$1/.claude/commands/optimize.md" \
        ': "${GUARD_RAN_RE:=[1-9][0-9]* (passed|passing|tests? ran|ok)}"' \
        ': "${GUARD_RAN_RE:=[0-9]+ (passed|passing|tests? ran|ok)}"'
}
