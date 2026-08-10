---
name: handoff
description: Create HANDOFF.md files for session continuity between conversations. Use when ending a session, switching context, or before /compact.
---

# Handoff

Preserve context across Claude Code sessions by writing a structured HANDOFF.md file at the project root.

## When to Use

- Before ending a long session
- Before running `/compact` to free context
- When switching to a different task and planning to return
- When handing work to another developer or agent

## How It Works

1. Check if a HANDOFF.md already exists in the project root
2. If it does, read it first to build on previous context
3. Write/update HANDOFF.md with the five sections below

## HANDOFF.md Format

**This is the canonical definition of the HANDOFF.md format.** `/compact` reproduces this
template inline for convenience; if the two ever disagree, this file is correct. See
**Related — who owns what** at the end.

```markdown
# Handoff — [Project Name]

**Date**: YYYY-MM-DD HH:MM
**Branch**: current git branch

## Goal
What we're trying to accomplish overall.

## Current Progress
- What's been completed this session
- Files created or modified (with paths)
- Decisions made and rationale

## What Worked
- Approaches or patterns that succeeded
- Key insights discovered

## What Didn't Work
- Approaches tried and abandoned (with reasons)
- Pitfalls to avoid next time

## Next Steps
1. Specific actionable items for the next session
2. Ordered by priority
3. Include file paths and context needed
```

## Rules

- Always include the current git branch and date
- Be specific about file paths — the next session has zero context
- List what didn't work so the next session doesn't repeat failed approaches
- Keep it under 100 lines — enough to resume, not a novel
- If a HANDOFF.md exists, update it rather than overwriting blindly

## Example

```markdown
# Handoff — checkout-service

**Date**: 2026-02-12 14:30
**Branch**: feat/stripe-checkout

## Goal
Implement Stripe checkout flow with webhook verification.

## Current Progress
- Created `src/api/checkout.ts` with createSession endpoint
- Added `src/api/webhooks/stripe.ts` for webhook handler
- Database migration `migrations/005_orders.sql` applied
- Unit tests passing for checkout session creation

## What Worked
- Using Stripe's PaymentIntent API instead of Charges (simpler flow)
- Zod schema validation on webhook payload before processing

## What Didn't Work
- Tried using Stripe Checkout Sessions redirect — didn't work with SPA routing
- webhook signature verification failed when using raw body parser from express (need raw buffer)

## Next Steps
1. Fix webhook body parsing — use `express.raw()` middleware for `/api/webhooks/stripe`
2. Add idempotency key to prevent duplicate order creation
3. Write integration tests for the full checkout -> webhook -> order flow
4. Add error handling for failed payments (update order status)
```

## Related — who owns what

Three entry points produce a session record, and they duplicate easily. **This skill owns the
HANDOFF.md format**; the commands own their surrounding workflow.

| Entry point | Owns | Writes to | Use when |
|---|---|---|---|
| **`handoff` skill** (this file) | **The HANDOFF.md format — canonical** | `HANDOFF.md` at project root | You want the file and nothing else |
| **`/compact`** | The compact *workflow*: write the handoff, then compress the conversation | `HANDOFF.md` at project root, using this template | You are out of context and continuing in the **same** session |
| **`/save-session`** | A different, richer format with a **mandatory** "What Did NOT Work" section carrying exact error messages | `~/.claude/sessions/<id>.md` — global, keeps the working tree clean | You want a resumable record across sessions, reloaded with `/resume-session` |

**Ownership rule:** if the HANDOFF.md format changes, change it *here*. `/compact` restates this
template inline, so any divergence means `/compact` is stale — update `/compact` to match rather
than forking a second format.

`/save-session` is deliberately **not** this template. It is a superset with a stricter failure
record and a global location, so the two are not interchangeable and must not be merged.

For choosing between truncating, forking a subagent, `/compact`, and a full handoff, see the
`context-escalation` skill.
