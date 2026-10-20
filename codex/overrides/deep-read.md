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

Qualify each reported claim: observed (directly inspected — state whether the basis is source inspection at the cited revision/`file:line` or an actual runtime capture; reading code does not prove the runtime path executed), derived (name the premises), or inferred (a hypothesis still to verify). Keep unknown, unsupported and contradictory evidence visible — a missing fact is not proof of absence, nor licence to invent one — and preserve truncated or partial coverage. Bound negatives to the searched root/query or selected-file scope and its limits; no match in a partial search, and a clean tool exit, are not repository-wide absence or complete coverage. On a truncated preview, page a supported smaller read or reuse retained source by stable path rather than promote the preview or rerun identical expensive work. For a consequential finding record, within the normal concise report, its conclusion, basis/category, citation, scope and limits, any contradiction, and the next discriminating read — scaled to the question, no numeric confidence scores, no new phase or schema.

Use `rg` and shell/file tools; LSP/code graphs are optional accelerators. Delegate
only if authorized and supported; skills do not automatically fork a Codex session.
See `references/reading-strategies.md` for conditional reading strategies.
