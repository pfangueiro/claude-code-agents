# Git worktree isolation

Inspect `git status --short`, `git rev-parse HEAD` and `git worktree list` first.
Respect existing changes. For independent coding tasks, create distinct branches
and worktree directories with `git worktree add -b <branch> <path> <input-sha>`.
Quote paths in shell commands and check that the branch/path does not already exist.

Pass the absolute worktree path, baseline SHA and permitted write scope to each
worker. Do not assume spawning itself creates isolation. Use a host-managed worktree
tool when exposed and appropriate, following its schema and lifecycle instructions.

Verify each result independently, integrate dependency-safe changes sequentially,
then run tests on the combined tree. Remove only worktrees created for this task,
after verifying their changes are committed or otherwise preserved. Never discard
a dirty worktree or remove another user's branch. Codex CLI also offers `--worktree`
where supported; verify with the installed CLI help before invoking it.
