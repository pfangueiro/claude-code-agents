---
name: git-workflow
description: Git workflow conventions and conflict/recovery procedures — Conventional Commits format, branching models (Git Flow, GitHub Flow, trunk-based), pull request structure and review checklists, merge-versus-rebase choice, cherry-pick, interactive rebase, and guarded use of history-rewriting or destructive commands. Covers the rebase inversion where --ours is the upstream and --theirs is the user's own work. Use when resolving a merge or rebase conflict, choosing or documenting a branching strategy, writing a commit message or PR description to a convention, deciding between merging and rebasing, undoing or reverting a commit, cleaning up history before a PR, or recovering work after a bad reset, rebase, or force-push. Not needed for routine single commands whose syntax is already known — git status, git add, git diff, git log, staging, a plain commit, or a straightforward push or pull.
---

# Git Workflow

## Overview

This skill provides comprehensive git workflow best practices, branching strategies, and collaboration patterns. Use it to ensure consistent, professional git usage across your projects.

## When to Use This Skill

- Creating commits with proper messages
- Establishing branching strategies (Git Flow, GitHub Flow, Trunk-Based)
- Handling pull requests and code reviews
- Managing releases and hotfixes
- Resolving merge conflicts
- Setting up git hooks and automation

## Core Workflows

### Commit Message Guidelines

Follow the Conventional Commits specification for clear, semantic commit messages:

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Formatting, missing semicolons, etc.
- `refactor`: Code restructuring without behavior changes
- `perf`: Performance improvements
- `test`: Adding or updating tests
- `chore`: Build process, dependencies, tooling
- `ci`: CI/CD pipeline changes

**Examples:**
```
feat(auth): add JWT token refresh mechanism

Implement automatic token refresh before expiration.
Tokens are refreshed 5 minutes before expiry.

Closes #123
```

```
fix(api): handle null responses in user service

Add defensive null checks to prevent NPE when
external API returns unexpected null values.

Fixes #456
```

### Branching Strategies

#### Git Flow (Traditional)
Best for: Scheduled releases, multiple version support

**Branches:**
- `main`: Production-ready code
- `develop`: Integration branch for features
- `feature/*`: New features
- `release/*`: Release preparation
- `hotfix/*`: Emergency production fixes

**Workflow:**
```bash
# Start new feature
git checkout develop
git checkout -b feature/user-authentication

# Finish feature
git checkout develop
git merge feature/user-authentication
git branch -d feature/user-authentication

# Create release
git checkout -b release/1.2.0
# Bump version, final testing
git checkout main
git merge release/1.2.0
git tag -a v1.2.0 -m "Release 1.2.0"
git checkout develop
git merge release/1.2.0
```

#### GitHub Flow (Simplified)
Best for: Continuous deployment, web applications

**Branches:**
- `main`: Always deployable
- `feature/*`: All changes

**Workflow:**
```bash
# Start work
git checkout -b feature/add-dark-mode

# Make changes, commit often
git commit -m "feat(ui): add dark mode toggle"

# Push and create PR
git push origin feature/add-dark-mode
# Create pull request on GitHub
# After review and CI passes, merge to main
# Deploy from main
```

#### Trunk-Based Development
Best for: High-frequency releases, mature CI/CD

**Key principles:**
- All work on `main` or very short-lived feature branches (<1 day)
- Feature flags for incomplete features
- Rigorous automated testing

### Pull Request Best Practices

**PR Description Template:**
```markdown
## Summary
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing Done
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing completed

## Screenshots (if applicable)

## Related Issues
Closes #123
```

**Review Checklist:**
1. Code follows project conventions
2. Tests cover new functionality
3. Documentation is updated
4. No sensitive data committed
5. CI/CD pipeline passes
6. Performance impact considered

### Handling Merge Conflicts

**Process:**
```bash
# Update your branch with latest main
git checkout feature/my-feature
git fetch origin
git merge origin/main

# If conflicts occur
# 1. Open conflicted files
# 2. Look for conflict markers: <<<<<<< ======= >>>>>>>
# 3. Resolve manually, keeping appropriate changes
# 4. Remove conflict markers
# 5. Test the resolved code
git add <resolved-files>
git commit -m "chore: resolve merge conflicts with main"
```

**Conflict Resolution Tips:**
- Communicate with the other developer if unsure
- Prefer rebasing for cleaner history (if branch not shared)
- Use `git mergetool` for complex conflicts
- Always test after resolution
- If unsure at any point, `git merge --abort` / `git rebase --abort` restores the pre-conflict state

