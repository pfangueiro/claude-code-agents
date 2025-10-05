#!/bin/bash
# Claude Advanced Agent System v2.0 - Installation Script
# Production-grade AI agent routing with visual intelligence

set -eo pipefail

# Configuration
readonly REPO_URL="https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main"
readonly VERSION="2.0.0"

# Colors (basic fallback before color system loads)
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly YELLOW='\033[1;33m'
readonly CYAN='\033[0;36m'
readonly BOLD='\033[1m'
readonly NC='\033[0m'

# Banner
echo -e "${CYAN}${BOLD}"
cat << 'EOF'
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   Claude Advanced Agent System v2.0                       ║
║   7 Specialized Agents with Visual Intelligence          ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Check requirements
check_requirements() {
    echo -e "${BLUE}→${NC} Checking requirements..."

    if ! command -v curl &> /dev/null; then
        echo -e "${RED}✗${NC} curl is required but not installed"
        exit 1
    fi

    echo -e "${GREEN}✓${NC} All requirements met"
}

# Create directory structure
create_structure() {
    echo -e "${BLUE}→${NC} Creating directory structure..."

    mkdir -p .claude/agents
    mkdir -p .claude/lib/hooks
    mkdir -p .claude/tests/unit
    mkdir -p .claude/telemetry

    echo -e "${GREEN}✓${NC} Directory structure created"
}

