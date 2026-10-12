# Publication acceptance

Implementation input: `aadd77c383189d5b72e06e89aff87a2e3285cae8`, parent
`c4f343a89fcd7311c4973708048c04670f299de3`. The parent was fast-forwarded from GitHub
before implementing publication changes, preserving prior commit SHAs.

An independent reviewer who did not implement the change returned PASS at that exact
implementation SHA, with no blocking finding. Independently observed checks:

- 21 Codex acceptance tests passed, including native discovery in an isolated home.
- Eight mutations were detected; every restored negative control passed.
- Isolated Claude validation exited 0: 230 checks, 224 passes, six expected fresh-home
  warnings and zero errors. The controller also ran the 22-case Claude mutation suite
  with passing baseline and negative controls.
- Inventory/resource/invocation checks confirmed 39 workflows, 13 role guides and
  13 native TOML definitions. All relative file links resolved.
- Targeted publication scans found no concrete machine paths or credential patterns.
  Public MEMORY.md is generic; private user/project memory is not committed.
- Documentation covers shared/global architecture, model/permission inheritance,
  optional hooks/MCPs and the unported/runtime verification limits.

Generated payload at that implementation SHA: 129 files; SHA256
`1b7b97879236a096d6ecce9b35435e03958cd510287cf986f1093617ee21fccf`.
Serialization is sorted relative path UTF-8 + NUL + contents for each `build()` output.
The controller independently matched that payload fingerprint. Historical initial
review fingerprints remain in REVIEW.md rather than being relabeled as current.

This record certifies the reviewed implementation and local checks. GitHub branch/CI
verification belongs to the exact subsequently pushed head and is reported separately;
an older green run does not certify a newer commit. No release/tag is implied.

The first GitHub run at `1debb1848b503861bedeb6fd8bbd5140436081d8` passed the four
existing checks but failed Codex resource execution: the health checker imports Requests,
which was not in the dependency manifest. Local system Python had masked the omission.
The failure was independently reproduced in a clean Python 3.11 environment before
repair. The correction declares the dependency and makes CI use a fresh virtualenv;
the new resource mutation keeps the original failure path observable. Initial local
acceptance above is historical, not a claim that the failed GitHub run was green.
