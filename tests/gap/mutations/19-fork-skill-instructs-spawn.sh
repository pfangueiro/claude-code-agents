MUT_DESC="a 'context: fork' skill instructs an Explore-agent spawn it cannot perform"
MUT_CLAIM="validate.sh fork-spawn guard (derived scope; a two-name list once passed over a live instance)"
MUT_BASELINE_PASS="deep-read: forked and instructs no Agent-launcher/AskUserQuestion step"
MUT_EXPECT="deep-read: declares 'context: fork' but instructs capabilities a forked subagent lacks"

mutate() {
    mut_append "$1/.claude/skills/deep-read/SKILL.md" \
        'Launch parallel Explore agents to sweep the remaining directories.'
}
