#!/usr/bin/env bash
# ============================================================================
# Claude Framework Watchdog — hourly slow-path reconciliation & snapshots
# ============================================================================
# Runs under launchd (StartInterval 3600). OBSERVE-ONLY for framework state —
# it reports health and keeps backups; it does NOT repair, migrate, reseed or
# run the analytics collector. Drift is reported for an explicit foreground
# `./install.sh --update` by the owner. Responsibilities:
#   1. Strict validation admission (./validate.sh --quick --json, no --heal) →
#      one `validation_result` event in framework-health.jsonl
#   2. Repo .git integrity (git fsck) → watchdog-alerts.jsonl on corruption
#   3. Rolling git bundle snapshots (~/.claude/snapshots/) — daily cadence
#   4. User config tarball snapshots (~/.claude/hooks, settings.json) — daily
#   4b. Project-memory tarball (~/.claude/projects/*/memory) — daily, separate
#       archive, relative paths, verified-before-promote, keep-floor retention
#   5. Retention: prune snapshots older than 7 days
#
# All stdout/stderr captured to ~/.claude/analytics/watchdog.log by launchd.
# This script soft-fails on every check — never exit non-zero from a check.
# A nonblocking exit 0 is NOT a health signal: the real validation outcome is
# retained in the emitted `validation_result` event, never in the exit code.
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

trim_jsonl() {
    # $1 = jsonl file, $2 = max lines to keep. Bounds unbounded append-only diagnostic logs
    # (framework-health.jsonl grows ~50 lines/day). Atomic: tail to temp, verify non-empty, mv.
    local f="$1" cap="$2" n tmp
    [ -f "$f" ] || return 0
    n=$(wc -l < "$f" 2>/dev/null | tr -d ' ')
    [ -n "$n" ] && [ "$n" -gt "$cap" ] 2>/dev/null || return 0
    tmp="$f.trim.$$"
    if tail -n "$cap" "$f" > "$tmp" 2>/dev/null && [ -s "$tmp" ]; then
        mv "$tmp" "$f" 2>/dev/null && log "watchdog: trimmed $(basename "$f") $n → $cap lines"
    else
        rm -f "$tmp" 2>/dev/null
    fi
}

# The health verdict emitter is defined HERE — before repo resolution — so an
# unresolved marker can still record exactly one terminal `validation_result`
# instead of exiting silently (a silent exit leaves prior success unqualified
# for downstream consumers).
_emit_validation_result() {
    # $1 status, $2 exit_code (integer or the literal null), $3 reason,
    # $4 checks, $5 errors, $6 warnings (counts empty when unavailable)
    local status="$1" ec="$2" reason="$3" c="${4:-}" e="${5:-}" w="${6:-}"
    # `complete` is a typed boolean the statusline requires true before it shows a
    # green glyph. It is derived from the terminal status: a healthy or drift verdict
    # means the predeclared scope completed; every unknown (malformed/interrupted/
    # ambiguous/incomplete) outcome is complete:false — it is NEVER coerced to true.
    local complete="false"
    case "$status" in healthy|drift) complete="true" ;; esac
    local body
    body="\"event\":\"validation_result\",\"source\":\"watchdog\",\"status\":\"$status\",\"exit_code\":$ec,\"reason\":\"$reason\",\"complete\":$complete"
    # Attach the numeric summary only when all three were admitted as integers.
    if [ -n "$c" ] && [ -n "$e" ] && [ -n "$w" ]; then
        body="$body,\"checks\":$c,\"errors\":$e,\"warnings\":$w"
    fi
    log_jsonl "$HEALTH_LOG" "$body"
    log "watchdog: validation_result status=$status exit_code=$ec reason=$reason complete=$complete"
}

# -------- Resolve repo --------
# Read the framework source path from the marker written by install.sh. No
# hardcoded user-specific paths (this script is distributed to multiple users).
# The path is read with `IFS= read -r` so embedded spaces are preserved — a
# `tr -d '[:space:]'` corrupts any valid path containing a space. The marker
# content is only ever TESTED as a directory; it is never eval'd or sourced.
REPO=""
repo_reason=""
if [ ! -e "$FRAMEWORK_PATH_MARKER" ]; then
    repo_reason="framework_path_marker_missing"
