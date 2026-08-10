MUT_DESC="/execute agent-selection matrix drops security-auditor (the Opus agent becomes unselectable)"
MUT_CLAIM="validate.sh: 'Gap-tested by mutation: one \`### <agent>\` heading removed -> FAIL naming it'"
MUT_BASELINE_PASS="/execute agent matrix enumerates all"
MUT_EXPECT="/execute agent matrix omits shipped agent\(s\): security-auditor"

mutate() {
    # Headings read `### security-auditor (subagent_type: security-auditor)`, and
    # validate.sh harvests them with `^### [a-z-]+`.
    mut_delete_lines "$1/.claude/skills/execute/references/agent-selection.md" \
        '^### security-auditor(\s|$)'
}
