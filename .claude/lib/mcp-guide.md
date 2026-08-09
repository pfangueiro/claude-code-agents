# Tool & MCP Integration Guide

## Built-in Tools (No MCP Required)

Claude Code provides these tools natively — no MCP server needed:

### Task Management
- **TaskCreate** — Create tasks with subjects, descriptions, and dependencies (`addBlockedBy`)
- **TaskUpdate** — Update status (`pending` → `in_progress` → `completed`), add dependencies
- **TaskList** — View all tasks with status and blockers
- **TaskGet** — Get full task details including description and dependencies

### Scheduling & Automation
- **CronCreate** — Schedule recurring or one-shot prompts using 5-field cron expressions. Session-scoped, 7-day max for recurring jobs. Use for polling CI, periodic checks, reminders.
- **CronDelete** — Cancel a scheduled job by ID
- **CronList** — List all active scheduled jobs
- **RemoteTrigger** — Create, list, run, update remote agent triggers for cross-session automation

### Code Intelligence
- **LSP** — Language Server Protocol operations: `goToDefinition`, `findReferences`, `hover`, `documentSymbol`, `workspaceSymbol`, `goToImplementation`, `prepareCallHierarchy`, `incomingCalls`, `outgoingCalls`. Requires LSP server configured for the file type.
- **Code graph (optional, per-repo)** — an indexed structural-query tool (e.g. CodeGraphContext / `cgc`) answers whole-repo transitive, cross-language, and aggregate queries (blast-radius, dead code, all implementers of X) that LSP's one-hop, per-language calls cannot. Opt-in; **not shipped/registered by this framework** — see the tool's own docs. `/deep-read` uses it as an accelerator when warranted; source stays the source of truth.

### Git Isolation
- **EnterWorktree** — Create an isolated git worktree for parallel development, experiments, or risky changes
- **ExitWorktree** — Leave worktree (keep or remove)

### User Interaction
- **AskUserQuestion** — Present structured questions with labeled options, descriptions, and previews. Supports multi-select and up to 4 questions per call.

---

## MCP (Model Context Protocol)

## What is MCP?

MCP is a standardized protocol that allows Claude Code to connect to external services, APIs, and tools. MCP servers run as separate processes and expose tools that Claude can invoke.

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│ Claude Code  │ ──────> │  MCP Server  │ ──────> │ External API │
│              │ <────── │              │ <────── │  or Service  │
└──────────────┘         └──────────────┘         └──────────────┘
     Uses tools          Provides tools          Data source
```

## MCP-Powered Skills

### library-docs (context7 MCP server)

Fetches up-to-date documentation for 100+ libraries (React, Next.js, Vue, MongoDB, Supabase, PostgreSQL, etc.).

```javascript
// Resolve library ID
mcp__context7__resolve-library-id({ libraryName: "react", query: "hooks" })
// Returns: "/facebook/react"

// Fetch documentation
mcp__context7__query-docs({
  libraryId: "/facebook/react",
  query: "hooks"
})
```

Free tier: ~1,000 requests/month (each lookup ≈ resolve-library-id + query-docs ≈ 2 calls; +20 bonus calls/day once capped) — ample for on-demand use. If context7 is unavailable or rate-limited, fall back to WebFetch of the official docs, then WebSearch.

### deep-analysis (sequential-thinking MCP server)

Structured multi-step reasoning with up to 31,999 thinking tokens, branching, and revision.

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "Let me analyze the architectural trade-offs...",
  thoughtNumber: 1,
  totalThoughts: 10,
  nextThoughtNeeded: true
})
```

## MCP + Agent Integration

- **architecture-planner** + deep-analysis skill → Structured architectural decisions
- **documentation-maintainer** + library-docs skill → Documentation using library patterns
- **performance-optimizer** + deep-analysis skill → Root cause analysis

## Configuring MCP Servers

Add MCP servers to your Claude Code settings (`.mcp.json` or settings):

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

## When to Use MCP

- External data or API integrations
- Sandboxed tool execution
- Reusable capabilities across skills and agents
- Up-to-date information from external sources

## Resources

- [EXTENSIBILITY.md](../EXTENSIBILITY.md) — Complete extensibility guide
- [MCP Documentation](https://modelcontextprotocol.io) — Official protocol docs
