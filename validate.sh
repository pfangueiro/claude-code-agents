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

    # Existence guard: a full DELETE of settings.json (vs an emptied {} wipe) must
    # be an ERROR, not a silent skip — every hook/statusLine/env check below is
    # gated on the file existing, so without this a deleted file yields 0 errors
    # and the watchdog never heals it. Fail -> errors>0 -> watchdog runs install --update.
    if [ ! -f "$HOME/.claude/settings.json" ]; then
        fail "Structural: ~/.claude/settings.json is MISSING (deleted) — self-heal must recreate it"
    fi

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

    # Regression guard: statusline.sh must keep the framework-status segment (reads
    # .framework-version + derives health from the framework-health.jsonl diagnostic
    # stream). Catches a reconcile/overwrite that silently drops the "gear<version> glyph".
    if [ -f "global-config/statusline.sh" ]; then
        if grep -q '\.framework-version' global-config/statusline.sh \
           && grep -q 'framework-health\.jsonl' global-config/statusline.sh; then
            pass "Structural: statusline.sh has the framework-status segment"
        else
            fail "Structural: statusline.sh MISSING the framework-status segment"
        fi
        # Deploy check: the LIVE status bar runs ~/.claude/statusline.sh, so a skipped or
        # failed deploy would drop the segment from the actual bar even though source has it.
        # Assert deployed == source (auto-heals via install --update; mirrors analytics-drift).
        if [ -f "$HOME/.claude/statusline.sh" ]; then
            if diff -q global-config/statusline.sh "$HOME/.claude/statusline.sh" >/dev/null 2>&1; then
                pass "Structural: deployed ~/.claude/statusline.sh matches source"
            else
                fail "Structural: deployed ~/.claude/statusline.sh differs from source (re-run install.sh)"
            fi
        fi
    fi

    # Regression guard: install.sh must implement AND advertise the --upgrade mode (the
    # one-command old→new migration path). Catches an accidental removal of the case arm or help.
    if [ -f "install.sh" ]; then
        if grep -qE '^[[:space:]]*--upgrade\)' install.sh && grep -qE 'echo "  --upgrade' install.sh; then
            pass "Structural: install.sh implements + advertises the --upgrade mode"
        else
            fail "Structural: install.sh missing the --upgrade mode or its --help entry"
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

        # Reverse guard: a hook EVENT the template DROPPED but still bound in
        # ~/.claude/settings.json to a framework hook script is a stale double-bind
        # (e.g. `Stop -> session-end.sh` after session-end.sh moved to SessionEnd — it then
        # double-fires every turn, over-logging). The forward check above only asserts
        # template events match; it cannot see an EXTRA event. sync_hooks must prune these.
        local stale_events=0 uevent ucmd ubase
        for uevent in $(jq -r '.hooks | keys[]' "$HOME/.claude/settings.json" 2>/dev/null); do
            printf '%s\n' "$tmpl_events" | grep -qx "$uevent" && continue
            while IFS= read -r ucmd; do
                [ -n "$ucmd" ] || continue
                ubase=$(basename "$ucmd")
                if [ -f "global-config/hooks/$ubase" ]; then
                    fail "Structural: stale hook event '$uevent' still runs framework hook $ubase (template dropped it; sync_hooks event-prune failed)"
                    stale_events=$((stale_events + 1))
                fi
            done < <(jq -r ".hooks[\"$uevent\"][]?.hooks[]?.command // empty" "$HOME/.claude/settings.json" 2>/dev/null)
        done
        [ "$stale_events" -eq 0 ] && pass "Structural: no stale framework hook event bindings (no double-bind)"

        # statusLine drift: a CLI settings-sync wipe can drop .statusLine (kills the
        # status bar) without touching hooks. Framework-owned → must match template.
        local tmpl_sl usr_sl
        tmpl_sl=$(jq -Sc '.statusLine' global-config/settings.json.template 2>/dev/null)
        usr_sl=$(jq -Sc '.statusLine // null' "$HOME/.claude/settings.json" 2>/dev/null)
        if [ "$tmpl_sl" != "null" ] && [ "$tmpl_sl" != "$usr_sl" ]; then
            fail "Structural: ~/.claude/settings.json .statusLine drifted/missing from template (status bar gone)"
        else
            pass "Structural: ~/.claude/settings.json .statusLine matches template"
        fi

        # Attribution invariant: the maintainer's standing rule is no AI co-author
        # trailer (see CLAUDE.md Git conventions), so the template must not ship a
        # commit attribution string. Removes the human obligation to keep the two surfaces in sync.
        local tmpl_ac
        tmpl_ac=$(jq -r '.attribution.commit // ""' global-config/settings.json.template 2>/dev/null)
        if [ -z "$tmpl_ac" ]; then
            pass "Structural: settings.json.template attribution.commit empty (no AI co-author trailer)"
        else
            fail "Structural: settings.json.template attribution.commit non-empty — contradicts the no-AI-trailer rule"
        fi
    fi

    # Warn if watchdog daemon not loaded (macOS only).
    # Use `launchctl print` (direct query by domain/label) instead of `launchctl list | grep`:
    # the grep-parse variant can race a concurrent install_watchdog invocation and false-positive.
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

        # Value check: CLAUDE_CODE_EFFORT_LEVEL must be a valid PERSISTENT tier.
        # max/ultracode are session-only (/effort ...) and invalid as env values —
        # silently ineffective if set here, so catch them rather than just presence.
        eff=$(jq -r '.env.CLAUDE_CODE_EFFORT_LEVEL // empty' "$SETTINGS_DST" 2>/dev/null)
        if [ -n "$eff" ]; then
            case "$eff" in
                low|medium|high|xhigh) pass "Quick: CLAUDE_CODE_EFFORT_LEVEL valid ($eff)" ;;
                *) fail "Quick: CLAUDE_CODE_EFFORT_LEVEL invalid ('$eff') — persistent tiers are low|medium|high|xhigh (max/ultracode are session-only)" ;;
            esac
        fi
    fi

    # Shared-set sync: the framework's agents/skills/commands/rules/lib must be
    # present + identical at ~/.claude (install --update reconciles them). Lives in
    # --quick so the watchdog heals shared-set drift, alongside the SessionStart Check 7.
    ss_ok=true
    _ss_cmp() {
        local src="$1" dst="$HOME/.claude/${1#.claude/}"
        if [ ! -f "$dst" ]; then fail "Quick: shared-set missing: ${1#.claude/}"; ss_ok=false
        elif ! diff -q "$src" "$dst" >/dev/null 2>&1; then fail "Quick: shared-set drift: ${1#.claude/}"; ss_ok=false; fi
    }
    if [ -d "$HOME/.claude/agents" ]; then
        while IFS= read -r f; do _ss_cmp "$f"; done < <(
            { [ -d .claude/agents ]   && find .claude/agents -type f -name '*.md' ! -name '._*'
              [ -d .claude/rules ]    && find .claude/rules -type f -name '*.md' ! -name '._*'
              [ -d .claude/commands ] && find .claude/commands -type f -name '*.md' ! -name '._*'
              [ -d .claude/lib ]      && find .claude/lib -type f ! -name '._*'
              [ -d .claude/skills ]   && find .claude/skills -type f -path '.claude/skills/*/*' ! -name '._*'; } 2>/dev/null )
        [ "$ss_ok" = true ] && pass "Quick: shared set synced to ~/.claude (agents/skills/commands/rules/lib)"
    else
        fail "Quick: framework not installed user-global (~/.claude/agents missing) — run ./install.sh"
    fi

    # Memory backup freshness — the watchdog's automated path runs ONLY --quick,
    # so this runtime detector must live here to reconcile automatically.
    check_memory_freshness "Quick: "

    # Live-settings attribution: the template check (structural, above) only guards the
    # SOURCE. The .attribution reconcile writes the user's LIVE ~/.claude/settings.json, so
    # assert the deployed commit trailer is empty here too — otherwise a failed/absent heal
    # (or a settings-sync payload re-introducing a Co-Authored-By trailer) is invisible to the
    # watchdog's --quick path and to --upgrade's self-verify.
    if [ -f "$HOME/.claude/settings.json" ] && command -v jq &>/dev/null; then
        live_attr_commit=$(jq -r '.attribution.commit // ""' "$HOME/.claude/settings.json" 2>/dev/null)
        if [ -z "$live_attr_commit" ]; then
            pass "Quick: live settings.json attribution.commit empty (no AI co-author trailer)"
        else
            fail "Quick: live settings.json carries an AI-attribution commit trailer — run ./install.sh --update"
        fi
    fi

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
# Currency Lints — guard regressions surfaced by the sub-agents/docs eval
# ============================================================================

