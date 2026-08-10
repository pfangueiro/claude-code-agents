MUT_DESC="library-docs re-introduces the removed context7 tool name get-library-docs"
MUT_CLAIM="validate.sh context7 API-shape guard (the guard that once certified four surviving dead params)"
MUT_BASELINE_PASS="no removed context7 tool name or parameter"
MUT_EXPECT="removed-context7-API reference\(s\) in skill/docs"

mutate() {
    mut_append "$1/.claude/skills/library-docs/SKILL.md" \
        'Call `mcp__context7__get-library-docs` with the library id to fetch the pages.'
}