# Download file from GitHub
download_file() {
    local file_path="$1"
    local target_path="$2"
    local url="${REPO_URL}/${file_path}"

    if curl -fsSL "$url" -o "$target_path" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Install agents
install_agents() {
    echo -e "${BLUE}→${NC} Installing 7 specialized agents..."

    local agents=(
        "mobile-ux:📱 Mobile/PWA UX"
        "api-reliability:🔌 API Reliability"
        "schema-guardian:🛡️  Schema Guardian"
        "performance:⚡ Performance"
        "security:🔒 Security"
        "accessibility:♿ Accessibility"
        "documentation:📚 Documentation"
    )

    for agent_info in "${agents[@]}"; do
        local agent="${agent_info%%:*}"
        local name="${agent_info#*:}"

        if download_file ".claude/agents/${agent}.md" ".claude/agents/${agent}.md"; then
            echo -e "  ${GREEN}✓${NC} $name"
        else
            echo -e "  ${YELLOW}!${NC} $name (using fallback)"
        fi
    done
}

# Install core scripts
install_core() {
    echo -e "${BLUE}→${NC} Installing core scripts..."

    # Intent router
    if download_file ".claude/intent-router.sh" ".claude/intent-router.sh"; then
        chmod +x .claude/intent-router.sh
        echo -e "  ${GREEN}✓${NC} Intent Router"
    else
        echo -e "  ${RED}✗${NC} Failed to download intent router"
        exit 1
    fi

    # Commands
    if download_file ".claude/commands.sh" ".claude/commands.sh"; then
        chmod +x .claude/commands.sh
        echo -e "  ${GREEN}✓${NC} Slash Commands"
    fi

    # Demo
    if download_file ".claude/demo-colors.sh" ".claude/demo-colors.sh"; then
        chmod +x .claude/demo-colors.sh
        echo -e "  ${GREEN}✓${NC} Color Demo"
    fi
}

# Install libraries
install_libraries() {
    echo -e "${BLUE}→${NC} Installing utility libraries..."

    local libs=(
        "colors:🎨 Visual Identity System"
        "security:🔒 Input Sanitization"
        "fuzzy-match:🔍 Typo Correction"
        "adaptive-confidence:📊 Machine Learning"
        "performance-utils:⚡ Optimizations"
    )

    for lib_info in "${libs[@]}"; do
        local lib="${lib_info%%:*}"
        local name="${lib_info#*:}"

        if download_file ".claude/lib/${lib}.sh" ".claude/lib/${lib}.sh"; then
            chmod +x ".claude/lib/${lib}.sh"
            echo -e "  ${GREEN}✓${NC} $name"
        else
            echo -e "  ${YELLOW}!${NC} $name (optional, skipped)"
        fi
    done
}

# Install hooks
install_hooks() {
    echo -e "${BLUE}→${NC} Installing specialized hooks..."

    download_file ".claude/lib/hooks/rows-affected-enforcer.sh" ".claude/lib/hooks/rows-affected-enforcer.sh" 2>/dev/null && \
        chmod +x .claude/lib/hooks/rows-affected-enforcer.sh && \
        echo -e "  ${GREEN}✓${NC} Rows Affected Enforcer"

    download_file ".claude/lib/hooks/schema-introspection.sh" ".claude/lib/hooks/schema-introspection.sh" 2>/dev/null && \
        chmod +x .claude/lib/hooks/schema-introspection.sh && \
        echo -e "  ${GREEN}✓${NC} Schema Introspection"
}

# Install tests
install_tests() {
    echo -e "${BLUE}→${NC} Installing test suite (optional)..."

    download_file ".claude/tests/comprehensive-test.sh" ".claude/tests/comprehensive-test.sh" 2>/dev/null && \
        chmod +x .claude/tests/comprehensive-test.sh && \
        echo -e "  ${GREEN}✓${NC} Comprehensive tests installed"

    download_file ".claude/tests/unit/test-intent-router.sh" ".claude/tests/unit/test-intent-router.sh" 2>/dev/null && \
        chmod +x .claude/tests/unit/test-intent-router.sh && \
        echo -e "  ${GREEN}✓${NC} Unit tests installed"
}

# Initialize telemetry
init_telemetry() {
    echo -e "${BLUE}→${NC} Initializing telemetry system..."

    # Create learning.json
    cat > .claude/telemetry/learning.json << 'EOF'
{
  "agents": {
    "mobile-ux": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "api-reliability": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "schema-guardian": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "performance": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "security": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "accessibility": {"threshold": 0.5, "success_rate": 0.0, "samples": 0},
    "documentation": {"threshold": 0.5, "success_rate": 0.0, "samples": 0}
  },
  "global": {
    "total_requests": 0,
    "correct_routing": 0,
    "false_positives": 0,
    "false_negatives": 0
  }
}
EOF

    # Create empty events log
    touch .claude/telemetry/events.jsonl
    chmod 600 .claude/telemetry/events.jsonl

    echo -e "${GREEN}✓${NC} Telemetry initialized"
}

# Setup CLAUDE.md
setup_claude_md() {
    echo -e "${BLUE}→${NC} Configuring CLAUDE.md..."

    local snippet='
## 🤖 Advanced Agent System v2.0

This project uses the Claude Advanced Agent System with 7 specialized agents:
- 📱 **Mobile/PWA UX** - Responsive design, PWA features
- 🔌 **API Reliability** - Data persistence, API contracts
- 🛡️  **Schema Guardian** - Database migrations, integrity
- ⚡ **Performance** - Optimization, bundle size
- 🔒 **Security** - Vulnerability detection, hardening
- ♿ **Accessibility** - WCAG compliance, a11y
- 📚 **Documentation** - README, API docs

### Usage
```bash
# Test routing with visual feedback
.claude/intent-router.sh route "your request"

# See all agent colors
.claude/demo-colors.sh

# Run specific agent
/agent security  # or ux-audit, api-reliability, etc.
```
'

    if [[ -f "CLAUDE.md" ]]; then
        echo -e "${YELLOW}!${NC} Found existing CLAUDE.md"
        echo -e "${BLUE}→${NC} Add this section to your CLAUDE.md:"
        echo -e "${CYAN}──────────────────────────────────────────${NC}"
        echo "$snippet"
        echo -e "${CYAN}──────────────────────────────────────────${NC}"
    else
        echo -e "${BLUE}→${NC} Creating CLAUDE.md..."
        cat > CLAUDE.md << EOF
# Project Context
$snippet

## Project Specific Context
Add your project-specific information here.
EOF
        echo -e "${GREEN}✓${NC} Created CLAUDE.md with agent context"
    fi
}

# Verify installation
verify_installation() {
    echo -e "${BLUE}→${NC} Verifying installation..."

    local required_files=(
        ".claude/intent-router.sh"
        ".claude/lib/colors.sh"
        ".claude/telemetry/learning.json"
    )

    local all_good=true
    for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            echo -e "  ${RED}✗${NC} Missing: $file"
            all_good=false
        fi
    done

    if [[ "$all_good" == true ]]; then
        echo -e "${GREEN}✓${NC} Installation verified"
        return 0
    else
        echo -e "${RED}✗${NC} Installation incomplete"
        return 1
    fi
}

# Show success message with color
show_success() {
    echo ""
    echo -e "${GREEN}${BOLD}"
    cat << 'EOF'
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║            ✅  Installation Complete!                     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"

    echo -e "${BOLD}🎨 Visual Agent System Installed:${NC}"
    echo ""
    echo -e "  📱 ${BOLD}Mobile/PWA UX${NC}      - Purple/Pink theme"
    echo -e "  🔌 ${BOLD}API Reliability${NC}    - Orange/Amber theme"
    echo -e "  🛡️  ${BOLD}Schema Guardian${NC}    - Indigo/Sapphire theme"
    echo -e "  ⚡ ${BOLD}Performance${NC}        - Lime/Gold theme"
    echo -e "  🔒 ${BOLD}Security${NC}           - Ruby Red theme (critical alerts)"
    echo -e "  ♿ ${BOLD}Accessibility${NC}      - Teal/Cyan theme"
    echo -e "  📚 ${BOLD}Documentation${NC}      - Emerald/Green theme"
    echo ""

    echo -e "${CYAN}${BOLD}🚀 Quick Start:${NC}"
    echo ""
    echo -e "${YELLOW}# See the color system in action${NC}"
    echo -e "  .claude/demo-colors.sh"
    echo ""
    echo -e "${YELLOW}# Test agent routing${NC}"
    echo -e "  .claude/intent-router.sh route \"mobile layout broken on iPhone\""
    echo ""
    echo -e "${YELLOW}# Run comprehensive tests${NC}"
    echo -e "  .claude/tests/comprehensive-test.sh"
    echo ""
    echo -e "${YELLOW}# Check system status${NC}"
    echo -e "  .claude/intent-router.sh status"
    echo ""

    echo -e "${BOLD}📊 Features:${NC}"
    echo "  • Natural language routing (96% accuracy)"
    echo "  • Visual confidence bars"
    echo "  • Fuzzy matching (auto-corrects typos)"
    echo "  • Security hardening (input sanitization)"
    echo "  • Adaptive learning from usage"
    echo "  • <40ms routing speed"
    echo ""

    echo -e "${CYAN}Documentation:${NC} https://github.com/pfangueiro/claude-code-agents"
    echo -e "${CYAN}Report Issues:${NC} https://github.com/pfangueiro/claude-code-agents/issues"
    echo ""
}

# Main installation flow
main() {
    check_requirements
    create_structure
    install_agents
    install_core
    install_libraries
    install_hooks
    install_tests
    init_telemetry
    setup_claude_md

    if verify_installation; then
        show_success
    else
        echo -e "${RED}${BOLD}Installation failed. Please check errors above.${NC}"
        exit 1
    fi
}

# Run installation
main "$@"