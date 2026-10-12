# Execute a goal with Codex

Turn the requested goal into dependency-safe tasks and carry it through verification.

1. Record the exact input SHA, working-tree changes, acceptance criteria and existing
   authorization. Read the relevant source before designing a change.
2. Decompose substantial work into tasks under 30 minutes. For each record inputs,
   selected skill, agent/model, tools, concrete steps, write scope, dependencies,
   success checks, outputs and logging. Use the available plan tool or a Markdown
   task ledger; do not assume Claude task-list tools exist.
3. Discover installed skills, specialist agent types, MCPs and native tools. Use
   only capabilities exposed by this session. Select specialists by task; inherit
   the model unless the user or applicable policy specifies another available one.
   If native custom types are unavailable, load the corresponding sdlc-agent-<name>
   guide and apply its procedure inline or pass it to an authorized generic worker;
   do not claim its native sandbox/tool restrictions were enforced.
4. Launch independent read-only research together where delegation is authorized.
   Inspect every result and reconcile material claims against source or executable
   reproductions at the same SHA before assigning implementation.
5. Keep coupled work sequential. Parallel coding requires disjoint write scopes
   and separate Git worktrees. Create isolation before spawning; the launcher's
   schema, not a Claude `isolation` example, determines available parameters.
6. Use the session's collaboration tools for spawning, messaging and waiting.
   Native CLI names may include `spawn_agent`, `send_input`, `wait_agent`,
   `resume_agent` and `close_agent`; other hosts expose equivalent names.
   Inspect the actual schema. Send workers self-contained tasks or explicitly
   request history sharing when supported. Observe completion through native
   notifications/waits, with concise user updates during long work.
7. Run the relevant build and behavior checks. A fresh reviewer receives the goal,
   acceptance criteria, exact SHA/diff and raw artifacts, without the producer's
   verdict. Reproduce findings before fixing. Mutation-test fragile guards with
   both a failing input and a negative control.
8. Report completed outputs, actual validation and unresolved gaps. If a task
   fails, log its evidence and block dependents; continue independent work.

If delegation is unavailable, execute sequentially and disclose that verification
was local; do not label it an independent agent review. Keep the ledger current.
