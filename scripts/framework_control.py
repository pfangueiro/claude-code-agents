#!/usr/bin/env python3
"""One entry point for this framework source checkout: status, settings and update.

./framework [status]  Read-only. Installed files against their own install records (the portable
                      helper .claude/lib/framework_settings.py), then a comparison with THIS
                      checkout (scripts/framework-status.py). The comparison is skipped, and
                      reported as incomplete, when a Codex or Claude delivery install record
                      already needs attention. Writes nothing and never prompts.
./framework settings  Optional extras and display preferences (the same helper). It saves only
                      when a settings option is given.
./framework update    The safe updater for an existing installation (scripts/framework_update.py),
                      loaded only for this command; its own --help lists what it accepts.

The root ./framework launcher only loads this module; nothing is installed on PATH. Python 3.11+,
standard library only. The Codex part of the source comparison also needs the declared Codex
dependencies, exactly as scripts/framework-status.py does, and reports an error without them.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import TextIO

sys.dont_write_bytecode = True  # read-only includes writing no .pyc files into the checkout

REPO = Path(__file__).resolve().parent.parent
INVOCATION = './framework'
SCHEMA = 'sdlc-framework-control/v1'
HELPER = REPO / '.claude/lib/framework_settings.py'
SOURCE_CHECKER = REPO / 'scripts/framework-status.py'
UPDATER = REPO / 'scripts/framework_update.py'
COMMANDS = ('status', 'settings', 'update')
INTEGRATION_LABELS = {'codex': 'Codex files', 'claude_delivery': 'Claude delivery files',
                      'claude_framework': 'Claude framework files'}
COMPARISON_LABELS = {'clean': 'matches this checkout', 'drift': 'differs from this checkout',
                     'error': 'could not be compared', 'not_installed': 'not installed'}
# Manifest-backed installs the legacy source checker would trust and read again by its own, broader
# rules. When the installed helper already flags one, that checker is not run at all.
GUARDED_COMPONENTS = ('codex', 'claude_delivery')
GUARD_REASON = ('installed files need attention (ownership or integrity) before they can be compared with this '
                'checkout, so the comparison was not run; see the installed-file results')
HELP = f'''usage: {INVOCATION} [status | settings | update] [options]

One entry point for this framework source checkout.

  status    Default. Read-only: shows whether installed framework files match their own
            install records, then compares them with this checkout. Writes nothing and
            never prompts. Options: --json, --detail concise|full, --project PATH,
            --claude-home PATH ({INVOCATION} status --help).
  settings  Optional extras and how to change each one. Saves display preferences or
            reviewed extras only when you pass a settings option ({INVOCATION} settings --help).
  update    The safe updater for an existing installation: it plans first and changes files
            only on its explicit apply step ({INVOCATION} update --help). It does not pull new
            source and does not install for the first time (use ./install.sh or
            ./install-codex.sh for that).

From another folder, run the installed helper (status and settings only):
  python3 ~/.claude/lib/framework_settings.py    Claude install
  python3 ~/.codex/framework/settings.py         Codex user install

Exit status: 0 nothing needs attention; 1 something needs attention or differs from this
checkout; 2 a check could not complete or reported an error, or a usage error.
'''


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load {path.name}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compare_with_checkout(project: Path | None, claude_home: Path) -> dict:
    """The existing source checker's report; a failure is reported with exit 2, never hidden."""
    try:
        checker = load_module('framework_status', SOURCE_CHECKER)
        report = checker.collect(user=project is None, project=project, claude_home=claude_home)
        code = checker.exit_code(report)
    except Exception as exc:  # any failure means the comparison is incomplete; it is reported, not swallowed
        return {'state': 'incomplete', 'exit': 2,
                'detail': f'the comparison could not run ({type(exc).__name__}: {exc})'}
    return {'state': 'completed', 'exit': code, 'report': report}


def guarded_attention(installed: dict, attention: str) -> list[str]:
    return [component['id'] for component in installed['components']
            if component['id'] in GUARDED_COMPONENTS and component['state'] == attention]


