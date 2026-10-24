# Shared framework maintenance memory

This is public repository memory. Keep personal configuration, credentials, private
project names, machine paths and session transcripts in private user memory. Read
AGENTS.md and relevant source before relying on these notes.

## Architecture

- One repository supports Claude Code and Codex. `.claude/` remains canonical domain
  source; `codex/overrides/` contains handwritten Codex runtime procedures.
- Claude installs user-global with `./install.sh` into `~/.claude`. Codex uses
  `./install-codex.sh --user`: skills in `~/.agents/skills`, native profiles/resources
  in `~/.codex`, and a hash-owned instruction block in AGENTS.md.
- No copies in every project are required. Codex `--project` is an explicit alternative.
  Alternate profiles, project instructions, disabled skills and host features affect use.
- Source inventory: 30 skills, 12 executable command templates and 13 specialists.
  The command directory also contains a README, not a thirteenth workflow.
- Codex builds 42 workflow skills plus 13 specialist guides (55 bundles), and 13
  native TOML definitions. Namespaced guides avoid collisions with built-ins.
  51 are implicit; commit-pr, create-jira, new-feature and ui-guidelines stay explicit-only.
- An override in `codex/overrides/` shadows its canonical source. The commit-pr override
  once diverged from the corrected neutral command (review before commit); it and the
  review-pr override were removed so one publication contract and one review contract
  export to both editions.
- Delivery skills (delivery, repo-context, verified-handoff), the delivery rule and
  commit-pr can be updated in an existing Claude home with `scripts/install-delivery.py`
  (hash manifest, explicit `--baseline` adoption, no settings/hooks). The broad
  installer can later rewrite the same paths; the delivery installer then refuses.
- Availability of a workflow is not an execution or an enforced gate. Report delivery
  states only from receipts; no watcher, daemon, auto-merge or hook trust exists.
- Native custom routing is host-dependent. Guide discovery is verified; guide prose
  does not enforce a native sandbox. Models and approval policy are inherited.
- Code-quality guidance is right-sized and reuse-first: the `code-quality` rule, the
  `code-quality` agent and the `code-review-checklist` skill ask for the smallest complete
  change, reuse before new code (project helper → platform/stdlib → installed dependency),
  and responsibility/coupling-based splitting instead of line-count triggers (the former
  `>20`/`< 40` line rules are gone). Findings cite concrete consequences, not invented
  metrics; the rule opening reads as instruction guidance, not guaranteed enforcement. The
  Codex edition inherits it through the generated `rules.md`.
- Quality outcomes share one vocabulary across the `code-quality` agent, `/quality-gate`,
  `/review-pr`, `code-review-checklist` and the verification rule: findings are
  runtime-reproduced, source-proven, unverified hypotheses or nonblocking suggestions;
  missing required evidence is INCOMPLETE, an actual failure FAIL, a predeclared
  inapplicable check NOT_APPLICABLE, and PASS covers only the declared completed scope.
  No grades, synthetic indices or unmeasured metrics. Task-specific acceptance lives in
  `delivery/references/acceptance-by-task.md`; optional repository measurements and their
  disclosure/sandbox limits in `delivery/references/repository-measurements.md`. The
  `verified-handoff` v1 receipt schema is unchanged.
- Opt-in agent-guidance evaluation is documented in
  `verified-handoff/references/agent-evaluation.md`: baseline vs candidate instruction
  files, a six-case synthetic corpus, a caller-supplied trusted adapter, behavioural
  graders outside solver inputs; a known candidate failure or regression is FAIL, else
  unavailability or source drift is INCOMPLETE, else PASS for the declared selected scope;
  unknown never zero, requested and observed model kept separate, source identity as
  digests (no Git SHA field). Provider runs are opt-in, never automatic in CI or the
  ordinary gate (offline fake-adapter tests run in CI); process separation is not an OS sandbox; raw results
  stay private; a pilot is not efficacy proof. Inventory counts are unchanged.
- `deep-read` and `investigate` (and their shadowing `codex/overrides/` bodies, so both
  editions) carry a shared evidence-reporting convention: label findings observed (source
  inspection vs an actual runtime capture — a source read is not proof the runtime path
  ran), derived from named premises, or inferred and unverified; preserve unknown/contradictory
  evidence and truncated/partial coverage; bound negatives to the searched/read scope; page a
  truncated read rather than promote a preview; report behaviour checks apart from static
  conclusions. Reporting guidance only — no new phase, gate, schema or runtime; the existing
  proof/consent/coverage gates and the `verified-handoff` v1 schema are unchanged. Adapted in
  our own words from REA's reporting practices, not its runtime.

## Safety and verification

- Never reuse Claude's settings/installer pipeline for Codex or translate provider
  model aliases/tool lists/permission syntax into invented Codex configuration.
- Manifest hashes authorize adapter updates/removal. Reject foreign/modified files,
  malformed instruction markers and symlink destinations. Missing owned files can be
  explicitly repaired. Rollback covers caught errors, not power-loss recovery.
- Native hook trust belongs to the user. Direct-patch protection inspects all
  add/update/delete/move destinations; it is not an arbitrary shell/MCP sandbox.
- Run `python3 -m unittest discover -s tests/codex -v` and
  `python3 tests/codex/mutations.py`. Discovery also loads every portable resource test
  in `tests/delivery/` through a bridge, so CI runs new cases without a list edit. Native discovery is explicitly skipped without
  a CLI; do not call that an end-to-end pass. Claude checks remain independent:
  `./validate.sh` and `bash tests/gap/run.sh --prove --jobs 4`.
