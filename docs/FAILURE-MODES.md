# Failure Modes

A taxonomy of the defect classes that actually shipped in this repository, distilled from six
rounds of execution-based stress testing across all 27 skills, the installer, the validator, the
hooks, and the daemon.

**Why this file exists.** Every entry below is a real defect that passed review, passed
`./validate.sh`, and in most cases passed a guard specifically written to catch it. They are not
hypothetical. If you are adding a check, a guard, a gate, or a fix to this framework, read this
first — the same nine shapes keep coming back, and knowing them is most of the job.

The rounds were "execution-based": every `references/*.md` and `scripts/*` file was opened and every
documented command was actually **run**, not reasoned about. Findings rose with each round. That was
the probe sharpening, not the codebase decaying — round 1 only read `SKILL.md` and under-called by a
wide margin.

---

## 1. Fail-open verification — "gates that cannot fail"

**The dominant class. Found in all six rounds, including twice *inside guards written to prevent
it*.**

A gate that reports success when it did not actually verify anything is worse than no gate: it
converts an unknown into a false "verified", and everyone downstream stops looking.

Four that shipped here:

| Artifact | The defect | Measured behavior |
|---|---|---|
| `/optimize` test gate | Default regex `[0-9]+ (passed\|…)` | Matches the literal string `0 passed`. A runner that collected **zero tests** and exited 0 read **GREEN** — through the exact gate added to catch that. |
| `deployment-runbook/scripts/health_check.py` guard | Tested `if python3 … --check X` (i.e. exit 0) | A single-check run can *never* exit 0 — an all-passed-but-partial run exits `EXIT_PARTIAL=3`. The detection branch was unreachable, so the guard printed **PASS** over an injected `return True`. |
| `infrastructure-as-code` drift detection | Alerted only on `terraform plan -detailed-exitcode` == 2 | Exit 1 (expired credentials, unreachable backend) produced **silence** — indistinguishable from "no drift" in an unattended scheduled job. |
| `browser-testing` visual regression | `compare -metric AE` on mismatched image sizes | Returns `0 (0)`, **exit 0** — the cleanest possible pass. A genuine same-size regression returns `2601 (0.065)`, exit 1. A mis-sized screenshot was the *easiest* way to get a green visual diff. The skill's own "Fail-closed rules" asserted the opposite. |

Note the direction of every one of these: the false claim always pointed toward hiding the problem.
That is not coincidence — a fail-*closed* bug produces noisy false alarms that someone fixes within
a day, so only the fail-open ones survive to be found in round six.

> **RULE — feed it the failing input.**
> Before shipping any check, regex, threshold, or exit-code contract, run it against the input it is
> supposed to reject. Not a similar input. The actual failing one.
>
> - Regex? Run it against `0 passed`, `0 passing`, `0 tests ran`, `0 ok` — and against `12 passed`,
>   which must still be accepted.
> - Exit-code contract? Enumerate *every* exit code the artifact can produce and say what each one
>   means. "Non-zero" is not a contract; `1` vs `2` vs `3` vs `124` are different events.
> - Comparator or metric? Feed it the degenerate input (empty, zero-length, wrong shape, wrong size)
>   and confirm it errors instead of scoring perfectly.
>
> **"Did not run" must never share an outcome with "nothing to report."**

### The guard corollary

A guard that greps for a magic string is a proxy, and proxies drift. Our `context7` guard grepped
for one literal and certified **four surviving dead parameter references**. The repaired guards in
`validate.sh` now **execute the artifact** and require the failure path — see
`validate.sh` §"Checking fail-open regression guards" for the shape to copy.

---

## 2. A gate that can never PASS is the same defect

**CI here was red for 20 of 20 runs across more than a month.** No green run since 2026-07-08.
Every commit in the remediation effort was pushed onto a red pipeline — including commits whose
messages reported "0 errors" from a local run.

