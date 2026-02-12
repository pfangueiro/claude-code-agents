#!/bin/bash

# ============================================================================
# Claude Agents - Intelligent Installation Script
# ============================================================================
# Detects existing components and deploys only what's needed
# Supports minimal, full, repair, update, and team-setup modes
#
# Usage:
#   ./install.sh              - Interactive installation
#   ./install.sh --minimal    - Minimal CLAUDE.md only
#   ./install.sh --full       - Complete agent system
#   ./install.sh --repair     - Fix missing components
#   ./install.sh --update     - Update existing installation
#   ./install.sh --team-setup - Full team onboarding (agents + global config)
# ============================================================================

set -e

# Configuration
SCRIPT_VERSION="2.3.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
    "agent-coordination.md"
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

print_progress() {
    echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $1"
}

print_success() {
    echo -e "${GREEN}✅${NC} $1"
    (( STATS_INSTALLED++ )) || true
}

print_skip() {
    echo -e "${YELLOW}⏭️${NC}  $1"
    (( STATS_SKIPPED++ )) || true
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ️${NC}  $1"
}

# ============================================================================
# Preflight Checks
# ============================================================================

preflight_checks() {
    local errors=0

    # Check write permissions
    if [ ! -w "." ]; then
        print_error "No write permission in current directory: $(pwd)"
        ((errors++))
    fi

    # Check disk space (need at least 1MB)
    local available_kb
    available_kb=$(df -k . 2>/dev/null | awk 'NR==2 {print $4}')
    if [ -n "$available_kb" ] && [ "$available_kb" -lt 1024 ]; then
        print_error "Insufficient disk space (need at least 1MB, have ${available_kb}KB)"
        ((errors++))
    fi

    # Validate source directory has agent files
    if [ ! -d "${SCRIPT_DIR}/.claude/agents" ]; then
        print_error "Source directory missing .claude/agents/. Run from the cloned repo."
        ((errors++))
    fi

    if [ $errors -gt 0 ]; then
        print_error "Preflight checks failed with $errors error(s). Aborting."
        exit 1
    fi

    print_success "Preflight checks passed"
}

# ============================================================================
# Detection Functions
# ============================================================================

detect_claude_directory() {
    print_progress "Checking for .claude directory..."
    (( STATS_CHECKED++ )) || true

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
        (( STATS_CHECKED++ )) || true
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
        (( STATS_CHECKED++ )) || true
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
    (( STATS_CHECKED++ )) || true

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
    mkdir -p .claude/rules

    print_success "Directory structure created"
}

