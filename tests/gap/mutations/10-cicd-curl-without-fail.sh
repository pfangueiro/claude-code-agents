MUT_DESC="ci-cd-templates deploy webhook curl loses --fail (HTTP 500 marks the deploy green)"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 6b)"
MUT_BASELINE_PASS="ci-cd-templates semgrep carries --error; every curl carries --fail"
MUT_EXPECT="curl invocation \(line [0-9]+\) has no --fail/--fail-with-body"

mutate() {
    mut_replace "$1/.claude/skills/ci-cd-templates/SKILL.md" \
        "curl --fail --show-error --silent" "curl --show-error --silent"
}
