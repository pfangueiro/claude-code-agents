MUT_DESC="/optimize GUARD_RAN_RE default deleted outright — the zero-test gate is absent"
MUT_CLAIM="validate.sh: 'Gap-tested by mutation: ... line deleted -> FAIL'"
MUT_BASELINE_PASS="/optimize GUARD_RAN_RE rejects zero-test output and accepts a real run"
MUT_EXPECT="no GUARD_RAN_RE default found"

mutate() {
    mut_delete_lines "$1/.claude/commands/optimize.md" '^: "\$\{GUARD_RAN_RE:='
}
