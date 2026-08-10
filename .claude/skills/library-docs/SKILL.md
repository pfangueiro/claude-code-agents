---
name: library-docs
description: Quick access to up-to-date library documentation using MCP. Use this skill when you need to reference official documentation for libraries, frameworks, or APIs. Leverages the context7 MCP server to fetch current docs for React, Next.js, Vue, MongoDB, Supabase, and hundreds of other libraries. Complements the documentation-maintainer agent.
---

# Library Docs

## Overview

This **MCP-powered skill** provides instant access to up-to-date library documentation through the context7 MCP server. Instead of searching documentation manually or relying on potentially outdated information, this skill fetches current, authoritative documentation directly from library maintainers.

## When to Use This Skill

- Looking up API references for libraries
- Understanding how specific features work
- Finding code examples from official docs
- Verifying correct usage patterns
- Checking latest syntax and best practices
- Comparing different library approaches
- Complementing the **documentation-maintainer agent**

## MCP Integration

This skill leverages the **context7 MCP server** which provides access to documentation for hundreds of popular libraries.

### How It Works

1. **MCP Server Connection**: Claude Code connects to context7 MCP server
2. **Library Resolution**: Convert library name to Context7-compatible ID
3. **Documentation Fetch**: Retrieve up-to-date documentation
4. **Context Integration**: Load relevant docs into conversation

### Available Tools

The context7 MCP server provides two tools:

