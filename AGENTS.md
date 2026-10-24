# Framework maintenance

This repository ships a Claude Code framework and a separate Codex adapter.
Read `MEMORY.md`, `codex/README.md` and `codex/FEATURES.md` before changing the adapter.
Claude sources in `.claude/` remain the source of portable domain procedures;
Codex runtime procedures live in `codex/overrides/`.

Use Conventional Commits. Do not add AI attribution trailers, force-push main,
amend commits, or skip hooks without an explicit request. Update CHANGELOG.md
with behavioral changes. Do not commit generated installation directories.

Verify source claims at the recorded SHA. Read the implementation before editing.
Current inventory and limits live in README, INSTALL and `codex/FEATURES.md`; past
acceptance snapshots are archived under `docs/archive/` (see `docs/archive/README.md`)
as historical records — cite them for provenance, not as current state, and do not
relabel their dates, SHAs or counts as current.
Use independent reviewers for substantial changes; reviewers must not review
their own implementation. Parallel writes require disjoint scopes and isolated
worktrees. Discover tools at runtime; do not assume a named MCP is connected.

Quality contract for both editions. The canonical procedures are the verification and
code-quality rules, the `code-quality` agent, `code-review-checklist`, `/review-pr`,
`/quality-gate`, and `delivery` with `references/acceptance-by-task.md`. Report concrete
findings and their evidence class. A review names the exact base and head SHA it covered. A
check receipt records the exact checked input SHA, not a base (a source-only receipt records
no SHA). A new commit invalidates both. Report PASS, FAIL or INCOMPLETE for the declared
scope: missing required evidence is INCOMPLETE, and unknown is not zero. Accept work by task
type. Default maintenance roles: Codex coordinates and independently verifies, and an actual
Claude execution implements. Existing explicit owner or project instructions that set other
roles still apply, with no extra confirmation step. Implement, review, merge, deploy and release are separate states, and each needs
its own authorization.

Adapter checks: `python3 -m unittest discover -s tests/codex -v`.
Claude checks: `./validate.sh` and `bash tests/gap/run.sh --prove --jobs 4`.
Run installed-environment checks in a disposable home, not against personal
configuration. `validate.sh` observes only — `--heal` is retired (no repair; rejected) —
so never treat any `--heal` as a verification gate; repair is an explicit `install.sh --update`.
Read-only checks of a real installed system and global installation are allowed when
the user explicitly requests them; preserve personal config and instruction content.

Both integrations are user-global by default. Claude uses `./install.sh`; Codex uses
`./install-codex.sh --user`. Do not fan out copies to all project directories. Project
Codex installation is an explicit alternative, not needed for ordinary global use.
To upgrade an existing install, follow INSTALL.md (*Upgrading an existing installation*):
delivery manifest first, broad `./install.sh --update` second, Codex separately. The broad
installer replaces same-name customizations; the hash-owned installers refuse them.
Never claim complete runtime parity; consult the feature matrix and global test record.

Before publishing, fetch and reconcile remote changes without rebasing published SHAs.
Stage explicit task paths, inspect the staged diff for private data, run applicable
checks, and obtain independent review at the exact commit. Verify GitHub's branch head
and CI at that SHA after an authorized push. If SSH fails, scope the authenticated gh
HTTPS credential helper to the command and preserve the saved remote URL. Never force
push or imply a new release unless a release was requested.

The Codex edition must not invoke the Claude installer, overwrite foreign skills
or configuration, change model/approval/sandbox defaults, or trust hooks itself.
Generated rules are instructions, not a sandbox or a guaranteed tool restriction.
