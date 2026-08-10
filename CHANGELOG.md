# Changelog

All notable changes to Claude Agents will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **CI had never passed. 20 of 20 runs red, no green run since 2026-07-08 — over a month.** Every
  commit in this remediation effort was pushed onto a red pipeline, including ones whose message
  reported "0 errors" from a local run. Single root cause: `run_structural_checks` asserted
  `~/.claude/settings.json` exists *unconditionally*, but that is a property of an **installed
  machine**, not of the repository — on a CI runner or a fresh clone "missing" means *never
  installed*, not *deleted*. It now degrades to a warning when no install marker
  (`.framework-version` / `~/.claude/agents`) is present, matching the sibling `~/.claude/hooks` and
  analytics checks that already skipped gracefully. Verified in all three states: CI-clean → green
  (225 checks), installed → green (242), installed with `settings.json` genuinely deleted → still
  FAILS, so the self-heal invariant is intact.
  A gate that can never PASS is read exactly as often as one that can never FAIL — this was the
  process-level twin of the fail-open class the guards in this file exist to catch.

- **Round-6 verification: two recipes that destroyed committed work, a dead guard, and a watchdog
  heal-loop.** A final execution-based stress test of all 27 skills (every `references/` and
  `scripts/` file, not just SKILL.md). 0 broken. Everything below was reproduced before it was fixed.
  - **`validate.sh --quick` was RED on a clean tree, and the watchdog could never heal it.** The
    shared-set enumeration walked `__pycache__`, so the *first time anyone ran a shipped Python
    script* — which the docs instruct — a `.pyc` appeared in source, was reported
    `shared-set missing`, and handed the watchdog drift it cannot fix (install.sh does not deploy
    bytecode). `__pycache__` is now pruned; gap-tested that real drift in a sibling script in the
    same directory is still caught.
  - **`git-workflow` certified destroyed work as safe — a defect introduced by the previous round's
    own repair.** `git diff --cached HEAD` EMPTY was documented as "the commit contributes nothing;
    dropping it loses nothing". EMPTY is *ambiguous*: it also means you resolved by discarding your
    own side, and under a rebase `git checkout --ours` **is** the upstream side, so it is easy to hit
    by accident. Measured on git 2.50.1: resolving that way gives `--cached HEAD` = 0 bytes while
    `git diff REBASE_HEAD -- <file>` = 112 bytes, and continuing left **zero** commits containing the
    change. The recipe now treats EMPTY as ambiguous and adds the discriminator that tells the two
    causes apart. (The prior commit claimed this was "proven in scratch repos" — it was proven on the
    happy path only.)
  - **`investigate`'s bisect recipe orphaned commits.** It ran `git bisect start/bad/good` and never
    `git bisect reset`, leaving a detached HEAD. Verified: a commit made in that state is unreachable
    from the original branch after reset. Added the reset, the clean-tree precondition, the
    mark-each-step call, and the do-not-commit-while-bisecting warning with the reflog recovery note.
  - **The fail-open guard for `health_check.py` could not fail — killed by a later repair.** It tested
    `if python3 … --check X` (exit 0), but a single-check run can never exit 0: an all-passed-but-
    partial run exits `EXIT_PARTIAL=3`. That exit code was added by a *later* commit the same day,
    silently making the earlier guard's detection branch unreachable — both green. Proven by injecting
    `return True` into `check_database`: the guard printed PASS. It now asserts the outcome
    (fail-closed probe → 1; probe stubbed to succeed → 3) and FAILS on that same injection.
  - **`infrastructure-as-code` drift detection alerted only on exit 2**, so an errored run — expired
    credentials, unreachable backend — exits 1 and produces *silence*, indistinguishable from "no
    drift" in a scheduled unattended job. Now fails loudly on both, because "did not run" must never
    share an outcome with "nothing to report".
  - **`ui-guidelines`' `App.useApp()` mandate had swept SKILL.md but not the two reference files
    Step 1 routes readers into** — `component-patterns.md` and `codebase-patterns.md` still taught the
    static `message`/`notification`/`Modal.confirm` APIs the skill now forbids. Converted. (`<Modal>`
    as a *component* is genuinely exempt and was left alone.)
  - **`browser-testing`'s visual regression could not fail on a size mismatch — and the skill said
    the opposite.** Its Fail-closed rules asserted "a size mismatch makes the comparator error out;
    treat that error as a FAIL". Measured on ImageMagick 7.1.2-21, `compare -metric AE` on 200x200
    vs 100x100 returns **`0 (0)` with exit 0** — the cleanest possible *pass* — while a genuine
    same-size regression returns `2601 (0.065)` with exit 1. So a mis-sized capture was the easiest
    way to get green. The recipe now asserts identical `magick identify -format '%wx%h'` dimensions
    *before* comparing, and no longer assumes the screenshot filename (the tool may append a
    timestamp; a comparator pointed at a nonexistent path must FAIL). Guarded, and gap-tested both
    ways: drop the dimension assertion -> FAIL; restore the false claim -> FAIL.
  241 checks, 0 errors, under bash 3.2 and bash 5.

