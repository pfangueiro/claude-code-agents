# Preserve context before native compaction

Read any existing HANDOFF.md. Save the current goal, exact SHA/branch, working-tree
changes, completed outputs, decisions, failed attempts with error evidence, validation
and next steps. Verify the file was written and report the location.

Codex controls compaction. A skill cannot call `/compact` as a tool; in a CLI with
that command, tell the user they can invoke the native `/compact` after the handoff.
Do not recursively invoke this skill or claim the context was compacted.
