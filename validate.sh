#!/bin/bash

# ============================================================================
# Claude Agents - Validation Script
# ============================================================================
# Validates that all agents, skills, lib files, and configuration are correct.
#
# Usage:
#   ./validate.sh           - Run all checks
#   ./validate.sh --quiet   - Only show errors
# ============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

QUIET="${1:-}"
ERRORS=0
WARNINGS=0
CHECKS=0

pass() {
    ((CHECKS++))
    [ "$QUIET" = "--quiet" ] || echo -e "  ${GREEN}PASS${NC} $1"
}

fail() {
    ((CHECKS++))
    ((ERRORS++))
    echo -e "  ${RED}FAIL${NC} $1"
}

warn() {
    ((CHECKS++))
    ((WARNINGS++))
    echo -e "  ${YELLOW}WARN${NC} $1"
}

section() {
    [ "$QUIET" = "--quiet" ] || echo -e "\n${BOLD}$1${NC}"
}

# ============================================================================
# Agent Validation
# ============================================================================

EXPECTED_AGENTS=(
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

section "Checking Agent Files (${#EXPECTED_AGENTS[@]} expected)"

for agent in "${EXPECTED_AGENTS[@]}"; do
    agent_file=".claude/agents/${agent}.md"

    if [ ! -f "$agent_file" ]; then
        fail "Missing agent file: $agent_file"
        continue
    fi

    # Check required frontmatter fields
    has_frontmatter=true
    for field in name description tools model color; do
        if ! grep -q "^${field}:" "$agent_file" 2>/dev/null; then
            fail "$agent: missing frontmatter field '$field'"
            has_frontmatter=false
        fi
    done

    if [ "$has_frontmatter" = true ]; then
        pass "$agent: frontmatter complete"
    fi

    # Check required sections
    if grep -q "^# Purpose" "$agent_file" 2>/dev/null; then
        pass "$agent: has # Purpose section"
    else
        fail "$agent: missing # Purpose section"
    fi

    if grep -q "^## Instructions" "$agent_file" 2>/dev/null; then
        pass "$agent: has ## Instructions section"
    else
        fail "$agent: missing ## Instructions section"
    fi
done

# ============================================================================
# Library File Validation
# ============================================================================

EXPECTED_LIBS=(
    "agent-templates.json"
    "sdlc-patterns.md"
    "activation-keywords.json"
    "agent-coordination.md"
)

section "Checking Library Files (${#EXPECTED_LIBS[@]} expected)"

for lib in "${EXPECTED_LIBS[@]}"; do
    lib_file=".claude/lib/${lib}"

    if [ ! -f "$lib_file" ]; then
        fail "Missing lib file: $lib_file"
        continue
    fi

    pass "Exists: $lib"

    # Validate JSON files
    if [[ "$lib" == *.json ]]; then
        if command -v jq &>/dev/null; then
            if jq empty "$lib_file" 2>/dev/null; then
                pass "$lib: valid JSON"
            else
                fail "$lib: invalid JSON"
            fi
        else
            warn "$lib: jq not installed, skipping JSON validation"
        fi
    fi
done

# ============================================================================
# Skills Validation
# ============================================================================

section "Checking Skills"

if [ -d ".claude/skills" ]; then
    skill_count=0
    for skill_dir in .claude/skills/*/; do
        [ -d "$skill_dir" ] || continue
        skill_name=$(basename "$skill_dir")

        if [ -f "${skill_dir}SKILL.md" ]; then
            pass "Skill $skill_name: has SKILL.md"

            # Check frontmatter
            if head -5 "${skill_dir}SKILL.md" | grep -q "^---" 2>/dev/null; then
                has_name=$(grep -c "^name:" "${skill_dir}SKILL.md" 2>/dev/null || echo "0")
                has_desc=$(grep -c "^description:" "${skill_dir}SKILL.md" 2>/dev/null || echo "0")
                if [ "$has_name" -gt 0 ] && [ "$has_desc" -gt 0 ]; then
                    pass "Skill $skill_name: frontmatter valid"
                else
                    fail "Skill $skill_name: missing name or description in frontmatter"
                fi
            else
                fail "Skill $skill_name: missing YAML frontmatter"
            fi
            ((skill_count++))
        else
            fail "Skill $skill_name: missing SKILL.md"
        fi
    done
    pass "Found $skill_count skill(s)"
else
    warn "No .claude/skills/ directory found"
fi

# ============================================================================
# MCP Configuration Validation
# ============================================================================

section "Checking MCP Configuration"

if [ -f ".mcp.json" ]; then
    pass "Exists: .mcp.json"

    if command -v jq &>/dev/null; then
        if jq empty .mcp.json 2>/dev/null; then
            pass ".mcp.json: valid JSON"

            # Check for expected servers
            for server in context7 sequential-thinking; do
                if jq -e ".mcpServers[\"$server\"]" .mcp.json &>/dev/null; then
                    pass ".mcp.json: has $server server"
                else
                    warn ".mcp.json: missing $server server"
                fi
            done
        else
            fail ".mcp.json: invalid JSON"
        fi
    else
        warn "jq not installed, skipping MCP JSON validation"
    fi
else
    warn "No .mcp.json found (optional)"
fi

# ============================================================================
# Slash Commands Validation
# ============================================================================

section "Checking Slash Commands"

if [ -d ".claude/commands" ]; then
    cmd_count=0
    for cmd_file in .claude/commands/*.md; do
        [ -f "$cmd_file" ] || continue
        cmd_name=$(basename "$cmd_file" .md)

        # Skip README
        [ "$cmd_name" = "README" ] && continue

        if head -5 "$cmd_file" | grep -q "^---" 2>/dev/null; then
            pass "Command $cmd_name: has frontmatter"
        else
            fail "Command $cmd_name: missing YAML frontmatter"
        fi
        ((cmd_count++))
    done
    pass "Found $cmd_count command(s)"
else
    warn "No .claude/commands/ directory found"
fi

# ============================================================================
# Agent Templates Cross-Reference
# ============================================================================

section "Cross-referencing agent-templates.json"

if [ -f ".claude/lib/agent-templates.json" ] && command -v jq &>/dev/null; then
    template_agents=$(jq -r '.agents[].name // .templates[].name // empty' .claude/lib/agent-templates.json 2>/dev/null || echo "")
    if [ -n "$template_agents" ]; then
        while IFS= read -r tname; do
            if [ -f ".claude/agents/${tname}.md" ]; then
                pass "Template '$tname' matches agent file"
            else
                warn "Template '$tname' has no matching agent file"
            fi
        done <<< "$template_agents"
    else
        pass "agent-templates.json: no agent name refs to cross-check (structure varies)"
    fi
else
    [ -f ".claude/lib/agent-templates.json" ] || fail "agent-templates.json not found"
    command -v jq &>/dev/null || warn "jq not installed, skipping cross-reference"
fi

# ============================================================================
# Rules Directory Validation
# ============================================================================

section "Checking Rules"

if [ -d ".claude/rules" ]; then
    rule_count=0
    for rule_file in .claude/rules/*.md; do
        [ -f "$rule_file" ] || continue
        rule_name=$(basename "$rule_file" .md)
        pass "Rule: $rule_name"
        ((rule_count++))
    done
    pass "Found $rule_count rule(s)"
else
    warn "No .claude/rules/ directory found"
fi

# ============================================================================
# Summary
# ============================================================================

echo ""
echo -e "${BOLD}=== Validation Summary ===${NC}"
echo "  Checks: $CHECKS"
echo -e "  Passed: ${GREEN}$((CHECKS - ERRORS - WARNINGS))${NC}"
echo -e "  Warnings: ${YELLOW}$WARNINGS${NC}"
echo -e "  Errors: ${RED}$ERRORS${NC}"

if [ $ERRORS -eq 0 ]; then
    echo -e "\n${GREEN}${BOLD}All validations passed!${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Validation failed with $ERRORS error(s).${NC}"
    exit 1
fi
