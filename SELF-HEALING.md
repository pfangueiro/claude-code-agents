# Self-Healing — full runbook

The framework reconciles its own user-global install at `~/.claude` (the single install that serves every project). Two paths, one diagnostic stream. CLAUDE.md carries only a summary of this; the operational detail — watchdog cadence/retention, the settings-sync-wipe recovery mechanism, the `--upgrade` consent flow, `.attribution` auto-heal, statusline glyph states, diagnostic-log capping, and every snapshot-restore command — lives here. **Read this before any framework-infra change.**

## Fast path — SessionStart hook (`global-config/hooks/session-start-healthcheck.sh`)

- Runs on every Claude Code session start, budget <2s.
- Checks env keys in `~/.claude/settings.json` against template, hook script sha256 against source, the shared set (agents/skills/commands/rules) sha256 against source (Check 7), analytics files present.
- On drift: logs to `~/.claude/analytics/framework-health.jsonl` and forks `install.sh --update` in background.
- Exit 0 always — never blocks session start.

## Slow path — launchd watchdog (`global-config/daemon/claude-framework-watchdog.sh`)

- Runs hourly via the `com.claude-code-agents.framework-watchdog` LaunchAgent.
- **Hourly:** `validate.sh --quick --json`, `git fsck` on repo (corruption → `watchdog-alerts.jsonl`).
- **Daily:** git bundle snapshot of repo, tarball of `~/.claude/hooks` + `settings.json`, separate tarball of project memory (`~/.claude/projects/*/memory`).
- **Diagnostic-log capping (every cycle):** the append-only diagnostic logs are bounded via `trim_jsonl` (atomic tail-to-temp, verify non-empty, `mv`) — `framework-health.jsonl` to the last 1000 lines, `watchdog-alerts.jsonl` to 500. Previously these grew unbounded (~50 lines/day). `validate.sh` guards `trim_jsonl`'s presence in the watchdog source, so losing rotation is a validation failure.
- **Retention:** prunes snapshots older than 7 days (memory snapshots keep a floor of the newest 3 regardless of age).
- **Output:** `~/.claude/analytics/watchdog.log`.
- **Plist self-reload:** `install_watchdog` sha-tracks the loaded plist in `~/.claude/.watchdog-plist.sha` and reloads the daemon only on a real plist change (deferred under `CLAUDE_WATCHDOG_RUN` to avoid a self-kill mid-run). The watchdog *script* self-updates via launchd re-exec of the deployed copy, which `install.sh` copies unconditionally on every `--update`.

## Snapshot restore (`~/.claude/snapshots/`)

- **Repo corruption:** `git clone ~/.claude/snapshots/claude-code-agents-YYYYMMDD-HHMM.bundle recovered/`
- **User config corruption:** `tar -xzf ~/.claude/snapshots/userconfig-YYYYMMDD.tgz -C /`
- **Project memory** (`~/.claude/projects/<slug>/memory/*.md`): archives use paths relative to `~/.claude` and restore with `-C ~/.claude` (never `-C /`), so they can only write under `projects/*/memory`. **List before restoring.**
  - List a snapshot: `tar -tzvf ~/.claude/snapshots/memory-latest.tgz`
  - One project (common case): `tar -xzf ~/.claude/snapshots/memory-latest.tgz -C ~/.claude projects/<slug>/memory`
  - Compare backup vs current before clobbering: `tar -xzOf ~/.claude/snapshots/memory-latest.tgz projects/<slug>/memory/MEMORY.md | diff - ~/.claude/projects/<slug>/memory/MEMORY.md`
  - All memory (fresh machine / mass loss): `tar -xzf ~/.claude/snapshots/memory-latest.tgz -C ~/.claude`

## Known external cause — CLI settings-sync hooks wipe

Claude Code's own settings-sync (`tengu_enable_settings_sync_push`) does a *wholesale replace* of `~/.claude/settings.json` (CLI `src/services/settingsSync/index.ts:519`, no merge, change-detection suppressed). When settings-sync is enabled across machines, a sync cycle can pull a payload lacking the framework's `.hooks` block and overwrite it to `{}` — with no install.sh involvement and no drift event at write time. This is external CLI behavior, not an install bug.

Defense is detect-and-heal on TWO independent triggers: (1) the SessionStart `hook_wiring`/`statusline_wiring` checks re-run `install.sh --update` on the next session — but the SessionStart hook itself lives in the wiped `.hooks`, so it cannot recover the wipe that removed it; (2) the launchd watchdog, which runs independently of `~/.claude/settings.json` and therefore SURVIVES the wipe, parses `validate.sh --quick --json` and on `errors>0` runs `install.sh --update` itself (Task 1) — this is the trigger that actually recovers a `.hooks` wipe, logging `heal_triggered`/`heal_succeeded` to `framework-health.jsonl`.

