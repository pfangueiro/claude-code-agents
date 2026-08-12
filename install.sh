#!/bin/bash

# ============================================================================
# Claude Agents - User-Global Installer
# ============================================================================
# Installs the framework ONCE into ~/.claude, where Claude Code picks it up in
# EVERY project. No per-project deployment. Self-healing: the SessionStart
# healthcheck hook and the launchd watchdog fork `install.sh --update` to
# reconcile ~/.claude against this source repo.
#
# Usage:
#   ./install.sh            - Install / re-install into ~/.claude (canonical)
#   ./install.sh --update   - Non-interactive reconcile of ~/.claude (self-heal)
#   ./install.sh --upgrade  - Migrate from old per-project copies (reconcile + confirm teardown + verify)
#   ./install.sh --help      - Show this help message
# ============================================================================

set -e

# Configuration
SCRIPT_VERSION="3.2.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEBUG="${DEBUG:-false}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Installation mode (no-args = canonical install)
MODE="${1:-install}"
# --upgrade consent flag (read ONLY by the --upgrade teardown; harmless no-op on other modes).
# Canonical flag order is `--upgrade [--yes]` (MODE reads $1); the skip one-liner emits that.
UPGRADE_ASSUME_YES=0
for _arg in "$@"; do case "$_arg" in --yes|-y) UPGRADE_ASSUME_YES=1 ;; esac; done

# Component lists
AGENTS=(
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

LIB_FILES=(
    "agent-templates.json"
    "sdlc-patterns.md"
    "agent-coordination.md"
    "mcp-guide.md"
)

# Lib files the framework once shipped and has since RETIRED. install copies
# LIB_FILES forward but never reverse-prunes, so a removed lib file would linger
# in ~/.claude/lib forever (activation-keywords.json did, after 0b343bb).
# prune_retired_lib_files() deletes these from ~/.claude/lib.
# SAFETY: an explicit retired-list (not "anything not in LIB_FILES") because
# ~/.claude/lib may hold a user's own files — we only ever delete files the
# framework itself shipped and retired, never an unrecognized user file
# (fail-closed, per security.md). Add an entry here in the same commit that
# removes a file from LIB_FILES.
RETIRED_LIB_FILES=(
    "activation-keywords.json"
)

# Skills the framework once shipped and has since RETIRED. The skills orphan-prune is
# scoped to "names the framework CURRENTLY ships" (see the prune contract below), which is
# correct for protecting the user's own skills — but it means a DELETED framework skill
# becomes indistinguishable from a personal one and would linger in ~/.claude/skills
# forever, still auto-activating in every project (api-guidelines did, after its retirement).
# Same fail-closed shape as RETIRED_LIB_FILES: an explicit list, never "anything unknown".
RETIRED_SKILLS=(
    "api-guidelines"
)

# Statistics
STATS_INSTALLED=0
STATS_SKIPPED=0

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo ""
    echo -e "${PURPLE}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${PURPLE}║${BOLD}     🤖 Claude Agents - User-Global Installer v${SCRIPT_VERSION}     ${NC}${PURPLE}║${NC}"
    echo -e "${PURPLE}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_progress() {
    echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $1"
}

print_success() {
    echo -e "${GREEN}✅${NC} $1"
    (( STATS_INSTALLED++ )) || true
}

print_skip() {
    echo -e "${YELLOW}⏭️${NC}  $1"
    (( STATS_SKIPPED++ )) || true
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ️${NC}  $1"
}

# ============================================================================
# Prerequisites & Preflight
# ============================================================================

check_prerequisites() {
    print_progress "Checking prerequisites..."

    local missing_required=false

    for cmd in git curl; do
        if command -v "$cmd" &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $cmd"
        else
            echo -e "  ${RED}✗${NC} $cmd (required)"
            missing_required=true
        fi
    done

    for cmd in jq npx; do
        if command -v "$cmd" &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $cmd"
        else
            echo -e "  ${YELLOW}!${NC} $cmd (optional — needed for statusline/MCP)"
        fi
    done

    if [ "$missing_required" = true ]; then
        print_error "Missing required tools. Install them and retry."
        exit 1
    fi

    print_success "Prerequisites satisfied"
}

