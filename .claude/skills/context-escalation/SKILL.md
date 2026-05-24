---
name: context-escalation
description: Explicit-level policy for context management in long-horizon Claude Code sessions. Five escalating responses to context pressure — apply the cheapest intervention that still preserves the work. Auto-activates on context limit, near context limit, conversation getting long, /compact, handoff, /save-session.
---

# Context Escalation Policy

A discipline for handling context pressure deliberately rather than reactively. Inspired by DCI-Agent-Lite's escalating context-manager but adapted to Claude Code's harness, where `/compact`, `handoff`, `/save-session`, and the Agent tool already exist as separate primitives.

## The principle

Context limits are inevitable in long sessions. Default reflex — "I'll compact when I hit the wall" — loses information unnecessarily and creates a hard cliff. The DCI-Agent-Lite pattern that's worth borrowing: a sliding policy of progressively-more-aggressive interventions, applied as the context fills.

Apply the **cheapest** intervention that still preserves what matters. Escalate only when the cheaper option is no longer enough.

## Five levels

| Level | When | Action | Cost (information loss) |
|---|---|---|---|
| **L1 — Truncate** | A single tool output is large (find dump, long log, multi-file diff) but the rest of context is fine | Re-run with stricter filters: `head -50`, `grep ... | head`, `wc -l` first to size, `--limit` flags. Or summarize the output verbally before the next turn. | Near zero — the raw blob wasn't load-bearing |
| **L2 — Drop redundant reads** | You've Read the same file twice, or have multiple iterations of the same diff visible | Acknowledge: "I have what I need from X.py, the line numbers above are authoritative" — implicit hint that the older read can be forgotten | Low — the latest copy survives |
| **L3 — Fork to subagent** | A subtask (research a library, audit a single file, run a benchmark) can be self-contained | Delegate via the Agent tool. The subagent's context is separate and its tool output never lands in the main thread. You receive a short summary back. | Low — explicit boundary; sub-agent transcript stays accessible if needed |
| **L4 — `/compact`** | The conversation has many turns, but the current task is still in flight | Summarize the existing context into HANDOFF.md and compact. The session continues; some earlier verbatim turns are replaced by their summary. | Medium — verbatim detail is gone, structured summary remains |
| **L5 — `handoff` + `/save-session`** | You're approaching a real boundary (context almost full, task naturally pausing, need to come back next session) | Use the `handoff` skill to write a structured HANDOFF.md, then `/save-session` to persist. Next session resumes via `/resume-session`. | High — but only if the next session reads the handoff |

## Decision flow

```
context pressure detected
  ├── is it ONE giant tool output? → L1 (truncate / re-query)
  ├── are there duplicate reads / repeated diffs? → L2 (acknowledge canonical version)
  ├── is the next subtask self-contained? → L3 (fork to subagent)
  ├── is current task still in flight? → L4 (/compact)
  └── crossing a natural session boundary? → L5 (handoff + /save-session)
```

## What this skill does NOT do

- It does **not** trigger compaction automatically — that's the PreCompact hook's job. This skill is a **policy**, not a hook.
- It does **not** replace `/compact` or `handoff` — it tells you **when** to use which.
- It does **not** measure context usage — the statusline shows token use; use that signal as input to the policy.

## When to invoke this skill explicitly

Type `/context-escalation` (or just describe context pressure) when:
- The statusline shows >70% used and the task isn't done
- You're about to receive a tool output you suspect is huge (a `find` on a 100K-file tree)
- You're planning a multi-step task and want to pre-decide where to fork vs. compact
- A previous compact lost useful detail and you want to recalibrate

The skill prompts Claude to choose the right escalation level based on the current task shape rather than reflexively hitting the same intervention each time.

## Why this is worth a separate skill

Without an explicit policy, the harness defaults to "compact when full" (L4 hard-cliff). That loses subagent-fork (L3) and truncate (L1) as cheaper interventions. Most sessions waste budget on this default. Naming the policy explicitly is how you stop doing the wrong thing reflexively.

## Lineage

This skill borrows the **escalating-levels structure** (not the implementation) from [DCI-Agent-Lite's context manager](https://github.com/DCI-Agent/DCI-Agent-Lite). DCI's three primitives (truncation, compaction, summarization) map onto Claude Code's existing tools (truncated tool output, `/compact`, `handoff` + `/save-session`) with two additions specific to multi-agent setups (L2 redundant-read awareness, L3 subagent fork).