Single root cause: `run_structural_checks` asserted `~/.claude/settings.json` exists
*unconditionally*. That is a property of an **installed machine**, not of the repository. On a CI
runner or a fresh clone, "missing" means *never installed*, not *deleted*.

The consequence was not a broken check. It was that **everyone learned to ignore CI.** A signal that
is always red carries exactly as much information as one that is always green: zero. Both are
read the same number of times, which is never.

The fix gated the assertion on an install marker (`.framework-version` / `~/.claude/agents`) and
degraded to a warning otherwise — matching sibling checks that already skipped gracefully. Verified
in all three states:

```
CI-clean (no ~/.claude)                    -> green, 225 checks
installed                                  -> green, 242 checks
installed, settings.json genuinely deleted -> still FAILS  (invariant intact)
```

> **RULE — a check must be able to land on both sides.**
> Before merging a check, name the concrete condition under which it PASSES and the concrete
> condition under which it FAILS, and produce both. If either is unreachable in the environment
> where the check runs, it is a zero-information gate regardless of polarity.
>
> Ask specifically: **is this asserting a property of the repository, or a property of my machine?**
> That single question would have caught the CI outage on day one.

---

## 3. A later repair can silently kill an earlier guard

Adding `EXIT_PARTIAL=3` to `health_check.py` made an earlier guard's detection branch unreachable —
the guard tested for exit 0, which the script could no longer produce on that path. **Both commits
were green. Same day.** The guard went on printing PASS over a stubbed probe for weeks.

This is the mechanism that makes a hardened codebase quietly soften over time. Nobody edited the
guard. Nobody edited the invariant. Someone changed the *interface between them*.

> **RULE — changing an artifact's contract means re-gap-testing every guard that watches it.**
> "Contract" includes: exit codes, output format, log line wording, file paths, CLI flag names,
> JSON keys, and the set of states the artifact can be in.
>
> Practical move: `grep -rn '<artifact-name>' validate.sh` before you change it, and re-run the
> gap test (§ *Contributor checklist*) for every hit.

---

## 4. Fix the class, not the reported instance

Repeatedly, the reported file was fixed while its **twin was never opened**.

- `ui-guidelines`' `App.useApp()` mandate swept `SKILL.md` but not `component-patterns.md` and
  `codebase-patterns.md` — the two reference files that *Step 1 of the skill routes readers into*.
  Both still taught the static `message` / `notification` / `Modal.confirm` APIs the skill now
  forbids.
- Some `references/*.md` files have **one commit in their entire history** while their `SKILL.md`
  sibling was edited repeatedly. That asymmetry is the fingerprint: if a file has not been touched
  since it was created, it has almost certainly not been re-read either.

The tell is structural. A skill is a directory, not a file. A rule stated in `SKILL.md` is a claim
about *everything under that directory*, and reference files are exactly where a reader lands after
the summary convinced them.

> **RULE — one instance of a defect is evidence of a class.**
> When you fix something, immediately search for the same shape everywhere else:
> ```bash
> git log --format='%h' -1 -- <the-file-you-fixed>     # when was its twin last touched?
> grep -rn '<the-bad-pattern>' .claude/skills/          # who else does this?
> ```
> Then fix all of them in the same commit. A partial sweep is worse than none, because the next
> reviewer sees a recent commit on the topic and assumes it is handled.

---

## 5. "Proven in scratch repos" — on the happy path only

`git-workflow` documented `git diff --cached HEAD` being EMPTY as *"the commit contributes nothing;
dropping it loses nothing."* A prior commit claimed this was **proven in scratch repos**. It was —
on the path where it works.

The destructive path inverts the verdict. EMPTY is **ambiguous**: it also means you resolved a
conflict by discarding *your own side*. Under a rebase, `git checkout --ours` **is** the upstream
side, so this is easy to hit by accident. Measured on git 2.50.1:

```
resolved by discarding own work:
  git diff --cached HEAD              ->    0 bytes    ("safe to drop")
  git diff REBASE_HEAD -- <file>      ->  112 bytes    (the work you just destroyed)
  after --continue                    ->  ZERO commits contain the change
```

