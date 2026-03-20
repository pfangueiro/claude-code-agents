---
description: "Save structured session state to a global session file for cross-session continuity"
argument-hint: "[session-id or description]"
---

Save the current session's state to a structured file in `~/.claude/sessions/` for later resumption.

## Key Improvement Over /compact

This command stores a mandatory **"What Did NOT Work"** section with exact error messages — preventing the next session from retrying failed approaches. It also saves globally (not in the project root) to keep the working tree clean.

## Steps

1. **Create sessions directory** if it doesn't exist:
   ```
   mkdir -p ~/.claude/sessions
   ```

2. **Generate session ID**:
   - If `$ARGUMENTS` is provided, use it as the session identifier (slugified)
   - Otherwise, generate from: `YYYY-MM-DD-<project-name>-<short-hash>`
   - File path: `~/.claude/sessions/<session-id>.md`

3. **Gather session context** by analyzing the conversation:

   - **Goal**: What was the user trying to accomplish?
   - **Progress**: What was completed? List files created/modified with paths.
   - **What Worked**: Approaches and techniques that succeeded. Include evidence (test output, build success, etc.)
   - **What Did NOT Work**: **MANDATORY** — failed approaches with:
     - The exact error message or failure output
     - Why it failed (root cause if known)
     - What was tried to fix it
     - Why the approach was abandoned
   - **Decisions Made**: Architecture, library, or approach choices with rationale
   - **Next Steps**: Prioritized remaining work
   - **File States**: Key files and their current state (modified, created, deleted)

4. **Write the session file**:

```markdown
# Session: <session-id>

**Date**: <current date and time>
**Project**: <project directory name>
**Branch**: <current git branch>
**Duration**: <approximate session duration if estimable>

## Goal
<What was being accomplished>

## Progress
- [x] <Completed item with file paths>
- [ ] <Incomplete item>

## What Worked
- <Approach that succeeded> — Evidence: <test output, build success, etc.>

## What Did NOT Work (and why)
> This section prevents the next session from repeating failed approaches.

### <Failed approach 1>
- **Error**: `<exact error message>`
- **Root cause**: <why it failed>
- **Attempted fixes**: <what was tried>
- **Verdict**: <why abandoned — e.g., "incompatible with X", "upstream bug", "wrong approach">

### <Failed approach 2>
- **Error**: `<exact error message>`
- ...

## Decisions Made
- <Decision>: <rationale>

## Next Steps
1. <Most important remaining task>
2. <Next task>
3. <Future consideration>

## File States
| File | Status | Notes |
|------|--------|-------|
| <path> | created/modified/deleted | <brief note> |
```

5. **Confirm** with:
   ```
   Session saved: ~/.claude/sessions/<session-id>.md
   Resume with: /resume-session <session-id>
   ```

6. **Optionally run /compact** to compress the conversation context after saving.

**Important notes:**
- The "What Did NOT Work" section is **mandatory** — never skip it, even if everything succeeded (write "No failed approaches this session")
- Include exact error messages, not paraphrased versions
- Session files are global (`~/.claude/sessions/`) — they don't clutter the project
- This complements (not replaces) the existing `/compact` command
