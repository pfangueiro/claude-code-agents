MUT_DESC="/execute Pre-Flight Gate asserts dominance over an (almost) empty ABORT set"
MUT_CLAIM="validate.sh: 'GAP-TESTED BY EXECUTION ... ABORT mentions reduced to one -> NOABORTS|1'"
MUT_BASELINE_PASS="execute: pre-flight gate is abort-dominant"
MUT_EXPECT="execute: gate asserts dominance but declares no ABORT conditions to dominate"

mutate() {
    local f="$1/.claude/skills/execute/SKILL.md"
    # Keep the dominance sentence (so dominance is still asserted) but strip the
    # conditions it claims to dominate: dominance over an empty set is vacuous.
    mut_delete_lines "$f" '^- ABORT \(do it directly\)' || return 1
    mut_replace "$f" 'check the ABORT condition below' 'check the abort condition below'
}
