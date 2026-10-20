---
description: Create an issue in the configured issue tracker, or hand back a ready-to-file draft when no connector is available
argument-hint: "<type> [parent] <title>"
disable-model-invocation: true
---

Create a tracker issue (epic, story, or task) using whatever issue-tracking capability this environment actually exposes. Do not assume a specific tenant, project key, credentials store, or helper script.

1. **Parse the request**:
   - Read `$ARGUMENTS` as an issue type (`epic`, `story`, or `task`), an optional parent/epic reference, and a title. If the type or title is missing, ask for it.
   - Keep drafting the issue content while you wait for any missing required field — do not block all progress on a single answer.

2. **Discover the tracker capability**:
   - Look for an issue-tracking connector or integration actually exposed to this session: an MCP tracker tool, a CLI or API documented by the project, or project instructions that name the tracker.
   - Use read-only calls to confirm the target project, the issue types it supports, and whether a parent/epic link applies.
   - Resolve defaults (project, assignee, priority, labels) from that authorized configuration or the project's own instructions — never from a hardcoded project key or database.

3. **Prepare the issue content**:
   - Compose the summary, description, type, parent link (if the type needs one), and assignee. Use the current-user convention (for example `git config user.email`) only when the tracker's configuration calls for it or the user names an assignee.
   - Validate the content against the schema the discovered capability actually supports before attempting creation.

4. **Create it — only if a connector exists**:
   - If an authorized tracker capability is available, create the issue through it, then verify and report the returned key, URL, and fields.
   - Creating the one requested issue is in scope; sending unrelated messages, notifications, or updates is not.

5. **No connector? Return a draft, honestly**:
   - If no tracker connector or runnable integration is available, report that **no issue was created** and hand back the ready-to-file draft (type, title, parent, description, suggested assignee) so the user can file it themselves.
   - Never present a draft as if it were a live, created issue.

**Notes**:
- The project, issue types, and parent conventions are discovered from the authorized configuration, not assumed.
- The command creates at most the single requested issue, and only when a real capability exists; otherwise it drafts.
