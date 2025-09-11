#!/bin/bash

# Claude Code Agents Installation Script
# This script helps you install the Claude Code agents into your project

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Claude Code Agents v3.0 Installation    ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo

# Check for required dependencies
print_info "Checking dependencies..."
MISSING_DEPS=""

if ! command -v git &> /dev/null; then
    MISSING_DEPS="${MISSING_DEPS} git"
fi

if ! command -v jq &> /dev/null; then
    print_warning "jq not installed - JSON tracking features will be limited"
    print_info "  Install with: brew install jq (macOS) or apt-get install jq (Linux)"
fi

if ! command -v bc &> /dev/null; then
    print_warning "bc not installed - Cost calculations will not work"
    print_info "  Install with: brew install bc (macOS) or apt-get install bc (Linux)"
fi

if ! command -v uuidgen &> /dev/null && ! command -v uuid &> /dev/null; then
    print_warning "uuidgen not installed - Task IDs will use timestamps"
    print_info "  Install with: brew install ossp-uuid (macOS) or apt-get install uuid-runtime (Linux)"
fi

if [ ! -z "$MISSING_DEPS" ]; then
    print_error "Required dependencies missing:$MISSING_DEPS"
    print_info "Please install missing dependencies and try again"
    exit 1
fi

# Validate source directory
if [ ! -d "$SCRIPT_DIR/.claude" ]; then
    print_error "Installation source corrupted: .claude directory not found"
    print_info "Please re-clone the repository and try again"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/CLAUDE.md.template" ]; then
    print_error "Installation source corrupted: CLAUDE.md.template not found"
    exit 1
fi

# Check if target directory is provided
if [ -z "$1" ]; then
    print_info "Usage: ./install.sh <target-project-directory>"
    print_info "Example: ./install.sh ~/projects/my-app"
    echo
    print_info "This will install:"
    print_info "  • .claude/ directory with all agents and commands"
    print_info "  • CLAUDE.md template for project configuration"
    print_info "  • Tracking hooks and scripts"
    echo
    print_info "System requirements:"
    print_info "  • git (required)"
    print_info "  • jq (recommended for tracking)"
    print_info "  • bc (recommended for cost calculation)"
    print_info "  • gh CLI (optional for GitHub integration)"
    echo
    exit 1
fi

TARGET_DIR="$1"

# Check if target directory exists
if [ ! -d "$TARGET_DIR" ]; then
    print_error "Target directory does not exist: $TARGET_DIR"
    exit 1
fi

# Project Auto-Detection Engine
detect_project_type() {
    local project_dir="$1"
    local detected_type="generic"
    local tech_stack=""
    
    print_info "Auto-detecting project type..."
    
    # Node.js/JavaScript Detection
    if [ -f "$project_dir/package.json" ]; then
        tech_stack="nodejs"
        if grep -q "next" "$project_dir/package.json" 2>/dev/null; then
            detected_type="nextjs"
        elif grep -q "react" "$project_dir/package.json" 2>/dev/null; then
            detected_type="react"
        elif grep -q "vue" "$project_dir/package.json" 2>/dev/null; then
            detected_type="vue"
        elif grep -q "angular" "$project_dir/package.json" 2>/dev/null; then
            detected_type="angular"
        elif grep -q "express" "$project_dir/package.json" 2>/dev/null; then
            detected_type="nodejs-api"
        else
            detected_type="nodejs"
        fi
    # Python Detection
    elif [ -f "$project_dir/requirements.txt" ] || [ -f "$project_dir/pyproject.toml" ]; then
        tech_stack="python"
        if [ -f "$project_dir/manage.py" ] || grep -q "django" "$project_dir/requirements.txt" 2>/dev/null; then
            detected_type="django"
        elif grep -q "fastapi" "$project_dir/requirements.txt" 2>/dev/null || grep -q "fastapi" "$project_dir/pyproject.toml" 2>/dev/null; then
            detected_type="fastapi"
        elif grep -q "flask" "$project_dir/requirements.txt" 2>/dev/null; then
            detected_type="flask"
        else
            detected_type="python"
        fi
    # Rust Detection
    elif [ -f "$project_dir/Cargo.toml" ]; then
        tech_stack="rust"
        detected_type="rust"
    # Go Detection
    elif [ -f "$project_dir/go.mod" ]; then
        tech_stack="go"
        detected_type="go"
    # Java Detection
    elif [ -f "$project_dir/pom.xml" ] || [ -f "$project_dir/build.gradle" ]; then
        tech_stack="java"
        detected_type="java"
    # PHP Detection
    elif [ -f "$project_dir/composer.json" ]; then
        tech_stack="php"
        detected_type="php"
    # Ruby Detection
    elif [ -f "$project_dir/Gemfile" ]; then
        tech_stack="ruby"
        detected_type="ruby"
    fi
    
    echo "$detected_type|$tech_stack"
}

