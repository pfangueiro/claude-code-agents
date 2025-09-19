#!/bin/bash
# Claude Agents - Zero Config Installation
# One command. Just works.

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Simple banner
echo -e "${BLUE}╔══════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Claude Agents Installation     ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════╝${NC}"
echo

# Detect project type automatically
detect_project() {
    if [ -f "package.json" ]; then
        if grep -q "react" package.json 2>/dev/null; then
            echo "react"
        elif grep -q "next" package.json 2>/dev/null; then
            echo "nextjs"
        elif grep -q "express" package.json 2>/dev/null; then
            echo "node-api"
        else
            echo "nodejs"
        fi
    elif [ -f "requirements.txt" ] || [ -f "pyproject.toml" ]; then
        if [ -f "manage.py" ]; then
            echo "django"
        elif grep -q "fastapi" requirements.txt 2>/dev/null || grep -q "fastapi" pyproject.toml 2>/dev/null; then
            echo "fastapi"
        else
            echo "python"
        fi
    elif [ -f "Cargo.toml" ]; then
        echo "rust"
    elif [ -f "go.mod" ]; then
        echo "go"
    elif [ -f "pom.xml" ] || [ -f "build.gradle" ]; then
        echo "java"
    elif [ ! "$(ls -A 2>/dev/null)" ]; then
        echo "new"
    else
        echo "generic"
    fi
}

PROJECT_TYPE=$(detect_project)
echo -e "${GREEN}✓${NC} Detected project type: ${BLUE}$PROJECT_TYPE${NC}"

# Create minimal structure
echo -e "${BLUE}→${NC} Creating .claude directory..."
mkdir -p .claude/agents
mkdir -p .claude/history

# Create the 4 core agents
echo -e "${BLUE}→${NC} Installing 4 AI agents..."

# 1. Architect Agent
cat > .claude/agents/architect.md << 'EOF'
# Architect Agent
**Purpose**: Design and build code structures

## Capabilities
- API design (REST, GraphQL, WebSocket)
- Database schemas and models
- System architecture
- Component design
- Code generation

## Activation Patterns
- "create", "build", "implement", "design", "architect"
- "setup", "scaffold", "generate", "construct"

## Tools
- Read: Analyze existing patterns
- Write: Generate code
- MultiEdit: Refactor structures
- Task: Coordinate with other agents
EOF

# 2. Guardian Agent
cat > .claude/agents/guardian.md << 'EOF'
# Guardian Agent
**Purpose**: Quality, security, and performance

## Capabilities
- Security auditing and fixes
- Test writing and validation
- Performance optimization
- Bug fixing and debugging
- Code quality and refactoring

## Activation Patterns
- "test", "fix", "secure", "optimize", "debug"
- "audit", "validate", "check", "improve", "profile"

## Tools
- Read: Analyze code issues
- Write: Fix problems
- Bash: Run tests
- Grep: Find vulnerabilities
- Task: Comprehensive reviews
EOF

# 3. Connector Agent
cat > .claude/agents/connector.md << 'EOF'
# Connector Agent
**Purpose**: External services and deployment

## Capabilities
- API integrations
- Deployment configuration
- CI/CD setup
- Cloud services
- Database connections
- Third-party services

## Activation Patterns
- "deploy", "integrate", "connect", "setup", "configure"
- "publish", "release", "ship", "launch"

## Tools
- Read: Check configurations
- Write: Create configs
- Bash: Execute deployments
- WebSearch: Find documentation
- Task: Complex integrations
EOF

# 4. Documenter Agent
cat > .claude/agents/documenter.md << 'EOF'
# Documenter Agent
**Purpose**: Documentation and explanations

## Capabilities
- Code documentation
- API documentation
- README creation
- Architecture diagrams
- Code explanations
- Comment generation

## Activation Patterns
- "document", "explain", "describe", "comment"
- "readme", "docs", "annotate", "clarify"

## Tools
- Read: Understand code
- Write: Create documentation
- Task: Comprehensive docs
EOF

# Create the smart router
echo -e "${BLUE}→${NC} Installing smart router..."
cat > .claude/router.sh << 'ROUTER'
#!/bin/bash
# Claude Agents Router - The Brain
# Understands intent and activates the right agents

INPUT="$1"
COMMAND="${2:-auto}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Detect intent from natural language
detect_intent() {
    local input_lower=$(echo "$1" | tr '[:upper:]' '[:lower:]')

    # Architect patterns
    if echo "$input_lower" | grep -E "create|build|implement|design|setup|scaffold|architect" > /dev/null; then
        echo "architect"
    # Guardian patterns
    elif echo "$input_lower" | grep -E "test|fix|secure|optimize|debug|audit|validate|improve" > /dev/null; then
        echo "guardian"
    # Connector patterns
    elif echo "$input_lower" | grep -E "deploy|integrate|connect|publish|release|ship" > /dev/null; then
        echo "connector"
    # Documenter patterns
    elif echo "$input_lower" | grep -E "document|explain|describe|comment|readme" > /dev/null; then
        echo "documenter"
    # Default to architect for creation tasks
    else
        echo "architect"
    fi
}

