#!/bin/bash

# Quick installer for Claude Agents v2.2.0
# This simplified version focuses on reliable downloads

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🤖 Claude Agents - Quick Installer${NC}"
echo ""

# Configuration
GITHUB_BASE="https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main"

# Agent list
AGENTS=(
    "architecture-planner"
    "code-quality"
    "security-auditor"
    "test-automation"
    "performance-optimizer"
    "devops-automation"
    "documentation-maintainer"
    "database-architect"
    "frontend-specialist"
    "api-backend"
    "incident-commander"
    "meta-agent"
)

# Library files
LIBS=(
    "agent-templates.json"
    "sdlc-patterns.md"
)

# Create directories
echo "📁 Creating directories..."
mkdir -p .claude/agents
mkdir -p .claude/lib
mkdir -p .claude/history
echo -e "${GREEN}✓${NC} Directories created"
echo ""

# Download agents
echo "📦 Downloading agents..."
SUCCESS=0
FAILED=0

for agent in "${AGENTS[@]}"; do
    echo -n "  Downloading ${agent}... "
    url="${GITHUB_BASE}/.claude/agents/${agent}.md"
    dest=".claude/agents/${agent}.md"

    if curl -fsSL "$url" -o "$dest" 2>/dev/null; then
        if [ -s "$dest" ]; then
            echo -e "${GREEN}✓${NC}"
            ((SUCCESS++))
        else
            echo -e "${RED}✗${NC} (empty file)"
            rm -f "$dest"
            ((FAILED++))
        fi
    else
        echo -e "${RED}✗${NC} (download failed)"
        ((FAILED++))
    fi
done

echo ""
echo "📚 Downloading library files..."

for lib in "${LIBS[@]}"; do
    echo -n "  Downloading ${lib}... "
    url="${GITHUB_BASE}/.claude/lib/${lib}"
    dest=".claude/lib/${lib}"

    if curl -fsSL "$url" -o "$dest" 2>/dev/null; then
        if [ -s "$dest" ]; then
            echo -e "${GREEN}✓${NC}"
            ((SUCCESS++))
        else
            echo -e "${RED}✗${NC} (empty file)"
            rm -f "$dest"
            ((FAILED++))
        fi
    else
        echo -e "${RED}✗${NC} (download failed)"
        ((FAILED++))
    fi
done

echo ""
echo "📝 Creating CLAUDE.md..."

if [ ! -f "CLAUDE.md" ]; then
    curl -fsSL "${GITHUB_BASE}/CLAUDE-minimal.md" -o "CLAUDE.md" 2>/dev/null || {
        # Fallback: Create minimal CLAUDE.md
        cat > CLAUDE.md << 'EOF'
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

*No configuration needed. Just describe what you want to build.*
EOF
    }
    echo -e "${GREEN}✓${NC} CLAUDE.md created"
else
    echo -e "${YELLOW}⚠${NC} CLAUDE.md already exists (skipped)"
fi

echo ""
echo "════════════════════════════════════════"
echo -e "${BLUE}Installation Summary${NC}"
echo "════════════════════════════════════════"
echo "  Successful downloads: ${SUCCESS}"
echo "  Failed downloads: ${FAILED}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ Installation completed successfully!${NC}"
    echo ""
    echo "Agents are ready to auto-activate. Just describe what you need:"
    echo '  • "Design a REST API" → architecture-planner activates'
    echo '  • "Check security" → security-auditor activates'
    echo '  • "Deploy to AWS" → devops-automation activates'
else
    echo -e "${YELLOW}⚠️ Installation completed with some errors${NC}"
    echo ""
    echo "Some files couldn't be downloaded. You can:"
    echo "1. Run this script again"
    echo "2. Clone the repository for local installation:"
    echo "   git clone https://github.com/pfangueiro/claude-code-agents.git"
fi

echo ""
echo "For debug info, run: DEBUG=true $0"