**`--ours` and `--theirs` invert between merge and rebase.** During `git rebase main`, `--ours` is
`main` (the upstream) and `--theirs` is **your own commits** being replayed — the opposite of a
merge. Taking `--ours` mid-rebase because "ours means mine" silently discards your work. Run
`git status` to see which operation is in progress, and prefer deciding by branch name ("keep the
version from `main`") over the bare flags. See `references/conflict-resolution.md` before using
either flag.

### Git Hooks and Automation

Common hooks to consider:

**pre-commit:**
```bash
# Run linters, formatters
npm run lint
npm run format

# Run fast tests
npm run test:unit
```

**commit-msg:**
```bash
# Validate commit message format
# Ensure conventional commits compliance
```

**pre-push:**
```bash
# Run full test suite
npm run test

# Run build
npm run build
```

## Advanced Patterns

### Rebasing vs Merging

**Use Rebase When:**
- Working on personal feature branch
- Want linear history
- Need to incorporate upstream changes

```bash
git fetch origin
git rebase origin/main
```

**Use Merge When:**
- Working on shared branches
- Want to preserve complete history
- Merging pull requests

```bash
git merge origin/main
```

### Cherry-Picking

Use to apply specific commits to another branch:

```bash
# Find commit hash
git log

# Apply to current branch
git cherry-pick <commit-hash>
```

### Interactive Rebase

Clean up commit history before pushing:

```bash
# Rebase last 3 commits
git rebase -i HEAD~3

# Options: pick, reword, squash, fixup, drop
```

`drop` (and deleting a line from the todo list) removes that commit entirely. Only rewrite commits
you have not pushed, and abort with `git rebase --abort` if the result is not what you expected.
A commit removed this way remains recoverable from `git reflog` until garbage collection.

## Common Scenarios

### Undo Last Commit (Not Pushed)
```bash
git reset --soft HEAD~1  # Keep changes staged
git reset HEAD~1         # Keep changes unstaged
```

`--soft` and plain `reset` are non-destructive — your changes survive in the index or working tree.

**`git reset --hard` permanently destroys uncommitted work** in the working tree and index. There is
no undo for changes that were never committed; `git reflog` recovers commits, not unstaged edits.
Before running it, confirm there is nothing to lose and take a rescue point:

```bash
git status                 # MUST be clean apart from what you intend to discard
git stash -u               # rescue anything uncommitted (including untracked) — reversible
git reset --hard HEAD~1    # only now, and only on a branch that is not pushed
```

Never run `git reset --hard` on a branch others have pulled — use `git revert` below instead.

### Undo Pushed Commit
```bash
# Create new commit that reverses changes
git revert <commit-hash>
git push origin main
```

`git revert` is the correct tool for published history: it adds a new commit rather than rewriting
existing ones, so no collaborator loses work and no force-push is needed.

### Never Force-Push a Shared Branch

`git push --force` overwrites remote history and destroys commits other people have already pulled.

- **Never force-push `main`, `master`, or any protected/shared branch.** This is a hard rule.
- On your own unshared feature branch, use `git push --force-with-lease`, which refuses the push if
  someone else has pushed since your last fetch. Plain `--force` has no such check.
- To undo something already published, use `git revert` — not a force-push.

### Stash Changes
```bash
# Save work in progress
git stash save "WIP: feature description"

# List stashes
git stash list

# Apply stash
git stash apply stash@{0}

# Apply and remove
git stash pop
```

### Update Commit Message
```bash
# Last commit (not pushed)
git commit --amend -m "new message"

# Older commit
git rebase -i HEAD~n  # Use 'reword'
```

Both rewrite history: they replace commits with new SHAs. Only use them on commits you have **not**
pushed. Amending an already-pushed commit leaves the remote holding the original and can only be
published with a force-push — see "Never Force-Push a Shared Branch" above.

## Worktrees

Git worktrees let you work on multiple branches simultaneously without stashing or switching.

### When to Use Worktrees vs Branches

| Scenario | Use Branch | Use Worktree |
|----------|-----------|-------------|
| Sequential feature work | Yes | No |
| Parallel features (simultaneous) | No | Yes |
| Quick hotfix while mid-feature | Stash + branch | Yes (cleaner) |
| Risky experiment | Maybe | Yes (isolated) |
| Code review while coding | No | Yes |

The table above compares the *git concept* of worktrees against branches. Claude Code's
`EnterWorktree`/`ExitWorktree` **tools** are gated far more narrowly than that comparison suggests —
read the contract below before invoking either.

### Using EnterWorktree/ExitWorktree

**Explicit instruction only.** Do not reach for `EnterWorktree` because a task merely looks
isolated, risky, or parallel. Per the tool's own contract, never use it unless "worktree" is
explicitly mentioned by the user or by project instructions (CLAUDE.md / memory). In particular:

- "Create a branch" / "switch branches" / "work on another branch" → use ordinary git commands.
- "Fix this bug" / "build this feature" → use the normal git workflow, **not** a worktree.
- Only an explicit request ("use a worktree", "work in a worktree") authorizes the tool.

- **EnterWorktree** — Creates a git worktree under `.claude/worktrees/` on a new branch and switches
  the session's working directory into it.
  - **Base ref is `fresh` by default: it branches from `origin/<default-branch>`, NOT from your
    current HEAD.** Uncommitted or unpushed local work is therefore *not* carried in. The `head`
    setting (`worktree.baseRef`) is what branches from local HEAD.
  - `name` is optional (one is generated if omitted). Pass `path` instead to enter an *existing*
    worktree; `name` and `path` are mutually exclusive.
  - Requires a git repository, or `WorktreeCreate`/`WorktreeRemove` hooks in settings.json.
  - Cannot create a new worktree while already in a worktree session.
- **ExitWorktree** — Leaves the worktree and restores the previous working directory. `action` is
  required: `keep` (leave directory and branch on disk) or `remove` (delete both).
  - Only operates on a worktree created by `EnterWorktree` **in this session**. It is a no-op
    otherwise, and will not touch manually created or previous-session worktrees.
  - **`remove` refuses** when the worktree has uncommitted files or commits not on the original
    branch. It only proceeds with `discard_changes: true` — which permanently discards that work.
    Confirm with the user before setting it; do not set it reflexively to clear the refusal.

### Common Patterns

These assume the user has explicitly asked to work in a worktree.

**Experiment safely:**
1. `EnterWorktree` with name `experiment-X` (branches from `origin/<default-branch>`)
2. Try the risky approach
3. If it works: commit, `ExitWorktree(keep)`, merge later
4. If it fails: commit or stash anything worth keeping, then `ExitWorktree(remove)`. If `remove`
   refuses, that refusal is the safety net reporting unsaved work — inspect it rather than
   overriding with `discard_changes`.

**Hotfix while mid-feature:**
1. `EnterWorktree` with name `hotfix-Y`
2. Fix the bug, commit, **push** (pushing matters: `remove` deletes the local branch)
3. `ExitWorktree(remove)` — back to feature work

See the `worktree-workflow` skill for detailed patterns and best practices.

## Resources

### references/
This skill includes reference documentation for deeper dives:

- **git-best-practices.md**: Comprehensive git guidelines
- **branching-models.md**: Detailed branching strategy comparisons
- **conflict-resolution.md**: Advanced merge conflict patterns

## Quick Reference

**Daily Commands:**
```bash
git status                    # Check status
git add <file>               # Stage file
git commit -m "message"      # Commit with message
git push origin <branch>     # Push to remote
git pull origin <branch>     # Pull from remote
git checkout -b <branch>     # Create and switch branch
git merge <branch>           # Merge branch
```

**Inspection:**
```bash
git log --oneline --graph    # Visual commit history
git diff                     # See unstaged changes
git diff --staged            # See staged changes
git show <commit>            # Show commit details
git blame <file>             # See who changed each line
```

**Cleanup:**
```bash
git branch -d <branch>       # Delete local branch (refuses if unmerged — keep -d, not -D)
git fetch --prune            # Drop stale remote-tracking refs (local only, safe)
git gc                       # Garbage collection
```

**Guarded — these destroy things:**
```bash
# Delete a REMOTE branch: affects everyone. Confirm it is merged and that no open PR
# or other collaborator depends on it first.
git push origin --delete <branch>

# Remove untracked files: PERMANENT. These files are not in git, so there is no reflog,
# no stash, and no recovery. ALWAYS dry-run first and read the list.
git clean -nd                # -n = dry run: lists what WOULD be deleted. Read it.
git clean -fd                # only after the dry-run list is confirmed safe
```

`git clean -fd` also deletes untracked files that are merely *ignored-adjacent* but not ignored —
local `.env` files, scratch notes, and unstaged assets sitting in the tree. Run `git clean -nd`
every time; treat the `-n` output as the confirmation step, not a formality.
