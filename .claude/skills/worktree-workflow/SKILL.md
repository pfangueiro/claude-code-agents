---
name: worktree-workflow
description: Git worktree isolation via the EnterWorktree and ExitWorktree tools — creating a separate checkout on its own branch, working in it, then keeping or discarding it. Use ONLY when a worktree is explicitly requested, by the user or by project instructions (CLAUDE.md / memory). Triggers include worktree, EnterWorktree, ExitWorktree, isolated checkout, side branch. Once explicitly requested it fits work needing a second simultaneous checkout — a risky refactor that may be thrown away, a hotfix on a release branch while feature work continues in the main tree, or two implementations compared side by side — but none of those authorizes the tool on its own, without the explicit request. It does not cover parallelism in general — parallel sub-agents, parallel tool calls, and concurrent tasks are unrelated, and per-agent repo isolation is instead the Agent tool's isolation parameter set to "worktree" — nor an ordinary branch switch, a single-file experiment revertible with git checkout, or a non-git project.
---

# Worktree Workflow

A second checkout of the repository, on its own branch, in its own directory — created and torn
down through the `EnterWorktree` / `ExitWorktree` tools.

## The Gate: Explicit Instruction Only

**Exactly one thing authorizes `EnterWorktree`: the word "worktree" appearing explicitly in the
user's request, or in project instructions (CLAUDE.md / memory).** Per the tool's own contract,
never reach for it because work merely *looks* isolated, risky, experimental, or parallel.

If you got here from any of the following, **stop and do the other thing instead**:

| If the trigger was… | Do this instead |
|---|---|
| "fix this bug", or a hotfix, without the word "worktree" | Normal git workflow — branch, fix, commit |
| Investigating a bug or testing a hypothesis | Investigate in place; undo with `git checkout -- <file>` |
| "do this in isolation" / "experiment in isolation" | An ordinary branch or a scratch copy — isolation alone is not a worktree trigger |
| Parallel sub-agents, parallel tool calls, concurrent tasks | Unrelated to worktrees. For per-agent repo isolation, use the `Agent` tool's `isolation: "worktree"` parameter — a different mechanism (see Related) |
| "create a branch" / "switch branches" | `git switch` or `git checkout` |

Once the user **has** explicitly asked for a worktree, it fits work that genuinely needs a second
simultaneous checkout: a risky refactor that may be thrown away, a release-branch hotfix while
feature work stays in the main tree, or two implementations compared side by side.

## Tools

### EnterWorktree
Creates a git worktree on a new branch. Use only when the user explicitly asks for a worktree.

**Parameters:**
- `name` (optional) — Descriptive name for a **new** worktree (e.g., `fix-auth-bug`, `experiment-caching`). Auto-generated if omitted.
- `path` (optional) — Path to an **existing** worktree to switch into instead of creating one. Mutually exclusive with `name`.

**Behavior:**
- Creates worktree in `.claude/worktrees/<name>`
- **Branches from `origin/<default-branch>`, NOT from local HEAD.** The base ref is governed by the `worktree.baseRef` *setting*, whose default is `fresh`; the `head` value is what branches from local HEAD. It is a setting, not a call parameter — so uncommitted or unpushed local work is not carried into the worktree by default.
- Switches the **session's** working directory to the worktree — this is session-wide state, not per-task state
- Full git history available — commits, pushes, etc. all work normally

### ExitWorktree
Leave the worktree and return to the original working directory. Only operates on a worktree created by `EnterWorktree` **in this session** — otherwise it is a no-op, and it never touches manually created or previous-session worktrees. Call it when the user asks to exit, not proactively.

**Parameters:**
- `action` (required) — `"keep"` or `"remove"`
  - `keep` — Leave the worktree and branch on disk for later
  - `remove` — Delete the worktree directory and branch
- `discard_changes` (optional, default `false`) — Only meaningful with `remove`. **`remove` refuses** when the worktree has uncommitted files or commits not on the original branch, and lists them; it proceeds only with `discard_changes: true`, which permanently discards that work. Treat the refusal as the safety net reporting unsaved work — confirm with the user before overriding it, never set it reflexively to clear the error.

## Workflow Patterns

Every pattern below assumes the user has **already explicitly asked** to work in a worktree. None of
them is a reason to reach for the tool on your own.

### Experiment-then-Merge
1. `EnterWorktree` with descriptive name (branches from `origin/<default-branch>`)
2. Implement the experimental approach
3. Run tests to validate
4. If successful: commit, exit with `keep`, merge from main branch
5. If failed: commit or stash anything worth keeping, then exit with `remove`. If `remove` refuses, it is reporting unsaved work — inspect it rather than overriding with `discard_changes`

### Two Features, Two Branches
Sequential, not concurrent — the single-instance rule means each worktree must be exited before the
next is created. The payoff is two checkouts left on disk, not two things happening at once.

1. `EnterWorktree` for feature A
2. Implement feature A, commit
3. `ExitWorktree` with `keep`
4. `EnterWorktree` for feature B
5. Implement feature B, commit
6. `ExitWorktree` with `keep`
7. Both branches exist independently — merge when ready

### A/B Comparison
1. `EnterWorktree` for implementation A, build it, commit, `ExitWorktree` with `keep`
2. `EnterWorktree` for implementation B, build it, commit, `ExitWorktree` with `keep`
3. Compare the two branches side by side — both checkouts remain on disk
4. Merge the winner; delete the loser's branch with ordinary git commands

> Bug investigation is **not** on this list. The tool's contract routes "fix this bug" and
> "diagnose this issue" to the normal git workflow — investigate in the main working directory and
> revert with `git checkout -- <file>`.

## Constraints

- Requires a git repository, or `WorktreeCreate` / `WorktreeRemove` hooks in settings.json
- **Single-instance:** cannot create a new worktree (`name`) while already in a worktree session — exit first. Entering an *existing* worktree by `path` is the exception
- **Session-scoped:** `EnterWorktree` moves the whole session's working directory, so a worktree is never a per-task or per-batch isolation mechanism
- Uncommitted changes or unmerged commits make `remove` refuse unless `discard_changes: true`
- On session exit while in a worktree, user is prompted to keep or remove

## When NOT to Use Worktrees

- **No explicit instruction** — if neither the user nor CLAUDE.md / memory said "worktree", stop here regardless of how isolated the work looks
- **Bug fixes and feature work** — the tool's contract routes these to the normal git workflow
- **Simple branch switches** — Use `git checkout` or `git switch` instead
- **Single-file experiments** — Just edit and revert with `git checkout -- file`
- **Non-git projects** — Worktrees require git

## Best Practices

- Name worktrees descriptively: `fix-auth-timeout`, `experiment-redis-cache`, `hotfix-v2.1`
- Commit or push meaningful work before exiting — `remove` deletes the local branch, and `discard_changes: true` permanently destroys anything uncommitted
- Use `keep` when you plan to return or merge; use `remove` for throwaway work — and read the refusal if `remove` reports unsaved changes instead of forcing past it
- Combine with `experiment-loop` skill for metric-driven iteration, once a worktree has been explicitly requested

## Related

- `Agent` tool's `isolation: "worktree"` parameter — the *separate* mechanism that gives one spawned agent a temporary git worktree, i.e. an isolated copy of the repo. This is what per-agent or per-task isolation uses; it is not `EnterWorktree` and is not gated on the user saying "worktree"
- `experiment-loop` skill — Autonomous optimization patterns (can run inside worktrees)
- `git-workflow` skill — Branch management and commit conventions
- `/checkpoint` command — Named save points (lighter weight than worktrees)