elif [ ! -r "$FRAMEWORK_PATH_MARKER" ]; then
    repo_reason="framework_path_unreadable"
else
    candidate=""
    IFS= read -r candidate < "$FRAMEWORK_PATH_MARKER" 2>/dev/null || true
    candidate="${candidate%$'\r'}"   # tolerate a CRLF marker; keep inner spaces
    if [ -z "$candidate" ]; then
        repo_reason="framework_path_empty"
    elif [ -d "$candidate/.claude/agents" ]; then
        REPO="$candidate"
    else
        repo_reason="framework_path_invalid"
    fi
fi

if [ -z "$REPO" ]; then
    # Unresolved source: record one terminal UNKNOWN (exit_code null, no counts,
    # qualified static reason) so downstream consumers never read stale success.
    _emit_validation_result unknown null "$repo_reason" "" "" ""
    log "watchdog: repo unresolved ($repo_reason) — recorded unknown, exiting"
    exit 0
fi

log "watchdog: run start (repo=$REPO)"

# -------- Task 1: strict validation admission (NO automatic repair) --------
# The watchdog OBSERVES and reports; it does NOT repair. Earlier revisions ran
# `install.sh --update` on drift (and a per-cycle `--migrate-legacy`). Both are
# removed: a detached installer is a broad background write with wide blast
# radius, and admitting "0 errors" from erased/malformed validator output hid
# real failures. Drift is now surfaced for an explicit foreground
# `./install.sh --update` by the owner — never launched here. A legacy
# `.framework-autonomy` marker does NOT re-grant background mutation.
#
# Admission rules: run validate.sh WITHOUT --heal, capture stdout and stderr
# SEPARATELY, and preserve the real exit code (no `|| true` erasing it). A
# health verdict is admitted only from a single, well-formed JSON summary whose
# checks/errors/warnings are nonnegative integers below 2^53, whose checks count
# is nonzero (a real run happened), whose totals are internally consistent
# (errors + warnings <= checks), and whose DOCUMENTED exit code (0 clean,
# 1 errors) agrees with the error count. Everything else — malformed/noisy/
# multiple JSON, missing jq or validator, impossible totals, a signal or any
# other exit code (interrupted/faulted run), rc/result disagreement — is UNKNOWN
# and is NEVER coerced to 0 errors or admitted as a completed drift/healthy check.

