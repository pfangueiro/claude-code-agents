---
name: deep-analysis
description: Structured multi-step reasoning for complex problems using MCP. Use this skill when facing architectural decisions, performance bottlenecks, complex debugging, system design challenges, or any problem requiring deep, systematic analysis. Leverages the sequential-thinking MCP server for rigorous step-by-step reasoning with up to 31,999 thinking tokens. Complements architecture-planner and performance-optimizer agents.
---

# Deep Analysis

## Overview

This **MCP-powered skill** enables structured, multi-step reasoning for complex problems through the sequential-thinking MCP server. Unlike standard responses, deep analysis breaks down problems into discrete reasoning steps, allowing for course correction, hypothesis generation, and verification before reaching conclusions.

## When to Use This Skill

- **Architectural Decisions**: Evaluating system design trade-offs
- **Performance Bottlenecks**: Diagnosing complex performance issues
- **Complex Debugging**: Multi-layered bugs with unclear root causes
- **Design Patterns**: Choosing the right pattern for specific contexts
- **Scalability Analysis**: Planning for growth and load
- **Migration Strategies**: Large-scale refactoring or technology changes
- **Security Analysis**: Threat modeling and vulnerability assessment
- **Algorithm Selection**: Finding optimal approaches for problems

## MCP Integration

This skill leverages the **sequential-thinking MCP server** which provides structured reasoning capabilities.

### How It Works

1. **Problem Decomposition**: Break complex problem into steps
2. **Sequential Reasoning**: Think through each step systematically
3. **Hypothesis Testing**: Generate and verify hypotheses
4. **Course Correction**: Revise thinking based on new insights
5. **Solution Synthesis**: Build complete answer from reasoning chain

### Available Tool

The sequential-thinking MCP server provides:

**`mcp__sequential-thinking-server__sequentialthinking`**
- Supports up to 31,999 thinking tokens (vs 4,000 standard)
- Enables multi-step reasoning with revision capability
- Generates hypothesis → verifies → adjusts → concludes
- Can branch and explore multiple solution paths

### Key Parameters

```javascript
{
  thought: "Current reasoning step",
  thoughtNumber: 5,              // Current step number
  totalThoughts: 20,             // Estimated total steps
  nextThoughtNeeded: true,       // Continue reasoning?
  isRevision: false,             // Revising previous thought?
  revisesThought: null,          // Which thought to revise
  branchFromThought: null,       // Branching point
  branchId: null,                // Branch identifier
  needsMoreThoughts: false       // Need more steps than estimated?
}
```

## Common Usage Patterns

### Pattern 1: Architecture Decision

**User Request:**
```
"Should we use microservices or monolith for our e-commerce platform?"
```

**Deep Analysis Workflow:**
1. **Thought 1**: Understand current requirements (traffic, team size, complexity)
2. **Thought 2**: Analyze microservices benefits (scalability, independence, tech diversity)
3. **Thought 3**: Analyze microservices costs (complexity, ops overhead, latency)
4. **Thought 4**: Analyze monolith benefits (simplicity, dev speed, consistency)
5. **Thought 5**: Analyze monolith costs (coupling, scaling limits, deployment risks)
6. **Thought 6**: Map requirements to architecture strengths
7. **Thought 7**: Consider team capabilities and timeline
8. **Thought 8**: Evaluate long-term vs short-term trade-offs
9. **Thought 9**: Generate recommendation with rationale
10. **Thought 10**: Verify recommendation against requirements

**Example MCP Call:**
```javascript
mcp__sequential-thinking-server__sequentialthinking({
  thought: "Let me start by understanding the key requirements. The platform needs to handle varying traffic loads, support a team of 8 developers, and launch in 6 months...",
  thoughtNumber: 1,
  totalThoughts: 10,
  nextThoughtNeeded: true
})
```

### Pattern 2: Performance Bottleneck Investigation

**User Request:**
```
"Our API response time went from 200ms to 2s after the last deployment"
```

**Deep Analysis Workflow:**
1. **Thought 1**: What changed in the deployment? (code, config, infrastructure)
2. **Thought 2**: Hypothesis: Database query regression
3. **Thought 3**: Evidence check: Query logs, slow query analyzer
4. **Thought 4**: Revision: Not just DB - also seeing high CPU
5. **Thought 5**: New hypothesis: Inefficient algorithm or data structure
6. **Thought 6**: Code diff analysis of performance-critical paths
7. **Thought 7**: Found O(n²) operation introduced in new feature
8. **Thought 8**: Verify: Does traffic volume correlate with slowdown?
9. **Thought 9**: Confirmed. Generate solution: Optimize to O(n log n)
10. **Thought 10**: Validate solution with complexity analysis

