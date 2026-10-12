# Framework maintenance

This repository ships a Claude Code framework and a separate Codex adapter.
Read `MEMORY.md`, `codex/README.md` and `codex/FEATURES.md` before changing the adapter.
Claude sources in `.claude/` remain the source of portable domain procedures;
Codex runtime procedures live in `codex/overrides/`.

Use Conventional Commits. Do not add AI attribution trailers, force-push main,
amend commits, or skip hooks without an explicit request. Update CHANGELOG.md
with behavioral changes. Do not commit generated installation directories.

Verify source claims at the recorded SHA. Read the implementation before editing.
Use independent reviewers for substantial changes; reviewers must not review
their own implementation. Parallel writes require disjoint scopes and isolated
worktrees. Discover tools at runtime; do not assume a named MCP is connected.

Adapter checks: `python3 -m unittest discover -s tests/codex -v`.
Claude checks: `./validate.sh` and `bash tests/gap/run.sh --prove --jobs 4`.
Run installed-environment checks in a disposable home, not against personal
configuration. Never invoke `validate.sh --heal` as a verification gate.
Read-only checks of a real installed system and global installation are allowed when
the user explicitly requests them; preserve personal config and instruction content.

Both integrations are user-global by default. Claude uses `./install.sh`; Codex uses
`./install-codex.sh --user`. Do not fan out copies to all project directories. Project
Codex installation is an explicit alternative, not needed for ordinary global use.
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
