MUT_DESC="observability-stack alert references a recording rule whose definition was removed"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 3)"
MUT_BASELINE_PASS="observability-stack alerts reference no undefined recording rules"
MUT_EXPECT="reference UNDEFINED recording rule\(s\)"

mutate() {
    # Drop the definition, keep the two alert expressions that use it: the alert
    # becomes an empty vector that never fires and logs no error.
    mut_delete_lines "$1/.claude/skills/observability-stack/SKILL.md" \
        '^\s*-\s*record:\s*sli:availability:ratio_rate5m\s*$'
}
