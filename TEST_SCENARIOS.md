# Claude Code Agents - Test Scenarios

## 🧪 Automatic Activation Tests

### Scenario 1: API Development
**User Input:** "I need to create a REST API for user authentication"

**Expected Behavior:**
1. ✅ `api-builder` activates (keywords: REST API)
2. ✅ Creates authentication endpoints
3. ✅ Handoff to `test-engineer` 
4. ✅ Tests written automatically
5. ✅ Handoff to `secure-coder`
6. ✅ Security review performed
7. ✅ Tracking logs all steps

### Scenario 2: Database Schema Design
**User Input:** "Design a PostgreSQL schema for an e-commerce platform"

**Expected Behavior:**
1. ✅ `database-architect` activates (keywords: PostgreSQL, schema)
2. ✅ Creates normalized tables
3. ✅ Defines indexes and constraints
4. ✅ Handoff to `api-builder` for model creation
5. ✅ Tracking captures token usage

### Scenario 3: Performance Issue
**User Input:** "The dashboard is loading slowly, there's a bottleneck somewhere"

**Expected Behavior:**
1. ✅ `performance-optimizer` activates (keywords: slowly, bottleneck)
2. ✅ Analyzes performance issues
3. ✅ Parallel activation with `database-architect` if query issues
4. ✅ Handoff to `refactor-specialist` for fixes
5. ✅ Cost tracked (Opus model = higher cost)

### Scenario 4: Security Vulnerability
**User Input:** "Check for XSS vulnerabilities in the login form"

**Expected Behavior:**
1. ✅ `secure-coder` activates (keywords: XSS, vulnerabilities)
2. ✅ Reviews security issues
3. ✅ Fixes vulnerabilities
4. ✅ Handoff to `test-engineer` for security tests
5. ✅ GitHub issue created (if enabled)

### Scenario 5: Frontend Development
**User Input:** "Build a React component for user profile with Redux state management"

**Expected Behavior:**
1. ✅ `frontend-architect` activates (keywords: React, Redux)
2. ✅ Creates component structure
3. ✅ Implements state management
4. ✅ Parallel with `ui-ux-specialist` for design
5. ✅ Handoff to `test-engineer`

## 🔄 Workflow Command Tests

### Test 1: Feature Workflow
**Command:** `/workflow feature user-authentication`

**Expected Chain:**
```
project-coordinator → Plans implementation
↓
database-architect → User table schema
↓
api-builder → Auth endpoints
↓
frontend-architect → Login components
↓
test-engineer → Test coverage
↓
secure-coder → Security validation
↓
deployment-engineer → Deploy to staging
```

### Test 2: Bug Fix Workflow
**Command:** `/workflow bug performance-dashboard`

**Expected Chain:**
```
performance-optimizer → Identify bottlenecks
↓
refactor-specialist → Optimize code
↓
test-engineer → Validate fixes
↓
deployment-engineer → Deploy hotfix
```

### Test 3: Quality Check
**Command:** `/quality-check`

**Expected Parallel Execution:**
```
secure-coder ─┐
              ├→ Quality Report
performance-optimizer ─┤
              │
refactor-specialist ─┤
              │
test-engineer ─┘
```

## 📊 Tracking System Tests

### Test 1: Basic Tracking
**Action:** Run any agent task

**Verify:**
- ✅ `.claude/metrics/metrics-YYYY-MM-DD.csv` created
- ✅ Task logged with timestamp
- ✅ Token usage recorded
- ✅ Status tracked (in_progress → completed)

### Test 2: Cost Calculation
**Action:** Complete tasks with different models

**Verify:**
- ✅ Haiku tasks = $0.80/1M tokens
- ✅ Sonnet tasks = $3/1M tokens  
- ✅ Opus tasks = $15/1M tokens
- ✅ `.claude/metrics/token-costs.csv` updated

### Test 3: GitHub Integration
**Setup:** `.claude/scripts/tracking.sh enable github`

