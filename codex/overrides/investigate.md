# Evidence-driven investigation

Read actual source at the input SHA before consequential edits. For an unknown
cause, follow OBSERVE → REPRODUCE → TRACE → HYPOTHESIZE → PROVE → ROOT CAUSE
→ FIX → PREVENT. Do not skip evidence by trusting another agent's diagnosis.

- Capture symptoms, environment and a minimal reproducible failure.
- Trace execution through actual implementations and error paths with file/line citations.
- Consider competing hypotheses; run discriminating tests and record confirmations,
  eliminations and inconclusive evidence. Use optional Sequential Thinking, docs or
  browser MCPs only when available and relevant.
- Qualify each claim: observed (directly inspected — basis is source inspection at the
  cited revision/`file:line`, or an actual runtime capture such as a reproduction or test;
  reading code does not prove the path executed), derived (name the premises), or inferred
  (a hypothesis still to verify). Keep unknown, unsupported, inconclusive and contradictory
  evidence visible — a missing fact is not proof of absence, and an unproven cause is not
  a root cause, so do not report it complete. Bound negatives to the files read and the
  blast-radius search scope and its limits: a green test or clean search covers only what it
  exercised. On a truncated read, page a supported smaller read or reuse retained source by
  stable path rather than promote a preview or rerun an identical reproduction. Report
  runtime behaviour separately from static reasoning; invent no test, output or citation; no
  numeric confidence scores.
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
