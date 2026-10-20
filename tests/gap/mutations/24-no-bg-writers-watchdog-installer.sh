MUT_DESC="the observe-only watchdog re-adds a background install.sh --update invocation"
MUT_CLAIM="validate.sh: 'No-background-writers' guard — background health scripts must never run the installer"
MUT_BASELINE_PASS="No-background-writers: watchdog + SessionStart invoke no installer/migration/collector"
MUT_EXPECT="No-background-writers: observe-only background script invokes installer/migration/collector.*watchdog:installer"

mutate() {
    # A background installer run inside the observe-only watchdog is exactly the
    # no-background-writers violation. validate.sh only READS the watchdog (never
    # executes it), so the injected line proves the guard's source scan, not a run.
    mut_insert_after "$1/global-config/daemon/claude-framework-watchdog.sh" \
        'log "watchdog: run start' \
        './install.sh --update >/dev/null 2>&1 &'
}
