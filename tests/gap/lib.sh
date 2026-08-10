#!/bin/bash
# ============================================================================
# tests/gap/lib.sh — shared helpers for the mutation (gap) test suite
# ============================================================================
# Sourced by run.sh and by every mutations/*.sh file.
#
# Every helper here is FAIL-CLOSED: if an edit's anchor is not found, the helper
# returns non-zero and the runner reports the mutation as STALE rather than
# letting a no-op edit be scored against a guard. A mutation that silently fails
# to apply would make the guard look green — the exact defect class this suite
# exists to catch, reproduced inside the test harness.
#
# bash 3.2 compatible (macOS /bin/bash 3.2.57): no associative arrays, no
# `wait -n`, no `mapfile`, no `${var^^}`, no `local -n`.
# ============================================================================

# ---- mut_python <file> <<'PY' ... PY ---------------------------------------
# Run an inline python3 edit script against <file>. The script receives the
# absolute path as sys.argv[1]. Fails if the file content is unchanged, so a
# regex that stopped matching is reported instead of silently doing nothing.
mut_python() {
    local target="$1"
    local script before after
    if [ ! -f "$target" ]; then
        echo "mutation anchor missing: no such file: $target" >&2
        return 1
    fi
    script=$(cat)
    before=$(_gap_hash "$target")
    if ! printf '%s' "$script" | python3 - "$target"; then
        echo "mutation script errored on: $target" >&2
        return 1
    fi
    after=$(_gap_hash "$target")
    if [ "$before" = "$after" ]; then
        echo "mutation was a NO-OP on: $target (anchor text has moved or changed)" >&2
        return 1
    fi
    return 0
}

# ---- mut_replace <file> <old-literal> <new-literal> [max] -------------------
# Literal (non-regex) substring replacement. Fails if <old> is absent.
mut_replace() {
    local target="$1" old="$2" new="$3" maxn="${4:-1}"
    MUT_OLD="$old" MUT_NEW="$new" MUT_MAX="$maxn" mut_python "$target" <<'PY'
import os, sys
p = sys.argv[1]
old, new = os.environ['MUT_OLD'], os.environ['MUT_NEW']
n = int(os.environ['MUT_MAX'])
s = open(p, encoding='utf-8').read()
if old not in s:
    sys.stderr.write("anchor not found: %r\n" % old[:80])
    sys.exit(1)
open(p, 'w', encoding='utf-8').write(s.replace(old, new) if n <= 0 else s.replace(old, new, n))
PY
}

# ---- mut_replace_all <file> <old-literal> <new-literal> --------------------
mut_replace_all() { mut_replace "$1" "$2" "$3" 0; }

# ---- mut_delete_lines <file> <python-regex> --------------------------------
# Delete every line matching the regex. Fails if none matched.
mut_delete_lines() {
    local target="$1" pat="$2"
    MUT_PAT="$pat" mut_python "$target" <<'PY'
import os, re, sys
p = sys.argv[1]
pat = re.compile(os.environ['MUT_PAT'])
lines = open(p, encoding='utf-8').read().splitlines(True)
kept = [l for l in lines if not pat.search(l)]
if len(kept) == len(lines):
    sys.stderr.write("no line matched: %s\n" % os.environ['MUT_PAT'])
    sys.exit(1)
open(p, 'w', encoding='utf-8').writelines(kept)
PY
}

# ---- mut_insert_after <file> <anchor-literal> <text> -----------------------
# Insert <text> as its own line immediately after the first line containing
# <anchor-literal>. Fails if the anchor line is absent.
mut_insert_after() {
    local target="$1" anchor="$2" text="$3"
    MUT_ANCHOR="$anchor" MUT_TEXT="$text" mut_python "$target" <<'PY'
import os, sys
p = sys.argv[1]
anchor, text = os.environ['MUT_ANCHOR'], os.environ['MUT_TEXT']
lines = open(p, encoding='utf-8').read().splitlines(True)
for i, l in enumerate(lines):
    if anchor in l:
        lines.insert(i + 1, text.rstrip("\n") + "\n")
        open(p, 'w', encoding='utf-8').writelines(lines)
        sys.exit(0)
sys.stderr.write("anchor line not found: %r\n" % anchor[:80])
sys.exit(1)
PY
}

