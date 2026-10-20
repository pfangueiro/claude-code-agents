#!/bin/bash

# Color theme: gray, orange, blue, teal, green, lavender, rose, gold, slate, cyan
COLOR="cyan"

# Color codes
C_RESET='\033[0m'
C_GRAY='\033[38;5;245m'
C_BAR_EMPTY='\033[38;5;238m'
C_GREEN='\033[38;5;71m'
C_YELLOW='\033[38;5;136m'
C_RED='\033[38;5;167m'
case "$COLOR" in
    orange)   C_ACCENT='\033[38;5;173m' ;;
    blue)     C_ACCENT='\033[38;5;74m' ;;
    teal)     C_ACCENT='\033[38;5;66m' ;;
    green)    C_ACCENT='\033[38;5;71m' ;;
    lavender) C_ACCENT='\033[38;5;139m' ;;
    rose)     C_ACCENT='\033[38;5;132m' ;;
    gold)     C_ACCENT='\033[38;5;136m' ;;
    slate)    C_ACCENT='\033[38;5;60m' ;;
    cyan)     C_ACCENT='\033[38;5;37m' ;;
    *)        C_ACCENT="$C_GRAY" ;;
esac

input=$(cat)

# [FIX 4] Single jq call extracts all fields at once (was 7 separate calls)
# Each field on its own line — handles empty fields cleanly
{
    read -r model
    read -r cwd
    read -r total_cost
    read -r duration_ms
    read -r lines_added
    read -r lines_removed
    read -r pct
    read -r max_context
    read -r transcript_path
    read -r agent_name
} < <(echo "$input" | jq -r '
    (.model.display_name // .model.id // "?"),
    (.cwd // ""),
    (.cost.total_cost_usd // 0 | tostring),
    (.cost.total_duration_ms // 0 | tostring),
    (.cost.total_lines_added // 0 | tostring),
    (.cost.total_lines_removed // 0 | tostring),
    (.context_window.used_percentage // 0 | floor | tostring),
    (.context_window.context_window_size // 200000 | tostring),
    (.transcript_path // ""),
    (.agent.name // "")
')

dir=$(basename "$cwd" 2>/dev/null || echo "?")
cost_display=$(printf '$%.2f' "$total_cost")
lines_display="+${lines_added}-${lines_removed}"

# Duration: format ms into human-readable
duration_s=$((duration_ms / 1000))
if [[ $duration_s -lt 60 ]]; then
    duration_display="${duration_s}s"
elif [[ $duration_s -lt 3600 ]]; then
    duration_display="$((duration_s / 60))m$((duration_s % 60))s"
else
    duration_display="$((duration_s / 3600))h$((duration_s % 3600 / 60))m"
fi

# [FIX 2] Cache git operations (5-second TTL) to avoid running git on every update.
# Scope the cache to session_id so concurrent sessions in different repos don't
# read each other's cached git state (stable within a session, unique across).
session_id=$(echo "$input" | jq -r '.session_id // "nosession"' 2>/dev/null)
GIT_CACHE="/tmp/statusline-git-cache-${session_id}"
GIT_CACHE_TTL=5

git_cache_is_stale() {
    [[ ! -f "$GIT_CACHE" ]] && return 0
    local mtime
    mtime=$(stat -f %m "$GIT_CACHE" 2>/dev/null || stat -c %Y "$GIT_CACHE" 2>/dev/null || echo 0)
    (( $(date +%s) - mtime > GIT_CACHE_TTL ))
}

branch=""
git_status=""
if [[ -n "$cwd" && -d "$cwd" ]]; then
    if git_cache_is_stale; then
        branch_val=$(git -C "$cwd" branch --show-current 2>/dev/null)
        if [[ -n "$branch_val" ]]; then
            # [FIX 1] Removed -uall flag (can cause memory issues on large repos)
            file_count=$(git -C "$cwd" --no-optional-locks status --porcelain 2>/dev/null | wc -l | tr -d ' ')

            # Check sync status with upstream
            sync_status=""
            upstream=$(git -C "$cwd" rev-parse --abbrev-ref @{upstream} 2>/dev/null)
            if [[ -n "$upstream" ]]; then
                fetch_head="$cwd/.git/FETCH_HEAD"
                fetch_ago=""
                if [[ -f "$fetch_head" ]]; then
                    fetch_time=$(stat -f %m "$fetch_head" 2>/dev/null || stat -c %Y "$fetch_head" 2>/dev/null)
                    if [[ -n "$fetch_time" ]]; then
                        now=$(date +%s)
                        diff=$((now - fetch_time))
                        if [[ $diff -lt 60 ]]; then
                            fetch_ago="<1m ago"
                        elif [[ $diff -lt 3600 ]]; then
                            fetch_ago="$((diff / 60))m ago"
                        elif [[ $diff -lt 86400 ]]; then
                            fetch_ago="$((diff / 3600))h ago"
                        else
                            fetch_ago="$((diff / 86400))d ago"
                        fi
                    fi
                fi

                counts=$(git -C "$cwd" rev-list --left-right --count HEAD...@{upstream} 2>/dev/null)
                ahead=$(echo "$counts" | cut -f1)
                behind=$(echo "$counts" | cut -f2)
                if [[ "$ahead" -eq 0 && "$behind" -eq 0 ]]; then
                    if [[ -n "$fetch_ago" ]]; then
                        sync_status="synced ${fetch_ago}"
                    else
                        sync_status="synced"
                    fi
                elif [[ "$ahead" -gt 0 && "$behind" -eq 0 ]]; then
                    sync_status="${ahead} ahead"
                elif [[ "$ahead" -eq 0 && "$behind" -gt 0 ]]; then
                    sync_status="${behind} behind"
                else
                    sync_status="${ahead} ahead, ${behind} behind"
                fi
            else
                sync_status="no upstream"
            fi

            # Build git status string
            if [[ "$file_count" -eq 0 ]]; then
                git_status_val="(0 files uncommitted, ${sync_status})"
            elif [[ "$file_count" -eq 1 ]]; then
                # [FIX 1] Also removed -uall here
                single_file=$(git -C "$cwd" --no-optional-locks status --porcelain 2>/dev/null | head -1 | sed 's/^...//')
                git_status_val="(${single_file} uncommitted, ${sync_status})"
            else
                git_status_val="(${file_count} files uncommitted, ${sync_status})"
            fi

            printf '%s\n%s\n' "$branch_val" "$git_status_val" > "$GIT_CACHE"
        else
            printf '\n\n' > "$GIT_CACHE"
        fi
    fi

    { read -r branch; read -r git_status; } < "$GIT_CACHE"
fi

# [FIX 3] Use used_percentage from JSON instead of parsing transcript
# [FIX 5] Color thresholds: green < 70%, yellow 70-89%, red 90%+
max_k=$((max_context / 1000))
bar_width=10

if [[ $pct -ge 90 ]]; then
    C_BAR="$C_RED"
elif [[ $pct -ge 70 ]]; then
    C_BAR="$C_YELLOW"
else
    C_BAR="$C_GREEN"
fi

[[ $pct -gt 100 ]] && pct=100

bar=""
for ((i=0; i<bar_width; i++)); do
    bar_start=$((i * 10))
    progress=$((pct - bar_start))
    if [[ $progress -ge 8 ]]; then
        bar+="${C_BAR}█${C_RESET}"
    elif [[ $progress -ge 3 ]]; then
        bar+="${C_BAR}▄${C_RESET}"
    else
        bar+="${C_BAR_EMPTY}░${C_RESET}"
    fi
done

ctx="${bar} ${C_GRAY}${pct}% of ${max_k}k tokens"

# ── Framework status ────────────────────────────────────────────────────────
# Cheap, cached (60s) health of the claude-code-agents framework itself — NEVER a
# live validation, Git, or network call in the hot path, only the bounded cache
# and a tail of the diagnostic log. Version comes from ~/.claude/.framework-version;
# the glyph is DERIVED only from the structured records the observe-only
# watchdog/healthcheck already wrote to framework-health.jsonl, plus corruption
# alerts. Emits nothing if the framework isn't installed here, so a plain Claude
# Code user sees no change.
#
# Honest, fail-closed reporting (there is no repair to report):
#   ✓  a RECENT, admitted validation_result from the watchdog's `validate.sh --quick
#      --json` run — status healthy, complete true, exit_code 0, errors 0, with
#      meaningful, internally consistent counts. Here "complete" means that QUICK
#      installed-integrity scope finished (deployed hooks / env / shared-set / hook
#      wiring under ~/.claude); --quick deliberately exits BEFORE the full-only source
#      checks, so ✓ attests the completed watchdog quick installed-integrity scope
#      ONLY — it does NOT certify the default full `validate.sh` repository validator,
#      the project test suites, or CI.
#   ⚠  a current drift / failed validation, a drift from the SessionStart check,
#      or a recent corruption/backup alert
#   ?  default — no admitted evidence yet (version-only), or evidence that is
#      missing / malformed / stale / future / inconsistent
# The LAST-APPENDED relevant record wins (physical JSONL order — the append-only
# log's own write order, read whitespace-tolerantly). A self-reported timestamp only
# QUALIFIES whether the selected record is admissible (fresh / not future); it never
# reorders records, so an invalid/stale/future stamp on the latest record fails closed
# to ? and never lets selection fall back to an earlier green. A scope-qualified
# SessionStart healthcheck_result can downgrade or confirm but never certifies green
# (only an admitted watchdog --quick validation_result can). Retired heal_* records are historical and ignored; an
# unselected watchdog that simply never ran is not "stalled" (absence of evidence is ?,
# not ⚠).
fw_seg=""; fw_ver=""
# Fingerprint the cache by $HOME so two homes sharing one UID (e.g. test sandboxes)
# can never read each other's cached verdict — a /tmp-per-UID cache could leak a
# green from one HOME into another. cksum is POSIX; fall back to a sanitized path.
_fw_home_fp=$(printf '%s' "$HOME" | cksum 2>/dev/null | cut -d' ' -f1)
[[ -z "$_fw_home_fp" ]] && _fw_home_fp=$(printf '%s' "$HOME" | tr -c 'A-Za-z0-9' '_')
FW_CACHE="/tmp/statusline-fw-cache-${UID:-x}-${_fw_home_fp}"
_fw_cache_stale() {
    [[ -f "$FW_CACHE" ]] || return 0
    local m; m=$(stat -f %m "$FW_CACHE" 2>/dev/null || stat -c %Y "$FW_CACHE" 2>/dev/null || echo 0)
    (( $(date +%s) - m > 60 ))
}
# Parse an ISO-8601 Z (UTC) timestamp → epoch. macOS `date -j -f` IGNORES the trailing Z and
# parses in LOCAL time, so `-u` is REQUIRED to read it as UTC — without it the age is off by the
# local UTC offset. GNU `date -d` honors the Z; `-u` is harmless there. Unparseable → 0, which the
# caller treats as "no usable timestamp" (fail-closed), never as fresh.
_iso_epoch() { date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$1" +%s 2>/dev/null || date -u -d "$1" +%s 2>/dev/null || echo 0; }
if _fw_cache_stale; then
    _v=$(grep -m1 '^version=' "$HOME/.claude/.framework-version" 2>/dev/null | cut -d= -f2)
    # Distinguish "on the release" from "N commits past it". `ahead` is computed by
    # install.sh at install time and read from the marker, so this stays out of the
    # hot path (no git call).
    _ahead=$(grep -m1 '^ahead=' "$HOME/.claude/.framework-version" 2>/dev/null | cut -d= -f2)
    if [[ -n "$_v" && "${_ahead:-0}" =~ ^[0-9]+$ && "${_ahead:-0}" -gt 0 ]]; then
        _v="${_v}+${_ahead}"
    fi
    if [[ -n "$_v" ]]; then
        # DEFAULT is unknown: a version marker alone is NOT evidence of health.
        _g="?"; _c="$C_GRAY"; _now=$(date +%s)
        _fresh=9000   # 2.5× the hourly watchdog cadence; older evidence is stale → ?
        _H="$HOME/.claude/analytics/framework-health.jsonl"
        _A="$HOME/.claude/analytics/watchdog-alerts.jsonl"

        # --- Latest watchdog --quick validation_result (the only record that can certify ✓) ---
        # Select the LAST such record by physical append order, matching the event
        # whitespace-tolerantly (compact OR spaced JSON) so a later record is never
        # invisible. grep -n carries the line index as "N:line"; _vr_idx is the index,
        # _vr the content. A recognizable-but-malformed latest line stays the selected
        # candidate (jq fails → unk below); we never scan back to an earlier green.
        _vr_cls="none"; _vr_ts=0; _vr_idx=""
        if [[ -f "$_H" ]]; then
            _vr_hit=$(grep -n -E '"event"[[:space:]]*:[[:space:]]*"validation_result"' "$_H" 2>/dev/null | tail -1)
            if [[ -n "$_vr_hit" ]]; then
                _vr_idx=${_vr_hit%%:*}; _vr=${_vr_hit#*:}
                _vr_cls=$(printf '%s' "$_vr" | jq -r '
                    def _int($x): ($x|type)=="number" and $x>=0 and ($x|floor)==$x and $x<9007199254740992;
                    if (.status=="healthy" and .complete==true and .exit_code==0
                        and _int(.checks) and .checks>0 and _int(.errors) and .errors==0
                        and _int(.warnings) and ((.errors+.warnings)<=.checks)) then "green"
                    elif (.status=="drift" and .complete==true and _int(.errors) and .errors>0) then "drift"
                    else "unk" end' 2>/dev/null)
                [[ -z "$_vr_cls" ]] && _vr_cls="unk"
                _vr_ts=$(_iso_epoch "$(printf '%s' "$_vr" | jq -r '.ts // empty' 2>/dev/null)")
                # stale / future / unparseable timestamp → not usable evidence
                if [[ "${_vr_ts:-0}" -le 0 || "$_vr_ts" -gt "$_now" || $((_now - _vr_ts)) -gt "$_fresh" ]]; then
                    _vr_cls="unk"
                fi
            fi
        fi

        # --- Latest scope-qualified SessionStart healthcheck_result ---
        # Same whitespace-tolerant, line-indexed selection as validation_result above.
        _hc_cls="none"; _hc_ts=0; _hc_idx=""
        if [[ -f "$_H" ]]; then
            _hc_hit=$(grep -n -E '"event"[[:space:]]*:[[:space:]]*"healthcheck_result"' "$_H" 2>/dev/null | tail -1)
            if [[ -n "$_hc_hit" ]]; then
                _hc_idx=${_hc_hit%%:*}; _hc=${_hc_hit#*:}
                case "$(printf '%s' "$_hc" | jq -r '.status // empty' 2>/dev/null)" in
                    healthy) _hc_cls="clean" ;;
                    drift)   _hc_cls="drift" ;;
                    *)       _hc_cls="unk" ;;
                esac
                _hc_ts=$(_iso_epoch "$(printf '%s' "$_hc" | jq -r '.ts // empty' 2>/dev/null)")
                if [[ "${_hc_ts:-0}" -le 0 || "$_hc_ts" -gt "$_now" || $((_now - _hc_ts)) -gt "$_fresh" ]]; then
                    _hc_cls="unk"
                fi
            fi
        fi

        # --- Combine: the record appended LAST (higher line index) governs — NOT the
        #     one with the larger self-reported timestamp. This is what stops a later
        #     unknown/malformed record (epoch 0, or a same-second tie) from losing a
        #     strict `>` and reverting to an earlier green. The timestamp checks above
        #     already demoted any inadmissible selected record to unk, so a bad stamp
        #     fails closed here. Only an admitted watchdog `--quick` validation_result can
        #     go green; a scope (healthcheck) check can only downgrade or confirm an
        #     already-admitted green. ---
        if [[ -n "$_hc_idx" && ( -z "$_vr_idx" || "$_hc_idx" -gt "$_vr_idx" ) ]]; then
            case "$_hc_cls" in
                drift) _g="⚠"; _c="$C_RED" ;;
                clean) if [[ "$_vr_cls" == "green" ]]; then _g="✓"; _c="$C_GREEN"; else _g="?"; _c="$C_GRAY"; fi ;;
                *)     _g="?"; _c="$C_GRAY" ;;
            esac
        elif [[ -n "$_vr_idx" ]]; then
            case "$_vr_cls" in
                green) _g="✓"; _c="$C_GREEN" ;;
                drift) _g="⚠"; _c="$C_RED" ;;
                *)     _g="?"; _c="$C_GRAY" ;;
            esac
        fi

        # --- A recent (within 24h) corruption/backup alert trumps to ⚠. Only the
        #     alerts the current watchdog actually emits are honored (allowlist), so
        #     a retired/legacy record in the log is ignored, never relabeled. ---
        if [[ -f "$_A" ]]; then
            _al=$(tail -1 "$_A" 2>/dev/null)
            if [[ -n "$_al" ]]; then
                case "$(printf '%s' "$_al" | jq -r '.event // empty' 2>/dev/null)" in
                    git_fsck_error|bundle_failed|userconfig_snapshot_failed|memory_snapshot_failed)
                        _ae=$(_iso_epoch "$(printf '%s' "$_al" | jq -r '.ts // empty' 2>/dev/null)")
                        if [[ "${_ae:-0}" -gt 0 && "$_ae" -le "$_now" && $((_now - _ae)) -lt 86400 ]]; then
                            _g="⚠"; _c="$C_RED"
                        fi
                        ;;
                    *) : ;;
                esac
            fi
        fi
        printf '%s\n%s\n' "$_v" "${_c}${_g}${C_RESET}" > "$FW_CACHE"
    else
        printf '\n\n' > "$FW_CACHE"
    fi
fi
{ read -r fw_ver; read -r _fw_glyph; } < "$FW_CACHE" 2>/dev/null
[[ -n "$fw_ver" ]] && fw_seg="${C_GRAY}⚙${fw_ver} ${_fw_glyph}"

# Build output: Model [Agent] | Dir | Branch (uncommitted) | Cost Duration Lines | Context [| Framework]
output="${C_ACCENT}${model}${C_GRAY}"
# [FIX 6] Show active agent name when running a specialized agent
[[ -n "$agent_name" ]] && output+=" [${C_ACCENT}${agent_name}${C_GRAY}]"
output+=" | 📁${dir}"
[[ -n "$branch" ]] && output+=" | 🔀${branch} ${git_status}"
output+=" | 💰${cost_display} ⏱${duration_display} ${C_ACCENT}${lines_display}${C_GRAY} | ${ctx}${C_RESET}"
[[ -n "$fw_seg" ]] && output+=" ${C_GRAY}|${C_RESET} ${fw_seg}${C_RESET}"

printf '%b\n' "$output"

# Line 2: last user message (still reads transcript for this feature only)
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
    plain_output="${model} | 📁${dir}"
    [[ -n "$agent_name" ]] && plain_output+=" [${agent_name}]"
    [[ -n "$branch" ]] && plain_output+=" | 🔀${branch} ${git_status}"
    plain_output+=" | ${cost_display} ${duration_display} ${lines_display} | xxxxxxxxxx ${pct}% of ${max_k}k tokens"
    [[ -n "$fw_ver" ]] && plain_output+=" | O ${fw_ver} o"
    max_len=${#plain_output}
    last_user_msg=$(jq -rs '
        def is_unhelpful:
            startswith("[Request interrupted") or
            startswith("[Request cancelled") or
            . == "";

        [.[] | select(.type == "user") |
         select(.message.content | type == "string" or
                (type == "array" and any(.[]; .type == "text")))] |
        reverse |
        map(.message.content |
            if type == "string" then .
            else [.[] | select(.type == "text") | .text] | join(" ") end |
            gsub("\n"; " ") | gsub("  +"; " ")) |
        map(select(is_unhelpful | not)) |
        first // ""
    ' < "$transcript_path" 2>/dev/null)

    if [[ -n "$last_user_msg" ]]; then
        if [[ ${#last_user_msg} -gt $max_len ]]; then
            echo "💬 ${last_user_msg:0:$((max_len - 3))}..."
        else
            echo "💬 ${last_user_msg}"
        fi
    fi
fi