preflight_checks() {
    local errors=0

    # Ensure ~/.claude exists and is writable (install destination)
    mkdir -p "$HOME/.claude" 2>/dev/null || true
    if [ ! -w "$HOME/.claude" ]; then
        print_error "No write permission in destination: $HOME/.claude"
        ((errors++)) || true
    fi

    # Check disk space in $HOME (need at least 1MB)
    local available_kb
    available_kb=$(df -k "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')
    if [ -n "$available_kb" ] && [ "$available_kb" -lt 1024 ]; then
        print_error "Insufficient disk space (need at least 1MB, have ${available_kb}KB)"
        ((errors++)) || true
    fi

    # Validate source directory has the shared set
    if [ ! -d "${SCRIPT_DIR}/.claude/agents" ]; then
        print_error "Source directory missing .claude/agents/. Run from the cloned repo."
        ((errors++)) || true
    fi

    if [ $errors -gt 0 ]; then
        print_error "Preflight checks failed with $errors error(s). Aborting."
        exit 1
    fi

    print_success "Preflight checks passed"
}

# ============================================================================
# Shared Set — agents / lib / rules / skills / commands → ~/.claude
# ============================================================================
#
# FRAMEWORK-SCOPED PRUNE CONTRACT (security-critical):
# ~/.claude/{skills,agents,commands,lib,rules} may already hold the user's OWN
# personal entries (e.g. skills: cloudflare, wrangler, durable-objects). The
# install must NEVER delete or overwrite anything the framework does not own.
#   * Every copy REPLACES the framework's own files (heals drift) — it never
#     touches a name outside the framework's set.
#   * Every orphan-prune only ever removes a name PROVABLY framework-owned:
#       - agents  : the AGENTS array (hand-maintained allowlist)
#       - lib     : LIB_FILES + RETIRED_LIB_FILES (via prune_retired_lib_files)
#       - skills/commands/rules : the set the framework ships in
#         ${SCRIPT_DIR}/.claude/<dir> — names outside that set are never eligible.
# This is fail-closed, per the RETIRED_LIB_FILES precedent above: we only ever
# remove names the framework itself ships/shipped, never an unrecognized file.

# Reverse-prune retired framework lib files from ~/.claude/lib. Only touches
# names in RETIRED_LIB_FILES, so a user's own lib files are never at risk.
prune_retired_lib_files() {
    [ -d "$HOME/.claude/lib" ] || return 0
    local retired
    for retired in "${RETIRED_LIB_FILES[@]}"; do
        if [ -f "$HOME/.claude/lib/${retired}" ]; then
            rm -f "$HOME/.claude/lib/${retired}" \
                && print_skip "Pruned retired lib file ${retired} (no longer shipped)"
        fi
    done
}

# Reverse-prune retired framework SKILLS from ~/.claude/skills. Only touches names in
# RETIRED_SKILLS, so the user's own skills are never at risk. Without this, retiring a
# skill removes it from the repo but leaves it live and auto-activating in every project.
prune_retired_skills() {
    [ -d "$HOME/.claude/skills" ] || return 0
    local retired
    for retired in "${RETIRED_SKILLS[@]}"; do
        # Refuse to act on a name the framework still ships — that would be a bug in the
        # retired list, and deleting a live skill is worse than leaving a stale one.
        if [ -d "${SCRIPT_DIR}/.claude/skills/${retired}" ]; then
            print_error "RETIRED_SKILLS lists '${retired}' but it is still shipped in source — not pruning"
            continue
        fi
        if [ -d "$HOME/.claude/skills/${retired}" ]; then
            rm -rf "$HOME/.claude/skills/${retired}" \
                && print_skip "Pruned retired skill ${retired} (no longer shipped)"
        fi
    done
}

install_global_agents() {
    echo -e "\n${BOLD}Installing Agents (~/.claude/agents):${NC}"

    local src_dir="${SCRIPT_DIR}/.claude/agents"
    local dest_dir="$HOME/.claude/agents"

    if [ ! -d "$src_dir" ]; then
        print_error "Source agents dir missing: $src_dir"
        return 1
    fi
    mkdir -p "$dest_dir"

    # Copy (REPLACE) every framework-owned agent so drift heals.
    local agent src
    for agent in "${AGENTS[@]}"; do
        src="$src_dir/${agent}.md"
        if [ -f "$src" ]; then
            cp "$src" "$dest_dir/${agent}.md"
            print_success "Synced agent ${agent}"
        else
            print_error "Framework agent source missing: ${agent}.md"
        fi
    done

    # Framework-scoped orphan prune: remove a DEPLOYED agent only if its name is
    # framework-owned (in AGENTS) AND its source file is gone. Personal agents
    # (names not in AGENTS) are never eligible.
    local deployed dname owned
    for deployed in "$dest_dir"/*.md; do
        [ -f "$deployed" ] || continue
        dname=$(basename "$deployed" .md)
        [[ "$dname" == ._* ]] && continue
        owned=0
        for agent in "${AGENTS[@]}"; do
            [ "$agent" = "$dname" ] && { owned=1; break; }
        done
        if [ "$owned" -eq 1 ] && [ ! -f "$src_dir/${dname}.md" ]; then
            rm -f "$deployed"
            print_skip "Pruned orphan agent ${dname} (framework-owned, no longer in source)"
        fi
    done
}

install_global_lib() {
    echo -e "\n${BOLD}Installing Library Files (~/.claude/lib):${NC}"

    local src_dir="${SCRIPT_DIR}/.claude/lib"
    local dest_dir="$HOME/.claude/lib"

    if [ ! -d "$src_dir" ]; then
        print_info "No lib directory in source — skipping"
        return 0
    fi
    mkdir -p "$dest_dir"

    # Copy (REPLACE) every framework-owned lib file.
    local lib src
    for lib in "${LIB_FILES[@]}"; do
        src="$src_dir/${lib}"
        if [ -f "$src" ]; then
            cp "$src" "$dest_dir/${lib}"
            print_success "Synced lib ${lib}"
        else
            print_error "Framework lib source missing: ${lib}"
        fi
    done

    # Orphan prune for lib is the explicit retired-list (fail-closed).
    prune_retired_lib_files
    prune_retired_skills
}

install_global_rules() {
    echo -e "\n${BOLD}Installing Rules (~/.claude/rules):${NC}"

    local src_dir="${SCRIPT_DIR}/.claude/rules"
    local dest_dir="$HOME/.claude/rules"

    if [ ! -d "$src_dir" ]; then
        print_info "No rules directory in source — skipping"
        return 0
    fi
    mkdir -p "$dest_dir"

    # Framework's own rule set = names shipped in source. Copy (REPLACE) each.
    local -a src_names=()
    local file name
    for file in "$src_dir"/*.md; do
        [ -f "$file" ] || continue
        name=$(basename "$file")
        [[ "$name" == ._* ]] && continue
        [ "$name" = ".DS_Store" ] && continue
        src_names+=("$name")
        cp "$file" "$dest_dir/$name"
        print_success "Synced rule $name"
    done

    _prune_framework_orphan_files "$dest_dir" "$src_dir" "rule" "${src_names[@]}"
}

install_global_skills() {
    echo -e "\n${BOLD}Installing Skills (~/.claude/skills):${NC}"

    local src_dir="${SCRIPT_DIR}/.claude/skills"
    local dest_dir="$HOME/.claude/skills"

    if [ ! -d "$src_dir" ]; then
        print_info "No skills directory in source — skipping"
        return 0
    fi
    mkdir -p "$dest_dir"

    # Framework's own skill set = directory names shipped in source.
    local -a src_names=()
    local skill_dir name
    for skill_dir in "$src_dir"/*/; do
        [ -d "$skill_dir" ] || continue
        name=$(basename "$skill_dir")
        [[ "$name" == ._* ]] && continue
        [ "$name" = ".DS_Store" ] && continue
        src_names+=("$name")
        # REPLACE: rm then copy so intra-skill drift (files deleted inside a
        # skill) heals too. Only ever removes a framework-owned skill name.
        rm -rf "$dest_dir/$name"
        cp -r "$skill_dir" "$dest_dir/$name"
        print_success "Synced skill $name"
    done

    _prune_framework_orphan_dirs "$dest_dir" "$src_dir" "${src_names[@]}"
}

install_global_commands() {
    echo -e "\n${BOLD}Installing Slash Commands (~/.claude/commands):${NC}"

    local src_dir="${SCRIPT_DIR}/.claude/commands"
    local dest_dir="$HOME/.claude/commands"

    if [ ! -d "$src_dir" ]; then
        print_info "No commands directory in source — skipping"
        return 0
    fi
    mkdir -p "$dest_dir"

    # Framework's own command set = names shipped in source. Copy (REPLACE) each.
    local -a src_names=()
    local file name
    for file in "$src_dir"/*.md; do
        [ -f "$file" ] || continue
        name=$(basename "$file")
        [[ "$name" == ._* ]] && continue
        [ "$name" = ".DS_Store" ] && continue
        src_names+=("$name")
        cp "$file" "$dest_dir/$name"
        print_success "Synced command $name"
    done

    _prune_framework_orphan_files "$dest_dir" "$src_dir" "command" "${src_names[@]}"
}

# Framework-scoped orphan prune for a FLAT dir of *.md files (rules, commands).
# Args: <dest_dir> <src_dir> <label> <framework-owned name>...
# Only a deployed file whose name is in the framework's own set (the passed
# names) AND is absent from source is removed. Since the owned set is derived
# from source, a personal file (name not shipped by the framework) is never
# eligible — the fail-closed guard that guarantees personal entries survive.
# (A framework file retired from source is left in place, same as lib was before
# RETIRED_LIB_FILES; add a retired-list to actively prune such names.)
_prune_framework_orphan_files() {
    local dest_dir="$1" src_dir="$2" label="$3"
    shift 3
    local -a owned=("$@")
    [ -d "$dest_dir" ] || return 0
    local deployed dname is_owned o
    for deployed in "$dest_dir"/*.md; do
        [ -f "$deployed" ] || continue
        dname=$(basename "$deployed")
        [[ "$dname" == ._* ]] && continue
        is_owned=0
        for o in "${owned[@]}"; do
            [ "$o" = "$dname" ] && { is_owned=1; break; }
        done
        if [ "$is_owned" -eq 1 ] && [ ! -f "$src_dir/$dname" ]; then
            rm -f "$deployed"
            print_skip "Pruned orphan $label $dname (framework-owned, no longer in source)"
        fi
    done
}

# Framework-scoped orphan prune for a dir of skill SUBDIRECTORIES (skills).
# Args: <dest_dir> <src_dir> <framework-owned name>...
# Same fail-closed guarantee as _prune_framework_orphan_files: only a subdir
# whose name is in the framework's own (source-derived) set is ever eligible,
# so the user's personal skills are never removed.
_prune_framework_orphan_dirs() {
    local dest_dir="$1" src_dir="$2"
    shift 2
    local -a owned=("$@")
    [ -d "$dest_dir" ] || return 0
    local deployed dname is_owned o
    for deployed in "$dest_dir"/*/; do
        [ -d "$deployed" ] || continue
        dname=$(basename "$deployed")
        [[ "$dname" == ._* ]] && continue
        is_owned=0
        for o in "${owned[@]}"; do
            [ "$o" = "$dname" ] && { is_owned=1; break; }
        done
        if [ "$is_owned" -eq 1 ] && [ ! -d "$src_dir/$dname" ]; then
            rm -rf "$deployed"
            print_skip "Pruned orphan skill $dname (framework-owned, no longer in source)"
        fi
    done
}

install_shared_set() {
    install_global_agents
    install_global_lib
    install_global_rules
    install_global_skills
    install_global_commands
}

# Append a JSON event to the framework health stream (best-effort, never fails).
_health_log() {
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null)
    mkdir -p "$HOME/.claude/analytics" 2>/dev/null || true
    echo "{\"ts\":\"$ts\",$1}" >> "$HOME/.claude/analytics/framework-health.jsonl" 2>/dev/null || true
}

# sha256 of a file (portable across macOS/Linux); empty on failure.
_sha_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" 2>/dev/null | awk '{print $1}'
    fi
}

# Autonomous, OPT-IN, guardrailed migration of OLD per-project framework copies to
# user-global. Runs ONLY if ~/.claude/.framework-autonomy sets LEGACY_PROJECTS_DIR.
# For each project under that dir carrying a per-project framework .claude/agents,
# remove ONLY the framework shared-set subdirs (agents/skills/commands/rules/lib) —
# and ONLY when git-untracked (never rewrite a repo's history), snapshot-first,
# idempotent. Personal .claude content, committed repos, and the framework repo/clone
# are never touched. Absent marker → no-op (public users + fresh installs unaffected).
# ─────────────────────────────────────────────────────────────────────────────
# --upgrade helpers (interactive one-shot old→new migration). NONE of these run on
# the bare install / --update / --migrate-legacy paths.
# ─────────────────────────────────────────────────────────────────────────────

# Concurrency lock — same mkdir scheme as update_installation, EXTRACTED so --upgrade can
# reuse it without editing the protected --update body. Returns 0 if acquired (EXIT trap
# cleans up), 1 if another install holds it.
_acquire_install_lock() {
    local lock_dir="$HOME/.claude/.install.lock.d" lock_pid_file
    lock_pid_file="$lock_dir/pid"
    mkdir -p "$HOME/.claude" 2>/dev/null || true
    if [ -d "$lock_dir" ]; then
        if [ -f "$lock_pid_file" ]; then
            local lock_pid
            lock_pid=$(cat "$lock_pid_file" 2>/dev/null)
            if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
                echo "another install is running (pid $lock_pid) — exiting cleanly" >&2
                return 1
            fi
        fi
        echo "removing stale lock at $lock_dir" >&2
        rm -rf "$lock_dir"
    fi
    mkdir "$lock_dir" 2>/dev/null || { echo "lock acquisition failed — exiting" >&2; return 1; }
    echo $$ > "$lock_pid_file"
    # shellcheck disable=SC2064
    trap "rm -rf '$lock_dir' 2>/dev/null || true" EXIT INT TERM
    return 0
}

# Fail-closed consent for the interactive --upgrade teardown. $1=count $2=dir → 0 proceed,
# 1 skip. Deletion happens ONLY on explicit --yes / CLAUDE_UPGRADE_ASSUME_YES, or a typed
# y/yes at the CONTROLLING TERMINAL read via a DEDICATED fd bound to /dev/tty — never stdin,
# so a piped `curl|bash` stdin can never be misread as consent. No tty + no explicit → skip.
_upgrade_confirm_teardown() {
    local _count="$1" _dir="$2" reply
    if [ "${CLAUDE_UPGRADE_ASSUME_YES:-0}" = "1" ] || [ "${UPGRADE_ASSUME_YES:-0}" = "1" ]; then
        _health_log "\"event\":\"upgrade_consent\",\"mode\":\"explicit_yes\",\"count\":$_count"
        return 0
    fi
    if exec 9</dev/tty 2>/dev/null; then
        {
            printf '\n%s project(s) under %s carry old per-project framework copies.\n' "$_count" "$_dir"
            printf 'Only git-untracked framework files are removed; a snapshot is saved first.\n'
            printf 'Tear them down now? [y/N] '
        } >/dev/tty 2>/dev/null
        IFS= read -r -t 30 reply <&9 || reply=""
        exec 9<&-
        case "$reply" in
            y|Y|yes|YES) _health_log "\"event\":\"upgrade_consent\",\"mode\":\"tty_yes\",\"count\":$_count"; return 0 ;;
            *)           _health_log "\"event\":\"upgrade_consent\",\"mode\":\"tty_no\",\"count\":$_count"; echo "Declined — nothing removed."; return 1 ;;
        esac
    fi
    _health_log "\"event\":\"upgrade_consent\",\"mode\":\"noninteractive_skip\",\"count\":$_count"
    echo "No terminal for confirmation — teardown skipped (nothing removed)."
    echo "  To migrate the ${_count} old copy/copies: ${SCRIPT_DIR}/install.sh --upgrade --yes"
    echo "  (pipe-friendly:                          CLAUDE_UPGRADE_ASSUME_YES=1 ${SCRIPT_DIR}/install.sh --upgrade)"
    return 1
}

