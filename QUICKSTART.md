# 🚀 60-Second Quickstart

**Use these examples in your Claude CLI session.**

## Example 1: Create an API (30 seconds)

```bash
# Optional: Check which agent would handle this
.claude/router.sh "Create a REST API for a todo app"
# Output: 🏗️ Architect [S] recommended

# In Claude CLI:
claude> Create a REST API for a todo app with CRUD operations
```

**You get:**
```javascript
// api/todos.js - Complete REST API
GET    /api/todos       - List all todos
POST   /api/todos       - Create todo
GET    /api/todos/:id   - Get single todo
PUT    /api/todos/:id   - Update todo
DELETE /api/todos/:id   - Delete todo
```

With validation, error handling, and tests. Done.

## Example 2: Fix a Bug (20 seconds)

```bash
# Optional: Check recommendation
.claude/router.sh "Fix login bug"
# Output: 🛡️ Guardian [S] recommended

# In Claude CLI:
claude> My login function returns undefined sometimes
```

**What happens:**
1. Guardian finds the bug
2. Shows you the fix
3. Adds tests to prevent it
4. Explains why it happened

## Example 3: Add Security (25 seconds)

```bash
# Optional: Check recommendation
.claude/router.sh "Add JWT authentication"
# Output: 🏗️ Architect [S] for JWT implementation

# In Claude CLI:
claude> Add authentication to my API endpoints
```

**You get:**
- JWT authentication
- Protected routes
- Rate limiting
- Input validation
- Security headers

## Example 4: Make It Fast (15 seconds)

```bash
# Optional: Check recommendation
.claude/router.sh "Optimize database performance"
# Output: 🛡️ Guardian [O] for complex optimization

# In Claude CLI:
claude> This page loads slowly
```

**Guardian does:**
- Profiles the code
- Finds bottlenecks
- Implements caching
- Optimizes queries
- Lazy loads components

## Example 5: Deploy It (30 seconds)

```bash
# Optional: Check recommendation
.claude/router.sh "Deploy to Vercel"
# Output: 🔌 Connector [H] for simple deployment

# In Claude CLI:
claude> Deploy this to Vercel
```

**Connector handles:**
- Build configuration
- Environment variables
- CI/CD setup
- Monitoring
- Rollback strategy

## Common Patterns

### Building Features
```bash
Create a [thing]           → 🏗️ Architect [S/O]
Add [feature] to [thing]   → 🏗️ Architect [S]
Connect [A] to [B]         → 🔌 Connector [H/S]
```

### Fixing Problems
```bash
Fix [issue]                → 🛡️ Guardian [S]
[X] is not working         → 🛡️ Guardian [S]
Getting error: [message]   → 🛡️ Guardian [S/O]
```

### Improving Code
```bash
Make this faster           → 🛡️ Guardian [O]
Reduce memory usage        → 🛡️ Guardian [O]
Improve security           → 🛡️ Guardian [O]
```

### Understanding Code
```bash
Explain this function      → 📝 Documenter [H]
How does [X] work?         → 📝 Documenter [H]
Document this API          → 📝 Documenter [H]
```

## Real Project Example

Starting a new project from scratch:

```bash
# 1. Create project
claude> Create a task management app with React and Node.js
# 🏗️ Architect [S] builds full-stack structure

# 2. Add features
claude> Add user authentication with JWT
# 🏗️ Architect [S] implements auth system

# 3. Test it
claude> Write tests for all endpoints
# 🛡️ Guardian [S] creates comprehensive tests

# 4. Optimize
claude> Optimize for mobile devices
# 🛡️ Guardian [S] improves performance

# 5. Deploy
claude> Deploy to production with GitHub Actions
# 🔌 Connector [S] sets up CI/CD
```

**Pro tip**: Check recommendations first with:
```bash
.claude/router.sh "your task"
```

Total time: ~5 minutes for a production-ready app.

## Tips for Best Results

### Be Specific
❌ "Make a form"
✅ "Create a contact form with email validation"

### Describe the Problem
❌ "Fix it"
✅ "The form submits even with invalid email"

### State Your Goal
❌ "Change the database"
✅ "Migrate from MongoDB to PostgreSQL"

## What Each Agent Does Best

### Architect (Builder)
- API design
- Database schemas
- Component architecture
- System design
- Code generation

### Guardian (Protector)
- Security audits
- Performance optimization
- Bug fixes
- Test writing
- Code quality

### Connector (Integrator)
- Third-party APIs
- Deployment
- CI/CD
- Cloud services
- Webhooks

### Documenter (Explainer)
- Code documentation
- API docs
- README files
- Code comments
- Architecture diagrams

## Workflow Examples

### Feature Development
```
You: "Add shopping cart to my e-commerce site"
1. Architect designs cart system
2. Guardian adds validation
3. Connector integrates payment
4. Documenter updates API docs
```

### Bug Fix
```
You: "Users can't reset passwords"
1. Guardian identifies issue
2. Guardian fixes code
3. Guardian adds tests
4. Documenter updates changelog
```

### Performance
```
You: "Homepage takes 5 seconds to load"
1. Guardian profiles page
2. Guardian optimizes images
3. Guardian adds caching
4. Guardian lazy loads components
```

## Advanced Examples

### Complex Integration
```bash
claude> "Integrate Stripe payments with webhook handling and refunds"
```

### System Migration
```bash
claude> "Migrate from Express to Fastify with zero downtime"
```

### Architecture Refactor
```bash
claude> "Convert monolith to microservices architecture"
```

### Real-time Features
```bash
claude> "Add real-time chat with typing indicators and read receipts"
```

## Shortcuts

Use these keywords for faster routing:

- **"create"** → Architect
- **"fix"** → Guardian
- **"deploy"** → Connector
- **"explain"** → Documenter
- **"test"** → Guardian
- **"secure"** → Guardian
- **"integrate"** → Connector
- **"document"** → Documenter

## Getting Help

```bash
# Check status
.claude/router.sh status

# See what agents are doing
.claude/router.sh debug

# View learning history
.claude/router.sh history

# Reset if needed
.claude/router.sh reset
```

## Remember

- **Natural language** - Just describe what you want
- **No commands** - The system figures out what to do
- **Learns patterns** - Gets better as you use it
- **Zero config** - Works out of the box

---

**Ready?** Just type what you want to build!