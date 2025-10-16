#!/bin/bash

# Claude Agents - Minimal CLAUDE.md Installer
# Adds auto-activating agent configuration to projects

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Minimal CLAUDE.md content
read -r -d '' MINIMAL_CLAUDE_MD << 'EOF' || true
# CLAUDE.md

## 🤖 Auto-Activating AI Agents

This project has specialized AI agents that **automatically activate** when you describe tasks in natural language.

### 🚀 Just Use Natural Language - Agents Auto-Activate

| Say This | Agent Activates | Does This |
|----------|-----------------|-----------|
| "design the system" | **architecture-planner** | Creates system design & API specs |
| "review the code" | **code-quality** | Reviews code quality & suggests improvements |
| "check security" | **security-auditor** 🔴 | Scans vulnerabilities (Opus) |
| "write tests" | **test-automation** | Generates comprehensive tests |
| "running slow" | **performance-optimizer** | Profiles & optimizes performance |
| "deploy to production" | **devops-automation** | Handles CI/CD & deployment |
| "document this" | **documentation-maintainer** | Creates docs (Haiku - 95% cheaper) |
| "design database" | **database-architect** | Optimizes schemas & queries |
| "create UI" | **frontend-specialist** | Builds responsive components |
| "create API" | **api-backend** | Implements backend services |
| "production is down!" | **incident-commander** 🚨 | Emergency response (Opus) |

### 💡 Example

```
You: "I need to build a user authentication system"
```

**Auto-triggers:**
1. **architecture-planner** → Designs the system
2. **api-backend** → Implements authentication logic
3. **database-architect** → Creates user schema
4. **security-auditor** → Ensures secure implementation
5. **test-automation** → Generates tests
6. **documentation-maintainer** → Documents the API

### 🔒 Security First

- **security-auditor** & **incident-commander** always use Opus for maximum intelligence
- All agents follow OWASP & DevSecOps best practices
- Security scanning activates automatically on auth/security keywords

---

*No configuration needed. Just describe what you want to build.*
EOF

# Append section for existing files
read -r -d '' APPEND_SECTION << 'EOF' || true

<!-- ============ CLAUDE AGENTS AUTO-ACTIVATION SECTION START ============ -->

## 🤖 Auto-Activating AI Agents

**NEW:** This project has specialized agents that auto-activate based on natural language.

### Quick Reference - Just Say What You Need

- **Planning:** "design", "architecture" → `architecture-planner`
- **Quality:** "review", "refactor" → `code-quality`
- **Security:** "security", "auth" → `security-auditor` (Opus)
- **Testing:** "test", "coverage" → `test-automation`
- **Performance:** "slow", "optimize" → `performance-optimizer`
- **Deployment:** "deploy", "CI/CD" → `devops-automation`
- **Docs:** "document", "README" → `documentation-maintainer` (Haiku -95%)
- **Database:** "SQL", "schema" → `database-architect`
- **Frontend:** "UI", "React" → `frontend-specialist`
- **Backend:** "API", "endpoint" → `api-backend`
- **Emergency:** "CRITICAL", "outage" → `incident-commander` (Opus)

**Example:** Say "build a REST API with authentication" and watch multiple agents collaborate automatically.

<!-- ============ CLAUDE AGENTS AUTO-ACTIVATION SECTION END ============ -->
EOF

echo -e "${BLUE}🤖 Claude Agents - CLAUDE.md Configuration Installer${NC}"
echo ""

# Check if CLAUDE.md exists
if [ -f "CLAUDE.md" ]; then
    echo -e "${YELLOW}📄 Existing CLAUDE.md found${NC}"

    # Check if agents section already exists
    if grep -q "Auto-Activating AI Agents" CLAUDE.md 2>/dev/null; then
        echo -e "${GREEN}✅ Agent configuration already present in CLAUDE.md${NC}"
        echo "Nothing to do - agents are ready to use!"
        exit 0
    fi

    # Ask user what to do
    echo ""
    echo "Options:"
    echo "1) Append agent configuration to existing CLAUDE.md"
    echo "2) Show the configuration (manual copy/paste)"
    echo "3) Cancel"
    echo ""
    read -p "Choose an option [1-3]: " choice

    case $choice in
        1)
            # Backup existing file
            cp CLAUDE.md CLAUDE.md.backup
            echo -e "${BLUE}📦 Created backup: CLAUDE.md.backup${NC}"

            # Append the section
            echo "$APPEND_SECTION" >> CLAUDE.md
            echo -e "${GREEN}✅ Agent configuration added to CLAUDE.md${NC}"
            ;;
        2)
            echo ""
            echo "Copy this section to your CLAUDE.md:"
            echo "========================================"
            echo "$APPEND_SECTION"
            echo "========================================"
            ;;
        3)
            echo "Installation cancelled"
            exit 0
            ;;
        *)
            echo "Invalid option"
            exit 1
            ;;
    esac
else
    echo -e "${BLUE}📝 Creating new CLAUDE.md with agent configuration${NC}"
    echo "$MINIMAL_CLAUDE_MD" > CLAUDE.md
    echo -e "${GREEN}✅ CLAUDE.md created successfully${NC}"
fi

echo ""
echo -e "${GREEN}🚀 Setup Complete!${NC}"
echo ""
echo "Just use natural language and agents will auto-activate:"
echo '  Say: "I need to build a login system"'
echo '  Say: "Check this code for security issues"'
echo '  Say: "Write tests for the payment module"'
echo ""
echo -e "${BLUE}No configuration needed - just describe what you want to build!${NC}"