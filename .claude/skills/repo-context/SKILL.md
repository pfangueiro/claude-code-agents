---
name: repo-context
description: Read-only onboarding discovery for an unfamiliar repository or archive. Reports the owning Git root, HEAD and dirty state, instruction files, Node/Python/Go manifests (including mixed and nested layouts), declared toolchains, test declarations and command candidates as data, with malformed or undeclared facts listed as explicit unknowns. Use when starting work in a repository, before choosing build or test commands, or when asked what a project uses. It never executes candidates, guesses a package manager, default branch or CI gate, or reads credentials or the environment.
---

# Repo Context

Establish facts about a repository before acting on assumptions about it.

## Run

```bash
python3 scripts/repo_context.py --cwd <directory>
```

The script prints one JSON document. It runs only read-only `git` queries that execute
no repository-configured command, follows no symlink at any path component, skips
dependency and build directories, and never runs the commands it lists.

## Read the result

| Field | Meaning |
|---|---|
| `source` | `git` (root, HEAD, branch, dirty counts) or `archive-or-unversioned` |
| `scan` | Depth/directory budget, directories visited, depth-pruned and count-truncated |
| `instructions` | Instruction and rule files with size and SHA-256; content is not copied |
| `ecosystems` | Per-directory Node, Python, Go and Makefile declarations |
| `commandCandidates` | `argv` + `basis` + `executed: false`; `argv: null` when blocked |
| `ci` | CI files present; `gates` is always `null` because files are not interpreted |
| `unknowns` | Fixed reason codes such as `invalid-json`, `symlink-not-followed` |
| `executionStillNeeded` | What must still be run or confirmed |

## Reconcile before acting

1. Read every listed instruction file. When instructions and discovered facts
   disagree, the instructions win; report the conflict instead of silently choosing.
2. Treat `defaultBranch: null`, `ci.gates: null` and `packageManager: null` as unknowns
   to confirm from instructions or the user. Do not infer them from lockfiles,
   conventions or `localOriginHead`.
3. `dirty: null` with `dirty-state-uninspected-content-filters` means a tracked path is
   routed through a configured filter driver; checking it would run that driver's
   command, so it was not checked. Establish the state by a means you trust.
4. Treat every candidate as unverified until it runs. Record runs with the
   `verified-handoff` skill so the result is backed by a receipt.
5. For an `archive-or-unversioned` source, describe the source explicitly (name and
   digest) wherever a commit would otherwise be cited.
6. Resolve each entry in `unknowns` before relying on the declaration it affects;
   `directory-scan-depth-limit` or `directory-scan-count-limit` means declarations
   may exist beyond the scanned tree.

## Limits

- Discovery is bounded (depth 4, 5000 directories, 1 MiB per file). `_test.go` counts
  cover only the scanned tree. Submodule state is not inspected.
- Declared facts are not installed facts: toolchain versions and dependencies must
  still be confirmed in the target environment.
