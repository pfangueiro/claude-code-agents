---
name: deep-analysis
description: Runs a long, structured multi-step reasoning chain over the sequential-thinking MCP server, with branching, revision, and explicit hypothesis verification. Reserved for consequential, genuinely open problems whose answer cannot be reached by reading the code — an architecture decision with several defensible options, an unexplained performance bottleneck, technology selection, design trade-offs, or a migration and risk strategy. Because it is slow and token-heavy it is not for questions with one correct answer, factual or syntax lookups, summarizing or explaining existing code, a defect with an obvious cause, or applying a fix already chosen. Prefer /investigate for root-cause work on a reproducible defect, and /diverge when the need is a wide option space rather than one reasoned conclusion.
context: fork
argument-hint: "<problem description or question requiring deep reasoning>"
---

# Deep Analysis — Structured Reasoning Engine

Multi-step reasoning through the sequential-thinking MCP server. Decomposes complex problems into discrete thinking steps with branching, revision, and hypothesis verification.

## When to Use

- Architectural decisions with multiple valid approaches
- Performance diagnosis where the bottleneck is unclear
- Technology selection requiring trade-off evaluation
- Complex debugging (use `/investigate` for full root cause protocol)
- System design with many interconnected parts
- Migration strategies with risk assessment

**Do NOT use for:** Simple lookups, straightforward implementations, well-established patterns, or tasks where the answer is obvious.

## Pre-Flight Gate

Activation is decided by the frontmatter description alone — this file is read only AFTER the skill
has been selected. Nothing here can prevent over-triggering, so this gate is a **post-selection
redirect**, not a filter.

**Before proceeding, check the ABORT conditions below. If any holds, STOP, say in one line which one
fired, and take the redirect instead of starting the chain.** Being invoked — including a literal
`/deep-analysis` or "give me a deep analysis" — does NOT override an ABORT: the phrasing that
selected this skill is not evidence the problem is hard.

| ABORT when the ask is… | Redirect |
|---|---|
| A factual, syntax, or definition lookup — anything with one correct answer | Answer directly |
| Summarizing or explaining existing code | Read the code and answer (`/deep-read` if it is large) |
| A well-established pattern or a straightforward implementation | Implement it directly |
| A defect with an obvious cause, or a fix the user already chose | Apply the fix directly |
| A reproducible defect whose cause is genuinely unknown | `/investigate` — 8-phase root cause |
| A wide option space rather than one reasoned conclusion | `/diverge` first, then return here to converge |
| Answerable by reading the code or running one command | Do that instead |

**PROCEED only when no ABORT fired AND the problem is genuinely open** — several defensible answers,
an architectural or trade-off decision, an unexplained bottleneck, or a design space that must be
reasoned through rather than looked up.

## Protocol

### 1. Frame the Problem

Start the sequential-thinking chain with a clear problem statement and all known constraints.

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "PROBLEM: <clear statement>. CONSTRAINTS: <known limits>. Let me decompose this...",
  thoughtNumber: 1,
  totalThoughts: 10,  // Initial estimate — adjust as needed
  nextThoughtNeeded: true
})
```

### 2. Reason Through Steps

Each thought builds on the previous. Adjust `totalThoughts` up or down as understanding deepens.

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "Step 2: Analyzing option A. Strengths: ... Weaknesses: ...",
  thoughtNumber: 2,
  totalThoughts: 10,
  nextThoughtNeeded: true
})
```

### 3. Branch When Alternatives Exist

Explore competing approaches without losing the main thread.

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "BRANCH: What if we use approach B instead? Let me evaluate...",
  thoughtNumber: 5,
  totalThoughts: 12,
  nextThoughtNeeded: true,
  branchFromThought: 3,
  branchId: "approach-B"
})
```

### 4. Revise When Evidence Changes

Don't force a conclusion — revise earlier thinking when new evidence contradicts it.

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "REVISION: My assumption in step 3 was wrong. Evidence shows X instead of Y...",
  thoughtNumber: 7,
  totalThoughts: 14,
  nextThoughtNeeded: true,
  isRevision: true,
  revisesThought: 3
})
```

### 5. Conclude with Verification

Final thought must verify the conclusion against the original problem and constraints.

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "CONCLUSION: Approach A is recommended because [evidence]. Verified against constraints: [check]. Risks: [list].",
  thoughtNumber: 10,
  totalThoughts: 10,
  nextThoughtNeeded: false
})
```

## Key Parameters

| Parameter | Type | Purpose |
|-----------|------|---------|
| `thought` | string | Current reasoning step |
| `thoughtNumber` | int | Current step (1-based) |
| `totalThoughts` | int | Estimated total steps (adjustable) |
| `nextThoughtNeeded` | bool | `false` only when truly done |
| `isRevision` | bool | Revising a previous thought |
| `revisesThought` | int | Which thought number to revise |
| `branchFromThought` | int | Branching point for alternatives |
| `branchId` | string | Label for the branch |
| `needsMoreThoughts` | bool | Need more steps than estimated |

## Thinking Budget

- Up to 31,999 tokens per reasoning chain
- Typical analyses: 8-15 steps
- Adjust `totalThoughts` dynamically — don't force exactly N steps
- Balance depth vs response time

## Integration with Other Skills

| Situation | Use |
|-----------|-----|
| Bug with unknown root cause | `/investigate` (calls deep-analysis in Phase 4) |
| Multi-step implementation goal | `/execute` (may call deep-analysis for complex sub-tasks) |
| Architecture decision only | `/deep-analysis` directly |
| Trade-off evaluation only | `/deep-analysis` directly |
| Option space too narrow — widen before converging | `/diverge` (divergent complement; widen first, then converge here) |

## References

- [Reasoning Patterns](references/reasoning-patterns.md) — hypothesis testing, design space exploration, root cause templates
- [Integration Guide](references/integration-guide.md) — pairing with agents and other skills
