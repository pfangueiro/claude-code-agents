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

set -uo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# ---- Flag parsing ----
QUIET=""
QUICK_MODE=false
JSON_MODE=false
HEAL_MODE=false
for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET="--quiet" ;;
        --quick) QUICK_MODE=true ;;
        --json)  JSON_MODE=true; QUIET="--quiet" ;;
        --heal)  HEAL_MODE=true ;;
    esac
done

ERRORS=0
WARNINGS=0
CHECKS=0
JSON_EVENTS=()

_json_push() {
    # $1 level (pass/fail/warn), $2 message
    local safe
    safe=$(printf '%s' "$2" | sed 's/\\/\\\\/g; s/"/\\"/g')
    JSON_EVENTS+=("{\"level\":\"$1\",\"msg\":\"$safe\"}")
}

pass() {
    ((CHECKS++)) || true
    $JSON_MODE && _json_push pass "$1"
    [ "$QUIET" = "--quiet" ] || echo -e "  ${GREEN}PASS${NC} $1"
}

fail() {
    ((CHECKS++)) || true
    ((ERRORS++)) || true
    $JSON_MODE && _json_push fail "$1"
    $JSON_MODE || echo -e "  ${RED}FAIL${NC} $1"
}

warn() {
    ((CHECKS++)) || true
    ((WARNINGS++)) || true
    $JSON_MODE && _json_push warn "$1"
    $JSON_MODE || [ "$QUIET" = "--quiet" ] || echo -e "  ${YELLOW}WARN${NC} $1"
}

section() {
    $JSON_MODE && return 0
    [ "$QUIET" = "--quiet" ] || echo -e "\n${BOLD}$1${NC}"
}

# ============================================================================
# Structural Checks (always-on, regardless of mode)
# ============================================================================

run_structural_checks() {
    section "Structural Checks"

    # Regression guard: SessionStart hook in TEMPLATE must NOT be a decorative echo
    if [ -f "global-config/settings.json.template" ] && command -v jq &>/dev/null; then
        local sess_cmd
        sess_cmd=$(jq -r '.hooks.SessionStart[0].hooks[0].command // ""' global-config/settings.json.template 2>/dev/null)
        if [[ "$sess_cmd" =~ ^[[:space:]]*echo ]]; then
            fail "Structural: SessionStart hook in TEMPLATE is decorative (echo only)"
        else
            pass "Structural: SessionStart hook in template is non-decorative"
        fi
    fi

    # Hook-drift check: every event in template must match user's ~/.claude/settings.json.
    # This catches the "sync_hooks add-if-missing" bug class: hook installed on disk but
    # not wired into settings.json because an older entry already existed.
    if [ -f "global-config/settings.json.template" ] && [ -f "$HOME/.claude/settings.json" ] \
       && command -v jq &>/dev/null; then
        local drift_count=0
        local tmpl_events
        tmpl_events=$(jq -r '.hooks | keys[]' global-config/settings.json.template 2>/dev/null)
        for event in $tmpl_events; do
            local tmpl_cfg usr_cfg
            tmpl_cfg=$(jq -Sc ".hooks[\"$event\"]" global-config/settings.json.template 2>/dev/null)
            usr_cfg=$(jq -Sc ".hooks[\"$event\"] // null" "$HOME/.claude/settings.json" 2>/dev/null)
            if [ "$tmpl_cfg" != "$usr_cfg" ]; then
                fail "Structural: hook event '$event' in ~/.claude/settings.json drifted from template"
                drift_count=$((drift_count + 1))
            fi
        done
        if [ "$drift_count" -eq 0 ]; then
            pass "Structural: ~/.claude/settings.json hook events match template"
        fi
    fi

    # Warn if watchdog daemon not loaded (macOS only).
    # Use `launchctl print` (direct query by domain/label) instead of `launchctl list | grep`:
    # the grep-parse variant races against concurrent install_watchdog invocations
    # during deploy-all (88 × launchctl bootstrap) and false-positives.
    if [[ "$(uname -s)" == "Darwin" ]]; then
        if launchctl print "gui/$(id -u)/com.claude-code-agents.framework-watchdog" >/dev/null 2>&1; then
            pass "Structural: claude-framework-watchdog daemon loaded"
        else
            warn "Structural: claude-framework-watchdog daemon not loaded"
        fi
    fi

    # Warn if no snapshot newer than 48h
    local snap_dir="$HOME/.claude/snapshots"
    if [ -d "$snap_dir" ]; then
        local fresh=0
        if command -v find >/dev/null 2>&1; then
            if find "$snap_dir" -maxdepth 1 -type f \( -name '*.bundle' -o -name '*.tgz' \) -mtime -2 2>/dev/null | grep -q .; then
                fresh=1
            fi
        fi
        if [ "$fresh" -eq 1 ]; then
            pass "Structural: snapshot newer than 48h exists"
        else
            warn "Structural: no snapshot newer than 48h in $snap_dir"
        fi
    else
        warn "Structural: no $snap_dir directory"
    fi
}

