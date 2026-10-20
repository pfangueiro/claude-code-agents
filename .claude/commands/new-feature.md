---
description: Create a feature branch from the project's own base branch, following the repository's discovered branch and ticket conventions
argument-hint: "[ticket] <description>"
disable-model-invocation: true
---

Create a feature branch for new work, adapting to the repository's own conventions instead of assuming a fixed base branch or ticket scheme.

1. **Parse arguments**:
   - Treat `$ARGUMENTS` as an optional leading ticket/issue identifier followed by a short description.
   - Do NOT require a specific ticket prefix. Detect a ticket only if the repository's convention uses one (see step 3). If `$ARGUMENTS` is empty, ask for a description instead of failing silently.

2. **Preserve uncommitted work**:
   - Run `git status --porcelain`. If the tree is dirty, STOP and report the changed files. Do NOT stash, reset, or switch branches implicitly — let the user commit, bring the work along, or explicitly decide how to proceed.

3. **Discover the base branch and naming convention**:
   - Resolve the base branch from a known source, in this order: a project-configured base (a default documented in the repository's own instructions), else the remote's recorded default via `origin/HEAD` (`git symbolic-ref --quiet refs/remotes/origin/HEAD`). This handles `main`, `master`, or a custom configured default without assuming any one of them.
   - If neither resolves, the repository's default branch is not reliably known. Do NOT assume the currently checked-out branch is the default — ask the user which base to branch from rather than guessing or mutating. Never assume `master`.
   - Infer the branch-name convention from existing branches (`git branch -a`) and any project instructions — for example `TICKET-123-short-desc`, `feature/short-desc`, or a plain `short-desc`. Only treat a ticket identifier as required if the discovered convention requires one.
   - If the convention cannot be determined, ask instead of guessing.

4. **Refresh and freeze the base — no branch mutation yet**:
   - Refreshing the base is optional and only attempted when network access is available and expected. A plain `git fetch origin` is NOT safe to promise as touching `origin/*` alone: it follows the configured `remote.origin.fetch` refspec, which can legitimately target `refs/heads/*` and force-update a local branch (for example a `+refs/heads/main:refs/heads/owner-saved` mapping). Do not assume it leaves local branches untouched.
   - Prefer a fetch that cannot write any local or remote-tracking ref — fetch just the selected base with an empty refmap and a no-destination refspec, suppressing tag/prune/submodule effects the owner's config might enable:
     `git fetch --no-tags --no-prune --no-prune-tags --recurse-submodules=no --refmap= origin refs/heads/<base>`
     The empty `--refmap=` makes Git ignore the configured `remote.origin.fetch` for this command, and a refspec with no destination updates only `FETCH_HEAD`, leaving every branch and tracking ref in place.
   - Freeze the exact base commit from that fetch: `git rev-parse --verify FETCH_HEAD^{commit}` and keep that full SHA. Do not then re-resolve `origin/<base>` as if it were freshly fetched — the constrained fetch deliberately did not move it. Every later step branches from this one frozen SHA, so a concurrent move of the base cannot shift the branch point.
   - If the project documents its own fetch step instead, inspect its refspec and effects first; if it would update a local ref, stop and get authorization for that side effect rather than guaranteeing it cannot happen. Never rewrite the owner's Git configuration to make a fetch safe.
   - If the network is unavailable, do not claim a fresh fetch. Freeze the base from the already-known commit with `git rev-parse --verify <base>`, say it is a cached base, or ask the user — whichever the project policy calls for.
   - Do not create, switch, or modify any branch in this step.

5. **Name, validate, then create the branch exactly once**:
   - Build `<branch>` from the discovered convention: kebab-case the description and prefix it with the ticket only when the convention uses one.
   - Validate the name and check for a collision BEFORE any branch mutation: `git show-ref --verify --quiet refs/heads/<branch>` for a local branch and `git rev-parse --verify --quiet refs/remotes/origin/<branch>` for a remote one. If either already exists, choose a distinct name or ask — never overwrite an existing branch.
   - Only once the name is validated and collision-free, create the branch a single time from the frozen base SHA: `git checkout -b <branch> <base-sha>`. This is the only branch-creating command in the procedure.

6. **Publish only when requested or already authorized**:
   - Push with upstream tracking (`git push -u origin <branch>`) only if the project workflow expects it or the user asked for it. Otherwise leave the branch local and say so.

7. **Report**:
   - State the new branch name, the base branch and its exact SHA, and whether the branch was pushed. Suggest `/commit-pr` when the work is ready.

**Notes**:
- The base branch is discovered, not assumed — `master`, `main`, or a configured default are all handled; when none is known, ask rather than defaulting to whatever branch is checked out.
- A ticket identifier is used only when the repository's convention calls for one; it is not mandatory.
- Uncommitted work is never discarded or moved implicitly.
- The optional base refresh writes only `FETCH_HEAD` (empty `--refmap=`, no-destination refspec), so it cannot move a local branch even under a custom `remote.origin.fetch`; a plain `git fetch` is not assumed to be side-effect free.
- The branch is created exactly once, from the frozen base SHA, and only after its name and collisions are validated.
