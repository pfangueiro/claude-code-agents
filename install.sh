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

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Claude Code Agents v2.0 Installation    ║${NC}"
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

echo -e "${BLUE}Installing Claude Code Agents to:${NC} $TARGET_DIR"
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

# Step 2: Handle CLAUDE.md
print_info "Setting up CLAUDE.md..."
if [ -f "$TARGET_DIR/CLAUDE.md" ]; then
    print_warning "CLAUDE.md already exists in target"
    read -p "Do you want to backup and replace with template? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        mv "$TARGET_DIR/CLAUDE.md" "$TARGET_DIR/CLAUDE.md.backup"
        cp "$SCRIPT_DIR/CLAUDE.md.template" "$TARGET_DIR/CLAUDE.md"
        print_success "Existing CLAUDE.md backed up, template installed"
        print_info "Please edit CLAUDE.md to match your project"
    else
        print_info "Keeping existing CLAUDE.md"
    fi
else
    cp "$SCRIPT_DIR/CLAUDE.md.template" "$TARGET_DIR/CLAUDE.md"
    print_success "CLAUDE.md template installed"
    print_info "Please edit CLAUDE.md to configure for your project"
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