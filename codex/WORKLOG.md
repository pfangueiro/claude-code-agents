# Adaptation task ledger

Initial adaptation input SHA: 509d282a195cc7a0e3b4d63b51b5f791be519eed.
That phase made no commits or remote mutations. Subsequent global installation is in
GLOBAL-VALIDATION.md. The user later authorized documentation/memory updates and GitHub
publication; later verification is recorded separately from historical test inputs.

| Atomic task (<30 minutes each) | Capability routing / agent | Inputs and dependencies | Write scope | Success/output/logging |
|---|---|---|---|---|
| Inventory and compatibility audit | Independent Codex architecture/code-quality reviewer; deep-read, review checklist; Git/rg, official web/docs | Baseline SHA, all skills/commands/agents and runtime sources; no dependency | Read-only | Exhaustive matrix and source-proven/reproduced findings returned to controller |
| Installer/security audit | Independent Codex security/devops reviewer; deep-read/review checklist, shell/Python/Git | Same SHA, installer/validator/hooks/CI; independent of inventory | Read-only | Ownership and config risks, 38 shell syntax checks, required acceptance checks returned |
| Research and synthesis | Controller, OpenAI Docs and skill-creator; official web + isolated Sequential Thinking stdio MCP | Audit reports and primary documentation | Codex design/docs | Schemas confirmed; three concise evidence checkpoints accepted by MCP |
| Runtime adaptation | Controller, skill-creator/native patch tool | Verified audits/docs | codex/overrides, AGENTS.md | Native workflows with no Claude launch semantics, generic external scopes |
| Builder and owned installation | Controller, Python/PyYAML/TOML, shell wrapper | Runtime overrides | codex/framework.py, install-codex.sh, config example | 39 workflow/13 agent output, collision/hash/rollback checks |
| Native hook adapter | Controller, official hook schema/Python | Docs/reproduced patch bypass | codex/hook.py | Protected direct patch cases denied, metadata only; limits disclosed |
| Acceptance and CI | Controller, unittest/mutation probes | Builder/hooks complete | tests/codex, CI | Loadable artifacts, resource execution, isolation/ownership/privacy checks, negative controls |
| Fresh verification | Fresh Codex reviewer; code-review-checklist, tools/source reproduction | Working-tree artifact fingerprint, original goal and raw acceptance criteria | Read-only repo; disposable forward-test sandbox | Findings reconciled through reproduction; final report records actual checks |

Parallel work was read-only. Coupled implementation and integration stayed sequential;
no parallel coding or shared-worktree mutation was dispatched. Installed models were
inherited; no model override, auth inspection, live-data access or external messages.
