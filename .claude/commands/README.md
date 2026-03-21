# Claude Code Commands

This directory contains custom slash commands for streamlined development workflows.

## Available Commands

### `/new-feature` - Create Feature Branch
Creates a new feature branch from the latest master branch.

**Usage:**
```
/new-feature PROJ-XXX description
```

**Example:**
```
/new-feature PROJ-755 add-export-functionality
```

### `/commit-pr` - Commit and Create PR
Stages changes, commits, pushes, creates GitHub PR, and auto-updates JIRA ticket.

**Usage:**
```
/commit-pr [optional commit message]
```

**Features:**
- Auto-extracts JIRA ticket from branch name
- Creates GitHub PR with detailed summary
- Auto-updates JIRA ticket with PR link
- Transitions ticket to "Ready For Release"

### `/create-jira` - Create JIRA Issue
Creates a new JIRA issue (Epic or Story/Task) and assigns it to you.

**Usage:**
```
/create-jira epic <Title Here>
/create-jira story <EPIC-KEY> <Title Here>
/create-jira task <EPIC-KEY> <Title Here>
```

**Examples:**
```
/create-jira epic Improve Dashboard Performance
/create-jira story PROJ-753 Add filter functionality to alerts
/create-jira task PROJ-905 Fix mobile responsiveness
```

**Features:**
- Auto-assigns to current git user
- Creates Epic or Story/Task under Epic
- Adds "claude-created" label
- Returns clickable JIRA URL

### `/review-pr` - Review Pull Request
Reviews a pull request for code quality, security (OWASP), testing, and documentation.

**Usage:**
```
/review-pr 123
```

**Features:**
- Fetches PR details and diff via `gh`
- Analyzes code quality, security, testing, docs
- Generates structured report (Critical/Suggestions/Nits)
- Optionally posts review as GitHub comment

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
Runs formatter, linter, type checker, and tests as a comprehensive quality check.

**Usage:**
```
/quality-gate
/quality-gate src/ --fix
/quality-gate --strict
```

**Features:**
- Auto-detects language and tooling (TS/JS, Python, Go, Rust)
- Runs format check, lint, type check, and tests in order
- `--fix` flag auto-fixes formatting and lint issues
- `--strict` flag treats warnings as errors
- Reports PASS/FAIL for each check

### `/checkpoint` - Named Save Points
Creates named checkpoints during complex work for easy comparison and rollback.

**Usage:**
```
/checkpoint before-refactor
/checkpoint --verify before-refactor
/checkpoint --list
/checkpoint --diff before-refactor
```

**Features:**
- Creates lightweight git branches as save points
- Verify mode compares current state against a checkpoint
- Shows file changes, test results, and overall verdict (BETTER/WORSE/SAME)
- Checkpoints survive across sessions (git branches)

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
Commands may use Node.js scripts in `/scripts/` directory:
- `create-jira-issue.mjs` - JIRA issue creation
- `update-jira-on-pr.ts` - JIRA ticket updates

### Best Practices
1. **Validate arguments** - Always check for required arguments
2. **Fail fast** - Show clear error messages immediately
3. **Be explicit** - Provide examples and usage patterns
4. **Return JSON** - Scripts should return structured JSON
5. **Handle errors** - Graceful error handling with helpful messages

## Troubleshooting

**Command not found:**
- Ensure file is in `.claude/commands/` directory
- Check YAML frontmatter is valid
- File must have `.md` extension

**Script errors:**
- Check Node.js version compatibility (ESM modules required)
- Verify database credentials in script
- Check script has execute permissions: `chmod +x script.mjs`

**JIRA errors:**
- Verify git user.email matches your JIRA user
- Check JIRA instance configuration
- Ensure user has JIRA permissions

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
- [CLAUDE.md](../CLAUDE.md) - Project context
- [Slash Commands Guide](https://docs.claude.com/claude-code/slash-commands)