# Auto-detect project configuration
PROJECT_INFO=$(detect_project_type "$TARGET_DIR")
PROJECT_TYPE=$(echo "$PROJECT_INFO" | cut -d'|' -f1)
TECH_STACK=$(echo "$PROJECT_INFO" | cut -d'|' -f2)

print_success "Detected project type: $PROJECT_TYPE ($TECH_STACK)"

echo -e "${BLUE}Installing Claude Code Agents v3.0 to:${NC} $TARGET_DIR"
echo -e "${BLUE}Project Configuration:${NC} $PROJECT_TYPE with $TECH_STACK optimization"
echo

# Step 1: Copy .claude directory
print_info "Copying agents and commands..."
if [ -d "$TARGET_DIR/.claude" ]; then
    print_warning ".claude directory already exists in target"
    read -p "Do you want to merge/overwrite? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Skipping .claude directory"
    else
        cp -r "$SCRIPT_DIR/.claude" "$TARGET_DIR/"
        print_success "Agents and commands installed"
    fi
else
    cp -r "$SCRIPT_DIR/.claude" "$TARGET_DIR/"
    print_success "Agents and commands installed"
fi

# Step 2: Generate Project-Specific CLAUDE.md
generate_project_claude_md() {
    local project_type="$1"
    local tech_stack="$2"
    local target_dir="$3"
    
    # Start with base template
    local claude_content="# Claude Code Agents v3.0 - Auto-Configured for $PROJECT_TYPE

## 🎯 Project Context (Auto-Detected)
**Project Type**: $project_type
**Tech Stack**: $tech_stack
**Auto-Configuration**: Optimized agent priorities and workflows

## 🏗️ Project Structure (Auto-Detected)
"
    
    # Add project-specific structure and configuration
    case "$project_type" in
        "nextjs")
            claude_content+="### Next.js Project Optimization
**Primary Agents**: frontend-architect, typescript-expert, performance-optimizer
**Workflows**: Component development → Testing → Performance optimization → Deployment
**Cost Optimization**: Sonnet models for development, Haiku for documentation
"
            ;;
        "react")
            claude_content+="### React Project Optimization  
**Primary Agents**: frontend-architect, ui-ux-specialist, test-engineer
**Workflows**: Component development → UI/UX review → Testing → Deployment
**Cost Optimization**: Focus on Sonnet models for component development
"
            ;;
        "fastapi"|"django"|"flask")
            claude_content+="### Python API Project Optimization
**Primary Agents**: python-expert, api-builder, secure-coder, database-architect
**Workflows**: API development → Security review → Database optimization → Testing
**Cost Optimization**: Sonnet for development, Opus for security reviews
"
            ;;
        "nodejs-api")
            claude_content+="### Node.js API Project Optimization
**Primary Agents**: api-builder, typescript-expert, secure-coder, performance-optimizer
**Workflows**: API development → Type safety → Security → Performance → Deployment
**Cost Optimization**: Balanced model usage with Opus for security
"
            ;;
        *)
            claude_content+="### Generic Project Optimization
**Primary Agents**: Auto-configured based on file types and patterns
**Workflows**: Adaptive workflows based on detected patterns
**Cost Optimization**: Dynamic model selection based on task complexity
"
            ;;
    esac
    
    # Add auto-activation examples specific to project type
    claude_content+="
## 🤖 Auto-Activation Examples for Your Project

### Natural Language Triggers (Just speak normally):
"
    
    case "$project_type" in
        "nextjs"|"react"|"vue"|"angular")
            claude_content+="- \"Create a responsive component for the dashboard\"
- \"Add state management to the user profile page\"  
- \"Optimize the bundle size and loading performance\"
- \"Add TypeScript interfaces for the API responses\"
"
            ;;
        "fastapi"|"django"|"flask"|"nodejs-api")
            claude_content+="- \"Create REST endpoints for user authentication\"
- \"Optimize the database queries for better performance\"
- \"Add input validation and security measures\"
- \"Write comprehensive API tests\"
"
            ;;
        *)
            claude_content+="- \"Analyze the project structure and optimize performance\"
- \"Add security measures and vulnerability scanning\"
- \"Create comprehensive test coverage\"
- \"Optimize costs and improve efficiency\"
"
            ;;
    esac
    
    claude_content+="
## 📊 Project-Specific Agent Priorities (Auto-Configured)
"
    
    # Add agent priorities based on project type
    case "$project_type" in
        "nextjs"|"react")
            claude_content+="### High Priority Agents
