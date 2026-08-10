MUT_DESC="health_check.py partial run (--check api) exits 0 instead of EXIT_PARTIAL"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 1b)"
MUT_BASELINE_PASS="health_check.py partial run exits EXIT_PARTIAL"
MUT_EXPECT="PARTIAL run .* exits 0 — CI cannot tell it from a full pass"

mutate() {
    # This is the exact shape of the defect a LATER repair once re-opened: one probe
    # green out of five reads to CI as a verified deployment.
    mut_replace "$1/.claude/skills/deployment-runbook/scripts/health_check.py" \
        "    return EXIT_PARTIAL" "    return EXIT_OK"
}
