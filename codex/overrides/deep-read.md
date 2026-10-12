# Source-first deep reading

Define the target and exact SHA. Treat AGENTS.md and documentation as context,
then use source and executable evidence for conclusions.

1. SCOPE: identify the relevant entry points and fewer than 50 source files. If
   broader, narrow by verified dependency centrality and Git recency, reporting coverage.
2. MAP: inspect actual configs, entry points, dependencies and behavioral constants.
3. TRACE: follow primary and error paths to terminal I/O. Read implementations,
   not only signatures; verify indexed/LSP references against live source.
4. DEEP READ: read critical files fully. Document formulas, conditions, state
   changes and edge cases with file/line citations.
5. CONNECT: synthesize data flows, patterns, assumptions and risks. Use the connected
   Sequential Thinking MCP when helpful; if unavailable, disclose it and summarize
   evidence checks without claiming a tool call. Do not impose a fabricated tool name.
6. REPORT: answer the target with source citations and explicit coverage limits.

Use `rg` and shell/file tools; LSP/code graphs are optional accelerators. Delegate
only if authorized and supported; skills do not automatically fork a Codex session.
See `references/reading-strategies.md` for conditional reading strategies.
