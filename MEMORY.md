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
  52 are implicit; commit-pr, create-jira and new-feature stay explicit-only.
- An override in `codex/overrides/` shadows its canonical source. The commit-pr override
  once diverged from the corrected neutral command (review before commit); it was
  removed so one publication contract exports to both editions.
- Delivery skills (delivery, repo-context, verified-handoff), the delivery rule and
  commit-pr can be updated in an existing Claude home with `scripts/install-delivery.py`
  (hash manifest, explicit `--baseline` adoption, no settings/hooks). The broad
  installer can later rewrite the same paths; the delivery installer then refuses.
- Availability of a workflow is not an execution or an enforced gate. Report delivery
  states only from receipts; no watcher, daemon, auto-merge or hook trust exists.
- Native custom routing is host-dependent. Guide discovery is verified; guide prose
  does not enforce a native sandbox. Models and approval policy are inherited.

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
- Test failure/destructive paths in disposable homes/projects; `validate.sh --heal`
  repairs state and is not an acceptance gate. Real-machine validation requires the
  user's requested scope and preservation of personal configuration.
- Validate Python resources in a clean virtual environment populated only from declared
  dependencies. A passing system-Python run can hide missing dependencies; the first
  Linux Codex CI run caught an undeclared Requests import in the bundled health checker.
- Consult [FEATURES](codex/FEATURES.md), [review](codex/REVIEW.md) and
  [global validation](codex/GLOBAL-VALIDATION.md). Dashboard, watchdog, notifications,
  the Claude statusline renderer, automatic linting and snapshots remain unported. MCP
  examples are disabled and Codex hooks are opt-in. The status bar counterpart is an
  opt-in `tui.status_line` example of built-in footer IDs (never auto-merged into
  config) plus instruction guidance to title the current task `SDLC | <task>` where a
  native rename capability exists; the marker means guidance loaded, not checks passed.

## Evidence and publishing

- Initial adaptation input: `509d282a195cc7a0e3b4d63b51b5f791be519eed`. Retain
  historical audit inputs and record subsequent verification separately.
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
