# Evidence-driven investigation

Read actual source at the input SHA before consequential edits. For an unknown
cause, follow OBSERVE → REPRODUCE → TRACE → HYPOTHESIZE → PROVE → ROOT CAUSE
→ FIX → PREVENT. Do not skip evidence by trusting another agent's diagnosis.

- Capture symptoms, environment and a minimal reproducible failure.
- Trace execution through actual implementations and error paths with file/line citations.
- Consider competing hypotheses; run discriminating tests and record confirmations,
  eliminations and inconclusive evidence. Use optional Sequential Thinking, docs or
  browser MCPs only when available and relevant.
- State the proven causal chain and blast radius before editing.
- For a diagnosis-only request, return the report. When fixing is already authorized,
  continue within that scope; ask only for missing authority or an unresolved owner decision.
- Make the smallest change that addresses the proven class, rerun the reproduction,
  test for regressions and seek fresh review where material.
- Prove a regression guard fails on the original defect and passes with the fix.
  Save new pitfalls only in an authorized project memory/documentation location.

For an active outage, route to incident-commander for authorized mitigation first.
For a known-cause fix, implement directly rather than imposing this investigation.
See `references/investigation-frameworks.md` for deeper methods.