run_structural_checks

# ============================================================================
# Quick Mode: integrity of ~/.claude/ only (hooks + analytics + env keys)
# ============================================================================

emit_and_exit() {
    if $JSON_MODE; then
        local joined=""
        local sep=""
        for ev in "${JSON_EVENTS[@]}"; do
            joined+="${sep}${ev}"
            sep=","
        done
        printf '{"checks":%d,"errors":%d,"warnings":%d,"events":[%s]}\n' \
            "$CHECKS" "$ERRORS" "$WARNINGS" "$joined"
    else
        echo ""
        echo -e "${BOLD}=== Validation Summary ===${NC}"
        echo "  Checks: $CHECKS"
        echo -e "  Passed: ${GREEN}$((CHECKS - ERRORS - WARNINGS))${NC}"
        echo -e "  Warnings: ${YELLOW}$WARNINGS${NC}"
        echo -e "  Errors: ${RED}$ERRORS${NC}"
    fi

    # Heal mode: on drift, invoke install.sh --update (never exit non-zero)
    if $HEAL_MODE && [ "$ERRORS" -gt 0 ]; then
        if [ -x "./install.sh" ]; then
            ./install.sh --update >/dev/null 2>&1 || \
                $JSON_MODE || echo -e "${YELLOW}heal: install.sh --update failed (logged)${NC}"
        fi
        # Heal mode never exits non-zero
        exit 0
    fi

    if [ "$ERRORS" -eq 0 ]; then
        exit 0
    else
        exit 1
    fi
}

