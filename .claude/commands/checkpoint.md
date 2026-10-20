---
description: "Create named save points during complex work, and verify progress against them"
argument-hint: "<name> [--verify <name>] [--list] [--diff <name>]"
---

Create or manage named checkpoints during multi-step work.

A checkpoint is a snapshot of the current working tree captured into a ref under
`refs/checkpoint/<name>`. It is created with Git plumbing by a helper, so it NEVER
touches your branch, index, working tree or stashes — no `git stash`, no branch switch,
no `git checkout`. The old recipe did all three and could apply an unrelated stash; do
not reintroduce it.

## Resolve the helper

The helper ships inside the installed `verified-handoff` skill. Resolve it at the
installed skill location, never relative to the project you are checkpointing:

- User-global install (default): `~/.claude/skills/verified-handoff/scripts/checkpoint.py`
- Project-scoped install: the same `scripts/checkpoint.py` under the framework's installed
  skills directory for that project.

Run it with the interpreter and pass the target repository explicitly:

```bash
python3 <resolved>/checkpoint.py <subcommand> [name] --repo <path-to-repo>
```

`--repo` defaults to the current directory; pass the repository root when the working
directory differs. Exit codes: `0` ok, `1` git/runtime error, `2` usage error, `3`
refused before any change (unsafe name, existing checkpoint, unborn/merge-in-progress,
skip-worktree/assume-unchanged flags, submodule, an untracked embedded/nested repository,
a configured content filter on any staged or untracked path, or an active
`reference-transaction`/`post-index-change` hook that could mutate your state).

## Arguments

Parse `$ARGUMENTS` for:
- `<name>` — checkpoint name (e.g., `before-refactor`, `auth-working`, `v1-baseline`)
- `--verify <name>` — compare current state against a named checkpoint
- `--list` — list all checkpoints
- `--diff <name>` — show the file diff against a named checkpoint

## Modes

### Create checkpoint (default): `/checkpoint <name>`

1. **Record context** (optional but useful): run project tests if they are quick (under
   30 seconds) and note pass/fail counts to compare later.
2. **Create the snapshot**:
   ```bash
   python3 <resolved>/checkpoint.py save <name> --repo <repo>
   ```
   The helper captures staged, unstaged, deleted and non-ignored untracked files into
   `refs/checkpoint/<name>` and leaves your working state untouched. Ignored files are
   excluded. If it exits `3`, report the printed reason verbatim and stop — it refused
   before changing anything.
3. **Report** the helper's output: ref, commit, parent, branch, and the change summary
   versus HEAD. Mention how to recover (the helper prints the exact commands):
   - new branch: `git switch -c <name>-restore refs/checkpoint/<name>`
   - files only: `git restore --source=refs/checkpoint/<name> -- <path>`

### Verify against checkpoint: `/checkpoint --verify <name>`

1. Show what changed since the checkpoint:
   ```bash
   python3 <resolved>/checkpoint.py diff <name> --repo <repo>
   ```
2. Re-run tests if they are quick and compare pass/fail counts against what you recorded
   at checkpoint time.
3. Report a verdict — BETTER | SAME | WORSE | MIXED — grounded in the diff and the test
   delta, naming what improved or regressed.

### List checkpoints: `/checkpoint --list`

```bash
python3 <resolved>/checkpoint.py list --repo <repo>
```

Lists each `refs/checkpoint/*` with its short commit, creation time and subject.

### Diff against checkpoint: `/checkpoint --diff <name>`

```bash
python3 <resolved>/checkpoint.py diff <name> --repo <repo>
```

Prints the stat summary and full patch between the checkpoint and the current working
tree. Summarize files changed and lines added/removed.

## Cleanup

- Checkpoint refs are local only — never pushed. The helper never pushes.
- Remove one with `git update-ref -d refs/checkpoint/<name>`.
- Old checkpoints are harmless lightweight refs.

**Important notes:**
- Checkpoints survive across sessions; they are refs, not branches, so they will not be
  checked out by accident.
- Recovery is explicit — the helper snapshots and inspects, it never restores for you.
- If a save is refused (exit `3`), surface the exact reason; do not work around it by
  running `git stash`, switching branches, or disabling hooks.
