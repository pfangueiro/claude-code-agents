# Independent acceptance result

This records the initial adapter review before global installation. Subsequent
laptop deployment and cross-project tests are recorded in [GLOBAL-VALIDATION.md](GLOBAL-VALIDATION.md).

**PASS for documented workflow portability**, not complete Claude runtime parity.

Baseline Git SHA: `509d282a195cc7a0e3b4d63b51b5f791be519eed` plus local uncommitted
adapter changes. Review performed by two independent baseline auditors and a fresh
acceptance evaluator who did not implement the adapter. Controller independently
reproduced and corrected material findings.

Generated payload SHA256, independently matched by reviewer and controller:
`581455055f92e89deed4735ba72685d158bd3ccf19e8bf1c6a4d329499bb73e3`.
Serialization is sorted relative path UTF-8 + NUL + contents for each `build()` file.
The 34 raw review inputs, before adding this evidence document, hash to
`5f5c3b655a9dc06cffdc8a1af2ab621005d1c33a087fffbd14a0e3ae64acc7f7`
with a trailing NUL after each file. No implementation commit or published SHA is claimed.

Actual checks:

- Fresh evaluator and controller each ran **21 acceptance tests**, all passing.
- Both ran **8 Codex mutation probes**; each defect was detected and its restored
  negative control passed.
- Existing Claude suite passed its repository baseline, harmless negative control
  and **22/22 mutation probes** in `--prove` mode with an isolated home.
- Native CLI 0.162.1 prompt discovery exposed all **49 implicit skills** (36 workflows
  plus 13 specialist guides) and excluded the three explicit-only workflows as intended.
- Inventory and parser checks verified **39 workflows**, **13 specialist guides**,
  **13 native TOML definitions**, complete retained resources and invocation policy.
- Installed hook subprocess tests verified JSON deny decisions, malformed-input exit 2,
  and no retention of patch contents or credentials in metadata.
- Original `.claude/`, `global-config/`, `install.sh`, `validate.sh` and `observability/`
  remain unchanged according to `git diff --exit-code`.

Fresh review found an ancestor-symlink redirection, wrong skill invocations in handwritten
overrides, and invalid literal PR arguments. Each was reproduced, corrected and given a
regression check. Protected native auth paths and case-insensitive secret directories
were also verified against ordinary file-edit negative controls. No unresolved blocking
finding remained in the final review.

Independent procedure forward-test: in a disposable cache project, the evaluator loaded
the generated execute/investigate/meta-agent procedures, reproduced an expiry-boundary
failure, traced source line 13, applied a one-line correction and verified passing tests.
Restoring the original mechanism failed the regression; restoring the correction passed.
A narrow read-only specialist TOML parsed without a model override. This was independent
local procedure use, not an authenticated native custom-profile spawn.

Native custom-profile spawning, hook trust UI and authenticated desktop/IDE/cloud
behavior remain unverified. Dashboard, watchdog/self-healing, notifications, statusline,
automatic linting and automatic snapshots are not implemented. See [FEATURES.md](FEATURES.md).
No global installation, personal auth/configuration access, live-data writes, commits,
remote publishing or external messages were performed.
