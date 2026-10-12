# Save portable session notes

Resolve the Codex home from CODEX_HOME or ~/.codex, then use its `framework/sessions/`
directory. Parse an optional user-provided identifier into a safe filename slug:
letters, digits, hyphens and underscores only; never allow separators or traversal.
Otherwise generate a timestamp/project/short-SHA identifier. Avoid collisions and
read an existing note before any requested update.

Record goal, project absolute path, exact SHA/branch, uncommitted files, completed
outputs, decisions, acceptance-check results and next executable steps. Include
**What Did NOT Work**, with exact error evidence, cause if known and rejected approaches;
write “No failed approaches” if appropriate. Do not include credentials or private logs.

Write and reread the note to verify it, then report the exact path and use
`$sdlc-resume-session <identifier>` to resume. Markdown notes supplement native Codex
session history; they do not recreate a transcript. Do not claim compaction happened.
