# Design a native Codex specialist

Inspect existing `.codex/agents/*.toml` (project) or `~/.codex/agents/*.toml` (user)
within the authorized scope. Define a narrow responsibility and a description that
helps the coordinator select it. Use a standalone TOML file with `name`, `description`
and `developer_instructions`; choose supported configuration keys only after checking
current documentation and installed runtime. Match filename to the agent name.

Inherit the active model unless the user or project explicitly selects an available
model. Claude model aliases and `tools:` YAML allowlists are not translated by Codex.
Use supported sandbox/MCP policy for access restrictions; prompt text is not enforcement.

Specify inputs/SHA, outputs, write scope, verification and handoff to the coordinator.
Parse the file with a real TOML parser and forward-test it on a representative task
in an isolated workspace. Do not claim agents trigger deterministically on keywords.
