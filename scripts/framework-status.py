#!/usr/bin/env python3
"""Read-only status for the shared Claude/Codex framework installs.

Reports the source repository HEAD, each integration's installed source SHA and owned
integrity, native CLI presence, optional Codex hook configuration and MCP connectivity.
It reuses the existing read-only checkers (`codex/framework.py --check` and
`scripts/install-delivery.py --check`); it never writes, creates directories, takes a
lock, repairs anything, invokes the broad Claude installer or `validate.sh`, runs project
scripts, probes the network or starts MCP servers. It reads only the framework's own
ownership manifests, the owned files those checkers compare, the managed instruction
block, and the plain `~/.claude/.framework-version` marker — never `config.toml`,
`auth.json`, `settings.json`, environment secrets or `.env` files.

States are distinguished precisely: `not_installed` (no ownership manifest), `clean`
(the checker reports no pending change), `drift` (owned bytes differ from the current
source build), and `error` (a corrupt/foreign manifest, tampered owned file, symlink or
unreadable input). A missing integration is reported as `not_installed`, never healthy.
Codex hook trust and MCP connectivity are reported as UNKNOWN: trust is granted in the
native `/hooks` review and server tools are discovered at runtime, neither of which this
command inspects.

Scope: `--user` (default) inspects the user-global Codex home and the Claude home;
`--project PATH` inspects a project Codex install at PATH while still reporting the
user-global Claude home. `--claude-home PATH` overrides the Claude home (default
`~/.claude`; the environment is not consulted). `--json` prints machine-readable output.

Exit status: 0 when nothing is wrong (every inspected integration is clean or not
installed), 1 when any installed integration has drifted, 2 when any integration is in an
error state or the command itself could not complete. Python 3.11+ (the Codex integrity
check additionally needs the declared Codex dependencies).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent

# Read-only means the source tree too: never emit .pyc caches while importing the checker
# modules below. Set before any import so no codex/__pycache__ entry is written.
sys.dont_write_bytecode = True

try:  # The Codex checker needs PyYAML; degrade to an explicit error if it is absent.
    sys.path.insert(0, str(REPO / 'codex'))
    import framework
except Exception:  # noqa: BLE001 - any import failure means the Codex checker is unavailable here.
    framework = None


def _load_delivery():
    spec = importlib.util.spec_from_file_location('install_delivery', REPO / 'scripts/install-delivery.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repository_sha() -> str | None:
    try:
        if framework is not None:
            return framework.head_sha()
        # PyYAML absent (the checker import failed): still ignore inherited Git selectors so a
        # foreign GIT_DIR or config injection in the environment cannot misattribute our HEAD.
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        return subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'],
                                       text=True, stderr=subprocess.DEVNULL, env=env).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _classify(message: str) -> str:
    return 'drift' if 'drift' in message.lower() else 'error'


def codex_status(root: Path, user: bool) -> dict:
    result: dict = {'integration': 'codex', 'scope': 'user' if user else 'project', 'root': str(root)}
    manifest_file = root / '.codex/framework/manifest.json'
    if not os.path.lexists(manifest_file):
        return {**result, 'present': False, 'state': 'not_installed'}
    if framework is None:
        return {**result, 'present': True, 'state': 'error',
                'detail': 'Codex checker unavailable; install codex/requirements.txt'}
    try:
        meta = framework.load_manifest(root)
    except (ValueError, OSError):
        return {**result, 'present': True, 'state': 'error', 'detail': 'unreadable or invalid manifest'}
    if not meta.get('files'):
        return {**result, 'present': False, 'state': 'not_installed'}
    manifest_user = meta.get('user')
    if isinstance(manifest_user, bool) and manifest_user != user:
        # The requested scope must not be silently reinterpreted as the installed scope: a
        # user-install is never reported as a clean project install, or vice versa.
        requested = 'user' if user else 'project'
        installed = 'user' if manifest_user else 'project'
        return {**result, 'present': True, 'state': 'error',
                'detail': f'requested {requested}-scope status but this install records a {installed}-scope manifest'}
    hooks_configured = bool(meta.get('hooks')) and os.path.lexists(root / '.codex/hooks.json')
    result.update(present=True, installed_source_sha=meta.get('source_sha'),
                  owned_files=len(meta['files']), hooks_configured=hooks_configured,
                  hook_trust='UNKNOWN' if hooks_configured else 'n/a')
    try:
        framework.install(root, check=True, user=user)
        result['state'] = 'clean'
    except ValueError as err:
        result['state'] = _classify(str(err))
    except (OSError, subprocess.CalledProcessError):
        result['state'] = 'error'
    return result


def delivery_status(home: Path) -> dict:
    result: dict = {'integration': 'claude_delivery', 'root': str(home)}
    manifest_file = home / '.sdlc-delivery/manifest.json'
    if not home.is_dir() or not os.path.lexists(manifest_file):
        return {**result, 'present': False, 'state': 'not_installed'}
    delivery = _load_delivery()
    try:
        meta = delivery.load_manifest(home)
    except (delivery.InstallError, OSError):
        return {**result, 'present': True, 'state': 'error', 'detail': 'unreadable or invalid manifest'}
    if not meta.get('files'):
        return {**result, 'present': False, 'state': 'not_installed'}
    result.update(present=True, installed_source_sha=meta.get('source_sha'), owned_files=len(meta['files']))
    try:
        delivery.run(home, REPO, check=True)
        result['state'] = 'clean'
    except delivery.InstallError as err:
        result['state'] = _classify(str(err))
    except OSError:
        result['state'] = 'error'
    return result


def claude_framework_status(home: Path) -> dict:
    result: dict = {'integration': 'claude_framework', 'root': str(home)}
    marker = home / '.framework-version'
    if not os.path.lexists(marker) or marker.is_symlink() or not marker.is_file():
        return {**result, 'present': False}
    values: dict[str, str] = {}
    try:
        for line in marker.read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and key in ('version', 'sha', 'installed_at'):
                values[key] = value
    except OSError:
        return {**result, 'present': False, 'detail': 'unreadable version marker'}
    # The broad Claude install has no read-only Python integrity checker; validate.sh and
    # the installer are not invoked here, so integrity is reported as not checked.
    return {**result, 'present': True, 'version': values.get('version'),
            'installed_source_sha': values.get('sha'), 'installed_at': values.get('installed_at'),
            'integrity': 'not_checked'}


def collect(*, user: bool, project: Path | None, claude_home: Path) -> dict:
    codex_root = Path.home() if user else project.absolute()
    integrations = [codex_status(codex_root, user),
                    delivery_status(claude_home),
                    claude_framework_status(claude_home)]
    return {
        'repository': {'root': str(REPO), 'sha': repository_sha()},
        'integrations': integrations,
        'native_cli': {'codex': shutil.which('codex') is not None,
                       'claude': shutil.which('claude') is not None},
        'mcp': {'connectivity': 'UNKNOWN',
                'note': 'MCP servers are discovered and their tool schemas verified at runtime; '
                        'this read-only command does not connect to or start them.'},
    }


def exit_code(report: dict) -> int:
    states = {item.get('state') for item in report['integrations']}
    if 'error' in states:
        return 2
    if 'drift' in states:
        return 1
    return 0


def render(report: dict) -> str:
    lines = [f'repository {report["repository"]["sha"] or "unknown"} ({report["repository"]["root"]})', '']
    for item in report['integrations']:
        head = f'{item["integration"]}: {item.get("state", "present" if item.get("present") else "absent")}'
        lines.append(head)
        for key in ('scope', 'root', 'installed_source_sha', 'version', 'installed_at', 'owned_files',
                    'hooks_configured', 'hook_trust', 'integrity', 'detail'):
            if key in item:
                lines.append(f'  {key}: {item[key]}')
    cli = report['native_cli']
    lines += ['', f'native cli: codex={cli["codex"]} claude={cli["claude"]}',
              f'mcp connectivity: {report["mcp"]["connectivity"]}']
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--user', action='store_true', help='inspect the user-global installs (default)')
    scope.add_argument('--project', type=Path, help='inspect a project Codex install at this path')
    parser.add_argument('--claude-home', type=Path, help='Claude home to inspect (default: ~/.claude)')
    parser.add_argument('--json', action='store_true', help='print machine-readable JSON')
    args = parser.parse_args()
    user = args.project is None
    claude_home = (args.claude_home or Path.home() / '.claude').absolute()
    try:
        report = collect(user=user, project=args.project, claude_home=claude_home)
    except Exception as err:  # noqa: BLE001 - a read-only status run should still report, then exit 2.
        print(f'FAIL: {err}', file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render(report))
    return exit_code(report)


if __name__ == '__main__':
    raise SystemExit(main())
