---
description: "Create named save points during complex work, and verify progress against them"
argument-hint: "<name> [--verify] [--list] [--diff <name>]"
---

Create or manage named checkpoints during multi-step work.

## Arguments

Parse `$ARGUMENTS` for:
- `<name>` — checkpoint name (e.g., "before-refactor", "auth-working", "v1-baseline")
- `--verify <name>` — compare current state against a named checkpoint
- `--list` — list all checkpoints in this session
- `--diff <name>` — show file diff against a named checkpoint

## Modes

### Create Checkpoint (default): `/checkpoint <name>`

1. **Capture current state**:
   - Run `git status` to identify all modified, added, and deleted files
   - Run `git diff --stat` to summarize changes
   - Run project tests (if quick — under 30 seconds) and record pass/fail counts
   - Record current git HEAD commit hash

2. **Create the checkpoint**:
   - Create a git stash with a descriptive name: `git stash push -m "checkpoint: <name> [$(date +%Y-%m-%d_%H:%M)]"`
   - Immediately pop the stash to restore working state: `git stash pop`
   - This creates a recoverable snapshot without affecting the working tree

3. **Also create a lightweight commit** on a temporary branch for easy diffing:
   - `git stash push -m "checkpoint-temp"` (stash current changes)
   - `git checkout -b checkpoint/<name>` from current HEAD
   - `git stash pop` and `git add -A` and `git commit -m "checkpoint: <name>"`
   - `git checkout -` (return to original branch)
   - `git stash pop` (if anything was left — usually clean)
   - Note: this creates checkpoint/<name> branch pointing at the snapshot

4. **Report**:
   ```
   Checkpoint '<name>' created
   - Branch: checkpoint/<name>
   - Files changed: <count> (+<added> -<deleted> ~<modified>)
   - Tests: <pass>/<total> passing
   - Time: <timestamp>
   ```

### Verify Against Checkpoint: `/checkpoint --verify <name>`

1. **Compare current state against checkpoint**:
   - `git diff checkpoint/<name>..HEAD` — commits since checkpoint
   - `git diff checkpoint/<name>` — all changes (committed + uncommitted)
   - Count files changed, lines added/removed

2. **Run tests** and compare against checkpoint test results (if recorded)

3. **Report**:
   ```
   ## Checkpoint Verification: <name>

   ### File Changes Since Checkpoint
   - Files modified: <count>
   - Lines added: <count>
   - Lines removed: <count>

   ### Test Comparison
   - At checkpoint: <pass>/<total> passing
   - Now: <pass>/<total> passing
   - Delta: +<new_passing> / -<new_failing>

   ### Verdict
   <BETTER | SAME | WORSE | MIXED>
   <explanation of what improved or regressed>
   ```

### List Checkpoints: `/checkpoint --list`

1. List all `checkpoint/*` branches with their creation dates:
   ```
   Checkpoints:
   1. before-refactor (2026-03-20 14:30) — 5 files changed
   2. auth-working (2026-03-20 15:45) — 12 files changed
   ```

### Diff Against Checkpoint: `/checkpoint --diff <name>`

1. Show `git diff checkpoint/<name>` with full file diffs
2. Summarize: files changed, lines added/removed, new files, deleted files

## Cleanup

- Checkpoint branches are local only — never pushed
- Clean up with: `git branch -D checkpoint/<name>` (manual, not automatic)
- Old checkpoints are harmless — lightweight git branches cost nothing

**Important notes:**
- Checkpoints are local git branches — they survive across sessions
- Never force-push or modify checkpoint branches after creation
- If working tree has uncommitted changes, they're included in the checkpoint
- If git operations fail (not in a repo, dirty state), report the error clearly
