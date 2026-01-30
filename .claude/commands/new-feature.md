---
description: Create a new feature branch from the latest master branch
argument-hint: PROJ-XXX description
---

Create a new feature branch following best practices:

1. **Validate arguments (MANDATORY)**:
   - Check if `$ARGUMENTS` is provided
   - If missing or empty, STOP and display error:
     - "❌ Error: Ticket number and description required"
     - "Usage: `/new-feature PROJ-XXX description`"
     - "Example: `/new-feature PROJ-755 add-export-functionality`"
     - DO NOT proceed further
   - Validate format: Must start with "PROJ-" followed by numbers
   - If invalid format, STOP and show the same error message

2. **Check for uncommitted changes**:
   - Run `git status --porcelain` to check for uncommitted changes
   - If changes exist, STOP and warn the user:
     - "⚠️ You have uncommitted changes. Please commit or stash them first:"
     - List the changed files
     - Suggest: `git stash` or `/commit-pr` to save changes
     - DO NOT proceed further

3. **Fetch and update master**:
   - Run `git fetch origin` to get latest remote changes
   - Run `git checkout master` to switch to master branch
   - Run `git pull origin master` to update local master

4. **Parse branch name from arguments**:
   - Format: `$ARGUMENTS` should be in form "PROJ-XXX description-here"
   - Extract ticket number (e.g., PROJ-755) and description
   - Convert description to kebab-case (lowercase with hyphens)
   - Final branch name: `PROJ-XXX-description` (e.g., `PROJ-755-add-user-permissions`)

5. **Create and push new branch**:
   - Run `git checkout -b [branch-name]` to create new branch
   - Run `git push -u origin [branch-name]` to push and set upstream tracking

6. **Confirm success**:
   - Display: "✅ New branch created: `[branch-name]`"
   - Display: "🚀 Ready to start working on your feature!"
   - Display: "📝 When done, use `/commit-pr` to commit and create a pull request"

**Important notes**:
- Base branch is always `master`
- Ticket number (PROJ-XXX) is MANDATORY
- Arguments are REQUIRED - command will not run without them
- Example usage: `/new-feature PROJ-755 add-export-functionality`