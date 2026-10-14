---
description: Commit and publish the requested scope with project-selected policy, exact-head gates and honest per-effect states
argument-hint: [optional commit message]
disable-model-invocation: true
---

Commit and publish only the effects that are authorized. Commit, push, PR, issue
update, merge, release and branch deletion are distinct effects. Invoking this
command authorizes commit, push and PR creation for the current change once the
gates below pass; anything beyond that needs existing explicit authorization or
project policy that grants it.

1. **Analyze state.** Run `git status`, the full branch diff against the base and
   `git log`. Record the branch, the input SHA and any unrelated dirty files. Read
   the project instructions for commit convention, base branch, required checks,
   review, release and issue policy. Never assume a default branch, version file or
   ticket prefix — discover the base from the repository (for example
   `gh repo view --json defaultBranchRef`).

2. **Version.** Bump a version only when the project's release policy requires it
   for this change. Verify package and lockfile consistency before committing.

3. **Stage and commit.** Stage only the intended paths; preserve unrelated files.
   - If $ARGUMENTS is provided, use it as the commit message; otherwise write one
     that follows the repository convention.
   - Follow the owner's attribution preference. Add no assistant or AI footer or
     trailer unless the owner's policy asks for one.
   - Never skip hooks, amend earlier commits or force-push unless explicitly asked.
   - Record the resulting commit SHA as the candidate.

4. **Local checks.** Run the project's required local checks on the candidate and
   record commands and exit statuses. A failed or missing required check holds
   push and PR creation; report the check and stop.

5. **Independent review.** Obtain an independent verdict that covers the exact
   candidate SHA. Unresolved blockers, or no available independent reviewer, hold
   push and PR creation; name the gap. Any new commit after the verdict invalidates
   it: rerun steps 4 and 5 for the new candidate.

6. **Push and create the PR.** Confirm the head to push equals the reviewed
   candidate. Use the account and credentials the environment already selects; do
   not override authentication. Verify repository, base branch and the pushed head
   SHA. The PR body lists the summary of all branch changes, validation actually run,
   the reviewed SHA and material gaps. Pass the body as a file or structured argument
   so newlines survive.

7. **Issue tracker.** Update a ticket only when the project configures an integration
   and the update is authorized. Discover the actual tool; do not assume a project
   key, script or credential source exists.

8. **Merge.** Only when authorized, and only after the configured required checks
   and approvals apply to the exact current PR head SHA and the branch is up to date
   with its base. Conflict-free is not green. Stop on missing, pending or failing
   checks and on unresolved review findings; report the gate and its owner.

9. **Release and cleanup.** Create a release only when authorized and project policy
   defines one, after verifying the merged target SHA and the version/tag policy.
   Delete branches only when authorized; never force-delete a branch with unmerged work.

10. **Report.** For each effect state done, held (with gate), skipped (with reason)
    or failed. Include the PR URL, reviewed and pushed head SHAs and check statuses.
    A partial publish is never reported as complete; keep enough identifiers to
    resume safely.
