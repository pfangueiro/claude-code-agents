#!/usr/bin/env bash
# ============================================================================
# SessionStart Health-Check Hook — Self-Healing Framework
# ============================================================================
# Runs on every Claude Code session start. Reconciles deployed state under
# ~/.claude/ against the source-of-truth repo. On drift, forks a background
# `install.sh --update` and logs the event. Must exit 0 always — never block
# session start.
#
# Hot path: <2s. Heavy work is forked and disowned.
#
# Logs:
#   ~/.claude/analytics/framework-health.jsonl  — drift_detected / healthcheck_pass
# ============================================================================

set -uo pipefail

START_TS_MS=$(perl -MTime::HiRes=time -e 'printf "%d\n", time()*1000' 2>/dev/null || date +%s000)

ANALYTICS_DIR="$HOME/.claude/analytics"
HOOKS_DIR="$HOME/.claude/hooks"
SETTINGS_FILE="$HOME/.claude/settings.json"
HEALTH_LOG="$ANALYTICS_DIR/framework-health.jsonl"
FRAMEWORK_PATH_MARKER="$HOME/.claude/.framework-path"

mkdir -p "$ANALYTICS_DIR" 2>/dev/null || true

# -------- Repo resolution --------
REPO=""
if [ -d "$HOME/local-codebase/claude-code-agents/.claude/agents" ]; then
    REPO="$HOME/local-codebase/claude-code-agents"
elif [ -f "$FRAMEWORK_PATH_MARKER" ]; then
    candidate=$(cat "$FRAMEWORK_PATH_MARKER" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$candidate" ] && [ -d "$candidate/.claude/agents" ]; then
        REPO="$candidate"
    fi
fi

if [ -z "$REPO" ]; then
    # No repo available — nothing to reconcile against. Exit clean.
    exit 0
fi

# -------- Utilities --------
_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

_log() {
    # $1 = JSON body (without outer braces)
    local line
    line="{\"ts\":\"$(_ts)\",$1}"
    echo "$line" >> "$HEALTH_LOG" 2>/dev/null || true
}

_sha256() {
    # $1 = file path
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" 2>/dev/null | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
    else
        echo ""
    fi
}

_trigger_heal() {
    # Fork install.sh --update in background, fully detached.
    (
        cd "$REPO" || exit 0
        ./install.sh --update >/dev/null 2>&1
    ) >/dev/null 2>&1 &
    disown 2>/dev/null || true
}

DRIFT_FOUND=0

# -------- Check 1: env keys in settings.json --------
if [ -f "$SETTINGS_FILE" ] && [ -f "$REPO/global-config/settings.json.template" ] && command -v jq >/dev/null 2>&1; then
    while IFS= read -r key; do
        [ -z "$key" ] && continue
        if ! jq -e --arg k "$key" '.env[$k]' "$SETTINGS_FILE" >/dev/null 2>&1; then
            DRIFT_FOUND=1
            _log "\"event\":\"drift_detected\",\"check\":\"env_key\",\"expected\":\"$key\",\"actual\":\"missing\",\"action\":\"trigger_heal\""
        fi
    done < <(jq -r '.env | keys[]' "$REPO/global-config/settings.json.template" 2>/dev/null)
fi

# -------- Check 2: hook script sha256 match --------
if [ -d "$REPO/global-config/hooks" ] && [ -d "$HOOKS_DIR" ]; then
    for src in "$REPO/global-config/hooks"/*.sh; do
        [ -f "$src" ] || continue
        name=$(basename "$src")
        dst="$HOOKS_DIR/$name"
        if [ ! -f "$dst" ]; then
            DRIFT_FOUND=1
            _log "\"event\":\"drift_detected\",\"check\":\"hook_missing\",\"expected\":\"$name\",\"actual\":\"missing\",\"action\":\"trigger_heal\""
            continue
        fi
        src_hash=$(_sha256 "$src")
        dst_hash=$(_sha256 "$dst")
        if [ -n "$src_hash" ] && [ -n "$dst_hash" ] && [ "$src_hash" != "$dst_hash" ]; then
            DRIFT_FOUND=1
            _log "\"event\":\"drift_detected\",\"check\":\"hook_hash\",\"expected\":\"$src_hash\",\"actual\":\"$dst_hash\",\"file\":\"$name\",\"action\":\"trigger_heal\""
        fi
    done
fi

# -------- Check 3: analytics files present --------
for f in collector.py server.py dashboard.html schema.sql; do
    src="$REPO/observability/$f"
    dst="$ANALYTICS_DIR/$f"
    if [ -f "$src" ] && [ ! -f "$dst" ]; then
        DRIFT_FOUND=1
        _log "\"event\":\"drift_detected\",\"check\":\"analytics_missing\",\"expected\":\"$f\",\"actual\":\"missing\",\"action\":\"trigger_heal\""
    fi
done

# -------- Check 4: claude-obs.db exists (warn only) --------
if [ ! -f "$ANALYTICS_DIR/claude-obs.db" ]; then
    _log "\"event\":\"drift_detected\",\"check\":\"db_missing\",\"expected\":\"claude-obs.db\",\"actual\":\"missing\",\"action\":\"deferred_regen\""
    # Don't trigger heal for DB alone — it's regenerable from JSONL.
fi

# -------- Check 5: hook event wiring in settings.json --------
# Catches the class where a hook script is installed on disk but the event
# entry in user settings.json is missing or drifted from template. This is
# what caused SessionStart to stay decorative after sync_hooks "add-if-missing"
# skipped it, and what left stop-phrase-guard.sh disabled.
if [ -f "$SETTINGS_FILE" ] && [ -f "$REPO/global-config/settings.json.template" ] \
   && command -v jq >/dev/null 2>&1; then
    while IFS= read -r event; do
        [ -z "$event" ] && continue
        tmpl_cfg=$(jq -Sc --arg e "$event" '.hooks[$e]' "$REPO/global-config/settings.json.template" 2>/dev/null)
        usr_cfg=$(jq -Sc --arg e "$event" '.hooks[$e] // null' "$SETTINGS_FILE" 2>/dev/null)
        if [ "$tmpl_cfg" != "$usr_cfg" ]; then
            DRIFT_FOUND=1
            _log "\"event\":\"drift_detected\",\"check\":\"hook_wiring\",\"expected_event\":\"$event\",\"actual\":\"drifted_or_missing\",\"action\":\"trigger_heal\""
        fi
    done < <(jq -r '.hooks | keys[]' "$REPO/global-config/settings.json.template" 2>/dev/null)
fi

# -------- Heal if needed --------
if [ "$DRIFT_FOUND" -eq 1 ]; then
    _trigger_heal
else
    # Clean pass — sample 1-in-10 to avoid log spam
    if [ "$((RANDOM % 10))" -eq 0 ]; then
        END_TS_MS=$(perl -MTime::HiRes=time -e 'printf "%d\n", time()*1000' 2>/dev/null || date +%s000)
        DUR=$((END_TS_MS - START_TS_MS))
        _log "\"event\":\"healthcheck_pass\",\"duration_ms\":$DUR"
    fi
fi

exit 0
