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
- `/investigate` — full 8-phase root cause protocol with evidence, fix, and prevention
- `/deep-analysis` — structured reasoning only, no code changes

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

**Flow:** deep-analysis diagnoses the bottleneck, performance-optimizer implements the fix.

```
1. /deep-analysis "API response time degraded from 200ms to 2s"
   → Produces: Root cause identified (e.g., N+1 queries in document list)
2. performance-optimizer agent
   → Produces: Optimized queries, added indexes, benchmark results
```

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

```
Do you need to understand existing code first?
├── YES: Use /deep-read (then chain to other skills as needed)
└── NO: Complex problem requiring reasoning?
    ├── YES: Is it a bug/crash/error?
    │   ├── YES: Use /investigate (full protocol)
    │   └── NO: Is it a design/architecture decision?
    │       ├── YES: Use /deep-analysis
    │       └── NO: Is it a multi-step implementation?
    │           ├── YES: Use /execute
    │           └── NO: Use /deep-analysis
    └── NO: Use regular response or direct tool calls
```

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
| Design review of existing code | /deep-analysis + code-quality agent |
