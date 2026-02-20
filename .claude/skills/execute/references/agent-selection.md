# Agent & Tool Selection Matrix

Complete reference for choosing the right tool, agent, skill, or MCP server for each task type.

## Decision Flow

```
Is the task a simple, directed action?
├── YES: Find file? → Glob
│        Search content? → Grep
│        Read file? → Read
│        Edit file? → Edit (read first)
│        Create file? → Write
│        Run command? → Bash
│        Git operation? → Bash (git ...)
│        GitHub operation? → Bash (gh ...) or GitHub MCP
└── NO: Does it require multi-file exploration or research?
    ├── YES: Broad codebase search? → Explore agent (subagent_type: Explore)
    │        Web research? → WebSearch + WebFetch
    │        Library docs? → library-docs skill (context7 MCP)
    │        Complex reasoning? → deep-analysis skill (sequential-thinking MCP)
    └── NO: Does it require specialized code generation or review?
        ├── Backend/API code → api-backend agent
        ├── Frontend/UI code → frontend-specialist agent
        ├── Database schema/queries → database-architect agent
        ├── Test writing → test-automation agent
        ├── Code review → code-quality agent
        ├── Performance work → performance-optimizer agent
        ├── Architecture design → architecture-planner agent
        ├── Security audit → security-scan command
        ├── DevOps/CI/CD → devops-automation agent
        └── Production incident → incident-commander agent
```

## Agents — When to Use Each

### Explore (subagent_type: Explore)
**Use for:** Broad codebase searches, finding patterns across many files, understanding architecture
**Model:** Default (fast)
**When NOT to use:** Simple file lookups (use Glob/Grep directly)

### architecture-planner (subagent_type: architecture-planner)
**Use for:** System design, API contracts, architectural decisions, migration strategies
**Model:** Sonnet
**Pair with:** deep-analysis skill for complex trade-off evaluation

### api-backend (subagent_type: api-backend)
**Use for:** REST/GraphQL endpoints, middleware, controllers, business logic, data validation
**Model:** Sonnet
**When NOT to use:** Simple file edits (use Edit directly)

### frontend-specialist (subagent_type: frontend-specialist)
**Use for:** React/Vue/Angular components, CSS, responsive design, accessibility, state management
**Model:** Sonnet

### test-automation (subagent_type: test-automation)
**Use for:** Unit tests, integration tests, E2E tests, test coverage analysis
**Model:** Sonnet
**When:** After implementation tasks complete — tests depend on code being written

### code-quality (subagent_type: code-quality)
**Use for:** Code review, refactoring suggestions, code smell detection, best practices
**Model:** Sonnet
**When:** After implementation — as a verification step in Phase 5

### database-architect (subagent_type: database-architect)
**Use for:** Schema design, migrations, query optimization, indexing, data modeling
**Model:** Sonnet

### performance-optimizer (subagent_type: performance-optimizer)
**Use for:** Profiling, bottleneck analysis, optimization, benchmarking
**Model:** Sonnet
**Pair with:** deep-analysis skill for root cause analysis

### devops-automation (subagent_type: devops-automation)
**Use for:** Docker, Kubernetes, CI/CD pipelines, infrastructure, deployment
**Model:** Sonnet

### incident-commander (subagent_type: incident-commander)
**Use for:** Production emergencies ONLY — outages, crashes, data loss
**Model:** Opus
**Priority:** Immediate — skip normal batch planning

### general-purpose (subagent_type: general-purpose)
**Use for:** Tasks that don't fit any specialist, multi-step research, complex queries
**Model:** Default

## Skills — When to Invoke

| Skill | Trigger | Invocation |
|-------|---------|------------|
| bedrock-integration | Any AWS Bedrock API work | Consult reference — don't invoke, read SKILL.md |
| deep-analysis | Complex reasoning, architecture decisions, debugging | sequential-thinking MCP |
| library-docs | Need current docs for any library/framework | context7 MCP |
| security-scan | Security audit of code | `/security-scan` |
| code-review-checklist | Structured code review | Consult reference |
| git-workflow | Git operations guidance | Consult reference |

## MCP Servers — Direct Tool Access

### sequential-thinking (deep-analysis)
**Tool:** `mcp__sequential-thinking__sequentialthinking`
**Use for:** Multi-step reasoning, hypothesis testing, architecture decisions
**Budget:** Up to 31,999 thinking tokens

### context7 (library-docs)
**Tools:** `mcp__context7__resolve-library-id` → `mcp__context7__query-docs`
**Use for:** Fetching current documentation for any library
**Flow:** resolve library ID first, then query docs

### playwright (browser testing)
**Tools:** `mcp__playwright__playwright_navigate`, `_screenshot`, `_click`, `_fill`, etc.
**Use for:** Browser automation, E2E testing, visual verification

### GitHub MCP
**Tools:** `mcp__github__create_pull_request`, `_get_issue`, `_search_code`, etc.
**Use for:** GitHub operations (alternative to gh CLI)

## Parallelization Rules

### Safe to Parallelize
- Multiple Read/Grep/Glob calls (read-only)
- Multiple independent Explore agents
- Multiple WebSearch/WebFetch calls
- Agent tasks touching different files
- Independent research tasks

### Must Be Sequential
- Read → Edit on the same file (read first, then edit)
- Code implementation → Test writing (tests depend on code)
- Schema migration → Code that uses new schema
- Build → Deploy
- Any task with explicit `blockedBy` dependencies

### Batch Construction Algorithm
1. Assign depth = 0 to all tasks with no dependencies
2. For tasks with dependencies: depth = max(dependency depths) + 1
3. Group by depth → each group is a batch
4. Within a batch: all tasks launch in parallel (single message, multiple tool calls)
5. Between batches: wait for all tasks in batch N before starting batch N+1

## Model Selection for Agents

| Complexity | Model | Use When |
|------------|-------|----------|
| Quick lookup, simple search | haiku | Fast, low-cost exploration |
| Standard implementation | sonnet | Most coding and analysis tasks |
| Critical reasoning, complex architecture | opus | High-stakes decisions, incident response |

Default to **sonnet** unless the task is trivially simple (haiku) or critically complex (opus).