section "Checking agent tool-allowlist currency (body-referenced tools in tools:)"

# Any agent whose BODY instructs an LSP call must grant LSP in its tools: allowlist,
# or the call fails at runtime (tools: is a strict allowlist).
for agent_file in .claude/agents/*.md; do
    aname=$(basename "$agent_file" .md)
    if grep -vE '^tools:' "$agent_file" | grep -qE '\bLSP\b'; then
        if grep -m1 -iE '^tools:' "$agent_file" | grep -qE '\bLSP\b'; then
            pass "$aname: body uses LSP and tools: grants it"
        else
            fail "$aname: body instructs LSP but tools: omits it (call would fail at runtime)"
        fi
    fi
done

section "Checking meta-agent has no inert routing scaffolding"

# The agent factory must not mint dead confidence/keyword-weight metadata into
# generated agents — Claude Code routes on description text only (cf. 0b343bb).
if grep -qE 'weight: [0-9]\.[0-9]|\*\*Primary Keywords\*\*|\*\*Secondary Keywords\*\*|\*\*Confidence Threshold\*\*|Confidence threshold: Set' .claude/agents/meta-agent.md 2>/dev/null; then
    fail "meta-agent: contains inert confidence/keyword-weight scaffolding (routes on description text only; see 0b343bb)"
else
    pass "meta-agent: no inert confidence/keyword scaffolding"
fi

section "Checking for inert (consumer-less) scoring config in lib JSON"

# Claude Code routes on description text only — the framework has NO scoring / keyword-weight /
# confidence runtime (0b343bb removed the dead activation-keywords router). So these structured-
# config keys are ALWAYS dead if present in .claude/lib/*.json. Scope is STRUCTURED CONFIG ONLY —
# never skill/rule markdown, which legitimately uses "threshold"/"score"/"weight" in prose.
inert_scoring_hits=0
for _key in confidence_threshold keyword_weights activation_rules priority_override; do
    _hit=$(grep -lE "\"${_key}\"" .claude/lib/*.json 2>/dev/null || true)
    if [ -n "$_hit" ]; then
        fail "Inert config: \"${_key}\" present in $(echo "$_hit" | tr '\n' ' ')— dead scoring metadata, no runtime consumer (routes on description text only; see 0b343bb)"
        inert_scoring_hits=$((inert_scoring_hits + 1))
    fi
done
if [ "$inert_scoring_hits" -eq 0 ]; then
    pass "No inert scoring config (confidence/keyword-weight/priority-override) in lib JSON"
fi

section "Checking /execute Phase 5 independent verifier"

# Phase 5 must gate REPORT on an independent verifier, not self-grade.
if grep -qEi 'independent acceptance check|independent verifier' .claude/skills/execute/SKILL.md 2>/dev/null; then
    pass "/execute Phase 5: independent verifier gate present"
else
    fail "/execute Phase 5: missing independent verifier gate (self-grading regression)"
fi

# ============================================================================
# Library File Validation
# ============================================================================

EXPECTED_LIBS=(
    "agent-templates.json"
    "sdlc-patterns.md"
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
    for event in Notification PreToolUse PostToolUse SessionStart SubagentStart SubagentStop SessionEnd PermissionRequest PreCompact PostCompact; do
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
        for table in sessions api_calls agent_activations skill_activations tool_usage ingestion_state hook_events; do
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
