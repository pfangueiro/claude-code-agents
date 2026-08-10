MUT_DESC="/execute Pre-Flight Gate reverted to the pre-repair 'Explicit invocation, or ...' OR-arm"
MUT_CLAIM="validate.sh: 'GAP-TESTED BY EXECUTION ... pre-repair gate restored -> ARM'"
MUT_BASELINE_PASS="execute: pre-flight gate is abort-dominant"
MUT_EXPECT="execute: un-neutralized invocation arm"

mutate() {
    local f="$1/.claude/skills/execute/SKILL.md"
    mut_delete_lines "$f" 'does NOT override an ABORT' || return 1
    mut_delete_lines "$f" 'Being invoked' || return 1
    mut_insert_after "$f" '## Pre-Flight Gate' \
        '**Gate:** Explicit invocation, or a genuinely hard problem.'
}