# Marker-less --upgrade: resolve the projects dir to scan, prompting on /dev/tty. Echoes the
# chosen dir on STDOUT only; prompts/diagnostics go to /dev/tty and stderr. Returns non-zero
# (→ no teardown) if it can't get a safe dir. NEVER defaults to $HOME.
_upgrade_resolve_dir() {
    local suggested reply dir
    suggested=$(dirname "$SCRIPT_DIR")
    [ "$suggested" = "$HOME" ] && suggested=""
    if ! exec 9</dev/tty 2>/dev/null; then
        echo "No terminal to ask which directory holds old per-project copies." >&2
        echo "Set ~/.claude/.framework-autonomy (LEGACY_PROJECTS_DIR=/path), or use ./install.sh --migrate-legacy." >&2
        return 1
    fi
    if [ -n "$suggested" ]; then
        printf 'Directory holding old per-project .claude copies [%s]: ' "$suggested" >/dev/tty 2>/dev/null
    else
        printf 'Absolute path of the dir holding old per-project .claude copies (blank to skip): ' >/dev/tty 2>/dev/null
    fi
    IFS= read -r reply <&9 || reply=""
    exec 9<&-
    dir="${reply:-$suggested}"
    case "$dir" in "~") dir="$HOME" ;; "~/"*) dir="$HOME/${dir#\~/}" ;; esac
    if [ -z "$dir" ]; then
        echo "Already on user-global — nothing to migrate." >&2
        return 1
    fi
    if [ "$dir" = "$HOME" ] || [ ! -d "$dir" ]; then
        echo "Refusing '$dir' (home directory or not a directory) — skipping teardown." >&2
        return 1
    fi
    printf '%s\n' "$dir"
}

# Self-verify tail for --upgrade ONLY. Observe-only: runs validate.sh --quick WITHOUT --heal
# (--heal reaches install --update, a deletion path, and always exits 0). Honest tri-state.
_upgrade_self_verify() {
    if [ -x "$SCRIPT_DIR/validate.sh" ]; then
        local rc=0
        if "$SCRIPT_DIR/validate.sh" --quick; then rc=0; else rc=$?; fi
        if [ "$rc" -eq 0 ]; then
            print_success "Upgrade verified (validate.sh --quick clean)"
        else
            echo -e "${YELLOW}UPGRADE VERIFY: validate.sh --quick reported issues — some may predate this upgrade. Run ./validate.sh for detail.${NC}"
            exit "$rc"
        fi
    else
        verify_installation
        echo -e "${YELLOW}UNVERIFIED — validate.sh not found; ~/.claude structure present.${NC}"
    fi
}

reconcile_legacy_projects() {
    local explicit_dir="${1:-}" consent_mode="${2:-}"
    local dir
    if [ -z "$explicit_dir" ]; then
        # Autonomous / no-arg path: marker-gated (unchanged behavior).
        local marker="$HOME/.claude/.framework-autonomy"
        [ -f "$marker" ] || return 0
        dir=$(grep -E '^LEGACY_PROJECTS_DIR=' "$marker" 2>/dev/null | head -1)
        dir="${dir#LEGACY_PROJECTS_DIR=}"
        dir="${dir%\"}"; dir="${dir#\"}"
        dir="${dir%\'}"; dir="${dir#\'}"
        dir="$(printf '%s' "$dir" | tr -d '[:space:]')"
        case "$dir" in "~") dir="$HOME" ;; "~/"*) dir="$HOME/${dir#\~/}" ;; esac
    else
        # --upgrade path: caller supplied and validated the directory (see _upgrade_resolve_dir).
        dir="$explicit_dir"
    fi
    [ -n "$dir" ] && [ -d "$dir" ] || return 0

    # Framework-owned names (from source) — we ONLY ever remove THESE, and a project
    # qualifies for teardown ONLY if it actually carries one (so a project with only its
    # OWN custom agents is never a candidate → no snapshot spam, stays idempotent).
    local src="${SCRIPT_DIR}/.claude"
    local -a fw_agents=() fw_skills=() fw_cmds=() fw_rules=() fw_lib=()
    local f d
    [ -d "$src/agents" ]   && for f in "$src/agents"/*.md;   do [ -f "$f" ] && fw_agents+=("$(basename "$f")"); done
    [ -d "$src/skills" ]   && for d in "$src/skills"/*/;     do [ -d "$d" ] && fw_skills+=("$(basename "$d")"); done
    [ -d "$src/commands" ] && for f in "$src/commands"/*.md; do [ -f "$f" ] && fw_cmds+=("$(basename "$f")"); done
    [ -d "$src/rules" ]    && for f in "$src/rules"/*.md;    do [ -f "$f" ] && fw_rules+=("$(basename "$f")"); done
    [ -d "$src/lib" ]      && for f in "$src/lib"/*;         do [ -f "$f" ] && fw_lib+=("$(basename "$f")"); done
    [ "${#fw_agents[@]}" -gt 0 ] || return 0   # no framework agents in source → nothing to key on

    # Pass 1 (read-only): collect projects that carry a FRAMEWORK agent copy and are UNTRACKED.
    local -a candidates=()
    local proj bn n has_fw
    for proj in "$dir"/*/; do
        [ -L "${proj%/}" ] && continue                 # skip symlinked project dirs
        [ -d "${proj}.claude/agents" ] || continue
        # Symlink guard: line 484 only skips a symlinked PROJECT dir. If .claude (or a
        # framework subdir) is itself a symlink, `rm -f` would follow it into a shared or
        # committed target — skip the whole project so teardown never traverses a symlink
        # out of the project tree.
        [ -L "${proj}.claude" ] && continue
        local _sl=0 _s
        for _s in agents skills commands rules lib; do [ -L "${proj}.claude/$_s" ] && { _sl=1; break; }; done
        [ "$_sl" -eq 0 ] || continue
        bn=$(basename "$proj")
        case "$bn" in claude-code-agents|claude-code) continue ;; esac
        # qualify ONLY a project that actually holds a framework-owned agent file
        has_fw=0
        for n in "${fw_agents[@]}"; do [ -f "${proj}.claude/agents/$n" ] && { has_fw=1; break; }; done
        [ "$has_fw" -eq 1 ] || continue
        # Committed guard (FAIL-CLOSED): the teardown removes framework-named files from ALL
        # five subdirs (agents/skills/commands/rules/lib), so EVERY one that exists must be
        # git-UNTRACKED. Checking only .claude/agents would let a repo that committed e.g.
        # .claude/rules/<framework-name>.md (with agents left untracked) reach teardown and
        # have TRACKED files removed from its working tree. `git ls-files --error-unmatch`
        # exits 1=untracked (ok), 0=tracked, anything else = git error. If ANY existing
        # subdir is tracked or indeterminate → skip the whole project (never remove when the
        # tracked-status of any subdir is uncertain).
        if [ -d "${proj}.git" ]; then
            command -v git >/dev/null 2>&1 || continue
            local _sub _rc _tracked=0
            for _sub in agents skills commands rules lib; do
                [ -e "${proj}.claude/$_sub" ] || continue
                _rc=0
                ( cd "$proj" && git ls-files --error-unmatch ".claude/$_sub" >/dev/null 2>&1 ) || _rc=$?
                [ "$_rc" -eq 1 ] || { _tracked=1; break; }
            done
            [ "$_tracked" -eq 0 ] || continue
        fi
        candidates+=("$proj")
    done
    if [ "${#candidates[@]}" -eq 0 ]; then
        [ "$consent_mode" = confirm ] && echo "Nothing to migrate — already on user-global."
        return 0   # EXPLICIT return (never the `&&` tail — under set -e a false test as the last
                   # statement would make no-arg callers' update_installation reconcile exit non-zero)
    fi

    echo -e "\n${BOLD}Autonomous legacy teardown:${NC} ${#candidates[@]} project(s) → user-global"

    # Interactive one-shot (--upgrade, consent_mode=confirm): show the candidate LIST and require a
    # shown-count confirmation BEFORE any snapshot/delete. No-arg (autonomous) callers pass
    # consent_mode='' → this whole block is skipped → byte-identical to before.
    if [ "$consent_mode" = confirm ]; then
        for proj in "${candidates[@]}"; do echo "  - ${proj%/}"; done
        _upgrade_confirm_teardown "${#candidates[@]}" "$dir" || return 0
    fi

    # Snapshot-first (only the affected projects' .claude).
    mkdir -p "$HOME/.claude/snapshots" 2>/dev/null || true
    local snap="$HOME/.claude/snapshots/preteardown-auto-$(date +%Y%m%d-%H%M%S 2>/dev/null).tgz"
    local -a rels=()
    for proj in "${candidates[@]}"; do rels+=("${proj#$dir/}.claude"); done
    ( cd "$dir" && tar -czf "$snap" "${rels[@]}" ) >/dev/null 2>&1 || true
    # FAIL-CLOSED: only remove if the snapshot is a valid, non-empty, readable archive —
    # never tear down without a recovery path.
    if [ ! -s "$snap" ] || ! tar -tzf "$snap" >/dev/null 2>&1; then
        _health_log "\"event\":\"legacy_teardown_aborted\",\"reason\":\"snapshot_failed\",\"snapshot\":\"$snap\""
        print_error "Legacy teardown ABORTED — snapshot failed; nothing removed"
        return 0
    fi

    # Remove ONLY framework-owned files (by name); rmdir the now-empty framework subdirs
    # (rmdir no-ops on a non-empty dir, so any custom content is left in place).

    local removed=0 n sub
    for proj in "${candidates[@]}"; do
        for n in "${fw_agents[@]}"; do rm -f  "${proj}.claude/agents/$n"   2>/dev/null; done
        for n in "${fw_skills[@]}"; do rm -rf "${proj}.claude/skills/$n"   2>/dev/null; done
        for n in "${fw_cmds[@]}";   do rm -f  "${proj}.claude/commands/$n" 2>/dev/null; done
        for n in "${fw_rules[@]}";  do rm -f  "${proj}.claude/rules/$n"    2>/dev/null; done
        for n in "${fw_lib[@]}";    do rm -f  "${proj}.claude/lib/$n"      2>/dev/null; done
        [ -e "${proj}.claude/.framework-version" ] && rm -f "${proj}.claude/.framework-version"
        for sub in agents skills commands rules lib; do rmdir "${proj}.claude/$sub" 2>/dev/null || true; done
        rmdir "${proj}.claude" 2>/dev/null || true
        removed=$((removed + 1))
    done
    _health_log "\"event\":\"legacy_teardown\",\"projects\":$removed,\"snapshot\":\"$snap\""
    print_success "Migrated $removed legacy project(s) to user-global (snapshot: $snap)"
}

