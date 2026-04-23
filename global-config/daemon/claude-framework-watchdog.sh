#!/usr/bin/env bash
# ============================================================================
# Claude Framework Watchdog — hourly slow-path reconciliation & snapshots
# ============================================================================
# Runs under launchd (StartInterval 3600). Responsibilities:
#   1. Full validation (./validate.sh --quick --json) → framework-health.jsonl
#   2. Repo .git integrity (git fsck) → watchdog-alerts.jsonl on corruption
#   3. Rolling git bundle snapshots (~/.claude/snapshots/) — daily cadence
#   4. User config tarball snapshots (~/.claude/hooks, settings.json) — daily
#   5. Retention: prune snapshots older than 7 days
#
# All stdout/stderr captured to ~/.claude/analytics/watchdog.log by launchd.
# This script soft-fails on every check — never exit non-zero from a check.
# ============================================================================

set -uo pipefail

ANALYTICS_DIR="$HOME/.claude/analytics"
SNAPSHOT_DIR="$HOME/.claude/snapshots"
HEALTH_LOG="$ANALYTICS_DIR/framework-health.jsonl"
ALERT_LOG="$ANALYTICS_DIR/watchdog-alerts.jsonl"
WATCHDOG_LOG="$ANALYTICS_DIR/watchdog.log"
FRAMEWORK_PATH_MARKER="$HOME/.claude/.framework-path"

mkdir -p "$ANALYTICS_DIR" "$SNAPSHOT_DIR" 2>/dev/null || true

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
_stamp() { date +"%Y%m%d-%H%M"; }
_day_stamp() { date +"%Y%m%d"; }

log() {
    # plain log to watchdog.log (stdout is redirected by launchd)
    echo "[$(_ts)] $*"
}

log_jsonl() {
    # $1 = target file, $2 = json body (without outer braces)
    local target="$1"
    local body="$2"
    echo "{\"ts\":\"$(_ts)\",$body}" >> "$target" 2>/dev/null || true
}

# -------- Resolve repo --------
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
    log "watchdog: no repo found — exiting"
    exit 0
fi

log "watchdog: run start (repo=$REPO)"

# -------- Task 1: validate.sh --quick --json --------
if [ -x "$REPO/validate.sh" ]; then
    validate_out=$(cd "$REPO" && ./validate.sh --quick --json 2>&1 || true)
    # Escape for JSONL (truncate if huge)
    validate_snippet=$(printf '%s' "$validate_out" | head -c 4000 | tr '\n' ' ' | sed 's/"/\\"/g')
    log_jsonl "$HEALTH_LOG" "\"event\":\"validate_quick\",\"output\":\"$validate_snippet\""
    log "watchdog: validate.sh --quick --json completed"
else
    log "watchdog: validate.sh not found or not executable"
fi

# -------- Task 2: git fsck --------
if [ -d "$REPO/.git" ] && command -v git >/dev/null 2>&1; then
    fsck_out=$(git -C "$REPO" fsck --no-progress 2>&1 || true)
    if echo "$fsck_out" | grep -qiE 'error|corrupt|missing|bad'; then
        esc=$(printf '%s' "$fsck_out" | head -c 4000 | tr '\n' ' ' | sed 's/"/\\"/g')
        log_jsonl "$ALERT_LOG" "\"event\":\"git_fsck_error\",\"output\":\"$esc\""
        log "watchdog: git fsck reported issues (alerted)"
    else
        log_jsonl "$HEALTH_LOG" "\"event\":\"git_fsck_pass\""
        log "watchdog: git fsck clean"
    fi
fi

# -------- Task 3: rolling git bundle snapshot (daily) --------
latest_bundle=""
if [ -d "$SNAPSHOT_DIR" ]; then
    latest_bundle=$(ls -1t "$SNAPSHOT_DIR"/claude-code-agents-*.bundle 2>/dev/null | head -1 || true)
fi

needs_bundle=1
if [ -n "$latest_bundle" ] && [ -f "$latest_bundle" ]; then
    # file mtime in seconds since epoch
    if command -v stat >/dev/null 2>&1; then
        mtime=$(stat -f %m "$latest_bundle" 2>/dev/null || stat -c %Y "$latest_bundle" 2>/dev/null || echo 0)
        now=$(date +%s)
        age=$((now - mtime))
        if [ "$age" -lt 82800 ]; then  # 23h
            needs_bundle=0
        fi
    fi
fi

if [ "$needs_bundle" -eq 1 ] && command -v git >/dev/null 2>&1; then
    bundle_path="$SNAPSHOT_DIR/claude-code-agents-$(_stamp).bundle"
    if git -C "$REPO" bundle create "$bundle_path" --all >/dev/null 2>&1; then
        log_jsonl "$HEALTH_LOG" "\"event\":\"bundle_created\",\"path\":\"$bundle_path\""
        log "watchdog: created bundle $bundle_path"
    else
        log_jsonl "$ALERT_LOG" "\"event\":\"bundle_failed\",\"path\":\"$bundle_path\""
        log "watchdog: git bundle create FAILED"
    fi
else
    log "watchdog: bundle still fresh (<23h), skipping"
fi

# -------- Task 4: user config tarball (daily) --------
latest_tgz=""
if [ -d "$SNAPSHOT_DIR" ]; then
    latest_tgz=$(ls -1t "$SNAPSHOT_DIR"/userconfig-*.tgz 2>/dev/null | head -1 || true)
fi

needs_tgz=1
if [ -n "$latest_tgz" ] && [ -f "$latest_tgz" ]; then
    if command -v stat >/dev/null 2>&1; then
        mtime=$(stat -f %m "$latest_tgz" 2>/dev/null || stat -c %Y "$latest_tgz" 2>/dev/null || echo 0)
        now=$(date +%s)
        age=$((now - mtime))
        if [ "$age" -lt 82800 ]; then
            needs_tgz=0
        fi
    fi
fi

if [ "$needs_tgz" -eq 1 ]; then
    tgz_path="$SNAPSHOT_DIR/userconfig-$(_day_stamp).tgz"
    # Build list of existing paths to avoid tar errors
    paths=()
    [ -d "$HOME/.claude/hooks" ] && paths+=("$HOME/.claude/hooks")
    [ -f "$HOME/.claude/settings.json" ] && paths+=("$HOME/.claude/settings.json")
    if [ "${#paths[@]}" -gt 0 ]; then
        if tar -czf "$tgz_path" "${paths[@]}" >/dev/null 2>&1; then
            log_jsonl "$HEALTH_LOG" "\"event\":\"userconfig_snapshot\",\"path\":\"$tgz_path\""
            log "watchdog: created tarball $tgz_path"
        else
            log_jsonl "$ALERT_LOG" "\"event\":\"userconfig_snapshot_failed\",\"path\":\"$tgz_path\""
            log "watchdog: tar FAILED"
        fi
    fi
else
    log "watchdog: userconfig tarball still fresh (<23h), skipping"
fi

# -------- Task 5: retention (7 days) --------
if [ -d "$SNAPSHOT_DIR" ]; then
    find "$SNAPSHOT_DIR" -maxdepth 1 -type f \( -name 'claude-code-agents-*.bundle' -o -name 'userconfig-*.tgz' \) -mtime +7 -print -delete 2>/dev/null | while read -r purged; do
        log "watchdog: purged old snapshot $purged"
        log_jsonl "$HEALTH_LOG" "\"event\":\"snapshot_purged\",\"path\":\"$purged\""
    done
fi

log "watchdog: run complete"
exit 0
