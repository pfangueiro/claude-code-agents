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
#   ./install.sh --full /path/to/project - Install into a specific directory
# ============================================================================

set -e

# Configuration
SCRIPT_VERSION="2.9.0"
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

# Installation mode and optional target directory
MODE="${1:-interactive}"
if [ -n "$2" ] && [ -d "$2" ]; then
    cd "$2"
    echo -e "${CYAN}Target directory: $2${NC}"
fi

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
    "sre-specialist"
    "meta-agent"
)

LIB_FILES=(
    "agent-templates.json"
    "sdlc-patterns.md"
    "activation-keywords.json"
    "agent-coordination.md"
    "mcp-guide.md"
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

    # Resolve actual source path
    local src_path=""
    if [ -f "${SCRIPT_DIR}/${source_file}" ]; then
        src_path="${SCRIPT_DIR}/${source_file}"
    elif [ -f "$source_file" ]; then
        src_path="$source_file"
    else
        print_error "File not found: $source_file"
        print_info "Run this script from the cloned repository directory."
        return 1
    fi

    # Skip if source and destination resolve to the same inode
    # (happens when install.sh --update runs inside the source repo itself)
    if [ -f "$dest_file" ] && [ "$src_path" -ef "$dest_file" ]; then
        echo -e "  ${YELLOW}⏭${NC}  Skipped $file_type (in-place)"
        return 0
    fi

    cp "$src_path" "$dest_file"
    echo -e "  ${GREEN}✓${NC} Copied $file_type"
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
| "define SLOs" | **sre-specialist** | SRE, reliability, runbooks |
| "create an agent" | **meta-agent** | Generates new specialized agents |

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

### 🎯 Orchestration Skills (Slash Commands)

Use these for structured, multi-phase task execution:

- **`/deep-read <target>`** — 6-phase codebase reading engine. Reads actual source code line by line with file:line citations.
- **`/execute <goal>`** — Orchestrated task engine. Decomposes goals into atomic tasks, plans dependencies, executes in parallel batches.
- **`/investigate <symptom>`** — 8-phase root cause analysis. Uses 5 Whys, competing hypotheses, evidence classification.
- **`/deep-analysis <problem>`** — Structured multi-step reasoning via sequential-thinking MCP. For architecture decisions and trade-offs.

### 🛠️ Developer Workflow Commands

- **`/build-fix [path]`** — Auto-detect build system, run build, fix errors one at a time with regression guard.
- **`/tdd <feature>`** — Enforce RED-GREEN-REFACTOR cycle: failing test → minimal implementation → refactor.
- **`/quality-gate [path] [--fix]`** — Pre-commit validation: formatter + linter + type checker + tests.
- **`/checkpoint <name>`** — Named save points via git branches for complex multi-step work.
- **`/save-session [id]`** — Save structured session state with "What Did NOT Work" section.
- **`/resume-session [id]`** — Resume from a saved session with full context briefing.
- **`/optimize <metric>`** — Autonomous metric-driven improvement loop: measure → improve → keep/revert.

### 🔧 Built-in Tools (Always Available)

Beyond agents and skills, Claude Code provides these tools directly:

| Tool | Use When |
|------|----------|
| **TaskCreate/TaskUpdate/TaskList** | Multi-step work — structured task tracking with dependencies and progress |
| **CronCreate/CronDelete/CronList** | Recurring prompts, polling, reminders (session-scoped, 7-day max) |
| **EnterWorktree/ExitWorktree** | Parallel development — isolated git worktree branches for experiments or features |
| **RemoteTrigger** | Cross-session automation — create/run scheduled remote agents |
| **LSP** | Code intelligence — go-to-definition, find-references, hover, document symbols |
| **AskUserQuestion** | Structured user input with labeled options and previews |

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
- **SRE:** "SLO", "reliability", "runbook" → `sre-specialist`
- **Agent Creation:** "create agent", "generate agent" → `meta-agent`

**Orchestration Skills (Slash Commands):**
- `/deep-read <target>` — 6-phase codebase reading engine
- `/execute <goal>` — Orchestrated task execution with parallel batches
- `/investigate <symptom>` — 8-phase root cause analysis
- `/deep-analysis <problem>` — Structured multi-step reasoning

**Developer Workflow Commands:**
- `/build-fix` — Auto-detect build system, fix errors with regression guard
- `/tdd <feature>` — RED-GREEN-REFACTOR test-driven development
- `/quality-gate [--fix]` — Pre-commit formatter + linter + type checker
- `/checkpoint <name>` — Named save points for complex work
- `/save-session` / `/resume-session` — Cross-session continuity
- `/optimize <metric>` — Autonomous metric-driven improvement loop

**Built-in Tools (Always Available):**
- **TaskCreate/TaskUpdate/TaskList** — Structured task tracking with dependencies and progress
- **CronCreate/CronDelete/CronList** — Recurring prompts, polling, reminders (session-scoped, 7-day max)
- **EnterWorktree/ExitWorktree** — Isolated git worktree branches for experiments or features
- **RemoteTrigger** — Cross-session automation with scheduled remote agents
- **LSP** — Code intelligence: go-to-definition, find-references, hover, document symbols
- **AskUserQuestion** — Structured user input with labeled options and previews

**Example:** Say "build a REST API with authentication" and watch multiple agents collaborate automatically.

<!-- ============ CLAUDE AGENTS AUTO-ACTIVATION SECTION END ============ -->
EOF

    print_success "Appended agent configuration to CLAUDE.md"
}

