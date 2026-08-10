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
| **L4 — `/compact`** | Many turns and the task is still in flight, AND this is the session's first compact AND enough headroom remains that the work left plausibly fits after it | Summarize the existing context into HANDOFF.md and compact. The session continues; some earlier verbatim turns are replaced by their summary. | Medium — verbatim detail is gone, structured summary remains |
| **L5 — `handoff` + `/save-session`** | Any one of: context is nearly exhausted, so compacting would not buy enough runway to finish; you already compacted this session and pressure is back; or the task is at a natural pause and will resume next session | Use the `handoff` skill to write a structured HANDOFF.md, then `/save-session` to persist. Next session resumes via `/resume-session`. | High — but only if the next session reads the handoff |

## Decision flow

Arms are checked TOP-DOWN; the first match wins. "Task still in flight" is true in nearly every
context-pressure moment, so it cannot be an arm on its own — it would swallow every case and make L5
unreachable exactly at the boundary L5 exists for. The boundary test is therefore checked BEFORE
L4, and L4 carries the bounded condition.

```
context pressure detected
  ├── is it ONE giant tool output? → L1 (truncate / re-query)
  ├── are there duplicate reads / repeated diffs? → L2 (acknowledge canonical version)
  ├── is the next subtask self-contained? → L3 (fork to subagent)
  ├── is this a real boundary — context nearly exhausted (a compact would not
  │     leave enough runway to finish), already compacted once this session,
  │     or the task is pausing here? → L5 (handoff + /save-session)
  └── otherwise, task in flight, first compact, and the work left plausibly
        fits the post-compact budget → L4 (/compact)
```

If the L5 test and the L4 condition disagree — you want to keep going but the runway is gone —
L5 wins. Compacting into a budget too small to finish loses the verbatim detail AND still ends the
session, which is the worst of both.

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