# Runtime memory-snapshot freshness. Shared by quick AND full mode so the
# watchdog's automated `--quick --json` run actually reconciles this critical
# state (framework-integrity.md: not by manual validate.sh runs). Only meaningful
# where memory dirs exist; absent snapshot on a fresh install is a warn, not a
# fail — the daily job has simply not run yet.
check_memory_freshness() {
    local prefix="$1"   # "" for full, "Quick: " for quick
    local mem_dir_count=0 d
    if [ -d "$HOME/.claude/projects" ]; then
        for d in "$HOME"/.claude/projects/*/memory; do
            [ -d "$d" ] && mem_dir_count=$((mem_dir_count + 1))
        done
    fi
    [ "$mem_dir_count" -gt 0 ] || return 0
    local latest_mem_snap
    latest_mem_snap=$(ls -1t "$HOME"/.claude/snapshots/memory-*.tgz 2>/dev/null | grep -v 'memory-latest\.tgz$' | head -1 || true)
    if [ -n "$latest_mem_snap" ] && [ -f "$latest_mem_snap" ]; then
        local snap_age_days
        snap_age_days=$(( ( $(date +%s) - $(stat -f %m "$latest_mem_snap" 2>/dev/null || stat -c %Y "$latest_mem_snap" 2>/dev/null || echo 0) ) / 86400 ))
        if [ "$snap_age_days" -le 8 ]; then
            pass "${prefix}Memory snapshot present and fresh (${snap_age_days}d old, $mem_dir_count memory dirs)"
        else
            warn "${prefix}Memory snapshot stale (${snap_age_days}d old) — watchdog may not be running"
        fi
    else
        warn "${prefix}No memory snapshot yet ($mem_dir_count memory dirs present) — watchdog daily job pending"
    fi
}

if $QUICK_MODE; then
    section "Quick Mode: ~/.claude integrity"

    # Hooks check
    HOOKS_SRC="global-config/hooks"
    HOOKS_DST="$HOME/.claude/hooks"
    if [ -d "$HOOKS_SRC" ] && [ -d "$HOOKS_DST" ]; then
        for src in "$HOOKS_SRC"/*.sh; do
            [ -f "$src" ] || continue
            name=$(basename "$src")
            dst="$HOOKS_DST/$name"
            if [ ! -f "$dst" ]; then
                fail "Quick: hook not deployed: $name"
            elif diff -q "$src" "$dst" >/dev/null 2>&1; then
                pass "Quick: hook synced: $name"
            else
                fail "Quick: hook drift: $name"
            fi
        done
    else
        warn "Quick: hooks directories missing"
    fi

    # Analytics check
    for f in collector.py server.py dashboard.html schema.sql; do
        src="observability/$f"
        dst="$HOME/.claude/analytics/$f"
        if [ -f "$src" ] && [ -f "$dst" ]; then
            if diff -q "$src" "$dst" >/dev/null 2>&1; then
                pass "Quick: analytics synced: $f"
            else
                fail "Quick: analytics drift: $f"
            fi
        elif [ -f "$src" ]; then
            fail "Quick: analytics not deployed: $f"
        fi
    done

    # settings.json env keys
    SETTINGS_DST="$HOME/.claude/settings.json"
    TEMPLATE_SRC="global-config/settings.json.template"
    if [ -f "$SETTINGS_DST" ] && [ -f "$TEMPLATE_SRC" ] && command -v jq &>/dev/null; then
        while IFS= read -r k; do
            [ -z "$k" ] && continue
            if jq -e --arg k "$k" '.env[$k]' "$SETTINGS_DST" >/dev/null 2>&1; then
                pass "Quick: env key present: $k"
            else
                fail "Quick: env key missing: $k"
            fi
        done < <(jq -r '.env | keys[]' "$TEMPLATE_SRC" 2>/dev/null)
    fi

    # Memory backup freshness — the watchdog's automated path runs ONLY --quick,
    # so this runtime detector must live here to reconcile automatically.
    check_memory_freshness "Quick: "

    emit_and_exit
fi

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
    "sre-specialist"
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
# De-Anchoring Invariant (divergence capability)
# ============================================================================

DEANCHOR_AGENTS=(
    "architecture-planner"
    "database-architect"
    "devops-automation"
    "frontend-specialist"
    "performance-optimizer"
    "sre-specialist"
    "meta-agent"
)

section "Checking De-Anchoring Step (${#DEANCHOR_AGENTS[@]} open-ended agents)"

for agent in "${DEANCHOR_AGENTS[@]}"; do
    agent_file=".claude/agents/${agent}.md"
    [ -f "$agent_file" ] || continue
    if grep -q "De-Anchor Before Deciding" "$agent_file" 2>/dev/null; then
        pass "$agent: has de-anchoring step"
    else
        fail "$agent: missing de-anchoring step (De-Anchor Before Deciding)"
    fi
done

GATED_SKILLS=(
    "diverge"
    "execute"
    "investigate"
    "deep-analysis"
)

section "Checking Pre-Flight Gates (${#GATED_SKILLS[@]} expensive skills)"

for gated_skill in "${GATED_SKILLS[@]}"; do
    gated_file=".claude/skills/${gated_skill}/SKILL.md"
    [ -f "$gated_file" ] || continue
    if grep -q "Pre-Flight Gate" "$gated_file" 2>/dev/null; then
        pass "$gated_skill: has pre-flight gate"
    else
        fail "$gated_skill: missing pre-flight gate (Pre-Flight Gate)"
    fi
done

# ============================================================================
# Spawner Skills Must Not Be Forked (forked subagents cannot use the Agent tool)
# ============================================================================

SPAWNER_SKILLS=(
    "diverge"
    "execute"
)

section "Checking Spawner Skills Are Not Forked (${#SPAWNER_SKILLS[@]})"

for spawner in "${SPAWNER_SKILLS[@]}"; do
    spawner_file=".claude/skills/${spawner}/SKILL.md"
    [ -f "$spawner_file" ] || continue
    if grep -q "^context: fork" "$spawner_file" 2>/dev/null; then
        fail "$spawner: must NOT declare 'context: fork' — forked subagents cannot spawn the parallel sub-agents this skill needs"
    else
        pass "$spawner: not forked (can spawn parallel sub-agents)"
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
    "mcp-guide.md"
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
# Hooks Validation
# ============================================================================

EXPECTED_HOOKS=(
    "file-protection.sh"
    "post-edit-lint.sh"
    "notify.sh"
    "agent-tracker.sh"
    "session-end.sh"
    "session-start-healthcheck.sh"
    "smart-guard.sh"
    "pre-compact.sh"
    "post-compact.sh"
)

EXPECTED_HOOK_CONFIGS=(
    "smart-file-guard.json"
    "pre-commit-review.json"
)

section "Checking Hooks (${#EXPECTED_HOOKS[@]} scripts + ${#EXPECTED_HOOK_CONFIGS[@]} configs)"

if [ -d "global-config/hooks" ]; then
    for hook in "${EXPECTED_HOOKS[@]}"; do
        if [ -f "global-config/hooks/$hook" ]; then
            pass "Hook script: $hook"
            if head -1 "global-config/hooks/$hook" | grep -qE "^#!.*\b(bash|sh)$" 2>/dev/null; then
                pass "Hook $hook: has shebang"
            else
                fail "Hook $hook: missing bash/sh shebang"
            fi
        else
            fail "Missing hook script: global-config/hooks/$hook"
        fi
    done

    for cfg in "${EXPECTED_HOOK_CONFIGS[@]}"; do
        if [ -f "global-config/hooks/$cfg" ]; then
            pass "Hook config: $cfg"
            if command -v jq &>/dev/null; then
                if jq empty "global-config/hooks/$cfg" 2>/dev/null; then
                    pass "Hook config $cfg: valid JSON"
                else
                    fail "Hook config $cfg: invalid JSON"
                fi
            fi
        else
            fail "Missing hook config: global-config/hooks/$cfg"
        fi
    done
else
    warn "No global-config/hooks/ directory found"
fi

# Validate settings.json.template has expected hook events
if [ -f "global-config/settings.json.template" ]; then
    for event in Notification PreToolUse PostToolUse SessionStart SubagentStart SubagentStop Stop PermissionRequest PreCompact PostCompact; do
        if grep -q "\"$event\"" "global-config/settings.json.template" 2>/dev/null; then
            pass "settings.json.template: has $event hook event"
        else
            fail "settings.json.template: missing $event hook event"
        fi
    done
else
    fail "Missing global-config/settings.json.template"
fi

# ============================================================================
# Analytics / Observability Validation
# ============================================================================

section "Checking Analytics (Observability)"

if [ -d "observability" ]; then
    for analytics_file in collector.py server.py dashboard.html schema.sql; do
        if [ -f "observability/${analytics_file}" ]; then
            pass "Analytics: $analytics_file exists"
        else
            fail "Analytics: missing observability/${analytics_file}"
        fi
    done

    # Validate schema.sql has expected tables
    if [ -f "observability/schema.sql" ]; then
        for table in sessions api_calls agent_activations tool_usage ingestion_state hook_events; do
            if grep -q "CREATE TABLE.*${table}" "observability/schema.sql" 2>/dev/null; then
                pass "schema.sql: has $table table"
            else
                fail "schema.sql: missing $table table"
            fi
        done
    fi
else
    warn "No observability/ directory found (optional)"
fi

# ============================================================================
# Deployment Integrity (md5 manifest — ALL projects; 5 sampled in --quick)
# ============================================================================
# Verifies every install-deployed source file is PRESENT and md5-IDENTICAL in
# each project. Detects BOTH content drift AND missing files — a file absent
# from a project is a deploy gap the old sampled diff-check silently ignored
# (its per-file check was guarded by `[ -f "$dst" ]` with no else branch).

section "Checking Deployment Integrity ($([ "$QUICK_MODE" = true ] && echo 'md5 manifest, sample 5' || echo 'md5 manifest, all projects'))"

PROJECTS_DIR="$HOME/local-codebase"

_md5of() { md5 -q "$1" 2>/dev/null || md5sum "$1" 2>/dev/null | cut -d' ' -f1; }

# Canonical deployable set (mirrors install.sh selection): agents/*.md, lib/*,
# rules/*.md, skills/<name>/** subdir contents, commands/*.md. Emits
# "relpath<TAB>md5", LC_ALL=C-sorted so two manifests are comm-comparable.
_gen_manifest() {
    local root="$1"
    [ -d "$root" ] || return 0
    (
        cd "$root" || return 0
        {
            [ -d agents ]   && find agents -type f -name '*.md' ! -name '._*'
            [ -d lib ]      && find lib -type f ! -name '._*'
            [ -d rules ]    && find rules -type f -name '*.md' ! -name '._*'
            [ -d skills ]   && find skills -type f -path 'skills/*/*' ! -name '._*'
            [ -d commands ] && find commands -type f -name '*.md' ! -name '._*'
        } 2>/dev/null | while IFS= read -r f; do
            printf '%s\t%s\n' "$f" "$(_md5of "$f")"
        done
    ) | LC_ALL=C sort
}