- **frontend-architect** (Sonnet): Component development and architecture
- **typescript-expert** (Sonnet): Type safety and code quality
- **ui-ux-specialist** (Sonnet): User experience optimization
- **performance-optimizer** (Opus): Bundle optimization and performance

### Medium Priority Agents  
- **test-engineer** (Sonnet): Component and integration testing
- **secure-coder** (Opus): Security review and vulnerability scanning
- **deployment-engineer** (Opus): CI/CD and deployment automation
"
            ;;
        "fastapi"|"django"|"flask"|"nodejs-api")
            claude_content+="### High Priority Agents
- **api-builder** (Sonnet): REST API development and design
- **database-architect** (Sonnet): Schema design and query optimization  
- **secure-coder** (Opus): Security review and vulnerability scanning
- **python-expert** (Sonnet): Python best practices and optimization

### Medium Priority Agents
- **test-engineer** (Sonnet): API testing and validation
- **performance-optimizer** (Opus): Database and API performance
- **deployment-engineer** (Opus): Containerization and deployment
"
            ;;
        *)
            claude_content+="### Adaptive Agent Priorities
- **context-analyzer** (Haiku): Project analysis and optimization
- **ai-optimizer** (Sonnet): Cost and performance optimization
- **workflow-learner** (Opus): Learn patterns and optimize workflows
- **integration-specialist** (Sonnet): Tool and service integration
"
            ;;
    esac
    
    claude_content+="
---
*Auto-configured for $project_type projects | Claude Code Agents v3.0*
*Customization: Edit this file to adjust priorities and workflows*"
    
    echo "$claude_content"
}

# Step 2: Handle CLAUDE.md with Auto-Configuration
print_info "Setting up project-specific CLAUDE.md..."
if [ -f "$TARGET_DIR/CLAUDE.md" ]; then
    print_warning "CLAUDE.md already exists in target"
    read -p "Do you want to backup and replace with auto-configured version? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        mv "$TARGET_DIR/CLAUDE.md" "$TARGET_DIR/CLAUDE.md.backup"
        generate_project_claude_md "$PROJECT_TYPE" "$TECH_STACK" "$TARGET_DIR" > "$TARGET_DIR/CLAUDE.md"
        print_success "Existing CLAUDE.md backed up, auto-configured version installed"
        print_info "CLAUDE.md optimized for $PROJECT_TYPE projects"
    else
        print_info "Keeping existing CLAUDE.md"
    fi
else
    generate_project_claude_md "$PROJECT_TYPE" "$TECH_STACK" "$TARGET_DIR" > "$TARGET_DIR/CLAUDE.md"
    print_success "Auto-configured CLAUDE.md created for $PROJECT_TYPE"
    print_info "Agent priorities optimized for your $TECH_STACK project"
fi

# Step 3: Create .gitignore entries if needed
if [ -f "$TARGET_DIR/.gitignore" ]; then
    if ! grep -q ".claude/\*.log" "$TARGET_DIR/.gitignore"; then
        print_info "Adding Claude-specific entries to .gitignore..."
        echo "" >> "$TARGET_DIR/.gitignore"
        echo "# Claude Code" >> "$TARGET_DIR/.gitignore"
        echo ".claude/*.log" >> "$TARGET_DIR/.gitignore"
        echo ".claude/.DS_Store" >> "$TARGET_DIR/.gitignore"
        print_success "Updated .gitignore"
    fi
fi

# Step 4: Show summary
echo
echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Installation Complete! 🎉          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
echo

print_success "18 agents installed:"
echo "  • 15 core agents (with model optimization)"
echo "  • 3 specialist agents (Python, TypeScript, Infrastructure)"
echo

print_success "3 custom commands available:"
echo "  • /workflow - Execute development pipelines"
echo "  • /orchestrate - Coordinate multiple agents"
echo "  • /quality-check - Run quality gates"
echo

print_info "Next steps:"
echo "  1. Edit ${TARGET_DIR}/CLAUDE.md for your project"
echo "  2. Open Claude Code in ${TARGET_DIR}"
echo "  3. Agents will activate automatically based on keywords"
echo

print_info "Quick test:"
echo "  Try: 'Create a REST API for user management'"
echo "  This will activate: api-builder → test-engineer → deployment-engineer"
echo

print_info "Documentation:"
echo "  • README: ${SCRIPT_DIR}/README.md"
echo "  • Example: ${SCRIPT_DIR}/CLAUDE.md.example"
echo

echo -e "${BLUE}Happy coding with Claude Code Agents! 🚀${NC}"