- Test failure/destructive paths in disposable homes/projects; `validate.sh` observes
  only — `--heal` is retired (it performs no repair and exits nonzero), so it is never an
  acceptance gate and repair stays an explicit foreground `install.sh --update`.
  Real-machine validation requires the user's requested scope and preservation of
  personal configuration.
- Validate Python resources in a clean virtual environment populated only from declared
  dependencies. A passing system-Python run can hide missing dependencies; the first
  Linux Codex CI run caught an undeclared Requests import in the bundled health checker.
- Consult [FEATURES](codex/FEATURES.md) for current capability limits; the 2026-10-12
  acceptance snapshots ([review](docs/archive/codex-2026-10-12/REVIEW.md),
  [global validation](docs/archive/codex-2026-10-12/GLOBAL-VALIDATION.md)) are archived
  historical records under [docs/archive/](docs/archive/README.md). Dashboard, watchdog, notifications,
  the Claude statusline renderer, Claude's unconditional auto-lint and snapshots remain
  unported (an opt-in, user-approved post-edit lint now exists — see below). MCP
  examples are disabled and Codex hooks are opt-in. The status bar counterpart is an
  opt-in `tui.status_line` example of built-in footer IDs (context remaining, native
  session token counters, usage limits, branch/directory; never auto-merged into
  config; width clips trailing items) plus instruction guidance to title the current task `SDLC | <task>` where a
  native rename capability exists; the marker means guidance loaded, not checks passed.
- Opt-in post-edit lint: the installer ships `.codex/framework/lint.py` beside the hook
  but never creates or trusts the registry. Approval is always the single owner-global
  `~/.codex/framework/lint-projects.json` (both user AND project installs; a project-local
  registry is never consulted, and the literal unresolved path is used for the symlink/
  ancestor checks so a swapped-in symlinked ancestor is caught, not resolved away).
  Registry: owner-only regular non-symlink file, version exactly `1` (JSON `true` rejected),
  no unknown top-level or entry keys, no duplicate roots, argv of absolute literal strings,
  integer timeout 1-30. Lint runs only on a RECOGNIZED positive edit result (canonical
  apply_patch success text or structured `{"success": true}`); explicit failure runs
  nothing and emits NO feedback (no lint, no reminder), while an unknown/missing/unrecognized
  result runs nothing but falls back to a manual quality-gate reminder that does not assert
  success. On an approved exact-root match (nested cwd not
  approved; relative/NUL/invalid cwd rejected) the argv runs directly — no shell, no
  interpolation, no `--fix` — stdio discarded, in its own process group under the 40 s
  PostToolUse budget. A timeout, or a leader that exits while descendants it spawned are
  still running, is reported as timed-out/incomplete — never passed — with best-effort
  TERM→KILL cleanup and no containment promise. Output carries only a static status and the
  exit code. The PreToolUse credential guard is unchanged. Eight lint mutation controls
  (five original + three remediation: central owner-global registry, recognized-success
  gate, incomplete-not-pass) plus the nine framework controls, all gap-tested.
- `scripts/framework-status.py` is a read-only cross-integration status: repository SHA
  (its own HEAD, resolved while stripping inherited Git selectors like `GIT_DIR` so a
  foreign repo in the environment cannot misattribute it), each integration's installed
  source SHA and owned-integrity state (not_installed/clean/drift/error) via the existing
  `framework.py --check` and `install-delivery.py --check` logic, native CLI presence, Codex
  hook config (trust UNKNOWN → `/hooks`) and MCP connectivity UNKNOWN. It passes the
  REQUESTED scope to the checker: a requested-vs-installed scope mismatch is an `error`,
  never silently relabelled clean. `--user` default, `--project PATH`, `--claude-home PATH`,
  `--json`; exit 0 clean/absent, 1 drift, 2 error. It never writes — not even a source
  `.pyc` (`sys.dont_write_bytecode` is set before importing the checker) — locks, repairs,
  runs the broad installer/validate, executes project scripts, probes networks or reads
  config/auth/settings/secrets.

## Evidence and publishing

- Initial adaptation input: `509d282a195cc7a0e3b4d63b51b5f791be519eed`. Retain
  historical audit inputs and record subsequent verification separately.
- Past acceptance snapshots are historical records, not current checks. The 2026-10-12
  Codex audit/review/global-validation/worklog live under
  `docs/archive/codex-2026-10-12/` and the v2.1 skills summary under
  `docs/archive/legacy-skills-integration.md` (see `docs/archive/README.md`). Keep their
  dates, SHAs and counts verbatim; current inventory and limits stay in README, INSTALL
  and `codex/FEATURES.md`.
- Global discovery passed in two unrelated repositories and a nested directory.
  Actual Codex/Claude reviewers reproduced one synthetic boundary defect without
  changing fixture source. This is representative validation, not every workflow.
- Fetch before publishing: another machine can advance main. Preserve published SHAs;
  fast-forward or merge, never force-push or rebase existing citations.
- Stage explicit task paths; do not add unrelated recordings, memory dumps or credentials.
  Use Conventional Commits and the maintainer's no-AI-attribution preference.
- Review the exact commit independently and verify GitHub's resulting head and CI.
  Command-scoped gh HTTPS credentials can work when SSH is unavailable; preserve the
  remote URL. A push is not a release; green older CI is not a current gate.