The recipe now treats EMPTY as ambiguous and ships the discriminator that tells the two causes apart.

> **RULE — for anything that can destroy work, the test that matters is the destructive path.**
> Verifying that a safety check says "safe" when things *are* safe proves nothing about the check.
> You must produce the dangerous state and confirm it says "dangerous".
>
> **A verdict with two possible causes is ambiguous, not safe.** If a signal can be produced by both
> the benign and the catastrophic case, it is not a signal — find the discriminator that separates
> them, or state the ambiguity in the doc.

Same class, same round: `investigate`'s bisect recipe ran `git bisect start/bad/good` and never
`git bisect reset`, leaving a detached HEAD. A commit made in that state is unreachable from the
original branch after reset. The happy path — bisect finds the commit, you walk away — never
exposes it.

---

## 6. Guard asymmetry is the evasion surface

The abort-dominance guard matched the **"bad pattern" side as a closed keyword list** while the
**"excuse" side was a synonym family**. An evader only ever has to beat the weaker side.

Two concrete leaks it shipped with:

- Denial-amnesty fragments were **unanchored**, so `pass` matched inside **by`pass`**, and the
  sentence *"… is enough, though it never bypasses the ABORT list"* cancelled its own grant.
- `trig`, a closed verb list, gated the strong signals and short-circuited — so the line
  *"If the user says `/execute`, proceed."* was **never examined at all**.

The repair was not a longer blacklist. Gate bullets are now checked against a **positive whitelist
of the three legitimate shapes** (ABORT / ROUTE OUT / restrictive run-condition) — fail-closed by
construction. Re-tested against 10 evasions including all four the reviewers demonstrated: 0 leaks,
and the four live gates still pass.

> **RULE — prefer a positive whitelist of legitimate shapes over a blacklist of bad ones.**
> A blacklist is always one paraphrase away from a leak, and its failure mode is silent. A whitelist
> fails *closed*: an unrecognized shape is rejected and someone has to look at it.
>
> If you must match two sides of a condition, make them **equally strict**. Asymmetry is not a
> partial defense; it is a documented bypass.

---

## 7. A guard that CONVICTS must ship WITH the repair, in the same commit

A correct new abort-dominance guard once **landed red on its own tree**: it convicted `execute` and
`investigate`, and shipped without repairing them. `./validate.sh` exited 1 on `main`.

The temptation at that moment is enormous and it is always wrong: **narrow the guard until it goes
green.** Doing so converts a true finding into a permanently blind spot, and the blind spot is
shaped exactly like the defect you just found.

> **RULE — guard and repair land together, or neither lands.**
> - Never merge a guard that fails on the current tree.
> - Never weaken a guard to make it pass. Fix the thing it caught.
> - If the repair is too large for this commit, the guard waits for the repair. It does not ship
>   narrowed, and it does not ship with the finding suppressed.
>
> Related, from the same round: the sweep that introduced this guard also shipped `/optimize`'s
> `0 passed` regex (§1). **Review your own sweep as adversarially as you reviewed the originals.**

---

## 8. Following the documentation must not break the framework

`validate.sh --quick` went RED on a clean tree — and the watchdog could **never heal it.**

The shared-set enumeration walked `__pycache__`. So the *first time anyone ran a shipped Python
script* — which the docs explicitly instruct — a `.pyc` appeared in the source tree, was reported as
`shared-set missing`, and handed the self-healing watchdog drift it is structurally incapable of
fixing (`install.sh` does not deploy bytecode). The directory was gitignored, so it was also
invisible in `git status`.

Result: an hourly heal loop, triggered by a user doing exactly what the README told them to do.

