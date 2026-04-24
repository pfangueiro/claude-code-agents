#!/usr/bin/env bash
# ============================================================================
# deploy-all.sh — Drive install.sh across every ~/local-codebase/* project
# ============================================================================
# Per-project rule:
#   - has .claude/agents/  → install.sh --update
#   - missing .claude/agents/ → install.sh --full
#
# Flags:
#   --dry-run            Show commands, perform no writes.
#   --continue-on-error  On a project failure, log and continue (default: ON).
#   --halt-on-error      Opposite of --continue-on-error: abort on first failure.
#   --only <name>        Restrict to a single project by basename.
#   --help               Usage.
#
# Every invocation writes:
#   ~/.claude/snapshots/project-<name>-pre-<ts>.tgz   (per project, before install)
#   ~/.claude/analytics/deploy-manifest-<ts>.jsonl    (one line per project)
#
# Exit 0 if every project succeeded; 1 if any failed (even with continue-on-error).
# ============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SH="${SCRIPT_DIR}/install.sh"
BASE_DIR="${LOCAL_CODEBASE_DIR:-$HOME/local-codebase}"
SNAPSHOT_DIR="$HOME/.claude/snapshots"
ANALYTICS_DIR="$HOME/.claude/analytics"
RUN_TS="$(date +%Y%m%d-%H%M%S)"
MANIFEST="$ANALYTICS_DIR/deploy-manifest-${RUN_TS}.jsonl"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

DRY_RUN=0
CONTINUE_ON_ERROR=1
ONLY=""

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Deploy the Claude Agents framework to every project in $BASE_DIR.

Options:
  --dry-run            Print commands, perform no writes.
  --continue-on-error  Continue on per-project failure (default).
  --halt-on-error      Abort on the first project failure.
  --only <name>        Restrict to a single project by basename.
  --help               Show this help.

Exit status: 0 if all projects succeeded; 1 otherwise.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --continue-on-error) CONTINUE_ON_ERROR=1 ;;
        --halt-on-error) CONTINUE_ON_ERROR=0 ;;
        --only)
            shift
            if [ $# -eq 0 ]; then
                echo "error: --only requires a project basename" >&2
                exit 2
            fi
            ONLY="$1"
            ;;
        --help|-h) usage; exit 0 ;;
        *)
            echo "error: unknown flag: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [ ! -x "$INSTALL_SH" ]; then
    echo "error: install.sh not found or not executable at $INSTALL_SH" >&2
    exit 2
fi

if [ ! -d "$BASE_DIR" ]; then
    echo "error: base dir $BASE_DIR not found" >&2
    exit 2
fi

log() { echo -e "$*"; }

# In dry-run we still produce the manifest path in output but do not create files.
if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$SNAPSHOT_DIR" "$ANALYTICS_DIR"
    : > "$MANIFEST"
fi

_json_escape() {
    # Minimal escape for JSONL body values.
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n' ' '
}

record_manifest() {
    # $1 project $2 mode $3 outcome $4 duration_ms $5 error
    local body
    body=$(printf '{"ts":"%s","project":"%s","mode":"%s","outcome":"%s","duration_ms":%s,"error":"%s"}' \
        "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        "$(_json_escape "$1")" \
        "$2" \
        "$3" \
        "$4" \
        "$(_json_escape "$5")")
    if [ "$DRY_RUN" -eq 0 ]; then
        echo "$body" >> "$MANIFEST"
    fi
}

# Enumerate candidate project dirs
projects=()
while IFS= read -r -d '' dir; do
    local_name=$(basename "$dir")
    case "$local_name" in
        claude-code|claude-code-agents) continue ;;
        .claude) continue ;;  # shared settings dir, not a project
    esac
    if [ -n "$ONLY" ] && [ "$local_name" != "$ONLY" ]; then
        continue
    fi
    projects+=("$dir")