install_rules() {
    echo -e "\n${BOLD}Installing Rules:${NC}"

    local src_dir="${SCRIPT_DIR}/.claude/rules"
    local dest_dir=".claude/rules"

    if [ ! -d "$src_dir" ]; then
        print_info "No rules directory found in source — skipping"
        return 0
    fi

    mkdir -p "$dest_dir"

    for file in "$src_dir"/*.md; do
        [ -f "$file" ] || continue
        local name
        name=$(basename "$file")
        [[ "$name" == ._* ]] && continue
        if [ -f "$dest_dir/$name" ]; then
            print_skip "Rule $name already exists"
        else
            cp "$file" "$dest_dir/$name"
            print_success "Installed rule $name"
        fi
    done
}

backup_existing() {
    if [ -d ".claude" ] || [ -f "CLAUDE.md" ]; then
        print_progress "Creating backup..."
        mkdir -p "$BACKUP_DIR"

        if [ -d ".claude" ]; then
            cp -r .claude "$BACKUP_DIR/"
            (( STATS_BACKED_UP++ )) || true
        fi

        if [ -f "CLAUDE.md" ]; then
            cp CLAUDE.md "$BACKUP_DIR/"
            (( STATS_BACKED_UP++ )) || true
        fi

        print_success "Backup created in $BACKUP_DIR"
    fi
}

download_or_copy() {
    local source_file="$1"
    local dest_file="$2"
    local file_type="$3"

    # Create directory if it doesn't exist
    local dest_dir
    dest_dir=$(dirname "$dest_file")
    mkdir -p "$dest_dir"

    # Check if running from the repo (local clone)
    if [ -f "${SCRIPT_DIR}/${source_file}" ]; then
        cp "${SCRIPT_DIR}/${source_file}" "$dest_file"
        echo -e "  ${GREEN}✓${NC} Copied $file_type"
    elif [ -f "$source_file" ]; then
        cp "$source_file" "$dest_file"
        echo -e "  ${GREEN}✓${NC} Copied $file_type"
    else
        print_error "File not found: $source_file"
        print_info "Run this script from the cloned repository directory."
        return 1
    fi
}

install_agent() {
    local agent="$1"

    if [ -f ".claude/agents/${agent}.md" ]; then
        print_skip "Agent ${agent} already exists"
    else
        print_progress "Installing ${agent} agent..."
        if download_or_copy ".claude/agents/${agent}.md" ".claude/agents/${agent}.md" "$agent"; then
            print_success "Installed ${agent}"
        else
            print_error "Failed to install agent ${agent}"
            return 1
        fi
    fi
}

install_lib_file() {
    local lib="$1"

    if [ -f ".claude/lib/${lib}" ]; then
        print_skip "Library file ${lib} already exists"
    else
        print_progress "Installing ${lib}..."
        if download_or_copy ".claude/lib/${lib}" ".claude/lib/${lib}" "$lib"; then
            print_success "Installed ${lib}"
        else
            print_error "Failed to install library file ${lib}"
            return 1
        fi
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
# Team Setup Functions
# ============================================================================

check_prerequisites() {
    print_progress "Checking prerequisites..."

    local missing_required=false

    for cmd in git curl; do
        if command -v "$cmd" &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $cmd"
        else
            echo -e "  ${RED}✗${NC} $cmd (required)"
            missing_required=true
        fi
    done

    for cmd in jq npx; do
        if command -v "$cmd" &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $cmd"
        else
            echo -e "  ${YELLOW}!${NC} $cmd (optional — needed for statusline/MCP)"
        fi
    done

    if [ "$missing_required" = true ]; then
        print_error "Missing required tools. Install them and retry."
        exit 1
    fi

    print_success "Prerequisites satisfied"
}

install_skills() {
    echo -e "\n${BOLD}Installing Skills:${NC}"

    local src_dir="${SCRIPT_DIR}/.claude/skills"
    local dest_dir=".claude/skills"

    if [ ! -d "$src_dir" ]; then
        print_info "No skills directory found in source — skipping"
        return 0
    fi

    mkdir -p "$dest_dir"

    for skill_dir in "$src_dir"/*/; do
        [ -d "$skill_dir" ] || continue
        local name
        name=$(basename "$skill_dir")
        [[ "$name" == ._* ]] && continue
        if [ -f "$dest_dir/$name/SKILL.md" ]; then
            print_skip "Skill $name already exists"
        else
            cp -r "$skill_dir" "$dest_dir/$name"
            print_success "Installed skill $name"
        fi
    done
}

