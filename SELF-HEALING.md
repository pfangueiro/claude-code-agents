# Health observation & explicit repair — full runbook

This describes the **Claude user-global runtime**. Codex uses the same source repository
but has no watchdog, automatic snapshots or unattended reconciliation. Use
`./install-codex.sh --user --check` and repeat `--user` for explicit repair/update;
owner modifications remain conflicts. See [Codex coverage](codex/FEATURES.md).

The framework **observes** the health of its own user-global install at `~/.claude` (the
single install that serves every project) and keeps backups. It does **not** repair,
migrate, reseed or collect in the background: the two paths below only report drift and
write snapshots. Repair is always an explicit, foreground `./install.sh --update` the
owner runs. CLAUDE.md carries only a summary of this; the operational detail — watchdog
cadence/retention, the settings-sync-wipe recovery procedure, the `--upgrade` consent
flow, `.attribution` reconcile, statusline glyph states, diagnostic-log capping, and every
snapshot-restore command — lives here. **Read this before any framework-infra change.**

The optional components are opt-in at install time: `--with-watchdog` (the launchd
daemon + snapshots, macOS), `--with-analytics` (dashboard assets + `claude-obs` alias),
`--with-notifications` (the desktop notify hook). A fresh install installs none of them.

## Fast path — SessionStart hook (`global-config/hooks/session-start-healthcheck.sh`)

- Runs on every Claude Code session start, budget <2s. **Observe-only.**
- Checks env keys and the `CLAUDE_CODE_EFFORT_LEVEL` value in `~/.claude/settings.json`
  against the template, hook script sha256 against source, hook/statusline wiring, the
  shared set (agents/skills/commands/rules) sha256 against source, and — only for the
  optional components the `.framework-version` marker records as selected — their assets.
- On drift: logs a `drift_detected` record (with `"action":"manual_repair_required"`) to
  `~/.claude/analytics/framework-health.jsonl`. It does **not** fork, spawn, install or
  write anything back; it reports that an explicit `./install.sh --update` is required.
- An ambiguous/unreadable prerequisite (missing `jq`, unreadable settings) is recorded as
  *unknown*, never silently treated as healthy.
- Exit 0 always — never blocks session start.

## Slow path — launchd watchdog (`global-config/daemon/claude-framework-watchdog.sh`)

Installed only with `./install.sh --with-watchdog` (macOS). **Observe-only** — it reports
health and keeps backups; it does **not** repair, migrate or reseed. Earlier revisions ran
`install.sh --update` on drift (and a per-cycle `--migrate-legacy`); both were removed.

- Runs hourly via the `com.claude-code-agents.framework-watchdog` LaunchAgent.
- **Hourly:** `validate.sh --quick --json` (no `--heal`) for admission, and `git fsck` on
  the repo (corruption → `watchdog-alerts.jsonl`). On `errors>0` it records the drift; it
  does not launch the installer.
- **Daily:** a git bundle snapshot of the repo, a tarball of `~/.claude/hooks` +
  `settings.json`, and a separate tarball of project memory (`~/.claude/projects/*/memory`).
- **Diagnostic-log capping (every cycle):** the append-only diagnostic logs are bounded via
  `trim_jsonl` (atomic tail-to-temp, verify non-empty, `mv`) — `framework-health.jsonl` to
  the last 1000 lines, `watchdog-alerts.jsonl` to 500. `validate.sh` guards `trim_jsonl`'s
  presence in the watchdog source, so losing rotation is a validation failure.
- **Retention:** prunes snapshots older than 7 days (memory snapshots keep a floor of the
  newest 3 regardless of age, so a >7-day backup outage never deletes the last copy).
- **Output:** `~/.claude/analytics/watchdog.log`.
- **Plist reload (explicit installer runs only):** `install_watchdog` sha-tracks the loaded
  plist in `~/.claude/.watchdog-plist.sha` and reloads the daemon only on a real plist change.
  The `CLAUDE_WATCHDOG_RUN=1` deferral is kept only for compatibility and as a test guard. The
  observe-only watchdog never runs the installer, so this is not a self-update path. The next
  explicit installer run with `--with-watchdog` applies a deferred reload. A watchdog
  *script* that `install.sh` re-copies (only when the watchdog is selected) takes effect at
  the next launchd run.

## Snapshot restore (`~/.claude/snapshots/`)

Snapshots exist only when the watchdog is installed. Restore is always a manual command.