- **Known-open sweep: the 10 remaining majors closed, and the six new defects that sweep introduced.**
  A 10-fixer / 10-reviewer / 1-gate run repaired the carried-forward majors; an adversarial review then
  found that six of the ten areas had introduced a new defect, and those were fixed on top. What
  actually landed:
  - **ci-cd-templates** — the blue/green cutover was an *invalid* AWS call (`modify-listener` without
    `Type` in `DefaultActions[0]`, rejected by the aws-cli 2.34.37 parser), so the one step that
    promotes green could never run; smoke tests ran before the async `create-deployment` finished; the
    canary job installed `kubectl` with no kubeconfig. Fixed, plus the follow-on: `kubectl rollout
    status deployment/app` was a **hardcoded name**, which returns 0 instantly against whatever else is
    already converged — now waits on the manifest just applied (`-f`).
  - **git-workflow** — `git diff REBASE_HEAD^ REBASE_HEAD` cannot measure "already applied upstream"
    (it is the commit's own patch against its own parent, independent of upstream); replaced with a
    check proven in scratch repos to distinguish the two cases. The unguarded
    `git branch --merged | xargs git branch -d` — which deleted `develop` and `release/1.2.0`, the two
    branches this same skill marks Permanent — is now guarded.
  - **library-docs** — three of four worked examples returned zero documentation. Every library ID in
    the file was re-queried live; `/facebook/react` and `/tailwindlabs/tailwindcss` were bare redirects
    and the version-pinned ID form does not exist.
  - **kubernetes-ops** — pinned `replicas` + HPA + Argo `selfHeal` flapped forever. Fixed, and the
    follow-on too: the new `ignoreDifferences` had **no `name:` selector**, which would have disabled
    replica drift detection *and* correction for every Deployment in the Application.
  - **docker-deployment** — four of six bind-mount sources were never created, so Docker made
    *directories* named `nginx.conf`/`init-db.sql` and the stack failed stickily. Fixed; and since the
    block doubles as the repair procedure, the unguarded `openssl rand > secrets/…` that would rotate
    the DB password on re-run (while the volume keeps the old one, leaving `pg_isready` green) is now
    generate-if-absent.
  - **ui-guidelines** — antd's static `message`/`notification`/`Modal.confirm` cannot consume
    `ConfigProvider` context, which is this skill's central mandate; `App.useApp()` now required. The
    replacement snippet initially fired all three **in the render body** (renders nothing, antd warns)
    — corrected to event handlers, and an unreproducible theme-hash literal replaced with the
    comparison that actually holds.
  - **execute / agent-coordination** — `agent-selection.md` omitted 4 of 13 agents, so security work
    routed to a grep scanner instead of the Opus `security-auditor`; a phantom `bedrock-integration`
    row (no such skill has ever existed) removed. Its self-check was **fail-open** — run from the wrong
    directory both inputs come back empty and `comm` prints nothing, reading as clean — so it is now
    fail-closed *and* enforced by validate.sh instead of living only in prose.
    `execute/SKILL.md` still taught "omit `subagent_type` to fork" two lines from a corrected line;
    omitting does **not** fork, it silently starts a fresh-context general-purpose agent.
  - **deployment-runbook** — ten cited scripts that are neither shipped nor inline, including the
    mid-incident rollback, no longer read as runnable; and the documented success string
    "External services reachable" appears nowhere in the script, which ships none for that check.
  - **The abort-dominance guard was fail-open two ways** — the defect it exists to prevent, in the
    guard itself. Its denial-amnesty fragments were unanchored, so `pass` matched inside **bypass** and
    "… is enough, though it never bypasses the ABORT list" cancelled its own grant; and `trig`, a
    closed verb list, gated the strong signals and short-circuited, so "If the user says `/execute`,
    proceed." was never examined at all. Both fixed, and because a blacklist is always one paraphrase
    from a leak, gate **bullets** are now checked against a positive whitelist of the three legitimate
    shapes (ABORT / ROUTE OUT / restrictive run-condition) — fail-closed by construction. 10 evasions
    incl. all four the reviewers demonstrated: 0 leaks; the four live gates still pass. The header
    comment's false "25 evasions -> 0 leaks" claim is corrected to what was actually re-run, with the
    remaining limit stated (a grant written as a prose paragraph still faces only the vocabulary
    conjuncts).
  - Latent crash: `"${_ref_files[@]}"` on an empty array aborts under `set -u` on **bash 3.2**, which
    is what macOS ships — reachable as soon as a forked skill has no reference files.
  241 checks, 0 errors, verified under bash 3.2 and bash 5.

- **Final remediation sweep: the last 13 skills, plus three holes the repairs themselves left.**
  A 15-agent run repaired the assigned defects, verified each independently, then re-tested all 27 skills by
  execution. Measured result on the re-test: **0 broken, 19 of 27 ready to rely on, 8 still carrying a major**
  (the open ones are listed under *Known open* below — this round did not close them).
  - **Gate logic** (deep-analysis, diverge, context-escalation): the OR-disjunction gates whose unconditional
    arm made their own ABORT lists unreachable are now abort-dominant post-selection redirects — each abort
    condition names where to go instead, and being invoked (even by literal slash command) no longer overrides
    an abort. context-escalation's L5 is reachable again: its L4 arm ("task still in flight") was true in
    essentially every context-pressure case, so the level that exists for exactly that case could never run.
  - **Tool-contract violations** (execute, worktree-workflow): `EnterWorktree` is explicit-request-only,
    session-scoped and single-instance, so it cannot isolate one task among many — both skills prescribed it as
    a per-task mechanism. Corrected against the live schema. Note the fixer's own correction to the brief:
    `isolation: "worktree"` **is** real — it is a parameter of the **Agent** tool, not EnterWorktree — so the
    verified mechanism was kept and only the unverifiable part removed.
  - **kubernetes-ops** blamed CrashLoopBackOff on the readiness probe, the one probe that provably cannot
    restart a pod (readiness failure → Running, READY 0/1, RESTARTS 0). **sre-runbooks**' chaos gate was looser
    than its own budget policy, and its freeze condition is now *root cause not understood*, not budget == 0.
  - **OWASP 2017 → 2025** in code-review-checklist (two editions stale: no SSRF, no supply chain, still listing
    XXE), and **security-scan** no longer reports *unchecked* as clean.
  - **experiment-loop** scored a perfect metric when the toolchain was deleted (`tsc … | grep error | wc -l`
    returns 0 when `tsc` is absent) — now gated on the build actually succeeding.
  - **multi-agent-orchestration**: the fork instruction was **inverted and silent**. Verified against the
    shipped `sdk-tools.d.ts`: omitting `subagent_type` does not fork the coordinator — it starts a
    general-purpose agent with a **fresh context**, losing the context sharing the section exists for, without
    ever erroring. Corrected, with `SendMessage` named as the real context-preserving mechanism.
  - **Two guards were reporting green on live defects.** The ci-cd guard anchored command detection at `^`, so
    a `curl` **indented inside a `run: |` block** — the normal YAML shape — was invisible to it; widened to
    `^\s*` and gap-tested. New guards now cover the browser-testing and ci-cd-templates repairs, which had none.
  - **The sweep shipped the repo red, and put a fail-open inside the check written to stop fail-opens.**
    Two defects found on review of the sweep itself, fixed here:
    - The new abort-dominance guard was correct and convicted `execute` and `investigate` — but shipped without
      repairing them, so `./validate.sh` exited 1 on its own tree. Both gates now carry the neutralizing clause
      `deep-analysis` and `diverge` already had. The guard was **not** narrowed to make it green.
    - `/optimize`'s new test gate defaulted `GUARD_RAN_RE` to `[0-9]+ (passed|…)`, which **matches the string
      "0 passed"** — a runner that collected zero tests and exited 0 read GREEN through the exact gate added to
      catch that. Pinned to `[1-9][0-9]*`, and a new guard now **executes** the shipped regex against
      `0 passed` / `0 passing` / `0 tests ran` / `0 ok` (must reject) and `12 passed` (must accept), so a guard
      that merely asserted the line exists can no longer pass over it. Gap-tested three ways: regex reverted →
      FAIL, line deleted → FAIL, unmodified → PASS.
  236 checks, 0 errors.

### Known open

Carried forward deliberately, not silently. Each is reproduced and located; none is a regression from this work:

- **ci-cd-templates** — blue/green cutover is an invalid `modify-listener` call (missing `Type` in
  `DefaultActions[0]`); smoke tests run before the async `create-deployment` completes; the canary job installs
  `kubectl` with no kubeconfig.
- **git-workflow** — `git diff REBASE_HEAD^ REBASE_HEAD` cannot measure "already applied upstream" (it is the
  commit's own patch); an unguarded `git branch --merged | xargs git branch -d` deletes branches this same skill
  marks permanent.
- **library-docs** — three of four worked examples return zero documentation (`/facebook/react` and
  `/tailwindlabs/tailwindcss` are bare redirects; the version-pinned ID form does not exist). The prose is right;
  the copyable examples are not.
- **docker-deployment** — the setup block pre-creates two of six bind-mount sources, so Docker creates
  *directories* named `nginx.conf` / `init-db.sql` and the stack fails stickily.
- **kubernetes-ops** — composing the shipped Deployment + HPA + Argo CD `selfHeal` templates causes permanent
  replica flapping; no `ignoreDifferences` anywhere.
- **ui-guidelines** — the antd static `message`/`notification`/`Modal.confirm` APIs cannot consume
  `ConfigProvider` context (this skill's central mandate) and `App.useApp()` is unmentioned; grid, router and
  CSS guidance contradict SKILL.md.
- **execute / agent-coordination.md / deployment-runbook / deep-analysis** — `agent-selection.md` calls itself
  complete while omitting 4 of 13 agents (security audit routes to a grep scanner instead of the Opus agent);
  `agent-coordination.md` still carries the three orchestration claims corrected in the skill; ten cited
  deployment scripts are neither shipped nor inline; `deep-analysis`'s reference file worked-example does the
  thing its own gate ABORTs.
- **The abort-dominance guard is asymmetric** — negation is matched as a synonym family, the invocation arm as a
  closed keyword list, so same-chunk laundering and paraphrase can still pass. It catches the literal shape it
  was built for, not an evader.

### Fixed

- **Round-3 P0: a git recipe that destroyed user work, three gates that passed on failure, and over-triggering
  fixed at the only layer that can fix it.** Each repair was proven by running the real tool against the doc's own
  text, with a negative control reproducing the original failure:
  - **`git-workflow` silently discarded the user's own commits.** `--ours`/`--theirs` **invert under rebase** —
    measured on git 2.50.1: under merge `--ours` is your work, under rebase `--ours` is the *upstream* — while the
    skill taught rebase-first with merge-only semantics. Following it mid-rebase resolved conflicts to upstream and
    threw away the replayed commits, leaving a clean-looking file and no warning. Added the merge-vs-rebase mapping
    (flags and `:2:`/`:3:` stages), a resolve-by-branch-name procedure, and guards on every unguarded destructive
    one-liner (`reset --hard`, `clean -fd`, `rebase --skip`, branch delete, force-push).
  - **`docker-deployment`'s compose healthcheck reported HEALTHY on a 503** — A/B'd against a container actually
    serving 503 (Engine 29.4.0): old probe → healthy, `curl -fsS … || exit 1` → unhealthy. `depends_on:
    service_healthy` had been releasing dependents against a dead API.
  - **`observability-stack`'s SLO alerts could not fire for a single-service outage.** Verified with real
    `promtool`: grouping `by (service)` alone still yields `got:[]` — the `or 0 *` padding is also load-bearing,
    because an all-5xx service has no numerator series. Also replaced the `loki` exporter, deleted from
    collector-contrib in v0.131.0, which took down the metrics and traces pipelines too (config resolution is
    all-or-nothing).
  - **`investigate` ran its fix phases unconsented when forked.** Phase 6's consent gate is unsatisfiable without
    AskUserQuestion; the contradiction is now closed at both ends — the rule that forbade stopping was amended, not
    just the gate.
  - **`skill-creator`'s placeholder gate was bypassable by renaming** the generated examples; detection is now
    content-based, plus the documented name/description constraints are enforced at scaffold time.
  - **`deployment-runbook` exit codes now discriminate**: `2` usage, `1` failed, `3` partial, `0` ok. A blue-green
    invocation that argparse rejected used to return the code the script documented as "everything that ran
    passed", and a *typo'd* `--check` was indistinguishable from a probe that ran and failed.
  - **Over-triggering fixed at the description layer.** Anthropic's docs are explicit that only `name` +
    `description` are pre-loaded and decide activation — SKILL.md is read only *after* selection — so every
    body-level entry gate written in earlier rounds was at the wrong layer. Eight descriptions rewritten (third
    person, what + specifically when, heavyweight skills stating the narrow conditions that warrant them), and the
    four body lines that then contradicted their own new description were corrected.

### Fixed

- **Retiring a skill left it live — a hole the retirement itself exposed.** Deleting `api-guidelines` from the
  repo did **not** remove it from `~/.claude/skills`: the skills orphan-prune is deliberately scoped to names the
  framework *currently* ships (so it can never touch the user's own skills), which means a **deleted** framework
  skill becomes indistinguishable from a personal one and lingers forever — still auto-activating in every
  project — while `validate.sh` reported 0 errors. Fixed with the same fail-closed shape `lib` already used:
  a `RETIRED_SKILLS` allowlist plus `prune_retired_skills()`, which refuses to act on any name still shipped in
  source (deleting a live skill is worse than leaving a stale one). A new validate guard asserts no retired skill
  remains in the live install. Verified: the guard failed while the skill was live, the prune removed it, the
  guard went green, and 41 of 42 live skills survived — exactly one removed, personal skills untouched. Safety
  gap-tested by listing a still-shipped skill as retired: refused, not deleted, and validate flagged the bad list.

### Removed

- **`api-guidelines` retired from the framework** (maintainer decision; recoverable from git history at
  `d0b9adf`). It was 931 lines installed **user-globally** — so it loaded for every matching repo on the
  machine — while being welded to a single private application: 11 imports from that app's private module graph
  (`@/lib/auth/wrappers`, `@/constants/permissions`, `@/lib/db`) and **7 references to a MariaDB MCP server this
  framework has never shipped**, on a step the skill marked MANDATORY. Its Standard Endpoint Template also leaked
  `error.message` at HTTP 500, contradicting the skill's own guidance and the framework's security rule. Two
  independent audit rounds rated it BROKEN/RETIRE. Skills 28 → 27; counts updated in CLAUDE.md, README (badge,
  table, prose), INSTALL.md and EXTENSIBILITY.md, with the doc-accuracy guard confirming 27 = 27.
  If the host application still wants this content, it belongs in that repo — not in a user-global install.

### Fixed

- **Round-2 P0: two skills that certified failure as success, plus the guards that certified themselves.**
  A blind re-test (testers shown no prior findings) then independent reconciliation confirmed round 1 was
  *under*-called, not inflated — one over-report in 28. Repaired, each verified by execution:
  - **`browser-testing` was certifying a failed login as a passing E2E.** `playwright_assert_response` was
    called with no `value`, and the server's own source shows the call then falls straight through to
    `createSuccessResponse` — printing a 401's status without ever comparing it. Both call sites now assert a
    success-only value; `expect_response` moved *before* its triggering click (it only waits from the moment it
    is registered); all 59 bare `playwright_*` names prefixed to `mcp__playwright__*` (verified against the
    installed server: every one of the 30 tools referenced exists); the phantom screenshot "comparison" now
    names a real comparator with a threshold and treats a missing baseline or an un-run comparator as FAIL.
  - **`ci-cd-templates`**: semgrep ran without `--error` (exit 0 with findings present) and emitted the wrong
    report schema; the registry push used an unqualified image name; `snyk/actions@master` was unpinned;
    codecov's `fail_ci_if_error` was unset; and both deploy webhooks used `curl` with no `--fail`, so a failing
    deploy call returned success. The unbacked CircleCI claim was removed from the skill and from CLAUDE.md.
  - **`health_check.py` partial runs lied**: `--check api` against a reachable endpoint printed “ALL CHECKS
    PASSED” and exited 0 after running one of five probes. Partial runs now exit `EXIT_PARTIAL`.
  - **`quick_validate.py`** regex-scraped frontmatter instead of parsing it, so a description containing a colon
    was mis-read by the gate that mints every future skill; it now uses `yaml.safe_load` and fails closed on
    malformed YAML. An unbalanced code fence used to silently abort the body scan — that now fails too. And
    `init_skill.py` emitted an *unquoted* `[TODO: …]`, which YAML reads as a list, so scaffolded skills failed
    with “must be text, got list” instead of naming the placeholder; it is quoted now.
  - **`deep-read` / `investigate` were forked yet instructed fork-unavailable capabilities** (AskUserQuestion,
    Explore agents) — their own enforcement was dead text. Scope narrowing is now deterministic in-fork, the
    displaced instruction in `references/reading-strategies.md` is corrected, and an off-by-one (“keep the top
    50” against a strict `< 50` gate) is reconciled.
- **Three guards that certified themselves green — found by review, fixed before commit.** The health guard
  asserted `main()`'s **return value**, so a `__main__` wrapper changed to `sys.exit(0)` would keep it passing;
  it now measures the **process** exit code via subprocess, and asserts the *specific* `EXIT_PARTIAL` rather
  than “non-zero” (a merely failed probe is also non-zero). While fixing it, a bug in the guard's own fixture
  surfaced: it patched only the first `api_url`, and since `production` is declared before `staging` the probe
  was hitting an unreachable host — so the guard had been passing on a **failed** run, not a partial one. The
  fork/spawn guard had three holes: a file-wide caveat amnesty (one boilerplate sentence exempted every later
  violation), `context: "fork"` silently unscanned, and no detection of “Task tool”. All closed — and the
  strengthened guard immediately caught a live instance in `investigate` that the amnesty had been hiding.
  229 checks; every guard gap-tested by reintroducing its bug.

### Added

- **Fail-open regression guards — the P0 fixes are now enforced, not just applied.** A gap analysis found that
  **7 of the 8** repaired gates had **no** validate coverage: reverting any of them left `validate.sh` reporting a
  clean 223/0, because it never executed a skill artifact and only checked file identity (which happily copies a
  regression to `~/.claude` and calls it synced). Four FULL-only guards now assert the **invariant by running the
  artifact**, not by grepping for a magic word — the proxy-guard anti-pattern that previously let four dead
  context7 params pass:
  - `health_check.py`'s unimplemented probes must exit non-zero (a deploy gate that cannot fail is the defect).
  - `quick_validate.py` must reject a `[TODO]` placeholder **and** still accept a real skill — two-sided, because a
    validator that rejects everything is as broken as one that accepts everything.
  - every recording rule an `observability-stack` alert references must be defined in the same file (an undefined
    rule makes the alert an empty vector: never fires, logs nothing).
  - no skill may advertise a `## Resources` file that does not exist.
  Each was **gap-tested by reintroducing the bug** (unconditional `return True`; a neutered placeholder check that
  still compiles; a deleted recording rule; a phantom resource) and each fired with the correct message, then went
  green on restore. 223 → **227 checks**.

### Fixed

- **Two defects the independent P0 re-verification caught — including one the P0 fix itself introduced.**
  (a) `api-contract-testing`'s validation example enforced **nothing**: the spec declares
  `servers: https://api.example.com/v1`, so express-openapi-validator derives basePath `/v1`, while the app
  mounted bare `/users` — no route matched, so a request missing a required field returned **201** instead of 400
  (reproduced on express 5.2.1 / eov 5.6.2: 2 of 4 tests failed; the same app under `/v1` returns the asserted
  400/500). Routes and requests now use `/v1`, with a comment explaining where basePath comes from.
  (b) **The P0 `scheduled-tasks` correction over-shot.** Calling `durable` a *fabricated* API was wrong — the
  parameter is real and the CLI ships an implementation behind the `tengu_kairos_cron_durable` gate. Replacing it
  with the absolutes "there is no durable cron and no on-disk task store" / "session-only is absolute" swapped one
  false claim for another. Now stated as the gate-conditional truth, anchored to what the live schema actually
  says (`durable`: "has no effect" while the gate is off) with the practical guidance unchanged: don't promise
  persistence — use `RemoteTrigger` if it must outlive the session. Verified against the live `CronCreate` schema.
- **Residue from the P0 batch and the audit's B-list.** `deployment-runbook` advertised three resource files it
  never shipped — and pointed a database-failure procedure at one of them, one line from a script that does exist
  (a dead end mid-incident); the phantom entries are gone and the procedure now calls the real script.
  `infrastructure-as-code`'s production job ran `apply -auto-approve` with **no plan file**, so what executed was
  never what anyone reviewed — it now plans and applies the same plan in one job, with the stronger
  artifact-based option documented. `api-contract-testing` imported `express`/`supertest` with no install line
  (guaranteed `Cannot find module` on first run). `observability-stack` advised `interval: 1m` while its own rule
  group omitted it; `docker-deployment` kept the obsolete Compose `version:` key. Also added the SHA citations
  missing from the `[Unreleased]` entries — this repo's own self-named recurring audit gap, recurring.

- **P0: eight gates that could not fail** (`77a6199`) — a 28-skill stress test (5 defect classes, trap scenarios, independent
  adversarial review) found that the two bugs fixed earlier were systemic, and that the most dangerous class was
  verification that always reports success. Repaired, each with executable evidence:
  - `deployment-runbook/scripts/health_check.py` — **four** probes (database, cache, external services, and a
    metrics check comparing hard-coded constants) were unconditional passes shipped as a deploy gate. All now
    **fail closed** with an actionable "NOT IMPLEMENTED — implement before using as a gate" message; the
    teaching snippets are kept. Verified: `--check database` now exits 1.
  - `skill-creator/scripts/quick_validate.py` — advertised four checks, performed two, and green-lit a literal
    `[TODO: …]` description. Placeholder/short descriptions and body-less skills now fail; verified against a
    placeholder fixture (exit 1) with no false positive on real skills (git-workflow / deep-read / security-scan
    all exit 0).
  - `observability-stack` — three multi-window burn-rate alerts referenced **four recording rules that were never
    defined**, so PromQL's empty-vector AND made them permanently un-fireable with no error logged. All four
    windows (30m/1h/6h/3d) are now defined; verified zero dangling `sli:*` references.
  - `api-contract-testing` — the regression test passed when a schema was **deleted** and when a **required field
    was added** (the two most common breaking changes), and the flagship validation test never booted an app. Both
    fixed, plus a sibling test that the reviewer caught still passing vacuously on an empty spec.
  - `infrastructure-as-code` — the reference CD `apply` job could never run under either trigger, and the policy
    gate errored instead of enforcing (`opa eval -i` takes a file path, not stdin). Both corrected.
  - `scheduled-tasks` / `remote-triggers` — **fabricated APIs removed**: a `durable: true` option and a
    `~/.claude/scheduled_tasks.json` persistence store that do not exist, and a create body whose field names
    meant the primary documented operation could not succeed. Both rewritten against the live tool schemas.
  - `docker-deployment` — the Python image installed packages as root into `/root/.local` then switched to a
    non-root user that could not read them (container could not start); the Next.js example omitted its
    `output: 'standalone'` prerequisite; the compose template shipped a plaintext password and no resource limits,
    violating the skill's own checklist. All three fixed and proven against a real Docker daemon.
  - `library-docs` + `validate.sh` — the earlier context7 repair corrected tool **names** but left dead
    `topic`/`tokens`/`context7CompatibleLibraryID` **parameter** references, and the guard added alongside it
    grepped a single literal string, so it reported PASS over the residue. Residue removed and the guard widened
    to the parameter names — gap-tested (re-injecting a dead param fails validate; removing it passes).
  Independent review overrode the fixers in three places (a measured `docker compose config` regression, an
  unswept sibling test, and a doc left contradicting its own repaired script), all closed before commit.

### Changed

- **`deep-read` skill gained code-graph awareness** (`dec3d9d`, hardened `ee636f5`) — merging the CodeGraphContext/mex evaluations' *principle*
  into an existing skill instead of adding a new one (skills stay 28). Short guidance woven into the phases where
  a code graph genuinely accelerates: **MAP** (structure + centrality in one query vs grepping imports), **TRACE**
  (LSP one-hop + whole-repo *transitive* / *cross-language* chains that grep and per-language LSP miss), **CONNECT**
  (aggregate queries — dead code, all-implementers-of-X, blast-radius) — plus one decision heuristic (a per-repo
  graph earns its one-time setup only on large/unfamiliar/cross-language repos doing whole-repo/aggregate work;
  otherwise LSP + Grep + Read). **Tool-agnostic** (CodeGraphContext/`cgc` named once as an example, not
  shipped/registered — INVOKE an existing index, RECOMMEND building one in the report, never bootstrap silently),
  and the "source is truth" invariant is **extended, not weakened**: a graph/LSP hit is a possibly-stale snapshot,
  verified against live source before citing. ~7 net lines, no new H2; `mcp-guide.md` gained a one-line code-graph
  pointer. No version bump (skill enhancement). **Behaviorally tested** (independent subagent, 4 scenarios incl. a targeted-cross-language trap): the first pass found a real over-reach path — the per-phase MAP/TRACE mentions used looser OR conditions than the governing rule — fixed by making both defer to an explicit **two-gate AND** (large-or-multi-language AND whole-repo/aggregate; one gate alone → LSP/Grep/Read). Re-test confirmed the trap routes to LSP with no over-correction on genuine blast-radius.

### Fixed

- **library-docs skill referenced a nonexistent context7 tool** (`9fee8ed`; found by evaluating CodeGraphContext as a
  proposed context7 replacement — a **category error**: CGC graphs *your own* code, context7 fetches *library*
  docs, so CGC was NOT adopted). The skill, `.claude/lib/mcp-guide.md`, and `EXTENSIBILITY.md` documented
  `mcp__context7__get-library-docs` (9 refs) with params `context7CompatibleLibraryID`/`topic`/`tokens` — but the
  current `@upstash/context7-mcp` exposes `resolve-library-id({libraryName, query})` + `query-docs({libraryId,
  query})`; `get-library-docs` no longer exists, so the examples would fail if followed. Fixed every reference +
  params, corrected the wrong package name (`@context7/mcp-server` → `@upstash/context7-mcp`), added a
  WebFetch/WebSearch **fallback** clause, and documented context7's free-tier cap (~1,000 req/mo — still ample on
  demand; it is freemium, **not** paid, and does not bind our usage). `validate.sh` gained a doc-accuracy guard
  that fails if the removed `get-library-docs` name reappears (the tool-name analogue of the count-drift check —
  this slipped through because validate only checked MCP *server presence*, not tool names). 223 checks.

## [3.1.1] - 2026-08-02

### Changed

- **Self-Healing runbook split out of the always-loaded CLAUDE.md → new top-level `SELF-HEALING.md`** (context
  economy — surfaced by evaluating `mex-memory/mex`, whose thesis "a giant instruction file floods context, goes
  stale, drifts from code" measured true here: the Self-Healing section alone was ~40% of CLAUDE.md, loaded every
  session). The full runbook (watchdog cadence/retention, settings-sync-wipe recovery, `--upgrade` consent flow,
  `.attribution` auto-heal, statusline glyph states, diagnostic-log capping, and every snapshot-restore command)
  moved to `SELF-HEALING.md` (not on any Claude Code auto-load path); CLAUDE.md keeps a compact summary + a
  `[SELF-HEALING.md](./SELF-HEALING.md)` pointer so a session still knows self-heal exists and where the runbook is
  without paying for the detail every session. `validate.sh` gained guards that SELF-HEALING.md exists, retains the
  restore commands, and is still linked from CLAUDE.md (the moved runbook can't silently vanish); SECURITY.md's
  restore-path reference repointed. Verified: the memory-restore-path invariant + all doc-accuracy checks stay
  green (222 checks); gap-injecting a missing SELF-HEALING.md fails as designed. Also linked from INSTALL.md ("Update & migrate") and CONTRIBUTING.md ("Self-healing safety net") so the runbook is discoverable from the README→INSTALL chain, not only CLAUDE.md/SECURITY.md.
- **Version → 3.1.1** (`SCRIPT_VERSION`, README badge, EXTENSIBILITY footer): v3.1.0 was tagged/released at
  `b70abe4`, and the three fixes below shipped on `main` above that tag — so the `~/.claude/.framework-version`
  marker, the README badge, and the statusline `⚙<version>` glyph were advertising 3.1.0 while the deployed
  framework differed. This closes the tag↔HEAD gap.

### Fixed

- **Watchdog now caps the append-only diagnostic logs** (`framework-health.jsonl` was unbounded — ~3.8k lines /
  3.3 MB, growing ~50 lines/day with no rotation): a new `trim_jsonl` helper trims `framework-health.jsonl` to the
  last 1000 lines and `watchdog-alerts.jsonl` to 500 at the end of every hourly cycle (atomic tail → temp → mv,
  keeps the newest lines). Safe because the statusline only `tail`-reads these logs and nothing ingests them into
  a DB. `validate.sh` gained a regression guard (`trim_jsonl` present in the watchdog source). Verified: a real
  watchdog run capped the live log 3849 → 1000 with the newest event intact and the statusline still rendering.
- **`install.sh --update`/`--upgrade` now re-deploy a drifted `statusline.sh`** (regression exposed by the
  f2905b9 deployed==source check): `ensure_statusline` was install-only ("never overwrites"), so once the source
  statusline changed, the heal path (`install.sh --update`) could never satisfy the new validate assertion — the
  watchdog looped hourly (**25 heal_failed, never converging**) while the machine was otherwise healthy.
  `ensure_statusline` is now **replace-on-drift** (cp when absent or `diff -q` differs, skip when byte-identical),
  using the same `diff -q` the validator uses so "skip" == "pass"; one change heals all three call sites
  (install / `--update` / `--upgrade`). Verified: `--update` reconciles a planted drift (validate 1→0).
- **Statusline health glyph now recovers after a resolved incident**: the `⚙<ver> <glyph>` logic latched `⚠`/`⟳`
  on the most recent `heal_`/alert event without checking whether a newer clean `validate_quick` had superseded
  it, so a *fixed* heal incident held the bar `⚠` red for up to 24h (a `heal_failed` in `watchdog-alerts.jsonl`
  "trumps everything" for 24h). The glyph now anchors to the epoch of the latest **clean** `validate_quick` and
  only latches `heal_`/alert events newer than it; a transient `heal_failed` clears once a passing validate
  supersedes it, while genuine (non-`heal_failed`) corruption alerts still trump for 24h. Verified across 6
  scenarios (resolved → ✓; unresolved / in-flight / failing / real-corruption still warn).
- **validate.sh now checks doc-ACCURACY, not just file-identity** (surfaced by evaluating `mex-memory/mex`, which
  correctly diagnosed that our drift detection guarded `deployed==source` file identity but never whether the docs'
  stated counts match the code — the blind spot behind the self-admitted "CHANGELOG lag is THE recurring audit
  finding"): a new **full-only** check counts actual agents/skills/hook-scripts/MCP-servers and FAILS if CLAUDE.md's
  prose numbers disagree. Full-only by design — a count mismatch can't be auto-healed (install can't rewrite prose),
  so running it in `--quick` would loop the watchdog; it fails on `./validate.sh` at commit time, exactly when the
  drift is introduced. Verified: passes on current counts (13 agents / 28 skills / 9 hook scripts / 4 MCP), stays
  absent from `--quick`, and a gap-injected 13→14 agent count fails then restores clean (219 checks full).

## [3.1.0] - 2026-07-07

### Added

- **Autonomous cross-system self-migration** (opt-in, no auto-pull): after a deliberate `git pull` on any
  machine, the framework finishes its own migration to user-global with no further manual steps. The existing
  self-heal path (SessionStart healthcheck / launchd watchdog fork `install.sh --update`) now also runs a
  guardrailed teardown of old per-project copies.
  - `reconcile_legacy_projects()` in `install.sh --update`: gated behind an explicit per-machine marker
    `~/.claude/.framework-autonomy` (`LEGACY_PROJECTS_DIR=<dir>`). For each project under that dir carrying a
    per-project framework `.claude/agents`, it removes ONLY the framework shared-set subdirs, and ONLY when
    git-**untracked** (never rewrites a repo's history). Framework-scoped, **snapshot-first**, idempotent (no-op
    + no snapshot once torn down). **Absent marker → no-op** — public users and fresh installs are unaffected,
    and there is deliberately **no auto-pull** (`git pull` stays the one manual trigger).
  - **Autonomous scheduling**: the launchd watchdog runs a fast, teardown-only mode
    (`install.sh --migrate-legacy`) **every cycle**, so a newly-set marker triggers the teardown within the
    hour — independent of shared-set drift (the heal path only fires on validate errors). Manual immediate
    trigger: `install.sh --migrate-legacy`.
  - **Watchdog plist self-reload**: `install_watchdog` now sha-tracks the loaded plist and reloads the daemon on
    a real plist change, **deferring** the reload when running under the watchdog's own `--update` (avoids a
    self-kill; the next SessionStart-triggered `--update` applies it). The watchdog script already self-updated
    via launchd re-exec.
- **Framework status in the statusline**: `statusline.sh` now renders a compact `⚙<version> <glyph>` segment at
  the end of line 1 — `✓` healthy, `⟳` self-healing in progress, `⚠` watchdog stalled / heal failed / recent
  corruption (within 24h). It reads only the framework's own cheap artifacts (`.framework-version` plus the
  watchdog/healthcheck `framework-health.jsonl` / `watchdog-alerts.jsonl` diagnostic stream) — it **never runs a
  live validation in the hot path**, caches the result for 60s (like the existing git segment), and emits nothing
  when the framework isn't installed (plain Claude Code users are unaffected). A `validate.sh` regression guard
  asserts the segment survives reconciles.
- **`install.sh --upgrade` — one-command migration from the old per-project framework** (designed + de-risked with
  a multi-agent workflow pre-mortem; the teardown-safety and `.attribution` fixes below came out of the same
  review). Reconciles `~/.claude` to the latest, then detects old per-project `.claude/` copies, shows a **count +
  the candidate list**, asks **one confirmation**, does a snapshot-first framework-scoped teardown, and
  self-verifies (`validate.sh --quick`). Safety by construction: teardown runs ONLY past a shown-count
  confirmation — an explicit `--yes` / `CLAUDE_UPGRADE_ASSUME_YES=1`, or a typed `y` at the **controlling
  terminal** read via a dedicated fd bound to `/dev/tty` (never stdin, so a piped `curl|bash` stdin can't be
  misread as consent; `[ -t 0 ]` is deliberately NOT the interactivity test — it reads false under `curl|bash`
  even at a real terminal). No terminal + no explicit consent → **fail-closed skip** (exit 0) with the exact
  re-run one-liner. The scan dir comes from the `.framework-autonomy` marker if armed, else a `/dev/tty` prompt
  that **refuses `$HOME`** and non-directories. Self-verify is observe-only (never `--heal`) with an honest
  tri-state (green / measured non-zero / UNVERIFIED). Bare install, `--update`, and the autonomous no-arg teardown
  are **byte-identical** — the parameterized `reconcile_legacy_projects` returns 0 for no-arg callers (the `set -e`
  exit-code contract the self-heal loop depends on). Concurrency-locked against the watchdog; bare install now
  hints `--upgrade`. Verified: no-arg exits 0 and tears down silently; `--upgrade --yes` shows count+list, removes
  untracked, skips committed, snapshots; non-interactive-no-consent skips with the one-liner. (This is a MANUAL,
  checkout-local command — `curl|bash` derives its mode from checkout presence and can't pass `--upgrade`; see
  INSTALL.md.)

### Fixed

- **Autonomous legacy teardown is now framework-scoped** (`de82069`): `reconcile_legacy_projects()` removes only
  the framework's OWN files (agents/skills/commands/rules/lib, enumerated by name from source) from an untracked
  project — never a project's own custom agents/skills, even uncommitted ones — then `rmdir`s the emptied
  framework subdirs. A project qualifies for teardown only if it actually holds a framework-owned agent file, so a
  custom-only project is never a candidate (no snapshot spam, stays idempotent). Previously the whole
  `agents/skills/...` subdirs were deleted, which could drop uncommitted custom content. Verified in a sandbox:
  framework files removed while a custom agent + custom skill survive; committed / git-error / snapshot-fail
  guardrails intact; custom-only untouched; re-run makes no new snapshot.
- **`observability/collector.py` cost model refreshed**: added the current model IDs (`claude-opus-4-8`,
  `claude-sonnet-5`, `claude-fable-5`, plus the `claude-haiku-4-5` alias) so per-session cost estimates stop
  falling back to Sonnet pricing with an "unknown model" warning. Corrected two stale rows — the Opus tier is now
  $5/$25 input/output (the `claude-opus-4-6` entry was 3× high at $15/$75), and Haiku 4.5 is $1/$5 (was $0.8/$4).
  Cache read/create derived from the standard 0.1× / 1.25× (5-min TTL) multipliers.
- **Removed the deprecated Postgres MCP server** from `.mcp.json.example` (and the `global-config/` copy) and from
  the README: `@modelcontextprotocol/server-postgres` is marked "no longer supported" on npm (frozen at 0.6.2).
  The MCP badge/table now read **4 servers** (context7, sequential-thinking, playwright, github), and the MCP
  section no longer claims the servers are "auto-configured on install" — `install.sh` ships the example config
  but does not register any MCP server (users add them manually). Added a Requirements line and an INSTALL.md link
  to the README.
- **`sync_hooks` now reverse-prunes stale hook EVENT bindings, and `validate.sh` detects them**: the hook
  reconcile added/repaired every event the template *has* but never removed one the template *dropped*. A stale
  event still bound to a framework hook script (e.g. `Stop → session-end.sh`, left over after `session-end.sh`
  moved from `Stop` to `SessionEnd`) survived `install --update` forever and **double-fired the script every turn**,
  over-logging `session-summaries.jsonl`. `sync_hooks` now reverse-prunes such off-template events
  **framework-scoped** — only when the bound command is one of this framework's own hook scripts, so a user's own
  off-template hook is left untouched — mirroring the existing hook-FILE orphan prune (files were pruned; event
  keys weren't). `validate.sh` gained the matching assertion that fails on any off-template event still running a
  framework hook (previously it checked template-events-present but not dropped-events-absent, so it passed 210/0
  with the double-bind live). Verified by gap-injection: a stale `Stop → session-end.sh` makes validate fail,
  `--update` prunes it surgically (settings otherwise byte-identical), validate goes green; a user's own
  `Stop → ~/bin/my-hook.sh` is preserved. Found on the sister machine (it carried the stale binding); the mini was
  clean only because a prior `settings.json` wipe had rebuilt it from the `Stop`-less template.
- **Statusline deploy-drift check + no transient `⚠` right after install** (follow-ups to the statusline
  feature, from the sister machine's adversarial review): (1) `validate.sh` now also asserts the **deployed**
  `~/.claude/statusline.sh` matches source — the earlier guard only grepped the source file, so a skipped/failed
  deploy would drop the segment from the LIVE bar undetected (mirrors the analytics-drift check; inject-tested to
  fail on drift, pass when synced). (2) `install.sh` now kickstarts the watchdog after a load/reload AND stamps a
  fresh `install_reconciled` health event + drops the statusline's 60s cache, so the freshness check is satisfied
  immediately — previously a reload reset the watchdog's hourly timer and the bar showed a transient `⚠` (stale)
  after a successful install (the kickstarted watchdog logs too, but async and behind the cache). Both are guarded
  against the watchdog's own `--update` (`CLAUDE_WATCHDOG_RUN`).
- **Teardown safety hardening — committed-guard now covers all five subdirs, plus symlink guards** (found by an
  adversarial pre-mortem of the autonomy teardown before building the upgrade flow): `reconcile_legacy_projects`
  removes framework-named files from `agents/skills/commands/rules/lib`, but the git committed-guard only proved
  `.claude/agents` was untracked — so a repo that **committed** e.g. `.claude/rules/code-quality.md` (a framework
  *name*) while leaving `.claude/agents` untracked could reach teardown and have **tracked files `rm`'d** from its
  working tree. The guard now requires **every existing subdir** to be git-untracked (any tracked/indeterminate
  subdir → skip the whole project). Added **symlink guards**: a project whose `.claude` or any framework subdir is
  a symlink is skipped, so `rm -f` can never follow it into a shared/committed target (the prior guard only
  skipped a symlinked project *dir*). Verified: a mixed-tracking repo (agents untracked, rules committed) is
  skipped with the committed file intact; a symlinked subdir is skipped with its target intact; a clean
  fully-untracked copy still tears down; the no-arg autonomous path still exits 0.
- **`.attribution` auto-heals on install/`--update`, and validate checks LIVE settings** (so old-framework
  users' `Co-Authored-By` commit trailer scrubs automatically — no more hand-fixing, as the sister machine had to
  do during its sync): `sync_hooks` now reconciles `.attribution` with the same replace-on-drift policy as
  `.permissions`/`.statusLine` — a stale AI-attribution commit trailer in the live `~/.claude/settings.json` (from
  an old per-project install or a CLI settings-sync payload) is healed to the template's `commit=""` and the
  template `.pr` footer is restored, in one atomic whole-block replace. `validate.sh --quick` gained a matching
  **live-settings** assertion (`.attribution.commit` empty) — the prior check only guarded the source template, so
  a failed/absent heal was invisible to the watchdog and to `--upgrade`'s self-verify. Runs on the shared path
  (bare install, `--update`, `--upgrade`); a user wanting a custom PR footer uses `settings.local.json` (higher
  precedence), the same note the permissions block carries. Verified: an injected trailer fails `validate --quick`,
  heals on `--update` to `commit=""` + template `.pr`, passes validate, and a 2nd back-to-back `--update` writes
  nothing (converges to a no-op — preserving the byte-identical self-heal contract).
- **Statusline `⚙<ver> ⚠` false positive on non-UTC machines** (reported as `⚙3.1.0 ⚠` on a UTC+1 machine, framework
  fully healthy): the freshness check's `_iso_epoch` used macOS `date -j -f '…Z'`, which **ignores the trailing
  `Z` and parses the UTC health timestamp as LOCAL time** — inflating every age by the local UTC offset (UTC+1 →
  +60 min), so the glyph flipped to `⚠` for the back half of every hourly watchdog cycle even with validate at 0
  errors and the watchdog alive. Fixed by parsing as UTC (`date -j -u -f` on macOS; `date -u -d` on GNU — epoch is
  timezone-absolute; the corruption-window check shares `_iso_epoch` and is corrected too), and widened the
  staleness threshold 90 → 150 min (2.5× the 60-min cadence) so normal jitter / one missed cycle never trips it
  while a genuinely stalled watchdog still surfaces within ~2.5h. Verified: the real machine renders `✓`; seeded
  fresh/45-min → ✓, 3h-stale → ⚠, recent corruption → ⚠ (genuine states preserved).
- **Docs accuracy sync (post-session multi-agent audit)**: brought CLAUDE.md, README.md, INSTALL.md, and
  EXTENSIBILITY.md in line with this release. CLAUDE.md now documents the `--upgrade` mode, the `.attribution`
  auto-heal, the statusline framework-status glyph, the all-five-subdir teardown committed-guard, and the
  4-MCP-server count; INSTALL.md's Commands table gained `--upgrade` + `--migrate-legacy` rows and its `lib/`
  line dropped the stale "Activation patterns" (activation-keywords.json was removed earlier); README + INSTALL
  statusline lines note the framework-status glyph; EXTENSIBILITY.md's footer version was corrected 3.0.0 → 3.1.0.
  Surfaced by a workflow that audited every doc surface against shipped reality (the confirmed-correct MCP badge,
  README `--upgrade` row, and INSTALL `--upgrade` section were left untouched).
## [3.0.0] - 2026-07-07

Outcome of a framework self-review (reversibility-ordered revamp). Phases 1–4 shipped the
low-regret cleanup; Phase 5 migrated the framework to a **user-global install** (goal resolved to
leverage-per-effort; a single public product) and repositioned it as a public tool.

### Changed

- **User-global install** (`install.sh` ~1900→~1023 LOC): the framework now installs ONCE into
  `~/.claude` — Claude Code loads `~/.claude/{agents,skills,commands,rules}` in every project — instead of
  copying into each project's `.claude/`. New `install_shared_set` REPLACE-copies the framework's own files
  with a **framework-scoped orphan-prune** that provably never removes a user's personal skills/agents
  (prune eligibility is limited to names the framework itself ships). Bare `install.sh` is the canonical
  install; `--update` reconciles `~/.claude` non-interactively under the concurrency lock (the self-heal
  path). Deleted ~840 LOC of per-project machinery (`detect_*`, the 5 `patch_*_in_claude_md`, CLAUDE.md
  emission, backup rotation, interactive menu, per-project markers).
- **Self-heal now covers the shared set**: SessionStart healthcheck Check 7 (agents/skills/commands/rules
  sha256 vs source → heal) plus a `validate.sh --quick` shared-set sync check, so the launchd watchdog
  heals shared-set drift too.
- **Public repositioning**: `README.md`/`INSTALL.md` rewritten from "deploy to each project" to "install
  once, user-global"; `quick-install.sh` is now a `curl … | bash` wrapper delegating to `install.sh`;
  retired the per-project seed fragments (`CLAUDE-DEPLOYMENT.md`, `CLAUDE-minimal.md`,
  `CLAUDE-append-section.md`, `CLAUDE-ultra-minimal.md`, `install-claude-config.sh`).
- **Removed the multi-project fan-out**: deleted `deploy-all.sh` and the per-project deploy-integrity md5
  manifest in `validate.sh` (obsolete under a single install).
- **Scrubbed personal/employer leakage** from the public repo (employer name, a private internal repo,
  `~/local-codebase` paths, project counts, two-Mac framing) across `CHANGELOG.md`/`CLAUDE.md`/
  `CONTRIBUTING.md`/`SECURITY.md`/`validate.sh`.
- **Post-migration currency sweep**: removed the last stale per-project references (`CONTRIBUTING.md`'s
  `--full /path` test flow + "deployed projects" wording, `global-config/README.md`'s `--team-setup`
  framing, the `.gitignore` per-project-marker comment) and repointed `meta-agent`'s lib reads to
  `~/.claude/lib`.

### Added

- **Per-skill observability** (`c262cef`): new `skill_activations` table plus a `Skill`-tool
  branch in `observability/collector.py` (mirrors the existing Task/Agent capture, reads
  `input.skill`). Skill usage was aggregate-only (`tool_usage` counted the `Skill` tool, not
  which skill), so skill pruning could not be data-backed the way agent pruning is. Retroactive
  via `collector.py --full` (backfill verified: deep-read 15, deep-analysis 8, diverge 4, …).
- **Generalized inert-config lint** (`a21d037`): `validate.sh` now fails on any
  `confidence_threshold` / `keyword_weights` / `activation_rules` / `priority_override` key in
  `.claude/lib/*.json`. The framework has no scoring runtime (Claude Code routes on description
  text only), so such keys are always dead. Scoped to structured config, never skill/rule prose;
  gap-injection tested.
- **Attribution invariant** (`daa2341`): `validate.sh` asserts `settings.json.template`
  `attribution.commit` stays empty, tying the no-AI-trailer rule to config so the two surfaces
  cannot silently diverge.
- **lib-orphan reverse-prune** (`44c82fa`): `install.sh` now reverse-prunes retired framework
  lib files (`RETIRED_LIB_FILES`) instead of only copying forward.

### Fixed

- **AI co-author trailer removed** (`daa2341`): `attribution.commit` shipped a
  `Co-Authored-By: Claude` trailer, contradicting the maintainer's no-AI-trailer rule (and the
  mechanism behind `44c82fa`'s stray trailer). Emptied in the template **and** jq-patched into the
  live `~/.claude/settings.json` — `install.sh` copies the template only when the file is absent,
  so a template edit alone is a no-op on existing machines. `attribution.pr` (PR footer) kept.
- **Currency follow-ups** (`435cc20`, `b66c7b4`): finished the `Task`→`Agent` rename in skill
  prose + README doc links to code.claude.com; tightened the meta-agent scaffolding lint so it no
  longer matches its own corrective prose; corrected the expected hook event to `SessionEnd`.

### Removed

- **Dead `activation_rules` scoring block** (`a21d037`): removed the consumer-less
  `confidence_threshold` / `keyword_weights` / `priority_override` block from
  `.claude/lib/agent-templates.json` — the same dead-scoring pattern as the removed
  `activation-keywords.json` (`0b343bb`), hiding in a file the old lint never scanned.

### Notes

- Agents `incident-commander` + `sre-specialist` KEPT as contingency insurance: their 0 recorded
  spawns reflect that the incident-response/SRE domains never arose in this dev work, not a defect.

## [2.10.0] - 2026-05-29

### Added

- **anti-anchoring rule** (`.claude/rules/anti-anchoring.md`): always-on
  divergence habit — name the obvious pick + one non-obvious alternative + one
  trap on every open-ended judgment call; exempts closed/factual work; escalates
  consequential open decisions to `/diverge`.
- **/diverge skill** (`.claude/skills/diverge/SKILL.md`): divergence engine that
  spawns isolated parallel sub-agents under cognitive frames (no cross-anchoring),
  then a separate critic pass scores / flags traps / clusters / deepens. Built on
  the framework's own Task primitives (no npm dependency). The divergent
  complement to `/deep-analysis`, gated by consequence × openness.
- **De-anchoring step** in the 7 open-ended agents (architecture-planner,
  database-architect, devops-automation, frontend-specialist,
  performance-optimizer, sre-specialist, meta-agent) — each names a domain
  obvious/alternative/trap and points to `/diverge` for high-stakes choices.
- **Pre-flight self-gates** on `/execute`, `/investigate`, `/deep-analysis`
  (consequence/complexity-aware "when NOT to invoke" gates).
- **Divergence activation keywords** in `.claude/lib/activation-keywords.json`.
- **validate.sh invariants**: hard-fail if any of the 7 open-ended agents lacks
  the de-anchoring step, or any of the 4 expensive skills lacks a pre-flight gate.
- **install.sh**: `patch_diverge_in_claude_md` (idempotent, dual-format) plus
  `/diverge` in all three CLAUDE.md emitters, so fresh and existing deployments
  both learn the skill.

### Removed

- **Dead `activation-keywords.json` router** (`0b343bb`): removed
  `.claude/lib/activation-keywords.json`. Its `confidence_scoring` weights,
  `thresholds`, and `multi_agent_triggers` "router" were never wired into any
  code path — exhaustive grep confirmed install.sh/quick-install.sh only *copied*
  the file, validate.sh only *existence-checked* it, and `meta-agent.md` read it
  as an authoring reference; the scoring keys (`confidence_scoring`,
  `multi_agent_triggers`, `force_opus_model`, `minimum_activation`) appear in zero
  hooks/scripts. Real agent routing is model-native: Claude Code reads each
  agent's `description:` frontmatter and selects, so tuning those weights changed
  runtime behavior by exactly nothing. Removed the entry from `LIB_FILES`
  (install.sh, quick-install.sh) and `EXPECTED_LIBS` (validate.sh), the
  EXTENSIBILITY.md file tree, and repointed `meta-agent.md` to author new agents
  from the real `description:` router surface. Corrects the false "Confidence
  scoring" capability claimed for this file under the v0.x entry below. Surfaced
  while evaluating Sakana Fugu (arXiv:2606.21228) — wrong-layer for direct
  adoption (trained coordinator weights vs. our prompt/config layer), but its
  critique of hand-designed routers exposed that ours was not only hand-designed
  but inert.

### Fixed

- **Currency follow-up to `c6aa820`**: completed the `Task`→`Agent` rename in the execute/diverge
  skill prose (the agent frontmatter was done in `c6aa820`; `Task` still works as an alias), and
  updated the README Claude Code links from the old `docs.anthropic.com` domain to the canonical
  `code.claude.com/docs`. No behavior change; closes recurring currency-audit residue.
- **Hook + statusline currency fixes** (`7babc5b`): (1) `smart-guard.sh` PermissionRequest
  auto-approve printed a bare `allow` string that Claude Code does not parse, so safe
  read-only tools were never auto-approved — now emits the required
  `hookSpecificOutput.decision.behavior` JSON. (2) `session-end.sh` was bound to `Stop`
  (fires every turn), writing a bogus `session_end` record per response — rebound to
  `SessionEnd`. (3) `statusline.sh` git cache used a fixed `/tmp` path, so concurrent
  sessions in different repos read each other's cached git state — now scoped to
  `session_id`. Verified against code.claude.com/docs/en/{hooks,statusline}.
- **Sub-agent + command currency & safety fixes** (`c6aa820`): from a currency sweep
  of the sub-agents/hooks/skills docs (prompted by the XDA sub-agents eval). (1) SAFETY:
  added `disable-model-invocation: true` to side-effectful commands (`commit-pr`,
  `create-jira`, `new-feature`) — commands are now skills, so Claude could otherwise run
  them (incl. auto-merge/release) autonomously. (2) Removed `TeamCreate`/`TeamDelete` from
  the agent-teams docs (removed in Claude Code v2.1.178; a team now forms on first teammate
  spawn, is experimental via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, one-per-session),
  dropped the unsupported `SendMessage to:"*"` broadcast, and corrected the
  never-available-to-workers list (`TaskStop` → `ScheduleWakeup`/`WaitForMcpServers`).
  (3) Added `LSP` to the `tools:` of architecture-planner/code-quality/performance-optimizer
  (their bodies instruct LSP calls that were failing against the strict allowlist).
  (4) Stripped the inert `Confidence threshold`/keyword-`weight` scaffolding the `meta-agent`
  factory baked into every generated agent (Claude Code routes on `description:` text only;
  completes the `0b343bb` cleanup) + fixed its stale `docs.anthropic.com` WebFetch URLs.
  (5) Renamed the `Task` tool alias → `Agent` across 11 agents. (6) Deleted the dead
  `security-scan` command (shadowed by the skill). (7) Added an independent, isolated-context
  acceptance-verifier to `/execute` Phase 5 (gates REPORT on the Phase-2 `Success:` criteria
  instead of self-grading; double-sourced by the FUGU eval + the sub-agents article) + a
  `verification.md` independent-oracle clause. (8) Added `validate.sh` currency lints
  (tool-in-body ⊆ `tools:`; no meta-agent scaffolding; Phase 5 names an independent verifier),
  each gap-injection tested.
- **Self-heal now survives its own failure mode — watchdog heals, not just detects**
  (`claude-framework-watchdog.sh`, `d6932b6`): the flagship self-heal had a bootstrap
  paradox — the only healer (`install.sh --update`, via `_trigger_heal`) was wired as
  a SessionStart hook *inside* the `.hooks` block that a CLI settings-sync wipes, so
  the wipe removed the healer and the surviving launchd watchdog only *logged* drift
  (a "warning nobody reads" — framework-integrity.md violation). The watchdog now
  parses the `--quick --json` error count and, on `errors>0`, runs `install.sh --update`
  itself, re-validates, and logs `heal_triggered`/`heal_succeeded`/`heal_failed`. The
  wipe-surviving component is now the healer. Verified: `.hooks`→`{}` → watchdog →
  10 hooks + statusLine restored. Corrected the false CLAUDE.md claim that the watchdog
  already re-ran install.
- **`.statusLine` self-heal** (`e1717fe`): the same settings-sync wipe that empties
  `.hooks` also drops `.statusLine` (killing the status bar), but only hooks were in
  the reconcile set, so `install --update` healed hooks and silently left the bar dead.
  Added `.statusLine` to the sync_hooks reconcile (replace-on-drift), a SessionStart
  `statusline_wiring` drift check, and a validate.sh structural assertion — statusLine
  now self-heals like hooks.
- **Atomic, guarded settings.json writes** (`install.sh`, `16f1a75`): routed all three
  reconcile writes through `_atomic_settings_jq` — a unique `mktemp` temp file (no
  cross-process collision) plus non-empty + valid-JSON guards, so the framework's own
  reconcile can never contribute to a wipe even on already-corrupted input. Root cause
  documented: CLI settings-sync (`src/services/settingsSync/index.ts:519`) wholesale-
  replaces settings.json with change-detection suppressed — external CLI behavior, not
  an install bug.
- **Fail-closed secrets guard + daemon PATH + settings.json delete recovery**
  (`4e57582`): (1) `file-protection.sh` used `exit 1`, which is *non-blocking* for
  PreToolUse — the write to a `.env`/`.pem`/etc. proceeded, making the guard theater;
  now `exit 2` with the message on stderr so it actually blocks. (2) The watchdog plist
  had no `EnvironmentVariables`, so a Homebrew-only `jq` was invisible to launchd and
  the jq-gated heal path silently no-oped; added a `PATH` including
  `/opt/homebrew/bin`. (3) A full *delete* of settings.json (vs an emptied `{}`) was
  both undetected (every check is gated on `[ -f settings.json ]`) and unrecoverable
  (`--update` never recreated it); validate.sh now fails on a missing file (→ watchdog
  heals) and sync_hooks recreates it from template. All three verified end-to-end.
- **EXTENSIBILITY.md appendix counts** (`b37e067`): the Project Structure diagram had
  drifted (skills 15→28, agents 12→13, commands 6→13, rules 4→6); the body already
  listed 28 skills correctly — only the appendix tree was stale.
- **Deploy-integrity exclusion for rules-source repos** (`validate.sh`): generalized
  the hardcoded exclusions into an `INTEGRITY_EXCLUDE` list so a downstream repo that
  intentionally ships its own versions of framework-named rules is not flagged as drift.
  Such rules are authoritative overrides (per the framework's own "project rules override
  general ones" model), not drift, so byte-identity against framework source must not flag
  them. Verified by inject-test: without the exclusion, exactly the overridden rules
  drift-fail. _(The whole per-project deploy-integrity check was later retired when the
  framework moved to a single user-global install.)_
- **Reasoning effort default → `xhigh`** (`settings.json.template`, `8d1cb5f`):
  raised `CLAUDE_CODE_EFFORT_LEVEL` from `high` to `xhigh` (the highest persistent
  tier; `max`/`ultracode` are session-only and invalid as env values). Added an
  effort-VALUE check to `validate.sh --quick` and the SessionStart healthcheck —
  both now reject anything outside `low|medium|high|xhigh` and heal it, catching a
  latent live bug where the value had drifted to an ineffective `max`. Added a
  "Reasoning Effort" section to CLAUDE.md (persistent vs. session-only; workflows
  have no persistent on-switch).
- **Measurement-honesty discipline** (`verification.md` + `optimize.md`, `cb91d7a`):
  new "Honest Measurement" rule (distinguish real change from noise, never report
  an unmeasured number, state the basis of quantitative claims) + a noise guard on
  `optimize`'s keep/revert step so within-variance deltas on noisy metrics
  (build-time, bundle-size) are not kept as wins. Lesson extracted from evaluating
  Headroom (the tool itself was rejected as wrong-layer).
- **Removed hardcoded validate check-count from README** (`33f3b4e`): the
  verify-installation example hardcoded a `--quick` count that went stale on every
  change; replaced with "count auto-discovered, scales with deployed projects" so
  it cannot drift again.
- **Memory-freshness detector now runs in `--quick`** (`d62a2ac`): the runtime
  freshness check lived below the quick-mode `emit_and_exit`, so the watchdog's
  automated `--quick --json` run never executed it. Extracted to a shared
  `check_memory_freshness` called from both quick and full mode; fixed the
  watchdog header comment ("Full" → "Quick" validation).
- **Project-memory backup** (`claude-framework-watchdog.sh`, `5b17dba` + freshness
  wiring fix): the watchdog backed up `~/.claude/hooks` + `settings.json` but NOT
  persistent memory (`~/.claude/projects/*/memory/*.md`) — critical state with no
  snapshot or restore path (framework-integrity.md violation). Added watchdog
  Task 4b (separate `memory-YYYYMMDD.tgz`, relative paths restored with
  `-C ~/.claude`, shallow `projects/*/memory` glob excluding the ~100s-MB JSONL,
  atomic verify-before-promote, `memory-latest.tgz` symlink) + Task 4c retention
  (keep-floor newest 3 regardless of age). Restore steps documented in CLAUDE.md.
  (The `--quick` wiring of the freshness detector was a follow-up — see `d62a2ac`
  above.)
- **Comprehensive md5 deploy-integrity check** (`validate.sh`, `68e3530`):
  replaced the sampled diff-based check (5 projects, content-only) with an md5
  manifest verifying the full deployable set (agents, lib, rules,
  `skills/<name>/**`, commands) is present and identical across ALL deployed
  projects (5 sampled in `--quick` for watchdog speed). Detects both content
  drift AND missing files — the old per-file check was guarded by
  `[ -f "$dst" ]` with no else, so a project missing an entire skill/rule
  passed clean.
- **/diverge wording + cross-reference** (`bf0d76f`): install.sh CLAUDE.md
  emitters now say "isolated parallel sub-agents" (not the clumsy coinage
  "framings"); added the reverse `/diverge` row to `/deep-analysis`'s
  Integration table so the divergent↔convergent cross-reference is bidirectional.

- Documentation count drift reconciled to true on-disk state: skills 26 → 28
  (backfilled `context-escalation`), rules "Four" → 6 (backfilled
  `framework-integrity`) in README.
- **Skill execution model**: removed `context: fork` from `diverge` and `execute`
  so they run inline and can spawn the parallel sub-agents their protocols require
  (forked subagents are denied the Agent/Task launcher per Claude Code docs, so both
  silently degraded — diverge to sequential-single-context, execute to no delegation).
  `investigate` keeps fork (its core RCA uses only subagent-available tools), with
  Phase 1 realigned to evidence-first + return-questions. validate.sh now guards that
  spawner skills (diverge, execute) stay un-forked.
- Added `__pycache__/` and `*.pyc` to `.gitignore` (observability tooling bytecode).

## [2.9.5] - 2026-05-26

### Added

- **context-escalation skill** (`.claude/skills/context-escalation/SKILL.md`):
  Explicit-level policy for handling context pressure in long-horizon
  sessions. Five interventions from cheapest to most aggressive:
  L1 truncate → L2 drop-redundant-reads → L3 fork-subagent → L4 /compact →
  L5 handoff + /save-session. Names a discipline that's otherwise applied
  reflexively, so a session uses cheap interventions before hard-cliff
  compaction.

  Inspired by [DCI-Agent-Lite](https://github.com/DCI-Agent/DCI-Agent-Lite)'s
  context-manager pattern (truncation → compaction → summarization in
  escalating levels), adapted to Claude Code's existing primitives
  (`/compact`, `handoff`, `/save-session`, Agent tool). Borrows the
  structural pattern, not the implementation.

### Considered but not adopted

- **Minimalist single-system-prompt harness** (DCI-Agent-Lite's other notable
  pattern — a 1.7KB system_prompt.txt as the entire agent driver). Not
  applicable to a multi-agent framework where 13 specialized agents need
  distinct system prompts. Documented here so the choice is explicit rather
  than overlooked.

### Validation context

External validation of the framework's bash-native architecture: VentureBeat
[Your AI agents need a terminal, not just a vector database](https://venturebeat.com/orchestration/your-ai-agents-need-a-terminal-not-just-a-vector-database)
argues the case for terminal-tool-native agentic search over vector-DB RAG.
This framework has been in that paradigm since 2.0 — no integration needed,
but the reading reinforces the architectural choice.

## [2.9.4] - 2026-05-06

### Changed (public-repo hygiene)

Made the framework safe to publish under a public repo without leaking
maintainer-specific identifiers (macOS username, hardcoded user paths,
private project names):

- **LaunchAgent Label is project-scoped**: `com.claude-code-agents.framework-watchdog`.
- **Plist filename matches the Label** for consistency.
- **Plist source uses `__HOME__` placeholder** instead of any user path.
  `install.sh` substitutes `__HOME__` → `$HOME` at install time.
- **healthcheck.sh + watchdog.sh repo-resolution**: rely solely on
  `~/.claude/.framework-path` marker (written by `install.sh` on every install
  mode). No hardcoded probe paths. If marker is missing, scripts exit cleanly.
- **CLAUDE.md**: daemon Label reference uses the project-scoped form.
- **History rewrite (git-filter-repo)**: removed legacy hardcoded paths,
  user-scoped Label remnants, machine hostname leakage in author email,
  and personal project names from earlier commit messages and diffs. Author
  email normalized via mailmap to a single canonical noreply form.

Functional behavior is unchanged.

## [2.9.3] - 2026-05-01

### Fixed

- **sync_hooks orphan detection**: `sync_hooks()` now reverse-prunes deployed
  hooks that no longer exist in source. Previously the function copied forward
  but never cleaned up, so files removed from source persisted in
  `~/.claude/hooks/` indefinitely (hit twice this week — `pre-commit.sh` from
  an earlier framework version, and `stop-phrase-guard.sh` after v2.9.2
  removal both required manual rm). With this fix, install.sh closes the
  third and final sync direction:
  - **forward-sync** (always): copy source → deployed
  - **drift-correct** (v2.9.0): replace user's hook events when template differs
  - **reverse-prune** (v2.9.3): remove deployed files no longer in source
  Verified: `touch ~/.claude/hooks/fake-orphan.sh; ./install.sh --update` →
  "Pruned orphan hook fake-orphan.sh (no longer in source)" → file removed.

## [2.9.2] - 2026-04-26

### Removed

- **stop-phrase-guard hook**: removed after evidence-based evaluation. 31 violations
  logged across 3 days; 90% were the single phrase "want me to" — the hook was
  effectively a one-pattern filter wearing a 38-pattern costume (16 of 38
  patterns never fired). Substring matching produced false positives on
  legitimate destructive-action confirmations ("want me to push?") that the
  Claude Code system prompt and project deployment policies explicitly require.
  No measured benefit. The pattern conflicts with the system prompt's
  "transparently communicate the action and ask for confirmation" guidance.
- **install.sh stale-lock + backup rotation** also landed (see 2.9.1 entry below
  for accumulated 4th-pass fixes).

### Fixed (4th audit pass)

- **install.sh stale-lock recovery**: `update_installation()` now writes its
  PID into the lock dir and treats locks with dead/missing PIDs as stale.
  Prevents the framework from deadlocking after a killed install.
- **install.sh backup rotation**: `backup_existing()` keeps the 3 most-recent
  `.claude-backup-*` directories per project, prunes older. Cleaned up 3,637
  stale dirs across 88 deployed projects (~39MB freed).

## [2.9.1] - 2026-04-24

### Self-Healing Framework Hardening

Follow-up to 2.9.0 addressing gaps found by a pre-deploy deep-analysis pass.

### Fixed

- **sync_hooks `permissions` reconciliation**: template permissions now propagate to user `~/.claude/settings.json` on install, not just hook events and env vars. Previous add-if-missing skipped drifted permissions.
- **Install concurrency lock**: `install.sh --update` now acquires a non-blocking lock at `~/.claude/.install.lock.d`. Prevents healthcheck + watchdog racing on `jq` read-modify-write of settings.json.
- **Watchdog fsck filter**: tightened from `error|corrupt|missing|bad` to only match real object corruption. Benign reflog residue and dangling commits no longer alert.
- **Plist path templating**: `install_watchdog()` sed-substitutes a placeholder in the LaunchAgent plist with the caller's `$HOME` at install time so the daemon works for any user. (Hardened in 2.9.4 to use `__HOME__` placeholder explicitly — see 2.9.4 entry.)
- **Doc drift**: CLAUDE.md, MEMORY.md, README.md, EXTENSIBILITY.md — fixed stale counts (9 hooks → 10, 4 rules → 5) and version strings.
- **Framework marker in source repo**: `write_framework_version_marker()` now skips when CWD is the source tree; added `.gitignore` entries for `.claude/.framework-version` and `.claude-backup-*/` as defense in depth.
- **Stop-phrase-guard output**: violation message now written to stderr so Claude Code's Stop-hook UI displays the actual matched phrase instead of "No stderr output".

### Added

- **deploy-all.sh**: driver for batch install across local projects with per-project pre-install tarballs, `--dry-run`, `--continue-on-error` (default), `--halt-on-error`, `--only <name>`, and JSONL failure manifest. _(Retired when the framework moved to a single user-global install.)_
- **.claude/.framework-version marker**: written into every deployed project (version + short SHA + UTC timestamp). Enables targeted re-deploy and staggered rollout.
- **Watchdog claude-obs.db regeneration**: when the DB is missing, watchdog runs `python3 collector.py` with a 120s timeout. Closes the "deferred_regen" path logged by the healthcheck hook.

## [2.9.0] - 2026-04-23

### Self-Healing Framework

Introduces an end-to-end reconciliation loop so framework state can no longer silently drift.

### Added

- **SessionStart healthcheck hook** (`global-config/hooks/session-start-healthcheck.sh`): runs on every session start with a <2s budget. Checks env keys, hook sha256s, analytics file presence, hook event wiring vs template. On drift: logs to `~/.claude/analytics/framework-health.jsonl` and forks `install.sh --update` in background. Exit 0 always (never blocks session start).
- **launchd watchdog daemon** (`global-config/daemon/claude-framework-watchdog.sh` + plist): hourly `validate.sh --quick --json`, `git fsck`, daily rolling `git bundle` snapshots to `~/.claude/snapshots/`, daily userconfig tarballs, 7d retention.
- **validate.sh modes**: `--quick` (~0.08s, checks `~/.claude/` only), `--json` (machine-readable for daemon consumption), `--heal` (invokes `install.sh --update` on detected drift).
- **validate.sh structural checks** (always-on): SessionStart template non-decorative regression guard, user-settings hook-wiring drift vs template, watchdog daemon loaded, snapshot freshness (<48h).
- **.claude/rules/framework-integrity.md**: no decorative hooks; auto-reconciled state; every critical directory has a snapshot with restore path.
- **Self-Healing section in CLAUDE.md**: describes the fast/slow paths, diagnostic streams, and restore procedures.
- **install.sh install_watchdog() + write_framework_path_marker()**: wired into `--full`, `--update`, `--team-setup`, `--repair`.
- **install.sh inode guards**: `-ef` checks in `download_or_copy()` and three direct `cp` sites make `--update` idempotent when run inside the source repo.

### Fixed

- **sync_hooks reconciliation** (was add-if-missing): template hook events now REPLACE user's version on drift, not just on missing-key. Previously left SessionStart stuck on a decorative echo and `stop-phrase-guard.sh` disabled for weeks even though present on disk.
- **sync_hooks env merge**: environment variables from `settings.json.template` now merged into user `~/.claude/settings.json`. Previously lost across installs — e.g., `CLAUDE_CODE_EFFORT_LEVEL=high` never reached users.

## [2.3.0] - 2026-02-12

### Quality, Coordination & Extensibility Release

This release fixes credibility gaps between documentation and reality, adds missing infrastructure, and incorporates improvements from the latest Claude Code features.

### Fixed

- **False telemetry/metrics claims**: Removed fabricated metrics ("90ms activation", "30% productivity", "85% accuracy") from README.md
- **Telemetry references**: Marked telemetry as "Planned" across README.md, CLAUDE.md, and sdlc-patterns.md — no longer claimed as existing
- **EXTENSIBILITY.md directory references**: Fixed all `.claude/subagents/` references to `.claude/agents/`
- **EXTENSIBILITY.md version**: Updated from 2.2.0 to 2.3.0
- **meta-agent.md broken tools**: Removed non-existent `firecrawl` MCP tools, added `WebSearch`
- **meta-agent.md URLs**: Fixed documentation URLs from `docs.claude.com` to `docs.anthropic.com`
- **meta-agent.md telemetry**: Replaced "Generate Telemetry Hooks" with "Define Success Criteria"
- **install.sh error handling**: `install_agent()` and `install_lib_file()` now check return codes from `download_or_copy()`

### Added

- **validate.sh**: New validation script checking all agent files (frontmatter, sections), lib files (JSON validity), skills (SKILL.md), MCP config, slash commands, and cross-references
- **Agent coordination protocol** (`.claude/lib/agent-coordination.md`): Formal protocol for sequential handoffs, parallel coordination, review chains, error recovery, and priority rules
- **.claude/rules/ directory**: Auto-loaded rules for security and code quality
  - `security.md`: Secrets, input validation, auth, HTTP security, dependencies
  - `code-quality.md`: Dead code, function design, error handling, naming
- **`/review-pr` slash command**: PR review for code quality, security (OWASP), testing, documentation
- **`/security-scan` slash command**: Security scanning with secrets detection, dependency checks, OWASP patterns, file permissions
- **install.sh preflight checks**: Write permissions, disk space, source directory validation
- **install.sh rules installation**: New `install_rules()` function and `.claude/rules/` directory creation
- **install.sh error counting**: `install_errors` counter in `install_full()`
- **EXTENSIBILITY.md meta-agent listing**: Added missing `meta-agent` to agents list

### Changed

- README.md "Enterprise Ready" description updated from "telemetry and monitoring" to "extensible architecture"
- README.md `history/` directory description updated from "Telemetry & learning" to "Session history (planned: telemetry)"
- README.md "Why Claude Agents?" section updated to reference extensibility instead of telemetry
- CLAUDE.md "Continuous Improvement" section marked as planned
- Commands README updated with `/review-pr` and `/security-scan` documentation

---

## [2.2.0] - 2025-10-28

### 🌐 MCP Integration & 4-Way Extensibility

This release introduces **Model Context Protocol (MCP)** integration, adding external tools and data sources to the Claude Code platform. Combined with Skills, Slash Commands, and Subagents, this creates a comprehensive 4-way extensibility system.

### Added

#### MCP-Powered Skills
- 🟢 **library-docs** skill (uses context7 MCP server)
  - Fetch up-to-date documentation for 100+ libraries
  - Support for React, Next.js, Vue, MongoDB, Supabase, PostgreSQL, and more
  - Topic-focused documentation retrieval
  - Version-specific query support
  - Integration with documentation-maintainer agent

- 🧠 **deep-analysis** skill (uses sequential-thinking MCP server)
  - Structured multi-step reasoning for complex problems
  - Up to 31,999 thinking tokens (vs 4,000 standard)
  - Hypothesis generation and verification
  - Course correction and branching
  - Integration with architecture-planner and performance-optimizer agents

#### Comprehensive Documentation
- 📘 **EXTENSIBILITY.md** - Complete extensibility guide
  - Comprehensive overview of all four mechanisms
  - Skills (Blue): Knowledge & methodology
  - MCP (Green): External tools & data
  - Slash Commands (Red): User-triggered workflows
  - Subagents (Orange): Isolated task execution
  - Decision matrix for choosing mechanisms
  - 5 integration patterns with real examples
  - Best practices for each mechanism
  - Validation and testing guidance

#### Enhanced Documentation
- 📝 **CLAUDE.md Updates**
  - Added comprehensive MCP Integration section
  - Documentation of both MCP servers (context7, sequential-thinking)
  - MCP + Agent integration examples
  - Configuration guidance
  - Usage patterns and examples

- 📖 **README.md Updates**
  - Version badge updated to 2.2.0
  - Skills badge updated to 6 included
  - New MCP badge added
  - Added "MCP Integration" to key features
  - Added "4-Way Extensibility" feature
  - New MCP Integration section with examples
  - Four extensibility mechanisms diagram
  - Architecture updated to show MCP-powered skills
  - Links to EXTENSIBILITY.md

### Enhanced

- 🔌 **Four Extensibility Mechanisms**
  - **Skills**: Modular knowledge packages (6 included)
  - **MCP**: External integrations (2 servers configured)
  - **Slash Commands**: User-triggered workflows
  - **Subagents**: Isolated execution (11 agents)

- 🎓 **Skills System**
  - Now includes MCP-powered skills
  - Clear integration patterns with MCP servers
  - Enhanced agent-skill collaboration
  - Updated power combos showing MCP usage

- 📊 **Integration Patterns**
  - Skill + MCP: library-docs fetches external data
  - Skill + Agent: deep-analysis guides architecture-planner
  - MCP + Agent: External tools enhance agent capabilities
  - Full Integration: All mechanisms working together

### Technical Details
- **New Skills**: 2 MCP-powered (library-docs, deep-analysis)
- **Total Skills**: 6 (skill-creator + git-workflow + code-review-checklist + deployment-runbook + library-docs + deep-analysis)
- **MCP Servers**: 2 (context7, sequential-thinking)
- **Documentation**: 800+ line extensibility guide
- **Architecture**: 4-way extensibility system

### MCP Configuration

Add to Claude Code settings:

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@context7/mcp-server"]
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

### Benefits

**For Developers:**
- Access up-to-date library documentation on-demand
- Deep reasoning for complex architectural decisions
- External tool integration via MCP
- Clear decision matrix for extensibility choices

**For Organizations:**
- Comprehensive extensibility options
- Integration with external APIs and services
- Structured reasoning for critical decisions
- Complete documentation of all mechanisms

### Skills + MCP + Agents Integration

| Agent | Skill | MCP Server | Result |
|-------|-------|------------|--------|
| **architecture-planner** | **deep-analysis** | sequential-thinking | Structured architectural decisions |
| **documentation-maintainer** | **library-docs** | context7 | Documentation using library patterns |
| **performance-optimizer** | **deep-analysis** | sequential-thinking | Root cause analysis |

### What's Next?

See **[EXTENSIBILITY.md](./EXTENSIBILITY.md)** for:
- Complete guide to all four mechanisms
- Decision matrices and integration patterns
- Real-world examples from this project
- Best practices and validation guidance

---

## [2.0.0] - 2024-10-16

### 🚀 Major Release - Enterprise Agent System

This release transforms Claude Agents into a comprehensive enterprise-grade SDLC/SSDLC agent system with natural language activation.

### Added

#### Core System
- ✨ **11 Specialized SDLC/SSDLC Agents**
  - `architecture-planner` - System design and API specifications
  - `code-quality` - Code review and quality metrics
  - `security-auditor` - OWASP compliance and vulnerability scanning
  - `test-automation` - Comprehensive test generation
  - `performance-optimizer` - Profiling and optimization
  - `devops-automation` - CI/CD and deployment
  - `documentation-maintainer` - Auto-documentation with Haiku
  - `database-architect` - Schema design and query optimization
  - `frontend-specialist` - UI/UX implementation
  - `api-backend` - Backend service development
  - `incident-commander` - Production emergency response

#### Meta-Agent System
- 🤖 **Enhanced Meta-Agent v2.0**
  - SDLC/SSDLC phase awareness
  - Natural language activation patterns
  - Security-first design principles
  - Intelligent tool selection
  - Multi-agent orchestration
  - Cost optimization (Haiku/Sonnet/Opus)

#### Supporting Infrastructure
- 📚 **Agent Templates Library** (`agent-templates.json`)
  - 13 pre-built agent templates
  - Activation keywords and patterns
  - Tool configurations
  - Best practices embedded

- 📋 **SDLC Patterns Reference** (`sdlc-patterns.md`)
  - Phase detection patterns
  - Multi-agent workflows
  - Priority rules
  - Collaboration strategies

- 🔤 **Activation Keywords Database** (`activation-keywords.json`)
  - Natural language patterns
  - Confidence scoring
  - Technology-specific keywords
  - Multi-agent triggers
  - _Correction: this scoring/router logic was never wired into any executing
    code path (agent routing is model-native via `description:` fields). The file
    was removed as dead config — see **Removed** under [2.10.0]._

#### Installation System
- 🛠️ **Intelligent Installer** (`install.sh`)
  - Detects existing components
  - Multiple modes (minimal, full, repair, update)
  - Automatic backups
  - Progress tracking
  - Verification and rollback

- 📦 **Deployment Options**
  - One-liner installation from GitHub
  - Multiple CLAUDE.md variants
  - Merge-friendly configurations
  - Ultra-minimal options

### Changed
- 🔄 **Complete Architecture Overhaul**
  - From 4 basic agents to 11 specialized agents
  - From manual commands to natural language activation
  - From single agent to multi-agent collaboration
  - From fixed models to intelligent selection

### Enhanced
- 💡 **Natural Language Processing**
  - Auto-activation based on conversation context
  - Weighted confidence scoring _(never wired into any code path — see **Removed** under [2.10.0]; real routing is model-native via agent `description:` fields)_
  - Context-aware agent selection
  - Phrase pattern matching

- 💰 **Cost Optimization**
  - Haiku for documentation (95% savings)
  - Sonnet for standard development
  - Opus for security and critical tasks
  - ~70% overall cost reduction

- 🔒 **Security Improvements**
  - OWASP Top 10 compliance
  - DevSecOps practices
  - Automatic security scanning
  - SOC2/ISO 27001 considerations

### Technical Details
- **Lines of Code**: 5,000+
- **Configuration Files**: 15+
- **Agent Definitions**: 11
- **Test Coverage**: Comprehensive
- **Performance**: Keyword-based activation

### Breaking Changes
- Old agent format deprecated
- Manual command invocation replaced with auto-activation
- Directory structure reorganized

### Migration Guide
Users can upgrade using:
```bash
./install.sh --update
```

## [1.0.0] - 2024-10-01

### Initial Release
- Basic 4-agent system
- Manual router
- Simple cost tracking
- Basic installation script

## [2.1.0] - 2024-10-28

### 🎓 Skills System Integration

This release adds a comprehensive skills system that extends the agent framework with modular knowledge packages, enabling users to create custom domain expertise alongside the existing agent system.

### Added

#### Skills System
- ✨ **Skills Infrastructure**
  - `.claude/skills/` directory for modular knowledge packages
  - Integration with existing 11-agent system
  - Progressive disclosure (metadata → SKILL.md → bundled resources)
  - Skill creation, validation, and packaging tools

- 🛠️ **skill-creator Skill**
  - `init_skill.py` - Create new skills from templates
  - `package_skill.py` - Validate and package skills for distribution
  - `quick_validate.py` - Quick validation during development
  - Comprehensive skill creation methodology (6-step process)

#### Demonstration Skills
- 📚 **git-workflow**
  - Git best practices and branching strategies
  - Commit message guidelines (Conventional Commits)
  - Pull request workflows
  - Merge conflict resolution
  - Git Flow, GitHub Flow, Trunk-Based Development

- 🔍 **code-review-checklist**
  - Systematic code review guidelines
  - 10-category review framework
  - Security checklist (OWASP Top 10)
  - Performance anti-patterns
  - Team collaboration best practices
  - Complements code-quality agent

- 🚀 **deployment-runbook**
  - Deployment strategies (blue-green, canary, rolling)
  - Pre/post-deployment checklists
  - Health check automation scripts
  - Rollback procedures
  - Troubleshooting guides
  - Complements devops-automation agent

#### Documentation
- 📖 **Comprehensive Skills Documentation**
  - Updated CLAUDE.md with Skills System section
  - Agent vs Skills comparison guide
  - Skills integration examples
  - README.md with skills features
  - Updated architecture diagrams

- 📘 **Skills README** (`.claude/skills/README.md`)
  - What skills are and when to create them
  - Skills vs agents comparison
  - Step-by-step creation guide
  - Integration patterns
  - Real-world examples

### Enhanced

- 🎯 **Agent-Skill Integration**
  - Skills complement agents for powerful workflows
  - Examples: code-quality + code-review-checklist
  - Clear guidance on when to use agents vs skills
  - Progressive disclosure for efficient context management

- 📊 **Architecture**
  - Updated to show dual agent + skills system
  - Clear separation of concerns
  - Modular, extensible design

### Technical Details
- **New Skills**: 4 (skill-creator + 3 demonstrations)
- **Scripts Added**: 3 Python utilities
- **Documentation Pages**: 5+ comprehensive guides
- **Directory Structure**: `.claude/skills/` with organized subdirectories

### Benefits

**For Users:**
- Extend capabilities with domain-specific knowledge
- Create reusable, shareable skill packages
- Bundle scripts, references, and assets
- Complement agents with specialized expertise

**For Organizations:**
- Codify company-specific knowledge (APIs, schemas, processes)
- Standardize workflows across teams
- Share best practices through skills
- Reduce onboarding time with packaged knowledge

### Skills vs Agents

| **Agents** | **Skills** |
|------------|------------|
| Auto-activating task executors | Modular knowledge packages |
| Execute SDLC workflows | Provide domain expertise & tools |
| Examples: security-auditor, test-automation | Examples: git-workflow, brand-guidelines |

---

## Upcoming Features

### [3.0.0] - Future
- VS Code extension
- Web dashboard for telemetry
- AI model fine-tuning
- Custom agent marketplace
- Enterprise dashboard
- Advanced telemetry analytics