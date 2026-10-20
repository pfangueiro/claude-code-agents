MUT_DESC="statusline.sh stops reading validation_result evidence — a version marker alone could read green"
MUT_CLAIM="validate.sh: 'Statusline honest-health' guard — the glyph must gate on an admitted validation_result"
MUT_BASELINE_PASS="Statusline honest-health: glyph requires an admitted validation_result"
MUT_EXPECT="Statusline honest-health:.*no-validation_result-evidence"

mutate() {
    # Delete every line that reads the validation_result stream. Without it the
    # glyph can no longer be gated on an admitted full validation — the marker-only
    # green this retirement removed. (The `complete` jq lines survive, so only the
    # no-validation_result-evidence arm of the guard fires.)
    mut_delete_lines "$1/global-config/statusline.sh" 'validation_result'
}
