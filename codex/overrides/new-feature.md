# Create a feature branch

Parse the ticket/description according to project conventions. Check `git status`
and preserve uncommitted work; do not stash, reset or switch a dirty tree implicitly.
Resolve the project's configured base branch or `origin/HEAD`, instead of assuming
`master` or a mandatory `PROJ-*` key. If the base cannot be determined, ask for it.

Fetch when needed and authorized. Create a distinct, shell-quoted branch from the
selected exact base SHA without rewriting the owner's existing branch. Check for
branch-name collisions. Push with upstream tracking only when requested or already
authorized by the project workflow. Report the branch, base SHA and publication state.
