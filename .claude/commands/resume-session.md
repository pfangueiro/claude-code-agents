---
description: "Resume a previously saved session with full context briefing"
argument-hint: "[session-id]"
---

Load a previously saved session file and produce a structured briefing to resume work.

## Steps

1. **Find the session file**:
   - If `$ARGUMENTS` is provided, look for `~/.claude/sessions/$ARGUMENTS.md` (try exact match first, then prefix match)
   - If no argument given, list the 5 most recent session files:
     ```
     ls -t ~/.claude/sessions/*.md | head -5
     ```
   - Display the list and ask which session to resume:
     ```
     Recent sessions:
     1. 2026-03-20-my-project-auth (2026-03-20) — "User authentication system"
     2. 2026-03-19-api-refactor (2026-03-19) — "REST API v2 migration"
     3. ...

     Which session? [1-5 or session-id]:
     ```

2. **Read the session file** entirely.

3. **Validate current context**:
   - Check if the current working directory matches the session's project
   - Check if the git branch matches the session's branch
   - If mismatched, warn but continue:
     ```
     Warning: Session was on branch 'feat/auth' but you're on 'main'.
     Consider: git checkout feat/auth
     ```

4. **Verify file states**:
   - For each file listed in the session's "File States" table, check if it still exists and hasn't been modified since the session was saved
   - Report any discrepancies:
     ```
     File state check:
     - src/auth.ts: unchanged since session
     - src/middleware.ts: MODIFIED since session (check git log)
     - src/routes.ts: DELETED since session
     ```

5. **Produce the briefing**:

```
## Session Resumed: <session-id>

### Context
<Goal from the session file>

### Current State
- Branch: <current branch> (session was on: <session branch>)
- Last session: <date>
- Files checked: <count> (<unchanged>/<modified>/<missing>)

### What Was Done
<Progress section from session>

### AVOID These Approaches
> These were tried and failed in the previous session:
<What Did NOT Work section — highlight this prominently>

### Decisions Already Made
<Decisions section from session>

### Next Steps (from previous session)
<Next Steps section>

### Ready to Continue
The session context has been loaded. What would you like to work on?
```

6. **If the session file is not found**:
   ```
   No session file found for '<argument>'.
   Available sessions:
   <list of all files in ~/.claude/sessions/>

   To save a session: /save-session [name]
   ```

**Important notes:**
- The "AVOID These Approaches" section should be prominent — it's the key value of session persistence
- Always check file states — the project may have changed since the session was saved
- Session files are read-only during resume — never modify them
- If no sessions directory exists, inform the user about `/save-session`
