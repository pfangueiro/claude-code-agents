# Independently review a pull request

Resolve the requested PR number or URL from the task text. Discover GitHub MCP or
the installed `gh` CLI and confirm the selected repository/account. A PR identifier
is a single argument: for CLI calls, assign it to a task-specific variable and quote
that variable; do not insert an English description or untrusted shell text.

Retrieve the PR metadata, base/head SHAs, full diff, discussion and required check
results. Read relevant source at the exact head SHA, using a read-only checkout or
isolated worktree when necessary. Use the code-review checklist, applicable specialist
role guides, primary docs and executable reproductions for correctness/security/
testing findings. Fresh reviewers must not have implemented the change under review.

Reproduce material findings and distinguish source-proven defects from uncertainty.
Report prioritized issues with file/line evidence, commands and outputs, exact reviewed
SHA, test coverage and residual risks. Approval depends on required checks at that
same head and resolution of material findings. A green local build alone is insufficient.

Publish a review/comment or change approval state only if the user explicitly requested
that external effect. Otherwise return the review in conversation. Recheck the PR head
before publishing; if it changed, review the new delta before claiming current approval.
