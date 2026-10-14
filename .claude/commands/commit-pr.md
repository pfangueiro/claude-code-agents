---
description: Commit and publish the requested scope with project-selected policy, exact-head gates and honest per-effect states
argument-hint: [optional commit message]
disable-model-invocation: true
---

Commit and publish only the effects that are authorized. Commit, push, PR, issue
update, merge, release and branch deletion are distinct effects. Invoking this
command authorizes commit, push and PR creation for the current change; anything
beyond that needs existing explicit authorization or project policy that grants it.

1. **Analyze state.** Run `git status`, the full branch diff against the base and
   `git log`. Record the branch, the input SHA and any unrelated dirty files. Read
   the project instructions for commit convention, base branch, release and issue
   policy. Never assume a default branch, version file or ticket prefix — discover
   the base from the repository (for example `gh repo view --json defaultBranchRef`).

2. **Version.** Bump a version only when the project's release policy requires it
   for this change. Verify package and lockfile consistency before committing.

3. **Stage and commit.** Stage only the intended paths; preserve unrelated files.
   - If $ARGUMENTS is provided, use it as the commit message; otherwise write one
     that follows the repository convention.
   - Follow the owner's attribution preference. Add no assistant or AI footer or
     trailer unless the owner's policy asks for one.
   - Never skip hooks, amend earlier commits or force-push unless explicitly asked.

4. **Check before publishing.** Run the project's required local checks and record
   their commands and exit statuses. Do not push work whose required checks failed
   without saying so.

5. **Push and create the PR.** Use the account and credentials the environment
   already selects; do not override authentication. Verify repository, base branch
   and the pushed head SHA. The PR body lists the summary of all branch changes,
   validation actually run and material gaps. Pass the body as a file or structured
   argument so newlines survive.

6. **Issue tracker.** Update a ticket only when the project configures an integration
   and the update is authorized. Discover the actual tool; do not assume a project
   key, script or credential source exists.

7. **Merge.** Only when authorized, and only after the configured required checks
   and approvals apply to the exact current PR head SHA and the branch is up to date
   with its base. Conflict-free is not green. Stop on missing, pending or failing
   checks and on unresolved review findings; report the gate and its owner.

8. **Release and cleanup.** Create a release only when authorized and project policy
   defines one, after verifying the merged target SHA and the version/tag policy.
   Delete branches only when authorized; never force-delete a branch with unmerged work.

9. **Report.** For each effect state done, skipped (with reason) or failed. Include
   the PR URL, head SHA and check statuses. A partial publish is never reported as
   complete; keep enough identifiers to resume safely.
