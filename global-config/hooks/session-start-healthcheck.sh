#!/usr/bin/env bash
# ============================================================================
# SessionStart Health-Check Hook — observe-only drift reporter
# ============================================================================
# Runs on every Claude Code session start. Inspects deployed state under
# ~/.claude/ against the source-of-truth repo and records a single, honest
# diagnostic result. It NEVER repairs: on drift it reports that explicit
# foreground repair is required (`./install.sh --update`) and nothing is
# forked, spawned or written back. Must exit 0 always — never block session
# start. Hook transport success (exit 0) is NOT health: the real outcome lives
# in the emitted `healthcheck_result` event, never in the exit code.
#
# This is a qualified-scope check (a few drift comparisons), not a full
# `validate.sh` run — the emitted scope says so.
#
# Hot path: <2s. No background work.
#
# Logs:
#   ~/.claude/analytics/framework-health.jsonl
#     - drift_detected     (per finding, action=manual_repair_required)
#     - healthcheck_result (one per run: healthy | drift | unknown)
# ============================================================================

set -uo pipefail

START_TS_MS=$(perl -MTime::HiRes=time -e 'printf "%d\n", time()*1000' 2>/dev/null || date +%s000)

ANALYTICS_DIR="$HOME/.claude/analytics"
HOOKS_DIR="$HOME/.claude/hooks"
SETTINGS_FILE="$HOME/.claude/settings.json"
HEALTH_LOG="$ANALYTICS_DIR/framework-health.jsonl"
FRAMEWORK_PATH_MARKER="$HOME/.claude/.framework-path"

mkdir -p "$ANALYTICS_DIR" 2>/dev/null || true

# -------- Utilities (defined BEFORE repo resolution so an unresolved marker
# still emits one honest terminal result) --------
_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

_log() {
    # $1 = JSON body (without outer braces)
    local line
    line="{\"ts\":\"$(_ts)\",$1}"
    echo "$line" >> "$HEALTH_LOG" 2>/dev/null || true
}

_now_ms() { perl -MTime::HiRes=time -e 'printf "%d\n", time()*1000' 2>/dev/null || date +%s000; }

# -------- Repo resolution --------
# Read the framework source path from the marker written by install.sh — the only
# authoritative source (no hardcoded user-specific paths; this script ships to many
# users). Read ONE line with `IFS= read -r` so an embedded SPACE in a valid checkout
# path is preserved (a prior `tr -d '[:space:]'` silently corrupted such paths and
# then the run vanished with no result at all). The marker is DATA — never eval'd or
# sourced. A missing, empty, unreadable or non-framework marker is UNKNOWN, not silent
# success: emit exactly ONE qualified-scope healthcheck_result(unknown) with checks=0
# and a static reason BEFORE exiting, so an older green is never implied.
REPO=""
candidate=""
if [ -f "$FRAMEWORK_PATH_MARKER" ]; then
    IFS= read -r candidate < "$FRAMEWORK_PATH_MARKER" 2>/dev/null || true
    if [ -n "$candidate" ] && [ -d "$candidate/.claude/agents" ]; then
        REPO="$candidate"
    fi
fi

if [ -z "$REPO" ]; then
    _DUR=$(( $(_now_ms) - START_TS_MS ))
    _log "\"event\":\"healthcheck_result\",\"status\":\"unknown\",\"scope\":\"sessionstart_drift_checks\",\"checks\":0,\"drift\":0,\"reason\":\"framework_path_unresolved\",\"duration_ms\":$_DUR"
    exit 0
fi

# -------- Utilities (cont.) --------
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

# -------- Diagnostic state --------
# DRIFT_FOUND : count of confirmed drift findings (needs explicit repair).
# UNKNOWN     : set when a tool is missing or a read fails so a check could not
#               be completed — the run is then incomplete and must NOT be
#               reported healthy (unknown must never hide behind an older green).
# CHECKS_RUN  : count of comparisons actually performed (a healthy verdict
#               requires at least one real check).
DRIFT_FOUND=0
UNKNOWN=0
UNKNOWN_REASON=""
CHECKS_RUN=0

_note_drift() { DRIFT_FOUND=$((DRIFT_FOUND + 1)); }
_note_unknown() {
    UNKNOWN=1
    [ -z "$UNKNOWN_REASON" ] && UNKNOWN_REASON="$1"
}

