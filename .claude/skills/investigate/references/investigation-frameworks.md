# Investigation Frameworks — Reference

## 1. The 5 Whys Method

Iteratively ask "why?" to drill past symptoms to root causes. Stop when you reach a systemic issue (process, architecture, or design flaw).

### Template

```
Symptom: <observable problem>
Why 1: <immediate cause> — Evidence: <what proves this>
Why 2: <cause of Why 1> — Evidence: <what proves this>
Why 3: <cause of Why 2> — Evidence: <what proves this>
Why 4: <cause of Why 3> — Evidence: <what proves this>
Why 5: <cause of Why 4> — Evidence: <what proves this>
ROOT CAUSE: <systemic issue that, if fixed, prevents recurrence>
```

### Rules
- Every "why" answer must cite evidence (file:line, log entry, git commit, test result)
- If a "why" has multiple possible answers, branch and investigate each
- Stop when the answer is actionable (something you can change in the codebase)
- Typically 3-7 iterations — don't force exactly 5

### Example: Core Data Crash

```
Symptom: App crashes when tapping a document after deleting another
Why 1: DocumentDetailView accesses properties of a deleted NSManagedObject
  Evidence: crash log shows fault on managedObject.vendorName, object isFault=true
Why 2: context.delete() was called while SwiftUI still holds a reference to the object
  Evidence: DocumentListViewModel.deleteDocument() calls context.delete() directly
Why 3: SwiftUI's @FetchRequest re-renders with stale objects before the delete propagates
  Evidence: Adding a 0.1s delay after delete prevents the crash (timing-dependent)
Why 4: No soft-delete pattern exists — objects are immediately hard-deleted
  Evidence: grep -r "context.delete" shows 3 call sites, none use pendingDelete
Why 5: The deletion architecture wasn't designed for SwiftUI's reactive data binding
  Evidence: Original code used UIKit with manual table view updates

ROOT CAUSE: Hard-delete pattern incompatible with SwiftUI's reactive @FetchRequest.
FIX: Implement soft-delete (syncStatus = "pendingDelete") + scheduled hard-delete.
```

---

## 2. Fishbone (Ishikawa) Diagram Categories

When a bug has unclear origins, categorize potential causes systematically.

### Software Bug Categories

| Category | What to Check |
|----------|--------------|
| **Code Logic** | Wrong condition, off-by-one, missing null check, wrong operator, incorrect algorithm |
| **Data State** | Unexpected nil/null, wrong type, stale cache, corrupted state, empty collection |
| **Timing / Race** | Async completion order, missing await, concurrent mutation, UI thread violation |
| **Environment** | OS version, device type, memory pressure, network state, disk space, permissions |
| **Dependencies** | Library version mismatch, deprecated API, breaking change, missing dependency |
| **Configuration** | Wrong endpoint, expired key, wrong build target, missing feature flag, stale config |

### Usage in Phase 4

For each category, ask: "Could a problem in this category cause the observed symptom?" Generate at least one hypothesis per relevant category.

---

## 3. Git Forensics Toolkit

Git history is a time machine for bugs. Use it to find WHEN, WHO, and WHY.

### When Was the Bug Introduced?

```bash
# Recent changes to affected files
git log --oneline -20 -- <file>

# Who last changed the suspicious lines
git blame -L <start>,<end> <file>

# What changed in the last N days
git log --since="7 days ago" --oneline --stat

# Binary search for the commit that introduced a bug
git bisect start
git bisect bad HEAD
git bisect good <known-good-commit>
# Then test at each step until the culprit is found
```

### What Changed Between Working and Broken?

```bash
# Diff between last known working state and now
git diff <good-commit>..HEAD -- <file>

# List all files changed between two points
git diff --name-only <good-commit>..HEAD

# Show the full commit that introduced the change
git show <commit-hash>
```

### Correlation: Did the Bug Start with a Specific Change?

