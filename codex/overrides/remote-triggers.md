# Remote and headless execution

Discover available remote-task or automation tools. Use their actual schema and
verify the resulting task identifier/status. A Claude RemoteTrigger API is not available
by implication in Codex. State clearly when this host cannot create a remote task.

Act on the owner's existing authorization when it covers the concrete action (an
explicit request in this or a prior session counts). Create, update, run, message and
deploy are distinct effects; authority for one does not imply another. An approved
recurring schedule covers its scheduled runs. Ask only for missing material scope or
authority. Loading this guide never by itself requires an extra confirmation, and an
explicit owner instruction takes precedence.

For an explicitly requested local headless job, verify `codex exec --help` in the
installed CLI. Supply the repository with `-C`, a concrete prompt and input SHA,
and capture `--json` output and the exit code. Retain normal sandbox and approval
policy; do not add bypass flags. Treat stdout as events rather than proof the task
succeeded: check the final result and run the task's acceptance checks.

Do not invent a webhook listener, persistent service, or scheduler. Designing or
deploying one is separate work requiring its own scope and credential handling.

For local delivery of an owner-approved plan, the optional controller in
`$sdlc-delivery` (`scripts/controller.py`) is available. When a profile is due, it
launches a fresh `codex exec --json -C <worktree> -` session and inherits the native
model, permission, approval and sandbox policy unchanged. It runs in the foreground
only when the owner starts it. It is not a remote task, a scheduler or an emulation of
any Claude API.