**Example MCP Call with Revision:**
```javascript
// Initial hypothesis
mcp__sequential-thinking-server__sequentialthinking({
  thought: "Hypothesis: The performance issue is caused by a database query regression introduced in the deployment...",
  thoughtNumber: 2,
  totalThoughts: 10,
  nextThoughtNeeded: true
})

// Revising after new evidence
mcp__sequential-thinking-server__sequentialthinking({
  thought: "Wait, the database logs don't show significant slow queries. But I'm seeing high CPU usage. Let me revise my hypothesis...",
  thoughtNumber: 4,
  totalThoughts: 12,  // Adjusted estimate
  nextThoughtNeeded: true,
  isRevision: true,
  revisesThought: 2
})
```

### Pattern 3: System Design Challenge

**User Request:**
```
"Design a real-time collaboration system for 100k concurrent users"
```

**Deep Analysis Workflow:**
1. **Thought 1**: Functional requirements (editing, cursor positions, presence)
2. **Thought 2**: Non-functional requirements (latency <100ms, consistency, availability)
3. **Thought 3**: Scalability math (100k users, message rates, data volumes)
4. **Thought 4**: Technology options (WebSockets, Server-Sent Events, polling)
5. **Thought 5**: State management (CRDT, OT, event sourcing)
6. **Thought 6**: Infrastructure needs (load balancers, message brokers, databases)
7. **Thought 7**: Branching: Explore CRDT approach
8. **Thought 8**: Branching: Explore OT approach
9. **Thought 9**: Compare approaches against requirements
10. **Thought 10**: Select optimal approach with justification
11. **Thought 11**: Design complete system architecture
12. **Thought 12**: Identify potential failure points and mitigations

**Example MCP Call with Branching:**
```javascript
// Branch to explore CRDT
mcp__sequential-thinking-server__sequentialthinking({
  thought: "Let me explore the CRDT approach. CRDTs provide eventual consistency without coordination...",
  thoughtNumber: 7,
  totalThoughts: 15,
  nextThoughtNeeded: true,
  branchFromThought: 6,
  branchId: "crdt-exploration"
})
```

### Pattern 4: Complex Debugging

**User Request:**
```
"Users randomly get logged out, but I can't reproduce it"
```

**Deep Analysis Workflow:**
1. **Thought 1**: Gather evidence (logs, error rates, affected users)
2. **Thought 2**: Pattern analysis (time of day, user types, browsers)
3. **Thought 3**: Hypothesis 1: Session timeout misconfiguration
4. **Thought 4**: Test hypothesis 1: Check session settings
5. **Thought 5**: Hypothesis 2: Race condition in session refresh
6. **Thought 6**: Analyze session refresh code for race conditions
7. **Thought 7**: Found: Async refresh without proper locking
8. **Thought 8**: Verify: Does this explain the randomness?
9. **Thought 9**: Solution design: Implement mutex for refresh
10. **Thought 10**: Validation: Will this solve without new issues?

## Integration with Agents

### architecture-planner Agent

**Synergy**: deep-analysis provides structured reasoning, architecture-planner provides implementation.

**Workflow Example:**
```
User: "Design a payment processing system"

1. deep-analysis skill → Systematic design decision analysis
2. architecture-planner agent → Create detailed architecture
3. Result: Well-reasoned, documented architecture
```

### performance-optimizer Agent

**Synergy**: deep-analysis diagnoses root causes, performance-optimizer implements fixes.

**Workflow Example:**
```
User: "System is slow under load"

1. deep-analysis skill → Multi-step bottleneck investigation
2. performance-optimizer agent → Implement optimizations
3. Result: Targeted fixes based on deep understanding
```

### security-auditor Agent

**Synergy**: deep-analysis for threat modeling, security-auditor for implementation.

**Workflow Example:**
```
User: "Evaluate security of authentication flow"

1. deep-analysis skill → Systematic threat model analysis
2. security-auditor agent → Security scan and fixes
3. Result: Comprehensive security improvements
```

## Best Practices

### DO:
- ✅ Use for genuinely complex problems (not simple queries)
- ✅ Let reasoning adjust estimates mid-stream
- ✅ Embrace revision when new evidence emerges
- ✅ Branch to explore multiple solution paths
- ✅ Verify hypotheses before concluding
- ✅ Document reasoning chain for future reference

### DON'T:
- ❌ Use for simple lookups (use regular responses)
- ❌ Force completion without adequate thinking
- ❌ Ignore contradictory evidence
- ❌ Skip hypothesis verification
- ❌ Rush to conclusions

## Reasoning Patterns

### Pattern: Hypothesis Generation & Verification

```
1. State problem clearly
2. Generate multiple hypotheses
3. For each hypothesis:
   - Identify evidence needed
   - Gather evidence
   - Test hypothesis
4. Compare hypotheses
5. Select most supported
6. Verify solution
```

### Pattern: Design Space Exploration