- **Repo corruption:** `git clone ~/.claude/snapshots/claude-code-agents-YYYYMMDD-HHMM.bundle recovered/`
- **User config corruption:** `tar -xzf ~/.claude/snapshots/userconfig-YYYYMMDD.tgz -C /`
- **Project memory** (`~/.claude/projects/<slug>/memory/*.md`): archives use paths relative to `~/.claude` and restore with `-C ~/.claude` (never `-C /`), so they can only write under `projects/*/memory`. **List before restoring.**
  - List a snapshot: `tar -tzvf ~/.claude/snapshots/memory-latest.tgz`
  - One project (common case): `tar -xzf ~/.claude/snapshots/memory-latest.tgz -C ~/.claude projects/<slug>/memory`
  - Compare backup vs current before clobbering: `tar -xzOf ~/.claude/snapshots/memory-latest.tgz projects/<slug>/memory/MEMORY.md | diff - ~/.claude/projects/<slug>/memory/MEMORY.md`
  - All memory (fresh machine / mass loss): `tar -xzf ~/.claude/snapshots/memory-latest.tgz -C ~/.claude`

## Known external cause — CLI settings-sync hooks wipe

Claude Code's own settings-sync (`tengu_enable_settings_sync_push`) does a *wholesale replace* of `~/.claude/settings.json` (CLI `src/services/settingsSync/index.ts:519`, no merge, change-detection suppressed). When settings-sync is enabled across machines, a sync cycle can pull a payload lacking the framework's `.hooks` block and overwrite it to `{}` — with no install.sh involvement and no drift event at write time. This is external CLI behavior, not an install bug.

Recovery is detect-then-explicit-repair; nothing auto-heals:

- The SessionStart `hook_wiring`/`statusline_wiring` checks report the drift on the next
  session — but the SessionStart hook itself lives in the wiped `.hooks`, so it cannot run
  to report a wipe that removed it.
- The launchd watchdog, when installed, runs independently of `~/.claude/settings.json` and
  therefore survives the wipe; its `validate.sh --quick --json` admission records `errors>0`
  in `framework-health.jsonl` and its daily `userconfig-*.tgz` snapshot captures a good
  copy. It does **not** repair the wipe.
- **Repair the wipe explicitly:** run `./install.sh --update`. Its hook-event reconcile
  re-populates an emptied `{}` (a valid-JSON object) with the framework events, and a fully
  absent (deleted) `settings.json` is reseeded from the template with only the selected
  optional hook events wired. A present-but-corrupt (non-object) `settings.json` is a
  separate case (below).

`install.sh`'s own settings writes are hardened via `_atomic_settings_jq` (unique mktemp
temp file + non-empty + valid-JSON guards) so an explicit reconcile can never contribute to
a wipe. On install / `--update`, `settings.json` `.attribution` is reconciled replace-on-drift
(scrubs a stale `Co-Authored-By` commit trailer to `""` and restores the template PR footer),
and `validate.sh --quick` reports whether the LIVE `~/.claude/settings.json` `.attribution.commit`
is empty. This is the config-layer side of the "No AI-attribution trailers" convention; a user
wanting a custom PR footer edits `settings.local.json` (higher precedence).

A present-but-**corrupt** `~/.claude/settings.json` (unparseable, or valid JSON of a
non-object shape — `[]`, `123`, `"x"`, `true`, anything for which `jq -e 'type == "object"'`
fails) is **preserved as-is**, never silently reset: `install.sh` writes a forensic copy to
`settings.json.corrupt-<timestamp>` and reports it as a manual-repair item, leaving the live
file untouched so an owner edit or snapshot is never clobbered by a reseed. Fix it by hand or
restore from a `userconfig-*.tgz` snapshot. Only a fully **absent** file is reseeded from the
template.

## Explicit migration of old per-project copies (opt-in)