done < <(find "$BASE_DIR" -maxdepth 1 -mindepth 1 -type d -print0 | LC_ALL=C sort -z)

if [ ${#projects[@]} -eq 0 ]; then
    if [ -n "$ONLY" ]; then
        echo "error: no project matching --only '$ONLY' under $BASE_DIR" >&2
    else
        echo "error: no projects found under $BASE_DIR" >&2
    fi
    exit 2
fi

log "${BOLD}${CYAN}deploy-all.sh${NC}  base=$BASE_DIR  projects=${#projects[@]}  dry_run=$DRY_RUN"
log "${CYAN}manifest=${MANIFEST}${NC}"
echo ""

total=0
succeeded=0
failed=0
failed_names=()

for proj in "${projects[@]}"; do
    total=$((total + 1))
    name=$(basename "$proj")

    if [ -d "$proj/.claude/agents" ]; then
        mode="--update"
    else
        mode="--full"
    fi

    log "${BOLD}[$total/${#projects[@]}] $name${NC}  ($mode)"

    if [ "$DRY_RUN" -eq 1 ]; then
        log "  ${YELLOW}DRY-RUN${NC} $INSTALL_SH $mode $proj"
        continue
    fi

    # Per-project backup BEFORE install.sh runs.
    tarball="$SNAPSHOT_DIR/project-${name}-pre-${RUN_TS}.tgz"
    backup_err=""
    if [ -d "$proj/.claude" ]; then
        if ! tar -czf "$tarball" -C "$proj" .claude 2>/tmp/deploy-all-tar.err; then
            backup_err=$(head -c 500 /tmp/deploy-all-tar.err 2>/dev/null || true)
            log "  ${YELLOW}WARN${NC} backup tar failed: $backup_err"
        else
            log "  ${GREEN}snapshot${NC} $tarball"
        fi
    else
        log "  ${YELLOW}no existing .claude/ to snapshot${NC}"
    fi

    # Run install.sh.
    start_ms=$(perl -MTime::HiRes=time -e 'printf("%.0f\n", time()*1000)' 2>/dev/null || echo 0)
    out=$("$INSTALL_SH" "$mode" "$proj" 2>&1)
    rc=$?
    end_ms=$(perl -MTime::HiRes=time -e 'printf("%.0f\n", time()*1000)' 2>/dev/null || echo 0)
    duration_ms=$((end_ms - start_ms))
    [ "$duration_ms" -lt 0 ] && duration_ms=0

    if [ $rc -eq 0 ]; then
        succeeded=$((succeeded + 1))
        log "  ${GREEN}ok${NC} (${duration_ms}ms)"
        record_manifest "$name" "$mode" "success" "$duration_ms" ""
    else
        failed=$((failed + 1))
        failed_names+=("$name")
        tail_snip=$(printf '%s' "$out" | tail -c 500)
        log "  ${RED}FAILED${NC} (rc=$rc)"
        log "  ---- tail ----"
        printf '%s\n' "$tail_snip" | sed 's/^/    /'
        log "  --------------"
        record_manifest "$name" "$mode" "failed" "$duration_ms" "$tail_snip"
        if [ "$CONTINUE_ON_ERROR" -eq 0 ]; then
            log "${RED}halting (--halt-on-error)${NC}"
            break
        fi
    fi
done

echo ""
log "${BOLD}=== Summary ===${NC}"
log "  total:      $total"
log "  ${GREEN}succeeded:${NC}  $succeeded"
if [ $failed -gt 0 ]; then
    log "  ${RED}failed:${NC}     $failed"
    for n in "${failed_names[@]}"; do
        log "    - $n"
    done
else
    log "  failed:     0"
fi
log "  manifest:   $MANIFEST"

if [ "$DRY_RUN" -eq 1 ]; then
    log "${YELLOW}(dry-run — no writes performed)${NC}"
    exit 0
fi

if [ $failed -gt 0 ]; then
    exit 1
fi
exit 0
