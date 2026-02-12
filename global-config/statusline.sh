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

# [FIX 2] Cache git operations (5-second TTL) to avoid running git on every update
GIT_CACHE="/tmp/statusline-git-cache"
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

# Build output: Model [Agent] | Dir | Branch (uncommitted) | Cost Duration Lines | Context
output="${C_ACCENT}${model}${C_GRAY}"
# [FIX 6] Show active agent name when running a specialized agent
[[ -n "$agent_name" ]] && output+=" [${C_ACCENT}${agent_name}${C_GRAY}]"
output+=" | 📁${dir}"
[[ -n "$branch" ]] && output+=" | 🔀${branch} ${git_status}"
output+=" | 💰${cost_display} ⏱${duration_display} ${C_ACCENT}${lines_display}${C_GRAY} | ${ctx}${C_RESET}"

printf '%b\n' "$output"

# Line 2: last user message (still reads transcript for this feature only)
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
    plain_output="${model} | 📁${dir}"
    [[ -n "$agent_name" ]] && plain_output+=" [${agent_name}]"
    [[ -n "$branch" ]] && plain_output+=" | 🔀${branch} ${git_status}"
    plain_output+=" | ${cost_display} ${duration_display} ${lines_display} | xxxxxxxxxx ${pct}% of ${max_k}k tokens"
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
