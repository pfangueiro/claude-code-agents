MUT_DESC="validate.sh re-adds an install.sh --update invocation (the retired --heal exit-0 laundering path)"
MUT_CLAIM="validate.sh: 'Heal-retired' guard — the --heal installer-laundering path must stay removed"
MUT_BASELINE_PASS="Heal-retired: validate.sh invokes no installer"
MUT_EXPECT="Heal-retired: validate.sh invokes install.sh --update"

mutate() {
    # Reintroduce the exact forbidden shape: a redirected install.sh --update call
    # on a live code line. It is behind an unset-var guard so the clone never
    # actually runs the installer, but the SOURCE grep the guard performs still
    # sees it — which is the whole point (the retirement is a source property).
    mut_insert_after "$1/validate.sh" \
        '_note_incomplete() { COMPLETE=false; }' \
        'if [ "${_GAP_REHEAL:-}" = 1 ]; then ./install.sh --update >/dev/null 2>&1; fi'
}
