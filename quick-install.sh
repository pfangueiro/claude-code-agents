#!/usr/bin/env bash
#
# Claude Agents - one-line installer
#
#   curl -fsSL https://raw.githubusercontent.com/pfangueiro/claude-code-agents/main/quick-install.sh | bash
#
# Clones (or updates) the framework, then delegates to install.sh, which installs
# everything USER-GLOBAL to ~/.claude. Claude Code loads ~/.claude/{agents,skills,
# commands,rules} in every project, so the agents work everywhere automatically.
#
# Override the checkout location with CLAUDE_AGENTS_HOME.

set -euo pipefail

REPO_URL="https://github.com/pfangueiro/claude-code-agents.git"
INSTALL_DIR="${CLAUDE_AGENTS_HOME:-$HOME/.claude-code-agents}"

# Colors (disabled when stdout is not a terminal)
if [ -t 1 ]; then
    GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
else
    GREEN=''; BLUE=''; YELLOW=''; RED=''; NC=''
fi

info() { printf "${BLUE}%s${NC}\n" "$1"; }
ok()   { printf "${GREEN}%s${NC}\n" "$1"; }
warn() { printf "${YELLOW}%s${NC}\n" "$1"; }
fail() { printf "${RED}%s${NC}\n" "$1" >&2; exit 1; }

info "Claude Agents - installer"

# Prerequisites
command -v git  >/dev/null 2>&1 || fail "git is required but not installed."
command -v curl >/dev/null 2>&1 || fail "curl is required but not installed."

# Clone fresh, or update an existing checkout
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing checkout in $INSTALL_DIR ..."
    git -C "$INSTALL_DIR" pull --ff-only || warn "git pull failed; using existing checkout."
    MODE="--update"
else
    info "Cloning into $INSTALL_DIR ..."
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" || fail "Clone failed."
    MODE=""
fi

# Delegate ALL install logic to install.sh (installs user-global to ~/.claude).
cd "$INSTALL_DIR"
chmod +x install.sh 2>/dev/null || true

if [ -n "$MODE" ]; then
    ./install.sh "$MODE"
else
    ./install.sh
fi

ok "Done. The agents are now available in every project on your machine."
echo "Open any project with Claude Code and just describe what you need."
echo "Update any time with: cd \"$INSTALL_DIR\" && ./install.sh --update"