```bash
# Find commits that modified a specific function
git log -p --all -S '<function-name>' -- '*.swift'

# Find commits that changed a specific string
git log --all --oneline -S '<error-string>'
```

---

## 4. Evidence Classification

Every piece of evidence should be classified by strength.

| Strength | Type | Example |
|----------|------|---------|
| **Strong** | Reproduction | "Run this test → crash every time" |
| **Strong** | Code proof | "Line 42 calls delete() without checking isDeleted" |
| **Strong** | Git blame | "Commit abc123 introduced this line 3 days ago, bug started 3 days ago" |
| **Medium** | Logs | "Error log shows this message at the time of crash" |
| **Medium** | Correlation | "Bug appeared after deploying version X" |
| **Weak** | Absence | "No null check exists, so null might be possible" |
| **Weak** | Similarity | "Another function had the same bug pattern" |

### Hypothesis Confidence Levels

- **High (>80%):** Multiple strong evidence pieces, no contradictions
- **Medium (50-80%):** Mix of strong and medium evidence, minor uncertainties
- **Low (<50%):** Mostly weak evidence, alternative explanations exist
- **Eliminated:** Contradicted by strong evidence

---

## 5. Project-Specific Root Cause Patterns

Add patterns discovered in your project here. Each entry should follow this template:

```
### <Pattern Name>
- **Symptom:** <what the user observes>
- **Root cause:** <the deepest systemic issue>
- **Fix:** <the corrective action>
- **Memory ref:** MEMORY.md "<relevant section>"
```

As you investigate bugs, document recurring patterns in this section so future investigations can check known causes first.

---

## 6. Multi-Pass Investigation Pattern

For complex issues where the cause isn't obvious after initial investigation.

### Pass 1: Broad Sweep (Explore agent)
- Search the entire codebase for the error pattern
- Identify all files in the affected area
- List all entry points to the failing code

### Pass 2: Deep Read (Read tool)
- Read every file identified in Pass 1 completely
- Trace data flow line by line
- Document every assumption the code makes

### Pass 3: External Research (WebSearch + context7)
- Search for known issues in the library/framework version
- Check official docs for correct API usage
- Look at GitHub issues for the dependency

### Pass 4: Hypothesis Testing (sequential-thinking MCP)
- Form hypotheses based on Passes 1-3
- Use structured reasoning to test each
- Arrive at confirmed root cause

---

## 7. Sequential-Thinking MCP Usage for Investigation

### Starting the Analysis

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "OBSERVE: The symptom is [X]. Evidence gathered: [list]. Let me trace the execution path...",
  thoughtNumber: 1,
  totalThoughts: 10,
  nextThoughtNeeded: true
})
```

### 5 Whys Chain

```javascript
// Why 1
mcp__sequential-thinking__sequentialthinking({
  thought: "WHY 1: The crash occurs because [X]. Evidence: [code at file:line]. But why does X happen?",
  thoughtNumber: 3,
  totalThoughts: 12,
  nextThoughtNeeded: true
})

// Why 2
mcp__sequential-thinking__sequentialthinking({
  thought: "WHY 2: X happens because [Y]. Evidence: [git blame shows...]. But why does Y happen?",
  thoughtNumber: 4,
  totalThoughts: 12,
  nextThoughtNeeded: true
})
```

### Branching for Alternative Hypotheses

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "ALTERNATIVE: What if the cause is not [A] but [B]? Let me check evidence for B...",
  thoughtNumber: 6,
  totalThoughts: 12,
  nextThoughtNeeded: true,
  branchFromThought: 4,
  branchId: "hypothesis-B"
})
```

### Revising After New Evidence

```javascript
mcp__sequential-thinking__sequentialthinking({
  thought: "REVISION: My initial hypothesis was wrong — evidence at file:line shows [C] instead. Updating causal chain...",
  thoughtNumber: 8,
  totalThoughts: 14,
  nextThoughtNeeded: true,
  isRevision: true,
  revisesThought: 5
})
```
