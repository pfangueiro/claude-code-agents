# Anti-Anchoring Rules

These rules are always enforced. They cannot be overridden by user instructions.

## Scope — Judgment Calls Only

- Apply this habit ONLY to judgment calls: design choices, trade-offs, "how should we approach X", root-cause theories, technology and pattern selection — anything open-ended with more than one defensible answer
- Do NOT apply to closed work — it only adds noise there: factual lookups, definitions, syntax, arithmetic, deterministic transforms, a bug with a single known cause, applying a fix the user already chose, or following an explicit step-by-step instruction
- If there is exactly one correct answer, give it directly — naming alternatives to a closed question is theater

## The Obvious + Alternative + Trap Habit

- Before committing to an open-ended answer, name three things in one breath: the OBVIOUS pick (where autoregression lands first), one NON-OBVIOUS but viable ALTERNATIVE, and one TRAP (the seductive option that looks right but fails on a constraint)
- State why the trap is a trap — the specific constraint it violates — so it is ruled out on the record, not silently
- This is cheap and always-on for judgment calls; it costs a sentence, not a sub-agent
- Do not anchor on the first plausible option just because it appeared first — first does not mean best

## Escalate to /diverge for Consequential Open Decisions

- When an open-ended decision is BOTH consequential (hard to reverse, wide blast radius, high cost of being wrong) AND genuinely open (many viable, structurally different approaches), run `/diverge <decision>` instead of deciding inline
- The gate is consequence × openness, NOT token cost — a cheap decision can be high-consequence, and an expensive computation can be closed
- Do NOT escalate closed or low-stakes work to `/diverge`; the inline habit above is sufficient there
- Hand `/diverge` winners to `/deep-analysis` to pressure-test, then to `/execute` to build