# Tool availability gates whether an inspection is complete or merely skipped.
HAVE_JQ=0
command -v jq >/dev/null 2>&1 && HAVE_JQ=1
HAVE_SHA=0
if command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1; then
    HAVE_SHA=1
fi

# -------- Selected optional components (from the install marker) --------
# Each optional component (analytics, notifications, watchdog) is TRI-STATE in the
# marker: enabled → inspect; disabled → deliberate default-off, intentionally skipped
# (its missing hook/wiring is NOT drift); absent / unknown / invalid / duplicate /
# unreadable → UNKNOWN, which must NOT be collapsed to "disabled". An unknown selection
# cannot be inspected and cannot be assumed off, so it qualifies the whole run as unknown
# (never a fresh green) while existing extras are left exactly as they are — never
# activated or recreated here. The marker is parsed as DATA (no eval/source). This mirrors
# install.sh's selection fields so a fresh minimal install is never falsely reported as
# drift just because an optional component was deliberately never selected.
FW_VERSION_MARKER="$HOME/.claude/.framework-version"
_marker_field() {
    # $1 = field name → enabled | disabled | unknown | absent
    local name="$1" line
    [ -f "$FW_VERSION_MARKER" ] || { echo "absent"; return 0; }
    local -a vals=()
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            "${name}="*) vals+=("${line#"${name}="}") ;;
        esac
    done < "$FW_VERSION_MARKER"
    case "${#vals[@]}" in
        0) echo "absent" ;;
        1) case "${vals[0]}" in enabled) echo "enabled" ;; disabled) echo "disabled" ;; *) echo "unknown" ;; esac ;;
        *) echo "unknown" ;;   # duplicate field key → ambiguous → unknown (fail-closed)
    esac
}
# Fold absent/invalid/duplicate/unreadable into unknown → enabled | disabled | unknown.
_component_state() {
    case "$(_marker_field "$1")" in
        enabled)  echo "enabled" ;;
        disabled) echo "disabled" ;;
        *)        echo "unknown" ;;
    esac
}
ANALYTICS_STATE=$(_component_state analytics)
NOTIFICATIONS_STATE=$(_component_state notifications)
WATCHDOG_STATE=$(_component_state watchdog)

# An unknown selection qualifies the run: it can be neither confirmed nor assumed off.
[ "$ANALYTICS_STATE"     = unknown ] && _note_unknown "analytics_selection_unknown"
[ "$NOTIFICATIONS_STATE" = unknown ] && _note_unknown "notifications_selection_unknown"
[ "$WATCHDOG_STATE"      = unknown ] && _note_unknown "watchdog_selection_unknown"

ANALYTICS_ENABLED=0;     [ "$ANALYTICS_STATE" = enabled ]     && ANALYTICS_ENABLED=1
NOTIFICATIONS_ENABLED=0; [ "$NOTIFICATIONS_STATE" = enabled ] && NOTIFICATIONS_ENABLED=1

# Is a hook/event's optional component enabled? core → always 1.
_optional_hook_enabled() {
    case "$1" in
        agent-tracker.sh|session-end.sh) [ "$ANALYTICS_ENABLED" -eq 1 ] ;;
        notify.sh)                       [ "$NOTIFICATIONS_ENABLED" -eq 1 ] ;;
        *)                               return 0 ;;
    esac
}
_optional_event_enabled() {
    case "$1" in
        SubagentStart|SubagentStop|SessionEnd) [ "$ANALYTICS_ENABLED" -eq 1 ] ;;
        Notification)                          [ "$NOTIFICATIONS_ENABLED" -eq 1 ] ;;
        *)                                     return 0 ;;
    esac
}

TEMPLATE="$REPO/global-config/settings.json.template"

# -------- JSON-readability gate (checked ONCE, before any dependent comparison) --------
# A present file must be a PARSEABLE JSON OBJECT before its contents are compared. A
# present-but-malformed/unreadable template or settings file is UNKNOWN — never silently
# read as "no keys / empty" and then counted as a completed, green check (an unreadable
# config must not establish fresh green evidence). Absent files are not "unreadable": the
# per-check logic below treats an absent template as skip and an absent settings as its
# own unknown. Only a COMPLETED comparison increments CHECKS_RUN.
TEMPLATE_OK=0
if [ -f "$TEMPLATE" ] && [ "$HAVE_JQ" -eq 1 ]; then
    if jq -e 'type == "object"' "$TEMPLATE" >/dev/null 2>&1; then
        TEMPLATE_OK=1
    else
        _note_unknown "template_unreadable"
    fi