def skipped_comparison(blocked_by: list[str]) -> dict:
    return {'state': 'incomplete', 'exit': 2, 'blocked_by': blocked_by, 'detail': GUARD_REASON}


def _broad_claude_text(item: dict) -> str:
    if not item.get('present'):
        return 'not installed' + (f' ({item["detail"]})' if item.get('detail') else '')
    recorded = item.get('installed_source_sha') or 'unknown'
    return (f'not compared file by file (no per-file install record); its marker records commit {recorded}, '
            'which is abbreviated and does not prove the installed bytes')


def render_comparison(comparison: dict) -> list[str]:
    if comparison['state'] != 'completed':
        return ['Compared with this checkout: not completed', f'  {comparison["detail"]}']
    report = comparison['report']
    sha = report['repository'].get('sha')
    lines = [f'Compared with this checkout ({sha[:12] if sha else "commit unknown"}):']
    for item in report['integrations']:
        name = item.get('integration')
        label = INTEGRATION_LABELS.get(name, str(name))
        if name == 'claude_framework':
            lines.append(f'  {label}: {_broad_claude_text(item)}')
            continue
        scope = f' ({item["scope"]})' if item.get('scope') else ''
        text = COMPARISON_LABELS.get(item.get('state'), 'unknown')
        if item.get('detail'):
            text += f' - {item["detail"]}'
        lines.append(f'  {label}{scope}: {text}')
    if comparison['exit'] == 1:
        lines.append(f'  To bring an existing install up to this checkout, start with {INVOCATION} update --help')
    return lines


def run_status(argv: list[str], out: TextIO, err: TextIO) -> int:
    helper = load_module('framework_settings', HELPER)
    try:
        args = helper.build_parser(INVOCATION).parse_args(['status', *argv])
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.source is not None:
        err.write(f'--source is not used by {INVOCATION}: it always compares with this checkout.\n')
        return 2
    home = Path.home()
    claude_home = (args.claude_home or home / '.claude').expanduser().absolute()
    project = args.project.expanduser().absolute() if args.project else None
    installed = helper.installed_report(home=home, claude_home=claude_home, project=project, cwd=Path.cwd(),
                                        source=REPO, invocation=INVOCATION,
                                        claude_home_given=args.claude_home is not None)
    installed['source'].update(comparison='this_checkout', note='Compared with this checkout below.')
    blocked_by = guarded_attention(installed, helper.ATTENTION)
    comparison = skipped_comparison(blocked_by) if blocked_by else compare_with_checkout(project, claude_home)
    code = max(helper.exit_code(installed), comparison['exit'])
    if args.json:
        payload = {'schema': SCHEMA, 'exit_code': code, 'installed': installed, 'source_comparison': comparison}
        out.write(json.dumps(payload, indent=2, sort_keys=True) + '\n')
        return code
    detail = args.detail or installed['preferences']['display']['detail']
    out.write(helper.render_status(installed, detail) + '\n' + '\n'.join(render_comparison(comparison)) + '\n')
    return code


def run_settings(argv: list[str]) -> int:
    helper = load_module('framework_settings', HELPER)
    return helper.main(['settings', *argv], invocation=INVOCATION)


def run_update(argv: list[str], err: TextIO) -> int:
    if not UPDATER.is_file():
        err.write(f'The safe updater ({UPDATER.name}) is not in this checkout; nothing was changed.\n')
        return 2
    updater = load_module('framework_update', UPDATER)
    result = updater.main(list(argv))
    return result if isinstance(result, int) else 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    out, err = sys.stdout, sys.stderr
    if arguments and arguments[0] in ('-h', '--help', 'help'):
        out.write(HELP)
        return 0
    if arguments and arguments[0] in COMMANDS:
        command, rest = arguments[0], arguments[1:]
    else:
        command, rest = 'status', arguments
    if command == 'update':
        return run_update(rest, err)
    if command == 'settings':
        return run_settings(rest)
    return run_status(rest, out, err)


if __name__ == '__main__':
    raise SystemExit(main())
