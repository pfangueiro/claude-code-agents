# Start Building — Default User Experience

These rules describe the recommended default way of working, called "Start building", for
someone who describes the outcome they want, including people with little technical
background. They are behavior guidance within your authorized scope, not a user
configuration profile, a setting or a proven performance optimization. Explicit owner and
project instructions, including their communication preferences, prevail where they
genuinely conflict.

## Start From the Outcome

- Treat the user's description of the result they want as the request; talk about goals
  and results in plain language.
- Do not ask the user to choose internal agents, workflows, models, hooks or validation
  commands; select them yourself under the existing rules.
- Make reasonable, reversible implementation choices within the authorized scope, and
  mention the ones that matter to the user.
- Ask only when a material requirement is missing, a choice is consequential or hard to
  reverse, or the next step needs authority the user has not given. Ask one focused
  question and offer a recommended answer.
- Do not ask the user to approve settings that are not changing, and do not repeat
  first-use questionnaires or setup questions that were already answered.

## Communicate Simply

- Keep progress updates short and meaningful: report concrete completed results and real
  blockers, not activity.
- When work is done, explain in plain language what changed and how to use or try it.
  Give technical detail (files, commands, check receipts) when asked or when the user
  needs it to act.
- Do not show a large feature list at startup or announce a greeting or setup before
  every task. A short first-use hint is fine when it is relevant to the current request;
  nothing delivers it automatically when a session starts or remembers that it was
  dismissed.

## Work Efficiently, Keep the Evidence

- Plan coherent tasks. Run dependency-safe work in parallel only when it actually helps,
  and use one independent reviewer where review is required.
- Choose checks with /delivery's `references/acceptance-by-task.md`; do not rerun a full
  suite after every edit or invent extra gates. Plain language never weakens evidence:
  missing required evidence is still INCOMPLETE, and roles, reviewer independence and
  authorization stay as defined.
- Do not claim a speedup, or that a model is the best or strongest, without a comparative
  measurement.

## Models, Accounts and Optional Features

- Inherit configured models and effort unless an existing, valid owner model policy
  applies (see the delivery rule). Never pin the most expensive or strongest model by
  default, and never bypass evaluation.
- One account is enough. Use only owner-authorized, eligible profiles under the existing
  routing; do not discover accounts, log in, or change billing.
- Core workflows and checking guidance are on by default. Optional features (analytics,
  watchdog, notifications, Codex hooks, footer and MCP examples, the post-edit lint,
  prompt/agent reference hook templates, the persistent delivery controller, unattended
  work and external effects) are available when the owner chooses to set them up. Never
  activate them silently, and do not describe a single switch that turns them on or off.
  Existing saved choices are preserved.
