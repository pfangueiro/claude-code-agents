MUT_DESC="the observe-only watchdog re-adds a background analytics collector run"
MUT_CLAIM="validate.sh: 'No-background-writers' guard — background health scripts must never run the analytics collector"
MUT_BASELINE_PASS="No-background-writers: watchdog + SessionStart invoke no installer/migration/collector"
MUT_EXPECT="No-background-writers: observe-only background script invokes installer/migration/collector.*watchdog:collector"

mutate() {
    # Running the collector from the observe-only watchdog is an outbound analytics
    # WRITE — forbidden. This is the invocation form (interpreter + path-qualified
    # collector.py), NOT the drift-check filename list the guard must tolerate.
    mut_insert_after "$1/global-config/daemon/claude-framework-watchdog.sh" \
        'log "watchdog: run start' \
        'python3 "$HOME/.claude/analytics/collector.py" >/dev/null 2>&1 &'
}
