#!/bin/bash
# ============================================================================
# tests/gap/run.sh — executable mutation tests for validate.sh's guards
# ============================================================================
# WHY THIS EXISTS
#
# validate.sh carries prose comments of the form "Gap-tested by mutation: X ->
# FAIL; unmodified -> PASS". Those are comments. Nobody re-runs them, and at
# least one was measurably false: a comment claiming "25 evasion strings -> 0
# leaks" sat above a guard that leaked three of them. Separately, a later repair
# (adding EXIT_PARTIAL) made an earlier guard's detection branch unreachable, so
# it printed PASS over an injected fail-open for hours. A comment cannot catch
# either. This suite re-runs every such claim on every push.
#
# CONTRACT PER MUTATION
#   1. copy the repository to a throwaway scratch dir (the real tree is only read)
#   2. inject one specific known defect into the copy
#   3. run validate.sh inside the copy and require BOTH a non-zero exit AND the
#      specific expected FAIL line
#   4. discard the copy; the unmutated copy is separately asserted to PASS
#   5. exit non-zero if any guard failed to catch its defect
#
# HOW THIS SUITE AVOIDS BEING THE THING IT POLICES
#   * BASELINE gate — the unmutated copy must exit 0. If it does not, every
#     mutation result would be meaningless, so the run aborts instead of
#     reporting a wall of green "caught" results for the wrong reason.
#   * NEGATIVE CONTROL — a deliberately harmless edit must NOT be caught. If the
#     harness reports a harmless edit as caught, its own machinery is producing
#     spurious failures and every CAUGHT verdict is suspect.
#   * STALE detection — every mutation helper asserts its anchor was found and
#     that file content actually changed. A mutation that silently no-ops would
#     otherwise make its guard look green.
#   * GUARD-RAN check — each mutation names the PASS line its guard emits, and
#     that line must be present in the baseline. A guard skipped in this
#     environment (missing python3, restructured file) is reported, never
#     silently credited.
#   * --prove — re-runs every mutation with the injection skipped and requires
#     the verdict to flip to NOT-CAUGHT. This is the deliberate-break check: an
#     assertion that fires with or without the defect is worthless.
#
# ENVIRONMENT
#   validate.sh is invoked with an isolated empty HOME so results are identical
#   on a machine with ~/.claude installed and on a clean CI checkout. validate.sh
#   degrades its installed-environment checks to WARN when the framework is not
#   installed (see its "Framework not installed at ~/.claude" branch), and every
#   guard under test here reads repository content only.
#
# ADDING A MUTATION
#   Drop a file in mutations/ declaring four things and a mutate() function:
#     MUT_DESC          one line: the defect being injected, in product terms
#     MUT_CLAIM         which prose claim in validate.sh this makes executable
#     MUT_BASELINE_PASS substring of the PASS line the guard emits when clean
#     MUT_EXPECT        ERE that must appear in the FAIL output; make it specific
#                       enough that it cannot match a clean run (--prove enforces this)
#     mutate() { ... }  edits the copy at $1 using the mut_* helpers from lib.sh
#
# bash 3.2 compatible. Run: /bin/bash tests/gap/run.sh
# ============================================================================

set -uo pipefail

GAP_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$GAP_DIR/../.." && pwd)
# shellcheck source=tests/gap/lib.sh
. "$GAP_DIR/lib.sh"

JOBS="${GAP_JOBS:-4}"
PROVE=false
FILTER=""
KEEP=false

usage() {
    cat <<'EOF'
Usage: tests/gap/run.sh [options]

  --prove         additionally run every mutation with the injection SKIPPED and
                  require the verdict to flip to NOT-CAUGHT (deliberate-break check)
  --only <glob>   run only mutations whose id matches the shell glob
  --jobs <n>      parallel validate.sh runs (default 4, or $GAP_JOBS)
  --keep          keep the scratch working directory for inspection
  -h, --help      this text
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prove) PROVE=true ;;
        --only)  shift; FILTER="${1:-}" ;;
        --jobs)  shift; JOBS="${1:-4}" ;;
        --keep)  KEEP=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage; exit 2 ;;
    esac
    shift
done

