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
    #
    # ...but ONLY on a machine where the framework is actually installed. This check asserts a
    # property of the INSTALLED ENVIRONMENT, not of the repository, and on a CI runner or a fresh
    # clone "missing" means "never installed", not "deleted". Unconditional, it made `./validate.sh`
    # fail on every CI run: 20 of 20 red, no green run in over a month. A gate that can never PASS
    # is read exactly as often as one that can never FAIL — nobody looks at either — so this was the
    # process-level twin of the fail-open class the guards below exist to catch.
    # The install markers are the discriminator (install.sh writes .framework-version/.framework-path),
    # and the degrade-to-warn behaviour now matches the sibling ~/.claude/hooks and analytics checks.
    if [ -f "$HOME/.claude/.framework-version" ] || [ -d "$HOME/.claude/agents" ]; then
        if [ ! -f "$HOME/.claude/settings.json" ]; then
            fail "Structural: ~/.claude/settings.json is MISSING (deleted) — self-heal must recreate it"
        else
            pass "Structural: ~/.claude/settings.json exists"
        fi
    else
        warn "Framework not installed at ~/.claude — skipping installed-environment structural checks (CI or fresh clone)"
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

    # Version consistency: install.sh's SCRIPT_VERSION is the single source of truth, and it is
    # what lands in ~/.claude/.framework-version and therefore in the statusline glyph. A doc
    # claiming a different number is how a teammate ends up certain they are on a release they are
    # not on. Caught in practice: the framework ran a whole remediation effort at "3.1.1" while
    # 18 commits past that tag, with the README badge, EXTENSIBILITY.md and the marker all agreeing
    # on a number none of them had verified.
    # Gap-tested by mutation: bump SCRIPT_VERSION alone -> FAIL naming each stale doc; align -> PASS.
    if [ -f "install.sh" ]; then
        _sv=$(grep -m1 '^SCRIPT_VERSION=' install.sh | cut -d'"' -f2)
        if [ -z "$_sv" ]; then
            fail "Version: could not read SCRIPT_VERSION from install.sh"
        else
            _ver_stale=""
            if [ -f README.md ] && ! grep -q "badge/version-${_sv}-" README.md; then
                _ver_stale="$_ver_stale README.md"
            fi
            if [ -f EXTENSIBILITY.md ] && ! grep -q "^Version: ${_sv}$" EXTENSIBILITY.md; then
                _ver_stale="$_ver_stale EXTENSIBILITY.md"
            fi
            if [ -n "$_ver_stale" ]; then
                fail "Version: install.sh says $_sv but these disagree:$_ver_stale"
            else
                pass "Version: $_sv consistent across install.sh, README badge, EXTENSIBILITY.md"
            fi
        fi
    fi

    # The two reversibility flags a teammate needs before running an installer that writes into
    # their ~/.claude and loads a background daemon. Implemented AND advertised, same as --upgrade.
    if [ -f "install.sh" ]; then
        _rev_missing=""
        grep -qE '^[[:space:]]*--dry-run\|-n\)' install.sh   || _rev_missing="$_rev_missing --dry-run(arm)"
        grep -qE 'echo "  --dry-run'          install.sh     || _rev_missing="$_rev_missing --dry-run(help)"
        grep -qE '^[[:space:]]*--uninstall\)' install.sh     || _rev_missing="$_rev_missing --uninstall(arm)"
        grep -qE 'echo "  --uninstall'        install.sh     || _rev_missing="$_rev_missing --uninstall(help)"
        if [ -n "$_rev_missing" ]; then
            fail "Structural: install.sh missing reversibility mode(s):$_rev_missing"
        else
            pass "Structural: install.sh implements + advertises --dry-run and --uninstall"
        fi
    fi

    # EXECUTES --dry-run against a throwaway HOME and asserts two invariants that protect a
    # teammate's machine. Greps cannot establish either one:
    #   (a) it writes NOTHING — a "preview" that mutates is worse than no preview;
    #   (b) the owned-path enumeration never names user data. Uninstall removes exactly what this
    #       enumeration emits, so a single stray entry here is a command that deletes someone's
    #       session history, personal CLAUDE.md, or telemetry.
    # Gap-tested by mutation: emit "$HOME/.claude/settings.json" from _framework_owned_paths -> FAIL;
    # make cmd_dry_run touch a file -> FAIL; unmodified -> PASS.
    if [ -f "install.sh" ]; then
        _dr_home=$(mktemp -d 2>/dev/null)
        if [ -n "$_dr_home" ] && [ -d "$_dr_home" ]; then
            _dr_out=$(HOME="$_dr_home" bash install.sh --dry-run 2>&1)
            _dr_rc=$?
            _dr_wrote=$(find "$_dr_home" -mindepth 1 2>/dev/null | wc -l | tr -d ' ')
            # Any owned path naming user data is a deletion candidate that must never exist.
            _dr_bad=$(printf '%s\n' "$_dr_out" \
                | grep -oE '/(settings\.json|CLAUDE\.md)$|/(projects|todos|snapshots)/|\.jsonl$' \
                | sort -u | tr '\n' ' ')
            if [ "$_dr_rc" -ne 0 ]; then
                fail "install.sh --dry-run exited $_dr_rc"
            elif [ "$_dr_wrote" -ne 0 ]; then
                fail "install.sh --dry-run WROTE $_dr_wrote path(s) into a clean HOME — a preview must not mutate"
            elif [ -n "${_dr_bad// /}" ]; then
                fail "install.sh owned-path set names user data (uninstall would delete it): ${_dr_bad% }"
            else
                pass "install.sh --dry-run writes nothing and never claims ownership of user data"
            fi
            rm -rf "$_dr_home"
        else
            fail "install.sh --dry-run guard: could not create a temp HOME — invariant unverified"
        fi
    fi

    # Regression guard: the watchdog must cap the append-only diagnostic logs — otherwise
    # framework-health.jsonl grows unbounded (~50 lines/day). Assert the trim exists in source.
    if [ -f "global-config/daemon/claude-framework-watchdog.sh" ]; then
        if grep -q 'trim_jsonl' global-config/daemon/claude-framework-watchdog.sh; then
            pass "Structural: watchdog caps diagnostic logs (trim_jsonl)"
        else
            fail "Structural: watchdog missing diagnostic-log rotation (trim_jsonl) — framework-health.jsonl grows unbounded"
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
        # __pycache__ is PRUNED, not merely diffed. The skills ship runnable Python and the docs
        # tell you to run it, so a `.pyc` appears in the source tree the first time anyone follows
        # deployment-runbook or skill-creator. It is gitignored, so the working tree stays clean —
        # but this enumeration used to pick it up, report "shared-set missing", and hand the
        # watchdog a drift it can never heal (install.sh does not deploy bytecode). Following the
        # documentation must not put the framework into a permanent heal loop.
        while IFS= read -r f; do _ss_cmp "$f"; done < <(
            { [ -d .claude/agents ]   && find .claude/agents -type f -name '*.md' ! -name '._*'
              [ -d .claude/rules ]    && find .claude/rules -type f -name '*.md' ! -name '._*'
              [ -d .claude/commands ] && find .claude/commands -type f -name '*.md' ! -name '._*'
              [ -d .claude/lib ]      && find .claude/lib -type f ! -name '._*'
              [ -d .claude/skills ]   && find .claude/skills -name '__pycache__' -prune -o \
                                             -type f -path '.claude/skills/*/*' ! -name '._*' ! -name '*.pyc' -print; } 2>/dev/null )
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
# Documentation accuracy (FULL-ONLY — deliberately NOT in --quick)
# ============================================================================
# Count-drift catcher: the docs state component counts (agents/skills/hook-scripts/MCP) that
# silently rot when a component is added/removed and the prose isn't bumped — the framework's
# own self-admitted "CHANGELOG lag is THE recurring audit finding". validate previously checked
# only file IDENTITY (deployed==source), never whether the DOCS match reality; this closes that
# blind spot at OUR layer (surfaced by the mex-memory/mex eval — see the memory tool-eval log).
# FULL-ONLY BY DESIGN: a count mismatch cannot be auto-healed (install.sh can't rewrite prose),
# so running it in --quick would loop the watchdog. It fails on `./validate.sh` at commit time —
# exactly when the drift is introduced and a human can fix the number.
_doc_count_check() {  # $1=label  $2=actual  $3=stated(from CLAUDE.md, may be empty)
    if [ -z "$3" ]; then
        fail "Doc-accuracy: could not read the '$1' count in CLAUDE.md (phrasing changed — update this check)"
    elif [ "$2" = "$3" ]; then
        pass "Doc-accuracy: CLAUDE.md '$3 $1' matches code ($2)"
    else
        fail "Doc-accuracy: CLAUDE.md says '$3 $1' but code has $2 — bump the prose (silent count-rot)"
    fi
}
if [ -f "CLAUDE.md" ]; then
    _n_agents=$(ls .claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ')
    _n_skills=$(find .claude/skills -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')
    _n_hooks=$(ls global-config/hooks/*.sh 2>/dev/null | wc -l | tr -d ' ')
    _n_mcp=$(jq -r '.mcpServers|keys|length' .mcp.json.example 2>/dev/null)
    _s_agents=$(grep -oE '[0-9]+ specialized[^0-9]*agents' CLAUDE.md | head -1 | grep -oE '^[0-9]+')
    _s_skills=$(grep -oE '[0-9]+ skills' CLAUDE.md | head -1 | grep -oE '^[0-9]+')
    _s_hooks=$(grep -oE 'Command hooks \([0-9]+ scripts\)' CLAUDE.md | head -1 | grep -oE '[0-9]+')
    _s_mcp=$(grep -oE '[0-9]+ MCP servers' CLAUDE.md | head -1 | grep -oE '^[0-9]+')
    _doc_count_check "specialized SDLC/SSDLC agents" "$_n_agents" "$_s_agents"
    _doc_count_check "skills" "$_n_skills" "$_s_skills"
    _doc_count_check "Command hooks scripts" "$_n_hooks" "$_s_hooks"
    _doc_count_check "MCP servers" "$_n_mcp" "$_s_mcp"
fi

# Doc-vs-code: the library-docs skill / mcp-guide / EXTENSIBILITY must not reference a REMOVED
# context7 tool name OR a REMOVED context7 parameter. The real API is exactly:
#   mcp__context7__resolve-library-id({ libraryName, query })   -- both required
#   mcp__context7__query-docs({ libraryId, query })             -- both required
# `get-library-docs` was renamed to `query-docs`, and `context7CompatibleLibraryID` / `topic` /
# `tokens` were removed outright. The first fix corrected only the TOOL NAMES and left dead
# PARAMETER prose behind ("Use topic parameter...", "Default: 5000 tokens"), which the old
# single-literal grep on 'get-library-docs' happily reported as PASS — a check that cannot see
# the defect class it exists to catch. Signatures below are the unambiguous PARAMETER forms;
# plain English "topic"/"tokens" prose (e.g. sequential-thinking's "31,999 thinking tokens",
# EXTENSIBILITY's generic "Use token limits wisely") deliberately does NOT match.
# FULL-ONLY (repo-doc grep, can't auto-heal → would loop the watchdog in --quick).
_ctx7_docs=(".claude/skills/library-docs/SKILL.md" ".claude/lib/mcp-guide.md" "EXTENSIBILITY.md")
_ctx7_missing=""
for _f in "${_ctx7_docs[@]}"; do
    [ -f "$_f" ] || _ctx7_missing="$_ctx7_missing $_f"
done
if [ -n "$_ctx7_missing" ]; then
    # Fail closed: the guard cannot verify what it cannot read.
    fail "Doc-accuracy: context7 API-shape guard could not run — missing file(s):$_ctx7_missing"
else
    # (a) Removed tool name + removed parameter names in prose/identifier form.
    _stale_ctx7=$(grep -nE \
        'get-library-docs|context7CompatibleLibraryID|(topic|tokens)[[:space:]]+parameter|parameter[[:space:]]+(topic|tokens)|[Dd]efault:[[:space:]]*[0-9,]+[[:space:]]*tokens|[Tt]oken [Ll]imits:' \
        "${_ctx7_docs[@]}" 2>/dev/null)
    # (b) Removed parameter KEYS inside a context7 call block (`topic:` / `tokens:` between the
    #     mcp__context7__ call and its closing `})`), which catches example code specifically.
    _stale_ctx7_keys=$(awk '
        /mcp__context7__/ { inblk = 1 }
        inblk && /(^|[^[:alnum:]_])(topic|tokens)[[:space:]]*:/ { printf "%s:%d:%s\n", FILENAME, FNR, $0 }
        /\}\)/ { inblk = 0 }
    ' "${_ctx7_docs[@]}" 2>/dev/null)
    _stale_ctx7_all=$(printf '%s\n%s' "$_stale_ctx7" "$_stale_ctx7_keys" | grep -v '^$' || true)
    if [ -z "$_stale_ctx7_all" ]; then
        pass "Doc-accuracy: no removed context7 tool name or parameter (get-library-docs / context7CompatibleLibraryID / topic / tokens) in skill/docs"
    else
        _stale_ctx7_n=$(printf '%s\n' "$_stale_ctx7_all" | wc -l | tr -d ' ')
        fail "Doc-accuracy: $_stale_ctx7_n removed-context7-API reference(s) in skill/docs — real API is resolve-library-id{libraryName,query} + query-docs{libraryId,query}"
        [ "$QUIET" = "--quiet" ] || printf '%s\n' "$_stale_ctx7_all" | sed 's/^/         /'
    fi
fi

# ============================================================================
# Fail-open regression guards (FULL-ONLY — these EXECUTE the artifact)
# ============================================================================
# A 28-skill stress test found the most dangerous defect class is verification that always
# reports success ("gates that cannot fail"): stubbed health probes returning True, a validator
# green-lighting a literal [TODO], alerts referencing recording rules that were never defined.
# Eight were repaired — but a fix without a guard silently regresses, and a guard that greps for
# a magic word is a proxy that drifts (exactly how the context7 guard above once certified four
# surviving dead params). So each guard below asserts the INVARIANT by RUNNING the artifact and
# requiring the failure path, and each was gap-tested by reintroducing the bug.
# FULL-ONLY by design: these detect source-content defects install.sh cannot rewrite, so running
# them in --quick would make the watchdog heal-loop forever.
section "Checking fail-open regression guards"

# (1) deployment-runbook health_check.py — unimplemented probes MUST fail closed.
_hc=".claude/skills/deployment-runbook/scripts/health_check.py"
if [ -f "$_hc" ]; then
    if command -v python3 &>/dev/null; then
        # Assert the probe's OUTCOME, not merely "did not exit 0".
        # The original guard tested `if python3 … --check X` (i.e. exit 0). A single-check run can
        # NEVER exit 0 — a run where every executed check passed but not all checks ran exits
        # EXIT_PARTIAL=3 — so the detection branch was unreachable and the guard printed PASS over
        # an injected `return True`. That hole was opened by a LATER repair (adding partial-run exit
        # codes) silently invalidating an EARLIER guard; both were green on the same day.
        # Measured: fail-closed probe -> 1 (EXIT_FAILED); probe stubbed to succeed -> 3 (EXIT_PARTIAL).
        _hc_open=""
        for _probe in database cache external_services; do
            python3 "$_hc" --env staging --check "$_probe" >/dev/null 2>&1
            _hc_rc=$?          # capture BEFORE any other command resets $?
            case $_hc_rc in
                1) ;;                                            # ran, failed closed — correct
                *) _hc_open="$_hc_open ${_probe}(exit=$_hc_rc)" ;;  # 3 == reported healthy without verifying
            esac
        done
        if [ -z "$_hc_open" ]; then
            pass "Fail-open guard: health_check.py unimplemented probes fail closed"
        else
            fail "Fail-open guard: health_check.py probe(s) report SUCCESS without verifying:$_hc_open — a deploy gate that cannot fail"
        fi

        # (1b) A PARTIAL run must NOT exit 0. The loop above only probes checks that are
        # unimplemented, so it cannot see the other fail-open shape: `--check api` against a
        # REACHABLE endpoint runs 1 of 5 probes, and if that reports "ALL CHECKS PASSED" with
        # exit 0 a CI gate reads one healthy endpoint as a verified deployment. Assert the
        # invariant by RUNNING the script against a local stub, not by grepping for a banner.
        # Two-sided: a full run with every probe green must still exit 0, otherwise the script
        # is merely broken (always non-zero) rather than honest.
        _hc_stub=$(python3 - "$_hc" <<'PYEOF'
import contextlib, http.server, importlib.util, io, socketserver, sys, threading

# Importing by path would drop a __pycache__/ next to the artifact, which the
# --quick shared-set drift check then reports as untracked drift on every run.
sys.dont_write_bytecode = True

path = sys.argv[1]


class _Stub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *a):
        pass


srv = socketserver.TCPServer(('127.0.0.1', 0), _Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = 'http://127.0.0.1:%d/health' % srv.server_address[1]


def load():
    spec = importlib.util.spec_from_file_location('hc_guard', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ENVIRONMENTS['staging']['api_url'] = url
    mod.MAX_RESPONSE_TIME_MS = 60000  # testing run accounting, not loopback latency
    return mod


def run(mod, argv):
    sys.argv = argv
    with contextlib.redirect_stdout(io.StringIO()):
        return mod.main()


# The stub must genuinely satisfy the api probe, else a non-zero exit proves nothing.
m = load()
probe_ok, _ = m.HealthChecker('staging').check_api_health()

# PARTIAL run is measured as a SUBPROCESS, not via main()'s return value. A CI gate reads the
# PROCESS exit code, so that is what must be asserted: an in-process check would still pass if
# the `if __name__ == "__main__"` wrapper were changed to sys.exit(0), which is precisely the
# fail-open this guard exists to catch.
import re as _re, subprocess, tempfile, os as _os
_src = open(path).read()
# Patch EVERY api_url (not just the first — 'production' is declared before 'staging', so a
# count=1 substitution would leave staging pointing at an unreachable host; the probe would
# then fail and the guard would go green on a FAILED run rather than on a partial one).
_patched = _re.sub(r"('api_url'\s*:\s*)'[^']*'", lambda mo: mo.group(1) + repr(url), _src)
# Loopback is fast, but pin the latency ceiling so a slow runner cannot turn this into a
# false FAIL — the invariant under test is the exit code, not the machine's timing.
_patched = _re.sub(r'^MAX_RESPONSE_TIME_MS\s*=\s*\d+', 'MAX_RESPONSE_TIME_MS = 60000',
                   _patched, count=1, flags=_re.M)
_tmpdir = tempfile.mkdtemp()
_tmp = _os.path.join(_tmpdir, 'hc_cli_probe.py')
open(_tmp, 'w').write(_patched)
try:
    rc_partial = subprocess.run(
        [sys.executable, '-B', _tmp, '--env', 'staging', '--check', 'api'],
        capture_output=True, text=True, timeout=60).returncode
finally:
    _os.remove(_tmp)
    _os.rmdir(_tmpdir)

m2 = load()
for _attr in [a for a in dir(m2.HealthChecker) if a.startswith('check_')]:
    setattr(m2.HealthChecker, _attr, lambda self, _a=_attr: (True, 'stub'))
rc_full = run(m2, ['health_check.py', '--env', 'staging'])

srv.shutdown()
print('API_PROBE', 'ok' if probe_ok else 'bad')
print('RC_PARTIAL', rc_partial)
print('RC_FULL', rc_full)
# Report the script's own EXIT_PARTIAL so the shell asserts the SPECIFIC partial code rather
# than "any non-zero": a probe that merely failed also exits non-zero and would otherwise let
# this guard pass without ever exercising the partial-run path.
print('EXIT_PARTIAL', getattr(m, 'EXIT_PARTIAL', 2))
PYEOF
) || _hc_stub=""
        _hc_probe=$(printf '%s\n' "$_hc_stub" | awk '$1=="API_PROBE"{print $2}')
        _hc_rc_partial=$(printf '%s\n' "$_hc_stub" | awk '$1=="RC_PARTIAL"{print $2}')
        _hc_rc_full=$(printf '%s\n' "$_hc_stub" | awk '$1=="RC_FULL"{print $2}')
        _hc_exit_partial=$(printf '%s\n' "$_hc_stub" | awk '$1=="EXIT_PARTIAL"{print $2}')
        if [ "$_hc_probe" != "ok" ] || [ -z "$_hc_rc_partial" ] || [ -z "$_hc_rc_full" ]; then
            # Fail closed: unable to execute the artifact (missing `requests`, blocked
            # loopback, changed API) means the invariant is UNVERIFIED, not satisfied.
            fail "Fail-open guard: could not run health_check.py against a local stub — partial-run invariant UNVERIFIED (probe='${_hc_probe:-none}')"
        elif [ "$_hc_rc_partial" = "0" ]; then
            fail "Fail-open guard: health_check.py PARTIAL run (--check api, 1 of 5 probes) exits 0 — CI cannot tell it from a full pass"
        elif [ -n "$_hc_exit_partial" ] && [ "$_hc_rc_partial" != "$_hc_exit_partial" ]; then
            # Non-zero is not enough: a merely FAILED probe also exits non-zero, which would let
            # this guard pass without the partial-run path ever executing.
            fail "Fail-open guard: health_check.py partial run exited $_hc_rc_partial, expected EXIT_PARTIAL=$_hc_exit_partial — the probe failed instead of reporting a partial run, so the invariant is untested"
        elif [ "$_hc_rc_full" != "0" ]; then
            fail "Fail-open guard: health_check.py FULL run with every probe green exits $_hc_rc_full — the gate can never go green"
        else
            pass "Fail-open guard: health_check.py partial run exits EXIT_PARTIAL=$_hc_rc_partial (subprocess), full green run exits 0"
        fi
    else
        warn "Fail-open guard: python3 absent — cannot execute health_check.py"
    fi
fi

# (2) skill-creator quick_validate.py — must REJECT placeholder descriptions (and not
# false-positive on the real corpus). Two-sided: a validator that accepts everything is
# indistinguishable from no validator.
_qv=".claude/skills/skill-creator/scripts/quick_validate.py"
if [ -f "$_qv" ] && command -v python3 &>/dev/null; then
    _qv_tmp=$(mktemp -d)
    mkdir -p "$_qv_tmp/probe-skill"
    printf -- '---\nname: probe-skill\ndescription: "[TODO: describe what this skill does]"\n---\n\n# Probe\n\n## Overview\nPlaceholder body used only to test the validator.\n' \
        > "$_qv_tmp/probe-skill/SKILL.md"
    if python3 "$_qv" "$_qv_tmp/probe-skill" >/dev/null 2>&1; then
        fail "Fail-open guard: quick_validate.py ACCEPTS a '[TODO]' placeholder description — the validator cannot fail"
    else
        # Negative side: it must still accept a real skill, or it is merely broken.
        if python3 "$_qv" ".claude/skills/git-workflow" >/dev/null 2>&1; then
            pass "Fail-open guard: quick_validate.py rejects placeholders, accepts real skills"
        else
            fail "Fail-open guard: quick_validate.py REJECTS a valid skill (git-workflow) — false positive"
        fi
    fi
    rm -rf "$_qv_tmp"
fi

# (3) observability-stack — every recording rule an alert references must be DEFINED in the same
# file. An undefined rule makes the alert an empty vector: it never fires and logs no error.
_obs=".claude/skills/observability-stack/SKILL.md"
if [ -f "$_obs" ] && command -v python3 &>/dev/null; then
    _dangling=$(python3 - "$_obs" <<'PYEOF'
import re, sys
s = open(sys.argv[1]).read()
defined = set(re.findall(r'-\s*record:\s*([A-Za-z_][\w:]*)', s))
referenced = set(re.findall(r'\b([a-z_]+:[a-z_]+:[A-Za-z0-9_]+)\b', s))
print(" ".join(sorted(referenced - defined)))
PYEOF
)
    if [ -z "$_dangling" ]; then
        pass "Fail-open guard: observability-stack alerts reference no undefined recording rules"
    else
        fail "Fail-open guard: observability-stack alert(s) reference UNDEFINED recording rule(s):$_dangling — they can never fire"
    fi
fi

# (4) Skill "## Resources" sections must not advertise files that do not exist — a phantom
# resource is a dead end mid-incident (deployment-runbook cited a test_db_connection.py it never
# shipped, one line from a script that does exist).
if command -v python3 &>/dev/null; then
    _phantom=$(python3 - <<'PYEOF'
import os, re, glob
missing = []
for skill in sorted(glob.glob(".claude/skills/*/SKILL.md")):
    body = open(skill).read()
    m = re.search(r'^## Resources\s*$(.*?)(?=^## |\Z)', body, re.M | re.S)
    if not m:
        continue
    sub = None
    for line in m.group(1).splitlines():
        h = re.match(r'^###\s+(scripts|references|assets)/\s*$', line.strip())
        if h:
            sub = h.group(1); continue
        b = re.match(r'^-\s+\*\*([\w.\-]+)\*\*', line.strip())
        if b and sub:
            p = os.path.join(os.path.dirname(skill), sub, b.group(1))
            if not os.path.exists(p):
                missing.append(p)
print(" ".join(missing))
PYEOF
)
    if [ -z "$_phantom" ]; then
        pass "Fail-open guard: no skill advertises a Resources file that does not exist"
    else
        fail "Fail-open guard: phantom resource file(s) advertised but absent:$_phantom"
    fi
fi

# (5) browser-testing — two repairs that decide whether an "E2E pass" means anything:
#   (a) every assert_response EXAMPLE must pass `value`. With only an `id` the MCP server
#       reports success for ANY response it received — a 401 or 500 comes back as
#       "assertion successful" — so a failed login reads as a green test.
#   (b) every tool name must carry the mcp__playwright__ prefix. A bare `playwright_navigate`
#       is not a callable tool name; an agent copying it gets a tool-not-found error mid-run.
# Both anchors are fail-closed: if the detector finds ZERO invocation examples or ZERO
# prefixed mentions it FAILS, because a restructured file would otherwise let a guard that
# now matches nothing keep reporting green.
_bt=".claude/skills/browser-testing/SKILL.md"
if [ -f "$_bt" ] && command -v python3 &>/dev/null; then
    _bt_err=$(python3 - "$_bt" <<'PYEOF'
import re, sys
s = open(sys.argv[1]).read()
errs = []

# (a) A line naming assert_response AND carrying an `id` argument is an invocation example;
# prose that merely mentions the tool writes `id` in backticks with no colon, so it is not
# swept up here.
inv = [l.strip() for l in s.splitlines()
       if "assert_response" in l and re.search(r'(\bid\s*[:=]|"id")', l)]
if not inv:
    errs.append("no assert_response invocation example found - the guard verifies nothing")
for l in inv:
    if not re.search(r'(\bvalue\s*[:=]|"value")', l):
        errs.append("assert_response example with no 'value' argument: " + l[:90])

# (b) Compare MAXIMAL identifier tokens, so mcp__playwright__playwright_navigate is a single
# token that is skipped wholesale. The deliberate counter-example written as
# `..._playwright_start_codegen_session` tokenizes with a leading underscore and so is not a
# bare name either - the negative teaching example survives this check.
prefixed = 0
for m in re.finditer(r'[A-Za-z0-9_]+', s):
    t = m.group(0)
    if t.startswith("mcp__playwright__"):
        prefixed += 1
        continue
    if re.fullmatch(r'playwright_[a-z_]+', t) or \
       re.fullmatch(r'(start|end|get|clear)_codegen_session', t):
        errs.append("tool name missing mcp__playwright__ prefix (line %d): %s"
                    % (s[:m.start()].count("\n") + 1, t))
if prefixed == 0:
    errs.append("no mcp__playwright__ tool mention found - the guard verifies nothing")

# (c) Visual regression must not trust the comparator to notice a size mismatch. Measured on
# ImageMagick 7.1.2-21: `compare -metric AE` on 200x200 vs 100x100 returns "0 (0)" with exit 0
# -- a PERFECT PASS -- while a real same-size regression returns exit 1. The skill previously
# asserted the opposite ("a size mismatch makes the comparator error out"), which is wrong in
# the direction that hides regressions. Require the dimension assertion, and forbid the claim.
if "compare -metric" in s:
    if not re.search(r"identify\s+-format\s+'%wx%h'", s):
        errs.append("visual regression compares without asserting identical dimensions first "
                    "(magick identify -format '%wx%h') - a size mismatch scores AE=0 exit 0, a clean pass")
    if re.search(r"size mismatch makes the comparator error out", s):
        errs.append("false claim retained: a size mismatch does NOT make ImageMagick error out")
print("; ".join(errs))
PYEOF
)
    if [ -z "$_bt_err" ]; then
        pass "Fail-open guard: browser-testing assert_response examples pass 'value'; tool names are mcp__playwright__-prefixed"
    else
        fail "Fail-open guard: browser-testing — $_bt_err"
    fi
fi

# (6) ci-cd-templates — the same fail-open defect expressed as pipeline YAML: a step that
# reports success no matter what it found or what the server answered.
#   (a) semgrep exits 0 even WITH findings unless `--error` is passed, so a SAST job without
#       it is a decorative gate. The only other honest shape is report-mode, which must be
#       declared machine-readably in a comment within 3 lines above the invocation.
#   (b) curl exits 0 on HTTP 4xx/5xx unless `--fail`/`--fail-with-body` (or a short flag
#       bundling -f) is passed, so a deploy webhook returning 500 marks the deploy green.
# `apk add ... curl` and friends install the binary rather than invoke it, so the detector
# requires curl in command position with at least one argument. Fail-closed on zero matches.
_cicd=".claude/skills/ci-cd-templates/SKILL.md"
if [ -f "$_cicd" ] && command -v python3 &>/dev/null; then
    _cicd_err=$(python3 - "$_cicd" <<'PYEOF'
import re, sys
lines = open(sys.argv[1]).read().splitlines()
errs = []
# `^` alone anchors at position 0, so a command INDENTED inside a `run: |` block — the
# normal YAML shape — was invisible to this guard. `^\s*` is required.
CMD = r'(?:^\s*|[-|;&]\s*|\brun:\s*|&&\s*|\|\s*)'

sem = [(i + 1, l) for i, l in enumerate(lines) if re.search(CMD + r'semgrep\s', l)]
if not sem:
    errs.append("no semgrep invocation found - the guard verifies nothing")
for n, l in sem:
    if "--error" in l:
        continue
    # Explicit opt-out: the three lines above must declare the job is report-only.
    if any("report-mode" in c for c in lines[max(0, n - 4):n - 1]):
        continue
    errs.append("semgrep invocation (line %d) has no --error and no 'report-mode' "
                "declaration above it - it exits 0 on findings" % n)

cur = [(i + 1, l) for i, l in enumerate(lines) if re.search(CMD + r'curl\s+\S', l)]
if not cur:
    errs.append("no curl invocation found - the guard verifies nothing")
for n, l in cur:
    if re.search(r'(--fail-with-body|--fail\b|(?<![\w-])-[a-zA-Z]*f[a-zA-Z]*(?![\w-]))', l):
        continue
    errs.append("curl invocation (line %d) has no --fail/--fail-with-body - "
                "an HTTP 4xx/5xx exits 0 and the step reports success" % n)
print("; ".join(errs))
PYEOF
)
    if [ -z "$_cicd_err" ]; then
        pass "Fail-open guard: ci-cd-templates semgrep carries --error; every curl carries --fail"
    else
        fail "Fail-open guard: ci-cd-templates — $_cicd_err"
    fi
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
# Pre-Flight Gates Must Be ABORT-DOMINANT (FULL-ONLY)
# ============================================================================
# The check above greps the literal heading — a LABEL, not a rule. A reviewer restored the old
# always-true OR arm ("**Gate:** Explicit invocation, or a genuinely hard problem.") underneath an
# intact `## Pre-Flight Gate` heading and validate still printed PASS. An unconditional invocation
# arm makes the gate's own ABORT list unreachable in precisely the case the list exists for — the
# user typing the slash command — so the heading check certifies a gate that cannot fire.
#
# ASSERTION CHOICE: this guard tests the LOGICAL RELATION between the gate's two arms, not any one
# phrase — and it now tests BOTH sides, because an evader only has to beat the weaker one. The
# weaker one was the invocation arm: negation was already matched as a synonym family while
# invocation was a CLOSED 6-token list, so a paraphrase ("the slash command alone suffices") walked
# straight past. Worse, the negation test was chunk-scoped, so a grant and its own neutralizer
# could sit in ONE chunk and the chunk read as neutralized — "**Gate:** Explicit invocation, or a
# multi-step goal, though invocation does not override an ABORT" was a demonstrated FALSE PASS.
# The previous claim here — that fine-grained chunking stops laundering — was WRONG; it is retracted.
#
#   (i) GRANT detector (per LINE, and with NO negation amnesty — this is what actually stops
#       laundering). Any line in the gate section that references the trigger (invocation /
#       invoking / invoked / slash command / typing / activation / being asked / an act of invoking
#       such as "running `/x`") and ALSO grants passage fails outright. Passage is granted three
#       ways: a sufficiency claim (enough | suffices | sufficient | all it takes | by itself | on
#       its own | alone is | qualifies | clears/passes/satisfies the gate | green light); a
#       criterion DECLARATION that is not restrictive (a `Gate:`/`Criteria:`/`Condition:`/`Trigger:`
#       label, or "proceed|run|use|apply|activate ... when|if", with no "only"); or an
#       unconditional quantifier ("any invocation", "whenever invoked", "automatically clears").
#       A negation elsewhere on the line does NOT launder the grant — only a negator governing the
#       sufficiency word's own clause (no comma/semicolon crossed) counts. So "invocation is not
#       enough" passes, while "... does not override an ABORT, though running `/execute` is enough"
#       fails. Breadth is safe on the trigger side here precisely because the grant marker is the
#       rare, discriminating half — the pairing is what makes it specific.
#
#  (ii) ARM + DOMINANCE (chunk level). A chunk naming invocation via the NARROW token list and not
#       neutralized is an un-neutralized arm; and at least one chunk must assert dominance — a
#       negation (not|never|n't) reaching an override verb (override|overrule|bypass|waive|
#       supersede|trump|excuse) while referring to the abort/gate. Dominance RECOGNITION uses the
#       BROAD trigger family while offence detection keeps the NARROW one: widening recognition can
#       only credit more honest phrasings ("Typing `/execute` does not waive the gate", which the
#       narrow list scored NODOMINANCE) and can never admit an evasion, whereas widening offence
#       would false-fail benign redirect prose like "then run `/investigate` for the root cause".
#
# A third conjunct requires the section to declare ABORT conditions at all (>=2 `ABORT` mentions:
# the dominance statement plus at least one condition), so dominance over an empty set cannot pass
# vacuously.
#
# Scope is DERIVED from source (every SKILL.md carrying the heading), never a hardcoded list — the
# fork-spawn guard below documents why a two-name list printed PASS over a live instance. The
# coverage cross-check then asserts the derived set still contains every GATED_SKILLS entry, so
# renaming a heading cannot shrink the guard's scope silently.
# FULL-ONLY: a prose defect install.sh cannot rewrite, so --quick would heal-loop the watchdog.
#
# GAP-TESTED BY EXECUTION against copies of the four gate files. Only results actually observed are
# recorded here:
#   the four gate files as they stand (deep-analysis/diverge/execute/investigate) -> OK, all four
#   dominance sentence deleted                                     -> NODOMINANCE
#   pre-repair gate restored ("**Gate:** Explicit invocation, or a genuinely hard problem.") -> ARM
#   ABORT mentions reduced to one                                  -> NOABORTS|1
#   heading absent                                                 -> NOSECTION
#   6 legitimate rewordings of the dominance sentence ("never bypasses the ABORT list", "does not
#     waive the gate", "does not excuse an ABORT", "does not supersede an ABORT", ...) -> OK
#
# A PREVIOUS VERSION OF THIS COMMENT claimed "25 evasion strings -> 0 leaks". That claim was false:
# an independent gate then leaked three of them through the live validate.sh. Corrected, and the
# two root causes fixed, both of which were structural rather than vocabulary gaps:
#   A. the denial-amnesty fragments were unanchored, so `pass` matched inside "bypass" and the
#      sentence "... is enough, though it never bypasses the ABORT list" cancelled its own grant;
#   B. `trig` — a closed verb list — gated the STRONG signals and short-circuited with `next`, so
#      "If the user says `/execute`, proceed." and "Whenever the user requests it, run the
#      protocol." were never examined at all. g_suff/g_always now evaluate independently of trig.
# Because B showed the blacklist is only ever one paraphrase from a leak, conjunct (0) inverts the
# approach for bullets: a positive whitelist of the three legitimate shapes. Re-run after the fix
# (`_gate_dominance` on synthetic sections, output captured):
#   10 evasions incl. all 3 that leaked and the 4 the reviewers demonstrated -> 0 leaks (7 GRANT, 2 ARM)
#   2 legitimate restrictive run-conditions ("Run the N-phase protocol only when/for ...") -> OK
#   the four live gate files (deep-analysis/diverge/execute/investigate)      -> OK, all four
# Not claimed: evasion-proof. A grant written as a PROSE PARAGRAPH rather than a bullet still faces
# only conjuncts (i)/(ii), which remain vocabulary-based.
# KNOWN LIMIT, pre-existing and unchanged by this hardening (verified by running the HEAD analyzer
# on the same probes — identical verdicts): the ARM conjunct flags ANY chunk naming invocation that
# is not itself a negation-reaching-an-override-verb. So a conjunctive restrictive criterion ("Run
# the protocol only when invoked AND the goal is multi-step"), an outright prohibition ("Do not run
# the protocol when merely invoked"), and neutral prose ("Being invoked is common; check every ABORT
# row") are all reported ARM. Those are false FAILs — the guard is too strict there — not fail-opens,
# and ARM fires before the new GRANT conjunct, so exempting them on the GRANT side would be dead code.

_gate_dominance() {
    awk '
        /^##+[[:space:]]*Pre-Flight Gate/ { inb=1; found=1; next }
        inb && /^##+[[:space:]]/          { inb=0 }
        inb {
            body = body " " $0

            # ---- (i) per-LINE passage-GRANT detector; no same-line negation amnesty ----
            ln = tolower($0)
            gsub(/\*\*/, "", ln)   # so **Gate:** reads as gate:

            # ---- (0) fail-CLOSED bullet whitelist -------------------------------------
            # A blacklist of "granting" phrasings is an arms race the guard keeps losing: three
            # evasions leaked past conjunct (i) below purely by dodging its verb list. Inside a
            # gate section the legitimate bullet vocabulary is tiny and formulaic, so the shapes
            # are enumerated POSITIVELY instead: an ABORT, a ROUTE OUT, or a restrictive
            # run-condition. Any other bullet fails regardless of what it says, which is what
            # makes it robust to paraphrase. A false FAIL here is loud and one edit to fix; the
            # false PASS it replaces was silent. Prose PARAGRAPHS are deliberately not whitelisted
            # (the dominance sentence is free-form) — they remain covered only by (i) and (ii).
            if ($0 ~ /^[[:space:]]*[-*][[:space:]]/) {
                if ($0 !~ /^[[:space:]]*[-*][[:space:]]*(\*\*)?(ABORT|ROUTE OUT)/ \
                    && ln !~ /(^|[^a-z])only([^a-z]|$)/) {
                    grants++
                    if (granttxt == "") { granttxt = $0 }
                }
            }

            trig = (ln ~ /invocation|invoking|invoked|unconditional|slash command|user typed|user asks|user asked|explicitly asked|being asked|asked for it|typing|typed|activation/ \
                    || ln ~ /(^|[^a-z])(run|running|type|typing|typed|call|calling|use|using|say|saying|says|ask|asking|asks|enter|entering|issue|issuing|request|requests|requesting|invoke|invokes)[a-z]*[ \t]+[`"]?\//)

            g_suff = (ln ~ /(^|[^a-z])(enough|suffice|suffices|sufficient|all it takes|by itself|on its own|alone is|is alone|qualifies|qualify)([^a-z]|$)/ \
                      || ln ~ /(clear|pass|satisf|meet)[a-z]*[ \t]+(this[ \t]+|the[ \t]+)?gate|green.?light/)
            # Only a negator inside the same clause as the sufficiency word denies it (no , ; . is
            # crossed): "invocation is not enough" is a denial, "..., though invoking it is enough" is not.
            # Every fragment is anchored on a non-letter. Unanchored, the `pass` branch matched
            # INSIDE "bypass", so "… though it never bypasses the ABORT list" — the most natural
            # disclaimer anyone would write — cancelled its own grant and the line passed clean.
            if (g_suff && ln ~ /(^|[^a-z])(not|never|n.t|nor|hardly|rarely)([^.,;]*[^a-z])?(enough|suffic|all it takes|by itself|on its own|alone|qualif|clear|pass|satisf|meet|green)/) g_suff = 0
            g_label  = (ln ~ /(^|[^a-z])(gate|criteria|criterion|condition|conditions|trigger|triggers|threshold|entry|passage)[ \t]*:/)
            g_cond   = (ln ~ /(^|[^a-z])(proceed|run|use|apply|activate|start|engage)[a-z]*[^.]*[^a-z](when|if)([^a-z]|$)/)
            g_always = (ln ~ /(any|every)[ \t]+(invocation|invoking|use|time)|whenever[ \t]+(invoked|invoking|the user|you are|it is)|always[ \t]+(proceed|run|qualif|pass)|automatic[a-z]*[ \t]*(proceed|run|qualif|pass|clear|satisf)/)
            restrictive = (ln ~ /(^|[^a-z])only([^a-z]|$)/)

            # g_suff and g_always are self-identifying ("X alone suffices", "whenever the user …"):
            # gating them behind `trig` let any paraphrase outside its verb list skip detection
            # entirely. Only the weak conjuncts (a bare label or a when/if clause) still need a
            # trigger word to show the subject really is invocation.
            if (g_suff || g_always || ((g_label || g_cond) && trig && !restrictive)) {
                grants++
                if (granttxt == "") { granttxt = $0 }
            }
        }
        END {
            if (!found) { print "NOSECTION"; exit }
            tmp = body
            aborts = gsub(/ABORT/, "", tmp)
            # ---- (ii) chunk-level un-neutralized ARM + dominance assertion ----
            # Sentence-sized chunks, bold delimiters split too. NOTE: chunking alone does NOT stop
            # laundering (demonstrated false pass) — conjunct (i) above is what does.
            gsub(/[.!?][ \t]+/, "&\n", body)
            gsub(/\*\*/, "\n", body)
            n = split(body, chunk, "\n")
            for (i = 1; i <= n; i++) {
                low = tolower(chunk[i])
                # NARROW = offence (widening it false-fails benign redirect prose).
                inv_narrow = (low ~ /unconditional/ || low ~ /invocation/ || low ~ /invoked/ \
                       || low ~ /user typed/ || low ~ /typed `\// || low ~ /explicitly asked/)
                # BROAD = dominance recognition only; can credit more honest phrasings, never admit one.
                inv_broad = (inv_narrow || low ~ /invoking|slash command|typing|user asks|user asked|being asked|asked for it|activation/ \
                       || low ~ /(^|[^a-z])(run|running|type|typing|typed|call|calling|use|using|say|saying|ask|asking|enter|entering|issue|issuing)[ \t]+[`"]?\//)
                neg = (low ~ /(not|never|n.t)[^.]*(override|overrule|bypass|waive|supersede|trump|excuse)/)
                ref = (low ~ /abort|gate/)
                if (inv_broad && neg && ref) { ok++; continue }
                if (inv_narrow) { bad++; if (badtxt == "") badtxt = chunk[i] }
            }
            if (bad > 0)    { gsub(/^[ \t]+|[ \t]+$/, "", badtxt); print "ARM|" substr(badtxt, 1, 110); exit }
            if (grants > 0) { gsub(/^[ \t]+|[ \t]+$/, "", granttxt); print "GRANT|" substr(granttxt, 1, 110); exit }
            if (ok == 0)    { print "NODOMINANCE"; exit }
            if (aborts < 2) { print "NOABORTS|" aborts; exit }
            print "OK"
        }
    ' "$1"
}

section "Checking Pre-Flight Gates Are Abort-Dominant"

_gated_found=""
for _gate_file in .claude/skills/*/SKILL.md; do
    [ -f "$_gate_file" ] || continue
    grep -Eq '^##+[[:space:]]*Pre-Flight Gate' "$_gate_file" 2>/dev/null || continue
    _gname=$(basename "$(dirname "$_gate_file")")
    _gated_found="$_gated_found $_gname"
    _gverdict=$(_gate_dominance "$_gate_file")
    case "$_gverdict" in
        OK)
            pass "$_gname: pre-flight gate is abort-dominant" ;;
        ARM\|*)
            fail "$_gname: un-neutralized invocation arm — invoking the skill satisfies the gate, so its ABORT list is unreachable: ${_gverdict#ARM|}" ;;
        GRANT\|*)
            fail "$_gname: gate GRANTS passage on invocation (sufficiency claim / non-restrictive criterion / unconditional trigger) — a same-line disclaimer does not neutralize it: ${_gverdict#GRANT|}" ;;
        NODOMINANCE)
            fail "$_gname: gate never states that invocation does NOT override an ABORT — dominance is unasserted" ;;
        NOABORTS\|*)
            fail "$_gname: gate asserts dominance but declares no ABORT conditions to dominate (${_gverdict#NOABORTS|} ABORT mention(s))" ;;
        NOSECTION)
            fail "$_gname: '## Pre-Flight Gate' heading matched but no section body could be read" ;;
        *)
            fail "$_gname: abort-dominance analyzer returned an unrecognized verdict '$_gverdict' — guard could not verify" ;;
    esac
done

if [ -z "$_gated_found" ]; then
    # Fail closed: zero gated skills means the guard asserted nothing at all.
    fail "Abort-dominance guard: no SKILL.md carries a '## Pre-Flight Gate' heading — guard verified nothing"
else
    # Coverage: a renamed/removed heading must not silently drop a skill out of scope above.
    _gate_missing=""
    for gated_skill in "${GATED_SKILLS[@]}"; do
        [ -f ".claude/skills/${gated_skill}/SKILL.md" ] || continue
        case " $_gated_found " in
            *" $gated_skill "*) ;;
            *) _gate_missing="$_gate_missing $gated_skill" ;;
        esac
    done
    if [ -z "$_gate_missing" ]; then
        pass "Abort-dominance guard: every expected gated skill carries a '## Pre-Flight Gate' heading"
    else
        fail "Abort-dominance guard: expected gated skill(s) have no '## Pre-Flight Gate' heading and were not analyzed:$_gate_missing"
    fi
fi

# ============================================================================
# Forked Skills Must Not Instruct Spawning
# (a forked subagent has no Agent launcher and no AskUserQuestion)
# ============================================================================

# DERIVED from source, never a hardcoded allowlist. The previous version checked a
# two-name list ("diverge" "execute") and so printed PASS while deep-read — which
# declares `context: fork` AND documented "Launch parallel Explore agents" plus
# AskUserQuestion steps — was a live instance of the very pattern this guard forbids.
# Any skill can acquire `context: fork` in one line, so the set under test must come
# from the files, not from a list a maintainer has to remember to update.
#
# Rule: for every skill whose FRONTMATTER declares `context: fork`, no line may instruct
# a capability a forked subagent lacks (Agent launcher / Explore agent / sub-agent spawn /
# AskUserQuestion) UNLESS the file carries an explicit fork caveat naming that capability
# as unavailable (as /investigate and /deep-read do), which tells the reader the step
# applies only to an un-forked run. Referenced-with-no-caveat is a FAIL.

# A retired skill must be GONE from the live install, not merely deleted from the repo. The
# skills orphan-prune is scoped to names the framework currently ships, so a deleted skill is
# indistinguishable from a personal one and would linger in ~/.claude/skills — still
# auto-activating in every project. install.sh's RETIRED_SKILLS list prunes it; assert it worked.
section "Checking Retired Skills Are Gone From The Live Install"
_retired_live=""
if [ -f "install.sh" ]; then
    for _rs in $(awk '/^RETIRED_SKILLS=\(/{f=1;next} f&&/^\)/{exit} f{gsub(/[" \t]/,"");if($0!="")print}' install.sh); do
        [ -d "$HOME/.claude/skills/$_rs" ] && _retired_live="$_retired_live $_rs"
        [ -d ".claude/skills/$_rs" ] && fail "Retired-skill guard: '$_rs' is in RETIRED_SKILLS but still shipped in source"
    done
    if [ -z "$_retired_live" ]; then
        pass "Retired-skill guard: no retired skill remains in ~/.claude/skills"
    else
        fail "Retired-skill guard: retired skill(s) still live in ~/.claude/skills:$_retired_live — run ./install.sh --update"
    fi
fi

# ONE detector, two sweeps (SKILL.md below, and the reference files after it). Factored into a
# function deliberately: two copies of this awk would drift, and a drifted second copy that matches
# nothing is a guard reporting green over an unread file — the defect class this file exists to catch.
_fork_scan() {
    awk '
        {
            low = tolower($0)
            is_ask   = (low ~ /askuserquestion/)
            # `task tool` is the canonical spawn mechanism in this product and was missing;
            # `launch ... agent` catches the instruction phrasing that names no tool.
            is_agent = (low ~ /explore agent|sub-?agent|subagent_type|spawn|`agent`|agent tool|agent launcher|task tool|launch[^.]*agent/)
            if (!is_ask && !is_agent) next
            # A line that states the fork LIMITATION is documentation, not an instruction.
            # Excused only by a marker ON THIS LINE — either it states the fork limitation,
            # or it explicitly scopes itself out of fork mode. A caveat elsewhere in the
            # file must NOT excuse an instruction here (that was the amnesty hole).
            if ((low ~ /fork/ && low ~ /cannot|can not|unavailable|not available|does not have|do not have|no access/) \
                || low ~ /un-?forked only|main session only|not in fork|unavailable when forked/) {
                if (is_ask)   cav_ask = 1
                if (is_agent) cav_agent = 1
                next
            }
            if (is_ask)   off_ask = 1
            if (is_agent) off_agent = 1
            printf "OFF %d: %s\n", FNR, substr($0, 1, 120)
        }
        END { printf "SUM %d %d %d %d\n", off_ask+0, off_agent+0, cav_ask+0, cav_agent+0 }
    ' "$1"
}

section "Checking Forked Skills Do Not Instruct Spawning"

_fork_files=()
_skill_total=0
for _skill_file in .claude/skills/*/SKILL.md; do
    [ -f "$_skill_file" ] || continue
    _skill_total=$((_skill_total + 1))
    # Frontmatter only: everything between the first two --- fences.
    # Accept quoted forms too: `context: "fork"` / `context: 'fork'` are the same YAML value,
    # and a bare-word-only match would silently skip scanning such a skill entirely.
    if awk 'NR==1 && /^---[[:space:]]*$/ {inb=1; next} inb && /^---[[:space:]]*$/ {exit} inb {print}' \
        "$_skill_file" 2>/dev/null | grep -qE '^context:[[:space:]]*["'"'"']?fork["'"'"']?[[:space:]]*$'; then
        _fork_files+=("$_skill_file")
    fi
done

if [ "$_skill_total" -eq 0 ]; then
    # Fail closed: no skills readable means the guard verified nothing.
    fail "Fork-spawn guard: no .claude/skills/*/SKILL.md found — guard could not run"
elif [ "${#_fork_files[@]}" -eq 0 ]; then
    pass "Fork-spawn guard: no skill declares 'context: fork' ($_skill_total skills scanned)"
else
    for _fork_file in "${_fork_files[@]}"; do
        _fname=$(basename "$(dirname "$_fork_file")")
        _fscan=$(_fork_scan "$_fork_file")
        read -r _off_ask _off_agent _cav_ask _cav_agent <<< "$(printf '%s\n' "$_fscan" | awk '$1=="SUM"{print $2, $3, $4, $5}')"

        # NO file-level caveat amnesty. A line that states the limitation is already skipped
        # above (the `next` in the caveat branch), so anything reaching the offence counters is
        # a genuine instruction. Letting one boilerplate caveat sentence exempt every later
        # violation in the file is exactly the "guard that certifies green" anti-pattern.
        if [ "$_off_ask" = "0" ] && [ "$_off_agent" = "0" ]; then
            pass "$_fname: forked and instructs no Agent-launcher/AskUserQuestion step"
        else
            fail "$_fname: declares 'context: fork' but instructs capabilities a forked subagent lacks (Agent launcher / AskUserQuestion) with no fork caveat naming them"
            [ "$QUIET" = "--quiet" ] || printf '%s\n' "$_fscan" | grep '^OFF ' | sed 's/^OFF /         line /'
        fi
    done
fi

# ---- Coverage extension: the REFERENCE files of fork-declared skills ----------------------
# The sweep above globbed only `.claude/skills/*/SKILL.md`, and this script contained zero
# occurrences of `references/` — so a live violation one directory down was invisible to it:
# `.claude/skills/investigate/references/investigation-frameworks.md:158` instructs an
# "Explore agent" while investigate declares `context: fork`. A skill's references/ is read by
# the same forked subagent as its SKILL.md, so the same rule must apply. Same detector, wider glob.
#
# SCOPING CHOICE — stated plainly because it leaves something unguarded. Two such violations
# already exist in reference files that this change does not own and may not edit. They are pinned
# below by EXACT offending text (not by filename, not by a count, not by line number, which would
# shift under any edit) and reported as WARN, so the pre-existing debt is visible on every run
# without failing the build. ANY finding that is not one of those exact lines FAILS — including a
# NEW violation in the very same file. Residual hole, accepted knowingly: if a pinned line is
# fixed and later reintroduced verbatim it warns instead of failing.
#
# The pin cannot rot into a fail-open: for every baseline entry whose text is STILL PRESENT in its
# file, the sweep must actually have flagged it. Present-but-unflagged means the detector stopped
# working, which is a FAIL — that is this guard's own self-test, run against real data every time.
_fork_ref_baseline=(
    ".claude/skills/deep-analysis/references/integration-guide.md|Task #1: Research current API surface → Explore agent"
    ".claude/skills/investigate/references/investigation-frameworks.md|### Pass 1: Broad Sweep (Explore agent)"
)

section "Checking Forked Skills' Reference Files Do Not Instruct Spawning"

if [ "${#_fork_files[@]}" -eq 0 ]; then
    pass "Fork-ref guard: no skill declares 'context: fork' — no reference files in scope"
else
    _ref_files=()
    for _fork_file in "${_fork_files[@]}"; do
        while IFS= read -r _ref; do
            [ -n "$_ref" ] && _ref_files+=("$_ref")
        done < <(find "$(dirname "$_fork_file")" -type f -name '*.md' ! -name 'SKILL.md' ! -name '._*' 2>/dev/null | sort)
    done

    _ref_new=""
    _ref_hit=""          # newline-joined "path|trimmed text" of everything the sweep flagged
    # bash 3.2 (what macOS ships) errors on "${arr[@]}" for an EMPTY array under `set -u`, which
    # would abort validate.sh mid-run rather than report anything. Reachable the moment a forked
    # skill ships no reference files.
    for _ref in ${_ref_files[@]+"${_ref_files[@]}"}; do
        while IFS= read -r _oline; do
            [ -n "$_oline" ] || continue
            _otxt=$(printf '%s' "$_oline" | sed 's/^OFF [0-9]*: //; s/^[[:space:]]*//; s/[[:space:]]*$//')
            _ref_hit="$_ref_hit$_ref|$_otxt
"
            _known=0
            for _b in "${_fork_ref_baseline[@]}"; do
                [ "$_ref|$_otxt" = "$_b" ] && { _known=1; break; }
            done
            if [ "$_known" -eq 1 ]; then
                warn "Fork-ref guard: KNOWN pre-existing fork violation, baselined not fixed — $_ref:${_oline#OFF }"
            else
                _ref_new="$_ref_new $_ref:${_oline#OFF }"
            fi
        done < <(_fork_scan "$_ref" | grep '^OFF ' || true)
    done

    if [ -z "$_ref_new" ]; then
        pass "Fork-ref guard: no NEW fork violation in ${#_ref_files[@]} reference file(s) of ${#_fork_files[@]} forked skill(s)"
    else
        fail "Fork-ref guard: NEW fork violation(s) in a forked skill's reference file — a forked subagent has no Agent launcher / AskUserQuestion:$_ref_new"
    fi

    # Self-test: a baseline entry still present in its file MUST have been flagged.
    _ref_rot=""
    for _b in "${_fork_ref_baseline[@]}"; do
        _bf="${_b%%|*}"; _bt="${_b#*|}"
        if [ ! -f "$_bf" ]; then
            warn "Fork-ref guard: baselined file no longer exists ($_bf) — drop the stale baseline entry"
        elif ! grep -Fq "$_bt" "$_bf" 2>/dev/null; then
            warn "Fork-ref guard: baselined violation was FIXED in $_bf — drop the entry so it fails if reintroduced"
        elif ! printf '%s' "$_ref_hit" | grep -Fqx "$_bf|$_bt"; then
            _ref_rot="$_ref_rot $_bf"
        fi
    done
    if [ -z "$_ref_rot" ]; then
        pass "Fork-ref guard: detector self-test — every still-present baselined violation was re-detected"
    else
        fail "Fork-ref guard: detector REGRESSED — baselined violation text is still in the file but the sweep no longer flags it:$_ref_rot"
    fi
fi

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
# /execute Agent Matrix Must Enumerate Every Shipped Agent
# ============================================================================
#
# agent-selection.md called itself the "complete reference" while listing 9 of 13 agents, so
# security-auditor (the Opus agent CLAUDE.md marks CRITICAL) was unselectable from /execute and
# security work routed to a grep-based scanner instead. The file carries a self-check, but a
# doc-only invariant is one nobody runs — and that one was itself fail-open (run from the wrong
# directory, both inputs come back empty and `comm` prints nothing, which reads as clean).
# Enforced here with both sides asserted non-empty.
#
# Gap-tested by mutation: one `### <agent>` heading removed -> FAIL naming it; restored -> PASS.

section "Checking /execute agent matrix covers every shipped agent"

_sel_doc=".claude/skills/execute/references/agent-selection.md"
if [ -f "$_sel_doc" ] && [ -d ".claude/agents" ]; then
    _have=$(ls .claude/agents/*.md 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/\.md$//' | sort)
    _doc=$(grep -oE '^### [a-z-]+' "$_sel_doc" | sed 's/^### //' | sort)
    if [ -z "$_have" ] || [ -z "$_doc" ]; then
        fail "/execute agent matrix: an input was empty (agents=$(printf '%s' "$_have" | grep -c . ), doc=$(printf '%s' "$_doc" | grep -c . )) — comparison not performed"
    else
        _missing=$(comm -23 <(printf '%s\n' "$_have") <(printf '%s\n' "$_doc") | tr '\n' ' ')
        if [ -n "${_missing// /}" ]; then
            fail "/execute agent matrix omits shipped agent(s): ${_missing% } — unselectable by /execute"
        else
            pass "/execute agent matrix enumerates all $(printf '%s\n' "$_have" | grep -c .) shipped agents"
        fi
    fi
else
    fail "/execute agent matrix: $_sel_doc or .claude/agents missing — coverage unverified"
fi

# ============================================================================
# /optimize Test Gate Must Reject a Zero-Test Run
# ============================================================================
#
# EXECUTES the shipped regex instead of grepping for it. The default was written
# `[0-9]+ (passed|...)`, which matches the literal string "0 passed" — so a runner that
# collected zero tests and exited 0 read GREEN through the very gate added to stop that.
# A guard that merely asserted the line exists would have passed over it, so this one
# feeds the regex the strings that matter and checks the verdict.
#
# Gap-tested by mutation: default reverted to `[0-9]+ ...` -> FAIL; line deleted -> FAIL;
# unmodified -> PASS.

section "Checking /optimize test gate rejects zero-test runs"

_opt_cmd=".claude/commands/optimize.md"
if [ -f "$_opt_cmd" ]; then
    # Pull the shipped default out of  : "${GUARD_RAN_RE:=<regex>}"
    _ran_re=$(sed -n 's/^: *"\${GUARD_RAN_RE:=\(.*\)}" *$/\1/p' "$_opt_cmd" | head -1)
    if [ -z "$_ran_re" ]; then
        fail "/optimize: no GUARD_RAN_RE default found — the zero-test gate is absent or was renamed"
    else
        _zero_leak=""
        for _probe in "0 passed" "0 passing" "0 tests ran" "0 ok"; do
            printf '%s' "$_probe" | grep -Eqi "$_ran_re" && _zero_leak="$_zero_leak '$_probe'"
        done
        # Counter-probe: the regex must still recognise a real run, or it is merely fail-shut.
        if printf '%s' "12 passed" | grep -Eqi "$_ran_re"; then
            _real_ok=1
        else
            _real_ok=0
        fi
        if [ -n "$_zero_leak" ]; then
            fail "/optimize GUARD_RAN_RE matches a zero-test run —$_zero_leak reads GREEN (fail-open)"
        elif [ "$_real_ok" -eq 0 ]; then
            fail "/optimize GUARD_RAN_RE rejects a real run ('12 passed') — gate is unusable"
        else
            pass "/optimize GUARD_RAN_RE rejects zero-test output and accepts a real run"
        fi
    fi
else
    fail "/optimize command file not found — test-gate invariant unverified"
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

# ============================================================================
# Self-Healing runbook (moved out of CLAUDE.md for context economy — FULL-ONLY)
# ============================================================================
# The self-heal detail lives in SELF-HEALING.md so CLAUDE.md doesn't load it every
# session. Guard that the runbook still EXISTS, still carries the restore commands, and
# is still LINKED from CLAUDE.md — otherwise the moved runbook could silently vanish or
# the pointer go dead, which the CLAUDE.md-only memory-restore grep above wouldn't catch.
section "Checking Self-Healing runbook (SELF-HEALING.md)"
if [ -f "SELF-HEALING.md" ]; then
    pass "SELF-HEALING.md present"
    _sh_missing=""
    for _tok in 'memory-latest.tgz' 'userconfig-' '.bundle'; do
        grep -q "$_tok" SELF-HEALING.md 2>/dev/null || _sh_missing="$_sh_missing $_tok"
    done
    if [ -z "$_sh_missing" ]; then
        pass "SELF-HEALING.md retains the snapshot-restore commands"
    else
        fail "SELF-HEALING.md missing restore command token(s):$_sh_missing"
    fi
    if grep -q 'SELF-HEALING.md' CLAUDE.md 2>/dev/null; then
        pass "CLAUDE.md links to SELF-HEALING.md"
    else
        fail "CLAUDE.md no longer links to SELF-HEALING.md (self-heal runbook orphaned)"
    fi
else
    fail "SELF-HEALING.md missing — the Self-Healing runbook was moved here from CLAUDE.md"
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