_admit_validation() {
    # $1 = real exit code, $2 = captured stdout
    local rc="$1" out="$2"
    local arrlen vtype counts checks errors warnings comp

    if ! command -v jq >/dev/null 2>&1; then
        _emit_validation_result unknown "$rc" "jq_missing" "" "" ""
        return
    fi
    if [ -z "$(printf '%s' "$out" | tr -d '[:space:]')" ]; then
        _emit_validation_result unknown "$rc" "empty_output" "" "" ""
        return
    fi
    # Exactly one top-level JSON value. jq -s slurps whitespace-separated values
    # and fails outright on any non-JSON (noisy) content, so a leading log line,
    # trailing garbage or a second object all land here as UNKNOWN.
    arrlen=$(printf '%s' "$out" | jq -s 'length' 2>/dev/null)
    if [ "$arrlen" != "1" ]; then
        _emit_validation_result unknown "$rc" "not_single_json_object" "" "" ""
        return
    fi
    # arrlen==1 proved exactly one top-level value, so the single object reads as
    # `.` without slurping (no `.[0]` indexing, which would error on an object).
    vtype=$(printf '%s' "$out" | jq -r 'type' 2>/dev/null)
    if [ "$vtype" != "object" ]; then
        _emit_validation_result unknown "$rc" "json_not_object" "" "" ""
        return
    fi
    # Extract all three counts in ONE jq pass. jq performs every numeric test so
    # bash never does arithmetic on an untrusted value: each count must be a
    # nonnegative integer BELOW 2^53 (exactly representable as a double AND safely
    # within bash's signed-64-bit range — this also rejects Infinity/NaN and any
    # scientific/float rendering that would break `[ ]` arithmetic). Any failure
    # yields empty output -> rejected as invalid.
    counts=$(printf '%s' "$out" | jq -r '
        def _ok($x): ($x|type)=="number" and $x>=0 and ($x|floor)==$x and $x<9007199254740992;
        if _ok(.checks) and _ok(.errors) and _ok(.warnings)
        then "\(.checks) \(.errors) \(.warnings)" else empty end' 2>/dev/null)
    if [ -z "$counts" ]; then
        _emit_validation_result unknown "$rc" "invalid_or_missing_counts" "" "" ""
        return
    fi
    read -r checks errors warnings <<<"$counts"
    # Optional `complete` flag from the validator summary (additive, backward
    # compatible). A legacy summary WITHOUT the field is treated as complete
    # (compat=true); a present value MUST be a boolean. Resolves to exactly one of
    # absent | true | false | invalid; an empty read is treated as invalid (fail
    # closed), since the object already parsed for its counts.
    comp=$(printf '%s' "$out" | jq -r '
        if (has("complete")|not) then "absent"
        elif (.complete|type)=="boolean" then (.complete|tostring)
        else "invalid" end' 2>/dev/null)
    [ -z "$comp" ] && comp="invalid"
    if [ "$checks" -le 0 ]; then
        # No meaningful check actually ran — cannot certify health.
        _emit_validation_result unknown "$rc" "zero_checks" "$checks" "$errors" "$warnings"
        return
    fi
    # The real validator counts every WARN and ERROR as a CHECK, so a well-formed
    # summary always satisfies errors + warnings <= checks. A total that exceeds
    # the check count is internally impossible (corrupt/foreign output) and is
    # never admitted as health or drift evidence. Both operands are < 2^53, so
    # the sum stays well inside int64 — no shell overflow.
    if [ "$((errors + warnings))" -gt "$checks" ]; then
        _emit_validation_result unknown "$rc" "inconsistent_counts" "$checks" "$errors" "$warnings"
        return
    fi
    # The `complete` flag is admitted here, with the real rc/counts preserved: an
    # invalid (non-boolean) type is corrupt output, and an explicit false means the
    # validator could not finish its scope. Either is UNKNOWN — never healthy/drift —
    # so a partial or malformed run cannot be laundered into a verdict. absent/true
    # fall through to the normal rc/errors decision below.
    if [ "$comp" = "invalid" ]; then
        _emit_validation_result unknown "$rc" "invalid_complete" "$checks" "$errors" "$warnings"
        return
    fi
    if [ "$comp" = "false" ]; then
        _emit_validation_result unknown "$rc" "validator_incomplete" "$checks" "$errors" "$warnings"
        return
    fi
    # Only the validator's DOCUMENTED exits are admissible evidence: 0 = clean,
    # 1 = errors found. A signal (rc >= 128) or any other code means the run was
    # interrupted or faulted — UNKNOWN, never a completed drift/healthy verdict,
    # even when the captured stdout happened to look like a valid summary.
    if [ "$rc" -eq 0 ] && [ "$errors" -eq 0 ]; then
        _emit_validation_result healthy "$rc" "ok" "$checks" "$errors" "$warnings"
    elif [ "$rc" -eq 1 ] && [ "$errors" -gt 0 ]; then
        _emit_validation_result drift "$rc" "validation_errors" "$checks" "$errors" "$warnings"
    elif [ "$rc" -eq 0 ] || [ "$rc" -eq 1 ]; then
        _emit_validation_result unknown "$rc" "rc_result_disagreement" "$checks" "$errors" "$warnings"
    elif [ "$rc" -ge 128 ]; then
        _emit_validation_result unknown "$rc" "validator_signaled" "$checks" "$errors" "$warnings"
    else
        _emit_validation_result unknown "$rc" "unexpected_exit_code" "$checks" "$errors" "$warnings"
    fi
}

if [ -x "$REPO/validate.sh" ]; then
    verr_tmp="$ANALYTICS_DIR/.validate-stderr.$$"
    v_out=$(cd "$REPO" && ./validate.sh --quick --json 2>"$verr_tmp")
    v_rc=$?
    # Bounded diagnostics (framework metadata only; no credential/transcript
    # content). Byte-bound first, then JSON-encode the raw strings with `jq -cn
    # --arg` so arbitrary bytes — backslashes, quotes, newlines, control chars —
    # can NEVER produce a malformed JSONL line. The predecessor hand-escaped only
    # quotes/newlines and corrupted the line on any other backslash (BH-05).
    v_out_snippet=$(printf '%s' "$v_out" | head -c 4000)
    v_err_snippet=$(head -c 2000 "$verr_tmp" 2>/dev/null)
    rm -f "$verr_tmp" 2>/dev/null || true
    if command -v jq >/dev/null 2>&1; then
        vq_line=$(jq -cn \
            --arg ts "$(_ts)" \
            --argjson ec "$v_rc" \
            --arg out "$v_out_snippet" \
            --arg err "$v_err_snippet" \
            '{ts:$ts,event:"validate_quick",exit_code:$ec,stdout:$out,stderr:$err}' \
            2>/dev/null)
        # Append only a well-formed encoder result — never a raw/partial line.
        [ -n "$vq_line" ] && printf '%s\n' "$vq_line" >> "$HEALTH_LOG" 2>/dev/null
    else
        # jq unavailable: emit TYPED numeric metadata only, never raw unescaped
        # diagnostic text (which could itself break the JSONL line).
        log_jsonl "$HEALTH_LOG" "\"event\":\"validate_quick\",\"exit_code\":$v_rc,\"stdout_bytes\":${#v_out_snippet},\"stderr_bytes\":${#v_err_snippet}"
    fi
    log "watchdog: validate.sh --quick --json completed (rc=$v_rc)"
    _admit_validation "$v_rc" "$v_out"
else
    _emit_validation_result unknown null "validator_absent" "" "" ""
    log "watchdog: validate.sh not found or not executable — validation unknown"
fi

# -------- Task 2: git fsck --------
# Filter benign noise (reflog residue, dangling commits, refs/ chatter) and
# only alert on real object-level corruption. Two-stage:
#   1. grep -vE drops known-benign lines
#   2. grep -qE on what remains matches real corruption signatures
if [ -d "$REPO/.git" ] && command -v git >/dev/null 2>&1; then
    fsck_raw=$(git -C "$REPO" fsck --no-progress 2>&1 || true)
    fsck_filtered=$(printf '%s\n' "$fsck_raw" | grep -vE \
        -e 'invalid reflog entry' \
        -e '^error: refs/' \
        -e '^dangling ' \
        -e '^notice:' \
        -e '^Checking ' \
        -e '^$' \
        || true)
    if printf '%s\n' "$fsck_filtered" | grep -qE \
        -e '^error: (object|tree|blob|commit):' \
        -e 'missing (blob|tree|commit)' \
        -e '^error:.*corrupt' \
        -e 'bad (object|tree|blob|commit|link)' ; then
        esc=$(printf '%s' "$fsck_filtered" | head -c 4000 | tr '\n' ' ' | sed 's/"/\\"/g')
        log_jsonl "$ALERT_LOG" "\"event\":\"git_fsck_error\",\"output\":\"$esc\""
        log "watchdog: git fsck reported real corruption (alerted)"
    else
        log_jsonl "$HEALTH_LOG" "\"event\":\"git_fsck_pass\""
        log "watchdog: git fsck clean (benign reflog/dangling lines filtered out)"
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

# -------- Task 4b: project-memory tarball (daily) --------
# Persistent memory lives in ~/.claude/projects/<slug>/memory/*.md and is NOT in
# the userconfig tarball. Back it up as a SEPARATE archive with RELATIVE paths
# (rooted at ~/.claude) so a restore writes only under projects/*/memory and can
# never clobber live settings.json/hooks. The projects/ parent holds ~100s of MB
# of JSONL session logs — the shallow glob projects/*/memory excludes it.
latest_mem=""
if [ -d "$SNAPSHOT_DIR" ]; then
    latest_mem=$(ls -1t "$SNAPSHOT_DIR"/memory-*.tgz 2>/dev/null | grep -v '/memory-latest\.tgz$' | head -1 || true)
fi

needs_mem=1
if [ -n "$latest_mem" ] && [ -f "$latest_mem" ]; then
    if command -v stat >/dev/null 2>&1; then
        mtime=$(stat -f %m "$latest_mem" 2>/dev/null || stat -c %Y "$latest_mem" 2>/dev/null || echo 0)
        now=$(date +%s)
        age=$((now - mtime))
        [ "$age" -lt 82800 ] && needs_mem=0
    fi
fi

if [ "$needs_mem" -eq 1 ] && [ -d "$HOME/.claude/projects" ]; then
    # Collect only real memory dirs as ~/.claude-relative paths; skip symlinks.
    # No nullglob (bash 3.2): an unmatched glob stays literal and fails [ -d ].
    mem_paths=()
    for d in "$HOME"/.claude/projects/*/memory; do
        [ -d "$d" ] || continue
        [ -L "$d" ] && continue
        mem_paths+=("${d#$HOME/.claude/}")
    done

    if [ "${#mem_paths[@]}" -gt 0 ]; then
        mem_path="$SNAPSHOT_DIR/memory-$(_day_stamp).tgz"
        mem_tmp="$mem_path.tmp.$$"
        mrc=0
        tar -czf "$mem_tmp" -C "$HOME/.claude" "${mem_paths[@]}" >/dev/null 2>&1 || mrc=$?
        # Promote only a verified, non-empty archive (atomic mv); else keep prior.
        if [ "$mrc" -ne 2 ] && [ -s "$mem_tmp" ] && tar -tzf "$mem_tmp" 2>/dev/null | grep -q '\.md$'; then
            if mv -f "$mem_tmp" "$mem_path" 2>/dev/null; then
                ln -sf "$(basename "$mem_path")" "$SNAPSHOT_DIR/memory-latest.tgz" 2>/dev/null || true
                mcount=$(tar -tzf "$mem_path" 2>/dev/null | grep -c '\.md$')
                log "watchdog: created memory snapshot $mem_path ($mcount md files)"
                log_jsonl "$HEALTH_LOG" "\"event\":\"memory_snapshot\",\"path\":\"$mem_path\",\"md_files\":$mcount"
            fi
        else
            rm -f "$mem_tmp"
            log_jsonl "$ALERT_LOG" "\"event\":\"memory_snapshot_failed\",\"path\":\"$mem_path\""
            log "watchdog: memory snapshot FAILED (kept prior good copy)"
        fi
    fi
elif [ "$needs_mem" -eq 0 ]; then
    log "watchdog: memory tarball still fresh (<23h), skipping"
fi

# -------- Task 4c: memory snapshot retention (7 days, keep-floor 3) --------
# Pure age-prune would delete the last copy after a >7d backup outage. Always
# keep the newest 3 memory snapshots regardless of age; age-prune only beyond.
if [ -d "$SNAPSHOT_DIR" ]; then
    mem_keep_min=3
    mem_idx=0
    for f in $(ls -1t "$SNAPSHOT_DIR"/memory-*.tgz 2>/dev/null | grep -v '/memory-latest\.tgz$'); do
        mem_idx=$((mem_idx + 1))
        [ "$mem_idx" -le "$mem_keep_min" ] && continue
        if find "$f" -mtime +7 -print 2>/dev/null | grep -q .; then
            rm -f "$f" 2>/dev/null && log "watchdog: purged old memory snapshot $f"
        fi
    done
fi

# -------- Task 5: retention (7 days) --------
if [ -d "$SNAPSHOT_DIR" ]; then
    find "$SNAPSHOT_DIR" -maxdepth 1 -type f \( -name 'claude-code-agents-*.bundle' -o -name 'userconfig-*.tgz' \) -mtime +7 -print -delete 2>/dev/null | while read -r purged; do
        log "watchdog: purged old snapshot $purged"
        log_jsonl "$HEALTH_LOG" "\"event\":\"snapshot_purged\",\"path\":\"$purged\""
    done
fi

# -------- Task 6: (removed) analytics DB regeneration --------
# The watchdog no longer runs the observability collector. Regenerating
# claude-obs.db means POSTing session history to the collector — an analytics
# action, not a framework-health diagnostic. Analytics is an explicit, owner
# invoked opt-in; coupling it to the hourly watchdog is a background write the
# owner never authorized here. Missing DB is left for explicit owner action.

# -------- Task 7: cap append-only diagnostic logs (the statusline only tail-reads them and
# nothing ingests them into a DB, so old lines are disposable). Runs every cycle, atomic.
trim_jsonl "$HEALTH_LOG" 1000
trim_jsonl "$ALERT_LOG" 500

log "watchdog: run complete"
exit 0
