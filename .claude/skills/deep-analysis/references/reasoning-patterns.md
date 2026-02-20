# Reasoning Patterns — Reference

Reusable thinking templates for the sequential-thinking MCP server.

---

## 1. Hypothesis Generation & Verification

For problems where the cause or best approach is unknown.

### Template

```
Step 1: State the problem and observable facts
Step 2: Generate hypothesis A — what evidence would confirm it?
Step 3: Generate hypothesis B — what evidence would confirm it?
Step 4: Gather evidence for hypothesis A (code, logs, docs, tests)
Step 5: Gather evidence for hypothesis B
Step 6: Compare — which hypothesis has stronger support?
Step 7: If inconclusive, generate hypothesis C or refine A/B
Step 8: Verify selected hypothesis against all known facts
Step 9: Conclusion with confidence level and remaining risks
```

### MCP Example

```javascript
// Step 2: Generate first hypothesis
mcp__sequential-thinking__sequentialthinking({
  thought: "HYPOTHESIS A: The slowdown is caused by N+1 queries in the document list endpoint. Evidence needed: query count per request, response time correlation with list size.",
  thoughtNumber: 2,
  totalThoughts: 9,
  nextThoughtNeeded: true
})

// Step 3: Competing hypothesis
mcp__sequential-thinking__sequentialthinking({
  thought: "HYPOTHESIS B: The slowdown is caused by unindexed full-text search on the documents table. Evidence needed: EXPLAIN ANALYZE on the search query, index list.",
  thoughtNumber: 3,
  totalThoughts: 9,
  nextThoughtNeeded: true
})
```

### When to Use
- Performance diagnosis
- Bug root cause analysis
- Intermittent failures
- Any problem with multiple possible explanations

---

## 2. Design Space Exploration

For architectural decisions with multiple valid approaches.

### Template

```
Step 1: Define requirements (functional + non-functional)
Step 2: Define constraints (budget, timeline, team skills, existing stack)
Step 3: Identify option A — strengths, weaknesses, fit to requirements
Step 4: Identify option B — strengths, weaknesses, fit to requirements
Step 5: [Branch] Deep-dive option A implications (cost, complexity, maintenance)
Step 6: [Branch] Deep-dive option B implications
Step 7: Compare options on each requirement dimension
Step 8: Risk assessment for top candidate
Step 9: Recommendation with justification and migration path
```

### MCP Example

```javascript
// Step 5: Branch to explore option A deeply
mcp__sequential-thinking__sequentialthinking({
  thought: "BRANCH A: If we use WebSockets for real-time updates: connection management at scale (100k concurrent), load balancer sticky sessions needed, reconnection logic, memory per connection...",
  thoughtNumber: 5,
  totalThoughts: 9,
  nextThoughtNeeded: true,
  branchFromThought: 4,
  branchId: "websockets-deep-dive"
})

// Step 6: Branch to explore option B
mcp__sequential-thinking__sequentialthinking({
  thought: "BRANCH B: If we use Server-Sent Events: simpler protocol, HTTP/2 multiplexing, no bidirectional needed for our use case, but limited browser connections per domain...",
  thoughtNumber: 6,
  totalThoughts: 9,
  nextThoughtNeeded: true,
  branchFromThought: 4,
  branchId: "sse-deep-dive"
})
```

### When to Use
- Technology selection (database, framework, protocol)
- Architecture decisions (monolith vs microservices, sync vs async)
- API design (REST vs GraphQL, polling vs push)
- Infrastructure choices (managed vs self-hosted)

---

## 3. Root Cause Drill-Down

For tracing from symptom to systemic cause. Pairs with `/investigate` for full protocol.

### Template

```
Step 1: OBSERVE — Document the symptom with all known facts
Step 2: TRACE — Follow the execution path from symptom backward
Step 3: WHY 1 — What is the immediate cause? (evidence: ...)
Step 4: WHY 2 — Why does that happen? (evidence: ...)
Step 5: WHY 3 — Why does THAT happen? (evidence: ...)
Step 6: [Revise if evidence contradicts] — Adjust causal chain
Step 7: ROOT CAUSE — The deepest actionable issue
Step 8: VERIFY — Does fixing this prevent recurrence?
```

### MCP Example

```javascript
// Why 1
mcp__sequential-thinking__sequentialthinking({
  thought: "WHY 1: The crash occurs because DocumentDetailView accesses vendorName on a deleted NSManagedObject. Evidence: crash log shows isFault=true at DocumentDetailView.swift:47.",
  thoughtNumber: 3,
  totalThoughts: 8,
  nextThoughtNeeded: true
})

// Revision after finding contradictory evidence
mcp__sequential-thinking__sequentialthinking({
  thought: "REVISION: I assumed the delete was triggered by user action, but git blame shows the sync engine also calls context.delete() on merge conflicts. This explains why it's intermittent — it only happens during background sync.",
  thoughtNumber: 6,
  totalThoughts: 10,
  nextThoughtNeeded: true,
  isRevision: true,
  revisesThought: 4
})
```

### When to Use
- Crashes and exceptions
- Data corruption or loss
- Intermittent failures
- Use `/investigate` for the full 8-phase protocol; use this pattern standalone for quick analysis

---

## 4. Trade-Off Matrix

For decisions where no option is clearly superior.

### Template

```
Step 1: List all options
Step 2: Define evaluation dimensions (performance, cost, complexity, maintainability, time-to-implement)
Step 3: Score each option on each dimension (with evidence, not gut feel)
Step 4: Weight dimensions by project priorities
Step 5: Identify deal-breakers (any dimension where an option fails completely)
Step 6: Calculate weighted scores
Step 7: Sensitivity analysis — does changing weights change the winner?
Step 8: Recommendation with confidence level
```

### When to Use
- Vendor/library selection
- Build vs buy decisions
- Feature prioritization
- Migration strategy selection

---

## 5. Thought Labeling Convention

Prefix each thought with a label for clarity in the reasoning chain:

| Prefix | Meaning |
|--------|---------|
| `PROBLEM:` | Initial problem statement |
| `OBSERVE:` | Gathering facts without interpretation |
| `HYPOTHESIS:` | Proposing an explanation or approach |
| `EVIDENCE:` | Evaluating evidence for/against a hypothesis |
| `BRANCH:` | Exploring an alternative path |
| `REVISION:` | Correcting an earlier thought |
| `COMPARE:` | Evaluating options side by side |
| `RISK:` | Identifying potential failure modes |
| `CONCLUSION:` | Final recommendation with justification |
| `VERIFY:` | Checking conclusion against constraints |
