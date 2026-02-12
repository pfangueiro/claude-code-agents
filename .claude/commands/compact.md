---
description: "Summarize current session context into HANDOFF.md and compact the conversation"
argument-hint: "[message]"
---

Create a HANDOFF.md file to preserve session context, then compact the conversation.

## Steps

1. **Check for existing HANDOFF.md** in the project root. If one exists, read it first.

2. **Gather current session context**:
   - What task(s) were worked on this session
   - Files created, modified, or deleted
   - Key decisions made and their rationale
   - Approaches that worked and didn't work
   - What remains to be done

3. **Write HANDOFF.md** at the project root using this format:

```markdown
# Handoff — [Project Name]

**Date**: [current date and time]
**Branch**: [current git branch]

## Goal
[Overall objective]

## Current Progress
- [Completed work with file paths]

## What Worked
- [Successful approaches]

## What Didn't Work
- [Failed approaches to avoid repeating]

## Next Steps
1. [Prioritized action items]
```

4. **If the user provided a message** via `$ARGUMENTS`, include it in the "Next Steps" section as additional context.

5. **Confirm** the HANDOFF.md was written and show a brief summary of what was captured.

6. **Run `/compact`** to compress the conversation context.

The next session can start by reading HANDOFF.md to resume with full context.
