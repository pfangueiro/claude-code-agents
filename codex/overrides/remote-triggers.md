# Remote and headless execution

Discover available remote-task or automation tools. Use their actual schema and
verify the resulting task identifier/status. A Claude RemoteTrigger API is not available
by implication in Codex. State clearly when this host cannot create a remote task.

For an explicitly requested local headless job, verify `codex exec --help` in the
installed CLI. Supply the repository with `-C`, a concrete prompt and input SHA,
and capture `--json` output and the exit code. Retain normal sandbox and approval
policy; do not add bypass flags. Treat stdout as events rather than proof the task
succeeded: check the final result and run the task's acceptance checks.

Do not invent a webhook listener, persistent service, or scheduler. Designing or
deploying one is separate work requiring its own scope and credential handling.
