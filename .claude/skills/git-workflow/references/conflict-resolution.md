# Conflict Resolution — Advanced Patterns

Strategies for resolving merge conflicts effectively and preventing them from recurring.

---

## Understanding Conflict Types

### Content Conflicts
Two branches modify the same lines in the same file.

```
<<<<<<< HEAD
const timeout = 5000;
=======
const timeout = 10000;
>>>>>>> feature/update-timeout
```

**Resolution:** Understand the intent of both changes, pick the correct value (or combine them).

**Do not assume `HEAD` is your work.** Which side is yours depends on the operation in progress
(see [Ours/Theirs Invert Under Rebase](#ourstheirs-invert-under-rebase) below):

| Operation in progress | Top block (`<<<<<<< HEAD`) | Bottom block (`>>>>>>>`) |
|---|---|---|
| `git merge <other>` | **your** branch | `<other>` |
| `git rebase <upstream>` | **`<upstream>`** | **your** commit being replayed |

Run `git status` first — it names the operation and the branches — before deciding which block to keep.

### Structural Conflicts
One branch modifies a function while another branch moves or renames it.

**Resolution:** Requires understanding the full context — often needs manual reconstruction.

### Semantic Conflicts
Changes don't conflict textually but break logic when combined. Git won't detect these.

Example: Branch A adds a required parameter to a function, Branch B calls that function without the new parameter.

**Resolution:** Tests catch these — always run the full test suite after resolving conflicts.

---

## Resolution Strategies

### Strategy 1: Rebase and Resolve Incrementally

Best when your branch has many commits and conflicts span multiple changes.

```bash
git fetch origin
git rebase origin/main

# Conflicts appear one commit at a time
# Resolve each, then:
git add <resolved-files>
git rebase --continue

# To abort and start over — always safe, restores the pre-rebase state:
git rebase --abort
```

**Advantage:** Resolve conflicts in small, understandable chunks.

**During a rebase, `--ours` is the upstream and `--theirs` is your own work** — the opposite of a
merge. See [Ours/Theirs Invert Under Rebase](#ourstheirs-invert-under-rebase) before reaching for
either flag.

**`git rebase --skip` discards the entire commit being applied**, not just the conflicting hunk. Use
it only after confirming the commit is genuinely redundant — its changes are already present
upstream:

```bash
# Confirm the commit adds nothing before skipping it.
git show REBASE_HEAD                       # what you are about to drop
git diff REBASE_HEAD^ REBASE_HEAD          # empty output => already applied upstream, safe to skip
git rebase --skip
```

If the diff is not empty, `--skip` deletes real work. Resolve the conflict and
`git rebase --continue` instead. A commit dropped by `--skip` is still recoverable from
`git reflog` until it is garbage-collected.

### Strategy 2: Merge and Resolve All at Once

Best when conflicts are minor or your branch has few commits.

```bash
git fetch origin
git merge origin/main

# Resolve all conflicts
git add <resolved-files>
git commit  # Git provides a merge commit message
```

**Advantage:** Simpler, preserves full history.

### Strategy 3: Ours/Theirs for Bulk Resolution

When you know one side is entirely correct.

#### Ours/Theirs Invert Under Rebase

**`--ours` and `--theirs` mean the OPPOSITE thing during a rebase than during a merge.** They are
not named after branches — they are named after the checked-out side of the in-progress operation,
and a rebase checks out the *upstream* and replays your commits on top of it. So during
`git rebase main`, `--ours` is `main` and `--theirs` is **your own work**.

| Flag | During `git merge <other>` | During `git rebase <upstream>` |
|---|---|---|
| `--ours` (stage `:2:`) | **your** branch | **`<upstream>`** — NOT yours |
| `--theirs` (stage `:3:`) | `<other>` | **your** commits being replayed |

This is the single most destructive trap in conflict resolution: running `git checkout --ours` during
a rebase because you read "ours = mine" **silently discards your own work**, and because the file
then looks clean, nothing warns you. This skill recommends rebasing (Strategy 1, and "Rebase Before
Creating PR" below), so assume rebase semantics unless you have confirmed otherwise.

#### Resolve by branch name, not by flag

Do not reason in `--ours`/`--theirs`. Decide *which branch's version you want to keep* and confirm
which flag maps to it right now:

```bash
# 1. ALWAYS check which operation is in progress first — it decides the mapping.
git status                       # says "You are currently rebasing..." or "...merging..."

# 2. Print both sides and identify them by content before choosing.
git show :2:path/to/file.ts      # the "--ours" side  (merge: yours | rebase: upstream)
git show :3:path/to/file.ts      # the "--theirs" side (merge: other | rebase: YOURS)

# 3. Take the side you actually want, then stage it.
git checkout --theirs path/to/file.ts   # during a REBASE: keeps YOUR version
git add path/to/file.ts

git checkout --ours path/to/file.ts     # during a REBASE: keeps the UPSTREAM version
git add path/to/file.ts
```

**Guards:**
- Never run these flags from memory mid-rebase. Verify with `git show :2:` / `:3:` first — it costs
  one command and is the only thing standing between you and a silent loss of your work.
- `git checkout --ours|--theirs` overwrites the working-tree file with no confirmation and no
  backup. Only use it when you are certain one side is completely correct in its entirety.
- If you are unsure at any point, `git rebase --abort` (or `git merge --abort`) returns you to the
  pre-conflict state with nothing lost. Aborting is always cheaper than recovering discarded work.
- If you discover you took the wrong side after committing, your original commits are still in
  `git reflog` — recover with `git reflog` and `git branch <rescue-name> <sha>` before running
  anything else.

---

## Complex Conflict Patterns

### Lock File Conflicts (package-lock.json, yarn.lock)

Never manually resolve lock file conflicts, and never pick a side and stage it as-is. Resolve the
**manifest** first, then regenerate the lock file from it — regeneration overwrites whichever side
you started from, which is what makes this safe under both merge and rebase:

```bash
# 1. Resolve package.json by hand (it is the source of truth), then:
git add package.json

# 2. Regenerate the lock file from the resolved manifest.
npm install                      # or: yarn install / pnpm install
git add package-lock.json
```

If the tool refuses to run while the lock file still contains conflict markers, take either side
first — it is about to be overwritten — then regenerate:

```bash
git checkout --ours package-lock.json && npm install && git add package-lock.json
```

### Auto-Generated File Conflicts

For files generated by tools (migrations, schemas, codegen), regenerate rather than merge. As with
lock files, the side you start from is discarded by the generator, so `--ours` vs `--theirs` does
not matter here — but the **inputs** to the generator must be correctly resolved first:

```bash
# 1. Resolve the generator's SOURCE files first (schema, models, spec).
git add <resolved-source-files>

# 2. Regenerate, then stage the output.
npm run generate
git add <generated-file>
```

**Guard:** verify the regenerated output before staging (`git diff --staged <generated-file>`).
If the generator's inputs were resolved wrongly, the output is confidently wrong and will pass review.

### Rename/Modify Conflicts

When one branch renames a file and the other modifies it:

```bash
# Git may not detect the rename — check manually
git log --follow --diff-filter=R -- <old-path>

# Extract the old version to a SCRATCH path — never redirect straight onto <new-path>,
# which would clobber the renamed file's content with no backup and no undo.
git show HEAD:<old-path> > <new-path>.orig

# Merge <new-path>.orig into <new-path> by hand, then verify before staging.
git diff --no-index <new-path>.orig <new-path>
git add <new-path>
rm <new-path>.orig

# Only remove the old path once <new-path> is staged and verified to contain both changes.
git rm <old-path>
```

**Guard:** during a rebase, `HEAD` is the upstream, not your branch — confirm with `git status`
which side `HEAD:<old-path>` is actually giving you before merging it in.

---

## Prevention Strategies

### 1. Keep Branches Short-Lived
- The longer a branch lives, the more likely conflicts become
- Merge or rebase from main at least daily
- Break large features into smaller PRs

### 2. Communicate About Shared Files
- If you know another developer is modifying the same area, coordinate
- Use draft PRs to signal work in progress
- Review the active branch list before starting work on shared code

### 3. Reduce Shared Mutable State in Code
- Smaller, focused files reduce conflict surface area
- Avoid "god files" that everything depends on
- Use barrel exports (`index.ts`) carefully — they're frequent conflict sources

### 4. Consistent Formatting
- Use automated formatters (Prettier, Black, gofmt)
- Run formatters on save or pre-commit
- Eliminates conflicts caused by whitespace/formatting differences

### 5. Rebase Before Creating PR
```bash
# Always rebase before opening a PR
git fetch origin
git rebase origin/main
# Resolve any conflicts locally before the reviewer sees them
```

Because this makes rebase the default path, rebase conflict semantics are the ones you will meet
most often: `--ours` is `origin/main` and `--theirs` is your own work. See
[Ours/Theirs Invert Under Rebase](#ourstheirs-invert-under-rebase).

Rebasing rewrites your branch's commits. Only rebase a branch **you** are working on. Never rebase
a branch someone else has based work on, and never rebase `main` — publishing a rewritten shared
branch requires a force-push, which destroys the commits your collaborators already pulled.

---

## Tooling

### git mergetool
```bash
# Configure a merge tool
git config --global merge.tool vimdiff

# Launch during conflict resolution
git mergetool
```

### Useful Commands During Resolution
```bash
# See which files are conflicted
git diff --name-only --diff-filter=U

# Which operation is in progress — run this FIRST, it decides what :2:/:3: mean
git status

# See the common ancestor version
git show :1:path/to/file

# See the "ours" version   — merge: YOUR branch   | rebase: the UPSTREAM branch
git show :2:path/to/file

# See the "theirs" version — merge: the other branch | rebase: YOUR replayed commit
git show :3:path/to/file

# Abort a merge — restores the pre-merge state, nothing is lost
git merge --abort

# Abort a rebase — restores the pre-rebase state, nothing is lost
git rebase --abort
```

Stage `:2:` and `:3:` carry the same inversion as the `--ours`/`--theirs` flags
(see [Ours/Theirs Invert Under Rebase](#ourstheirs-invert-under-rebase)). Identify each side by its
**content**, not by its label.

### Rerere (Reuse Recorded Resolution)
Git can remember how you resolved a conflict and apply the same resolution automatically next time:

```bash
# Enable rerere
git config --global rerere.enabled true

# Git will now record and replay conflict resolutions
```
