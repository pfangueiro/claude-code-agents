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
Coordinator (restricted tools: Read, Agent, SendMessage, TaskStop)
  ├── Worker A (background, restricted tools)
  ├── Worker B (background, restricted tools)
  └── Worker C (background, restricted tools)
```

**Why `Read` is in the coordinator's set:** the coordinator's whole job is the Synthesis phase,
and synthesis is a read operation — it consumes worker findings and any files those workers
wrote. A coordinator without `Read` cannot perform the step that justifies its existence.
Restrict the coordinator's *write* tools (no Edit/Write/Bash — delegate those to workers), not
its ability to read.

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

### Subagent context — read this before assuming a fork
**Omitting `subagent_type` does NOT fork the coordinator.** Verified against the shipped
`sdk-tools.d.ts`: `subagent_type?: string` is optional and selects *"the type of specialized
agent to use for this task"*; when it is omitted the **general-purpose** agent runs with a
**fresh context**. This never errors — you silently lose the context sharing you assumed.

To share context, put it in the `prompt` (an agent knows only what its prompt contains), or
continue an already-spawned agent with `SendMessage`, which resumes it *with its context
intact* — that is the real cheap-context-sharing mechanism.

```
Agent:
  description: "analyze test results"
  prompt: "<include the context the agent needs — it does NOT inherit yours>"
  subagent_type: "general-purpose"   # be explicit; omitting selects this anyway
  run_in_background: true
```

**When to fork vs fresh agent:**
- Fork: Worker needs coordinator's context (conversation history, prior findings)
- Fresh: Worker is self-contained (independent research, file editing)

### SendMessage (Inter-Agent Communication)
```
SendMessage:
  to: "agent-name"     # a single teammate by name (or "main"); no "*" wildcard — send one message per recipient
  message: "instructions or data"
  summary: "5-word preview"
```

Used for: assigning tasks, requesting status, sharing results between agents.

### Agent Teams (experimental)

Peer teammates that message each other directly. **Experimental** — enable with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`. There is NO `TeamCreate`/`TeamDelete` tool (removed in v2.1.178); a team forms implicitly when the first teammate is spawned via the Agent tool with a `team_name`. **One team per session**; the team config is torn down at session end (only the shared task list under `~/.claude/tasks/` persists). Teammates communicate via SendMessage and coordinate via TaskCreate/TaskUpdate.

## Worker Toolset Restrictions

Workers get restricted tools based on their type:

| Worker Type | Tools Available |
|-------------|----------------|
| **Explore** (research) | Read, Grep, Glob, Bash (read-only), WebSearch, WebFetch |
| **Background agent** | Read, Grep, Glob, Bash, Edit, Write, WebSearch, Skill, Worktree |
| **In-process teammate** | TaskCreate/Update/List/Get, SendMessage, CronCreate |
| **Custom agent** | Whatever the agent definition specifies in `tools:` |

**Never available to sub-agents:** AskUserQuestion, EnterPlanMode, ExitPlanMode, ScheduleWakeup, WaitForMcpServers

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
4. Collect the result:
   - The agent's final message arrives WITH the notification — that is the primary channel.
   - A file exists only if you instructed the worker to write one. If you need a durable
     artifact, say so in the prompt ("write your findings to <path>"), then Read that path.
   - Do NOT assume an output file exists by default. Reading one requires `Read` in the
     coordinator's toolset (see Coordinator Pattern above).
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

### Team-Based Long-Running Work (experimental — needs CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS)
```
1. Spawn teammates with Agent(subagent_type: ..., team_name: "auth-team")
   — the team forms on the first spawn (no TeamCreate step)
2. Teammates coordinate via:
   - TaskCreate/TaskUpdate (shared task list, persists under ~/.claude/tasks/)
   - SendMessage (one message per named teammate; no "*" broadcast)
3. One team per session; the team config is removed at session end
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