```
1. Define requirements and constraints
2. Identify decision points
3. For each decision:
   - List options
   - Analyze trade-offs
   - Consider long-term implications
4. Build solution incrementally
5. Verify against requirements
```

### Pattern: Root Cause Analysis

```
1. Observe symptom
2. Gather data
3. Form initial hypothesis
4. Test hypothesis
5. If disproved:
   - Revise understanding
   - Form new hypothesis
   - Repeat
6. If confirmed:
   - Verify completeness
   - Design solution
```

## Example Workflows

### Workflow 1: Technology Selection

```
Problem: "Should we use PostgreSQL or MongoDB for our social network?"

Deep Analysis Steps:
1. Define data model requirements
2. Analyze access patterns
3. Evaluate PostgreSQL strengths (ACID, relations, consistency)
4. Evaluate MongoDB strengths (flexibility, horizontal scaling)
5. Map requirements to database capabilities
6. Consider team expertise
7. Analyze long-term maintenance
8. Generate recommendation
9. Verify against requirements
10. Document decision rationale

Output: Reasoned decision with clear justification
```

### Workflow 2: Scalability Planning

```
Problem: "How do we scale from 1k to 1M users?"

Deep Analysis Steps:
1. Current architecture analysis
2. Bottleneck identification
3. Traffic pattern projection
4. Vertical vs horizontal scaling analysis
5. Database scaling strategy
6. Caching strategy
7. CDN requirements
8. Cost projection
9. Phased rollout plan
10. Risk assessment
11. Mitigation strategies
12. Final scaling blueprint

Output: Comprehensive scaling plan with milestones
```

### Workflow 3: Migration Strategy

```
Problem: "Migrate monolith to microservices without downtime"

Deep Analysis Steps:
1. Current system dependency map
2. Service boundary identification
3. Migration order determination
4. Data consistency strategy
5. Rollback plan for each phase
6. Testing strategy
7. Monitoring and observability
8. Team coordination plan
9. Timeline and milestones
10. Risk analysis
11. Stakeholder communication plan
12. Success criteria definition

Output: Detailed migration plan with risk mitigation
```

## MCP Server Setup

### Prerequisites

The sequential-thinking MCP server should be configured in Claude Code settings.

**Typical Configuration:**
```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

### Verification

To verify the MCP server is available, Claude Code should show sequential-thinking in the MCP servers list.

## When to Use vs Regular Analysis

| Use Deep Analysis When | Use Regular Response When |
|------------------------|---------------------------|
| Multiple solution paths to explore | Single clear answer exists |
| Trade-offs need careful evaluation | Straightforward implementation |
| Problem has many interconnected parts | Problem is isolated and simple |
| Risk of missing critical factors | Low-stakes decision |
| Need to document reasoning | Just need the answer |
| Complex architecture decisions | Configuration changes |
| Performance diagnosis unclear | Known performance pattern |

## Limitations & Considerations

**Thinking Budget:**
- Up to 31,999 tokens for reasoning
- Significantly more than standard 4,000
- Balance depth vs time to response

**Best For:**
- Architecture and design decisions
- Complex debugging and diagnosis
- System scalability planning
- Technology selection with trade-offs

**Not Ideal For:**
- Simple factual lookups
- Straightforward implementations
- Well-established patterns
- Time-sensitive quick answers

## Quick Reference

**Start Deep Analysis:**
```javascript
mcp__sequential-thinking-server__sequentialthinking({
  thought: "Initial reasoning step",
  thoughtNumber: 1,
  totalThoughts: 10,  // Estimate
  nextThoughtNeeded: true
})
```

**Revise Previous Thought:**
```javascript
mcp__sequential-thinking-server__sequentialthinking({
  thought: "Revised understanding based on new evidence",
  thoughtNumber: 5,
  totalThoughts: 12,
  nextThoughtNeeded: true,
  isRevision: true,
  revisesThought: 3  // Revising thought #3
})
```

**Branch to Explore Alternative:**
```javascript
mcp__sequential-thinking-server__sequentialthinking({
  thought: "Let me explore an alternative approach",
  thoughtNumber: 7,
  totalThoughts: 15,
  nextThoughtNeeded: true,
  branchFromThought: 5,
  branchId: "alternative-approach"
})
```

## Resources

### Related Skills
- git-workflow: For version control decisions
- deployment-runbook: For deployment strategy analysis
- code-review-checklist: For code quality evaluation

### Related Agents
- architecture-planner: Implements designed architecture
- performance-optimizer: Executes performance improvements
- security-auditor: Implements security recommendations

---

**This is an MCP-powered skill** - It demonstrates how Skills can leverage MCP servers for enhanced reasoning capabilities. The sequential-thinking MCP server provides the deep reasoning engine, while this skill provides the methodology for applying it to software engineering problems.
