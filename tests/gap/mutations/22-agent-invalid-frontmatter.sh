MUT_DESC="an agent description gains an unquoted colon, making its frontmatter invalid YAML (parses fine to a line-grep, not to a YAML parser)"
MUT_CLAIM="validate.sh agent-frontmatter YAML-validity guard"
MUT_BASELINE_PASS="Agent frontmatter: all agents parse as valid YAML"
MUT_EXPECT="Agent frontmatter: invalid YAML or missing keys"

mutate() {
    # Turn a comma into a colon-space inside code-quality's description. A plain YAML scalar
    # cannot contain ': ', so yaml.safe_load raises 'mapping values are not allowed here' —
    # exactly the shape two shipped agents once had. A field-presence grep would still pass.
    mut_replace "$1/.claude/agents/code-quality.md" \
        'quality assessment, refactoring suggestions' \
        'quality assessment: refactoring suggestions'
}
