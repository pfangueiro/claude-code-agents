#!/bin/bash

# ============================================================================
# Claude Agents - Intelligent Installation Script
# ============================================================================
# Detects existing components and deploys only what's needed
# Supports minimal, full, repair, and update modes
#
# Usage:
#   ./install.sh           - Interactive installation
#   ./install.sh --minimal - Minimal CLAUDE.md only
#   ./install.sh --full    - Complete agent system
#   ./install.sh --repair  - Fix missing components
#   ./install.sh --update  - Update existing installation
# ============================================================================

set -e

# Configuration
SCRIPT_VERSION="2.0.1"
GITHUB_REPO="https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main"
BACKUP_DIR=".claude-backup-$(date +%Y%m%d-%H%M%S)"
DEBUG="${DEBUG:-false}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Installation mode
MODE="${1:-interactive}"

# Component lists
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

LIB_FILES=(
    "agent-templates.json"
    "sdlc-patterns.md"
    "activation-keywords.json"
)

# Statistics
STATS_CHECKED=0
STATS_INSTALLED=0
STATS_SKIPPED=0
STATS_UPDATED=0
STATS_BACKED_UP=0

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo ""
    echo -e "${PURPLE}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${PURPLE}║${BOLD}     🤖 Claude Agents - Intelligent Installer v${SCRIPT_VERSION}     ${NC}${PURPLE}║${NC}"
    echo -e "${PURPLE}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

check_connectivity() {
    print_progress "Checking GitHub connectivity..."
    local test_url="${GITHUB_REPO}/README.md"
    if curl -fsSL "$test_url" -o /dev/null 2>/dev/null; then
        print_info "GitHub connection verified"
        return 0
    else
        print_error "Cannot reach GitHub repository"
        echo "Please check your internet connection or try again later"
        return 1
    fi
}

print_progress() {
    echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $1"
}

print_success() {
    echo -e "${GREEN}✅${NC} $1"
    ((STATS_INSTALLED++))
}

print_skip() {
    echo -e "${YELLOW}⏭️${NC}  $1"
    ((STATS_SKIPPED++))
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ️${NC}  $1"
}

# ============================================================================
# Detection Functions
# ============================================================================

detect_claude_directory() {
    print_progress "Checking for .claude directory..."
    ((STATS_CHECKED++))

    if [ -d ".claude" ]; then
        print_info ".claude directory exists"

        # Check subdirectories
        local subdirs=("agents" "lib" "history")
        for dir in "${subdirs[@]}"; do
            if [ -d ".claude/$dir" ]; then
                echo "  └─ /$dir found"
            else
                echo "  └─ /$dir missing"
            fi
        done
        return 0
    else
        print_info ".claude directory not found"
        return 1
    fi
}

