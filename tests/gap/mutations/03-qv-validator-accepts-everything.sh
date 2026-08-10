MUT_DESC="skill-creator quick_validate.py accepts every input (validator that cannot fail)"
MUT_CLAIM="validate.sh: 'each was gap-tested by reintroducing the bug' (fail-open guard 2)"
MUT_BASELINE_PASS="quick_validate.py rejects placeholders, accepts real skills"
MUT_EXPECT="quick_validate.py ACCEPTS a '\[TODO\]' placeholder description"

mutate() {
    mut_insert_after "$1/.claude/skills/skill-creator/scripts/quick_validate.py" \
        'if __name__ == "__main__":' '    sys.exit(0)'
}
