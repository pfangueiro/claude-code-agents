MUT_DESC="a skill's ## Resources advertises a scripts/ file that does not exist"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 4)"
MUT_BASELINE_PASS="no skill advertises a Resources file that does not exist"
MUT_EXPECT="phantom resource file\(s\) advertised but absent"

mutate() {
    mut_insert_after "$1/.claude/skills/deployment-runbook/SKILL.md" \
        '### scripts/' '- **ghost_probe.py**: advertised here, never shipped'
}