fi
SETTINGS_OK=0
if [ -f "$SETTINGS_FILE" ] && [ "$HAVE_JQ" -eq 1 ]; then
    if jq -e 'type == "object"' "$SETTINGS_FILE" >/dev/null 2>&1; then
        SETTINGS_OK=1
    else
        _note_unknown "settings_unreadable"
    fi
fi

# -------- Check 1: env keys + effort value in settings.json --------
if [ -f "$TEMPLATE" ]; then
    if [ "$HAVE_JQ" -eq 0 ]; then
        _note_unknown "jq_missing"
    elif [ ! -f "$SETTINGS_FILE" ]; then
        # Template present but settings.json absent — cannot verify settings state.
        _note_unknown "settings_missing"
    elif [ "$TEMPLATE_OK" -eq 1 ] && [ "$SETTINGS_OK" -eq 1 ]; then
        CHECKS_RUN=$((CHECKS_RUN + 1))
        while IFS= read -r key; do
            [ -z "$key" ] && continue
            # CLAUDE_CODE_EFFORT_LEVEL is intentionally OPTIONAL: an absent key is a valid
            # owner/native-default preference, never drift. Its presence is not required; its
            # VALUE (when set) is checked separately below, where absence/empty are accepted.
            [ "$key" = "CLAUDE_CODE_EFFORT_LEVEL" ] && continue
            if ! jq -e --arg k "$key" '.env[$k]' "$SETTINGS_FILE" >/dev/null 2>&1; then
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"env_key\",\"expected\":\"$key\",\"actual\":\"missing\",\"action\":\"manual_repair_required\""
            fi
        done < <(jq -r '.env | keys[]' "$TEMPLATE" 2>/dev/null)

        # CLAUDE_CODE_EFFORT_LEVEL: accept every value the current host documents as a
        # supported env setting — the persistent tiers low|medium|high|xhigh AND max|auto
        # (per code.claude.com/docs/en/model-config). An owner's valid choice is preserved,
        # not healed. Any OTHER value is a manual-repair item; the raw value is NOT echoed
        # into the log (it is arbitrary text and could corrupt the JSON line).
        eff=$(jq -r '.env.CLAUDE_CODE_EFFORT_LEVEL // empty' "$SETTINGS_FILE" 2>/dev/null)
        case "$eff" in
            ""|low|medium|high|xhigh|max|auto) : ;;
            *)
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"effort_value\",\"expected\":\"low|medium|high|xhigh|max|auto\",\"actual\":\"unsupported\",\"action\":\"manual_repair_required\""
                ;;
        esac
    fi
    # template/settings present-but-unreadable is already recorded as unknown above.
fi

