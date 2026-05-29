---
name: diverge
description: Structured divergence engine. Generates a wide, deliberately non-anchored set of approaches to a consequential, open-ended problem by spawning isolated parallel sub-agents under different cognitive frames, then a separate critic pass scores, declusters, and deepens the best. The divergent complement to /deep-analysis. Use for high-stakes architecture, strategy, design-space, and "what are our options" decisions. Auto-activates on diverge, brainstorm options, explore alternatives, what are our options, de-anchor, divergent thinking, option space, consider alternatives, multiple approaches.
context: fork
argument-hint: "<consequential, open-ended decision or problem to explore>"
---

# Diverge — Divergent Option-Generation Engine

Break premature convergence. Autoregressive reasoning commits to the first plausible answer; this skill manufactures genuine breadth before any evaluation, then converges deliberately.

**Core principle:** Separate generation from judgment. Ideas are generated in ISOLATION (no branch sees another, so none can anchor on another), and only a SEPARATE critic pass is allowed to evaluate. Evaluating while generating is the failure mode this skill exists to prevent.

## Pre-Flight Gate

Decide whether to run BEFORE doing anything else.

**Unconditional trigger — run immediately, no self-judging:**
- The user typed `/diverge` or explicitly asked to brainstorm, explore options, de-anchor, or "give me alternatives"

**Conditional trigger — self-judge on consequence × openness:**
- Run ONLY when the problem is BOTH **consequential** (hard to reverse, wide blast radius, or high cost of being wrong) AND **open-ended** (several viable, structurally different approaches plausibly exist)
- The gate is consequence × openness, NOT token cost

**ABORT — Do NOT use for (it manufactures noise on closed problems):**
- Syntax, definitions, factual lookups, arithmetic, deterministic transforms
- A bug with a single known root cause (use `/investigate`)
- A decision the user has already made (just execute it via `/execute`)
- Following an explicit step-by-step instruction
- Low-stakes choices where the inline obvious+alternative+trap habit (see `anti-anchoring` rule) already suffices

**Gate:** Either the unconditional trigger fired, or consequence AND openness are both true. If neither, STOP — state the single best answer directly (with a one-line obvious/alternative/trap) and do not spawn agents.

## Phase 1: DIVERGE — Isolated Parallel Generation

1. Restate the problem in one sentence and list the hard constraints (these go to every frame).
2. Pick ~5 frames from the table below whose vantage best surfaces structurally different approaches for THIS problem. Use 4 for narrow problems, up to 6–7 for wide ones. More than 7 hits diminishing returns (see `multi-agent-orchestration`).
3. **Send a single message with multiple `Task` tool calls for parallel agent launches** — one Task per frame, all in the same message. Each runs in isolation and never sees the others.
4. Give every sub-agent the SAME generator-only instruction:

> You are a GENERATOR working under the "<FRAME>" frame. From this vantage only:
> PROBLEM: <one-sentence problem>  CONSTRAINTS: <hard constraints>
> Produce 3–5 genuinely distinct approaches. For each: a one-line name, the core idea (2–3 sentences), and the single biggest risk.
> RULES: Do NOT evaluate, rank, hedge, or pick a winner. Do NOT mention other frames or approaches (you cannot see them). Favor range over safety — at least one approach must be non-obvious. Output a flat list. No preamble.

**Isolation invariant:** No generator receives another's output. No generator is asked to compare, score, or choose. Violating this re-introduces the anchoring the skill exists to remove.

**Gate:** All frame agents returned. You hold a flat, unscored, un-deduplicated pool. No evaluation has happened yet.

## Phase 2: FOCUS — Separate Critic Pass

Only now is judgment allowed. Do this yourself (or one critic agent) over the WHOLE pool.

1. **Score** each approach 1–5 on three axes, then weighted total:
   `score = 0.25·novelty + 0.45·viability + 0.30·fit`
   (novelty = distance from the obvious default; viability = buildable under constraints; fit = serves the real goal)
