MUT_DESC="ci-cd-templates semgrep loses --error (SAST job exits 0 with findings)"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 6a)"
MUT_BASELINE_PASS="ci-cd-templates semgrep carries --error; every curl carries --fail"
MUT_EXPECT="semgrep invocation \(line [0-9]+\) has no --error"

mutate() {
    mut_replace "$1/.claude/skills/ci-cd-templates/SKILL.md" \
        "- semgrep --config=auto --error " "- semgrep --config=auto "
}
