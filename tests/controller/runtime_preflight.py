"""Read-only runtime preflight for the controller lifecycle tests.

Reports, as JSON on stdout, whether the running interpreter passes the committed
controller_process._executable_binding gate and whether controller_process.boot_identity()
is available. Both are the exact preconditions LifecycleTest.setUpClass checks before it
skips the whole class, so a CI run that enforces this preflight cannot silently skip it.

Modes:
  --observe  record refusals/unavailability as data and exit 0 (diagnostic only)
  (default)  enforce: exit 1 unless the interpreter binds and the boot identity is
             available; an unknown result is never reported as ready

Output is limited to uid/euid, the executable alias and realpath, their lstat/stat
uid/mode/device/inode, the binding outcome or refusal code, and a boot-identity boolean.
It never prints the environment, credentials or the boot identifier itself. It changes
nothing: no chmod/chown, no file writes, no bytecode, no network, no new dependency.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # set before further imports: loading the module writes no .pyc

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
from pathlib import Path  # noqa: E402

SCHEMA = 'sdlc-controller/runtime-preflight/v1'
ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / '.claude/skills/delivery/scripts/controller_process.py'


def load_process_module():
    spec = importlib.util.spec_from_file_location('delivery_controller_process', MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError('controller_process spec unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def describe(stat_call, path: str) -> dict:
    try:
        info = stat_call(path)
    except OSError as err:
        return {'observed': False, 'error': type(err).__name__, 'errno': err.errno}
    return {'observed': True, 'uid': info.st_uid, 'mode': f'{info.st_mode:07o}',
            'isSymlink': stat.S_ISLNK(info.st_mode), 'device': info.st_dev,
            'inode': info.st_ino}


def executable_facts(path: str) -> dict:
    if not path or not os.path.isabs(path):
        return {'path': path or None, 'realpath': None, 'lstat': None, 'stat': None}
    real = os.path.realpath(path)
    return {'path': path, 'realpath': real, 'lstat': describe(os.lstat, path),
            'stat': describe(os.stat, real)}


def probe_binding(module, path: str) -> dict:
    try:
        module._executable_binding(path)
    except module.ProcessError as err:
        return {'status': 'refused', 'refusal': err.code}
    except OSError as err:
        return {'status': 'unknown', 'refusal': None, 'error': type(err).__name__}
    return {'status': 'bound', 'refusal': None}


def probe_boot(module) -> bool | None:
    try:
        return module.boot_identity() is not None
    except OSError:
        return None  # unknown, never reported as available


def current_ids() -> dict:
    if not hasattr(os, 'getuid'):
        return {'uid': None, 'euid': None}
    return {'uid': os.getuid(), 'euid': os.geteuid()}


def build_report(observe: bool) -> dict:
    report = {'schema': SCHEMA, 'mode': 'observe' if observe else 'enforce', **current_ids(),
              'executable': executable_facts(sys.executable), 'moduleLoaded': False,
              'moduleError': None, 'binding': None, 'bootIdentityAvailable': None}
    try:
        module = load_process_module()
    except Exception as err:  # recorded as data and fails enforce mode; never treated as ready
        report['moduleError'] = type(err).__name__
        report['verdict'] = 'unknown'
        return report
    report['moduleLoaded'] = True
    report['binding'] = probe_binding(module, sys.executable)
    report['bootIdentityAvailable'] = probe_boot(module)
    is_ready = report['binding']['status'] == 'bound' and report['bootIdentityAvailable'] is True
    report['verdict'] = 'ready' if is_ready else 'not-ready'
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--observe', action='store_true',
                        help='record refusals as data and exit 0 (diagnostic only)')
    args = parser.parse_args(argv)
    report = build_report(args.observe)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.observe:
        return 0
    return 0 if report['verdict'] == 'ready' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
