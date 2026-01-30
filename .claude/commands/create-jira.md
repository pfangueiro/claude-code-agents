---
description: Create a new JIRA issue (Epic or Story/Task) and assign to current user
argument-hint: <type> [epic-key] <title>
---

Create a new JIRA issue in the JPT Portal project and automatically assign it to you.

## Usage Examples

**Create a new Epic:**
```
/create-jira epic Improve Dashboard Performance
/create-jira epic Add User Management Features
```

**Create a Story under an Epic:**
```
/create-jira story PROJ-753 Add filter functionality to alerts
/create-jira story PROJ-905 Implement mobile responsive design
```

**Create a Task under an Epic:**
```
/create-jira task PROJ-753 Fix TypeScript compilation errors
/create-jira task PROJ-905 Update documentation
```

## Command Workflow

1. **Validate arguments (MANDATORY)**:
   - Check if `$ARGUMENTS` is provided
   - If missing or empty, STOP and display error:
     ```
     ❌ Error: Arguments required

     Usage:
       /create-jira epic <Title Here>
       /create-jira story <EPIC-KEY> <Title Here>
       /create-jira task <EPIC-KEY> <Title Here>

     Examples:
       /create-jira epic Improve Dashboard Performance
       /create-jira story PROJ-753 Add filtering to alerts
       /create-jira task PROJ-905 Fix mobile CSS issues
     ```
   - DO NOT proceed further if arguments are missing

2. **Parse and validate issue type**:
   - First argument must be: `epic`, `story`, or `task`
   - If invalid, STOP and show same error message as above
   - Convert to proper case: Epic, Story, Task

3. **Parse remaining arguments**:
   - For `epic`: All remaining arguments become the title
   - For `story`/`task`:
     - Second argument must be epic key (format: PROJ-XXX)
     - Validate epic key format (starts with PROJ- followed by numbers)
     - If invalid format, STOP and show error:
       ```
       ❌ Error: Invalid epic key format
       Expected: PROJ-XXX (e.g., PROJ-753)
       Provided: [invalid-key]
       ```
     - Remaining arguments become the title

4. **Get current user email**:
   - Run `git config user.email` to get user's email
   - This will be used to assign the issue

5. **Execute JIRA creation script**:
   - Run: `node scripts/create-jira-issue.mjs <type> [epic-key] "<title>"`
   - Examples:
     - `node scripts/create-jira-issue.mjs Epic "Improve Dashboard Performance"`
     - `node scripts/create-jira-issue.mjs Story PROJ-753 "Add filter functionality"`
     - `node scripts/create-jira-issue.mjs Task PROJ-905 "Fix mobile CSS"`
   - Pass user email as environment variable: `USER_EMAIL="user@your-company.com"`

6. **Parse script output**:
   - Script returns JSON with: `{ success: true, issueKey: "PROJ-XXX", issueId: "123", url: "https://..." }`
   - Or error: `{ success: false, error: "Error message" }`

7. **Display result**:
   - On success:
     ```
     ✅ JIRA issue created successfully!

     Issue Key: PROJ-XXX
     Type: Epic/Story/Task
     Title: [title]
     Assignee: [user email]
     URL: https://your-jira-instance.com/browse/PROJ-XXX

     🎯 Issue has been assigned to you and is ready to work on!
     ```
   - On failure:
     ```
     ❌ Failed to create JIRA issue

     Error: [error message]

     Please check:
     - Your git user.email is set correctly
     - You have access to JIRA
     - The epic key exists (if creating story/task)
     ```

## Important Notes

- **Auto-assignment**: Issue is automatically assigned to the git user (from `git config user.email`)
- **Project**: All issues are created in the "JPT Portal" project (JMIA)
- **Priority**: Default priority is "Medium"
- **Labels**: Automatically tagged with "claude-created"
- **Epic Link**: For stories/tasks, the epic key must exist in JIRA
- **Description**: Auto-generated with "🤖 Created via Claude Code" footer

## Validation Rules

1. **Issue Type**: Must be `epic`, `story`, or `task` (case-insensitive)
2. **Epic Key**: Must match pattern `PROJ-\d+` (e.g., PROJ-753)
3. **Title**: Cannot be empty, max 255 characters
4. **User Email**: Must be configured in git and exist in JPT database

## Troubleshooting

**"User not found in database"**
- Your git email doesn't match any user in JPT
- Run `git config user.email` to check your email
- Contact admin to add your email to the system

**"Epic key not found"**
- The epic key doesn't exist in JIRA
- Verify the epic exists: https://your-jira-instance.com/browse/PROJ-XXX
- Use `/create-jira epic` to create the epic first

**"Permission denied"**
- You don't have permission to create issues in JIRA
- Contact your JIRA admin for access

## Technical Details

**Script Location**: `scripts/create-jira-issue.mjs`

**JIRA Fields Used**:
- `project`: JMIA (JPT Portal)
- `issuetype`: Epic/Story/Task
- `summary`: Issue title
- `customfield_12000`: Epic Link (for stories/tasks)
- `assignee`: Current git user
- `priority`: Medium (default)
- `labels`: ["claude-created"]
- `description`: Auto-generated with Claude Code footer

**Database Tables**:
- `jira_instances`: JIRA credentials
- `users_acl`: User validation and username lookup