**`mcp__context7__resolve-library-id`**
- Resolves a library name to a Context7-compatible ID. Params (both required): `libraryName` (e.g. "Next.js") and `query` (what you're after — used to rank matches).
- Example: `{ libraryName: "React", query: "hooks" }` → ranked candidates, top match `/reactjs/react.dev`
- Returns candidates with reputation/snippet/benchmark scores; pick the best. Skip only if the user already gave a `/org/project` ID.

**Library IDs drift — resolve is the source of truth, not this file.** Context7 re-homes libraries, and the old ID is left as a stub that returns exactly one line and **zero documentation**:

```
Library /facebook/react has been redirected to this library: /react/react.
```

If you see that, you did not get docs. Re-run `resolve-library-id` and query the ID it gives you. Treat every hardcoded ID below as a hint, not a guarantee.

**`mcp__context7__query-docs`**
- Fetches documentation for a resolved library. Params (both required): `libraryId` (the `/org/project` ID) and `query` (one specific concept, e.g. "useEffect cleanup").
- Keep each `query` to a single concept; make separate calls for separate concepts. Limit: ≤3 calls per question.

**Fallback (if context7 is unavailable, errors, or is rate-limited):** context7's free tier is ~1,000 requests/month (each lookup ≈ resolve + query ≈ 2 calls; +20 bonus calls/day once capped) — ample for on-demand use, not unlimited. On failure or cap, fall back in order: (1) `WebFetch` the library's official docs site (or its `llms.txt`), (2) `WebSearch` for current docs, (3) training knowledge (flag that it may trail the library's latest release). Never block on context7.

## Common Usage Patterns

### Pattern 1: Basic Library Lookup

**User Request:**
```
"Show me React hooks documentation"
```

**Workflow:**
1. Resolve "react" to library ID using MCP
2. Fetch React documentation focused on "hooks"
3. Present relevant hooks documentation

**Example MCP Calls:**
```javascript
// Step 1: Resolve library ID
mcp__context7__resolve-library-id({ libraryName: "React", query: "hooks" })
// Returns ranked candidates; top match: "/reactjs/react.dev"

// Step 2: Get docs
mcp__context7__query-docs({
  libraryId: "/reactjs/react.dev",
  query: "hooks"
})
```

### Pattern 2: Specific Version

**User Request:**
```
"How does routing work in Next.js 14?"
```

**Workflow:**
1. Resolve "Next.js" — resolve never returns a version-pinned ID, but it does list the available versions
2. Append one of those version tags **verbatim** to the bare ID
3. Explain routing with v14-specific features

**Example MCP Calls:**
```javascript
// Step 1: Resolve. Returns the BARE id plus the versions that actually exist.
mcp__context7__resolve-library-id({ libraryName: "Next.js", query: "routing" })
// Returns: "/vercel/next.js"
//   Versions: v14.3.0-canary.87, v13.5.11, v15.1.8, v12.3.7, v16.2.9, ...

// Step 2: Pin by appending a tag copied verbatim from that Versions list.
mcp__context7__query-docs({
  libraryId: "/vercel/next.js/v14.3.0-canary.87",
  query: "routing"
})
```

**Do not invent a version.** Semver wildcards are rejected — `/vercel/next.js/v14.x.x` fails with:

```
Version "v14.x.x" not found for library "/vercel/next.js". Available versions: ...
```

Only tags from the live `Versions:` line work, and that list rotates as releases land. If you need a version you cannot find there, query the unpinned ID and say which version the docs reflect.

### Pattern 3: API Comparison

**User Request:**
```
"Compare MongoDB and Supabase query syntax"
```

**Workflow:**
1. Resolve both library IDs
2. Fetch query documentation for each
3. Present side-by-side comparison

**Example MCP Calls:**
```javascript
// Step 1: Resolve both library IDs
mcp__context7__resolve-library-id({ libraryName: "MongoDB", query: "query syntax" })
// Returns: "/mongodb/docs"
mcp__context7__resolve-library-id({ libraryName: "Supabase", query: "query syntax" })
// Returns: "/supabase/supabase"

// Step 2: Fetch MongoDB docs
mcp__context7__query-docs({
  libraryId: "/mongodb/docs",
  query: "queries"
})

// Step 3: Fetch Supabase docs
mcp__context7__query-docs({
  libraryId: "/supabase/supabase",
  query: "queries"
})
```

### Pattern 4: Focused Topic Research

**User Request:**
```
"I need comprehensive information on React Server Components"
```

**Workflow:**
1. Resolve React library ID
2. Fetch docs with a narrowly scoped `query` for depth
3. Focus specifically on Server Components topic

**Example MCP Calls:**
```javascript
// Step 1: Resolve library ID
mcp__context7__resolve-library-id({ libraryName: "React", query: "server components" })
// Returns ranked candidates; top match: "/reactjs/react.dev"

// Step 2: Get docs — one concept per call; split follow-ups into separate calls
mcp__context7__query-docs({
  libraryId: "/reactjs/react.dev",
  query: "server components"
})
```

## Supported Libraries

The context7 MCP server supports hundreds of libraries. Every ID below was verified to return real
documentation on 2026-08-10 — but IDs drift, so resolve first and trust the resolver over this list.

**Frontend Frameworks:**
- React (`/reactjs/react.dev`)
- Vue (`/vuejs/core`)
- Angular (`/angular/angular`)
- Svelte (`/sveltejs/svelte`)
- Next.js (`/vercel/next.js`)
- Nuxt (`/nuxt/nuxt`)

**Backend & Databases:**
- MongoDB (`/mongodb/docs`)
- PostgreSQL
- Supabase (`/supabase/supabase`)
- Prisma (`/prisma/prisma`)

**Tools & Libraries:**
- Tailwind CSS (`/tailwindlabs/tailwindcss.com`)
- TypeScript (`/microsoft/TypeScript`)
- Vite (`/vitejs/vite`)

*And hundreds more...*

## Integration with Agents

### documentation-maintainer Agent

**Synergy**: This skill provides source documentation, while the documentation-maintainer agent creates project-specific docs.

**Workflow Example:**
```
User: "Document our authentication system"

1. library-docs skill → Fetch auth library documentation
2. documentation-maintainer agent → Create docs using library patterns
3. Result: Consistent documentation following library conventions
```

### api-backend Agent

**Synergy**: This skill provides API reference, while api-backend implements the code.

**Workflow Example:**
```
User: "Implement Stripe payment integration"

1. library-docs skill → Fetch Stripe API documentation
2. api-backend agent → Implement using current Stripe patterns
3. Result: Correct, up-to-date implementation
```

### frontend-specialist Agent

**Synergy**: This skill provides component documentation, while frontend-specialist builds UI.

**Workflow Example:**
```
User: "Create a data table with React"

1. library-docs skill → Fetch React table library docs
2. frontend-specialist agent → Build component following patterns
3. Result: Modern component using best practices
```

## Best Practices

### DO:
- ✅ Specify library versions when relevant
- ✅ Keep each `query` to one concept to narrow results
- ✅ Combine with agents for implementation
- ✅ Reference official docs for correctness
- ✅ Check docs when libraries update

### DON'T:
- ❌ Assume docs are current without checking
- ❌ Skip version specifications for major changes
- ❌ Ignore deprecation warnings in docs
- ❌ Mix patterns from different library versions

## Example Workflows

### Workflow 1: Learning New Library

```
User: "I'm new to Supabase, show me how to get started"

Steps:
1. Use library-docs to fetch Supabase getting started guide
2. Review authentication patterns
3. See database query examples
4. Understand real-time subscriptions

Output: Comprehensive introduction with official examples
```

### Workflow 2: Debugging API Usage

```
User: "Why isn't my Next.js API route working?"

Steps:
1. Use library-docs to fetch Next.js API routes documentation
2. Compare user's code with official patterns
3. Identify discrepancies
4. Suggest corrections based on docs

Output: Fix based on current Next.js best practices
```

### Workflow 3: Migration Guide

```
User: "Help me migrate from Vue 2 to Vue 3"

Steps:
1. Fetch Vue 2 documentation for current patterns
2. Fetch Vue 3 documentation for new patterns
3. Identify breaking changes
4. Provide migration steps with examples

Output: Detailed migration guide with official references
```

## MCP Server Setup

### Prerequisites

The context7 MCP server should be configured in Claude Code settings.

**Typical Configuration:**
```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
```

### Verification

To verify the MCP server is available, Claude Code should show context7 in the MCP servers list.

## Limitations & Considerations

**Stale IDs:**
- A redirect stub (`Library X has been redirected to ...`) is a **failed** lookup, not a result — re-resolve and query the new ID
- A version tag that is not on the live `Versions:` line errors; wildcards like `v14.x.x` never work

**Library Coverage:**
- Most popular libraries supported
- Some niche libraries may not be available
- Check context7 documentation for full list

**Update Frequency:**
- Documentation refreshed regularly
- May have slight lag for very recent releases
- Always verify critical production changes

## Quick Reference

**Fetch Library Docs:**
```javascript
// Resolve library name
mcp__context7__resolve-library-id({
  libraryName: "library-name",
  query: "what you're looking for"
})

// Get documentation
mcp__context7__query-docs({
  libraryId: "/org/project",
  query: "one specific concept"
})
```

**Common Queries:**
- "Show me {library} {feature} documentation"
- "How to use {library} for {task}"
- "What's new in {library} version {X}"
- "Compare {library A} vs {library B} for {use case}"

## Resources

### References
- Context7 documentation
- MCP server configuration guide
- Supported libraries list

### Related Skills
- documentation-maintainer: Create project docs
- code-review-checklist: Verify against library patterns

### Related Agents
- documentation-maintainer: Auto-generate documentation
- api-backend: Implement backend using library patterns
- frontend-specialist: Build UI following library conventions

---

**This is an MCP-powered skill** - It demonstrates how Skills can leverage MCP servers for enhanced capabilities. The context7 MCP server provides the data source, while this skill provides the knowledge of how to use it effectively.
