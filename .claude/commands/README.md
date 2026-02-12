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