# ---- prerequisites (fail closed and loud, never skip into green) -----------
_missing=""
command -v python3 >/dev/null 2>&1 || _missing="$_missing python3"
command -v jq      >/dev/null 2>&1 || _missing="$_missing jq"
if [ -n "$_missing" ]; then
    echo "gap-tests: REQUIRED tool(s) missing:$_missing" >&2
    echo "gap-tests: validate.sh needs them, so a run without them would prove nothing." >&2
    exit 2
fi
[ -f "$REPO_ROOT/validate.sh" ] || { echo "gap-tests: no validate.sh at $REPO_ROOT" >&2; exit 2; }

WORK=$(mktemp -d "${TMPDIR:-/tmp}/gapmut.XXXXXX") || exit 2
FAKE_HOME="$WORK/home"
mkdir -p "$FAKE_HOME" "$WORK/results"

cleanup() {
    if $KEEP; then
        echo "gap-tests: scratch kept at $WORK"
        return
    fi
    # Belt and braces before a recursive delete: only ever this run's own
    # mktemp -d, never a path that could have been reassigned.
    case "$WORK" in
        */gapmut.??????) chmod -R u+w "$WORK" 2>/dev/null; rm -rf "$WORK" 2>/dev/null ;;
        *) echo "gap-tests: refusing to remove unexpected scratch path: $WORK" >&2 ;;
    esac
}
trap cleanup EXIT

echo "=============================================================="
echo " gap-tests — mutation tests for validate.sh's regression guards"
echo "=============================================================="
echo " repo    : $REPO_ROOT"
echo " scratch : $WORK"
echo " bash    : ${BASH_VERSION}"
echo " HOME    : isolated empty dir (results identical installed vs clean checkout)"
echo " jobs    : $JOBS   prove-mode: $PROVE"
echo

# ---- pristine copy + baseline ----------------------------------------------
PRISTINE="$WORK/pristine"
if ! gap_copy_repo "$REPO_ROOT" "$PRISTINE"; then
    echo "gap-tests: could not copy the repository" >&2; exit 2
fi

run_validate() {  # $1 = copy dir, $2 = output file ; echoes exit code
    # Deliberately NOT --quiet: quiet suppresses PASS lines, and the guard-ran
    # check below reads a guard's PASS line out of the baseline. Asserting on a
    # stream that cannot contain the evidence is how a check ends up verifying
    # nothing at all.
    local dir="$1" out="$2" rc
    ( cd "$dir" && HOME="$FAKE_HOME" ./validate.sh ) >"$out" 2>&1
    rc=$?
    _gap_strip_ansi <"$out" >"$out.plain" && mv "$out.plain" "$out"
    echo "$rc"
}

printf 'baseline: running validate.sh on the unmutated copy ... '
BASE_OUT="$WORK/baseline.out"
BASE_RC=$(run_validate "$PRISTINE" "$BASE_OUT")
if [ "$BASE_RC" != "0" ]; then
    echo "FAILED (exit $BASE_RC)"
    echo
    echo "gap-tests ABORTED: the UNMUTATED copy does not pass validate.sh, so no"
    echo "mutation verdict below could be trusted. Fix the tree first. Failures:"
    grep -E '^\s*FAIL ' "$BASE_OUT" | sed 's/^/    /'
    exit 1
fi
echo "PASS (exit 0) — contract step 4 satisfied"

# ---- negative control -------------------------------------------------------
# A harmless edit must NOT be reported as caught. If it is, the harness itself
# manufactures failures and every CAUGHT verdict below is worthless.
printf 'control : harmless edit must NOT be caught ......... '
CTRL="$WORK/control"
gap_clone "$PRISTINE" "$CTRL" >/dev/null 2>&1
printf '\n# gap-tests negative control: this edit changes nothing validate.sh reads\n' >>"$CTRL/LICENSE"
CTRL_RC=$(run_validate "$CTRL" "$WORK/control.out")
CONTROL_OK=true
if [ "$CTRL_RC" = "0" ]; then
    echo "PASS (exit 0, not caught)"
else
    echo "BROKEN (exit $CTRL_RC)"
    CONTROL_OK=false
fi

