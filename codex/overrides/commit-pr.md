# Commit and publish authorized changes

Inspect the current branch, input SHA, `git status`, full branch diff and repository
instructions. Identify the requested scope: commit, push, draft PR, merge and release
are distinct effects. Existing explicit authorization persists; skill selection alone
does not authorize every effect. Complete reviewable local work before a required approval.

1. Stage only the intended change. Preserve unrelated files and use the repository's
   commit convention and attribution preference. No generated assistant footer.
2. Apply a version bump only when the project's release policy calls for it; verify
   package and lockfile consistency before committing. Do not assume package.json exists.
3. Run the required tests and independent review. Commit without skipping hooks,
   amending prior commits or force-pushing unless specifically requested.
4. If push/PR creation is authorized, discover GitHub MCP or `gh` and verify repository,
   selected account, default base branch and current head SHA. Respect the owner's
   credential/account choice; do not silently override environment authentication.
5. Create the requested PR with summary, validation and material gaps. Use a structured
   body argument or a body file with actual newlines. Return its URL and exact head SHA.
6. If Jira synchronization is explicitly requested and configured, discover the actual
   Jira tool or repository integration, validate the ticket and perform only the authorized
   update. Do not assume a PROJ project, database credentials or a helper script exists.
7. Merge only when authorized and the required checks and independent approval apply
   to the exact current PR head. Being conflict-free does not mean CI passed. Stop on
   failing/missing required checks or unresolved review findings.
8. Create a release only when authorized, after verifying the merged target SHA and
   version/tag policy. Ticket closure and branch deletion follow their own existing
   authorization. Never force-delete a branch containing unmerged work.

Report each completed effect and any remaining dependency; partial publish failures
must not be reported as complete. Preserve enough identifiers to resume safely.