There is no auto-pull and no background migration. To move old per-project `.claude` copies
to the user-global layout, set `LEGACY_PROJECTS_DIR` in `~/.claude/.framework-autonomy` and
run `./install.sh --migrate-legacy` (or `--upgrade`) yourself. That teardown is
framework-scoped, untracked-only (never rewrites a repo's history), snapshot-first, skips
committed repos, and idempotent. The committed-guard requires ALL five framework subdirs
(agents/skills/commands/rules/lib) to be git-untracked before any teardown, plus symlink
guards. No marker → no teardown; the watchdog does **not** run this.

## Manual one-command migration — `install.sh --upgrade`

`cd ~/.claude-code-agents && ./install.sh --upgrade` reconciles `~/.claude`, detects old
per-project `.claude` copies, prints a COUNT + candidate LIST, and asks ONE confirmation at
the controlling terminal (a dedicated fd bound to `/dev/tty`, never stdin) — or `--yes` /
`CLAUDE_UPGRADE_ASSUME_YES=1`. Snapshot-first, framework-scoped teardown, then self-verifies
with `validate.sh --quick` (observe-only, never `--heal`). No tty + no explicit consent →
fail-closed SKIP (exit 0) with a re-run one-liner. Checkout-local only; `curl|bash` cannot
pass it. Bare install / `--update` / `--migrate-legacy` stay byte-identical. **Install
modes:** bare | `--update` | `--upgrade` | `--migrate-legacy` | `--help`, plus the opt-in
`--with-watchdog` / `--with-analytics` / `--with-notifications` flags.

## Statusline framework-status

`statusline.sh` renders a compact `⚙<version> <glyph>` segment at the end of line 1. The
glyph is derived only from the structured records the observe-only checks already wrote
(`framework-health.jsonl` plus corruption alerts); it never runs validate in the hot path,
caches 60s, and emits nothing when the framework isn't installed. It is honest and
fail-closed — there is no repair to report and no self-healing glyph:

- `✓` — a RECENT, admitted `validation_result` from the watchdog's `validate.sh --quick
  --json` run: status healthy, `complete` true, exit code 0, zero errors, with meaningful,
  internally consistent counts. Here `complete` means that QUICK installed-integrity scope
  finished (deployed hooks / env / shared-set / hook wiring under `~/.claude`); `--quick`
  deliberately exits before the full-only source checks, so `✓` attests the completed
  watchdog quick installed-integrity scope ONLY. It does **not** certify the default full
  `validate.sh` repository validator, the project test suites, or CI. Only such an admitted
  watchdog `--quick` `validation_result` can certify green.
- `⚠` — a current drift / failed validation, a drift from the SessionStart check, or a
  recent (within 24h) corruption/backup alert.
- `?` — default: no admitted evidence yet (a version marker alone is **not** proof), or
  evidence that is missing / malformed / stale / future / inconsistent.
- The newest relevant record wins; a scope-qualified SessionStart `healthcheck_result` can
  downgrade or confirm but never certifies green. Retired `heal_*` records are historical
  and ignored. An unselected watchdog that simply never ran is `?`, not `⚠` (absence of
  evidence is unknown, not stalled).
- **Deploy reconcile:** `validate.sh` asserts the segment exists AND that deployed
  `~/.claude/statusline.sh` == source, and that the glyph is derived from an admitted
  `validation_result` gated on `complete` (no revived self-healing display). `install.sh
  ensure_statusline` is replace-on-drift (`cp` when absent or `diff -q` differs, skip when
  byte-identical).
- **UTC timestamps:** staleness is computed by parsing the health-log ISO timestamps as UTC
  (`date -j -u -f` on macOS; `date -u -d` on GNU).

## Validation guards (`validate.sh`)

`validate.sh` **observes** — `--heal` is retired (it performs no repair and is rejected),
and the script is guarded against ever invoking the installer. Beyond file-identity
(deployed==source) reconcile checks, it asserts:

- **Doc-accuracy (FULL-ONLY):** counts actual agents/skills/hook-scripts/MCP-servers on
  disk and FAILS if CLAUDE.md's prose counts disagree — catching silent count-rot. Full-only
  by design: a count mismatch cannot be auto-repaired, and it must fail at commit time.
- **Live-attribution:** `--quick` asserts the live `~/.claude/settings.json`
  `.attribution.commit` is empty (not just the source template).
- **Statusline:** the framework-status segment exists in `statusline.sh`, deployed == source,
  and the glyph requires an admitted `validation_result(complete)` with no legacy
  self-healing display.
- **Heal-retired / observe-only:** `validate.sh` invokes no installer, and the watchdog and
  SessionStart hook source carry no `install.sh --update`/`--migrate-legacy` fork.
- **Watchdog log-cap:** `trim_jsonl` is present in the watchdog source.
- **Memory restore path:** the project-memory restore path (`memory-latest.tgz`) is
  documented (framework-integrity: no snapshot without a documented restore path).

## Diagnostic stream

`~/.claude/analytics/framework-health.jsonl` — single source for drift findings, validation
output and snapshot activity (capped every cycle by the watchdog when installed).
`~/.claude/analytics/watchdog-alerts.jsonl` — corruption/backup alerts.