detect_agents() {
    print_progress "Scanning for installed agents..."
    local found_agents=0
    local missing_agents=0

    echo -e "\n${BOLD}Agent Status:${NC}"
    for agent in "${AGENTS[@]}"; do
        ((STATS_CHECKED++))
        if [ -f ".claude/agents/${agent}.md" ]; then
            echo -e "  ${GREEN}✓${NC} ${agent}"
            ((found_agents++))
        else
            echo -e "  ${RED}✗${NC} ${agent}"
            ((missing_agents++))
        fi
    done

    echo -e "\n  Found: ${found_agents}/${#AGENTS[@]} agents"

    if [ $found_agents -eq ${#AGENTS[@]} ]; then
        return 0 # All agents present
    elif [ $found_agents -gt 0 ]; then
        return 2 # Partial installation
    else
        return 1 # No agents
    fi
}

detect_lib_files() {
    print_progress "Checking library files..."
    local found_libs=0

    echo -e "\n${BOLD}Library Files:${NC}"
    for lib in "${LIB_FILES[@]}"; do
        ((STATS_CHECKED++))
        if [ -f ".claude/lib/${lib}" ]; then
            echo -e "  ${GREEN}✓${NC} ${lib}"
            ((found_libs++))
        else
            echo -e "  ${RED}✗${NC} ${lib}"
        fi
    done

    echo -e "\n  Found: ${found_libs}/${#LIB_FILES[@]} library files"

    if [ $found_libs -eq ${#LIB_FILES[@]} ]; then
        return 0
    else
        return 1
    fi
}

detect_claude_md() {
    print_progress "Checking CLAUDE.md configuration..."
    ((STATS_CHECKED++))

    if [ ! -f "CLAUDE.md" ]; then
        print_info "CLAUDE.md not found"
        return 1
    fi

    # Check for agent configuration
    if grep -q "Auto-Activating" CLAUDE.md 2>/dev/null; then
        print_success "CLAUDE.md has agent configuration"

        # Check completeness
        local agent_count=$(grep -c "**.*-.*\*\*" CLAUDE.md 2>/dev/null || echo "0")
        echo "  └─ Found $agent_count agent references"

        if [ $agent_count -ge 10 ]; then
            return 0 # Full config
        else
            return 2 # Partial config
        fi
    else
        print_info "CLAUDE.md exists but lacks agent configuration"
        return 3 # Exists but no agents
    fi
}

# ============================================================================
# Installation Functions
# ============================================================================

create_directories() {
    print_progress "Creating directory structure..."

    mkdir -p .claude/agents
    mkdir -p .claude/lib
    mkdir -p .claude/history

    print_success "Directory structure created"
}

backup_existing() {
    if [ -d ".claude" ] || [ -f "CLAUDE.md" ]; then
        print_progress "Creating backup..."
        mkdir -p "$BACKUP_DIR"

        if [ -d ".claude" ]; then
            cp -r .claude "$BACKUP_DIR/"
            ((STATS_BACKED_UP++))
        fi

        if [ -f "CLAUDE.md" ]; then
            cp CLAUDE.md "$BACKUP_DIR/"
            ((STATS_BACKED_UP++))
        fi

        print_success "Backup created in $BACKUP_DIR"
    fi
}

download_or_copy() {
    local source_file="$1"
    local dest_file="$2"
    local file_type="$3"

    # Check if running from the repo
    if [ -f "$source_file" ]; then
        cp "$source_file" "$dest_file"
        echo -e "  ${GREEN}✓${NC} Copied $file_type"
    else
        # Download from GitHub - construct proper URL
        local url="${GITHUB_REPO}/${source_file}"
        # Remove leading ./ if present
        url="${url#./}"

        # Debug mode
        if [ "$DEBUG" = "true" ]; then
            echo "  DEBUG: Downloading from: $url"
            echo "  DEBUG: Saving to: $dest_file"
        fi

        # Create directory if it doesn't exist
        local dest_dir=$(dirname "$dest_file")
        mkdir -p "$dest_dir"

        # Try to download with better error handling
        if curl -fsSL "$url" -o "$dest_file"; then
            # Verify file was actually downloaded and not empty
            if [ -s "$dest_file" ]; then
                echo -e "  ${GREEN}✓${NC} Downloaded $file_type"
            else
                print_error "Downloaded empty file for $file_type"
                rm -f "$dest_file"
                return 1
            fi
        else
            print_error "Failed to download $file_type"
            if [ "$DEBUG" = "true" ]; then
                echo "  DEBUG: Attempted URL: $url"
                echo "  DEBUG: HTTP Response:"
                curl -IsS "$url" | head -5
            fi
            return 1
        fi
    fi
}

install_agent() {
    local agent="$1"

    if [ -f ".claude/agents/${agent}.md" ]; then
        print_skip "Agent ${agent} already exists"
    else
        print_progress "Installing ${agent} agent..."
        download_or_copy ".claude/agents/${agent}.md" ".claude/agents/${agent}.md" "$agent"
        print_success "Installed ${agent}"
    fi
}

install_lib_file() {
    local lib="$1"

    if [ -f ".claude/lib/${lib}" ]; then
        print_skip "Library file ${lib} already exists"
    else
        print_progress "Installing ${lib}..."
        download_or_copy ".claude/lib/${lib}" ".claude/lib/${lib}" "$lib"
        print_success "Installed ${lib}"
    fi
}

install_minimal_claude_md() {
    print_progress "Installing minimal CLAUDE.md..."

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

    print_success "Created minimal CLAUDE.md"
}

append_claude_md_section() {
    print_progress "Appending agent configuration to existing CLAUDE.md..."

    # Check if already has agent config
    if grep -q "Auto-Activating" CLAUDE.md 2>/dev/null; then
        print_skip "CLAUDE.md already has agent configuration"
        return 0
    fi

    cat >> CLAUDE.md << 'EOF'

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

    print_success "Appended agent configuration to CLAUDE.md"
}

# ============================================================================
# Installation Modes
# ============================================================================

install_minimal() {
    echo -e "\n${BOLD}Installing Minimal Configuration${NC}"
    echo "This will only add CLAUDE.md for agent auto-activation"

    if [ -f "CLAUDE.md" ]; then
        append_claude_md_section
    else
        install_minimal_claude_md
    fi
}

install_full() {
    echo -e "\n${BOLD}Installing Full Agent System${NC}"
    echo "This will install all agents and supporting files"

    # Check connectivity for downloads
    if ! check_connectivity; then
        echo -e "${RED}Installation requires internet connection to download files${NC}"
        exit 1
    fi

    backup_existing
    create_directories

    # Install all agents
    echo -e "\n${BOLD}Installing Agents:${NC}"
    for agent in "${AGENTS[@]}"; do
        install_agent "$agent"
    done

    # Install library files
    echo -e "\n${BOLD}Installing Library Files:${NC}"
    for lib in "${LIB_FILES[@]}"; do
        install_lib_file "$lib"
    done

    # Handle CLAUDE.md
    if [ -f "CLAUDE.md" ]; then
        append_claude_md_section
    else
        install_minimal_claude_md
    fi
}

repair_installation() {
    echo -e "\n${BOLD}Repairing Installation${NC}"
    echo "This will fix missing components"

    # Create directories if missing
    if [ ! -d ".claude" ]; then
        create_directories
    fi

    # Install missing agents
    echo -e "\n${BOLD}Checking Agents:${NC}"
    for agent in "${AGENTS[@]}"; do
        if [ ! -f ".claude/agents/${agent}.md" ]; then
            install_agent "$agent"
        else
            print_skip "Agent ${agent} already present"
        fi
    done

    # Install missing library files
    echo -e "\n${BOLD}Checking Library Files:${NC}"
    for lib in "${LIB_FILES[@]}"; do
        if [ ! -f ".claude/lib/${lib}" ]; then
            install_lib_file "$lib"
        else
            print_skip "Library ${lib} already present"
        fi
    done

    # Fix CLAUDE.md if needed
    if [ ! -f "CLAUDE.md" ]; then
        install_minimal_claude_md
    elif ! grep -q "Auto-Activating" CLAUDE.md 2>/dev/null; then
        append_claude_md_section
    else
        print_skip "CLAUDE.md already configured"
    fi
}

update_installation() {
    echo -e "\n${BOLD}Updating Installation${NC}"
    echo "This will update all components to latest version"

    backup_existing

    # Update all agents
    echo -e "\n${BOLD}Updating Agents:${NC}"
    for agent in "${AGENTS[@]}"; do
        print_progress "Updating ${agent}..."
        download_or_copy ".claude/agents/${agent}.md" ".claude/agents/${agent}.md" "$agent"
        print_success "Updated ${agent}"
        ((STATS_UPDATED++))
    done

    # Update library files
    echo -e "\n${BOLD}Updating Library Files:${NC}"
    for lib in "${LIB_FILES[@]}"; do
        print_progress "Updating ${lib}..."
        download_or_copy ".claude/lib/${lib}" ".claude/lib/${lib}" "$lib"
        print_success "Updated ${lib}"
        ((STATS_UPDATED++))
    done
}

# ============================================================================
# Interactive Mode
# ============================================================================

interactive_installation() {
    # Detection phase
    echo -e "\n${BOLD}=== System Detection ===${NC}"

    local has_claude_dir=false
    local agent_status=0
    local lib_status=0
    local claude_md_status=0

    detect_claude_directory && has_claude_dir=true

    if [ "$has_claude_dir" = true ]; then
        detect_agents || agent_status=$?
        detect_lib_files || lib_status=$?
    fi

    detect_claude_md || claude_md_status=$?

    # Analysis
    echo -e "\n${BOLD}=== Installation Analysis ===${NC}"

    if [ "$has_claude_dir" = false ] && [ $claude_md_status -eq 1 ]; then
        print_info "This appears to be a fresh installation"
        local recommendation="full"
    elif [ $agent_status -eq 0 ] && [ $lib_status -eq 0 ] && [ $claude_md_status -eq 0 ]; then
        print_info "Full system already installed"
        local recommendation="update"
    elif [ $agent_status -eq 2 ] || [ $lib_status -eq 1 ] || [ $claude_md_status -eq 2 ]; then
        print_info "Partial installation detected"
        local recommendation="repair"
    else
        print_info "Minimal configuration recommended"
        local recommendation="minimal"
    fi

    # User choice
    echo -e "\n${BOLD}=== Installation Options ===${NC}"
    echo "Recommended: ${YELLOW}${recommendation}${NC}"
    echo ""
    echo "1) Minimal  - Just CLAUDE.md for auto-activation"
    echo "2) Full     - Complete agent system (all files)"
    echo "3) Repair   - Fix missing components"
    echo "4) Update   - Update to latest version"
    echo "5) Cancel   - Exit without changes"
    echo ""

    read -p "Choose installation type [1-5]: " choice

    case $choice in
        1) install_minimal ;;
        2) install_full ;;
        3) repair_installation ;;
        4) update_installation ;;
        5)
            echo "Installation cancelled"
            exit 0
            ;;
        *)
            print_error "Invalid choice"
            exit 1
            ;;
    esac
}