2. **Flag traps** — high-novelty/seductive approaches that fail a hard constraint. List each with the SPECIFIC constraint it violates. Traps are reported, never silently dropped.
3. **Cluster** survivors by underlying angle (collapse near-duplicates from different frames; note where isolated frames converged — that convergence is signal).
4. **Deepen the top 3** by weighted score: mechanism, key trade-off, first failure it would hit, rough cost/effort.

**Gate:** Every approach scored; traps flagged with reasons; clusters formed; top 3 deepened.

## Output Shape

1. **Brief** — one line: the problem and the constraints that bind it.
2. **Wide set** — full pool as a flat list, each with a chip `[N x.x | V x.x | F x.x → total]`.
3. **Converge — shortlist** — top 3, with the single best non-obvious pick STARRED (★) and one line on why it beats the obvious default. List **traps separately** below, each with the constraint it violates.
4. **Deepened branches** — the mechanism/trade-off/first-failure/cost for the top 3.
5. **One provocation** — a single closing line: the assumption most worth challenging, or the next option if constraints loosened. Exactly one.

## Anti-Patterns

| Bad Habit | What `/diverge` Does Instead |
|-----------|------------------------------|
| Commit to the first plausible answer | Forces a wide isolated pool before any judgment |
| Generators that rank or hedge themselves | Generator-only instruction; judgment is a separate pass |
| Branches seeing each other's ideas | Isolation invariant — parallel Task calls, no shared context |
| Running on closed/low-stakes problems | Pre-flight gate aborts unless consequence AND openness hold |
| Dropping the seductive-but-wrong option silently | Traps flagged with the exact constraint violated |
| Ending with a menu of equals | One starred non-obvious pick + one provocation |
| 12 frames "to be thorough" | ~5 frames; diminishing returns past 7 |

## Integration with Other Skills

`/diverge` is the **divergent** complement to the **convergent** `/deep-analysis`.

| Situation | Use |
|-----------|-----|
| Open-ended, consequential — "what are our options?" | `/diverge` (this skill) |
| One approach chosen — pressure-test it | `/deep-analysis` |
| Bug with unknown root cause | `/investigate` |
| Winners chosen — build them | `/execute` |
| Cheap inline judgment call | `anti-anchoring` rule habit — no skill needed |

**Hand-off chain:** `/diverge` (widen) → pick winners → `/deep-analysis` (validate) → `/execute` (build). Never feed the raw wide set to `/execute`; converge first.

## Cost Note

The Diverge phase spends ~5 parallel sub-agents plus one critic pass — real but bounded. Justified ONLY by the pre-flight gate (consequence × openness), never by default. On a closed or low-stakes problem this skill is WRONG, not merely expensive: it manufactures noise and false choices.

## Frames Table

| Frame | Vantage prompt |
|-------|----------------|
| **Regulator** | "What does compliance, audit, security, least-privilege demand? Design for the reviewer and the breach." |
| **Attacker** | "How would I break, abuse, or exploit this? Design the approach that survives an adversary." |
| **Inversion** | "What guarantees failure? Now invert each failure into a design constraint." |
| **First-principles** | "Ignore prior art. From the raw requirement and cost/physics, what is the minimal thing that works?" |
| **Markets / incentives** | "Who pays, who benefits, what behavior does this reward? Follow the incentives and the cost curve." |
| **Biology / evolution** | "Treat it as an organism: how does it adapt, self-heal, degrade gracefully, scale without central control?" |
| **Operator / 3am** | "I am on-call when this breaks. What is observable, reversible, boring to run? Optimize for the worst night." |
| **Scale-10x** | "Requirements hold but load/data/team are 10x. Which approaches survive, which shatter?" |
| **Constraint-removal** | "Which 'hard' constraint is actually assumed? Remove the most load-bearing one — what opens up?" |
| **Future-maintainer** | "Someone inherits this in two years with no context. What is simplest to understand, change, and delete?" |

## References

- `anti-anchoring` rule — the always-on inline habit this skill is the heavy mode for
- `deep-analysis` skill — the convergent partner; validates the chosen winner
- `multi-agent-orchestration` skill — parallel-launch idiom; 5–7-agent diminishing-returns limit
- `execute` skill — builds the converged winners
