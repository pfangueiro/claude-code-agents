# Optional agent-guidance evaluation

This is an opt-in, local comparison of two instruction files. It is not part of an
ordinary delivery, `/quality-gate` or a v1 execution receipt. A v1 receipt records an
observed execution of one check on a recorded input; it is necessary evidence, not
proof of authenticity, producer or semantic coverage. An evaluation records how an
agent's delivered outcomes differed between a baseline and a candidate instruction
file on a fixed corpus. Neither establishes the other.

Provider runs happen only when you run the command below with an adapter you chose;
they are never automatic in CI, `/quality-gate` or delivery. Offline behaviour tests
of the harness with a fake adapter do run in CI; they call no provider and say nothing
about any agent's efficacy.

## Run

Run from the `verified-handoff` skill directory (the harness resolves its own corpus
and helpers relative to the script, not the working directory):

```bash
EVAL=/absolute/path/to/private-eval   # existing directory outside public source
python3 scripts/agent_eval.py run \
  --baseline "$EVAL/baseline.md" \
  --candidate "$EVAL/candidate.md" \
  --adapter "$EVAL/adapter.json" \
  --out-dir "$EVAL/run-001" \
  --trials 2 --timeout 120
```

- Optional flags: `--trials` (1-20 trials per task and arm, default 1), `--timeout`
  (adapter seconds per trial, default 900), `--corpus FILE` (default
  `references/eval-corpus.json`) and `--task ID`, repeatable to select several tasks.
- `--out-dir` must not exist; its parent must already exist, and it must lie outside
  the skill source and the corpus directory. Keep it, the instruction files and the
  adapter private: raw logs and results can contain prompts, model output and local data.
- Standard-library Python 3.11; no dependency, installer, hook or background job.
- Exit codes: `0` PASS, `1` FAIL, `2` usage error (nothing evaluated), `3` INCOMPLETE.

## Corpus

The default corpus is six synthetic cases: a feature, a bug repair, a refactor, a
review with a real defect, a clean safe-counterexample review, and a support
interpretation of captured environment-limited evidence. A new or edited corpus needs
human and behavioural calibration (known-good solutions pass, plausible wrong ones
fail, valid alternatives stay accepted) before its results mean anything; passing the
JSON schema is not calibration.

## Adapter

```json
{
  "name": "local-wrapper",
  "version": "1",
  "requested_model": null,
  "argv": ["/absolute/path/to/your-wrapper", "{prompt_file}"],
  "input_files": ["/absolute/path/to/your-wrapper"]
}
```

`argv` holds literal strings; `{prompt_file}` is replaced with the prepared prompt
path. It runs directly (no shell) with a disposable fixture copy as its working
directory. The wrapper is yours: it invokes the agent CLI under that CLI's configured
defaults (use only options its own documentation supports; the harness sets no model,
account or permission override) and, after the provider reports a terminal success,
normalizes the native output into ONE JSON envelope on stdout with exactly these fields:

```json
{"status": "success", "observed_model": null, "cost_usd": null, "response": {}}
```

- `status` is `success` or `unavailable`. A trial is usable only when the envelope
  says `success`, the process exits zero and its process group is empty; exit zero
  alone is not success. Unavailable, malformed or extra-field envelopes, nonzero exits,
  signals, leftover processes and timeouts are UNAVAILABLE, never success. Nothing is
  retried.
- `requested_model` (config) and `observed_model` (provider-reported) are recorded
  separately. `cost_usd` is the inference cost the native CLI reported, not an invoice
  or a statement of extra billing; when not reported it is `null` (unknown), and no
  price is inferred. The aggregate is `null` with `reported_total_status: "overflow"`
  when reported costs do not sum to a finite number (`none-reported` when none were).
- Optional `input_files`: 1-16 regular, non-symlink files you declare (for example the
  wrapper or CLI binary), absolute or relative to the adapter file's directory. Their
  identities are frozen before the first trial and rechecked before every launch and
  at the end; a change is not launched and is source drift. Without `input_files` the
  adapter payload identity is recorded as `unknown`. Declared files are the whole
  claim: undeclared scripts, imports, transitive dependencies, environment and remote
  services are not identified.
- The task-specific `response` fields are defined by the harness prompt protocol.

## Scope and grading

- Graders are built into the harness and never placed in the solver workspace; gold
  answers and history are withheld. They check behaviour and accept valid alternatives.
- Scope compares complete entry inventories (files, directories, symlinks, never
  followed) in both the solver workspace and the grading copy. Any new file, directory
  or symlink, or any change outside the allowed paths, is a scope violation and FAIL,
  even when the provider was otherwise unavailable. Runtime caches are not
  automatically allowed (grader probes run Python with `-B`).
- Only `response.files` is applied, to a fresh copy of the fixture, and graded. Direct
  edits to allowed paths in the workspace are reported but not graded.
- Review grading is deliberately narrow: it supports only small integer floor-division
  fixtures with a single plain bucket function and a single unambiguous return, whose
  zero-divisor preflight must raise `ZeroDivisionError`. Unrepresentable, multiple-return
  or otherwise unsupported fixtures are UNAVAILABLE, never a clean result or an agent
  false miss. A finding counts only when its concrete witness is executed and reproduces
  the defect; a matching path, line or keyword is not a verified finding. This is not a
  general review-truth oracle.

## Verdicts

- Trial: PASS, FAIL or UNAVAILABLE.
- Overall: FAIL when any candidate trial failed or a task regressed against the
  baseline, even if other trials are unavailable (those stay listed in `reasons`);
  otherwise INCOMPLETE when any trial is unavailable or a source input changed;
  otherwise PASS for the declared selected scope. Baseline failures are observations
  and do not by themselves fail the candidate.
- A `--task` subset reports only those tasks (`config.tasks`); it never establishes
  whole-corpus coverage.
- Precision, recall and other ratios are `null` when undefined or when any review trial
  was not assessed. Missing evidence is unknown, never a zero or a success.

## What to record and compare

The result records source identity as digests of what actually ran: harness script,
evidence helpers, corpus, both instruction files, adapter config, the resolved `argv[0]`
executable, declared `input_files` and the Python interpreter. It has no Git commit
field (an installed bundle need not be a Git checkout); bind a commit separately with
an outer delivery receipt when one is needed. Also retained: adapter name/version,
requested and observed model, and per trial the outcome, scope, behaviour checks,
duration and reported cost or unknown. Compare only runs with the same corpus, graders
and adapter; changed definitions are not pooled. Repeated trials are descriptive counts;
a small pilot calibrates the harness and is not statistical or production evidence that
a candidate is better.

## Isolation limits

The disposable working directories, inventories and process-group cleanup separate
files and processes; they are not an OS sandbox. The trusted adapter and the produced
code run with the caller's privileges, inherited environment, configuration and
credentials. Entries created and removed within a step, writes outside the workspace,
network use and processes that leave the group are not observed or contained. The agent
may send fixture content and instructions to its provider. Run only adapters and
corpora you trust.
