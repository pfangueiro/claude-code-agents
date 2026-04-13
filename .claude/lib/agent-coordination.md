# Agent Coordination Protocol

Formal protocol for multi-agent collaboration in the Claude Agents system.

## Sequential Handoff Protocol

When one agent completes work and passes to the next, use this structured output:

```
### Handoff: [source-agent] -> [target-agent]

**Context**: What was done and why
**Artifacts**: Files created/modified with paths
**Decisions**: Key choices made and rationale
**Next Steps**: What the receiving agent should do
**Constraints**: Limitations or requirements to respect
```

### Example

```
### Handoff: architecture-planner -> api-backend

**Context**: Designed REST API for user auth with JWT tokens
**Artifacts**: docs/api-spec.md, docs/adr-001-jwt.md
**Decisions**: JWT over sessions (stateless scaling), bcrypt for passwords
**Next Steps**: Implement /auth/register, /auth/login, /auth/refresh endpoints
**Constraints**: Must use httpOnly cookies for refresh tokens, 15min access token TTL
```

## Parallel Coordination

When multiple agents work concurrently, they must agree on shared contracts before starting.

### Shared Contract Format

```
### Parallel Contract: [agent-a] + [agent-b]

**Interface**: Agreed API/data format between the agents
**Boundaries**: What each agent owns (no overlap)
**Sync Points**: When agents must check in with each other
```

### Example

```
### Parallel Contract: frontend-specialist + api-backend

**Interface**: OpenAPI spec at docs/api-spec.yaml
**Boundaries**:
  - frontend-specialist: UI components, client-side validation, state management
  - api-backend: Endpoints, server-side validation, database queries
**Sync Points**: After endpoint implementation, before integration testing
```

## Review Chain

Standard review order for completed work:

1. **code-quality** - Code standards, patterns, maintainability
2. **security-auditor** - OWASP compliance, vulnerability scan
3. **test-automation** - Test coverage, edge cases

Each reviewer adds findings in this format:

```
### Review: [reviewer-agent]

**Status**: PASS | PASS_WITH_NOTES | FAIL
**Findings**:
  - [Critical] Description (must fix before merge)
  - [Suggestion] Description (recommended improvement)
  - [Nit] Description (minor style/preference)
**Blocking**: Yes/No
```

## Error Recovery

When an agent encounters a failure:

1. **Document the failure**:
   ```
   ### Failure: [agent-name]

   **What failed**: Description
   **Root cause**: If known
   **Impact**: What downstream agents are affected
   **Recovery options**: List of possible next steps
   ```

2. **Conflict resolution** - When two agents produce conflicting outputs:
   - Security concerns take precedence over convenience
   - Performance concerns take precedence over code elegance
   - Correctness takes precedence over everything except security

## Priority Rules

When multiple agents could activate, priority determines which leads:

1. **incident-commander** - Always takes priority in emergencies
2. **security-auditor** - Security concerns override feature work
3. **test-automation** - Tests must pass before deployment
4. **architecture-planner** - Design decisions before implementation
5. **All other agents** - Equal priority, coordinate as peers

## Team-Based Orchestration

For persistent multi-agent work, use Claude Code's team system:

### Creating Teams
```
TeamCreate:
  team_name: "auth-team"
  description: "implementing authentication system"
```
Teams persist in `~/.claude/teams/` and provide shared task lists.

### Inter-Agent Messaging
```
SendMessage:
  to: "worker-name"         # or "*" for broadcast to all teammates
  message: "implement the login endpoint per the spec above"
  summary: "assign login endpoint"
```

### Worker Toolset Restrictions
Workers get limited tools based on their type:
- **Explore agents** — Read-only: Read, Grep, Glob, WebSearch (safe for research)
- **Background agents** — Read + Write: can edit files but can't ask user questions
- **Teammates** — Coordination: TaskCreate/Update, SendMessage, CronCreate
- **Custom agents** — Whatever is specified in the agent definition's `tools:` field

Workers NEVER get: AskUserQuestion, EnterPlanMode, ExitPlanMode, TaskStop

### Background Agents with Notifications
Launch agents with `run_in_background: true`. They run async and send a `<task-notification>` when done:
```
Agent:
  prompt: "research the authentication library options"
  run_in_background: true
  subagent_type: "Explore"
```
Continue other work while the agent runs. Read its output when notified.

### Fork Subagents (Cheap Context Sharing)
Omit `subagent_type` to fork — inherits full context, shares prompt cache:
```
Agent:
  description: "analyze findings"
  prompt: "based on our conversation, summarize..."
  run_in_background: true
  # no subagent_type = fork (shares prompt cache, much cheaper)
```

See `multi-agent-orchestration` skill for comprehensive patterns.

## Task-Based Coordination

Use Claude Code's built-in task tools for formal multi-agent coordination:

### TaskCreate for Work Items
Each agent's work becomes a tracked task with status and dependencies:
```
TaskCreate:
  subject: "Implement auth endpoints"
  description: "api-backend: implement /auth/register, /auth/login, /auth/refresh"
```

### TaskUpdate with Dependencies
Use `addBlockedBy` to enforce execution order:
```
TaskUpdate:
  taskId: "3"
  addBlockedBy: ["1", "2"]   # Can't start until tasks 1 and 2 complete
```

### TaskList for Visibility
Any agent can check overall progress and find unblocked work:
```
TaskList  →  shows all tasks with status, blockers, and owners
```

**When to use Task tools vs. markdown handoffs:**
- **Task tools**: Orchestrated multi-agent workflows (via `/execute`), complex dependency graphs
- **Markdown handoffs**: Simple sequential handoffs between 2-3 agents

## Anti-Patterns

- **No silent handoffs**: Always document what was done before passing work
- **No overlapping ownership**: Each file/component has one owning agent
- **No skipping reviews**: Security review is mandatory for auth/data code
- **No cascading failures**: If one agent fails, others should not proceed blindly
