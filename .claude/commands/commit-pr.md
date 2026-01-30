---
description: Stage changes, commit, push, create GitHub PR, auto-update JIRA, auto-merge, and create release
argument-hint: [optional commit message]
---

Execute the complete git workflow with JIRA integration and automatic release creation:

**IMPORTANT**: The automatic "Update Package Version on Release" workflow has been removed to prevent version mismatch issues. This command now handles version updates BEFORE creating release tags to ensure package.json version matches the Docker image version.

1. **Analyze current state**:
   - Run git status, git diff, and git log -1 to analyze current changes and branch
   - Extract JIRA ticket number from branch name (e.g., PROJ-755-test → PROJ-755)

2. **Automatically determine version and update package.json BEFORE committing**:
   - Get the latest release tag using env -u GITHUB_TOKEN gh release list --limit 1
   - Parse current version (e.g., 2.1.4)
   - **Automatically determine version increment based on changes:**
     - If changes contain BREAKING CHANGE: or !: → increment MAJOR (2.1.4 → 3.0.0)
     - If changes are new features (new files, new endpoints, new major functionality) → increment MINOR (2.1.4 → 2.2.0)
     - Otherwise (fix, chore, docs, refactor, etc.) → increment PATCH (2.1.4 → 2.1.5)
   - **IMMEDIATELY update package.json with determined version:**
     - Run: npm version <version> --no-git-tag-version
     - This happens BEFORE staging/committing (so version bump is included in the commit)
     - Display: "Version bumped: 2.1.4 → 2.1.5 (patch)"

3. **Stage all changes** with git add -A (includes package.json if it was updated)

4. **Create a commit** with a clear message:
   - If $ARGUMENTS is provided, use it as the commit message
   - Otherwise, analyze the changes and generate an appropriate message following the repository's commit style
   - Include the Claude Code generated footer: 🤖 Generated with [Claude Code](https://claude.com/claude-code)

5. **Push to the remote branch** with git push

5. **Create a GitHub PR** using gh pr create with:
   - **IMPORTANT**: Temporarily unset GITHUB_TOKEN environment variable before running gh commands to ensure PR is created with your logged-in account (not the API token user)
   - Use command: env -u GITHUB_TOKEN gh pr create ...
   - Base branch: master
   - Title from the commit message
   - Body with:
     - Summary of ALL changes in the branch (not just the latest commit)
     - Test plan checklist
     - Generated footer: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`

6. **Auto-update JIRA ticket** (only for PROJ-* branches):
   - Extract ticket key from branch name (e.g., PROJ-755 from PROJ-755-test)
   - If ticket key found, run: npx tsx scripts/update-jira-on-pr.ts <ticket-key> <pr-url> "<commit-message>" "<changes-summary>"
   - The script will:
     - **Auto-assign ticket to current git user** (reads from git config user.email)
     - Add detailed comment to JIRA ticket with PR link, commit message, and changes (uses on-prem JIRA credentials from database)
     - Update ticket description with implementation details
   - If JIRA update fails, show warning but don't fail the entire command
   - Example: npx tsx scripts/update-jira-on-pr.ts PROJ-755 "https://github.com/.../pull/17" "Add export functionality" "• Implemented CSV export\n• Added export button\n• Updated API endpoint"

7. **Check PR merge status and auto-merge if possible**:
   - Use env -u GITHUB_TOKEN gh pr view <pr-url> --json mergeable to check merge status (unset GITHUB_TOKEN)
   - If mergeable: MERGEABLE (no conflicts):
     - **Immediately auto-merge** using env -u GITHUB_TOKEN gh pr merge <pr-url> --merge --delete-branch
     - **Do NOT wait for CI checks** - merge immediately if no conflicts
     - Display success message: ✅ PR merged and branch deleted
   - If conflicts exist:
     - Display warning: ⚠️ Cannot auto-merge - conflicts detected
     - Show merge status details
   - If merge fails, don't fail the entire command (PR creation still succeeded)

8. **Auto-create GitHub Release** (only if PR was merged successfully):
   - Use the version that was already committed in package.json (from step 2)
   - Create release tag with that version:
     - Tag: version from package.json
     - Title: same as tag
     - Target: master branch (already has correct package.json version from the PR)
     - Notes: Use commit message and changes summary
     - Command: env -u GITHUB_TOKEN gh release create <tag> --target master --title "<tag>" --notes "<release-notes>"
   - **After successful release creation, close the JIRA ticket:**
     - Run: npx tsx scripts/update-jira-on-pr.ts <ticket-key> <pr-url> "<commit-message>" "<changes-summary>" --close
     - This transitions the ticket to "Closed" status
     - If transition fails, show warning but don't fail the command
   - **Delete local branch after successful release:**
     - Switch to master: git checkout master
     - Pull latest changes: git pull
     - Delete local branch: git branch -D <branch-name>
     - Display: ✅ Local branch deleted
   - If release creation fails, show warning but don't fail the command
   - Display: ✅ Release X.Y.Z created or ⚠️ Release creation failed

9. **Display summary**:
   - PR URL
   - JIRA ticket assignment status (✅ Assigned to <user> or ⚠️ Failed)
   - JIRA ticket update status (✅ Updated or ⚠️ Failed)
   - Merge status (✅ Merged or ⚠️ Manual merge required)
   - Release status (✅ Release X.Y.Z created or ⚠️ Skipped/Failed)
   - JIRA ticket closure status (✅ Closed or ⚠️ Not closed - only if release created)
   - Branch cleanup status (✅ Remote and local branches deleted or ⚠️ Manual cleanup needed)
   - Current branch (should be master after successful workflow)
   - Concise summary of what was done

**Important notes**:
**ALL gh commands MUST use env -u GITHUB_TOKEN** to prevent GITHUB_TOKEN environment variable from overriding your logged-in account
JIRA auto-update only works for branches starting with "PROJ-"
JIRA updates use the on-premise JIRA instance (your-jira-instance.com)
**JIRA ticket is automatically assigned to current git user** (from git config user.email)
**JIRA ticket is automatically closed after successful release creation**
If JIRA update/assignment/closure fails, the commit/PR still succeeds (warning shown)
The commit message should follow the repository's pattern (e.g., PROJ-XXX: description)
Auto-merge uses regular merge (not squash) and deletes the branch after merging
**Auto-merge happens immediately if no conflicts** - does NOT wait for CI checks
If auto-merge fails due to conflicts, manual merge is required
Release is only created if PR merge succeeds
**Version increment rules (Semantic Versioning - automatic):**
  - BREAKING CHANGE → MAJOR (2.1.4 → 3.0.0)
  - New features/endpoints → MINOR (2.1.4 → 2.2.0)
  - Bug fixes/chores/docs → PATCH (2.1.4 → 2.1.5)
Version is automatically determined and applied - no user confirmation needed
Release triggers GitHub Actions workflows automatically