**Verify:**
- ✅ GitHub issue created for new tasks
- ✅ Labels applied (agent:*, status:*)
- ✅ Comments added for handoffs
- ✅ Issues closed on completion

### Test 4: Dashboard
**Command:** `.claude/scripts/dashboard.sh`

**Verify:**
- ✅ Shows today's summary
- ✅ Agent performance metrics
- ✅ Token usage by model
- ✅ Recent activity feed
- ✅ Workflow chains displayed

## 🚀 Installation Tests

### Test 1: Clean Installation
```bash
git clone https://github.com/pfangueiro/claude-code-agents.git
cd claude-code-agents
./install.sh ~/test-project
```

**Verify:**
- ✅ `.claude/` directory copied
- ✅ `CLAUDE.md` template created
- ✅ Scripts are executable
- ✅ Tracking initialized

### Test 2: Existing Project
**Setup:** Project with existing `.claude/` directory

**Verify:**
- ✅ Prompts for merge/overwrite
- ✅ Backs up existing CLAUDE.md
- ✅ Preserves user customizations

### Test 3: Missing Dependencies
**Setup:** System without jq, bc, uuidgen

**Verify:**
- ✅ Warnings displayed for optional deps
- ✅ Installation continues
- ✅ Fallback mechanisms work

## 🔗 Integration Tests

### Test 1: Multi-Agent Collaboration
**Input:** "Create a complete user management system"

**Expected Flow:**
1. `project-coordinator` orchestrates
2. `database-architect` + `api-builder` work in parallel
3. `frontend-architect` + `ui-ux-specialist` collaborate
4. `test-engineer` validates all components
5. `secure-coder` reviews security
6. `deployment-engineer` deploys

**Verify:**
- ✅ All handoffs tracked
- ✅ Parallel execution works
- ✅ Context preserved between agents
- ✅ Total cost calculated correctly

### Test 2: Error Handling
**Scenario:** Agent fails mid-task

**Verify:**
- ✅ Failure logged in metrics
- ✅ GitHub issue updated with failure
- ✅ Handoff chain interrupted gracefully
- ✅ Dashboard shows failed task

### Test 3: Context Overflow
**Scenario:** Long conversation approaching token limit

**Verify:**
- ✅ Agents reference CLAUDE.md for context
- ✅ Handoffs transfer minimal context
- ✅ `/clear` command suggested
- ✅ Performance not degraded

## ✅ Validation Checklist

### Pre-Deployment
- [ ] All 18 agents have model parameters
- [ ] All agents have 8+ activation keywords
- [ ] Handoff protocols consistent
- [ ] Tracking hooks executable
- [ ] Installation script validated
- [ ] Dependencies documented

### Post-Installation
- [ ] Agents activate on keywords
- [ ] Workflows execute correctly
- [ ] Tracking captures metrics
- [ ] Dashboard displays data
- [ ] GitHub integration works (optional)
- [ ] Cost calculations accurate

### Performance
- [ ] Agents activate within 2 seconds
- [ ] Handoffs complete successfully
- [ ] Parallel execution works
- [ ] Token usage optimized
- [ ] No context overflow issues

## 🎯 Success Criteria

The system is considered fully functional when:

1. **80%+ keyword activation success** - Agents activate correctly on relevant keywords
2. **95%+ handoff success** - Inter-agent communication works reliably
3. **100% tracking capture** - All agent activities are logged
4. **Accurate cost tracking** - Token costs match model pricing
5. **Zero manual intervention** - Everything works automatically

## 🐛 Known Issues & Workarounds

### Issue 1: UUID Generation on Linux
**Problem:** Some Linux systems don't have `uuidgen`
**Workaround:** Falls back to timestamp-based IDs

### Issue 2: GitHub Rate Limiting
**Problem:** Too many API calls to GitHub
**Workaround:** Batch issue updates or disable GitHub tracking

### Issue 3: Large CLAUDE.md Files
**Problem:** Project CLAUDE.md exceeds 5k tokens
**Workaround:** Split into multiple files or use references

---

*Run these tests after any major changes to ensure system integrity*