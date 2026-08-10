MUT_DESC="/execute renames its '## Pre-Flight Gate' heading, silently dropping out of the guard's derived scope"
MUT_CLAIM="validate.sh: 'GAP-TESTED BY EXECUTION ... heading absent -> NOSECTION' + coverage cross-check"
MUT_BASELINE_PASS="every expected gated skill carries a '## Pre-Flight Gate' heading"
MUT_EXPECT="expected gated skill\(s\) have no '## Pre-Flight Gate' heading and were not analyzed.*execute"

mutate() {
    # Scope is DERIVED from the headings, so a rename would shrink the guard's
    # coverage in silence if the cross-check did not exist.
    mut_replace "$1/.claude/skills/execute/SKILL.md" \
        '## Pre-Flight Gate' '## Before You Start'
}
