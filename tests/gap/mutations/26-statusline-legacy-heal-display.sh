MUT_DESC="statusline.sh revives the retired self-healing display (the ⟳ in-progress glyph)"
MUT_CLAIM="validate.sh: 'Statusline honest-health' guard — the retired self-healing display must not return"
MUT_BASELINE_PASS="Statusline honest-health: glyph requires an admitted validation_result"
MUT_EXPECT="Statusline honest-health:.*legacy-heal-display"

mutate() {
    # Bring back the retired in-progress glyph and its "self-healing in progress"
    # label — a fabricated self-heal signal the honest-health retirement removed.
    # validate.sh scans statusline.sh as source, so this trips the guard even
    # though the line is never rendered in the clone.
    mut_insert_after "$1/global-config/statusline.sh" \
        'fw_seg=""; fw_ver=""' \
        '[ -n "${_gap_revived:-}" ] && { _g="⟳"; _c="$C_YELLOW"; }  # self-healing in progress'
}