# -------- Check 2: hook script sha256 match --------
if [ -d "$REPO/global-config/hooks" ]; then
    if [ "$HAVE_SHA" -eq 1 ] && [ -d "$HOOKS_DIR" ]; then
        for src in "$REPO/global-config/hooks"/*.sh; do
            [ -f "$src" ] || continue
            name=$(basename "$src")
            # Skip an optional-component hook that is not enabled: its absence is a
            # deliberate default-off (or preserved legacy), never drift.
            _optional_hook_enabled "$name" || continue
            CHECKS_RUN=$((CHECKS_RUN + 1))
            dst="$HOOKS_DIR/$name"
            if [ ! -f "$dst" ]; then
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"hook_missing\",\"expected\":\"$name\",\"actual\":\"missing\",\"action\":\"manual_repair_required\""
                continue
            fi
            src_hash=$(_sha256 "$src")
            dst_hash=$(_sha256 "$dst")
            if [ -z "$src_hash" ] || [ -z "$dst_hash" ]; then
                _note_unknown "hook_hash_unreadable"
            elif [ "$src_hash" != "$dst_hash" ]; then
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"hook_hash\",\"expected\":\"$src_hash\",\"actual\":\"$dst_hash\",\"file\":\"$name\",\"action\":\"manual_repair_required\""
            fi
        done
    elif [ "$HAVE_SHA" -eq 0 ]; then
        _note_unknown "sha256_tool_missing"
    else
        # Source hooks exist but no deployed hooks dir — cannot verify.
        _note_unknown "hooks_dir_missing"
    fi
fi

# -------- Check 3: hook event wiring in settings.json --------
# Catches the class where a hook script is installed on disk but the framework's own
# event binding in user settings.json is missing, modified or duplicated.
#
# The installer MERGES rather than wholesale-replaces: it preserves foreign groups and
# foreign sub-entries inside a mixed framework group, appending the framework's own hook
# entry alongside them. So a correctly-merged canonical GROUP is a SUPERSET of the
# template group (it may carry extra foreign sub-entries), and a whole-GROUP equality
# check would falsely convict every preserved owner customization as drift — and, worse,
# miss a second group that re-runs the owned guard while carrying its own foreign
# sub-entry (that group never equals the template group, so the duplicate hides).
# Instead, the canonical unit is the framework's OWN hook ENTRY carried with its group's
# event matcher: {matcher, entry}. The validator (validate.sh) uses this same owned-entry
# MULTISET comparison, and both consumers MUST agree — an independent exact-match count
# (as this once did) silently ignores an ADDITIONAL modified owned entry sitting beside a
# valid one, letting it hide. Build the EXPECTED multiset of owned {matcher, entry} tuples
# from the template, build the ACTUAL multiset of owned tuples in user settings — recognising
# framework ownership by exact canonical command identity (the tilde form the template ships
# OR its $HOME-expanded twin, never a basename look-alike) and PROJECTING OUT foreign
# sub-entries/groups — then compare the sorted multisets, carrying the FULL entry object (so a
# modified type/timeout or an added field is caught, never defaulted away). Reject any
# extra/missing/modified owned tuple even beside a valid one:
#   actual == expected → the owned binding is intact (foreign customizations pass through);
#   |actual| > |expected| → the owned guard is bound more than once (duplicate), even across
#                           mixed groups or via a modified twin hiding beside the valid entry;
#   otherwise → the framework binding is missing or modified out of its canonical shape.
if [ -f "$TEMPLATE" ]; then
    if [ "$TEMPLATE_OK" -eq 1 ] && [ "$SETTINGS_OK" -eq 1 ]; then
        while IFS= read -r event; do
            [ -z "$event" ] && continue
            # Skip an optional-component event that is not enabled: a fresh default
            # install intentionally does not wire it, so a missing entry is not drift.
            _optional_event_enabled "$event" || continue
            CHECKS_RUN=$((CHECKS_RUN + 1))
            tmpl_cfg=$(jq -c --arg e "$event" '.hooks[$e]' "$TEMPLATE" 2>/dev/null)
            usr_cfg=$(jq -c --arg e "$event" '.hooks[$e] // null' "$SETTINGS_FILE" 2>/dev/null)
            wiring=$(jq -rn --argjson tmpl "${tmpl_cfg:-null}" --argjson usr "${usr_cfg:-null}" --arg home "$HOME" '
                ($usr // []) as $u
                | ($tmpl // []) as $t
                | if ($u | type) != "array" then "missing"
                  else
                    # Owned command identity for this event: the template commands plus their
                    # $HOME-expanded twins (the installer may write either spelling).
                    [ $t[] | select(type == "object") | (.hooks // [])[] | .command ] as $tc
                    | ( $tc + ( $tc | map(if (type == "string" and startswith("~")) then ($home + .[1:]) else empty end) ) | unique ) as $owned_cmds
                    # Expected owned multiset: every template sub-entry carried with its group
                    # matcher, as the FULL entry object.
                    | ( [ $t[] | select(type == "object") as $g | ($g.matcher // "") as $m | ($g.hooks // [])[] | {matcher: $m, entry: .} ] | sort ) as $expected
                    # Actual owned multiset from user settings: foreign sub-entries/groups
                    # projected out by command identity (never a basename), and the
                    # $HOME-expanded twin normalised back to the tilde form so it compares.
                    | ( [ $u[] | select(type == "object") as $g | ($g.matcher // "") as $m | ($g.hooks // [])
                          | if type == "array" then .[] else empty end
                          | select(type == "object")
                          | select(.command as $c | any($owned_cmds[]; . == $c))
                          | {matcher: $m, entry: (if (.command | startswith($home)) then (.command = ("~" + (.command[($home | length):]))) else . end)} ] | sort ) as $actual
                    | if $expected == $actual then "ok"
                      elif ($actual | length) > ($expected | length) then "duplicate"
                      else "missing" end
                  end
            ' 2>/dev/null)
            if [ "$wiring" != "ok" ]; then
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"hook_wiring\",\"expected_event\":\"$event\",\"actual\":\"${wiring:-drifted_or_missing}\",\"action\":\"manual_repair_required\""
            fi
        done < <(jq -r '.hooks | keys[]' "$TEMPLATE" 2>/dev/null)
    fi
    # jq missing / settings absent / template or settings unreadable already recorded
    # as unknown by the readability gate and Check 1.
fi

# -------- Check 4: statusLine wiring in settings.json --------
# A CLI settings-sync wholesale-replace can drop .statusLine, killing the bar.
if [ -f "$TEMPLATE" ]; then
    if [ "$TEMPLATE_OK" -eq 1 ] && [ "$SETTINGS_OK" -eq 1 ]; then
        CHECKS_RUN=$((CHECKS_RUN + 1))
        tmpl_sl=$(jq -Sc '.statusLine' "$TEMPLATE" 2>/dev/null)
        usr_sl=$(jq -Sc '.statusLine // null' "$SETTINGS_FILE" 2>/dev/null)
        if [ "$tmpl_sl" != "null" ] && [ "$tmpl_sl" != "$usr_sl" ]; then
            _note_drift
            _log "\"event\":\"drift_detected\",\"check\":\"statusline_wiring\",\"actual\":\"drifted_or_missing\",\"action\":\"manual_repair_required\""
        fi
    fi
fi

# -------- Check 5: shared-set drift (agents/skills/commands/rules) --------
# Compares FRAMEWORK-OWNED files (those the source repo ships) against their
# deployed copies under ~/.claude. Only names present in the source repo are
# inspected, so the user's PERSONAL skills/agents/commands/rules (not in source)
# are never touched. Budget-safe: hashes ~60 small files.
_shared_set_drift() {
    # $1 = source dir, $2 = deployed dir, $3 = mode ("flat" *.md | "skill" */SKILL.md)
    local sdir="$1" ddir="$2" mode="$3" dirlabel
    dirlabel=$(basename "$ddir")
    [ -d "$sdir" ] || return 0

    if [ "$mode" = "skill" ]; then
        local sub nm ssrc ddst sh1 sh2
        for sub in "$sdir"/*/; do
            [ -d "$sub" ] || continue
            nm=$(basename "$sub")
            [ "${nm#._}" != "$nm" ] && continue
            ssrc="$sub/SKILL.md"
            ddst="$ddir/$nm/SKILL.md"
            [ -f "$ssrc" ] || continue
            CHECKS_RUN=$((CHECKS_RUN + 1))
            if [ ! -f "$ddst" ]; then
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"shared_set\",\"dir\":\"skills\",\"file\":\"$nm\",\"actual\":\"missing\",\"action\":\"manual_repair_required\""
                continue
            fi
            sh1=$(_sha256 "$ssrc"); sh2=$(_sha256 "$ddst")
            if [ -z "$sh1" ] || [ -z "$sh2" ]; then
                _note_unknown "shared_set_hash_unreadable"
            elif [ "$sh1" != "$sh2" ]; then
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"shared_set\",\"dir\":\"skills\",\"file\":\"$nm\",\"actual\":\"hash_mismatch\",\"action\":\"manual_repair_required\""
            fi
        done
    else
        local ssrc nm ddst sh1 sh2
        for ssrc in "$sdir"/*.md; do
            [ -f "$ssrc" ] || continue
            nm=$(basename "$ssrc")
            [ "${nm#._}" != "$nm" ] && continue
            ddst="$ddir/$nm"
            CHECKS_RUN=$((CHECKS_RUN + 1))
            if [ ! -f "$ddst" ]; then
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"shared_set\",\"dir\":\"$dirlabel\",\"file\":\"$nm\",\"actual\":\"missing\",\"action\":\"manual_repair_required\""
                continue
            fi
            sh1=$(_sha256 "$ssrc"); sh2=$(_sha256 "$ddst")
            if [ -z "$sh1" ] || [ -z "$sh2" ]; then
                _note_unknown "shared_set_hash_unreadable"
            elif [ "$sh1" != "$sh2" ]; then
                _note_drift
                _log "\"event\":\"drift_detected\",\"check\":\"shared_set\",\"dir\":\"$dirlabel\",\"file\":\"$nm\",\"actual\":\"hash_mismatch\",\"action\":\"manual_repair_required\""
            fi
        done
    fi
}

if [ -d "$REPO/.claude" ]; then
    if [ "$HAVE_SHA" -eq 1 ]; then
        _shared_set_drift "$REPO/.claude/agents"   "$HOME/.claude/agents"   flat
        _shared_set_drift "$REPO/.claude/rules"    "$HOME/.claude/rules"    flat
        _shared_set_drift "$REPO/.claude/commands" "$HOME/.claude/commands" flat
        _shared_set_drift "$REPO/.claude/skills"   "$HOME/.claude/skills"   skill
    else
        _note_unknown "sha256_tool_missing"
    fi
fi

# -------- Check 6: selected OPTIONAL-component payloads present/readable --------
# When a component is clearly ENABLED, a missing required payload is real drift (an
# explicitly selected feature losing its payload must be detected). These are EXISTENCE
# + READABILITY checks only — never a byte/hash claim: the owner may have customized an
# asset, and a shared basename is not proof the framework owns the bytes, so a preserved
# custom copy can never become an unfixable drift. Disabled → skipped (valid absence);
# unknown selection already qualified the run above. The collector is never invoked.
if [ "$ANALYTICS_ENABLED" -eq 1 ] && [ -d "$REPO/observability" ]; then
    for asset in collector.py server.py dashboard.html schema.sql; do
        [ -f "$REPO/observability/$asset" ] || continue   # only inspect assets the source ships
        dst="$HOME/.claude/analytics/$asset"
        CHECKS_RUN=$((CHECKS_RUN + 1))
        if [ ! -e "$dst" ]; then
            _note_drift
            _log "\"event\":\"drift_detected\",\"check\":\"analytics_asset\",\"expected\":\"$asset\",\"actual\":\"missing\",\"action\":\"manual_repair_required\""
        elif [ ! -r "$dst" ]; then
            _note_unknown "analytics_asset_unreadable"
        fi
    done
fi

# Watchdog payload is platform-specific: the launchd daemon is macOS-only. On macOS an
# enabled-but-missing daemon script is drift; off macOS it is legitimately NOT AVAILABLE
# (never installed), which is neither drift nor unknown — an honest not-applicable, never
# a permanent failure. Nothing is created, loaded or scheduled here.
if [ "$WATCHDOG_STATE" = enabled ]; then
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
        dst="$HOME/.claude/daemon/claude-framework-watchdog.sh"
        CHECKS_RUN=$((CHECKS_RUN + 1))
        if [ ! -e "$dst" ]; then
            _note_drift
            _log "\"event\":\"drift_detected\",\"check\":\"watchdog_asset\",\"expected\":\"claude-framework-watchdog.sh\",\"actual\":\"missing\",\"action\":\"manual_repair_required\""
        elif [ ! -r "$dst" ]; then
            _note_unknown "watchdog_asset_unreadable"
        fi
    fi
fi

# -------- Terminal result: one honest verdict per run --------
# Precedence: confirmed drift > incomplete (unknown) > healthy. A healthy
# verdict requires at least one completed check. NEVER heal — drift means the
# user must run an explicit `./install.sh --update`; this hook does not.
END_TS_MS=$(perl -MTime::HiRes=time -e 'printf "%d\n", time()*1000' 2>/dev/null || date +%s000)
DUR=$((END_TS_MS - START_TS_MS))

if [ "$DRIFT_FOUND" -gt 0 ]; then
    STATUS="drift"
    REASON="manual_repair_required"
elif [ "$UNKNOWN" -eq 1 ]; then
    STATUS="unknown"
    REASON="$UNKNOWN_REASON"
elif [ "$CHECKS_RUN" -eq 0 ]; then
    STATUS="unknown"
    REASON="no_checks_run"
else
    STATUS="healthy"
    REASON="ok"
fi

_log "\"event\":\"healthcheck_result\",\"status\":\"$STATUS\",\"scope\":\"sessionstart_drift_checks\",\"checks\":$CHECKS_RUN,\"drift\":$DRIFT_FOUND,\"reason\":\"$REASON\",\"duration_ms\":$DUR"

exit 0
