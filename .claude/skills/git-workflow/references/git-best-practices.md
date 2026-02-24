# Git Best Practices

Comprehensive guidelines for professional git usage.

---

## Commit Hygiene

### Atomic Commits
- Each commit should represent one logical change
- If you can describe your commit with "and", split it into two commits
- A commit should be independently revertable without breaking other changes

### Commit Messages
- Use imperative mood in the subject line: "Add feature" not "Added feature"
- Keep subject line under 72 characters
- Separate subject from body with a blank line
- Use the body to explain **what** and **why**, not **how**
- Reference issue numbers in the footer

### What NOT to Commit
- Secrets, API keys, tokens, passwords (use `.env` + `.gitignore`)
- Build artifacts, compiled output, `node_modules/`
- IDE/editor-specific files (add to global `.gitignore`)
- Large binary files (use Git LFS if needed)
- Temporary or debug files

---

## Branch Management

### Naming Conventions
```
feature/TICKET-123-add-user-auth
fix/TICKET-456-null-pointer-in-search
hotfix/critical-payment-failure
chore/update-dependencies
docs/api-documentation
refactor/simplify-auth-flow
```

### Keep Branches Short-Lived
- Feature branches should live days, not weeks
- Long-lived branches accumulate merge debt
- Break large features into smaller, mergeable increments
- Use feature flags for incomplete features

### Branch Cleanup
```bash
# Delete merged local branches
git branch --merged main | grep -v "main" | xargs git branch -d

# Delete remote tracking branches that no longer exist
git fetch --prune
```

---

## Pull Requests

### Before Creating a PR
1. Rebase on latest main: `git fetch origin && git rebase origin/main`
2. Run all tests locally
3. Self-review your diff: `git diff main...HEAD`
4. Remove debug code, console.log, TODO hacks
5. Ensure CI will pass

### PR Size
- Aim for < 400 lines changed
- Smaller PRs get reviewed faster and more thoroughly
- If a PR is large, break it into stacked PRs
- Each PR should be independently deployable (if possible)

### PR Review Etiquette
- Respond to all comments, even if just acknowledging
- Resolve conversations after addressing feedback
- Don't force-push after review has started (use fixup commits)
- Squash fixup commits before merge

---

## History Management

### When to Rebase vs Merge
- **Rebase** your feature branch onto main (keeps linear history)
- **Merge** main into your branch only as a last resort
- **Never rebase** shared/published branches
- **Squash merge** PRs for clean main history

### Preserving History
- Don't rewrite history that others have based work on
- Use `git revert` instead of `git reset` for public commits
- Tag releases for easy reference: `git tag -a v1.0.0 -m "Release 1.0.0"`

---

## .gitignore Strategy

### Global gitignore (per developer)
```bash
# Set up global gitignore
git config --global core.excludesfile ~/.gitignore_global
```

Contents of `~/.gitignore_global`:
```
# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
```

### Project gitignore
- Include language/framework-specific patterns
- Use [gitignore.io](https://www.toptal.com/developers/gitignore) for templates
- Keep it organized with section comments

---

## Security

- Enable signed commits: `git config --global commit.gpgsign true`
- Use SSH keys (not HTTPS passwords) for remote access
- Rotate deploy keys periodically
- Audit repository access permissions regularly
- Use branch protection rules on main/production branches
- Require PR reviews before merge
- Require status checks to pass before merge
