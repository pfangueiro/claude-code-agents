# Claude Code Commands

This directory contains custom slash commands for streamlined development workflows.

Inventory: 12 executable command templates; this README is documentation. Claude also
exposes skill invocations such as `/security-scan`, which are not command files here.
Codex converts the 12 templates to `$sdlc-<name>` skills. `commit-pr`, `create-jira` and
`new-feature` retain explicit-only selection; publication/service workflows honor actual
project configuration and authorization. [Codex behavior and limits](../../codex/FEATURES.md).

## Available Commands

### `/new-feature` - Create Feature Branch
Creates a feature branch from the repository's own discovered base branch — a
project-configured default, otherwise the remote's recorded default via `origin/HEAD`
(`main`, `master`, or a custom default are all handled; it never assumes `master`).
Uncommitted work is never stashed, reset, or moved implicitly. A ticket identifier is
optional and is used only when the repository's branch convention calls for one.

**Usage:**
```
/new-feature [ticket] <description>
```

**Examples** (the leading ticket is optional — follow your repo's own convention):
```
/new-feature add-export-functionality
/new-feature PROJ-755 add-export-functionality
```

### `/commit-pr` - Commit and Publish
Commits the intended scope and publishes only the effects that are authorized. Commit,
push and PR creation are authorized by invoking the command once the gates pass; issue
updates, merge, release and branch deletion stay separate effects that need existing
explicit authorization or project policy. Base branch, required checks, review, release
and issue-tracker integration come from the project's own configuration — never a
hardcoded default branch, version file or ticket prefix.

**Usage:**
```
/commit-pr [optional commit message]
```

**Features:**
- Stages only the intended paths, writes a convention-following message, and records the candidate SHA (never skips hooks, amends or force-pushes unless asked)
- Runs the project's required local checks and holds push/PR on a failed or missing check
- Requires an independent verdict covering the exact candidate SHA; any new commit invalidates it
- Confirms the pushed head equals the reviewed candidate and uses the environment's already-selected credentials; the PR body records the summary, validation run, reviewed SHA and material gaps
- Updates an issue tracker, merges, releases or deletes branches only when the project configures it and the effect is authorized — reporting each effect as done, held (with gate), skipped (with reason) or failed

### `/create-jira` - Create a Tracker Issue
Creates an issue (epic, story, or task) in whatever issue tracker this environment
actually exposes — an MCP tracker tool, a project-documented CLI/API, or a tracker named
in the project instructions. The target project, issue types, parent conventions, and
assignee come from that authorized configuration, never a hardcoded project key. If no
connector is available, it hands back a ready-to-file draft and states plainly that no
issue was created.

**Usage:**
```
/create-jira epic <Title Here>
/create-jira story <parent> <Title Here>
/create-jira task <parent> <Title Here>
```

**Examples** (parent keys are illustrative — use your own tracker's keys):
```
/create-jira epic Improve Dashboard Performance
/create-jira story PROJ-753 Add filter functionality to alerts
/create-jira task PROJ-905 Fix mobile responsiveness
```

**Behavior:**
- Discovers the tracker capability and uses read-only calls to confirm the project and supported types
- Creates at most the single requested issue, and only when an authorized connector exists
- Resolves assignee/labels from the tracker's configuration or project instructions (for example `git config user.email` only when the config calls for it)
- With no connector, returns the drafted issue rather than presenting a fake one

### `/review-pr` - Review Pull Request
Independently reviews a pull request at its exact base/head for correctness, security
(OWASP), language/framework hazards, tests and documentation.

**Usage:**
```
/review-pr 123
```

**Features:**
- Discovers the available GitHub tools or `gh`, records the reviewed base/head SHAs and reads review policy from the trusted base
- Validates candidate findings against triggers, affected callers and safe counterexamples; separates runtime-reproduced, source-proven and unverified findings from nonblocking suggestions
- Reports missing required evidence as INCOMPLETE; no letter grades or unmeasured metrics
- Posts comments or changes approval state only when already authorized, after rechecking the PR head

### `/security-scan` - Security Scan
Scans the project or a specified path for security vulnerabilities.

**Usage:**
```
/security-scan
/security-scan src/
```

**Features:**
- Secrets detection (API keys, tokens, passwords)
- Dependency vulnerability checks
- OWASP code pattern scanning
- File permission checks
- Generates report with Critical/High/Medium/Low findings

### `/compact` - Session Handoff & Compact
Summarizes current session context into HANDOFF.md and compacts the conversation.

**Usage:**
```
/compact
/compact remember to fix the webhook parsing
```

**Features:**
- Gathers session context (tasks, files, decisions, what worked/didn't)
- Writes structured HANDOFF.md at project root
- Preserves context for the next session
- Runs `/compact` to free conversation context

### `/build-fix` - Build Fix Loop
Auto-detects the build system, runs the build, parses errors, and fixes them one at a time with regression detection.

**Usage:**
```
/build-fix
/build-fix src/
```

**Features:**
- Auto-detects npm/tsc/cargo/go/gradle/maven/pyproject/make
- Fixes one error at a time, rebuilds after each fix
- Stops if a fix introduces more errors (regression guard)
- Stops if the same error persists after 3 attempts
- Reports all fixes applied and remaining issues

### `/tdd` - Test-Driven Development
Enforces strict RED-GREEN-REFACTOR cycle for implementing a function or feature.

**Usage:**
```
/tdd implement a password strength validator
```

**Features:**
- Writes failing tests FIRST (RED phase)
- Implements minimal code to pass tests (GREEN phase)
- Refactors while keeping tests green (REFACTOR phase)
- Verifies each phase before moving to the next
- Reports coverage if available

### `/quality-gate` - Pre-Commit Quality Gate
Runs the project's required format, lint, type/build and behavioral checks with
receipts and explicit incomplete outcomes.

**Usage:**
```
/quality-gate
/quality-gate src/ --fix
/quality-gate --strict
```

**Features:**
- Discovers the project's own commands, scripts and CI policy (no tool downloads or fetching `npx`)
- Selects tests by affected behavior, dependencies and consumer contracts
- Runs behavioral checks even when formatting fails; `--fix` explicitly permits configured fixes, followed by rechecks
- `--strict` flag treats warnings as failures within this gate
- Reports PASS/FAIL/UNAVAILABLE/NOT_APPLICABLE per check and an overall FAIL, INCOMPLETE or PASS limited to the declared completed scope

### `/checkpoint` - Named Save Points
Creates named checkpoints during complex work for comparison and explicit recovery. A
checkpoint is a snapshot of the current working tree captured into a `refs/checkpoint/<name>`
ref by a helper (shipped in the installed `verified-handoff` skill) using Git plumbing — it
never runs `git stash`, switches branches, or touches your index or working tree.

**Usage:**
```
/checkpoint before-refactor
/checkpoint --verify before-refactor
/checkpoint --list
/checkpoint --diff before-refactor
```

**Features:**
- Snapshots staged, unstaged, deleted and non-ignored untracked files into a ref (not a branch); ignored files are excluded
- Records the current working-tree content, so staging intent is not retained separately (a file staged as A but present as B in the tree is captured as B)
- Verify/diff compares the current tree against a checkpoint and reports a verdict (BETTER/SAME/WORSE/MIXED)
- Recovery is always explicit — the helper prints the exact `git switch`/`git restore` commands and never restores for you
- Checkpoints survive across sessions as refs, so they are never checked out by accident
- Refuses before any change (reporting the reason) on states it cannot snapshot honestly — e.g. an existing checkpoint, unborn HEAD or merge in progress, submodules or a nested untracked repo, skip-worktree/assume-unchanged flags, a configured content filter, or an active ref/index hook

### `/save-session` - Save Session State
Saves structured session state to a global file with mandatory "What Did NOT Work" section.

**Usage:**
```
/save-session
/save-session auth-implementation
```

**Features:**
- Writes to `~/.claude/sessions/` (global, not in project root)
- Mandatory "What Did NOT Work" section with exact error messages
- Records goal, progress, decisions, next steps, and file states
- Prevents next session from retrying failed approaches

### `/resume-session` - Resume Session
Loads a previously saved session and produces a structured briefing.

**Usage:**
```
/resume-session
/resume-session auth-implementation
```

**Features:**
- Lists recent sessions if no ID given
- Validates current branch and file states against saved session
- Prominently displays "AVOID These Approaches" section
- Checks for files modified or deleted since the session was saved

### `/optimize` - Metric-Driven Improvement Loop
Runs an autonomous optimization loop that iteratively improves a measurable code metric.

**Usage:**
```
/optimize lint-warnings
/optimize type-errors --iterations 5
/optimize test-coverage --scope src/
/optimize custom:grep -r TODO src/ | wc -l
```

**Features:**
- Supports lint warnings, type errors, test coverage, bundle size, build time, custom metrics
- Measures baseline, then iteratively improves one change at a time
- Keeps improvements, reverts regressions automatically
- Stops on plateau (3 consecutive no-improvement iterations) or max iterations
- Reports summary with all changes applied and reverted
- Inspired by karpathy/autoresearch autonomous experimentation pattern

## Command Development

### Structure
Each command is a markdown file with:
1. YAML frontmatter (description, argument-hint)
2. Detailed instructions for Claude to follow
3. Examples and validation rules

### Testing Commands
Test commands by typing them in Claude Code's chat:
```
/command-name arguments
```

### Supporting Scripts
Command templates are self-contained Markdown instructions; the framework bundles no
tracker or publication credential scripts. A command that touches an issue tracker or CI
discovers the tool and its configuration at runtime (an MCP tool, a project-documented
CLI/API, or the project instructions) and acts only when an authorized connector exists.

### Best Practices
1. **Validate arguments** - Always check for required arguments
2. **Fail fast** - Show clear error messages immediately
3. **Be explicit** - Provide examples and usage patterns
4. **Discover, never hardcode** - Resolve base branch, tracker project and credentials from project configuration
5. **Handle errors** - Graceful error handling with helpful messages

## Troubleshooting

**Command not found:**
- Ensure file is in `.claude/commands/` directory
- Check YAML frontmatter is valid
- File must have `.md` extension

**Issue-tracker / publication errors:**
- Confirm the project actually exposes a tracker or CI connector (MCP tool, CLI/API, or project instructions) — with none available, `/create-jira` and `/commit-pr` hand back a draft/report rather than inventing a result
- Check that the authenticated account and credentials the environment already selects have the needed permissions
- Verify the project's configured base branch, project key and required checks resolve before relying on an automated update

## Contributing

To add a new command:

1. Create `.claude/commands/your-command.md`
2. Add YAML frontmatter with description and argument-hint
3. Write detailed instructions for Claude
4. Add examples and validation rules
5. Test thoroughly
6. Document in this README

## Resources

- [Claude Code Documentation](https://docs.claude.com/claude-code)
- [CLAUDE.md](../../CLAUDE.md) - Project context
- [Slash Commands Guide](https://docs.claude.com/claude-code/slash-commands)
