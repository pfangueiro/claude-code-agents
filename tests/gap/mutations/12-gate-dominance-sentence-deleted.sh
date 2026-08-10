MUT_DESC="/execute Pre-Flight Gate no longer states that invocation does not override an ABORT"
MUT_CLAIM="validate.sh: 'GAP-TESTED BY EXECUTION ... dominance sentence deleted -> NODOMINANCE'"
MUT_BASELINE_PASS="execute: pre-flight gate is abort-dominant"
MUT_EXPECT="execute: gate never states that invocation does NOT override an ABORT"

mutate() {
    local f="$1/.claude/skills/execute/SKILL.md"
    mut_delete_lines "$f" 'does NOT override an ABORT' || return 1
    mut_delete_lines "$f" 'Being invoked'
}
