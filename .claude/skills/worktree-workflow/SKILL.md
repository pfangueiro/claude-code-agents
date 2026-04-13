---
name: worktree-workflow
description: Git worktree isolation for parallel development. Use EnterWorktree/ExitWorktree to create isolated branches for features, experiments, or risky changes. Auto-activates on worktree, parallel branches, isolated work, experiment in isolation, side branch, parallel feature.
---

# Worktree Workflow

Use git worktrees for parallel, isolated development without affecting the main working directory.

## When to Use

- **Parallel features**: Work on multiple features simultaneously without stashing/switching
- **Experiments**: Try risky refactors or approaches in isolation — discard if they fail
- **Hotfixes**: Fix a bug on a release branch while feature work continues
- **Investigation**: Test a hypothesis about a bug without polluting the main branch
- **A/B comparison**: Compare two implementations side by side

## Tools

### EnterWorktree
Creates an isolated git worktree with a new branch based on HEAD.

**Parameters:**
- `name` (optional) — Descriptive name for the worktree (e.g., `fix-auth-bug`, `experiment-caching`). Auto-generated if omitted.

**Behavior:**
- Creates worktree in `.claude/worktrees/<name>`
- Creates a new branch from current HEAD
- Switches the session's working directory to the worktree
- Full git history available — commits, pushes, etc. all work normally

### ExitWorktree
Leave the worktree and return to the original working directory.

**Parameters:**
- `action` (required) — `"keep"` or `"remove"`
  - `keep` — Leave the worktree and branch on disk for later
  - `remove` — Delete the worktree directory and branch
- `discard_changes` (optional) — Set `true` to force-remove even with uncommitted changes

## Workflow Patterns

### Experiment-then-Merge
1. `EnterWorktree` with descriptive name
2. Implement the experimental approach
3. Run tests to validate
4. If successful: commit, exit with `keep`, merge from main branch
5. If failed: exit with `remove` to clean up

### Parallel Feature Development
1. `EnterWorktree` for feature A
2. Implement feature A, commit
3. `ExitWorktree` with `keep`
4. `EnterWorktree` for feature B
5. Implement feature B, commit
6. `ExitWorktree` with `keep`
7. Both branches exist independently — merge when ready

### Safe Investigation
1. `EnterWorktree` to isolate investigation
2. Add debug logging, modify code freely
3. Reproduce and diagnose the issue
4. `ExitWorktree` with `remove` (no mess left behind)
5. Apply the targeted fix in the main working directory

## Constraints

- Must be in a git repository to use worktrees
- Cannot create a worktree while already in one (exit first)
- Uncommitted changes in worktree prevent `remove` unless `discard_changes: true`
- On session exit while in a worktree, user is prompted to keep or remove

## When NOT to Use Worktrees

- **Simple branch switches** — Use `git checkout` or `git switch` instead
- **Single-file experiments** — Just edit and revert with `git checkout -- file`
- **Non-git projects** — Worktrees require git

## Best Practices

- Name worktrees descriptively: `fix-auth-timeout`, `experiment-redis-cache`, `hotfix-v2.1`
- Commit meaningful work before exiting — uncommitted changes may be lost on remove
- Use `keep` when you plan to return or merge; use `remove` for throwaway experiments
- Combine with `experiment-loop` skill for metric-driven iteration in isolation

## Related

- `experiment-loop` skill — Autonomous optimization patterns (can run inside worktrees)
- `git-workflow` skill — Branch management and commit conventions
- `/checkpoint` command — Named save points (lighter weight than worktrees)