> **RULE — every documented command is part of the product's behavior.**
> Auto-reconciliation must be immune to the side effects your own documentation instructs users to
> create. Before shipping a doc that says "run this", run it, then run `./validate.sh` and check
> `git status` — including ignored files.
>
> Corollary: **a check that cannot auto-heal must not run in the automated caller's path.** The
> watchdog calls `--quick`; anything `install.sh --update` cannot rewrite (prose counts, source
> content defects) belongs in FULL-only, or it loops forever. Conversely, a reconciliation check
> that only runs in a manual full run is not reconciliation at all.

---

## 9. Repairs inject defects

**Roughly 23% of the final round's findings were introduced by earlier repair commits** — seven
majors, by that round's own accounting. Named instances, all documented in the CHANGELOG:

- The `health_check.py` guard killed by a later `EXIT_PARTIAL` repair (§3).
- `git-workflow`'s `git diff --cached HEAD` claim, introduced by the *previous round's own repair*
  (§5).
- `/optimize`'s `0 passed` regex, introduced by the sweep's new anti-fail-open gate (§1, §7).
- The abort-dominance guard shipping the repo red (§7).
- `ui-guidelines`' replacement snippet initially firing all three notification APIs **in the render
  body** (renders nothing, antd warns) — the fix for a correctness bug introduced a new one.
- `kubernetes-ops`' new `ignoreDifferences` shipped with **no `name:` selector**, which would have
  disabled replica drift detection *and* correction for every Deployment in the Application.

Three recurring mechanisms behind them:

1. **Fixed the reported instance, not the class** — the twin reference file was never opened (§4).
2. **The recipe was reasoned about, not run** — plausible, wrong, and untested (§1, §5).
3. **A later repair silently invalidated an earlier guard** (§3).

> **RULE — budget review capacity for the repairs themselves, not just the originals.**
> A remediation sweep is new code written fast under the belief that it is making things safer. That
> belief is precisely what suppresses scrutiny. Schedule an adversarial pass over the sweep, by
> someone who did not write it, before it merges.

---

## Contributor checklist

Before opening a PR that adds or changes any check, guard, gate, or fix:

**Gap test — non-negotiable.**
- [ ] **Inject the defect** the guard exists to catch. Confirm the guard **FAILS**.
- [ ] **Restore** the tree. Confirm the guard **PASSES**.
- [ ] Record both outcomes in the commit message. "Should catch it" is not a gap test.

**Fail-open.**
- [ ] Fed the check its **failing input** — the real one, not an analogue.
- [ ] Enumerated **every** exit code / output state the artifact can produce, and said what each means.
- [ ] Confirmed the check **executes the artifact** rather than grepping for a string that suggests
      the artifact is correct.
- [ ] Confirmed "did not run" cannot produce the same outcome as "ran and found nothing".

**Fail-closed-to-pass.**
- [ ] Named the condition under which this check PASSES, and produced it.
- [ ] Confirmed the check asserts a property of the **repository**, not of my installed machine —
      or is explicitly gated on an install marker.

**Blast radius.**
- [ ] `grep -rn '<artifact>' validate.sh` — re-gap-tested every guard watching anything whose exit
      codes, output format, or paths I changed.
- [ ] Searched for the **class**, not the instance: fixed every sibling and every `references/*`
      twin in the same commit.
- [ ] For anything that can destroy work: tested the **destructive** path, and confirmed no verdict
      has two possible causes.

**Shipping.**
- [ ] The guard and its repair are in the **same commit**; `./validate.sh` is green on this tree and
      the guard was **not narrowed** to achieve that.
- [ ] Ran every command this change documents, then re-ran `./validate.sh` and checked `git status`
      including ignored files.
- [ ] CHANGELOG bullet added **in this commit**, citing the SHA. (Changelog lag is this repo's most
      recurring audit finding.)

---

## Two rules that are not negotiable in this repo

1. **Every guard must be gap-tested** — inject the defect, confirm FAIL, restore, confirm PASS.
2. **A fix without a guard is incomplete** — an unguarded fix silently regresses, and the next
   person to find it will find it in round seven.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full contribution flow, and
[SELF-HEALING.md](../SELF-HEALING.md) before touching any reconciliation path.