# ============================================================================
# Global Configuration (hooks / output-styles / statusline / settings)
# ============================================================================

install_global_config() {
    echo -e "\n${BOLD}Installing Global Configuration:${NC}"

    local src_dir="${SCRIPT_DIR}/global-config"

    if [ ! -d "$src_dir" ]; then
        print_error "global-config/ directory not found. Run from the repo root."
        return 1
    fi

    # Create directories
    mkdir -p ~/.claude/hooks
    mkdir -p ~/.claude/output-styles

    # Copy hooks (executable shell scripts)
    for hook in "$src_dir"/hooks/*.sh; do
        [ -f "$hook" ] || continue
        local name
        name=$(basename "$hook")
        cp "$hook" ~/.claude/hooks/"$name"
        chmod +x ~/.claude/hooks/"$name"
        print_success "Installed hook $name"
    done

    # Copy hook reference configs (prompt/agent hook templates)
    for hook_cfg in "$src_dir"/hooks/*.json; do
        [ -f "$hook_cfg" ] || continue
        local name
        name=$(basename "$hook_cfg")
        cp "$hook_cfg" ~/.claude/hooks/"$name"
        print_success "Installed hook config $name"
    done

    sync_output_styles

    # Copy statusline
    if [ -f "$src_dir/statusline.sh" ]; then
        cp "$src_dir/statusline.sh" ~/.claude/statusline.sh
        chmod +x ~/.claude/statusline.sh
        print_success "Installed statusline.sh"
    fi

    # Handle settings.json — NON-INTERACTIVE. Seed from template on first run;
    # otherwise leave the user's file untouched (sync_hooks reconciles the
    # framework-owned keys: hooks / env / permissions / statusLine).
    if [ -f "$src_dir/settings.json.template" ]; then
        if [ ! -f ~/.claude/settings.json ]; then
            cp "$src_dir/settings.json.template" ~/.claude/settings.json
            print_success "Installed settings.json from template"
        else
            print_skip "settings.json exists — leaving it (sync_hooks reconciles framework keys)"
        fi
    fi
}

# Atomic, defensive mutation of ~/.claude/settings.json.
# - mktemp gives a UNIQUE temp file (not a shared name) so two concurrent
#   installs can never interleave on the same tmp and mv a partial file.
# - Refuses to install empty or malformed output: if jq fails, emits nothing,
#   or emits invalid JSON, settings.json is left untouched. This guarantees the
#   framework's own reconcile can never contribute to a hooks-wipe, even if the
#   input was already corrupted by an external writer (e.g. CLI settings-sync).
# Usage: _atomic_settings_jq '<jq filter>'   → 0 on success, non-zero on no-op.
_atomic_settings_jq() {
    local filter="$1" tmp
    tmp=$(mktemp "${HOME}/.claude/.settings.json.XXXXXX" 2>/dev/null) || return 1
    if jq "$filter" ~/.claude/settings.json > "$tmp" 2>/dev/null \
        && [ -s "$tmp" ] \
        && jq -e . "$tmp" >/dev/null 2>&1; then
        mv "$tmp" ~/.claude/settings.json
    else
        rm -f "$tmp" 2>/dev/null || true
        return 1
    fi
}

sync_hooks() {
    echo -e "\n${BOLD}Syncing Hooks:${NC}"

    local src_dir="${SCRIPT_DIR}/global-config/hooks"

    if [ ! -d "$src_dir" ]; then
        print_info "No hooks directory found in source — skipping"
        return 0
    fi

    mkdir -p ~/.claude/hooks

    # Build set of source hook basenames for orphan detection below
    local -a src_hook_names=()
    for hook in "$src_dir"/*.sh "$src_dir"/*.json; do
        [ -f "$hook" ] || continue
        src_hook_names+=("$(basename "$hook")")
    done

    for hook in "$src_dir"/*.sh; do
        [ -f "$hook" ] || continue
        local name
        name=$(basename "$hook")
        cp "$hook" ~/.claude/hooks/"$name"
        chmod +x ~/.claude/hooks/"$name"
        print_success "Synced hook $name"
    done

    for hook_cfg in "$src_dir"/*.json; do
        [ -f "$hook_cfg" ] || continue
        local name
        name=$(basename "$hook_cfg")
        cp "$hook_cfg" ~/.claude/hooks/"$name"
        print_success "Synced hook config $name"
    done

    # Orphan detection: prune deployed hook files that are no longer in source.
    # sync_hooks copies forward but never reverse-prunes; before this block,
    # files removed from source persisted in ~/.claude/hooks/ forever
    # (e.g. stop-phrase-guard.sh after v2.9.2 removal needed manual rm).
    local pruned=0
    for deployed in ~/.claude/hooks/*.sh ~/.claude/hooks/*.json; do
        [ -f "$deployed" ] || continue
        local dname
        dname=$(basename "$deployed")
        local found=0
        for src_name in "${src_hook_names[@]}"; do
            [ "$src_name" = "$dname" ] && { found=1; break; }
        done
        if [ "$found" -eq 0 ]; then
            rm -f "$deployed"
            pruned=$((pruned + 1))
            print_skip "Pruned orphan hook $dname (no longer in source)"
        fi
    done
    [ "$pruned" -eq 0 ] && print_skip "No orphan hooks to prune"

    # Recover from a full DELETE of settings.json (not just an emptied {} wipe) OR a settings.json
    # that is not a usable JSON OBJECT — either unparseable (truncated write) or valid JSON of the
    # wrong shape (array / scalar). The per-block reconcile reads the file with jq and either can't
    # parse it or can't index a non-object, so every _atomic_settings_jq below no-ops — leaving the
    # damage unhealed AND blocking the whole settings reconcile. Requiring type=="object" (not just
    # parseable) covers the full class. The bad file is preserved (settings.json.corrupt-<ts>) for
    # forensics / manual recovery before reseeding. Atomic cp so a reader never sees half.
    local _settings_reseed=0
    if [ ! -f ~/.claude/settings.json ]; then
        _settings_reseed=1
    elif command -v jq >/dev/null 2>&1 && ! jq -e 'type == "object"' ~/.claude/settings.json >/dev/null 2>&1; then
        local _corrupt_ts
        _corrupt_ts=$(date -u +%Y%m%d-%H%M%S 2>/dev/null || echo backup)
        cp ~/.claude/settings.json ~/.claude/settings.json.corrupt-"$_corrupt_ts" 2>/dev/null || true
        print_error "settings.json was not a valid JSON object — backed up to settings.json.corrupt-${_corrupt_ts} and reseeding from template" || true
        _settings_reseed=1
    fi
    if [ "$_settings_reseed" -eq 1 ] && [ -f "${SCRIPT_DIR}/global-config/settings.json.template" ]; then
        cp "${SCRIPT_DIR}/global-config/settings.json.template" ~/.claude/settings.json.recreate.$$ \
            && mv ~/.claude/settings.json.recreate.$$ ~/.claude/settings.json \
            && print_success "Recreated settings.json from template"
    fi

    # Reconcile hook events and env vars in settings.json against template.
    # Framework-managed hook events (those present in template) are the source of truth:
    # if user's version differs (missing, drifted command, drifted timeout, missing sub-hook),
    # REPLACE user's version with template. User env vars are preserved (only missing keys added).
    if [ -f ~/.claude/settings.json ] && command -v jq &>/dev/null; then
        local template="${SCRIPT_DIR}/global-config/settings.json.template"
        if [ -f "$template" ]; then
            local tmpl_events
            tmpl_events=$(jq -r '.hooks | keys[]' "$template" 2>/dev/null)
            local reconciled=false
            for event in $tmpl_events; do
                local tmpl_cfg usr_cfg
                tmpl_cfg=$(jq -Sc ".hooks[\"$event\"]" "$template")
                usr_cfg=$(jq -Sc ".hooks[\"$event\"] // null" ~/.claude/settings.json)
                if [ "$tmpl_cfg" != "$usr_cfg" ]; then
                    local event_config
                    event_config=$(jq ".hooks[\"$event\"]" "$template")
                    _atomic_settings_jq ".hooks[\"$event\"] = $event_config" || true
                    if [ "$usr_cfg" = "null" ]; then
                        print_success "Added hook event $event to settings.json"
                    else
                        print_success "Reconciled drifted hook event $event (was: ${usr_cfg:0:80}...)"
                    fi
                    reconciled=true
                fi
            done
            if [ "$reconciled" = false ]; then
                print_skip "All hook events match template"
            fi

            # Reverse-prune hook EVENTS: the forward loop above adds/repairs every event the
            # template HAS, but never removes an event the template DROPPED. A stale event
            # still bound to a framework hook script (e.g. `Stop -> session-end.sh` after
            # session-end.sh moved to SessionEnd) then double-fires that script every turn,
            # forever. Framework-scoped: only prune an off-template event whose command is one
            # of THIS framework's hook scripts — a user's own event/script is left alone.
            # Mirrors the hook-FILE orphan prune above (files were pruned; event keys weren't).
            local usr_events uevent
            usr_events=$(jq -r '.hooks | keys[]' ~/.claude/settings.json 2>/dev/null)
            for uevent in $usr_events; do
                printf '%s\n' "$tmpl_events" | grep -qx "$uevent" && continue
                local runs_fw=0 ucmd ubase src_name
                while IFS= read -r ucmd; do
                    [ -n "$ucmd" ] || continue
                    ubase=$(basename "$ucmd")
                    for src_name in "${src_hook_names[@]}"; do
                        [ "$ubase" = "$src_name" ] && runs_fw=1
                    done
                done < <(jq -r ".hooks[\"$uevent\"][]?.hooks[]?.command // empty" ~/.claude/settings.json 2>/dev/null)
                if [ "$runs_fw" -eq 1 ]; then
                    _atomic_settings_jq "del(.hooks[\"$uevent\"])" || true
                    print_skip "Pruned stale hook event $uevent (ran a framework hook the template dropped)"
                fi
            done

            # Merge new env vars into existing settings.json. Add-only, so a deliberate user
            # value is preserved — EXCEPT for a key whose valid set the framework knows and
            # whose current value is outside it.
            #
            # Why the exception exists: validate.sh --quick FAILS on an invalid
            # CLAUDE_CODE_EFFORT_LEVEL, and that failure is what the watchdog reacts to by
            # running `install.sh --update`. With a purely add-only merge the value was never
            # corrected, so the very next check failed identically — an hourly heal that heals
            # nothing, forever. Reproduced with `max` (a real, documented session-only tier a
            # user would plausibly try to persist): errors before heal, same error after.
            # This is the repo's own rule from docs/FAILURE-MODES.md — a check that convicts
            # must be paired with a heal that can actually fix it, or it must not run in the
            # automated path at all.
            local new_env_keys
            new_env_keys=$(jq -r '.env | keys[]' "$template" 2>/dev/null)
            for key in $new_env_keys; do
                if ! jq -e ".env[\"$key\"]" ~/.claude/settings.json &>/dev/null; then
                    local val
                    val=$(jq ".env[\"$key\"]" "$template")
                    _atomic_settings_jq ".env[\"$key\"] = $val" || true
                    print_success "Added env var $key to settings.json"
                elif [ "$key" = "CLAUDE_CODE_EFFORT_LEVEL" ]; then
                    local cur_eff
                    cur_eff=$(jq -r '.env["CLAUDE_CODE_EFFORT_LEVEL"] // ""' ~/.claude/settings.json 2>/dev/null)
                    case "$cur_eff" in
                        low|medium|high|xhigh) : ;;   # a valid choice — never overwrite it
                        *)
                            local eff_val
                            eff_val=$(jq '.env["CLAUDE_CODE_EFFORT_LEVEL"]' "$template")
                            _atomic_settings_jq ".env[\"CLAUDE_CODE_EFFORT_LEVEL\"] = $eff_val" || true
                            print_success "Healed invalid CLAUDE_CODE_EFFORT_LEVEL ('$cur_eff' → $eff_val); persistent tiers are low|medium|high|xhigh"
                            ;;
                    esac
                fi
            done

            # Reconcile .permissions (framework-owned, security-sensitive — same
            # replace-on-drift policy as hooks). Users who want custom permissions
            # should edit settings.local.json, which has higher precedence.
            if jq -e '.permissions' "$template" &>/dev/null; then
                local tmpl_perms usr_perms
                tmpl_perms=$(jq -Sc '.permissions' "$template")
                usr_perms=$(jq -Sc '.permissions // null' ~/.claude/settings.json)
                if [ "$tmpl_perms" != "$usr_perms" ]; then
                    local perms_value
                    perms_value=$(jq '.permissions' "$template")
                    _atomic_settings_jq ".permissions = $perms_value" || true
                    if [ "$usr_perms" = "null" ]; then
                        print_success "Added permissions block to settings.json"
                    else
                        print_success "Reconciled permissions block in settings.json"
                    fi
                fi
            fi

            # Reconcile .attribution (framework-owned — the commit trailer MUST stay empty).
            # Same replace-on-drift policy as permissions/statusLine. A stale "Co-Authored-By"
            # (or any AI-attribution) commit trailer left in the user's live settings.json —
            # e.g. from an old per-project install or a CLI settings-sync payload — is healed
            # back to the template's commit="" AND the template's .pr footer is restored, in
            # ONE whole-block replace. Users wanting a custom PR footer edit settings.local.json
            # (higher precedence), same as the permissions block above.
            if jq -e '.attribution' "$template" &>/dev/null; then
                local tmpl_attr usr_attr
                tmpl_attr=$(jq -Sc '.attribution' "$template")
                usr_attr=$(jq -Sc '.attribution // null' ~/.claude/settings.json)
                if [ "$tmpl_attr" != "$usr_attr" ]; then
                    local attr_value
                    attr_value=$(jq '.attribution' "$template")
                    _atomic_settings_jq ".attribution = $attr_value" || true
                    if [ "$usr_attr" = "null" ]; then
                        print_success "Added attribution block to settings.json"
                    else
                        print_success "Reconciled attribution block in settings.json (commit trailer reset)"
                    fi
                fi
            fi

            # Reconcile .statusLine (framework-owned — points to ~/.claude/statusline.sh).
            # Same replace-on-drift policy as hooks/permissions. Without this, a CLI
            # settings-sync wholesale-replace that drops .statusLine leaves the status
            # bar gone and install --update would NOT restore it (the bar vanished this
            # way once — hooks self-healed, statusLine did not, because it wasn't here).
            if jq -e '.statusLine' "$template" &>/dev/null; then
                local tmpl_sl usr_sl
                tmpl_sl=$(jq -Sc '.statusLine' "$template")
                usr_sl=$(jq -Sc '.statusLine // null' ~/.claude/settings.json)
                if [ "$tmpl_sl" != "$usr_sl" ]; then
                    local sl_value
                    sl_value=$(jq '.statusLine' "$template")
                    _atomic_settings_jq ".statusLine = $sl_value" || true
                    if [ "$usr_sl" = "null" ]; then
                        print_success "Added statusLine block to settings.json"
                    else
                        print_success "Reconciled statusLine block in settings.json"
                    fi
                fi
            fi
        fi
    fi
}

install_analytics() {
    echo -e "\n${BOLD}Installing Analytics (Observability Dashboard):${NC}"

    local src_dir="${SCRIPT_DIR}/observability"

    if [ ! -d "$src_dir" ]; then
        print_info "observability/ directory not found — skipping analytics"
        return 0
    fi

    mkdir -p ~/.claude/analytics

    local errors=0
    for file in collector.py server.py dashboard.html schema.sql; do
        if [ -f "$src_dir/$file" ]; then
            cp "$src_dir/$file" ~/.claude/analytics/"$file"
            print_success "Installed analytics $file"
        else
            print_error "Missing observability/$file"
            ((errors++)) || true
        fi
    done

    if [ "$errors" -gt 0 ]; then
        return 1
    fi

    # Add claude-obs alias (idempotent)
    local shell_rc=""
    if [ -f "$HOME/.zshrc" ]; then
        shell_rc="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        shell_rc="$HOME/.bashrc"
    fi

    if [ -n "$shell_rc" ]; then
        if ! grep -q "claude-obs" "$shell_rc" 2>/dev/null; then
            echo '' >> "$shell_rc"
            echo '# Claude Code Observability' >> "$shell_rc"
            echo 'alias claude-obs="python3 ~/.claude/analytics/collector.py; python3 ~/.claude/analytics/server.py --open"' >> "$shell_rc"
            print_success "Added claude-obs alias to $(basename "$shell_rc")"
        else
            print_skip "claude-obs alias already in $(basename "$shell_rc")"
        fi
    fi
}

write_framework_path_marker() {
    # Records the repo root so the SessionStart healthcheck hook and the watchdog
    # can locate it (they cd here to fork install.sh --update).
    mkdir -p "$HOME/.claude"
    echo "$SCRIPT_DIR" > "$HOME/.claude/.framework-path"
    print_success "Wrote framework path marker ($SCRIPT_DIR)"
}

write_framework_version_marker() {
    # Records the installed framework version and source SHA under ~/.claude so
    # downstream tooling can tell what's deployed.
    mkdir -p "$HOME/.claude"
    local sha="unknown" ahead=0
    if command -v git >/dev/null 2>&1; then
        sha=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
        # Commits between the newest reachable tag and HEAD. Recorded HERE, at install time,
        # so the statusline never has to shell out to git in its hot path.
        local _tag
        _tag=$(git -C "$SCRIPT_DIR" describe --tags --abbrev=0 2>/dev/null || echo "")
        if [ -n "$_tag" ]; then
            ahead=$(git -C "$SCRIPT_DIR" rev-list "${_tag}..HEAD" --count 2>/dev/null || echo 0)
        fi
    fi
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    {
        echo "version=${SCRIPT_VERSION}"
        echo "sha=${sha}"
        echo "ahead=${ahead}"
        echo "installed_at=${ts}"
    } > "$HOME/.claude/.framework-version"
    print_success "Wrote framework version marker (v${SCRIPT_VERSION} @ ${sha})"
}

install_watchdog() {
    # macOS-only launchd watchdog
    if [[ "$(uname -s)" != "Darwin" ]]; then
        print_info "Not macOS — skipping watchdog daemon"
        return 0
    fi

    # REFUSE to touch launchd when running against a HOME that is not this user's real home
    # (a sandbox, a test fixture, a CI runner with HOME overridden).
    #
    # A launchd label is MACHINE-GLOBAL, not per-HOME. Loading a plist from a temporary HOME
    # under the same label silently REPLACES the user's live registration, and when that temp
    # directory is deleted the job points at a plist that no longer exists — the watchdog stops
    # healing and nothing announces it. This was not theoretical: it happened on this machine
    # while sandbox-testing `--update`, and the registration had to be repaired by hand.
    local _rh _u
    _u=$(id -un 2>/dev/null || echo "")
    if [ -n "$_u" ]; then
        if command -v dscl >/dev/null 2>&1; then
            _rh=$(dscl . -read "/Users/$_u" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
        elif command -v getent >/dev/null 2>&1; then
            _rh=$(getent passwd "$_u" 2>/dev/null | cut -d: -f6)
        fi
    fi
    if [ -n "${_rh:-}" ] && [ "$HOME" != "$_rh" ]; then
        print_skip "Watchdog skipped — HOME ($HOME) is not $_u's home ($_rh); a launchd label is machine-global, so loading from a sandbox would hijack the real registration"
        return 0
    fi

    echo -e "\n${BOLD}Installing Watchdog Daemon:${NC}"

    local src_daemon_dir="${SCRIPT_DIR}/global-config/daemon"
    if [ ! -d "$src_daemon_dir" ]; then
        print_info "No daemon/ directory in source — skipping"
        return 0
    fi

    mkdir -p "$HOME/.claude/daemon"

    # Copy watchdog script
    if [ -f "$src_daemon_dir/claude-framework-watchdog.sh" ]; then
        cp "$src_daemon_dir/claude-framework-watchdog.sh" "$HOME/.claude/daemon/claude-framework-watchdog.sh"
        chmod +x "$HOME/.claude/daemon/claude-framework-watchdog.sh"
        print_success "Installed watchdog script"
    fi

    # Copy plist to LaunchAgents. Source plist contains __HOME__ placeholders
    # (no maintainer-specific paths in the public repo); we substitute the
    # caller's $HOME at install time so the daemon works for any user.
    local plist_src="$src_daemon_dir/com.claude-code-agents.framework-watchdog.plist"
    local plist_dst="$HOME/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist"
    if [ -f "$plist_src" ]; then
        mkdir -p "$HOME/Library/LaunchAgents"
        cp "$plist_src" "$plist_dst"
        # BSD sed (macOS) — `-i ''` for in-place edit
        sed -i '' "s|__HOME__|${HOME}|g" "$plist_dst" 2>/dev/null || true
        print_success "Installed plist to LaunchAgents"

        local _plist_marker="$HOME/.claude/.watchdog-plist.sha"
        local _plist_sha
        _plist_sha=$(_sha_file "$plist_dst")

        # Try bootstrap, fall back to load
        local uid
        uid=$(id -u)
        if launchctl bootstrap "gui/$uid" "$plist_dst" 2>/dev/null; then
            print_success "Loaded daemon via launchctl bootstrap"
        elif launchctl load "$plist_dst" 2>/dev/null; then
            print_success "Loaded daemon via launchctl load (fallback)"
        else
            # Already loaded — idempotent
            if launchctl list 2>/dev/null | grep -q claude-code-agents.framework-watchdog; then
                print_skip "Daemon already loaded (re-copy ok)"
            else
                print_info "Could not auto-load daemon (try manually: launchctl bootstrap gui/$uid $plist_dst)"
            fi
        fi

        # Reload the daemon if the plist CONTENT changed since it was last loaded.
        # (The watchdog SCRIPT self-updates via launchd re-exec each interval; a plist
        # change — StartInterval, paths — needs a reload.) A marker tracks the loaded
        # plist's sha so we only reload on a real change. Under the watchdog's OWN
        # --update (CLAUDE_WATCHDOG_RUN=1) we DEFER — a bootout there would kill the
        # in-flight run; the next SessionStart-triggered --update (detached from the
        # daemon) applies it safely, and the marker stays stale until it does.
        local _loaded_sha=""
        [ -f "$_plist_marker" ] && _loaded_sha=$(cat "$_plist_marker" 2>/dev/null)
        if [ -z "$_loaded_sha" ]; then
            echo "$_plist_sha" > "$_plist_marker" 2>/dev/null || true
        elif [ -n "$_plist_sha" ] && [ "$_plist_sha" != "$_loaded_sha" ]; then
            if [ "${CLAUDE_WATCHDOG_RUN:-}" = "1" ]; then
                _health_log "\"event\":\"plist_reload_deferred\",\"reason\":\"under_watchdog\""
                print_skip "Watchdog plist changed — reload deferred (under watchdog; next session applies)"
            else
                launchctl bootout "gui/$uid/com.claude-code-agents.framework-watchdog" 2>/dev/null || true
                launchctl bootstrap "gui/$uid" "$plist_dst" 2>/dev/null || true
                echo "$_plist_sha" > "$_plist_marker" 2>/dev/null || true
                _health_log "\"event\":\"watchdog_plist_reloaded\""
                print_success "Watchdog plist changed — daemon reloaded"
            fi
        fi

        # After a load/reload the watchdog's hourly timer resets, so its next health log is
        # up to StartInterval (~1h) away — which makes the statusline's freshness check show a
        # transient ⚠ (stale) right after a SUCCESSFUL install. Fix it two ways, skipping the
        # watchdog's own --update (CLAUDE_WATCHDOG_RUN=1 — already running, a self-kick re-enters):
        #   1. kickstart the daemon so it does a real health check now (async — logs in a few s);
        #   2. stamp a fresh health event SYNCHRONOUSLY and drop the statusline's 60s cache, so
        #      the bar's freshness check is satisfied immediately (the async kick lands behind
        #      the cache). Both best-effort — never fail the install on them.
        if [ "${CLAUDE_WATCHDOG_RUN:-}" != "1" ]; then
            launchctl kickstart "gui/$uid/com.claude-code-agents.framework-watchdog" 2>/dev/null \
                && print_skip "Kicked watchdog to run a health check now"
            _health_log "\"event\":\"install_reconciled\""
            rm -f /tmp/statusline-fw-cache-* 2>/dev/null || true
        fi
    fi
}

personalize_setup() {
    echo -e "\n${BOLD}Personalizing CLAUDE.md:${NC}"

    local template="${SCRIPT_DIR}/global-config/CLAUDE.md.template"

    if [ ! -f "$template" ]; then
        print_info "CLAUDE.md.template not found — skipping personalization"
        return 0
    fi

    if [ -f ~/.claude/CLAUDE.md ]; then
        print_skip "~/.claude/CLAUDE.md already exists — skipping"
        return 0
    fi

    # Auto-detect from git config
    local detected_name
    local detected_email
    detected_name=$(git config user.name 2>/dev/null || echo "")
    detected_email=$(git config user.email 2>/dev/null || echo "")

    # Prompt for confirmation
    if [ -n "$detected_name" ]; then
        echo -e "  Detected name: ${CYAN}${detected_name}${NC}"
        read -p "  Use this name? [Y/n]: " confirm_name
        if [[ "$confirm_name" =~ ^[Nn]$ ]]; then
            read -p "  Enter your name: " detected_name
        fi
    else
        read -p "  Enter your name: " detected_name
    fi

    if [ -n "$detected_email" ]; then
        echo -e "  Detected email: ${CYAN}${detected_email}${NC}"
        read -p "  Use this email? [Y/n]: " confirm_email
        if [[ "$confirm_email" =~ ^[Nn]$ ]]; then
            read -p "  Enter your git email: " detected_email
        fi
    else
        read -p "  Enter your git email: " detected_email
    fi

    # Generate CLAUDE.md from template
    sed -e "s/__YOUR_NAME__/${detected_name}/g" \
        -e "s/__YOUR_GIT_EMAIL__/${detected_email}/g" \
        "$template" > ~/.claude/CLAUDE.md

    print_success "Created ~/.claude/CLAUDE.md for ${detected_name}"
}

ensure_statusline() {
    # Reconcile the deployed statusline to source: install when absent, REPLACE on drift,
    # skip only when byte-identical. Was install-only ("never overwrites"), which left the
    # --update / --upgrade heal paths unable to re-deploy a changed statusline.sh — so once
    # the source drifted, validate.sh's "deployed == source" assertion looped the watchdog
    # (install --update ran hourly but never converged). Uses the same `diff -q` the
    # validator uses, so "skip" here exactly matches "pass" there.
    local src="${SCRIPT_DIR}/global-config/statusline.sh"
    [ -f "$src" ] || return 0

    if [ -f "$HOME/.claude/statusline.sh" ] && diff -q "$src" "$HOME/.claude/statusline.sh" >/dev/null 2>&1; then
        print_skip "Statusline already up to date"
        return 0
    fi

    mkdir -p "$HOME/.claude"
    cp "$src" "$HOME/.claude/statusline.sh"
    chmod +x "$HOME/.claude/statusline.sh"
    print_success "Reconciled statusline.sh (deployed == source)"
}

# ============================================================================
# Update (non-interactive reconcile under a concurrency lock)
# ============================================================================

update_installation() {
    # Concurrency guard: prevent two concurrent --update runs from racing on
    # ~/.claude/settings.json (jq read-modify-write isn't atomic). Portable
    # lockfile via `mkdir` (atomic on POSIX filesystems) — macOS bash lacks
    # flock(1). Non-blocking: if another install is running, exit cleanly so
    # the healthcheck-hook / watchdog self-heal loop doesn't log errors.
    local lock_dir="$HOME/.claude/.install.lock.d"
    local lock_pid_file="$lock_dir/pid"
    mkdir -p "$HOME/.claude" 2>/dev/null || true
    # Stale-lock detection: a previous install killed mid-run leaves the lock
    # directory but the PID inside is dead. Without this check the framework
    # would deadlock indefinitely (next install always exits "another running").
    if [ -d "$lock_dir" ]; then
        if [ -f "$lock_pid_file" ]; then
            local lock_pid
            lock_pid=$(cat "$lock_pid_file" 2>/dev/null)
            if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
                echo "another install is running (pid $lock_pid) — exiting cleanly" >&2
                return 0
            fi
        fi
        echo "removing stale lock at $lock_dir" >&2
        rm -rf "$lock_dir"
    fi
    if ! mkdir "$lock_dir" 2>/dev/null; then
        echo "lock acquisition failed unexpectedly — exiting" >&2
        return 0
    fi
    echo $$ > "$lock_pid_file"
    # shellcheck disable=SC2064
    trap "rm -rf '$lock_dir' 2>/dev/null || true" EXIT INT TERM

    echo -e "\n${BOLD}Updating Installation${NC}"
    echo "Reconciling ~/.claude against source (non-interactive)"

    # Reconcile the shared set + hooks/settings/analytics/statusline/markers/watchdog.
    # NO personalize_setup — never clobber the user's own ~/.claude/CLAUDE.md edits.
    install_shared_set
    sync_hooks
    install_analytics || print_error "Analytics installation failed"
    ensure_statusline
    sync_output_styles
    write_framework_path_marker
    write_framework_version_marker
    install_watchdog || true
    reconcile_legacy_projects
}

# ============================================================================
# Verification & Summary
# ============================================================================

verify_installation() {
    echo -e "\n${BOLD}=== Verifying Installation ===${NC}"

    local all_good=true
    local d
    for d in agents skills commands rules; do
        if [ -d "$HOME/.claude/$d" ]; then
            print_success "~/.claude/$d present"
        else
            print_error "~/.claude/$d missing"
            all_good=false
        fi
    done

    if [ -d "$HOME/.claude/hooks" ]; then
        print_success "~/.claude/hooks present"
    else
        print_error "~/.claude/hooks missing"
        all_good=false
    fi

    if [ -f "$HOME/.claude/settings.json" ]; then
        print_success "~/.claude/settings.json present"
    else
        print_error "~/.claude/settings.json missing"
        all_good=false
    fi

    if [ "$all_good" = true ]; then
        echo -e "\n${GREEN}${BOLD}✨ Installation Successful!${NC}"
    else
        echo -e "\n${YELLOW}⚠️  Installation completed with warnings${NC}"
    fi
}

print_summary() {
    echo -e "\n${BOLD}=== Installation Summary ===${NC}"
    echo "┌─────────────────────────────┐"
    echo "│ Components Installed:  $(printf "%4d" $STATS_INSTALLED) │"
    echo "│ Components Skipped:    $(printf "%4d" $STATS_SKIPPED) │"
    echo "└─────────────────────────────┘"

    echo -e "\n${BOLD}Installed to:${NC} ~/.claude (user-global — active in every project)"

    echo -e "\n${BOLD}=== Quick Start ===${NC}"
    echo "Just use natural language and agents will auto-activate:"
    echo ""
    echo '  📝 "Design a REST API for user management"'
    echo '  🔒 "Check this code for security issues"'
    echo '  ⚡ "Why is this query running slow?"'
    echo '  🚀 "Deploy this to AWS"'
    echo ""
    echo -e "${CYAN}No per-project setup — describe what you need in any project!${NC}"
}

# ============================================================================
# Main
# ============================================================================

# Copy framework output styles, replacing on drift. Extracted from install_global_config so the
# RECONCILE paths can call it too: install_global_config runs only on a bare install (--update
# deliberately skips it, because it also rewrites settings.json), which meant a changed
# output-style never reached an existing install — deployed content with no reconciliation path.
sync_output_styles() {
    local src_dir="${SCRIPT_DIR}/global-config" style name
    [ -d "$src_dir/output-styles" ] || return 0
    mkdir -p ~/.claude/output-styles 2>/dev/null || true
    for style in "$src_dir"/output-styles/*; do
        [ -f "$style" ] || continue
        name=$(basename "$style")
        case "$name" in ._*) continue ;; esac
        if [ -f ~/.claude/output-styles/"$name" ] && diff -q "$style" ~/.claude/output-styles/"$name" >/dev/null 2>&1; then
            continue
        fi
        cp "$style" ~/.claude/output-styles/"$name"
        print_success "Installed output style $name"
    done
}

# ─────────────────────────────────────────────────────────────────────────────
# --dry-run / --uninstall  (added for team distribution)
#
# A teammate will not run an installer that writes into their ~/.claude and
# installs a background daemon unless they can (a) see exactly what it will do
# and (b) undo it. Both commands below read from ONE source-derived enumeration,
# so "what the framework owns" can never drift between the preview and the removal.
# ─────────────────────────────────────────────────────────────────────────────

# Emit, one path per line, every ~/.claude path this framework OWNS.
# DERIVED FROM SOURCE, never a hardcoded list — the same fail-closed property that
# _prune_framework_orphan_* relies on: a name the source does not ship is not
# emitted, therefore a personal skill/agent/command can never be selected for
# removal. Directories are emitted with a trailing slash.
# Deliberately NOT emitted (user data, never framework-owned):
#   settings.json (merged in place — see _uninstall_clean_settings), CLAUDE.md,
#   analytics/*.jsonl telemetry, snapshots/, projects/, todos/.
_framework_owned_paths() {
    local d f base
    for d in agents rules commands; do
        [ -d "$SCRIPT_DIR/.claude/$d" ] || continue
        for f in "$SCRIPT_DIR/.claude/$d"/*.md; do
            [ -f "$f" ] || continue
            base=$(basename "$f"); case "$base" in ._*) continue ;; esac
            echo "$HOME/.claude/$d/$base"
        done
    done
    if [ -d "$SCRIPT_DIR/.claude/lib" ]; then
        for f in "$SCRIPT_DIR/.claude/lib"/*; do
            [ -f "$f" ] || continue
            base=$(basename "$f"); case "$base" in ._*) continue ;; esac
            echo "$HOME/.claude/lib/$base"
        done
    fi
    if [ -d "$SCRIPT_DIR/.claude/skills" ]; then
        for f in "$SCRIPT_DIR/.claude/skills"/*/; do
            [ -d "$f" ] || continue
            base=$(basename "$f"); case "$base" in ._*) continue ;; esac
            echo "$HOME/.claude/skills/$base/"
        done
    fi
    if [ -d "$SCRIPT_DIR/global-config/hooks" ]; then
        for f in "$SCRIPT_DIR/global-config/hooks"/*; do
            [ -f "$f" ] || continue
            base=$(basename "$f"); case "$base" in ._*) continue ;; esac
            echo "$HOME/.claude/hooks/$base"
        done
    fi
    if [ -d "$SCRIPT_DIR/global-config/output-styles" ]; then
        for f in "$SCRIPT_DIR/global-config/output-styles"/*; do
            [ -f "$f" ] || continue
            base=$(basename "$f"); case "$base" in ._*) continue ;; esac
            echo "$HOME/.claude/output-styles/$base"
        done
    fi
    for base in collector.py server.py dashboard.html schema.sql; do
        [ -f "$SCRIPT_DIR/observability/$base" ] && echo "$HOME/.claude/analytics/$base"
    done
    echo "$HOME/.claude/statusline.sh"
    echo "$HOME/.claude/daemon/claude-framework-watchdog.sh"
    echo "$HOME/.claude/.framework-path"
    echo "$HOME/.claude/.framework-version"
    echo "$HOME/.claude/.watchdog-plist.sha"
}

_WATCHDOG_PLIST="$HOME/Library/LaunchAgents/com.claude-code-agents.framework-watchdog.plist"

cmd_dry_run() {
    local p target n_create=0 n_over=0
    echo -e "${BOLD}DRY RUN — nothing is written.${NC}"
    echo "Source: $SCRIPT_DIR"
    echo "Target: $HOME/.claude"
    echo ""
    while IFS= read -r p; do
        target="${p%/}"
        if [ -e "$target" ]; then
            printf '  %boverwrite%b  %s\n' "$YELLOW" "$NC" "$p"; n_over=$((n_over + 1))
        else
            printf '  %bcreate%b     %s\n' "$GREEN" "$NC" "$p"; n_create=$((n_create + 1))
        fi
    done < <(_framework_owned_paths)
    echo ""
    echo -e "${BOLD}Merged in place (never replaced wholesale):${NC}"
    echo "  $HOME/.claude/settings.json   — hook bindings, statusLine, env"
    echo ""
    # Written by a BARE install but deliberately NOT in the owned set above, because --uninstall
    # must not delete them: CLAUDE.md becomes the user's own file the moment it exists, and a
    # shell rc belongs to the user entirely. Listing them anyway — a preview that hides a write
    # is not a preview, and both of these were missing until a review caught them.
    echo -e "${BOLD}Also written by a bare install (NOT removed by --uninstall):${NC}"
    if [ -f "$HOME/.claude/CLAUDE.md" ]; then
        echo "  $HOME/.claude/CLAUDE.md   — already exists, left untouched"
    else
        echo "  $HOME/.claude/CLAUDE.md   — created from template (prompts for name/email); never overwritten once it exists"
    fi
    local _rc="(none found)"
    [ -f "$HOME/.zshrc" ] && _rc="$HOME/.zshrc" || { [ -f "$HOME/.bashrc" ] && _rc="$HOME/.bashrc"; }
    echo "  $_rc   — one 'claude-obs' alias line appended (idempotent)"
    if [ "$(uname -s)" = "Darwin" ]; then
        echo -e "${BOLD}Background daemon (macOS):${NC}"
        echo "  $_WATCHDOG_PLIST"
        echo "  loaded via launchctl; runs hourly to self-heal drift under ~/.claude"
    else
        echo -e "${BOLD}Background daemon:${NC} skipped — not macOS (no launchd; SessionStart hook only)"
    fi
    echo ""
    echo -e "${BOLD}NOT touched:${NC}"
    echo "  your own skills/agents/commands in ~/.claude (anything this framework does not ship)"
    echo "  ~/.claude/CLAUDE.md · projects/ · todos/ · snapshots/ · analytics/*.jsonl telemetry"
    echo ""
    printf '%s path(s): %s new, %s overwritten.\n' "$((n_create + n_over))" "$n_create" "$n_over"
    echo "Run without --dry-run to apply, or ./install.sh --uninstall to remove."
}

# Fail-closed consent, mirroring _upgrade_confirm_teardown: an explicit --yes, or a
# typed y/yes read from a dedicated fd bound to the CONTROLLING TERMINAL. Never stdin,
# so `curl … | bash` can never have its piped stdin misread as consent. No tty → abort.
_uninstall_confirm() {
    local _count="$1" reply
    if [ "${CLAUDE_UNINSTALL_ASSUME_YES:-0}" = "1" ] || [ "${UNINSTALL_ASSUME_YES:-0}" = "1" ]; then
        _health_log "\"event\":\"uninstall_consent\",\"mode\":\"explicit_yes\",\"count\":$_count"
        return 0
    fi
    if exec 9</dev/tty 2>/dev/null; then
        {
            printf '\nRemove %s framework path(s) from %s/.claude?\n' "$_count" "$HOME"
            printf 'A snapshot is written first. Your own skills, CLAUDE.md, session data and\n'
            printf 'telemetry are NOT removed. [y/N] '
        } >/dev/tty 2>/dev/null
        IFS= read -r -t 30 reply <&9 || reply=""
        exec 9<&-
        case "$reply" in
            y|Y|yes|YES) _health_log "\"event\":\"uninstall_consent\",\"mode\":\"tty_yes\",\"count\":$_count"; return 0 ;;
            *) _health_log "\"event\":\"uninstall_consent\",\"mode\":\"tty_no\",\"count\":$_count"
               echo "Declined — nothing removed."; return 1 ;;
        esac
    fi
    _health_log "\"event\":\"uninstall_consent\",\"mode\":\"noninteractive_abort\",\"count\":$_count"
    echo "No terminal for confirmation — uninstall aborted (nothing removed)."
    echo "  To proceed non-interactively: CLAUDE_UNINSTALL_ASSUME_YES=1 $SCRIPT_DIR/install.sh --uninstall"
    return 1
}

# Strip the framework's own bindings out of settings.json rather than deleting the
# file — it is the user's. Leaving them behind would be worse than doing nothing:
# every hook would point at a script we just removed, and Claude Code would try to
# execute a missing file on every matching event.
_uninstall_clean_settings() {
    local s="$HOME/.claude/settings.json" tmp
    [ -f "$s" ] || return 0
    if ! command -v jq >/dev/null 2>&1; then
        print_error "jq not found — settings.json left as-is; remove ~/.claude/hooks bindings by hand"
        return 0
    fi
    cp "$s" "$s.pre-uninstall.bak" 2>/dev/null || true
    tmp=$(mktemp) || return 0
    if jq '
        (if (.hooks | type) == "object" then
            .hooks |= ( with_entries(
                .value |= ( map( .hooks = ((.hooks // []) | map(select(((.command // "") | tostring) | test("\\.claude/hooks/") | not))) )
                          | map(select(((.hooks // []) | length) > 0)) )
            ) | with_entries(select((.value | length) > 0)) )
         else . end)
        | (if ((.statusLine.command // "") | tostring | test("\\.claude/statusline\\.sh")) then del(.statusLine) else . end)
    ' "$s" > "$tmp" 2>/dev/null && [ -s "$tmp" ]; then
        mv "$tmp" "$s"
        print_success "Removed framework hook/statusLine bindings from settings.json (backup: settings.json.pre-uninstall.bak)"
    else
        rm -f "$tmp"
        print_error "Could not rewrite settings.json — left untouched (backup written)"
    fi
}

cmd_uninstall() {
    local p target n=0 removed=0 snap
    echo -e "${BOLD}Uninstall — removing the framework from ~/.claude${NC}"

    if [ ! -d "$HOME/.claude" ]; then
        print_info "No ~/.claude directory — nothing to uninstall."
        return 0
    fi

    while IFS= read -r p; do
        [ -e "${p%/}" ] && n=$((n + 1))
    done < <(_framework_owned_paths)

    if [ "$n" -eq 0 ]; then
        print_info "No framework files found under ~/.claude — nothing to remove."
        return 0
    fi

    _uninstall_confirm "$n" || return 0

    # Snapshot BEFORE any removal, same convention as the teardown path.
    mkdir -p "$HOME/.claude/snapshots" 2>/dev/null || true
    snap="$HOME/.claude/snapshots/preuninstall-$(date -u +%Y%m%dT%H%M%SZ).tgz"
    if tar -czf "$snap" -C "$HOME" .claude 2>/dev/null; then
        print_success "Snapshot: $snap"
    else
        print_error "Snapshot FAILED — aborting so nothing is removed without a backup"
        return 1
    fi

    # Daemon first: stop it before deleting what it heals, or it may reinstall mid-uninstall.
    if [ -f "$_WATCHDOG_PLIST" ]; then
        launchctl unload "$_WATCHDOG_PLIST" 2>/dev/null || true
        rm -f "$_WATCHDOG_PLIST"
        print_success "Unloaded and removed the launchd watchdog"
    fi

    while IFS= read -r p; do
        target="${p%/}"
        [ -e "$target" ] || continue
        if [ -d "$target" ]; then rm -rf "$target"; else rm -f "$target"; fi
        removed=$((removed + 1))
    done < <(_framework_owned_paths)

    _uninstall_clean_settings

    # Remove now-empty framework dirs, but never a dir that still holds user content.
    for p in agents rules commands lib skills hooks daemon analytics; do
        [ -d "$HOME/.claude/$p" ] || continue
        rmdir "$HOME/.claude/$p" 2>/dev/null && print_skip "Removed empty $HOME/.claude/$p"
    done

    _health_log "\"event\":\"uninstall\",\"removed\":$removed"
    echo ""
    print_success "Removed $removed framework path(s)."
    echo "  Kept: your own skills/agents/commands, CLAUDE.md, projects/, todos/, telemetry, snapshots/"
    echo "  Restore everything:  tar -xzf $snap -C \"\$HOME\""
    echo "  Reinstall:           $SCRIPT_DIR/install.sh"
}

main() {
    print_header

    case "$MODE" in
        install|--install|--team-setup)
            echo -e "${BOLD}Installing Claude Agents (user-global → ~/.claude)${NC}"
            check_prerequisites
            preflight_checks
            install_shared_set
            sync_hooks
            install_global_config
            install_analytics || print_error "Analytics installation failed"
            ensure_statusline
            personalize_setup || true
            write_framework_path_marker
            write_framework_version_marker
            install_watchdog || true
            reconcile_legacy_projects
            verify_installation
            print_summary
            echo -e "${CYAN}Migrating from old per-project .claude copies? Run ./install.sh --upgrade${NC}"
            ;;
        --update)
            echo -e "${BOLD}Running in UPDATE mode (non-interactive reconcile)${NC}"
            update_installation
            ;;
        --upgrade)
            echo -e "${BOLD}Running in UPGRADE mode (reconcile + interactive legacy teardown + self-verify)${NC}"
            check_prerequisites
            preflight_checks
            # Concurrency lock (extracted helper, same scheme as update_installation) so a human
            # --upgrade can't race the hourly watchdog --update on settings.json. --update's own
            # inline lock is left untouched.
            _acquire_install_lock || exit 0
            # Reconcile core — duplicated from update_installation (which is NOT called, so its
            # protected body stays untouched). NO install_global_config / personalize_setup (same
            # as --update; sync_hooks reseeds a deleted settings.json).
            install_shared_set
            sync_hooks
            install_analytics || print_error "Analytics installation failed"
            ensure_statusline
            sync_output_styles
            write_framework_path_marker
            write_framework_version_marker
            install_watchdog || true
            # Interactive legacy teardown: marker dir if armed, else prompt for a safe dir.
            if [ -f "$HOME/.claude/.framework-autonomy" ]; then
                reconcile_legacy_projects "" confirm
            else
                local up_dir; up_dir=$(_upgrade_resolve_dir) || up_dir=""
                [ -n "$up_dir" ] && reconcile_legacy_projects "$up_dir" confirm
            fi
            _upgrade_self_verify
            print_summary
            ;;
        --migrate-legacy)
            # Opt-in autonomous legacy teardown ONLY (marker-gated, idempotent, fast).
            # The watchdog runs this every cycle so a newly-set ~/.claude/.framework-autonomy
            # marker triggers the teardown within the hour — independent of shared-set drift.
            reconcile_legacy_projects
            ;;
        --dry-run|-n)
            cmd_dry_run
            exit 0
            ;;
        --uninstall)
            cmd_uninstall
            exit $?
            ;;
        --help|-h)
            echo "Usage: ./install.sh [OPTION]"
            echo ""
            echo "Installs the Claude Agents framework once into ~/.claude, where"
            echo "Claude Code picks it up in EVERY project (no per-project setup)."
            echo ""
            echo "Options:"
            echo "  (no option)    Install / re-install into ~/.claude (canonical)"
            echo "  --dry-run      Print every path that would be written; changes nothing"
            echo "  --uninstall    Remove the framework from ~/.claude (snapshot first, asks first)"
            echo "  --update       Non-interactive reconcile of ~/.claude (self-heal path)"
            echo "  --upgrade [--yes]  Migrate from old per-project copies: reconcile, confirm + teardown, self-verify"
            echo "  --migrate-legacy  Opt-in teardown of old per-project copies (needs ~/.claude/.framework-autonomy)"
            echo "  --help         Show this help message"
            echo ""
            echo "The SessionStart healthcheck hook and launchd watchdog fork"
            echo "'install.sh --update' automatically to heal drift under ~/.claude."
            exit 0
            ;;
        *)
            print_error "Unknown option: $MODE"
            echo "Run './install.sh --help' for usage."
            exit 1
            ;;
    esac
}

# Run main
main
