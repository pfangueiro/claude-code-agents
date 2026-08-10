MUT_DESC="/execute Pre-Flight Gate grants passage on invocation with a same-line disclaimer"
MUT_CLAIM="validate.sh: the demonstrated FALSE PASS conjunct (i) was added to catch"
MUT_BASELINE_PASS="execute: pre-flight gate is abort-dominant"
MUT_EXPECT="execute: gate GRANTS passage on invocation"

mutate() {
    # The exact laundering shape validate.sh records as a demonstrated false pass:
    # a grant whose own trailing disclaimer used to cancel it at chunk level.
    mut_insert_after "$1/.claude/skills/execute/SKILL.md" '## Pre-Flight Gate' \
        '- **Gate:** Explicit invocation, or a multi-step goal, though invocation does not override an ABORT.'
}