append_orchestration_skills_section() {
    print_progress "Adding orchestration skills to CLAUDE.md..."

    cat >> CLAUDE.md << 'EOF'

### 🎯 Orchestration Skills (Slash Commands)

Use these for structured, multi-phase task execution:

- **`/deep-read <target>`** — 6-phase codebase reading engine. Reads actual source code line by line with file:line citations.
- **`/execute <goal>`** — Orchestrated task engine. Decomposes goals into atomic tasks, plans dependencies, executes in parallel batches.
- **`/investigate <symptom>`** — 8-phase root cause analysis. Uses 5 Whys, competing hypotheses, evidence classification.
- **`/deep-analysis <problem>`** — Structured multi-step reasoning via sequential-thinking MCP. For architecture decisions and trade-offs.

### 🛠️ Developer Workflow Commands

- **`/build-fix [path]`** — Auto-detect build system, run build, fix errors one at a time with regression guard.
- **`/tdd <feature>`** — Enforce RED-GREEN-REFACTOR cycle: failing test → minimal implementation → refactor.
- **`/quality-gate [path] [--fix]`** — Pre-commit validation: formatter + linter + type checker + tests.
- **`/checkpoint <name>`** — Named save points via git branches for complex multi-step work.
- **`/save-session [id]`** — Save structured session state with "What Did NOT Work" section.
- **`/resume-session [id]`** — Resume from a saved session with full context briefing.
- **`/optimize <metric>`** — Autonomous metric-driven improvement loop: measure → improve → keep/revert.

### 🔧 Built-in Tools (Always Available)

| Tool | Use When |
|------|----------|
| **TaskCreate/TaskUpdate/TaskList** | Multi-step work — structured task tracking with dependencies and progress |
| **CronCreate/CronDelete/CronList** | Recurring prompts, polling, reminders (session-scoped, 7-day max) |
| **EnterWorktree/ExitWorktree** | Parallel development — isolated git worktree branches for experiments or features |
| **RemoteTrigger** | Cross-session automation — create/run scheduled remote agents |
| **LSP** | Code intelligence — go-to-definition, find-references, hover, document symbols |
| **AskUserQuestion** | Structured user input with labeled options and previews |
EOF

    print_success "Added orchestration skills section to CLAUDE.md"
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

    # Copy hooks (executable shell scripts)
    for hook in "$src_dir"/hooks/*.sh; do
        [ -f "$hook" ] || continue
        local name
        name=$(basename "$hook")
        cp "$hook" ~/.claude/hooks/"$name"
        chmod +x ~/.claude/hooks/"$name"
        print_success "Installed hook $name"
    done

    # Copy hook reference configs (prompt/agent hook templates)
    for hook_cfg in "$src_dir"/hooks/*.json; do
        [ -f "$hook_cfg" ] || continue
        local name
        name=$(basename "$hook_cfg")
        cp "$hook_cfg" ~/.claude/hooks/"$name"
        print_success "Installed hook config $name"
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

    # Keybindings removed in v2.7 — personal preference, not framework-level

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

sync_hooks() {
    echo -e "\n${BOLD}Syncing Hooks:${NC}"

    local src_dir="${SCRIPT_DIR}/global-config/hooks"

    if [ ! -d "$src_dir" ]; then
        print_info "No hooks directory found in source — skipping"
        return 0
    fi

    mkdir -p ~/.claude/hooks

    for hook in "$src_dir"/*.sh; do
        [ -f "$hook" ] || continue
        local name
        name=$(basename "$hook")
        cp "$hook" ~/.claude/hooks/"$name"
        chmod +x ~/.claude/hooks/"$name"
        print_success "Synced hook $name"
    done

    for hook_cfg in "$src_dir"/*.json; do
        [ -f "$hook_cfg" ] || continue
        local name
        name=$(basename "$hook_cfg")
        cp "$hook_cfg" ~/.claude/hooks/"$name"
        print_success "Synced hook config $name"
    done

    # Reconcile hook events and env vars in settings.json against template.
    # Framework-managed hook events (those present in template) are the source of truth:
    # if user's version differs (missing, drifted command, drifted timeout, missing sub-hook),
    # REPLACE user's version with template. User env vars are preserved (only missing keys added).
    if [ -f ~/.claude/settings.json ] && command -v jq &>/dev/null; then
        local template="${SCRIPT_DIR}/global-config/settings.json.template"
        if [ -f "$template" ]; then
            local tmpl_events
            tmpl_events=$(jq -r '.hooks | keys[]' "$template" 2>/dev/null)
            local reconciled=false
            for event in $tmpl_events; do
                local tmpl_cfg usr_cfg
                tmpl_cfg=$(jq -Sc ".hooks[\"$event\"]" "$template")
                usr_cfg=$(jq -Sc ".hooks[\"$event\"] // null" ~/.claude/settings.json)
                if [ "$tmpl_cfg" != "$usr_cfg" ]; then
                    local event_config
                    event_config=$(jq ".hooks[\"$event\"]" "$template")
                    jq ".hooks[\"$event\"] = $event_config" ~/.claude/settings.json > ~/.claude/settings.json.tmp \
                        && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
                    if [ "$usr_cfg" = "null" ]; then
                        print_success "Added hook event $event to settings.json"
                    else
                        print_success "Reconciled drifted hook event $event (was: ${usr_cfg:0:80}...)"
                    fi
                    reconciled=true
                fi
            done
            if [ "$reconciled" = false ]; then
                print_skip "All hook events match template"
            fi

            # Merge new env vars into existing settings.json (add-only: user values preserved)
            local new_env_keys
            new_env_keys=$(jq -r '.env | keys[]' "$template" 2>/dev/null)
            for key in $new_env_keys; do
                if ! jq -e ".env[\"$key\"]" ~/.claude/settings.json &>/dev/null; then
                    local val
                    val=$(jq ".env[\"$key\"]" "$template")
                    jq ".env[\"$key\"] = $val" ~/.claude/settings.json > ~/.claude/settings.json.tmp \
                        && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
                    print_success "Added env var $key to settings.json"
                fi
            done

            # Reconcile .permissions (framework-owned, security-sensitive — same
            # replace-on-drift policy as hooks). Users who want custom permissions
            # should edit settings.local.json, which has higher precedence.
            if jq -e '.permissions' "$template" &>/dev/null; then
                local tmpl_perms usr_perms
                tmpl_perms=$(jq -Sc '.permissions' "$template")
                usr_perms=$(jq -Sc '.permissions // null' ~/.claude/settings.json)
                if [ "$tmpl_perms" != "$usr_perms" ]; then
                    local perms_value
                    perms_value=$(jq '.permissions' "$template")
                    jq ".permissions = $perms_value" ~/.claude/settings.json > ~/.claude/settings.json.tmp \
                        && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
                    if [ "$usr_perms" = "null" ]; then
                        print_success "Added permissions block to settings.json"
                    else
                        print_success "Reconciled permissions block in settings.json"
                    fi
                fi
            fi
        fi
    fi
}

install_analytics() {
    echo -e "\n${BOLD}Installing Analytics (Observability Dashboard):${NC}"

    local src_dir="${SCRIPT_DIR}/observability"

    if [ ! -d "$src_dir" ]; then
        print_info "observability/ directory not found — skipping analytics"
        return 0
    fi

    mkdir -p ~/.claude/analytics

    local errors=0
    for file in collector.py server.py dashboard.html schema.sql; do
        if [ -f "$src_dir/$file" ]; then
            cp "$src_dir/$file" ~/.claude/analytics/"$file"
            print_success "Installed analytics $file"
        else
            print_error "Missing observability/$file"
            ((errors++)) || true
        fi
    done

    if [ "$errors" -gt 0 ]; then
        return 1
    fi

    # Add claude-obs alias (idempotent)
    local shell_rc=""
    if [ -f "$HOME/.zshrc" ]; then
        shell_rc="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        shell_rc="$HOME/.bashrc"
    fi

    if [ -n "$shell_rc" ]; then
        if ! grep -q "claude-obs" "$shell_rc" 2>/dev/null; then
            echo '' >> "$shell_rc"
            echo '# Claude Code Observability' >> "$shell_rc"
            echo 'alias claude-obs="python3 ~/.claude/analytics/collector.py; python3 ~/.claude/analytics/server.py --open"' >> "$shell_rc"
            print_success "Added claude-obs alias to $(basename "$shell_rc")"
        else
            print_skip "claude-obs alias already in $(basename "$shell_rc")"
        fi
    fi
}

write_framework_path_marker() {
    # Records the repo root so the SessionStart healthcheck hook can locate it.
    mkdir -p "$HOME/.claude"
    echo "$SCRIPT_DIR" > "$HOME/.claude/.framework-path"
    print_success "Wrote framework path marker ($SCRIPT_DIR)"
}

write_framework_version_marker() {
    # Records the framework version and source SHA in the deployed project.
    # Invoked from every install mode so downstream tooling can tell what's deployed.
    # Skip when CWD is the source repo itself — the marker is a *deployment* artifact,
    # not part of the framework tree. Writing it there would dirty git status and
    # propagate via the next install to the 88 projects, overwriting their own markers.
    local cwd_real src_real
    cwd_real=$(pwd -P)
    src_real=$(cd "$SCRIPT_DIR" && pwd -P)
    if [ "$cwd_real" = "$src_real" ]; then
        print_skip "Framework version marker (source repo — marker is for deployments only)"
        return 0
    fi
    mkdir -p .claude
    local sha="unknown"
    if command -v git >/dev/null 2>&1; then
        sha=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
    fi
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    {
        echo "version=${SCRIPT_VERSION}"
        echo "sha=${sha}"
        echo "installed_at=${ts}"
    } > .claude/.framework-version
    print_success "Wrote framework version marker (v${SCRIPT_VERSION} @ ${sha})"
}

install_watchdog() {
    # macOS-only launchd watchdog
    if [[ "$(uname -s)" != "Darwin" ]]; then
        print_info "Not macOS — skipping watchdog daemon"
        return 0
    fi

    echo -e "\n${BOLD}Installing Watchdog Daemon:${NC}"

    local src_daemon_dir="${SCRIPT_DIR}/global-config/daemon"
    if [ ! -d "$src_daemon_dir" ]; then
        print_info "No daemon/ directory in source — skipping"
        return 0
    fi

    mkdir -p "$HOME/.claude/daemon"

    # Copy watchdog script
    if [ -f "$src_daemon_dir/claude-framework-watchdog.sh" ]; then
        cp "$src_daemon_dir/claude-framework-watchdog.sh" "$HOME/.claude/daemon/claude-framework-watchdog.sh"
        chmod +x "$HOME/.claude/daemon/claude-framework-watchdog.sh"
        print_success "Installed watchdog script"
    fi

    # Copy plist to LaunchAgents
    local plist_src="$src_daemon_dir/com.pfang.claude-framework-watchdog.plist"
    local plist_dst="$HOME/Library/LaunchAgents/com.pfang.claude-framework-watchdog.plist"
    if [ -f "$plist_src" ]; then
        mkdir -p "$HOME/Library/LaunchAgents"
        cp "$plist_src" "$plist_dst"
        # Substitute template path /Users/pfang/ with caller's $HOME so the plist
        # works for any user. sed -i '' for BSD sed (macOS); Label is left alone
        # because renaming a loaded launchd Label breaks idempotent re-install.
        sed -i '' "s|/Users/pfang/|${HOME}/|g" "$plist_dst" 2>/dev/null || true
        print_success "Installed plist to LaunchAgents"

        # Try bootstrap, fall back to load
        local uid
        uid=$(id -u)
        if launchctl bootstrap "gui/$uid" "$plist_dst" 2>/dev/null; then
            print_success "Loaded daemon via launchctl bootstrap"
        elif launchctl load "$plist_dst" 2>/dev/null; then
            print_success "Loaded daemon via launchctl load (fallback)"
        else
            # Already loaded — idempotent
            if launchctl list 2>/dev/null | grep -q claude-framework-watchdog; then
                print_skip "Daemon already loaded (re-copy ok)"
            else
                print_info "Could not auto-load daemon (try manually: launchctl bootstrap gui/$uid $plist_dst)"
            fi
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

ensure_statusline() {
    # Install statusline if not already present (idempotent, never overwrites)
    if [ -f "$HOME/.claude/statusline.sh" ]; then
        print_skip "Statusline already installed"
        return 0
    fi

    local src="${SCRIPT_DIR}/global-config/statusline.sh"
    if [ -f "$src" ]; then
        mkdir -p "$HOME/.claude"
        cp "$src" "$HOME/.claude/statusline.sh"
        chmod +x "$HOME/.claude/statusline.sh"
        print_success "Installed statusline.sh (first-time setup)"
    fi
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
    if [ -f ".mcp.json" ] && grep -q '/Users/\|/home/' ".mcp.json" 2>/dev/null; then
        # Existing config has hardcoded user paths — replace with portable template
        if [ -f "${SCRIPT_DIR}/.mcp.json.example" ]; then
            cp "${SCRIPT_DIR}/.mcp.json.example" ".mcp.json"
            print_success "Replaced MCP configuration (removed hardcoded paths)"
        fi
    elif [ -f ".mcp.json" ]; then
        print_skip "MCP configuration (.mcp.json) already exists"
    elif [ -f "${SCRIPT_DIR}/.mcp.json.example" ]; then
        cp "${SCRIPT_DIR}/.mcp.json.example" ".mcp.json"
        print_success "Installed MCP configuration (.mcp.json from template)"
    elif [ -f "${SCRIPT_DIR}/.mcp.json" ]; then
        cp "${SCRIPT_DIR}/.mcp.json" ".mcp.json"
        print_success "Installed MCP configuration (.mcp.json)"
    fi

    # Handle CLAUDE.md
    if [ -f "CLAUDE.md" ]; then
        append_claude_md_section
    else
        install_minimal_claude_md
    fi

    # Install analytics dashboard (global, once per machine)
    install_analytics || ((install_errors++)) || true

    # Ensure statusline is installed (global, once per machine)
    ensure_statusline

    # Record framework path for SessionStart healthcheck hook
    write_framework_path_marker

    # Record framework version/SHA in the deployed project
    write_framework_version_marker

    # Install watchdog daemon (macOS only)
    install_watchdog || true

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
    if [ -f ".mcp.json" ] && grep -q '/Users/\|/home/' ".mcp.json" 2>/dev/null; then
        if [ -f "${SCRIPT_DIR}/.mcp.json.example" ]; then
            cp "${SCRIPT_DIR}/.mcp.json.example" ".mcp.json"
            print_success "Replaced MCP configuration (removed hardcoded paths)"
        fi
    elif [ -f ".mcp.json" ]; then
        print_skip "MCP configuration already present"
    elif [ -f "${SCRIPT_DIR}/.mcp.json.example" ]; then
        cp "${SCRIPT_DIR}/.mcp.json.example" ".mcp.json"
        print_success "Installed MCP configuration (.mcp.json from template)"
    elif [ -f "${SCRIPT_DIR}/.mcp.json" ]; then
        cp "${SCRIPT_DIR}/.mcp.json" ".mcp.json"
        print_success "Installed MCP configuration (.mcp.json)"
    else
        print_skip "No MCP configuration template found"
    fi

    # Fix CLAUDE.md if needed
    if [ ! -f "CLAUDE.md" ]; then
        install_minimal_claude_md
    elif ! grep -q "Auto-Activating" CLAUDE.md 2>/dev/null; then
        append_claude_md_section
    else
        print_skip "CLAUDE.md already configured"
    fi

    # Patch meta-agent into existing CLAUDE.md agents table
    patch_meta_agent_in_claude_md

    # Patch sre-specialist into existing CLAUDE.md agents table
    patch_sre_specialist_in_claude_md

    # Patch Developer Workflow Commands section if missing
    patch_developer_workflow_in_claude_md

    # Patch Built-in Tools section if missing
    patch_builtin_tools_in_claude_md

    # Sync hooks to global ~/.claude/hooks/
    sync_hooks

    # Repair analytics dashboard
    install_analytics || print_error "Analytics installation failed"

    # Ensure statusline is installed
    ensure_statusline

    # Record framework path for SessionStart healthcheck hook
    write_framework_path_marker

    # Record framework version/SHA in the deployed project
    write_framework_version_marker

    # Install watchdog daemon (macOS only)
    install_watchdog || true
}

patch_developer_workflow_in_claude_md() {
    # Patch CLAUDE.md to add Developer Workflow Commands section if missing
    if [ ! -f "CLAUDE.md" ]; then
        return 0
    fi
    if grep -q "Developer Workflow" CLAUDE.md 2>/dev/null; then
        return 0
    fi
    if ! grep -q "Orchestration Skills\|Auto-Activating" CLAUDE.md 2>/dev/null; then
        return 0
    fi

    # Append developer workflow section after orchestration skills or at end of agents section
    cat >> CLAUDE.md << 'EOF'

### 🛠️ Developer Workflow Commands

- **`/build-fix [path]`** — Auto-detect build system, run build, fix errors one at a time with regression guard.
- **`/tdd <feature>`** — Enforce RED-GREEN-REFACTOR cycle: failing test → minimal implementation → refactor.
- **`/quality-gate [path] [--fix]`** — Pre-commit validation: formatter + linter + type checker + tests.
- **`/checkpoint <name>`** — Named save points via git branches for complex multi-step work.
- **`/save-session [id]`** — Save structured session state with "What Did NOT Work" section.
- **`/resume-session [id]`** — Resume from a saved session with full context briefing.
- **`/optimize <metric>`** — Autonomous metric-driven improvement loop: measure → improve → keep/revert.
EOF

    print_success "Patched CLAUDE.md: added Developer Workflow Commands section"
}

patch_builtin_tools_in_claude_md() {
    # Patch CLAUDE.md to add Built-in Tools section if missing
    if [ ! -f "CLAUDE.md" ]; then
        return 0
    fi
    if grep -q "Built-in Tools" CLAUDE.md 2>/dev/null; then
        return 0
    fi
    if ! grep -q "Auto-Activating\|Orchestration Skills\|Developer Workflow" CLAUDE.md 2>/dev/null; then
        return 0
    fi

    cat >> CLAUDE.md << 'EOF'

### 🔧 Built-in Tools (Always Available)

| Tool | Use When |
|------|----------|
| **TaskCreate/TaskUpdate/TaskList** | Multi-step work — structured task tracking with dependencies and progress |
| **CronCreate/CronDelete/CronList** | Recurring prompts, polling, reminders (session-scoped, 7-day max) |
| **EnterWorktree/ExitWorktree** | Parallel development — isolated git worktree branches for experiments or features |
| **RemoteTrigger** | Cross-session automation — create/run scheduled remote agents |
| **LSP** | Code intelligence — go-to-definition, find-references, hover, document symbols |
| **AskUserQuestion** | Structured user input with labeled options and previews |
EOF

    print_success "Patched CLAUDE.md: added Built-in Tools section"
}

patch_sre_specialist_in_claude_md() {
    # Patch CLAUDE.md to add sre-specialist row if missing from agents table
    if [ ! -f "CLAUDE.md" ]; then
        return 0
    fi
    if grep -q "sre-specialist" CLAUDE.md 2>/dev/null; then
        return 0
    fi
    if ! grep -q "incident-commander" CLAUDE.md 2>/dev/null; then
        return 0
    fi
    # Insert sre-specialist line after incident-commander (handles both table and list formats)
    if grep -q 'incident-commander.*|' CLAUDE.md 2>/dev/null; then
        # Table format
        sed -i '' '/incident-commander.*|/{
a\
| "define SLOs" | **sre-specialist** | SRE, reliability, runbooks |
}' CLAUDE.md
    elif grep -q 'incident-commander' CLAUDE.md 2>/dev/null; then
        # List format
        sed -i '' '/incident-commander/{
a\
- **SRE:** "SLO", "reliability", "runbook" → `sre-specialist`
}' CLAUDE.md
    fi
    if grep -q "sre-specialist" CLAUDE.md 2>/dev/null; then
        print_success "Patched CLAUDE.md: added sre-specialist to agents table"
    fi
}

patch_meta_agent_in_claude_md() {
    # Patch CLAUDE.md to add meta-agent row if missing from agents table
    if [ ! -f "CLAUDE.md" ]; then
        return 0
    fi
    if grep -q "meta-agent" CLAUDE.md 2>/dev/null; then
        return 0
    fi
    if ! grep -q "incident-commander" CLAUDE.md 2>/dev/null; then
        return 0
    fi
    # Insert meta-agent line after incident-commander (handles both table and list formats)
    if grep -q 'incident-commander.*|' CLAUDE.md 2>/dev/null; then
        # Table format: | "production is down!" | **incident-commander** | ... |
        sed -i '' '/incident-commander.*|/{
a\
| "create an agent" | **meta-agent** | Generates new specialized agents |
}' CLAUDE.md
    elif grep -q 'incident-commander' CLAUDE.md 2>/dev/null; then
        # List format: - **Emergency:** ... → `incident-commander`
        sed -i '' '/incident-commander/{
a\
- **Agent Creation:** "create agent", "generate agent" → `meta-agent`
}' CLAUDE.md
    fi
    if grep -q "meta-agent" CLAUDE.md 2>/dev/null; then
        print_success "Patched CLAUDE.md: added meta-agent to agents table"
    fi
}

clean_old_agents() {
    # Remove agent files from v1.0 that have been renamed or replaced
    local OLD_AGENTS=(
        "architect.md"
        "connector.md"
        "documenter.md"
        "guardian.md"
        "accessibility.md"
        "api-reliability.md"
        "documentation.md"
        "mobile-ux.md"
        "performance.md"
        "schema-guardian.md"
        "security.md"
    )

    local cleaned=0
    for agent in "${OLD_AGENTS[@]}"; do
        if [ -f ".claude/agents/${agent}" ]; then
            rm ".claude/agents/${agent}"
            echo -e "  ${GREEN}✓${NC} Removed old ${agent}"
            ((cleaned++))
        fi
    done

    if [ $cleaned -gt 0 ]; then
        print_success "Cleaned $cleaned old v1.0 agent file(s)"
    fi
}

update_installation() {
    # Concurrency guard: prevent two concurrent --update runs from racing on
    # ~/.claude/settings.json (jq read-modify-write isn't atomic). Portable
    # lockfile via `mkdir` (atomic on POSIX filesystems) — macOS bash lacks
    # flock(1). Non-blocking: if another install is running, exit cleanly so
    # the healthcheck-hook / watchdog self-heal loop doesn't log errors.
    local lock_dir="$HOME/.claude/.install.lock.d"
    mkdir -p "$HOME/.claude" 2>/dev/null || true
    if ! mkdir "$lock_dir" 2>/dev/null; then
        echo "another install is running — exiting cleanly" >&2
        return 0
    fi
    # shellcheck disable=SC2064
    trap "rmdir '$lock_dir' 2>/dev/null || true" EXIT INT TERM

    echo -e "\n${BOLD}Updating Installation${NC}"
    echo "This will update all components to latest version"

    backup_existing

    # Ensure all directories exist (old installs may lack skills/, commands/, rules/)
    mkdir -p .claude/agents .claude/lib .claude/rules .claude/skills .claude/commands

    # Clean old v1.0 agents that have been renamed
    echo -e "\n${BOLD}Cleaning Old Components:${NC}"
    clean_old_agents

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
            if [ -f ".claude/rules/$name" ] && [ "$file" -ef ".claude/rules/$name" ]; then
                print_skip "Rule $name (in-place)"
            else
                cp "$file" ".claude/rules/$name"
                print_success "Updated rule $name"
            fi
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
            if [ -d ".claude/skills/$name" ] && [ "$skill_dir" -ef ".claude/skills/$name" ]; then
                print_skip "Skill $name (in-place)"
            else
                cp -r "$skill_dir" ".claude/skills/$name"
                print_success "Updated skill $name"
            fi
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
            if [ -f ".claude/commands/$name" ] && [ "$file" -ef ".claude/commands/$name" ]; then
                print_skip "Command $name (in-place)"
            else
                cp "$file" ".claude/commands/$name"
                print_success "Updated command $name"
            fi
            (( STATS_UPDATED++ )) || true
        done
    fi

    # Update MCP configuration
    if [ ! -f ".mcp.json" ]; then
        # No config exists — install from template
        if [ -f "${SCRIPT_DIR}/.mcp.json.example" ]; then
            cp "${SCRIPT_DIR}/.mcp.json.example" ".mcp.json"
            print_success "Installed MCP configuration (.mcp.json from template)"
            (( STATS_UPDATED++ )) || true
        elif [ -f "${SCRIPT_DIR}/.mcp.json" ]; then
            cp "${SCRIPT_DIR}/.mcp.json" ".mcp.json"
            print_success "Installed MCP configuration (.mcp.json)"
            (( STATS_UPDATED++ )) || true
        fi
    elif grep -q '/Users/\|/home/' ".mcp.json" 2>/dev/null; then
        # Existing config has hardcoded user paths — replace with portable template
        if [ -f "${SCRIPT_DIR}/.mcp.json.example" ]; then
            cp "${SCRIPT_DIR}/.mcp.json.example" ".mcp.json"
            print_success "Replaced MCP configuration (removed hardcoded paths)"
            (( STATS_UPDATED++ )) || true
        fi
    else
        print_skip "MCP configuration (.mcp.json) already exists"
    fi

    # Sync hooks to global ~/.claude/hooks/
    sync_hooks

    # Update analytics dashboard (installs if missing, updates if present)
    install_analytics || print_error "Analytics installation failed"

    # Handle CLAUDE.md — regenerate framework sections, preserve user content
    if [ -f "CLAUDE.md" ]; then
        if grep -q "CLAUDE AGENTS AUTO-ACTIVATION SECTION START" CLAUDE.md 2>/dev/null; then
            # Has markers — delete between markers and re-append latest
            sed -i '' '/<!-- .* CLAUDE AGENTS AUTO-ACTIVATION SECTION START/,/<!-- .* CLAUDE AGENTS AUTO-ACTIVATION SECTION END/d' CLAUDE.md
            append_claude_md_section
            print_success "Regenerated agent section in CLAUDE.md (marker-based)"
        elif grep -q "Just Use Natural Language" CLAUDE.md 2>/dev/null; then
            # Minimal template (we own the file) — regenerate entirely
            install_minimal_claude_md
            print_success "Regenerated CLAUDE.md (minimal template)"
        elif grep -q "Auto-Activating\|auto-activate" CLAUDE.md 2>/dev/null; then
            # Patched file (no markers) — use patch functions for incremental updates
            patch_meta_agent_in_claude_md
            patch_sre_specialist_in_claude_md
            patch_developer_workflow_in_claude_md
            patch_builtin_tools_in_claude_md
        else
            # No agent section at all — append
            append_claude_md_section
        fi
    else
        install_minimal_claude_md
    fi

    # Ensure statusline is installed
    ensure_statusline

    # Record framework path for SessionStart healthcheck hook
    write_framework_path_marker

    # Record framework version/SHA in the deployed project
    write_framework_version_marker

    # Install watchdog daemon (macOS only)
    install_watchdog || true
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

    if [ "$MODE" = "--full" ] || [ "$MODE" = "--update" ] || [ "$choice" = "2" ] || [ "$choice" = "4" ]; then
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