if [ -d "$PROJECTS_DIR" ]; then
    src_manifest=$(mktemp)
    proj_manifest=$(mktemp)
    _gen_manifest ".claude" > "$src_manifest"
    src_file_count=$(grep -c . "$src_manifest" 2>/dev/null || echo 0)

    all_projects=()
    for d in "$PROJECTS_DIR"/*/; do
        bn=$(basename "$d")
        [ "$bn" = "claude-code-agents" ] && continue
        [ "$bn" = "claude-code" ] && continue
        [ -d "$d/.claude/agents" ] || continue
        all_projects+=("$d")
    done

    # Full run checks ALL projects; --quick samples up to 5 (watchdog speed).
    target_projects=()
    if [ "$QUICK_MODE" = true ]; then
        sc=${#all_projects[@]}
        cc=$((sc < 5 ? sc : 5))
        st=$((sc / (cc > 0 ? cc : 1))); [ "$st" -eq 0 ] && st=1
        for ((i=0; i<sc && ${#target_projects[@]}<cc; i+=st)); do
            target_projects+=("${all_projects[$i]}")
        done
    else
        target_projects=("${all_projects[@]}")
    fi

    for proj in "${target_projects[@]}"; do
        pname=$(basename "$proj")
        _gen_manifest "$proj/.claude" > "$proj_manifest"
        gaps=0
        # comm -23 yields source lines not present verbatim in the project =
        # either a missing file or an md5 mismatch; classify by relpath presence.
        while IFS=$'\t' read -r rel shash; do
            [ -z "$rel" ] && continue
            if cut -f1 "$proj_manifest" | grep -qxF "$rel"; then
                fail "Deploy drift (md5): $pname/$rel"
            else
                fail "Deploy gap (missing): $pname/$rel"
            fi
            gaps=$((gaps + 1))
        done < <(comm -23 "$src_manifest" "$proj_manifest")
        [ "$gaps" -eq 0 ] && pass "Deployment $pname: $src_file_count files present + md5-identical"
    done
    rm -f "$src_manifest" "$proj_manifest"
else
    warn "No ~/local-codebase directory found — skipping deployment checks"
fi

# ============================================================================
# Global Hooks Integrity
# ============================================================================

section "Checking Global Hooks Sync"

if [ -d "$HOME/.claude/hooks" ]; then
    for hook in "${EXPECTED_HOOKS[@]}"; do
        src="global-config/hooks/$hook"
        dst="$HOME/.claude/hooks/$hook"
        if [ -f "$src" ] && [ -f "$dst" ]; then
            if diff -q "$src" "$dst" >/dev/null 2>&1; then
                pass "Hook synced: $hook"
            else
                fail "Hook drift: $hook (deployed differs from source)"
            fi
        elif [ -f "$src" ] && [ ! -f "$dst" ]; then
            fail "Hook not deployed: $hook"
        fi
    done
else
    warn "No ~/.claude/hooks/ directory — skipping hook sync checks"
fi

# ============================================================================
# Analytics Integrity
# ============================================================================

section "Checking Analytics Sync"

if [ -d "$HOME/.claude/analytics" ]; then
    for f in collector.py server.py dashboard.html schema.sql; do
        src="observability/$f"
        dst="$HOME/.claude/analytics/$f"
        if [ -f "$src" ] && [ -f "$dst" ]; then
            if diff -q "$src" "$dst" >/dev/null 2>&1; then
                pass "Analytics synced: $f"
            else
                fail "Analytics drift: $f (deployed differs from source)"
            fi
        elif [ -f "$src" ] && [ ! -f "$dst" ]; then
            fail "Analytics not deployed: $f"
        fi
    done
else
    warn "No ~/.claude/analytics/ directory — skipping analytics checks"
fi

# ============================================================================
# Memory Backup Coverage
# ============================================================================
# framework-integrity.md: "every critical directory must have a snapshot with a
# documented restore path." Persistent memory (~/.claude/projects/*/memory) is
# critical state; assert the watchdog carries the backup logic, and that a fresh
# snapshot exists when memory is present.