install_commands() {
    echo -e "\n${BOLD}Installing Slash Commands:${NC}"

    local src_dir="${SCRIPT_DIR}/.claude/commands"
    local dest_dir=".claude/commands"

    if [ ! -d "$src_dir" ]; then
        print_info "No commands directory found in source — skipping"
        return 0
    fi

    mkdir -p "$dest_dir"

    for file in "$src_dir"/*.md; do
        [ -f "$file" ] || continue
        local name
        name=$(basename "$file")
        # Skip macOS resource fork files
        [[ "$name" == ._* ]] && continue
        if [ -f "$dest_dir/$name" ]; then
            print_skip "Command $name already exists"
        else
            cp "$file" "$dest_dir/$name"
            print_success "Installed command $name"
        fi
    done
}

install_global_config() {
    echo -e "\n${BOLD}Installing Global Configuration:${NC}"

    local src_dir="${SCRIPT_DIR}/global-config"

    if [ ! -d "$src_dir" ]; then
        print_error "global-config/ directory not found. Run from the repo root."
        return 1
    fi

    # Create directories
    mkdir -p ~/.claude/hooks
    mkdir -p ~/.claude/output-styles

    # Copy hooks (executable)
    for hook in "$src_dir"/hooks/*.sh; do
        [ -f "$hook" ] || continue
        local name
        name=$(basename "$hook")
        cp "$hook" ~/.claude/hooks/"$name"
        chmod +x ~/.claude/hooks/"$name"
        print_success "Installed hook $name"
    done

    # Copy output styles
    for style in "$src_dir"/output-styles/*; do
        [ -f "$style" ] || continue
        local name
        name=$(basename "$style")
        cp "$style" ~/.claude/output-styles/"$name"
        print_success "Installed output style $name"
    done

    # Copy statusline
    if [ -f "$src_dir/statusline.sh" ]; then
        cp "$src_dir/statusline.sh" ~/.claude/statusline.sh
        chmod +x ~/.claude/statusline.sh
        print_success "Installed statusline.sh"
    fi

    # Copy keybindings
    if [ -f "$src_dir/keybindings.json" ]; then
        cp "$src_dir/keybindings.json" ~/.claude/keybindings.json
        print_success "Installed keybindings.json"
    fi

    # Handle settings.json
    if [ -f "$src_dir/settings.json.template" ]; then
        if [ ! -f ~/.claude/settings.json ]; then
            cp "$src_dir/settings.json.template" ~/.claude/settings.json
            print_success "Installed settings.json from template"
        else
            echo ""
            echo -e "  ${YELLOW}~/.claude/settings.json already exists.${NC}"
            echo "  1) Keep existing"
            echo "  2) Replace (backup created)"
            echo "  3) Show diff"
            echo ""
            read -p "  Choose [1-3]: " settings_choice
            case $settings_choice in
                2)
                    cp ~/.claude/settings.json ~/.claude/settings.json.backup
                    cp "$src_dir/settings.json.template" ~/.claude/settings.json
                    print_success "Replaced settings.json (backup: settings.json.backup)"
                    ;;
                3)
                    diff ~/.claude/settings.json "$src_dir/settings.json.template" || true
                    echo ""
                    read -p "  Replace? [y/N]: " replace_yn
                    if [[ "$replace_yn" =~ ^[Yy]$ ]]; then
                        cp ~/.claude/settings.json ~/.claude/settings.json.backup
                        cp "$src_dir/settings.json.template" ~/.claude/settings.json
                        print_success "Replaced settings.json (backup: settings.json.backup)"
                    else
                        print_skip "Kept existing settings.json"
                    fi
                    ;;
                *)
                    print_skip "Kept existing settings.json"
                    ;;
            esac
        fi
    fi
}

personalize_setup() {
    echo -e "\n${BOLD}Personalizing CLAUDE.md:${NC}"

    local template="${SCRIPT_DIR}/global-config/CLAUDE.md.template"

    if [ ! -f "$template" ]; then
        print_info "CLAUDE.md.template not found — skipping personalization"
        return 0
    fi

    if [ -f ~/.claude/CLAUDE.md ]; then
        print_skip "~/.claude/CLAUDE.md already exists — skipping"
        return 0
    fi

    # Auto-detect from git config
    local detected_name
    local detected_email
    detected_name=$(git config user.name 2>/dev/null || echo "")
    detected_email=$(git config user.email 2>/dev/null || echo "")

    # Prompt for confirmation
    if [ -n "$detected_name" ]; then
        echo -e "  Detected name: ${CYAN}${detected_name}${NC}"
        read -p "  Use this name? [Y/n]: " confirm_name
        if [[ "$confirm_name" =~ ^[Nn]$ ]]; then
            read -p "  Enter your name: " detected_name
        fi
    else
        read -p "  Enter your name: " detected_name
    fi

    if [ -n "$detected_email" ]; then
        echo -e "  Detected email: ${CYAN}${detected_email}${NC}"
        read -p "  Use this email? [Y/n]: " confirm_email
        if [[ "$confirm_email" =~ ^[Nn]$ ]]; then
            read -p "  Enter your git email: " detected_email
        fi
    else
        read -p "  Enter your git email: " detected_email
    fi

    # Generate CLAUDE.md from template
    sed -e "s/__YOUR_NAME__/${detected_name}/g" \
        -e "s/__YOUR_GIT_EMAIL__/${detected_email}/g" \
        "$template" > ~/.claude/CLAUDE.md

    print_success "Created ~/.claude/CLAUDE.md for ${detected_name}"
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

    local install_errors=0

    backup_existing
    create_directories

    # Install all agents
    echo -e "\n${BOLD}Installing Agents:${NC}"
    for agent in "${AGENTS[@]}"; do
        install_agent "$agent" || ((install_errors++))
    done

    # Install library files
    echo -e "\n${BOLD}Installing Library Files:${NC}"
    for lib in "${LIB_FILES[@]}"; do
        install_lib_file "$lib" || ((install_errors++))
    done

    # Install rules
    install_rules

    # Install skills
    install_skills

    # Install slash commands
    install_commands

    # Install MCP configuration
    if [ -f "${SCRIPT_DIR}/.mcp.json" ]; then
        if [ -f ".mcp.json" ]; then
            print_skip "MCP configuration (.mcp.json) already exists"
        else
            cp "${SCRIPT_DIR}/.mcp.json" ".mcp.json"
            print_success "Installed MCP configuration (.mcp.json)"
        fi
    fi

    # Handle CLAUDE.md
    if [ -f "CLAUDE.md" ]; then
        append_claude_md_section
    else
        install_minimal_claude_md
    fi

    if [ $install_errors -gt 0 ]; then
        print_error "$install_errors component(s) failed to install"
        return 1
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

    # Repair rules, skills, and commands
    install_rules
    install_skills
    install_commands

    # Repair MCP configuration
    if [ ! -f ".mcp.json" ] && [ -f "${SCRIPT_DIR}/.mcp.json" ]; then
        cp "${SCRIPT_DIR}/.mcp.json" ".mcp.json"
        print_success "Installed MCP configuration (.mcp.json)"
    else
        print_skip "MCP configuration already present"
    fi

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
        (( STATS_UPDATED++ )) || true
    done

    # Update library files
    echo -e "\n${BOLD}Updating Library Files:${NC}"
    for lib in "${LIB_FILES[@]}"; do
        print_progress "Updating ${lib}..."
        download_or_copy ".claude/lib/${lib}" ".claude/lib/${lib}" "$lib"
        print_success "Updated ${lib}"
        (( STATS_UPDATED++ )) || true
    done

    # Update rules, skills, and commands (re-copy from source)
    echo -e "\n${BOLD}Updating Rules:${NC}"
    local src_rules="${SCRIPT_DIR}/.claude/rules"
    if [ -d "$src_rules" ]; then
        mkdir -p .claude/rules
        for file in "$src_rules"/*.md; do
            [ -f "$file" ] || continue
            local name
            name=$(basename "$file")
            [[ "$name" == ._* ]] && continue
            cp "$file" ".claude/rules/$name"
            print_success "Updated rule $name"
            (( STATS_UPDATED++ )) || true
        done
    fi

    echo -e "\n${BOLD}Updating Skills:${NC}"
    local src_skills="${SCRIPT_DIR}/.claude/skills"
    if [ -d "$src_skills" ]; then
        mkdir -p .claude/skills
        for skill_dir in "$src_skills"/*/; do
            [ -d "$skill_dir" ] || continue
            local name
            name=$(basename "$skill_dir")
            [[ "$name" == ._* ]] && continue
            cp -r "$skill_dir" ".claude/skills/$name"
            print_success "Updated skill $name"
            (( STATS_UPDATED++ )) || true
        done
    fi

    echo -e "\n${BOLD}Updating Slash Commands:${NC}"
    local src_cmds="${SCRIPT_DIR}/.claude/commands"
    if [ -d "$src_cmds" ]; then
        mkdir -p .claude/commands
        for file in "$src_cmds"/*.md; do
            [ -f "$file" ] || continue
            local name
            name=$(basename "$file")
            [[ "$name" == ._* ]] && continue
            cp "$file" ".claude/commands/$name"
            print_success "Updated command $name"
            (( STATS_UPDATED++ )) || true
        done
    fi

    # Update MCP configuration
    if [ -f "${SCRIPT_DIR}/.mcp.json" ]; then
        cp "${SCRIPT_DIR}/.mcp.json" ".mcp.json"
        print_success "Updated MCP configuration (.mcp.json)"
        (( STATS_UPDATED++ )) || true
    fi
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
            preflight_checks
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
        --team-setup)
            echo -e "${BOLD}Running TEAM SETUP mode${NC}"
            check_prerequisites
            preflight_checks
            install_full
            install_global_config
            personalize_setup
            ;;
        --help)
            echo "Usage: ./install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --minimal      Install minimal CLAUDE.md only"
            echo "  --full         Install complete agent system"
            echo "  --repair       Fix missing components"
            echo "  --update       Update to latest version"
            echo "  --team-setup   Full team onboarding (agents + global config)"
            echo "  --help         Show this help message"
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