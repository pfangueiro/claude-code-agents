# Changelog

All notable changes to Claude Agents will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2026-07-07

### Added

- **Autonomous cross-system self-migration** (opt-in, no auto-pull): after a deliberate `git pull` on any
  machine, the framework finishes its own migration to user-global with no further manual steps. The existing
  self-heal path (SessionStart healthcheck / launchd watchdog fork `install.sh --update`) now also runs a
  guardrailed teardown of old per-project copies.
  - `reconcile_legacy_projects()` in `install.sh --update`: gated behind an explicit per-machine marker
    `~/.claude/.framework-autonomy` (`LEGACY_PROJECTS_DIR=<dir>`). For each project under that dir carrying a
    per-project framework `.claude/agents`, it removes ONLY the framework shared-set subdirs, and ONLY when
    git-**untracked** (never rewrites a repo's history). Framework-scoped, **snapshot-first**, idempotent (no-op
    + no snapshot once torn down). **Absent marker → no-op** — public users and fresh installs are unaffected,
    and there is deliberately **no auto-pull** (`git pull` stays the one manual trigger).
  - **Autonomous scheduling**: the launchd watchdog runs a fast, teardown-only mode
    (`install.sh --migrate-legacy`) **every cycle**, so a newly-set marker triggers the teardown within the
    hour — independent of shared-set drift (the heal path only fires on validate errors). Manual immediate
    trigger: `install.sh --migrate-legacy`.
  - **Watchdog plist self-reload**: `install_watchdog` now sha-tracks the loaded plist and reloads the daemon on
    a real plist change, **deferring** the reload when running under the watchdog's own `--update` (avoids a
    self-kill; the next SessionStart-triggered `--update` applies it). The watchdog script already self-updated
    via launchd re-exec.

### Fixed

- **Autonomous legacy teardown is now framework-scoped** (`de82069`): `reconcile_legacy_projects()` removes only
  the framework's OWN files (agents/skills/commands/rules/lib, enumerated by name from source) from an untracked
  project — never a project's own custom agents/skills, even uncommitted ones — then `rmdir`s the emptied
  framework subdirs. A project qualifies for teardown only if it actually holds a framework-owned agent file, so a
  custom-only project is never a candidate (no snapshot spam, stays idempotent). Previously the whole
  `agents/skills/...` subdirs were deleted, which could drop uncommitted custom content. Verified in a sandbox:
  framework files removed while a custom agent + custom skill survive; committed / git-error / snapshot-fail
  guardrails intact; custom-only untouched; re-run makes no new snapshot.
- **`observability/collector.py` cost model refreshed**: added the current model IDs (`claude-opus-4-8`,
  `claude-sonnet-5`, `claude-fable-5`, plus the `claude-haiku-4-5` alias) so per-session cost estimates stop
  falling back to Sonnet pricing with an "unknown model" warning. Corrected two stale rows — the Opus tier is now
  $5/$25 input/output (the `claude-opus-4-6` entry was 3× high at $15/$75), and Haiku 4.5 is $1/$5 (was $0.8/$4).
  Cache read/create derived from the standard 0.1× / 1.25× (5-min TTL) multipliers.
- **Removed the deprecated Postgres MCP server** from `.mcp.json.example` (and the `global-config/` copy) and from
  the README: `@modelcontextprotocol/server-postgres` is marked "no longer supported" on npm (frozen at 0.6.2).
  The MCP badge/table now read **4 servers** (context7, sequential-thinking, playwright, github), and the MCP
  section no longer claims the servers are "auto-configured on install" — `install.sh` ships the example config
  but does not register any MCP server (users add them manually). Added a Requirements line and an INSTALL.md link
  to the README.
