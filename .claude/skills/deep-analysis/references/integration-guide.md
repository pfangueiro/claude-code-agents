# Integration Guide — Deep Analysis with Skills & Agents

How deep-analysis connects with other skills and agents in the toolchain.

---

## Skill Relationships

### /investigate (root cause analysis)

`/investigate` uses deep-analysis internally in **Phase 4: HYPOTHESIZE**.

```
/investigate "app crashes on document delete"
  Phase 1-3: Observe, Reproduce, Trace (gathering evidence)
  Phase 4: HYPOTHESIZE → calls deep-analysis for 5 Whys reasoning
  Phase 5-8: Prove, Root Cause, Fix, Prevent
```

**When to use which:**
- `/investigate` — a reproducible defect whose cause is genuinely **unknown**: 8 phases, including a
  PROVE phase that tests each hypothesis against evidence before any cause is named
- `/deep-analysis` — a decision that is genuinely **open**: several defensible answers to weigh, and
  no cause that needs proving

The split is unknown-cause vs open-decision — **not** "makes code changes vs doesn't". Reasoning
about an unexplained defect instead of investigating it substitutes plausibility for the PROVE
phase, so deep-analysis ABORTs on it (SKILL.md ABORT row: *a reproducible defect whose cause is
genuinely unknown → `/investigate`*).

### /deep-read (codebase reading engine)

`/deep-read` produces thorough source-code understanding that feeds directly into `/deep-analysis` for reasoning.

```
/deep-read "the billing pipeline"
  Phases 1-4: Scope, Map, Trace, Deep Read (reads actual source code)
  Phase 5: CONNECT → may call deep-analysis for pattern synthesis
  Phase 6: Report with file:line citations
```

**When to use which:**
- `/deep-read` — understand how code works by reading it systematically
- `/deep-analysis` — reason about decisions, trade-offs, or design problems

**Combined workflow:**
```
/deep-read "payment processing flow"   → Understand the current implementation
/deep-analysis "should we refactor to event sourcing?"  → Reason about the change
```

### /execute (orchestrated task engine)

`/execute` may invoke deep-analysis when a sub-task requires complex reasoning during implementation.

```
/execute "migrate from REST to GraphQL"
  Task #1: Research current API surface → Explore agent
  Task #2: Design GraphQL schema → deep-analysis (trade-offs)
  Task #3: Implement resolvers → api-backend agent
  ...
```

**When to use which:**
- `/execute` — multi-step implementation with task tracking and parallelism
- `/deep-analysis` — reasoning about a single decision within a larger workflow

---

## Agent Pairings

### architecture-planner

**Flow:** deep-analysis reasons about the design, architecture-planner produces the specification.

```
1. /deep-analysis "Should we use event sourcing or CRUD for the invoice pipeline?"
   → Produces: Reasoned recommendation with trade-offs
2. architecture-planner agent
   → Produces: Detailed architecture spec, API contracts, component diagram
```

### performance-optimizer

**Flow:** the cause is already proven; deep-analysis weighs the competing remedies, and
performance-optimizer implements the one chosen.

```
1. /deep-analysis "Profiling proves the dashboard issues 40 queries per page load (N+1 on
   line items). Eager-load, materialized view, or read-through cache?"
   → Produces: Trade-off analysis — staleness vs write amplification vs operational cost,
     with a recommendation and its risks
2. performance-optimizer agent
   → Produces: Implementation of the chosen strategy, before/after benchmark
```

**Boundary:** deep-analysis chooses between remedies for a **proven** cause. A slowdown whose cause
is *not* yet proven — "response time degraded from 200ms to 2s, nobody knows why" — is an ABORT
here and goes to `/investigate`. Naming a root cause by reasoning alone is exactly the failure the
PROVE phase exists to prevent.

### database-architect

**Flow:** deep-analysis evaluates schema design trade-offs, database-architect implements.

```
1. /deep-analysis "Should we denormalize the line items table for read performance?"
   → Produces: Analysis of read/write trade-offs, data consistency risks
2. database-architect agent
   → Produces: Migration plan, updated schema, index strategy
```

---

## Decision Tree: Which Tool for the Job

Walk the branches in order. The defect branch is first because it is the one most often
skipped, and `/deep-analysis` is a narrow exit rather than the fallback.

```
1. Is it a bug, crash, error, regression, or unexplained slowdown?
   ├── Cause already obvious, or the fix already chosen
   │     → apply the fix directly
   └── Cause genuinely unknown
         → /investigate — NOT /deep-analysis. You still get the reasoning
           (Phase 4 HYPOTHESIZE calls deep-analysis), plus the Phase 5 PROVE
           step that deep-analysis has no substitute for.

2. Not a defect. Is it answerable by reading the code or running one command?
   ├── YES, and the code is large → /deep-read, then answer
   └── YES                        → answer directly / direct tool calls

3. Is it a multi-step implementation goal?
   └── YES → /execute (which may call deep-analysis for one open sub-decision)

4. Is it a genuinely open decision — architecture or technology choice, a
   trade-off, a design space with several defensible answers?
   ├── The decision is about EXISTING code you have not read
   │     → /deep-read FIRST, then this step. Reasoning over a codebase you
   │       have not read produces confident conclusions about imagined code.
   ├── Option space still too wide to converge → /diverge first, then converge here
   └── One reasoned conclusion needed          → /deep-analysis

5. Anything else → answer directly.
```

`/deep-analysis` is **not** the default exit. Every branch above that routes elsewhere is a
branch it must not swallow — reaching step 5 means answer directly, not "reason about it anyway".

---

## Common Combinations

| Scenario | Sequence |
|----------|----------|
| Codebase onboarding | /deep-read |
| Understand then redesign | /deep-read → /deep-analysis → /execute |
| Code review with full context | /deep-read → code-quality agent |
| Architecture decision + implementation | /deep-analysis → /execute |
| Performance issue investigation | /investigate (uses deep-analysis in Phase 4) |
| Technology selection + migration | /deep-analysis → architecture-planner → /execute |
| Complex bug → fix → prevent | /investigate (full protocol) |
| Design review of existing code | /deep-read → code-quality agent (add /deep-analysis only if an open trade-off survives the read) |
