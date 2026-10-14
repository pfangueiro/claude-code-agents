# Delivery Routing Rules

- Route implementation outcomes (changes carried through review, merge or deployment)
  through /delivery.
- Default roles: Codex coordinates and independently verifies; an actual Claude
  execution implements. Only explicit owner or project instructions override them.
  The default assigns roles; it does not start a dispatcher.
- In an unfamiliar project, run /repo-context before planning changes.
- Collect required check receipts with /verified-handoff; report only checks that ran.
- Read-only questions, explanations and lookups do not launch workers.
- Loading a skill is not execution. Implemented, reviewed, merged and deployed are
  distinct states, each reported from evidence.