# ---- collect mutations ------------------------------------------------------
MUT_LIST="$WORK/mutations.list"
# GAP_MUT_DIR points the runner at an alternative mutation directory. Its reason
# for existing is that the harness must itself be testable: point it at probe
# mutations that are deliberately broken (one that changes nothing a guard reads,
# one whose MUT_EXPECT matches a clean run, one whose anchor does not exist) and
# the runner must report NOTFIRED / UNPROVEN / STALE respectively. Those probes
# stay out of the shipped mutation set.
MUT_DIR="${GAP_MUT_DIR:-$GAP_DIR/mutations}"
: >"$MUT_LIST"
for m in "$MUT_DIR"/*.sh; do
    [ -f "$m" ] || continue
    id=$(basename "$m" .sh)
    if [ -n "$FILTER" ]; then
        case "$id" in $FILTER) ;; *) continue ;; esac
    fi
    echo "$m" >>"$MUT_LIST"
done
TOTAL=$(grep -c . "$MUT_LIST" 2>/dev/null || echo 0)
if [ "$TOTAL" -eq 0 ]; then
    echo "gap-tests: no mutations found in $MUT_DIR — nothing was verified" >&2
    exit 2
fi
echo "mutations: $TOTAL"
echo

# ---- one mutation ------------------------------------------------------------
# Runs in a subshell so a mutation file's variables and functions cannot leak
# into the next one. Writes a single result line to $WORK/results/<id>.
run_one() {
    local mfile="$1" skip_injection="$2"
    local id dir out rc verdict detail
    id=$(basename "$mfile" .sh)
    dir="$WORK/w-$id"
    [ "$skip_injection" = "true" ] && dir="$WORK/p-$id"
    out="$dir.out"

    MUT_DESC=""; MUT_EXPECT=""; MUT_BASELINE_PASS=""; MUT_CLAIM=""
    # shellcheck disable=SC1090
    . "$mfile"

    if [ -z "$MUT_EXPECT" ] || [ -z "$MUT_BASELINE_PASS" ] || [ -z "$MUT_CLAIM" ]; then
        _emit "$id" "BADMUT" "mutation file must declare MUT_EXPECT, MUT_BASELINE_PASS and MUT_CLAIM" "$skip_injection"
        return
    fi

    # The guard must have actually run in THIS environment before its silence
    # can be read as evidence of anything.
    if ! grep -qF -- "$MUT_BASELINE_PASS" "$BASE_OUT"; then
        _emit "$id" "NOGUARD" "guard did not run in baseline (expected PASS line absent): $MUT_BASELINE_PASS" "$skip_injection"
        return
    fi

    if ! gap_clone "$PRISTINE" "$dir" >"$dir.copy.log" 2>&1; then
        _emit "$id" "COPYFAIL" "could not clone the pristine snapshot (see $dir.copy.log)" "$skip_injection"
        return
    fi

    if [ "$skip_injection" != "true" ]; then
        if ! mutate "$dir" >"$dir.mut.log" 2>&1; then
            _emit "$id" "STALE" "mutation did not apply: $(tr '\n' ' ' <"$dir.mut.log" | cut -c1-160)" "$skip_injection"
            return
        fi
        # Second net: the helpers assert their own anchors, but require the tree
        # to differ from pristine as well, so a helper bug cannot fake a defect.
        if diff -rq "$PRISTINE" "$dir" >/dev/null 2>&1; then
            _emit "$id" "STALE" "mutation left the copy byte-identical to pristine" "$skip_injection"
            return
        fi
    fi

    rc=$(run_validate "$dir" "$out")
    local found=false
    grep -Eq -- "$MUT_EXPECT" "$out" && found=true

    # The exit code and the pattern are scored SEPARATELY and both are reported.
    # Collapsing them (short-circuiting on rc==0) would hide the one failure mode
    # prove-mode exists to expose: a MUT_EXPECT loose enough to match a clean run.
    if [ "$rc" != "0" ] && $found; then
        verdict="CAUGHT"
        detail=$(grep -E -- "$MUT_EXPECT" "$out" | head -1 | sed 's/^ *//' | cut -c1-150)
    elif [ "$rc" = "0" ] && $found; then
        verdict="LOOSE"
        detail="MUT_EXPECT matched output of a run that PASSED (exit 0) — the pattern does not identify a failure"
    elif [ "$rc" != "0" ]; then
        verdict="WRONGFAIL"
        detail="validate.sh failed (exit $rc) but NOT with the expected line; got: $(grep -E '^ *FAIL ' "$out" | head -1 | sed 's/^ *//' | cut -c1-120)"
    else
        verdict="NOTFIRED"
        detail="validate.sh exited 0 and the expected FAIL line never appeared"
    fi
    _emit "$id" "$verdict" "$detail" "$skip_injection"
}

