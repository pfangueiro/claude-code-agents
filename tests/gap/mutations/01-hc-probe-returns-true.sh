MUT_DESC="health_check.py check_database() reports success instead of failing closed"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 1)"
MUT_BASELINE_PASS="health_check.py unimplemented probes fail closed"
MUT_EXPECT="probe\(s\) report SUCCESS without verifying.*database"

mutate() {
    # An unimplemented probe that returns True is the original defect: the deploy
    # gate reports a healthy database it never contacted. Injected as an early
    # return so the file stays valid Python.
    MUT_ROOT="$1" mut_python "$1/.claude/skills/deployment-runbook/scripts/health_check.py" <<'PY'
import re, sys
p = sys.argv[1]
src = open(p, encoding='utf-8').read()
i = src.index("def check_database")
j = src.index("return self._not_implemented(", i)
indent = " " * (j - src.rindex("\n", 0, j) - 1)
open(p, 'w', encoding='utf-8').write(
    src[:j] + 'return True, "Database connectivity OK"\n' + indent + src[j:])
PY
}
