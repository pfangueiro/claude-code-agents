# MCP (Model Context Protocol) Integration Guide

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
mcp__context7__resolve-library-id({ libraryName: "react" })
// Returns: "/facebook/react"

// Fetch documentation
mcp__context7__get-library-docs({
  context7CompatibleLibraryID: "/facebook/react",
  topic: "hooks",
  tokens: 5000
})
```

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
