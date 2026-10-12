# Laptop user-global validation

Performed 2026-10-12 against framework Git baseline
`509d282a195cc7a0e3b4d63b51b5f791be519eed` plus the independently reviewed adapter.
The user requested installation/testing on this laptop across projects.

## Installation

Installed with the same operation as `./install-codex.sh --user`, after a successful
dry-run. It added 52 skills under `~/.agents/skills`, 13 native specialist definitions
under `~/.codex/agents`, adapter resources/ownership metadata under `~/.codex/framework`,
and a managed block in `~/.codex/AGENTS.md`.

Existing global instruction bytes remain a prefix of the updated file. Existing
personal skills were verified byte-identical with content hashes. Codex config.toml
and hooks.json metadata remained unchanged; auth files were not inspected. No optional
Codex hook definitions or MCP connections were activated. Both an installed integrity
check and a second idempotent install returned zero changed paths.

Claude already had a global install. Its shipped agent/skill/command/rule/library files
matched repository source (81 matching files, no drift). The two absent source-only
items were a directory README and an untracked .DS_Store, not executable components.
No Claude install/reconciliation was run.

## Cross-project discovery

Using the real user home/default Codex profile, ran native
`codex -C <directory> debug prompt-input ...` in two unrelated fresh Git repositories
and a nested directory. All three discovered exactly 49 implicit adapter skills:
36 workflow skills plus 13 specialist guides. Three explicit-only workflows remained
excluded from implicit selection as intended. Root aliases in the prompt were resolved
to confirm every adapter skill came from `~/.agents/skills`; the global managed
instruction block appeared in each prompt. No project-local `.agents` or `.codex`
installation was created.

## Actual CLI behavior

Ran independent read-only reviews through the installed Codex and Claude CLIs in
separate disposable repositories containing identical cache/test fixtures. Models
inherited the user's configuration; no approval, sandbox or hook-trust bypass flags
were used. Codex used its read-only sandbox. Claude selected the globally installed
`code-quality` agent with read/command tools and no file-editor tools.

Fixture SHA256 (cache.py followed by test_cache.py):
`cee3ebc145519295c49b581ef142b2f1ff2cc20c6d05b9826c79a17c3745cc8d`.
Both processes exited 0 and independently reported the same reproduced failure:
`expired(10, 10)` returned false because cache.py:2 compared `now > deadline`.
The fixture test requires inclusive expiry, so the minimal correction is `now >= deadline`.
The controller independently reran the failing test in both repositories, confirmed
the source fingerprints, and verified before/at/after boundary behavior with the
correction entirely in memory. Both fixture source files remained unchanged.

Codex read global rules, sdlc-agent-code-quality, sdlc-investigate and the review
checklist. Claude read its global code-quality agent and fix-quality/verification/
code-quality rules. Claude did not read the dedicated investigation skill; its report
looked for a command file instead. The controller confirmed that the actual dedicated
skill exists at `~/.claude/skills/investigate/SKILL.md`. Therefore this test establishes
Claude's global reviewer/rule use, not explicit investigation-skill invocation.

Raw evidence remains in private disposable local storage. Machine-specific paths and
CLI transcripts are excluded from this public repository; the fixture fingerprint
and independently reproduced outcomes above identify the relevant input.

## Scope of the conclusion

The installed workflows are available across projects for this laptop user with the
default profile. Project instructions, disabled skills, alternate CODEX_HOME/profiles
and host-specific capabilities can change effective behavior. Availability does not
guarantee automatic selection or prove all workflows. Native custom Codex profile
spawning, optional hooks/MCP activation and the remaining runtime parity gaps are
not established by these tests. See [FEATURES.md](FEATURES.md).