# Route to appropriate workflow
route_request() {
    local intent=$(detect_intent "$1")
    local workflow=""

    case "$intent" in
        architect)
            workflow="Architect → Guardian → Connector"
            echo -e "${BLUE}Intent:${NC} Build something new"
            echo -e "${BLUE}Workflow:${NC} $workflow"
            ;;
        guardian)
            workflow="Guardian"
            echo -e "${BLUE}Intent:${NC} Fix or improve"
            echo -e "${BLUE}Workflow:${NC} $workflow"
            ;;
        connector)
            workflow="Connector → Guardian"
            echo -e "${BLUE}Intent:${NC} Deploy or integrate"
            echo -e "${BLUE}Workflow:${NC} $workflow"
            ;;
        documenter)
            workflow="Documenter"
            echo -e "${BLUE}Intent:${NC} Document or explain"
            echo -e "${BLUE}Workflow:${NC} $workflow"
            ;;
    esac

    # Log to history for learning
    mkdir -p .claude/history
    echo "$(date -u +%Y%m%d-%H%M%S)|$intent|$1" >> .claude/history/requests.log

    echo -e "${GREEN}✓${NC} Agents activated for: $1"
}

# Handle special commands
case "$COMMAND" in
    status)
        echo "Claude Agents: Active"
        echo "Agents: Architect, Guardian, Connector, Documenter"
        echo "History: $(wc -l < .claude/history/requests.log 2>/dev/null || echo 0) requests"
        ;;
    debug)
        tail -10 .claude/history/requests.log 2>/dev/null || echo "No history yet"
        ;;
    history)
        cat .claude/history/requests.log 2>/dev/null || echo "No history yet"
        ;;
    reset)
        rm -f .claude/history/*
        echo "History cleared"
        ;;
    auto|*)
        if [ -z "$INPUT" ]; then
            echo "Usage: $0 \"your request\" [command]"
            echo "Commands: status, debug, history, reset"
        else
            route_request "$INPUT"
        fi
        ;;
esac
ROUTER

chmod +x .claude/router.sh

# Handle CLAUDE.md for project context
echo -e "${BLUE}→${NC} Checking for CLAUDE.md..."
CLAUDE_SNIPPET="
## AI Agents Available
Architect: builds code | Guardian: fixes/secures | Connector: deploys | Documenter: explains
Router: .claude/router.sh \"task\" shows optimal agent/model
"

if [ -f "CLAUDE.md" ]; then
    echo -e "${YELLOW}!${NC} Found existing CLAUDE.md"
    echo -e "${BLUE}→${NC} Add these 3 lines to your CLAUDE.md for agent awareness:"
    echo -e "${CYAN}────────────────────────────────────────${NC}"
    echo "$CLAUDE_SNIPPET"
    echo -e "${CYAN}────────────────────────────────────────${NC}"
    echo -e "${YELLOW}Note:${NC} This is the minimum context needed for Claude to use agents"
elif [ -f "claude.md" ]; then
    echo -e "${YELLOW}!${NC} Found existing claude.md"
    echo -e "${BLUE}→${NC} Add these 3 lines to your claude.md for agent awareness:"
    echo -e "${CYAN}────────────────────────────────────────${NC}"
    echo "$CLAUDE_SNIPPET"
    echo -e "${CYAN}────────────────────────────────────────${NC}"
    echo -e "${YELLOW}Note:${NC} This is the minimum context needed for Claude to use agents"
else
    echo -e "${BLUE}→${NC} No CLAUDE.md found. Creating minimal version..."
    cat > CLAUDE.md << CLAUDE_DOC
# Project Context
$CLAUDE_SNIPPET
## Project Info
Add your project-specific context here.
CLAUDE_DOC
    echo -e "${GREEN}✓${NC} Created CLAUDE.md with agent context"
fi

# Create optional config (not required)
if [ "$PROJECT_TYPE" != "generic" ] && [ "$PROJECT_TYPE" != "new" ]; then
    echo -e "${BLUE}→${NC} Optimizing for $PROJECT_TYPE project..."
    cat > .claude.yml << YAML
# Auto-generated config for $PROJECT_TYPE
# This is optional - system works without it

project_type: $PROJECT_TYPE
agents:
  architect: sonnet
  guardian: sonnet
  connector: haiku
  documenter: haiku

workflows:
$(case "$PROJECT_TYPE" in
    react|nextjs)
        echo "  component: [architect, guardian]
  api: [architect, guardian, connector]
  deploy: [connector, guardian]"
        ;;
    node-api|fastapi|django)
        echo "  endpoint: [architect, guardian]
  database: [architect, guardian]
  deploy: [connector, guardian]"
        ;;
    *)
        echo "  default: [architect, guardian, connector]"
        ;;
esac)
YAML
fi

# Success message
echo
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     ✓ Installation Complete!         ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo
echo -e "${GREEN}You now have 4 AI agents:${NC}"
echo "  • Architect - Builds code"
echo "  • Guardian  - Ensures quality"
echo "  • Connector - Handles integrations"
echo "  • Documenter - Writes documentation"
echo
echo -e "${BLUE}Try it now:${NC}"
echo -e "  ${YELLOW}claude>${NC} Create a REST API for user management"
echo
echo -e "${BLUE}Or check recommendations:${NC}"
echo -e "  ${YELLOW}.claude/router.sh${NC} \"Fix the bug in my login function\""
echo
echo -e "Need help? Check ${BLUE}QUICKSTART.md${NC}"
echo -e "${CYAN}Important:${NC} If you had a CLAUDE.md, add the snippet shown above to it"