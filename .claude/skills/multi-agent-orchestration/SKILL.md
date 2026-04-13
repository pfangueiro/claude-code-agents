---
name: multi-agent-orchestration
description: Advanced multi-agent patterns using Claude Code's built-in orchestration. Teams, background agents, coordinator pattern, worker restrictions, SendMessage protocol, fork subagents. Auto-activates on multi-agent, orchestrate, team, coordinator, parallel agents, worker agents, background agent, agent swarm.
---

# Multi-Agent Orchestration

Advanced patterns for coordinating multiple Claude agents using Claude Code's built-in tools.

## Core Concepts

### Coordinator Pattern
One Claude (the coordinator) orchestrates multiple worker Claudes:

```
Coordinator (restricted tools: Agent, SendMessage, TaskStop)
  ├── Worker A (background, restricted tools)
  ├── Worker B (background, restricted tools)
  └── Worker C (background, restricted tools)
```

**Workflow phases:**
1. **Research** — Launch parallel workers to explore and gather information
2. **Synthesis** — Coordinator reads all findings, forms a unified understanding
3. **Implementation** — Launch workers with specific, synthesized instructions
4. **Verification** — Launch verification workers to test the implementation

**Critical rule:** The coordinator MUST synthesize findings before delegating implementation. Never pass raw research output to an implementation worker — always digest it first.

## Tools

### Agent (Spawn Workers)
```
Agent:
  description: "short description"
  prompt: "detailed task instructions"
  subagent_type: "Explore" | "Plan" | "general-purpose" | custom
  run_in_background: true    # async — get notification when done
  isolation: "worktree"      # optional — isolated git worktree
  model: "sonnet" | "opus" | "haiku"
```

**Synchronous (foreground):** Coordinator waits for result. Use for quick lookups.
**Asynchronous (background):** Coordinator gets `<task-notification>` when done. Use for parallel work.

### Fork Subagent (Cheap Context Sharing)
Omit `subagent_type` to fork the coordinator:
```
Agent:
  description: "analyze test results"
  prompt: "..."
  run_in_background: true
  # no subagent_type = fork (inherits full context, shares prompt cache)
```

**When to fork vs fresh agent:**
- Fork: Worker needs coordinator's context (conversation history, prior findings)
- Fresh: Worker is self-contained (independent research, file editing)

### SendMessage (Inter-Agent Communication)
```
SendMessage:
  to: "agent-name"     # or "*" for broadcast
  message: "instructions or data"
  summary: "5-word preview"
```

Used for: assigning tasks, requesting status, sharing results between agents.

### TeamCreate (Persistent Teams)
```
TeamCreate:
  team_name: "feature-team"
  description: "building auth system"
```

Creates persistent team with shared task list. Teammates communicate via SendMessage and coordinate via TaskCreate/TaskUpdate.

## Worker Toolset Restrictions

Workers get restricted tools based on their type:

| Worker Type | Tools Available |
|-------------|----------------|
| **Explore** (research) | Read, Grep, Glob, Bash (read-only), WebSearch, WebFetch |
| **Background agent** | Read, Grep, Glob, Bash, Edit, Write, WebSearch, Skill, Worktree |
| **In-process teammate** | TaskCreate/Update/List/Get, SendMessage, CronCreate |
| **Custom agent** | Whatever the agent definition specifies in `tools:` |

**Never available to workers:** AskUserQuestion, EnterPlanMode, ExitPlanMode, TaskStop

## Patterns

### Parallel Research → Synthesized Implementation
```
Phase 1: Launch 3 Explore agents in parallel (single message, 3 Agent calls)
  - Agent A: "Research the auth library API"
  - Agent B: "Read the existing user model and database schema"
  - Agent C: "Check the test patterns used in this codebase"

Phase 2: Coordinator reads all 3 results, synthesizes:
  "Based on findings: library uses JWT, schema has users table with
   email/password_hash, tests use vitest with factory pattern..."

Phase 3: Launch implementation agent with synthesized spec:
  Agent: "Implement auth endpoints per this spec: [detailed spec from synthesis]"

Phase 4: Launch verification agent:
  Agent: "Run tests, verify auth endpoints work. Expected: [specific assertions]"
```

### Background Agent with Notification
```
1. Agent(run_in_background: true, prompt: "implement feature X")
2. Continue other work while agent runs
3. Receive <task-notification> when agent completes
4. Read agent's output file for results
5. Launch follow-up agent if needed
```

### Worktree Isolation for Risky Work
```
Agent:
  prompt: "try experimental approach to caching"
  isolation: "worktree"
  run_in_background: true

# Agent works in isolated git worktree
# If changes are good: worktree path + branch returned
# If no changes: worktree auto-cleaned
```

### Team-Based Long-Running Work
```
1. TeamCreate(team_name: "auth-team")
2. Spawn teammates with Agent(subagent_type: ...)
3. Teammates coordinate via:
   - TaskCreate/TaskUpdate (shared task list)
   - SendMessage (direct communication)
4. Team persists in ~/.claude/teams/ across sessions
```

## Best Practices

- **Launch independent agents in a SINGLE message** — don't serialize parallel work
- **Synthesize before delegating** — never pass raw research to implementation workers
- **Use background agents for anything > 30 seconds** — keeps coordinator responsive
- **Fork when workers need your context** — shares prompt cache, much cheaper
- **Don't set model on forks** — different models break cache reuse
- **Use Explore agents for research** — they can't modify files (safe)
- **Give workers specific instructions** — vague prompts waste tokens and produce poor results
- **Check TaskList before spawning** — avoid duplicate work

## Anti-Patterns

- Serializing independent research (launch all at once)
- Passing raw research output without synthesis
- Using foreground agents for long tasks (blocks coordinator)
- Spawning too many agents (diminishing returns past 5-7 parallel)
- Workers asking user questions (they can't — no AskUserQuestion tool)

## Related

- `execute` skill — uses orchestration for structured goal decomposition
- `agent-coordination.md` — formal handoff and review chain protocols
- `scheduled-tasks` skill — CronCreate for periodic agent work
- `remote-triggers` skill — RemoteTrigger for cross-session automation
- `worktree-workflow` skill — isolation patterns for experimental work
