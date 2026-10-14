---
name: verified-handoff
description: Record test, build and check runs as evidence receipts bound to an exact commit (or an explicitly described source archive), and verify a predeclared manifest of checks before claiming work is verified or handing it off. Use when reporting that checks passed, preparing a handoff or review request, or auditing someone else's claimed results. Receipts capture argv, cwd, times, exit status, signals, log hashes and input fingerprints; they are necessary evidence, not proof of review, semantic coverage, CI or deployment.
---

# Verified Handoff

A claim that a check passed needs a receipt for that exact input. Declare the checks
first, run each one through the recorder, then verify the whole manifest.

## 1. Declare the checks

Write `evidence/manifest.json` outside the repository before running anything:

```json
{
  "checks": [
    {
      "label": "unit-tests",
      "cwd": "../project",
      "command": {"executable": "python3", "args": ["-m", "unittest", "-v"]},
      "expectedSha": "<full 40- or 64-hex commit>",
      "resultFile": "unit-tests/result.json"
    }
  ]
}
```

`cwd` resolves against the manifest's directory. `resultFile` must be a relative path
inside a subdirectory of the manifest's directory, with no `.` or `..` parts. Each
check has exactly one of `expectedSha` or `sourceOnly` (a description of an archive
or unversioned tree).

## 2. Run each check

```bash
python3 scripts/evidence.py run --cwd ../project --out-dir evidence/unit-tests \
  --label unit-tests --expected-sha <full sha> [--timeout 900] -- python3 -m unittest -v
```

- The command is a literal argv; no shell is involved. Wrap in `sh -c` only when the
  manifest declares that.
- `--out-dir` must not exist; it is created for this run and must be outside the input.
- Committed runs are refused before launch when HEAD differs, when the index or any
  tracked file's content differs from HEAD, or when untracked files exist. Entries
  hidden by skip-worktree/assume-unchanged flags (`index-flags-unsupported`),
  submodules (`submodules-unsupported`) and tracked paths routed through a configured
  content filter driver (`content-filters-unsupported`, because inspecting them would
  run the driver's command) are refused rather than trusted. Use `--source-only` for
  such trees.
- A HEAD, index-flag or tracked-content change during the run fails the gate even if
  the child exited 0; the child status is kept separately.
- The child runs in its own process group. If the leader exits while group members
  remain, the recorder waits up to the timeout, then terminates only that group and
  fails the gate. On timeout the group receives SIGTERM, then SIGKILL.

Exit codes: `0` pass, `1` ran and failed, `2` usage error, `3` refused or not launched.

## 3. Verify before claiming

```bash
python3 scripts/evidence.py verify --manifest evidence/manifest.json
```

Read-only. Each check is `verified`, `pending` (no receipt yet) or `rejected` with
fixed reason codes (`wrong-command`, `wrong-commit`, `input-mutated`,
`child-nonzero-exit`, `invalid-timestamps`, `invalid-child-fields`,
`stdout-log-altered`, `receipt-path-symlink`, ...). A receipt verifies only when every
terminal field is present and correctly typed: ordered timestamps, finite duration and
timeout, integer exit code `0`, explicit `null` signal, no signals sent and an empty
process group. No component of the evidence path may be a symlink. Exit `0` only when
every check is verified. Report pending and rejected checks as such; never summarize
them as passing.

## What a receipt does not prove

- Who produced it, or that the manifest was honestly declared before the run.
- That the command exercises the changed behaviour (semantic coverage).
- Review, CI or deployment status; cite those separately.
- Authenticity: hashes are not signatures, and editing the receipt and logs together
  is not detectable.
- Transient input changes reverted during the run, or descendants that leave the
  process group (for example by starting a new session).

The child inherits the environment; it is not recorded. Keep receipts and logs outside
public source when they may contain private output.
