"""Behavior tests for the Claude PostToolUse edit-feedback hook
(`global-config/hooks/post-edit-lint.sh`).

Each case drives the exact source hook with a JSON payload on stdin, a disposable
HOME and project tree, and local fake `eslint` executables that record argv/cwd and
simulate `--fix` by rewriting the target file. No real HOME, personal settings,
network, package manager or real ESLint is used. The hook is edit-time feedback
only: these cases pin that it is file-scoped and check-only (no `--fix`, no
rewrite), uses only the nearest project-local ESLint (never PATH or npx) while
keeping the session's working directory for config discovery, bounds
its output, terminates, and never blocks the edit.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / 'global-config/hooks/post-edit-lint.sh'
BASH = shutil.which('bash') or '/bin/bash'
HAVE_JQ = shutil.which('jq') is not None
TIMEOUT = 10

# Records cwd/argv, rewrites the target when any --fix flag is passed, and emits
# controlled lint output selected by a marker in the target file.
FAKE_ESLINT = r'''#!/bin/sh
log=@LOG@
{
  printf 'cwd=%s\n' "$(pwd -P)"
  for arg in "$@"; do printf 'arg=%s\n' "$arg"; done
  printf 'end\n'
} >> "$log"
fix=0
target=
for arg in "$@"; do
  case "$arg" in
    --fix|--fix-dry-run) fix=1 ;;
    -*) ;;
    *) target=$arg ;;
  esac
done
if [ "$fix" = 1 ] && [ -n "$target" ]; then
  printf '// rewritten-by-fake-fix\n' >> "$target"
fi
if [ -n "$target" ] && grep -q LINT_CRASH "$target" 2>/dev/null; then
  printf 'fake-config-error\n'
  exit 2
fi
if [ -n "$target" ] && grep -q LINT_FLOOD "$target" 2>/dev/null; then
  i=0
  while [ "$i" -lt 200 ]; do
    printf '  %s:1  error  flood-rule  Flood problem\n' "$i"
    i=$((i + 1))
  done
  exit 1
fi
if [ -n "$target" ] && grep -q LINT_ERROR "$target" 2>/dev/null; then
  printf '%s\n  1:1  error  fake-rule  Fake problem\n' "$target"
  exit 1
fi
exit 0
'''

# A PATH-resolved tool the hook must never use (no global or downloaded ESLint).
PATH_POISON = '#!/bin/sh\nprintf "%s\\n" "$0" >> @SENTINEL@\nexit 0\n'


@unittest.skipUnless(HAVE_JQ, 'jq required (the hook parses its stdin payload with jq)')
class PostEditLintHook(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='claude-post-edit-')).resolve()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        for ancestor in self.base.parents:
            if os.access(ancestor / 'node_modules/.bin/eslint', os.X_OK):
                self.skipTest(f'an ancestor of the temporary directory provides ESLint: {ancestor}')
        self.home = self.base / 'home'
        self.home.mkdir()
        self.path_bin = self.base / 'path-bin'
        self.path_bin.mkdir()
        self.path_sentinel = self.base / 'PATH_TOOL_CALLED'
        for name in ('eslint', 'npx'):
            self.script(self.path_bin / name,
                        PATH_POISON.replace('@SENTINEL@', shlex.quote(str(self.path_sentinel))))
        self.project = self.base / 'project'
        self.project_log = self.install_eslint(self.project)

    # -- fixtures -------------------------------------------------------------
    def script(self, path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        path.chmod(0o755)

    def install_eslint(self, root: Path) -> Path:
        name = str(root.relative_to(self.base)).replace(os.sep, '_')
        log = self.base / f'eslint-{name}.log'
        self.script(root / 'node_modules/.bin/eslint',
                    FAKE_ESLINT.replace('@LOG@', shlex.quote(str(log))))
        return log

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def invocations(self, log: Path) -> list[dict]:
        if not log.exists():
            return []
        calls, current = [], None
        for line in log.read_text().splitlines():
            if line.startswith('cwd='):
                current = {'cwd': line[4:], 'args': []}
            elif line.startswith('arg=') and current is not None:
                current['args'].append(line[4:])
            elif line == 'end' and current is not None:
                calls.append(current)
                current = None
        return calls

    def run_hook(self, file_path=None, cwd=None, payload=None):
        if payload is None:
            payload = {'tool_name': 'Edit', 'tool_input': {'file_path': str(file_path)}}
        env = {'HOME': str(self.home),
               'PATH': f'{self.path_bin}{os.pathsep}{os.environ.get("PATH", "")}'}
        try:
            return subprocess.run([BASH, str(HOOK)], input=json.dumps(payload), capture_output=True,
                                  text=True, cwd=str(cwd or self.base), env=env, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            self.fail(f'hook did not terminate within {TIMEOUT}s for payload {payload!r}')

    # -- check-only, file-scoped ----------------------------------------------
    def test_check_only_never_passes_fix_or_rewrites_file(self):
        source = self.write(self.project / 'src/app.ts', 'export const value = 1;\n')
        before = source.read_bytes()
        result = self.run_hook(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), before, 'the hook rewrote the edited file')
        calls = self.invocations(self.project_log)
        self.assertEqual(len(calls), 1, calls)
        self.assertFalse([arg for arg in calls[0]['args'] if arg.startswith('--fix')],
                         f'a fix flag reached ESLint: {calls[0]["args"]}')
        positional = [arg for arg in calls[0]['args'] if not arg.startswith('-')]
        self.assertEqual(positional, [str(source)], 'lint must target only the edited file')

    def test_eslint_keeps_the_session_cwd(self):
        source = self.write(self.project / 'src/app.ts', 'export const value = 1;\n')
        # The binary is hoisted to the project root, but ESLint runs from the session's working
        # directory, so configuration is discovered as the project's own invocation would.
        package = self.project / 'packages/hoisted'
        nested = self.write(package / 'src/b.ts', 'export const b = 1;\n')
        runs = [(source, self.base), (source, self.project), (nested, package)]
        for target, cwd in runs:
            result = self.run_hook(target, cwd=cwd)
            self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.invocations(self.project_log)
        self.assertEqual([(call['cwd'], [arg for arg in call['args'] if not arg.startswith('-')]) for call in calls],
                         [(str(cwd), [str(target)]) for target, cwd in runs])

    def test_nearest_project_eslint_is_used(self):
        package = self.project / 'packages/pkg'
        package_log = self.install_eslint(package)
        nested = self.write(package / 'src/a.ts', 'export const a = 1;\n')
        self.run_hook(nested)
        self.assertEqual(len(self.invocations(package_log)), 1)
        self.assertEqual(self.invocations(self.project_log), [], 'an outer ESLint ran for a nested project')
        # A package without its own ESLint uses the nearest ancestor install (hoisted monorepo).
        hoisted = self.project / 'packages/hoisted'
        self.write(hoisted / 'package.json', '{}\n')
        other = self.write(hoisted / 'src/b.ts', 'export const b = 1;\n')
        self.run_hook(other)
        outer_calls = self.invocations(self.project_log)
        self.assertEqual(len(outer_calls), 1, outer_calls)
        self.assertIn(str(other), outer_calls[0]['args'])

    # -- missing inputs are safe no-ops ------------------------------------------
    def test_missing_tool_is_silent_and_never_falls_back_to_path_or_npx(self):
        bare = self.write(self.base / 'bare/src/app.ts', 'export const x = 1; // LINT_ERROR\n')
        before = bare.read_bytes()
        result = self.run_hook(bare)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('ESLint', result.stdout)
        self.assertNotIn('fake-rule', result.stdout)
        self.assertFalse(self.path_sentinel.exists(), 'a PATH eslint/npx was executed')
        self.assertEqual(bare.read_bytes(), before)

    def test_missing_file_runs_nothing(self):
        (self.project / 'src').mkdir(parents=True)
        missing = self.project / 'src/missing.ts'
        result = self.run_hook(missing)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(missing.exists(), 'the hook created the missing file')
        self.assertEqual(self.invocations(self.project_log), [])
        self.assertEqual(result.stdout.strip(), '')

    def test_payload_without_path_is_noop(self):
        result = self.run_hook(payload={'tool_name': 'Edit', 'tool_input': {}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '')
        self.assertEqual(self.invocations(self.project_log), [])

    def test_non_source_file_is_not_linted(self):
        doc = self.write(self.project / 'README.md', '# notes\n')
        result = self.run_hook(doc)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.invocations(self.project_log), [])

    # -- relative payload paths --------------------------------------------------
    def test_relative_path_is_resolved_against_cwd(self):
        source = self.write(self.project / 'src/rel.ts', 'export const rel = 1;\n')
        result = self.run_hook('src/rel.ts', cwd=self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.invocations(self.project_log)
        self.assertEqual(len(calls), 1, calls)
        self.assertIn(str(source), calls[0]['args'])

    def test_relative_path_without_local_eslint_terminates(self):
        bare = self.base / 'bare'
        self.write(bare / 'src/rel.ts', 'export const rel = 1;\n')
        result = self.run_hook('src/rel.ts', cwd=bare)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.path_sentinel.exists())

    # -- feedback is reported, bounded and nonblocking -----------------------------
    def test_lint_problem_is_reported_without_blocking(self):
        source = self.write(self.project / 'src/bad.ts', 'export const bad = 1; // LINT_ERROR\n')
        result = self.run_hook(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('fake-rule', result.stdout)

    def test_lint_output_is_bounded(self):
        source = self.write(self.project / 'src/flood.ts', 'export const f = 1; // LINT_FLOOD\n')
        result = self.run_hook(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        flood = [line for line in result.stdout.splitlines() if 'flood-rule' in line]
        self.assertTrue(flood, 'lint problems were not reported at all')
        self.assertLessEqual(len(flood), 20, 'lint feedback is not bounded')
        self.assertIn('truncated', result.stdout.lower())

    def test_eslint_failure_is_reported_without_blocking(self):
        source = self.write(self.project / 'src/crash.ts', 'export const c = 1; // LINT_CRASH\n')
        result = self.run_hook(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('fake-config-error', result.stdout)

    def test_clean_file_produces_no_lint_feedback(self):
        source = self.write(self.project / 'src/clean.ts', 'export const clean = 1;\n')
        result = self.run_hook(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '')
        self.assertEqual(len(self.invocations(self.project_log)), 1)

    # -- debug-statement warnings are kept -----------------------------------------
    def test_debug_statement_warning_kept_for_typescript(self):
        source = self.write(self.project / 'src/debug.ts', 'console.log("x");\n')
        result = self.run_hook(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('debug statements', result.stdout)

    def test_debug_statement_warning_kept_for_python(self):
        source = self.write(self.project / 'tool.py', 'print("x")\n')
        result = self.run_hook(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('debug statements', result.stdout)
        self.assertEqual(self.invocations(self.project_log), [])


if __name__ == '__main__':
    unittest.main()