# ============================================================================
# Verification
# ============================================================================

verify_installation() {
    echo -e "\n${BOLD}=== Verifying Installation ===${NC}"

    local all_good=true

    # Quick verification
    if [ -f "CLAUDE.md" ] && grep -q "Auto-Activating" CLAUDE.md 2>/dev/null; then
        print_success "CLAUDE.md configured correctly"
    else
        print_error "CLAUDE.md configuration issue"
        all_good=false
    fi

    if [ "$MODE" = "--full" ] || [ "$choice" = "2" ]; then
        if [ -d ".claude/agents" ] && [ -d ".claude/lib" ]; then
            print_success "Directory structure verified"
        else
            print_error "Directory structure issue"
            all_good=false
        fi
    fi

    if [ "$all_good" = true ]; then
        echo -e "\n${GREEN}${BOLD}✨ Installation Successful!${NC}"
    else
        echo -e "\n${YELLOW}⚠️  Installation completed with warnings${NC}"
    fi
}

# ============================================================================
# Summary
# ============================================================================

print_summary() {
    echo -e "\n${BOLD}=== Installation Summary ===${NC}"
    echo "┌─────────────────────────────┐"
    echo "│ Components Checked:    $(printf "%4d" $STATS_CHECKED) │"
    echo "│ Components Installed:  $(printf "%4d" $STATS_INSTALLED) │"
    echo "│ Components Skipped:    $(printf "%4d" $STATS_SKIPPED) │"
    echo "│ Components Updated:    $(printf "%4d" $STATS_UPDATED) │"
    echo "│ Files Backed Up:       $(printf "%4d" $STATS_BACKED_UP) │"
    echo "└─────────────────────────────┘"

    echo -e "\n${BOLD}=== Quick Start ===${NC}"
    echo "Just use natural language and agents will auto-activate:"
    echo ""
    echo '  📝 "Design a REST API for user management"'
    echo '  🔒 "Check this code for security issues"'
    echo '  ⚡ "Why is this query running slow?"'
    echo '  🚀 "Deploy this to AWS"'
    echo ""
    echo -e "${CYAN}No configuration needed - just describe what you need!${NC}"
}

# ============================================================================
# Main
# ============================================================================

main() {
    print_header

    case "$MODE" in
        --minimal)
            echo -e "${BOLD}Running in MINIMAL mode${NC}"
            install_minimal
            ;;
        --full)
            echo -e "${BOLD}Running in FULL mode${NC}"
            install_full
            ;;
        --repair)
            echo -e "${BOLD}Running in REPAIR mode${NC}"
            repair_installation
            ;;
        --update)
            echo -e "${BOLD}Running in UPDATE mode${NC}"
            update_installation
            ;;
        --help)
            echo "Usage: ./install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --minimal   Install minimal CLAUDE.md only"
            echo "  --full      Install complete agent system"
            echo "  --repair    Fix missing components"
            echo "  --update    Update to latest version"
            echo "  --help      Show this help message"
            echo ""
            echo "No options = Interactive mode"
            exit 0
            ;;
        *)
            interactive_installation
            ;;
    esac

    verify_installation
    print_summary
}

# Run main
main