_emit() {  # id verdict detail skip_injection
    local id="$1" verdict="$2" detail="$3" skip="$4" file
    file="$WORK/results/$id"
    [ "$skip" = "true" ] && file="$WORK/results/$id.prove"
    # Tabs are the record separator; validate.sh output may contain them.
    detail=$(printf '%s' "$detail" | tr '\t' ' ')
    printf '%s\t%s\t%s\n' "$id" "$verdict" "$detail" >"$file"
}

# ---- run mutations in batches (bash 3.2 has no `wait -n`) -------------------
run_batch() {  # $1 = skip_injection
    local skip="$1" n=0 mfile
    while IFS= read -r mfile; do
        [ -n "$mfile" ] || continue
        run_one "$mfile" "$skip" &
        n=$((n + 1))
        if [ "$n" -ge "$JOBS" ]; then wait; n=0; fi
    done <"$MUT_LIST"
    wait
}

run_batch false
$PROVE && run_batch true

# ---- report ------------------------------------------------------------------
FAILED=0
PASSED=0
echo "---- mutation results ------------------------------------------------"
while IFS= read -r mfile; do
    [ -n "$mfile" ] || continue
    id=$(basename "$mfile" .sh)
    rfile="$WORK/results/$id"
    if [ ! -f "$rfile" ]; then
        printf '  %-8s %s\n' "NORESULT" "$id"
        FAILED=$((FAILED + 1)); continue
    fi
    verdict=$(cut -f2 <"$rfile")
    detail=$(cut -f3 <"$rfile")
    desc=$(sed -n 's/^MUT_DESC="\(.*\)"$/\1/p' "$mfile" | head -1)

    prove_note=""
    prove_ok=true
    if $PROVE; then
        pfile="$WORK/results/$id.prove"
        if [ ! -f "$pfile" ]; then
            prove_note="  [prove: NO RESULT]"; prove_ok=false
        else
            pverdict=$(cut -f2 <"$pfile")
            case "$pverdict" in
                # Defect absent, assertion silent — the assertion is sensitive to
                # the defect and to nothing else in reach.
                NOTFIRED) prove_note="  [prove: ok — with the defect removed the assertion does not fire]" ;;
                CAUGHT|LOOSE)
                    prove_note="  [prove: UNPROVEN — the assertion fires WITHOUT the defect ($pverdict); this test would pass whether or not the guard works]"
                    prove_ok=false ;;
                *)  prove_note="  [prove: unexpected verdict $pverdict on a defect-free tree]"; prove_ok=false ;;
            esac
        fi
    fi

    if [ "$verdict" = "CAUGHT" ] && $prove_ok; then
        printf '  \033[0;32mCAUGHT\033[0m   %s\n' "$id"
        [ -n "$desc" ] && printf '           defect : %s\n' "$desc"
        printf '           guard  : %s\n' "$detail"
        [ -n "$prove_note" ] && printf '          %s\n' "$prove_note"
        PASSED=$((PASSED + 1))
    else
        printf '  \033[0;31m%s\033[0m %s\n' "$verdict" "$id"
        [ -n "$desc" ] && printf '           defect : %s\n' "$desc"
        printf '           result : %s\n' "$detail"
        [ -n "$prove_note" ] && printf '          %s\n' "$prove_note"
        FAILED=$((FAILED + 1))
    fi
done <"$MUT_LIST"

echo "----------------------------------------------------------------------"
echo "  baseline (unmutated copy passes) : PASS"
if $CONTROL_OK; then
    echo "  negative control (harmless edit) : PASS"
else
    echo "  negative control (harmless edit) : FAIL — harness manufactures failures"
    FAILED=$((FAILED + 1))
fi
echo "  mutations caught                 : $PASSED / $TOTAL"
echo "  mutations NOT caught / stale     : $FAILED"
echo "----------------------------------------------------------------------"

if [ "$FAILED" -gt 0 ]; then
    echo
    echo "gap-tests FAILED: a guard did not detect the defect it claims to detect,"
    echo "or a mutation no longer applies (its anchor moved). Either way the prose"
    echo "claim in validate.sh is now unsupported — fix the guard or the mutation."
    exit 1
fi
echo
echo "gap-tests PASSED: every guard detected its injected defect."
exit 0