- **`sync_hooks` now reverse-prunes stale hook EVENT bindings, and `validate.sh` detects them**: the hook
  reconcile added/repaired every event the template *has* but never removed one the template *dropped*. A stale
  event still bound to a framework hook script (e.g. `Stop → session-end.sh`, left over after `session-end.sh`
  moved from `Stop` to `SessionEnd`) survived `install --update` forever and **double-fired the script every turn**,
  over-logging `session-summaries.jsonl`. `sync_hooks` now reverse-prunes such off-template events
  **framework-scoped** — only when the bound command is one of this framework's own hook scripts, so a user's own
  off-template hook is left untouched — mirroring the existing hook-FILE orphan prune (files were pruned; event
  keys weren't). `validate.sh` gained the matching assertion that fails on any off-template event still running a
  framework hook (previously it checked template-events-present but not dropped-events-absent, so it passed 210/0
  with the double-bind live). Verified by gap-injection: a stale `Stop → session-end.sh` makes validate fail,
  `--update` prunes it surgically (settings otherwise byte-identical), validate goes green; a user's own
  `Stop → ~/bin/my-hook.sh` is preserved. Found on the sister machine (it carried the stale binding); the mini was
  clean only because a prior `settings.json` wipe had rebuilt it from the `Stop`-less template.

## [3.0.0] - 2026-07-07

Outcome of a framework self-review (reversibility-ordered revamp). Phases 1–4 shipped the
low-regret cleanup; Phase 5 migrated the framework to a **user-global install** (goal resolved to
leverage-per-effort; a single public product) and repositioned it as a public tool.

### Changed

- **User-global install** (`install.sh` ~1900→~1023 LOC): the framework now installs ONCE into
  `~/.claude` — Claude Code loads `~/.claude/{agents,skills,commands,rules}` in every project — instead of
  copying into each project's `.claude/`. New `install_shared_set` REPLACE-copies the framework's own files
  with a **framework-scoped orphan-prune** that provably never removes a user's personal skills/agents
  (prune eligibility is limited to names the framework itself ships). Bare `install.sh` is the canonical
  install; `--update` reconciles `~/.claude` non-interactively under the concurrency lock (the self-heal
  path). Deleted ~840 LOC of per-project machinery (`detect_*`, the 5 `patch_*_in_claude_md`, CLAUDE.md
  emission, backup rotation, interactive menu, per-project markers).
- **Self-heal now covers the shared set**: SessionStart healthcheck Check 7 (agents/skills/commands/rules
  sha256 vs source → heal) plus a `validate.sh --quick` shared-set sync check, so the launchd watchdog
  heals shared-set drift too.
- **Public repositioning**: `README.md`/`INSTALL.md` rewritten from "deploy to each project" to "install
  once, user-global"; `quick-install.sh` is now a `curl … | bash` wrapper delegating to `install.sh`;
  retired the per-project seed fragments (`CLAUDE-DEPLOYMENT.md`, `CLAUDE-minimal.md`,
  `CLAUDE-append-section.md`, `CLAUDE-ultra-minimal.md`, `install-claude-config.sh`).
- **Removed the multi-project fan-out**: deleted `deploy-all.sh` and the per-project deploy-integrity md5
  manifest in `validate.sh` (obsolete under a single install).
- **Scrubbed personal/employer leakage** from the public repo (employer name, a private internal repo,
  `~/local-codebase` paths, project counts, two-Mac framing) across `CHANGELOG.md`/`CLAUDE.md`/
  `CONTRIBUTING.md`/`SECURITY.md`/`validate.sh`.
- **Post-migration currency sweep**: removed the last stale per-project references (`CONTRIBUTING.md`'s
  `--full /path` test flow + "deployed projects" wording, `global-config/README.md`'s `--team-setup`
  framing, the `.gitignore` per-project-marker comment) and repointed `meta-agent`'s lib reads to
  `~/.claude/lib`.

### Added

- **Per-skill observability** (`c262cef`): new `skill_activations` table plus a `Skill`-tool
  branch in `observability/collector.py` (mirrors the existing Task/Agent capture, reads
  `input.skill`). Skill usage was aggregate-only (`tool_usage` counted the `Skill` tool, not
  which skill), so skill pruning could not be data-backed the way agent pruning is. Retroactive
  via `collector.py --full` (backfill verified: deep-read 15, deep-analysis 8, diverge 4, …).
- **Generalized inert-config lint** (`a21d037`): `validate.sh` now fails on any
  `confidence_threshold` / `keyword_weights` / `activation_rules` / `priority_override` key in
  `.claude/lib/*.json`. The framework has no scoring runtime (Claude Code routes on description
  text only), so such keys are always dead. Scoped to structured config, never skill/rule prose;
  gap-injection tested.
- **Attribution invariant** (`daa2341`): `validate.sh` asserts `settings.json.template`
  `attribution.commit` stays empty, tying the no-AI-trailer rule to config so the two surfaces
  cannot silently diverge.
- **lib-orphan reverse-prune** (`44c82fa`): `install.sh` now reverse-prunes retired framework
  lib files (`RETIRED_LIB_FILES`) instead of only copying forward.

### Fixed

- **AI co-author trailer removed** (`daa2341`): `attribution.commit` shipped a
  `Co-Authored-By: Claude` trailer, contradicting the maintainer's no-AI-trailer rule (and the
  mechanism behind `44c82fa`'s stray trailer). Emptied in the template **and** jq-patched into the
  live `~/.claude/settings.json` — `install.sh` copies the template only when the file is absent,
  so a template edit alone is a no-op on existing machines. `attribution.pr` (PR footer) kept.
- **Currency follow-ups** (`435cc20`, `b66c7b4`): finished the `Task`→`Agent` rename in skill
  prose + README doc links to code.claude.com; tightened the meta-agent scaffolding lint so it no
  longer matches its own corrective prose; corrected the expected hook event to `SessionEnd`.

### Removed

- **Dead `activation_rules` scoring block** (`a21d037`): removed the consumer-less
  `confidence_threshold` / `keyword_weights` / `priority_override` block from
  `.claude/lib/agent-templates.json` — the same dead-scoring pattern as the removed
  `activation-keywords.json` (`0b343bb`), hiding in a file the old lint never scanned.

### Notes

- Agents `incident-commander` + `sre-specialist` KEPT as contingency insurance: their 0 recorded
  spawns reflect that the incident-response/SRE domains never arose in this dev work, not a defect.

## [2.10.0] - 2026-05-29

### Added

- **anti-anchoring rule** (`.claude/rules/anti-anchoring.md`): always-on
  divergence habit — name the obvious pick + one non-obvious alternative + one
  trap on every open-ended judgment call; exempts closed/factual work; escalates
  consequential open decisions to `/diverge`.
- **/diverge skill** (`.claude/skills/diverge/SKILL.md`): divergence engine that
  spawns isolated parallel sub-agents under cognitive frames (no cross-anchoring),
  then a separate critic pass scores / flags traps / clusters / deepens. Built on
  the framework's own Task primitives (no npm dependency). The divergent
  complement to `/deep-analysis`, gated by consequence × openness.
- **De-anchoring step** in the 7 open-ended agents (architecture-planner,
  database-architect, devops-automation, frontend-specialist,
  performance-optimizer, sre-specialist, meta-agent) — each names a domain
  obvious/alternative/trap and points to `/diverge` for high-stakes choices.
- **Pre-flight self-gates** on `/execute`, `/investigate`, `/deep-analysis`
  (consequence/complexity-aware "when NOT to invoke" gates).
- **Divergence activation keywords** in `.claude/lib/activation-keywords.json`.
- **validate.sh invariants**: hard-fail if any of the 7 open-ended agents lacks
  the de-anchoring step, or any of the 4 expensive skills lacks a pre-flight gate.
- **install.sh**: `patch_diverge_in_claude_md` (idempotent, dual-format) plus
  `/diverge` in all three CLAUDE.md emitters, so fresh and existing deployments
  both learn the skill.

### Removed

- **Dead `activation-keywords.json` router** (`0b343bb`): removed
  `.claude/lib/activation-keywords.json`. Its `confidence_scoring` weights,
  `thresholds`, and `multi_agent_triggers` "router" were never wired into any
  code path — exhaustive grep confirmed install.sh/quick-install.sh only *copied*
  the file, validate.sh only *existence-checked* it, and `meta-agent.md` read it
  as an authoring reference; the scoring keys (`confidence_scoring`,
  `multi_agent_triggers`, `force_opus_model`, `minimum_activation`) appear in zero
  hooks/scripts. Real agent routing is model-native: Claude Code reads each
  agent's `description:` frontmatter and selects, so tuning those weights changed
  runtime behavior by exactly nothing. Removed the entry from `LIB_FILES`
  (install.sh, quick-install.sh) and `EXPECTED_LIBS` (validate.sh), the
  EXTENSIBILITY.md file tree, and repointed `meta-agent.md` to author new agents
  from the real `description:` router surface. Corrects the false "Confidence
  scoring" capability claimed for this file under the v0.x entry below. Surfaced
  while evaluating Sakana Fugu (arXiv:2606.21228) — wrong-layer for direct
  adoption (trained coordinator weights vs. our prompt/config layer), but its
  critique of hand-designed routers exposed that ours was not only hand-designed
  but inert.

### Fixed

- **Currency follow-up to `c6aa820`**: completed the `Task`→`Agent` rename in the execute/diverge
  skill prose (the agent frontmatter was done in `c6aa820`; `Task` still works as an alias), and
  updated the README Claude Code links from the old `docs.anthropic.com` domain to the canonical
  `code.claude.com/docs`. No behavior change; closes recurring currency-audit residue.
- **Hook + statusline currency fixes** (`7babc5b`): (1) `smart-guard.sh` PermissionRequest
  auto-approve printed a bare `allow` string that Claude Code does not parse, so safe
  read-only tools were never auto-approved — now emits the required
  `hookSpecificOutput.decision.behavior` JSON. (2) `session-end.sh` was bound to `Stop`
  (fires every turn), writing a bogus `session_end` record per response — rebound to
  `SessionEnd`. (3) `statusline.sh` git cache used a fixed `/tmp` path, so concurrent
  sessions in different repos read each other's cached git state — now scoped to
  `session_id`. Verified against code.claude.com/docs/en/{hooks,statusline}.
- **Sub-agent + command currency & safety fixes** (`c6aa820`): from a currency sweep
  of the sub-agents/hooks/skills docs (prompted by the XDA sub-agents eval). (1) SAFETY:
  added `disable-model-invocation: true` to side-effectful commands (`commit-pr`,
  `create-jira`, `new-feature`) — commands are now skills, so Claude could otherwise run
  them (incl. auto-merge/release) autonomously. (2) Removed `TeamCreate`/`TeamDelete` from
  the agent-teams docs (removed in Claude Code v2.1.178; a team now forms on first teammate
  spawn, is experimental via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, one-per-session),
  dropped the unsupported `SendMessage to:"*"` broadcast, and corrected the
  never-available-to-workers list (`TaskStop` → `ScheduleWakeup`/`WaitForMcpServers`).
  (3) Added `LSP` to the `tools:` of architecture-planner/code-quality/performance-optimizer
  (their bodies instruct LSP calls that were failing against the strict allowlist).
  (4) Stripped the inert `Confidence threshold`/keyword-`weight` scaffolding the `meta-agent`
  factory baked into every generated agent (Claude Code routes on `description:` text only;
  completes the `0b343bb` cleanup) + fixed its stale `docs.anthropic.com` WebFetch URLs.
  (5) Renamed the `Task` tool alias → `Agent` across 11 agents. (6) Deleted the dead
  `security-scan` command (shadowed by the skill). (7) Added an independent, isolated-context
  acceptance-verifier to `/execute` Phase 5 (gates REPORT on the Phase-2 `Success:` criteria
  instead of self-grading; double-sourced by the FUGU eval + the sub-agents article) + a
  `verification.md` independent-oracle clause. (8) Added `validate.sh` currency lints
  (tool-in-body ⊆ `tools:`; no meta-agent scaffolding; Phase 5 names an independent verifier),
  each gap-injection tested.
- **Self-heal now survives its own failure mode — watchdog heals, not just detects**
  (`claude-framework-watchdog.sh`, `d6932b6`): the flagship self-heal had a bootstrap
  paradox — the only healer (`install.sh --update`, via `_trigger_heal`) was wired as
  a SessionStart hook *inside* the `.hooks` block that a CLI settings-sync wipes, so
  the wipe removed the healer and the surviving launchd watchdog only *logged* drift
  (a "warning nobody reads" — framework-integrity.md violation). The watchdog now
  parses the `--quick --json` error count and, on `errors>0`, runs `install.sh --update`
  itself, re-validates, and logs `heal_triggered`/`heal_succeeded`/`heal_failed`. The
  wipe-surviving component is now the healer. Verified: `.hooks`→`{}` → watchdog →
  10 hooks + statusLine restored. Corrected the false CLAUDE.md claim that the watchdog
  already re-ran install.
- **`.statusLine` self-heal** (`e1717fe`): the same settings-sync wipe that empties
  `.hooks` also drops `.statusLine` (killing the status bar), but only hooks were in
  the reconcile set, so `install --update` healed hooks and silently left the bar dead.
  Added `.statusLine` to the sync_hooks reconcile (replace-on-drift), a SessionStart
  `statusline_wiring` drift check, and a validate.sh structural assertion — statusLine
  now self-heals like hooks.
- **Atomic, guarded settings.json writes** (`install.sh`, `16f1a75`): routed all three
  reconcile writes through `_atomic_settings_jq` — a unique `mktemp` temp file (no
  cross-process collision) plus non-empty + valid-JSON guards, so the framework's own
  reconcile can never contribute to a wipe even on already-corrupted input. Root cause
  documented: CLI settings-sync (`src/services/settingsSync/index.ts:519`) wholesale-
  replaces settings.json with change-detection suppressed — external CLI behavior, not
  an install bug.
- **Fail-closed secrets guard + daemon PATH + settings.json delete recovery**
  (`4e57582`): (1) `file-protection.sh` used `exit 1`, which is *non-blocking* for
  PreToolUse — the write to a `.env`/`.pem`/etc. proceeded, making the guard theater;
  now `exit 2` with the message on stderr so it actually blocks. (2) The watchdog plist
  had no `EnvironmentVariables`, so a Homebrew-only `jq` was invisible to launchd and
  the jq-gated heal path silently no-oped; added a `PATH` including
  `/opt/homebrew/bin`. (3) A full *delete* of settings.json (vs an emptied `{}`) was
  both undetected (every check is gated on `[ -f settings.json ]`) and unrecoverable
  (`--update` never recreated it); validate.sh now fails on a missing file (→ watchdog
  heals) and sync_hooks recreates it from template. All three verified end-to-end.
- **EXTENSIBILITY.md appendix counts** (`b37e067`): the Project Structure diagram had
  drifted (skills 15→28, agents 12→13, commands 6→13, rules 4→6); the body already
  listed 28 skills correctly — only the appendix tree was stale.
- **Deploy-integrity exclusion for rules-source repos** (`validate.sh`): generalized
  the hardcoded exclusions into an `INTEGRITY_EXCLUDE` list so a downstream repo that
  intentionally ships its own versions of framework-named rules is not flagged as drift.
  Such rules are authoritative overrides (per the framework's own "project rules override
  general ones" model), not drift, so byte-identity against framework source must not flag
  them. Verified by inject-test: without the exclusion, exactly the overridden rules
  drift-fail. _(The whole per-project deploy-integrity check was later retired when the
  framework moved to a single user-global install.)_
- **Reasoning effort default → `xhigh`** (`settings.json.template`, `8d1cb5f`):
  raised `CLAUDE_CODE_EFFORT_LEVEL` from `high` to `xhigh` (the highest persistent
  tier; `max`/`ultracode` are session-only and invalid as env values). Added an
  effort-VALUE check to `validate.sh --quick` and the SessionStart healthcheck —
  both now reject anything outside `low|medium|high|xhigh` and heal it, catching a
  latent live bug where the value had drifted to an ineffective `max`. Added a
  "Reasoning Effort" section to CLAUDE.md (persistent vs. session-only; workflows
  have no persistent on-switch).
- **Measurement-honesty discipline** (`verification.md` + `optimize.md`, `cb91d7a`):
  new "Honest Measurement" rule (distinguish real change from noise, never report
  an unmeasured number, state the basis of quantitative claims) + a noise guard on
  `optimize`'s keep/revert step so within-variance deltas on noisy metrics
  (build-time, bundle-size) are not kept as wins. Lesson extracted from evaluating
  Headroom (the tool itself was rejected as wrong-layer).
- **Removed hardcoded validate check-count from README** (`33f3b4e`): the
  verify-installation example hardcoded a `--quick` count that went stale on every
  change; replaced with "count auto-discovered, scales with deployed projects" so
  it cannot drift again.
- **Memory-freshness detector now runs in `--quick`** (`d62a2ac`): the runtime
  freshness check lived below the quick-mode `emit_and_exit`, so the watchdog's
  automated `--quick --json` run never executed it. Extracted to a shared
  `check_memory_freshness` called from both quick and full mode; fixed the
  watchdog header comment ("Full" → "Quick" validation).
- **Project-memory backup** (`claude-framework-watchdog.sh`, `5b17dba` + freshness
  wiring fix): the watchdog backed up `~/.claude/hooks` + `settings.json` but NOT
  persistent memory (`~/.claude/projects/*/memory/*.md`) — critical state with no
  snapshot or restore path (framework-integrity.md violation). Added watchdog
  Task 4b (separate `memory-YYYYMMDD.tgz`, relative paths restored with
  `-C ~/.claude`, shallow `projects/*/memory` glob excluding the ~100s-MB JSONL,
  atomic verify-before-promote, `memory-latest.tgz` symlink) + Task 4c retention
  (keep-floor newest 3 regardless of age). Restore steps documented in CLAUDE.md.
  (The `--quick` wiring of the freshness detector was a follow-up — see `d62a2ac`
  above.)
- **Comprehensive md5 deploy-integrity check** (`validate.sh`, `68e3530`):
  replaced the sampled diff-based check (5 projects, content-only) with an md5
  manifest verifying the full deployable set (agents, lib, rules,
  `skills/<name>/**`, commands) is present and identical across ALL deployed
  projects (5 sampled in `--quick` for watchdog speed). Detects both content
  drift AND missing files — the old per-file check was guarded by
  `[ -f "$dst" ]` with no else, so a project missing an entire skill/rule
  passed clean.
- **/diverge wording + cross-reference** (`bf0d76f`): install.sh CLAUDE.md
  emitters now say "isolated parallel sub-agents" (not the clumsy coinage
  "framings"); added the reverse `/diverge` row to `/deep-analysis`'s
  Integration table so the divergent↔convergent cross-reference is bidirectional.

- Documentation count drift reconciled to true on-disk state: skills 26 → 28
  (backfilled `context-escalation`), rules "Four" → 6 (backfilled
  `framework-integrity`) in README.
- **Skill execution model**: removed `context: fork` from `diverge` and `execute`
  so they run inline and can spawn the parallel sub-agents their protocols require
  (forked subagents are denied the Agent/Task launcher per Claude Code docs, so both
  silently degraded — diverge to sequential-single-context, execute to no delegation).
  `investigate` keeps fork (its core RCA uses only subagent-available tools), with
  Phase 1 realigned to evidence-first + return-questions. validate.sh now guards that
  spawner skills (diverge, execute) stay un-forked.
- Added `__pycache__/` and `*.pyc` to `.gitignore` (observability tooling bytecode).

## [2.9.5] - 2026-05-26

### Added

- **context-escalation skill** (`.claude/skills/context-escalation/SKILL.md`):
  Explicit-level policy for handling context pressure in long-horizon
  sessions. Five interventions from cheapest to most aggressive:
  L1 truncate → L2 drop-redundant-reads → L3 fork-subagent → L4 /compact →
  L5 handoff + /save-session. Names a discipline that's otherwise applied
  reflexively, so a session uses cheap interventions before hard-cliff
  compaction.

  Inspired by [DCI-Agent-Lite](https://github.com/DCI-Agent/DCI-Agent-Lite)'s
  context-manager pattern (truncation → compaction → summarization in
  escalating levels), adapted to Claude Code's existing primitives
  (`/compact`, `handoff`, `/save-session`, Agent tool). Borrows the
  structural pattern, not the implementation.

### Considered but not adopted

- **Minimalist single-system-prompt harness** (DCI-Agent-Lite's other notable
  pattern — a 1.7KB system_prompt.txt as the entire agent driver). Not
  applicable to a multi-agent framework where 13 specialized agents need
  distinct system prompts. Documented here so the choice is explicit rather
  than overlooked.

### Validation context

External validation of the framework's bash-native architecture: VentureBeat
[Your AI agents need a terminal, not just a vector database](https://venturebeat.com/orchestration/your-ai-agents-need-a-terminal-not-just-a-vector-database)
argues the case for terminal-tool-native agentic search over vector-DB RAG.
This framework has been in that paradigm since 2.0 — no integration needed,
but the reading reinforces the architectural choice.

## [2.9.4] - 2026-05-06

### Changed (public-repo hygiene)

Made the framework safe to publish under a public repo without leaking
maintainer-specific identifiers (macOS username, hardcoded user paths,
private project names):

- **LaunchAgent Label is project-scoped**: `com.claude-code-agents.framework-watchdog`.
- **Plist filename matches the Label** for consistency.
- **Plist source uses `__HOME__` placeholder** instead of any user path.
  `install.sh` substitutes `__HOME__` → `$HOME` at install time.
- **healthcheck.sh + watchdog.sh repo-resolution**: rely solely on
  `~/.claude/.framework-path` marker (written by `install.sh` on every install
  mode). No hardcoded probe paths. If marker is missing, scripts exit cleanly.
- **CLAUDE.md**: daemon Label reference uses the project-scoped form.
- **History rewrite (git-filter-repo)**: removed legacy hardcoded paths,
  user-scoped Label remnants, machine hostname leakage in author email,
  and personal project names from earlier commit messages and diffs. Author
  email normalized via mailmap to a single canonical noreply form.

Functional behavior is unchanged.

## [2.9.3] - 2026-05-01

### Fixed

- **sync_hooks orphan detection**: `sync_hooks()` now reverse-prunes deployed
  hooks that no longer exist in source. Previously the function copied forward
  but never cleaned up, so files removed from source persisted in
  `~/.claude/hooks/` indefinitely (hit twice this week — `pre-commit.sh` from
  an earlier framework version, and `stop-phrase-guard.sh` after v2.9.2
  removal both required manual rm). With this fix, install.sh closes the
  third and final sync direction:
  - **forward-sync** (always): copy source → deployed
  - **drift-correct** (v2.9.0): replace user's hook events when template differs
  - **reverse-prune** (v2.9.3): remove deployed files no longer in source
  Verified: `touch ~/.claude/hooks/fake-orphan.sh; ./install.sh --update` →
  "Pruned orphan hook fake-orphan.sh (no longer in source)" → file removed.

## [2.9.2] - 2026-04-26

### Removed

- **stop-phrase-guard hook**: removed after evidence-based evaluation. 31 violations
  logged across 3 days; 90% were the single phrase "want me to" — the hook was
  effectively a one-pattern filter wearing a 38-pattern costume (16 of 38
  patterns never fired). Substring matching produced false positives on
  legitimate destructive-action confirmations ("want me to push?") that the
  Claude Code system prompt and project deployment policies explicitly require.
  No measured benefit. The pattern conflicts with the system prompt's
  "transparently communicate the action and ask for confirmation" guidance.
- **install.sh stale-lock + backup rotation** also landed (see 2.9.1 entry below
  for accumulated 4th-pass fixes).

### Fixed (4th audit pass)

- **install.sh stale-lock recovery**: `update_installation()` now writes its
  PID into the lock dir and treats locks with dead/missing PIDs as stale.
  Prevents the framework from deadlocking after a killed install.
- **install.sh backup rotation**: `backup_existing()` keeps the 3 most-recent
  `.claude-backup-*` directories per project, prunes older. Cleaned up 3,637
  stale dirs across 88 deployed projects (~39MB freed).

## [2.9.1] - 2026-04-24

### Self-Healing Framework Hardening

Follow-up to 2.9.0 addressing gaps found by a pre-deploy deep-analysis pass.

### Fixed

- **sync_hooks `permissions` reconciliation**: template permissions now propagate to user `~/.claude/settings.json` on install, not just hook events and env vars. Previous add-if-missing skipped drifted permissions.
- **Install concurrency lock**: `install.sh --update` now acquires a non-blocking lock at `~/.claude/.install.lock.d`. Prevents healthcheck + watchdog racing on `jq` read-modify-write of settings.json.
- **Watchdog fsck filter**: tightened from `error|corrupt|missing|bad` to only match real object corruption. Benign reflog residue and dangling commits no longer alert.
- **Plist path templating**: `install_watchdog()` sed-substitutes a placeholder in the LaunchAgent plist with the caller's `$HOME` at install time so the daemon works for any user. (Hardened in 2.9.4 to use `__HOME__` placeholder explicitly — see 2.9.4 entry.)
- **Doc drift**: CLAUDE.md, MEMORY.md, README.md, EXTENSIBILITY.md — fixed stale counts (9 hooks → 10, 4 rules → 5) and version strings.
- **Framework marker in source repo**: `write_framework_version_marker()` now skips when CWD is the source tree; added `.gitignore` entries for `.claude/.framework-version` and `.claude-backup-*/` as defense in depth.
- **Stop-phrase-guard output**: violation message now written to stderr so Claude Code's Stop-hook UI displays the actual matched phrase instead of "No stderr output".

### Added

- **deploy-all.sh**: driver for batch install across local projects with per-project pre-install tarballs, `--dry-run`, `--continue-on-error` (default), `--halt-on-error`, `--only <name>`, and JSONL failure manifest. _(Retired when the framework moved to a single user-global install.)_
- **.claude/.framework-version marker**: written into every deployed project (version + short SHA + UTC timestamp). Enables targeted re-deploy and staggered rollout.
- **Watchdog claude-obs.db regeneration**: when the DB is missing, watchdog runs `python3 collector.py` with a 120s timeout. Closes the "deferred_regen" path logged by the healthcheck hook.

## [2.9.0] - 2026-04-23

### Self-Healing Framework

Introduces an end-to-end reconciliation loop so framework state can no longer silently drift.

### Added

- **SessionStart healthcheck hook** (`global-config/hooks/session-start-healthcheck.sh`): runs on every session start with a <2s budget. Checks env keys, hook sha256s, analytics file presence, hook event wiring vs template. On drift: logs to `~/.claude/analytics/framework-health.jsonl` and forks `install.sh --update` in background. Exit 0 always (never blocks session start).
- **launchd watchdog daemon** (`global-config/daemon/claude-framework-watchdog.sh` + plist): hourly `validate.sh --quick --json`, `git fsck`, daily rolling `git bundle` snapshots to `~/.claude/snapshots/`, daily userconfig tarballs, 7d retention.
- **validate.sh modes**: `--quick` (~0.08s, checks `~/.claude/` only), `--json` (machine-readable for daemon consumption), `--heal` (invokes `install.sh --update` on detected drift).
- **validate.sh structural checks** (always-on): SessionStart template non-decorative regression guard, user-settings hook-wiring drift vs template, watchdog daemon loaded, snapshot freshness (<48h).
- **.claude/rules/framework-integrity.md**: no decorative hooks; auto-reconciled state; every critical directory has a snapshot with restore path.
- **Self-Healing section in CLAUDE.md**: describes the fast/slow paths, diagnostic streams, and restore procedures.
- **install.sh install_watchdog() + write_framework_path_marker()**: wired into `--full`, `--update`, `--team-setup`, `--repair`.
- **install.sh inode guards**: `-ef` checks in `download_or_copy()` and three direct `cp` sites make `--update` idempotent when run inside the source repo.

### Fixed

- **sync_hooks reconciliation** (was add-if-missing): template hook events now REPLACE user's version on drift, not just on missing-key. Previously left SessionStart stuck on a decorative echo and `stop-phrase-guard.sh` disabled for weeks even though present on disk.
- **sync_hooks env merge**: environment variables from `settings.json.template` now merged into user `~/.claude/settings.json`. Previously lost across installs — e.g., `CLAUDE_CODE_EFFORT_LEVEL=high` never reached users.

## [2.3.0] - 2026-02-12

### Quality, Coordination & Extensibility Release

This release fixes credibility gaps between documentation and reality, adds missing infrastructure, and incorporates improvements from the latest Claude Code features.

### Fixed

- **False telemetry/metrics claims**: Removed fabricated metrics ("90ms activation", "30% productivity", "85% accuracy") from README.md
- **Telemetry references**: Marked telemetry as "Planned" across README.md, CLAUDE.md, and sdlc-patterns.md — no longer claimed as existing
- **EXTENSIBILITY.md directory references**: Fixed all `.claude/subagents/` references to `.claude/agents/`
- **EXTENSIBILITY.md version**: Updated from 2.2.0 to 2.3.0
- **meta-agent.md broken tools**: Removed non-existent `firecrawl` MCP tools, added `WebSearch`
- **meta-agent.md URLs**: Fixed documentation URLs from `docs.claude.com` to `docs.anthropic.com`
- **meta-agent.md telemetry**: Replaced "Generate Telemetry Hooks" with "Define Success Criteria"
- **install.sh error handling**: `install_agent()` and `install_lib_file()` now check return codes from `download_or_copy()`

### Added

- **validate.sh**: New validation script checking all agent files (frontmatter, sections), lib files (JSON validity), skills (SKILL.md), MCP config, slash commands, and cross-references
- **Agent coordination protocol** (`.claude/lib/agent-coordination.md`): Formal protocol for sequential handoffs, parallel coordination, review chains, error recovery, and priority rules
- **.claude/rules/ directory**: Auto-loaded rules for security and code quality
  - `security.md`: Secrets, input validation, auth, HTTP security, dependencies
  - `code-quality.md`: Dead code, function design, error handling, naming
- **`/review-pr` slash command**: PR review for code quality, security (OWASP), testing, documentation
- **`/security-scan` slash command**: Security scanning with secrets detection, dependency checks, OWASP patterns, file permissions
- **install.sh preflight checks**: Write permissions, disk space, source directory validation
- **install.sh rules installation**: New `install_rules()` function and `.claude/rules/` directory creation
- **install.sh error counting**: `install_errors` counter in `install_full()`
- **EXTENSIBILITY.md meta-agent listing**: Added missing `meta-agent` to agents list

### Changed

- README.md "Enterprise Ready" description updated from "telemetry and monitoring" to "extensible architecture"
- README.md `history/` directory description updated from "Telemetry & learning" to "Session history (planned: telemetry)"
- README.md "Why Claude Agents?" section updated to reference extensibility instead of telemetry
- CLAUDE.md "Continuous Improvement" section marked as planned
- Commands README updated with `/review-pr` and `/security-scan` documentation

---

## [2.2.0] - 2025-10-28

### 🌐 MCP Integration & 4-Way Extensibility

This release introduces **Model Context Protocol (MCP)** integration, adding external tools and data sources to the Claude Code platform. Combined with Skills, Slash Commands, and Subagents, this creates a comprehensive 4-way extensibility system.

### Added

#### MCP-Powered Skills
- 🟢 **library-docs** skill (uses context7 MCP server)
  - Fetch up-to-date documentation for 100+ libraries
  - Support for React, Next.js, Vue, MongoDB, Supabase, PostgreSQL, and more
  - Topic-focused documentation retrieval
  - Version-specific query support
  - Integration with documentation-maintainer agent

- 🧠 **deep-analysis** skill (uses sequential-thinking MCP server)
  - Structured multi-step reasoning for complex problems
  - Up to 31,999 thinking tokens (vs 4,000 standard)
  - Hypothesis generation and verification
  - Course correction and branching
  - Integration with architecture-planner and performance-optimizer agents

#### Comprehensive Documentation
- 📘 **EXTENSIBILITY.md** - Complete extensibility guide
  - Comprehensive overview of all four mechanisms
  - Skills (Blue): Knowledge & methodology
  - MCP (Green): External tools & data
  - Slash Commands (Red): User-triggered workflows
  - Subagents (Orange): Isolated task execution
  - Decision matrix for choosing mechanisms
  - 5 integration patterns with real examples
  - Best practices for each mechanism
  - Validation and testing guidance

#### Enhanced Documentation
- 📝 **CLAUDE.md Updates**
  - Added comprehensive MCP Integration section
  - Documentation of both MCP servers (context7, sequential-thinking)
  - MCP + Agent integration examples
  - Configuration guidance
  - Usage patterns and examples

- 📖 **README.md Updates**
  - Version badge updated to 2.2.0
  - Skills badge updated to 6 included
  - New MCP badge added
  - Added "MCP Integration" to key features
  - Added "4-Way Extensibility" feature
  - New MCP Integration section with examples
  - Four extensibility mechanisms diagram
  - Architecture updated to show MCP-powered skills
  - Links to EXTENSIBILITY.md

### Enhanced

- 🔌 **Four Extensibility Mechanisms**
  - **Skills**: Modular knowledge packages (6 included)
  - **MCP**: External integrations (2 servers configured)
  - **Slash Commands**: User-triggered workflows
  - **Subagents**: Isolated execution (11 agents)

- 🎓 **Skills System**
  - Now includes MCP-powered skills
  - Clear integration patterns with MCP servers
  - Enhanced agent-skill collaboration
  - Updated power combos showing MCP usage

- 📊 **Integration Patterns**
  - Skill + MCP: library-docs fetches external data
  - Skill + Agent: deep-analysis guides architecture-planner
  - MCP + Agent: External tools enhance agent capabilities
  - Full Integration: All mechanisms working together

### Technical Details
- **New Skills**: 2 MCP-powered (library-docs, deep-analysis)
- **Total Skills**: 6 (skill-creator + git-workflow + code-review-checklist + deployment-runbook + library-docs + deep-analysis)
- **MCP Servers**: 2 (context7, sequential-thinking)
- **Documentation**: 800+ line extensibility guide
- **Architecture**: 4-way extensibility system

### MCP Configuration

Add to Claude Code settings:

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@context7/mcp-server"]
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

### Benefits

**For Developers:**
- Access up-to-date library documentation on-demand
- Deep reasoning for complex architectural decisions
- External tool integration via MCP
- Clear decision matrix for extensibility choices

**For Organizations:**
- Comprehensive extensibility options
- Integration with external APIs and services
- Structured reasoning for critical decisions
- Complete documentation of all mechanisms

### Skills + MCP + Agents Integration

| Agent | Skill | MCP Server | Result |
|-------|-------|------------|--------|
| **architecture-planner** | **deep-analysis** | sequential-thinking | Structured architectural decisions |
| **documentation-maintainer** | **library-docs** | context7 | Documentation using library patterns |
| **performance-optimizer** | **deep-analysis** | sequential-thinking | Root cause analysis |

### What's Next?

See **[EXTENSIBILITY.md](./EXTENSIBILITY.md)** for:
- Complete guide to all four mechanisms
- Decision matrices and integration patterns
- Real-world examples from this project
- Best practices and validation guidance

---

## [2.0.0] - 2024-10-16

### 🚀 Major Release - Enterprise Agent System

This release transforms Claude Agents into a comprehensive enterprise-grade SDLC/SSDLC agent system with natural language activation.

### Added

#### Core System
- ✨ **11 Specialized SDLC/SSDLC Agents**
  - `architecture-planner` - System design and API specifications
  - `code-quality` - Code review and quality metrics
  - `security-auditor` - OWASP compliance and vulnerability scanning
  - `test-automation` - Comprehensive test generation
  - `performance-optimizer` - Profiling and optimization
  - `devops-automation` - CI/CD and deployment
  - `documentation-maintainer` - Auto-documentation with Haiku
  - `database-architect` - Schema design and query optimization
  - `frontend-specialist` - UI/UX implementation
  - `api-backend` - Backend service development
  - `incident-commander` - Production emergency response

#### Meta-Agent System
- 🤖 **Enhanced Meta-Agent v2.0**
  - SDLC/SSDLC phase awareness
  - Natural language activation patterns
  - Security-first design principles
  - Intelligent tool selection
  - Multi-agent orchestration
  - Cost optimization (Haiku/Sonnet/Opus)

#### Supporting Infrastructure
- 📚 **Agent Templates Library** (`agent-templates.json`)
  - 13 pre-built agent templates
  - Activation keywords and patterns
  - Tool configurations
  - Best practices embedded

- 📋 **SDLC Patterns Reference** (`sdlc-patterns.md`)
  - Phase detection patterns
  - Multi-agent workflows
  - Priority rules
  - Collaboration strategies

- 🔤 **Activation Keywords Database** (`activation-keywords.json`)
  - Natural language patterns
  - Confidence scoring
  - Technology-specific keywords
  - Multi-agent triggers
  - _Correction: this scoring/router logic was never wired into any executing
    code path (agent routing is model-native via `description:` fields). The file
    was removed as dead config — see **Removed** under [2.10.0]._

#### Installation System
- 🛠️ **Intelligent Installer** (`install.sh`)
  - Detects existing components
  - Multiple modes (minimal, full, repair, update)
  - Automatic backups
  - Progress tracking
  - Verification and rollback

- 📦 **Deployment Options**
  - One-liner installation from GitHub
  - Multiple CLAUDE.md variants
  - Merge-friendly configurations
  - Ultra-minimal options

### Changed
- 🔄 **Complete Architecture Overhaul**
  - From 4 basic agents to 11 specialized agents
  - From manual commands to natural language activation
  - From single agent to multi-agent collaboration
  - From fixed models to intelligent selection

### Enhanced
- 💡 **Natural Language Processing**
  - Auto-activation based on conversation context
  - Weighted confidence scoring _(never wired into any code path — see **Removed** under [2.10.0]; real routing is model-native via agent `description:` fields)_
  - Context-aware agent selection
  - Phrase pattern matching

- 💰 **Cost Optimization**
  - Haiku for documentation (95% savings)
  - Sonnet for standard development
  - Opus for security and critical tasks
  - ~70% overall cost reduction

- 🔒 **Security Improvements**
  - OWASP Top 10 compliance
  - DevSecOps practices
  - Automatic security scanning
  - SOC2/ISO 27001 considerations

### Technical Details
- **Lines of Code**: 5,000+
- **Configuration Files**: 15+
- **Agent Definitions**: 11
- **Test Coverage**: Comprehensive
- **Performance**: Keyword-based activation

### Breaking Changes
- Old agent format deprecated
- Manual command invocation replaced with auto-activation
- Directory structure reorganized

### Migration Guide
Users can upgrade using:
```bash
./install.sh --update
```

## [1.0.0] - 2024-10-01

### Initial Release
- Basic 4-agent system
- Manual router
- Simple cost tracking
- Basic installation script

## [2.1.0] - 2024-10-28

### 🎓 Skills System Integration

This release adds a comprehensive skills system that extends the agent framework with modular knowledge packages, enabling users to create custom domain expertise alongside the existing agent system.

### Added

#### Skills System
- ✨ **Skills Infrastructure**
  - `.claude/skills/` directory for modular knowledge packages
  - Integration with existing 11-agent system
  - Progressive disclosure (metadata → SKILL.md → bundled resources)
  - Skill creation, validation, and packaging tools

- 🛠️ **skill-creator Skill**
  - `init_skill.py` - Create new skills from templates
  - `package_skill.py` - Validate and package skills for distribution
  - `quick_validate.py` - Quick validation during development
  - Comprehensive skill creation methodology (6-step process)

#### Demonstration Skills
- 📚 **git-workflow**
  - Git best practices and branching strategies
  - Commit message guidelines (Conventional Commits)
  - Pull request workflows
  - Merge conflict resolution
  - Git Flow, GitHub Flow, Trunk-Based Development

- 🔍 **code-review-checklist**
  - Systematic code review guidelines
  - 10-category review framework
  - Security checklist (OWASP Top 10)
  - Performance anti-patterns
  - Team collaboration best practices
  - Complements code-quality agent

- 🚀 **deployment-runbook**
  - Deployment strategies (blue-green, canary, rolling)
  - Pre/post-deployment checklists
  - Health check automation scripts
  - Rollback procedures
  - Troubleshooting guides
  - Complements devops-automation agent

#### Documentation
- 📖 **Comprehensive Skills Documentation**
  - Updated CLAUDE.md with Skills System section
  - Agent vs Skills comparison guide
  - Skills integration examples
  - README.md with skills features
  - Updated architecture diagrams

- 📘 **Skills README** (`.claude/skills/README.md`)
  - What skills are and when to create them
  - Skills vs agents comparison
  - Step-by-step creation guide
  - Integration patterns
  - Real-world examples

### Enhanced

- 🎯 **Agent-Skill Integration**
  - Skills complement agents for powerful workflows
  - Examples: code-quality + code-review-checklist
  - Clear guidance on when to use agents vs skills
  - Progressive disclosure for efficient context management

- 📊 **Architecture**
  - Updated to show dual agent + skills system
  - Clear separation of concerns
  - Modular, extensible design

### Technical Details
- **New Skills**: 4 (skill-creator + 3 demonstrations)
- **Scripts Added**: 3 Python utilities
- **Documentation Pages**: 5+ comprehensive guides
- **Directory Structure**: `.claude/skills/` with organized subdirectories

### Benefits

**For Users:**
- Extend capabilities with domain-specific knowledge
- Create reusable, shareable skill packages
- Bundle scripts, references, and assets
- Complement agents with specialized expertise

**For Organizations:**
- Codify company-specific knowledge (APIs, schemas, processes)
- Standardize workflows across teams
- Share best practices through skills
- Reduce onboarding time with packaged knowledge

### Skills vs Agents

| **Agents** | **Skills** |
|------------|------------|
| Auto-activating task executors | Modular knowledge packages |
| Execute SDLC workflows | Provide domain expertise & tools |
| Examples: security-auditor, test-automation | Examples: git-workflow, brand-guidelines |

---

## Upcoming Features

### [3.0.0] - Future
- VS Code extension
- Web dashboard for telemetry
- AI model fine-tuning
- Custom agent marketplace
- Enterprise dashboard
- Advanced telemetry analytics