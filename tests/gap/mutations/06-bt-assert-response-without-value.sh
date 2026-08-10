MUT_DESC="browser-testing assert_response examples drop the 'value' argument (any 401/500 asserts green)"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 5a)"
MUT_BASELINE_PASS="browser-testing assert_response examples pass 'value'"
MUT_EXPECT="assert_response example with no 'value' argument"

mutate() {
    mut_python "$1/.claude/skills/browser-testing/SKILL.md" <<'PY'
import re, sys
p = sys.argv[1]
out = []
for l in open(p, encoding='utf-8').read().splitlines(True):
    if "assert_response" in l and re.search(r'(\bid\s*[:=]|"id")', l):
        l = re.sub(r',\s*value:.*?(?=\s*$)', '', l)
    out.append(l)
open(p, 'w', encoding='utf-8').writelines(out)
PY
}