# ---- mut_insert_before <file> <anchor-literal> <text> ----------------------
# Insert <text> immediately BEFORE the first line containing <anchor-literal>,
# reusing that line's indentation (so injected python stays syntactically valid).
mut_insert_before() {
    local target="$1" anchor="$2" text="$3"
    MUT_ANCHOR="$anchor" MUT_TEXT="$text" mut_python "$target" <<'PY'
import os, sys
p = sys.argv[1]
anchor, text = os.environ['MUT_ANCHOR'], os.environ['MUT_TEXT']
lines = open(p, encoding='utf-8').read().splitlines(True)
for i, l in enumerate(lines):
    if anchor in l:
        indent = l[:len(l) - len(l.lstrip())]
        lines.insert(i, indent + text.strip() + "\n")
        open(p, 'w', encoding='utf-8').writelines(lines)
        sys.exit(0)
sys.stderr.write("anchor line not found: %r\n" % anchor[:80])
sys.exit(1)
PY
}

# ---- mut_append <file> <text> ----------------------------------------------
mut_append() {
    local target="$1" text="$2"
    MUT_TEXT="$text" mut_python "$target" <<'PY'
import os, sys
p = sys.argv[1]
with open(p, 'a', encoding='utf-8') as fh:
    fh.write("\n" + os.environ['MUT_TEXT'].rstrip("\n") + "\n")
PY
}

# ---- _gap_hash <file> -------------------------------------------------------
# Content hash that works on both macOS (shasum) and Linux (sha1sum/shasum).
_gap_hash() {
    if command -v shasum >/dev/null 2>&1; then
        shasum "$1" | awk '{print $1}'
    elif command -v sha1sum >/dev/null 2>&1; then
        sha1sum "$1" | awk '{print $1}'
    else
        wc -c < "$1" | tr -d ' '
    fi
}

# ---- _gap_strip_ansi --------------------------------------------------------
# validate.sh colourises its output; strip the escapes so patterns can match
# across a whole line (e.g. "FAIL Fail-open guard: ...").
_gap_strip_ansi() {
    local esc
    esc=$(printf '\033')
    sed "s/${esc}\[[0-9;]*m//g"
}

# ---- gap_copy_repo <src> <dest> --------------------------------------------
# Copy exactly the parts of the repository validate.sh reads. NEVER copies .git,
# and NEVER runs inside the source tree, so the real working copy — which a human
# may be editing concurrently — is only ever read.
gap_copy_repo() {
    local src="$1" dest="$2" d f
    mkdir -p "$dest" || return 1
    # tests and .github are included because validate.sh reads them: the gap-test-suite guard
    # asserts tests/gap/run.sh + mutations exist and are wired into .github/workflows/validate.yml.
    # Omitting them made the UNMUTATED copy fail that guard, which correctly aborted the whole run
    # ("the baseline does not pass, so no verdict below can be trusted") rather than scoring 21
    # mutations against a tree validate.sh already rejected. The copy must contain everything
    # validate.sh reads, or the baseline is not a baseline.
    for d in .claude global-config observability tests .github; do
        [ -d "$src/$d" ] && { cp -R "$src/$d" "$dest/" || return 1; }
    done
    # Top-level regular files, minus the ones nothing reads and one 15MB media
    # stray that would dominate the copy cost.
    find "$src" -maxdepth 1 -type f -print | while IFS= read -r f; do
        case "$(basename "$f")" in
            *.mp3|.DS_Store) continue ;;
        esac
        cp "$f" "$dest/" 2>/dev/null || true
    done
    [ -f "$dest/validate.sh" ] || { echo "copy failed: no validate.sh in $dest" >&2; return 1; }
    chmod +x "$dest/validate.sh" 2>/dev/null || true
    return 0
}

# ---- gap_clone <src-copy> <dest> -------------------------------------------
# Clone an existing scratch copy. Mutation working dirs are cloned from the
# pristine snapshot rather than re-read from the repository: a human editing the
# real tree mid-run would otherwise give different mutations different source
# content, and the pristine-vs-mutated diff would stop meaning "the mutation".
gap_clone() {
    local src="$1" dest="$2"
    mkdir -p "$dest" || return 1
    cp -R "$src/." "$dest/" || return 1
    chmod +x "$dest/validate.sh" 2>/dev/null || true
    return 0
}