`install.sh`'s settings writes are hardened via `_atomic_settings_jq` (unique mktemp temp file + non-empty + valid-JSON guards) so the framework's own reconcile can never contribute to a wipe. On install / `--update`, `settings.json` `.attribution` also AUTO-HEALS (scrubs a stale `Co-Authored-By` commit trailer to `""` and restores the template PR footer, replace-on-drift like `.permissions`); `validate.sh --quick` also checks the LIVE `~/.claude/settings.json` `.attribution.commit` (the old check only guarded the source template, so a failed/absent heal was invisible). This is the config-layer enforcement behind the "No AI-attribution trailers" convention; a user wanting a custom PR footer edits `settings.local.json` (higher precedence).

## Autonomous cross-system migration (opt-in)

For the AUTONOMOUS path, a `git pull` on any machine is the only manual trigger — the next SessionStart healthcheck / watchdog forks `install.sh --update`, which reconciles `~/.claude` AND (only if `~/.claude/.framework-autonomy` sets `LEGACY_PROJECTS_DIR`) tears down old per-project `.claude` copies there. That teardown is framework-scoped, untracked-only (never rewrites a repo's history), snapshot-first, skips committed repos, and idempotent. The committed-guard requires ALL five framework subdirs (agents/skills/commands/rules/lib) to be git-untracked before any teardown (previously agents-only — a repo that committed `.claude/rules/<framework-name>.md` could have had TRACKED files removed), plus symlink guards. No marker → no teardown; there is deliberately **no auto-pull**.

## Manual one-command migration — `install.sh --upgrade`

Distinct from the marker-driven autonomous teardown, `cd ~/.claude-code-agents && ./install.sh --upgrade` reconciles `~/.claude`, detects old per-project `.claude` copies, prints a COUNT + candidate LIST, and asks ONE confirmation at the controlling terminal (a dedicated fd bound to `/dev/tty`, never stdin) — or `--yes` / `CLAUDE_UPGRADE_ASSUME_YES=1`. Snapshot-first, framework-scoped teardown, then self-verifies with `validate.sh --quick` (observe-only, never `--heal`). No tty + no explicit consent → fail-closed SKIP (exit 0) with a re-run one-liner. Checkout-local only; `curl|bash` cannot pass it. Bare install / `--update` / `--migrate-legacy` stay byte-identical. **Install modes:** bare | `--update` | `--upgrade` | `--migrate-legacy` | `--help`.

## Statusline framework-status

`statusline.sh` renders a compact `⚙<version> <glyph>` segment at the end of line 1 — ✓ healthy / ⟳ self-healing / ⚠ (watchdog stalled >150 min | heal_failed | recent corruption). It reads only `~/.claude/.framework-version` and `~/.claude/analytics/{framework-health.jsonl,watchdog-alerts.jsonl}`, NEVER runs validate in the hot path, caches 60s, and emits nothing when the framework isn't installed.

- **Deploy reconcile:** `validate.sh` asserts the segment exists AND that deployed `~/.claude/statusline.sh` == source. `install.sh ensure_statusline` is **replace-on-drift** (`cp` when absent or `diff -q` differs, skip when byte-identical) — previously it was install-only ("never overwrites"), which left `--update`/`--upgrade` unable to redeploy a changed `statusline.sh` and **looped the watchdog 25× on `heal_failed`** while the machine was otherwise healthy. One change heals all three call sites (install / `--update` / `--upgrade`). Install kickstarts the watchdog, stamps a fresh `install_reconciled` health event, and drops the 60s cache after a reload so there is no transient ⚠ post-install.
- **Glyph recovery:** the glyph anchors to the epoch of the most recent CLEAN `validate_quick`, so a *fixed* `heal_failed` (or a converged heal loop) clears the warn glyph instead of latching it for the full 24h. Genuine (non-`heal_failed`) git-corruption alerts still trump for 24h.
- **UTC timestamps:** staleness is computed by parsing the health-log ISO timestamps as UTC (`date -j -u -f` on macOS; `date -u -d` on GNU) — a prior local-time parse produced a false ⚠ on non-UTC machines. Staleness threshold is 150 min (2.5× the hourly cadence).

## Validation guards (`validate.sh`)

Beyond file-identity (deployed==source) reconcile, validate asserts:

- **Doc-accuracy (FULL-ONLY):** counts actual agents/skills/hook-scripts/MCP-servers on disk and FAILS if CLAUDE.md's prose counts disagree — catching silent count-rot (the recurring "CHANGELOG lag" failure). Full-only by design: a count mismatch can't be auto-healed (install can't rewrite prose), so running it in `--quick` would loop the watchdog. It fails on `./validate.sh` at commit time, exactly when the drift is introduced.
- **Live-attribution:** `--quick` asserts the live `~/.claude/settings.json` `.attribution.commit` is empty (not just the source template).
- **Statusline:** the framework-status segment exists in `statusline.sh` AND deployed == source.
- **Watchdog log-cap:** `trim_jsonl` is present in the watchdog source (diagnostic logs stay bounded).
- **Memory restore path:** the project-memory restore path (`memory-latest.tgz`) is documented (framework-integrity: no snapshot without a documented restore path).

## Diagnostic stream

`~/.claude/analytics/framework-health.jsonl` — single source for drift events, validation output, snapshot activity (capped every cycle by the watchdog). `~/.claude/analytics/watchdog-alerts.jsonl` — corruption alerts.