section "Checking Memory Backup Coverage"

WATCHDOG_SRC="global-config/daemon/claude-framework-watchdog.sh"
if [ -f "$WATCHDOG_SRC" ]; then
    if grep -q 'memory-\$(_day_stamp)\.tgz' "$WATCHDOG_SRC" && grep -q 'projects/\*/memory' "$WATCHDOG_SRC"; then
        pass "Watchdog source has project-memory backup logic"
    else
        fail "Watchdog source missing project-memory backup logic (Task 4b)"
    fi
    # Restore path must be documented (framework-integrity: no snapshot without restore)
    if grep -q 'memory-latest.tgz' CLAUDE.md 2>/dev/null; then
        pass "Memory restore path documented in CLAUDE.md"
    else
        fail "Memory restore path not documented in CLAUDE.md"
    fi
else
    warn "Watchdog source not found — skipping memory backup source check"
fi

# Runtime freshness (shared with quick mode via check_memory_freshness).
check_memory_freshness ""

# ============================================================================
# Summary
# ============================================================================

if $JSON_MODE; then
    emit_and_exit
fi

echo ""
echo -e "${BOLD}=== Validation Summary ===${NC}"
echo "  Checks: $CHECKS"
echo -e "  Passed: ${GREEN}$((CHECKS - ERRORS - WARNINGS))${NC}"
echo -e "  Warnings: ${YELLOW}$WARNINGS${NC}"
echo -e "  Errors: ${RED}$ERRORS${NC}"

if $HEAL_MODE && [ "$ERRORS" -gt 0 ]; then
    echo -e "\n${YELLOW}${BOLD}Heal mode: running install.sh --update...${NC}"
    if [ -x "./install.sh" ]; then
        ./install.sh --update >/dev/null 2>&1 || \
            echo -e "${YELLOW}heal: install.sh --update failed (logged)${NC}"
    fi
    # Heal mode never exits non-zero
    exit 0
fi

if [ $ERRORS -eq 0 ]; then
    echo -e "\n${GREEN}${BOLD}All validations passed!${NC}"
    exit 0
else
    echo -e "\n${RED}${BOLD}Validation failed with $ERRORS error(s).${NC}"
    exit 1
fi
