#!/usr/bin/env python3
"""Friendly, read-only framework readiness view plus owner display preferences.

`status` (the default) answers "are the framework files in place?" with one headline:
Framework files ready, Installed - not fully checked, Needs attention or Not installed.
Installed files are compared only with their own install records (the Claude delivery and
Codex ownership manifests, plus the Codex managed AGENTS.md block and hook choice), inside a
fixed allowlist of shipped paths, never following a symlink. The broad Claude install has no per-file record, so it is reported as Not checked,
never Ready. Comparing an install with the current source is a separate, source-side check
(`./framework status` inside the source repository).

Optional extras are read from their existing native records and kept distinct: On, Off,
Unknown, Not checked, Needs setup, Unavailable and Needs attention. A file that merely exists
(a lint approval list, an active model policy, a controller binding) is Not checked, never On:
its contents and validity are not read here. AI sign-in, model runs,
MCP connections and the host status line are host-only and always Unknown here: an install
record or a CLI on PATH never proves them.

`settings` shows the same extras with how to change each one (an honest handoff to the
existing installer, native UI or owner policy; this helper switches nothing on or off) and
manages display preferences and reviewed states in one private owner file,
~/.config/sdlc/framework-preferences.json. That file only shapes presentation: it grants no
permission and holds no account, credential, model identifier or operational switch. It is
written only on an explicit settings action. `settings --review` is a guided flow that runs
only on an interactive terminal; --json, CI and other non-interactive runs never prompt.

It never starts processes, services or schedules, never contacts the network or a provider,
and never reads credentials, provider configuration, ledgers, lint approvals or policy
contents (the model policy is opened only for its `version` and `active` fields).
Exit status: 0 when nothing needs attention, 1 when something does, 2 for a usage error or
a refused preference change. Python 3.11+, standard library only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import sys
import tempfile
from typing import Callable, TextIO

SCHEMA = 'sdlc-framework-settings/v1'
PREFERENCES_VERSION = 1
CATALOG_VERSION = 1
PREFERENCES_FILE = '.config/sdlc/framework-preferences.json'
MODEL_POLICY_FILE = '.config/sdlc/model-policy.json'
LINT_REGISTRY_FILE = '.codex/framework/lint-projects.json'
CODEX_MANIFEST = '.codex/framework/manifest.json'
DELIVERY_MANIFEST = '.sdlc-delivery/manifest.json'
CLAUDE_MARKER = '.framework-version'
SOURCE_LOCATOR = '.framework-path'
CONTROLLER_BINDING = 'sdlc-controller.binding'

MAX_JSON_BYTES = 1 << 20
# Install manifests get their own finite budget: the delivery manifest legitimately embeds
# base64 copies of adopted originals, so it can exceed the private-file JSON cap above.
MAX_INSTALL_RECORD_BYTES = 16 << 20
MAX_SMALL_BYTES = 64 << 10
MAX_OWNED_FILE_BYTES = 16 << 20
MAX_OWNED_FILES = 4096
SHA256 = re.compile(r'[0-9a-f]{64}')
DISPLAY_VALUE = re.compile(r'[A-Za-z0-9._+:-]{1,80}')
IS_MACOS = sys.platform == 'darwin'

# Exactly the Codex paths the installer ships (codex/framework.py build()). The private lint
# approval list, runtime evidence and the manifest itself share .codex/framework/ but are never
# install-owned, so a manifest naming them is refused before any payload is read.
CODEX_SKILL_PREFIX = '.agents/skills/sdlc-'
CODEX_AGENT_DIR = '.codex/agents/'
CODEX_HOOKS_FILE = '.codex/hooks.json'
CODEX_FRAMEWORK_FILES = frozenset(f'.codex/framework/{name}' for name in (
    'rules.md', 'inventory.json', 'mcp.example.toml', 'statusline.example.toml', 'hook.py', 'lint.py', 'settings.py'))
INSTRUCTION_BEGIN = '<!-- sdlc-codex:begin -->'
INSTRUCTION_END = '<!-- sdlc-codex:end -->'
DELIVERY_SKILLS = ('delivery', 'repo-context', 'verified-handoff')
DELIVERY_SINGLE_FILES = ('rules/delivery.md', 'commands/commit-pr.md')

READY, NOT_CHECKED, ATTENTION, NOT_INSTALLED = 'ready', 'not_checked', 'needs_attention', 'not_installed'
ON, OFF, UNKNOWN, NEEDS_SETUP, UNAVAILABLE = 'on', 'off', 'unknown', 'needs_setup', 'unavailable'
CORE, REFERENCE = 'core', 'reference'
STATE_LABELS = {
    READY: 'Ready', NOT_CHECKED: 'Not checked', ATTENTION: 'Needs attention', NOT_INSTALLED: 'Not installed',
    ON: 'On', OFF: 'Off', UNKNOWN: 'Unknown', NEEDS_SETUP: 'Needs setup', UNAVAILABLE: 'Unavailable',
    CORE: 'Core', REFERENCE: 'Reference only',
}
HEADLINES = {
    READY: 'Framework files ready',
    NOT_CHECKED: 'Installed - not fully checked',
    ATTENTION: 'Needs attention',
    NOT_INSTALLED: 'Not installed',
}
REVIEW_VALUES = {ON: 'enabled', OFF: 'disabled'}
DETAIL_LEVELS = ('concise', 'full')
REMINDER_MODES = ('changes-only', 'off')
PREFERENCE_KEYS = frozenset({'version', 'display', 'reviewed', 'catalog_reviewed'})
DISPLAY_KEYS = frozenset({'detail', 'reminders'})
COMMANDS = ('status', 'settings')

FEATURES: dict[str, dict] = {
    'claude.analytics': {
        'label': 'Claude usage dashboard (analytics)', 'short': 'analytics', 'reviewable': True,
        'about': 'Optional dashboard over your local session logs; it never runs on its own.',
        'change': 'To turn it on, run ./install.sh --with-analytics in the framework source folder. Leaving the '
                  'flag out keeps your current choice and never turns it off; ask the agent if you want it removed.'},
    'claude.watchdog': {
        'label': 'Claude health watchdog', 'short': 'watchdog', 'reviewable': True,
        'about': 'Optional hourly health check and backups on macOS; it reports problems and never repairs.',
        'change': 'To turn it on, run ./install.sh --with-watchdog in the framework source folder (macOS only). '
                  'Leaving the flag out keeps your current choice; ask the agent if you want it removed.'},
    'claude.notifications': {
        'label': 'Claude desktop notifications', 'short': 'notifications', 'reviewable': True,
        'about': 'Optional desktop alert when Claude needs you.',
        'change': 'To turn it on, run ./install.sh --with-notifications in the framework source folder. '
                  'Leaving the flag out keeps your current choice; ask the agent if you want it removed.'},
    'claude.post_edit_lint': {
        'label': 'Claude post-edit lint feedback', 'short': 'post-edit lint', 'reviewable': False,
        'about': 'Part of the core install: quick lint feedback after an edit. It is a hint, not a check result.',
        'change': 'Core feature; it comes with the framework files.'},
    'codex.hooks': {
        'label': 'Codex evidence hooks', 'short': 'Codex hooks', 'reviewable': True,
        'about': 'Optional Codex hooks that record evidence and protect credential files from direct edits.',
        'change': 'Install with ./install-codex.sh --user --hooks (or --project PATH --hooks), then approve them '
                  'in Codex with /hooks. Installing alone does not make them run.'},
    'codex.approved_lint': {
        'label': 'Codex approved post-edit lint', 'short': 'Codex lint', 'reviewable': True,
        'about': 'Optional lint after Codex edits, only in projects you approved yourself.',
        'change': 'You approve projects in ~/.codex/framework/lint-projects.json (the installer never writes it); '
                  'it also needs Codex hooks. The agent can prepare an entry for you to confirm.'},
    'model_policy': {
        'label': 'Model selection policy', 'short': 'model policy', 'reviewable': True,
        'about': 'Optional owner policy that picks an approved model per task; without it your normal model '
                 'settings apply.',
        'change': 'It needs a passing evaluation and your approval first; see the delivery skill reference '
                  'references/model-policy.md. The policy is ~/.config/sdlc/model-policy.json and this helper '
                  'never writes it.'},
    'controller': {
        'label': 'Delivery controller (this repository)', 'short': 'controller', 'reviewable': False,
        'about': 'Optional foreground tool that carries an approved plan through delivery for one repository.',
        'change': 'Set it up per repository with the controller setup command (docs/PERSISTENT-DELIVERY.md); '
                  'its setup, policy and runs stay separate from this view.'},
    'hook_templates': {
        'label': 'Prompt/agent hook templates', 'short': 'hook templates', 'reviewable': False,
        'about': 'Reference examples only; they are never wired in automatically.',
        'change': 'Copy a template into your own settings if you want one; the agent can help.'},
}
REVIEWABLE = tuple(feature_id for feature_id, info in FEATURES.items() if info['reviewable'])
HOST_ONLY = {
    'ai_login': ('AI sign-in', 'Checked by your host app; this helper never reads credentials or account settings.'),
    'model_execution': ('Model runs', 'Only a real run shows that a model works; not checked here.'),
    'mcp': ('MCP connections', 'Servers connect at runtime inside the host; check them with /mcp there.'),
    'footer': ('Status line / footer', 'Shown and configured by the host app; not reported here.'),
}


class RefusedError(Exception):
    """An unsafe, malformed or stale input: it is not used and nothing is written."""


# ---------------------------------------------------------------- safe reading

def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')  # never the key itself: it may come from a private file
        result[key] = value
    return result


def _reject_constant(name: str) -> object:
    raise ValueError(f'non-finite number {name}')


def parse_json(data: bytes, limit: int = MAX_JSON_BYTES) -> object:
    if len(data) > limit:
        raise RefusedError('the file is larger than expected')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_reject_duplicates,
                          parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as err:
        raise RefusedError(f'not valid JSON ({err})') from err


def symlink_in_path(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            return candidate
    return None


def _open_flags() -> int:
    return os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)


def read_regular(path: Path, limit: int) -> bytes:
    """Bytes of a regular file reached without any symlink; FileNotFoundError when absent."""
    link = symlink_in_path(path)
    if link is not None:
        raise RefusedError(f'reached through a symlink ({link})')
    fd = os.open(path, _open_flags())
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RefusedError('not a regular file')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise RefusedError('larger than expected')
    return data


def _check_owner_dir(directory: Path) -> None:
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode):
        raise RefusedError(f'{directory} is not a directory')
    if info.st_uid != os.geteuid():
        raise RefusedError(f'{directory} is not owned by you')
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RefusedError(f'{directory} can be changed by other users')


def read_private_file(path: Path) -> bytes | None:
    """Bytes of an owner-only file (mode within 0600, owned by you, private parent); None when absent."""
    link = symlink_in_path(path)
    if link is not None:
        raise RefusedError(f'{path} is reached through a symlink ({link})')
    try:
        fd = os.open(path, _open_flags())
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise RefusedError(f'{path} is not a regular file')
        if info.st_uid != os.geteuid():
            raise RefusedError(f'{path} is not owned by you')
        if info.st_mode & 0o177:
            raise RefusedError(f'{path} must be private to you (mode 0600)')
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise RefusedError(f'{path} is larger than expected')
    _check_owner_dir(path.parent)
    return data


# ---------------------------------------------------------------- install records

def read_marker(claude_home: Path) -> dict[str, list[str]] | None:
    """Key/value lines of the Claude install marker, parsed as data; None when absent."""
    try:
        data = read_regular(claude_home / CLAUDE_MARKER, MAX_SMALL_BYTES)
    except FileNotFoundError:
        return None
    fields: dict[str, list[str]] = {}
    for line in data.decode('utf-8').splitlines():
        key, separator, value = line.partition('=')
        if separator:
            fields.setdefault(key, []).append(value)
    return fields


def load_marker_safely(claude_home: Path) -> tuple[dict[str, list[str]] | None, str | None]:
    try:
        return read_marker(claude_home), None
    except (RefusedError, OSError, ValueError) as err:
        return None, str(err)


def marker_value(fields: dict[str, list[str]], key: str) -> str | None:
    values = fields.get(key, [])
    if len(values) != 1 or not DISPLAY_VALUE.fullmatch(values[0]):
        return None
    return values[0]


def marker_selection(fields: dict[str, list[str]], name: str) -> str:
    """enabled, disabled or unknown; a missing, duplicate or odd value is never read as off."""
    value = marker_value(fields, name)
    return value if value in ('enabled', 'disabled') else 'unknown'


def safe_relative(rel: object) -> bool:
    if not isinstance(rel, str) or not rel or rel.startswith('/') or '\\' in rel:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in rel):
        return False
    return all(part not in ('', '.', '..') and part.casefold() != '.git' for part in rel.split('/'))


def codex_allowed(rel: str) -> bool:
    if rel == CODEX_HOOKS_FILE or rel in CODEX_FRAMEWORK_FILES:
        return True
    if rel.startswith(CODEX_AGENT_DIR):
        name = rel[len(CODEX_AGENT_DIR):]
        return '/' not in name and name.endswith('.toml')
    return rel.startswith(CODEX_SKILL_PREFIX)


def delivery_allowed(rel: str) -> bool:
    return rel in DELIVERY_SINGLE_FILES or any(rel.startswith(f'skills/{name}/') for name in DELIVERY_SKILLS)


def load_install_record(root: Path, rel: str) -> dict | None:
    try:
        data = read_regular(root / rel, MAX_INSTALL_RECORD_BYTES)
    except FileNotFoundError:
        return None
    record = parse_json(data, MAX_INSTALL_RECORD_BYTES)
    if (not isinstance(record, dict) or type(record.get('version')) is not int or record['version'] != 1
            or not isinstance(record.get('files'), dict)):
        raise RefusedError('the install record has an unexpected format')
    return record


def validate_owned_paths(files: dict, allowed: Callable[[str], bool]) -> None:
    """Refuse the whole record before reading anything if one path leaves the managed namespace."""
    if len(files) > MAX_OWNED_FILES:
        raise RefusedError('the install record lists too many files')
    for rel, checksum in files.items():
        if not safe_relative(rel) or not allowed(rel):
            raise RefusedError(f'the install record names a path outside the managed files: {rel!r}')
        if not isinstance(checksum, str) or not SHA256.fullmatch(checksum):
            raise RefusedError(f'the install record has an invalid checksum for {rel}')


def compare_owned_files(root: Path, files: dict[str, str]) -> list[str]:
    problems = []
    for rel, checksum in sorted(files.items()):
        try:
            data = read_regular(root / rel, MAX_OWNED_FILE_BYTES)
        except FileNotFoundError:
            problems.append(f'{rel}: missing')
            continue
        except RefusedError as err:
            problems.append(f'{rel}: {err}')
            continue
        except OSError as err:
            problems.append(f'{rel}: unreadable ({err.strerror})')
            continue
        if hashlib.sha256(data).hexdigest() != checksum:
            problems.append(f'{rel}: changed since install')
    return problems


def _clean_sha(value: object) -> str | None:
    return value if isinstance(value, str) and DISPLAY_VALUE.fullmatch(value) else None


def _component(component_id: str, label: str, **fields: object) -> dict:
    return {'id': component_id, 'label': label, 'summary': '', 'next': '', 'problems': [], **fields}


def _verified(component: dict, root: Path, record: dict, allowed: Callable[[str], bool],
              extra_check: Callable[[], list[str]] | None = None, covered: str = '') -> dict:
    """Ready only when every listed file and every extra owned surface (extra_check) matches."""
    files = record['files']
    validate_owned_paths(files, allowed)
    problems = compare_owned_files(root, files)
    extra = extra_check() if extra_check is not None else []
    component.update(owned_files=len(files), installed_source_sha=_clean_sha(record.get('source_sha')))
    if problems or extra:
        parts = [f'{len(problems)} of {len(files)} files differ from their install record'] if problems else []
        component.update(state=ATTENTION, problems=problems + extra, summary='; '.join(parts + extra))
        return component
    component.update(state=READY, next='', summary=f'all {len(files)} files{covered} match their install record')
    return component


def claude_framework_component(claude_home: Path, fields: dict | None, error: str | None) -> dict:
    component = _component('claude_framework', 'Claude framework files', root=str(claude_home),
                           check='install-marker-only', source_comparison='not_checked')
    if error is not None:
        return {**component, 'state': ATTENTION, 'summary': f'the install marker could not be read ({error})',
                'next': 'Ask the agent to look at ~/.claude/.framework-version; nothing was changed.'}
    if fields is None:
        return {**component, 'state': NOT_INSTALLED, 'summary': 'no install marker found'}
    version = marker_value(fields, 'version')
    return {**component, 'state': NOT_CHECKED, 'version': version,
            'installed_source_sha': marker_value(fields, 'sha'),
            'summary': f'version {version or "unknown"}; these files have no per-file install record, '
                       'so they were not checked',
            'next': 'For a full check, run ./validate.sh in the framework source folder (the agent can do this).'}


def delivery_component(claude_home: Path) -> dict:
    component = _component('claude_delivery', 'Claude delivery files', root=str(claude_home),
                           check='installed-manifest', source_comparison='not_checked',
                           next='Run python3 scripts/install-delivery.py --check in the framework source folder '
                                'to see the difference (the agent can do this).')
    try:
        record = load_install_record(claude_home, DELIVERY_MANIFEST)
        if record is None or not record['files']:
            return {**component, 'state': NOT_INSTALLED, 'summary': 'not installed', 'next': ''}
        return _verified(component, claude_home, record, delivery_allowed)
    except (RefusedError, OSError) as err:
        return {**component, 'state': ATTENTION, 'summary': f'install record refused: {err}'}


def instruction_problems(root: Path, *, user: bool, owned: str) -> list[str]:
    """Exactly one managed block whose bytes still match the recorded checksum; text around it is personal."""
    rel = '.codex/AGENTS.md' if user else 'AGENTS.md'
    try:
        data = read_regular(root / rel, MAX_OWNED_FILE_BYTES)
    except FileNotFoundError:
        return [f'{rel}: missing, so the managed instruction block is gone']
    except RefusedError as err:
        return [f'{rel}: {err}']
    except OSError as err:
        return [f'{rel}: unreadable ({err.strerror})']
    begin, end = INSTRUCTION_BEGIN.encode(), INSTRUCTION_END.encode()
    if (data.count(begin), data.count(end)) != (1, 1):
        return [f'{rel}: the managed instruction block is missing or duplicated']
    low, end_at = data.index(begin), data.index(end)
    if end_at < low:
        return [f'{rel}: the managed instruction block markers are reversed']
    high = end_at + len(end)
    if data[high:high + 1] == b'\n':
        high += 1
    if hashlib.sha256(data[low:high]).hexdigest() != owned:
        return [f'{rel}: the managed instruction block changed since install']
    return []


def codex_component(root: Path, *, user: bool) -> dict:
    scope = 'user' if user else 'project'
    target = '--user' if user else f'--project {root}'
    component = _component('codex', f'Codex framework files ({scope})', scope=scope, root=str(root),
                           check='installed-manifest', source_comparison='not_checked', hooks_selected=None,
                           next=f'Run ./install-codex.sh {target} --check in the framework source folder '
                                '(the agent can do this).')
    try:
        record = load_install_record(root, CODEX_MANIFEST)
        if record is None or not record['files']:
            return {**component, 'state': NOT_INSTALLED, 'summary': 'not installed', 'next': ''}
        recorded_user, hooks = record.get('user'), record.get('hooks')
        if type(recorded_user) is not bool or type(hooks) is not bool:
            raise RefusedError('the install record has no valid scope or hook choice')
        if recorded_user != user:
            installed = 'user' if recorded_user else 'project'
            return {**component, 'state': ATTENTION,
                    'summary': f'asked about a {scope} install, but this install record is for a {installed} install'}
        if hooks != (CODEX_HOOKS_FILE in record['files']):
            raise RefusedError('the install record hook choice does not match its file list')
        owned_block = record.get('instructions')
        if not isinstance(owned_block, str) or not SHA256.fullmatch(owned_block):
            raise RefusedError('the install record has no valid instruction checksum')
        component['hooks_selected'] = hooks
        return _verified(component, root, record, codex_allowed,
                         extra_check=lambda: instruction_problems(root, user=user, owned=owned_block),
                         covered=' and the managed instruction block')
    except (RefusedError, OSError) as err:
        return {**component, 'state': ATTENTION, 'summary': f'install record refused: {err}'}


# ---------------------------------------------------------------- extras

def _extra(feature_id: str, state: str, detail: str, **observed: object) -> dict:
    """One extra; `observed` keeps presence metadata (e.g. registry_present) apart from the state."""
    info = FEATURES[feature_id]
    return {'id': feature_id, 'label': info['label'], 'short': info['short'], 'state': state, 'detail': detail,
            'about': info['about'], 'change': info['change'], 'reviewable': info['reviewable'], **observed}


def _claude_selection_extra(name: str, fields: dict) -> dict:
    feature_id = f'claude.{name}'
    choice = marker_selection(fields, name)
    if choice == 'disabled':
        return _extra(feature_id, OFF, 'Not selected at install.')
    if choice == 'unknown':
        return _extra(feature_id, UNKNOWN, 'The install record does not say, so it is not assumed to be off.')
    if name == 'watchdog' and not IS_MACOS:
        return _extra(feature_id, UNAVAILABLE, 'Selected, but the watchdog runs only on macOS.')
    return _extra(feature_id, ON, 'Selected at install; whether it is running right now was not checked.')


def claude_extras(fields: dict | None, error: str | None) -> list[dict]:
    names = ('analytics', 'watchdog', 'notifications')
    if error is not None:
        unreadable = 'The Claude install marker could not be read.'
        return [*(_extra(f'claude.{name}', UNKNOWN, unreadable) for name in names),
                _extra('claude.post_edit_lint', UNKNOWN, unreadable)]
    if fields is None:
        missing = 'Claude framework files are not installed.'
        return [*(_extra(f'claude.{name}', NOT_INSTALLED, missing) for name in names),
                _extra('claude.post_edit_lint', NOT_INSTALLED, missing)]
    return [*(_claude_selection_extra(name, fields) for name in names),
            _extra('claude.post_edit_lint', CORE, 'Installed with the core files; it gives hints, not check results.')]


def lint_registry_extra(home: Path, hooks_selected: bool) -> dict:
    path = home / LINT_REGISTRY_FILE
    feature_id = 'codex.approved_lint'
    if symlink_in_path(path) is not None:
        return _extra(feature_id, ATTENTION, 'The approval list is reached through a symlink, so lint will not run.')
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return _extra(feature_id, OFF, 'No projects are approved.', registry_present=False)
    except OSError as err:
        return _extra(feature_id, ATTENTION, f'The approval list could not be inspected ({err.strerror}).')
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        return _extra(feature_id, ATTENTION,
                      'The approval list is not a regular file only you can change, so lint will not run.')
    if not hooks_selected:
        return _extra(feature_id, NEEDS_SETUP, 'An approval list exists, but lint runs only with Codex hooks installed.',
                      registry_present=True)
    return _extra(feature_id, NOT_CHECKED, 'An approval list exists; which projects (if any) it approves was not '
                                           'read here, so lint is not reported as on.', registry_present=True)


def codex_extras(home: Path, codex: dict) -> list[dict]:
    if codex['state'] == NOT_INSTALLED:
        missing = 'Codex framework files are not installed.'
        return [_extra('codex.hooks', NOT_INSTALLED, missing), _extra('codex.approved_lint', NOT_INSTALLED, missing)]
    hooks = codex.get('hooks_selected')
    if hooks is None:
        unreadable = 'The Codex install record could not be used.'
        return [_extra('codex.hooks', UNKNOWN, unreadable), _extra('codex.approved_lint', UNKNOWN, unreadable)]
    if not hooks:
        hooks_extra = _extra('codex.hooks', OFF, 'Not installed with the Codex files.')
    elif codex['state'] != READY:
        hooks_extra = _extra('codex.hooks', UNKNOWN, 'Selected at install, but the Codex files need attention, so '
                                                     'the installed hook definition is not confirmed.')
    else:
        hooks_extra = _extra('codex.hooks', ON, 'Installed and matching its install record; Codex runs them only '
                                                'after you approve them in /hooks, which was not checked.')
    return [hooks_extra, lint_registry_extra(home, hooks)]


def model_policy_extra(home: Path) -> dict:
    """Only `version` and `active` are inspected. Bindings, model names, evidence and the text of a
    parse error (it could quote private content) are never reported. An active policy is Not
    checked, never On: whether it is valid, evaluated and approved is decided by the delivery
    model-policy tool."""
    feature_id = 'model_policy'
    try:
        data = read_private_file(home / MODEL_POLICY_FILE)
    except (RefusedError, OSError) as err:
        return _extra(feature_id, ATTENTION, f'The policy file is not usable ({err}); the delivery tool will '
                                             'report it as invalid rather than fall back silently.')
    if data is None:
        return _extra(feature_id, OFF, 'Not set up; your normal model settings apply.', configured_active=False)
    try:
        policy = parse_json(data)
    except RefusedError:
        return _extra(feature_id, ATTENTION, 'The policy file is not valid JSON (details are not shown because the '
                                             'file is private); the delivery tool will report it as invalid.')
    if (not isinstance(policy, dict) or type(policy.get('version')) is not int or policy['version'] != 1
            or type(policy.get('active')) is not bool):
        return _extra(feature_id, ATTENTION, 'The policy file is not a version 1 policy with a true/false "active".')
    if policy['active']:
        return _extra(feature_id, NOT_CHECKED, 'Marked active. Whether it is valid, evaluated and approved is '
                                               'checked by the delivery model-policy tool, not here.',
                      configured_active=True)
    return _extra(feature_id, OFF, 'Present but inactive; your normal model settings apply.', configured_active=False)


def _linked_common_dir(work_tree: Path, dot_git: Path) -> Path:
    text = read_regular(dot_git, MAX_SMALL_BYTES).decode('utf-8').strip()
    if not text.startswith('gitdir: ') or '\n' in text:
        raise RefusedError('unrecognized .git file')
    git_dir = Path(os.path.normpath(work_tree / text[len('gitdir: '):]))
    try:
        common = read_regular(git_dir / 'commondir', MAX_SMALL_BYTES).decode('utf-8').strip()
    except FileNotFoundError:
        return git_dir
    if not common or '\n' in common:
        raise RefusedError('unrecognized commondir file')
    return Path(os.path.normpath(git_dir / common))


def git_common_dir(start: Path) -> Path | None:
    """Locate the Git common directory by reading .git entries as data; Git itself is not run."""
    for candidate in (start, *start.parents):
        dot_git = candidate / '.git'
        if dot_git.is_symlink():
            raise RefusedError('the .git entry is a symlink')
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():
            return _linked_common_dir(candidate, dot_git)
    return None


def controller_extra(start: Path) -> dict:
    feature_id = 'controller'
    try:
        common = git_common_dir(start)
    except (RefusedError, OSError, ValueError) as err:
        return _extra(feature_id, NOT_CHECKED, f'The Git folder could not be identified ({err}).')
    if common is None:
        return _extra(feature_id, NOT_CHECKED, 'Not inside a Git repository, so there is nothing to check here.')
    try:
        info = os.lstat(common / CONTROLLER_BINDING)
    except FileNotFoundError:
        return _extra(feature_id, OFF, 'Not set up for this repository.', binding_present=False)
    except OSError as err:
        return _extra(feature_id, NOT_CHECKED, f'The controller binding could not be inspected ({err.strerror}).')
    if not stat.S_ISREG(info.st_mode):
        return _extra(feature_id, ATTENTION, 'The controller binding is not a regular file; ask the agent to look '
                                             'into it before running the controller.')
    return _extra(feature_id, NOT_CHECKED, 'A controller binding exists for this repository; whether it is valid '
                                           'and usable was not checked here (the controller checks it when it runs).',
                  binding_present=True)


# ---------------------------------------------------------------- source location

def source_info(explicit: Path | None, claude_home: Path) -> dict:
    """Where the framework source is, as reported data only; nothing there is run or imported."""
    base = {'comparison': 'not_checked',
            'note': 'Installed files were compared with their own install records only. To compare them with '
                    'the current source, run ./framework status inside the source folder.'}
    if explicit is not None:
        path = explicit.expanduser().absolute()
        return {**base, 'origin': 'argument', 'path': str(path), 'found': path.is_dir()}
    try:
        text = read_regular(claude_home / SOURCE_LOCATOR, 4096).decode('utf-8')
    except FileNotFoundError:
        return {**base, 'origin': 'none', 'path': None, 'found': False}
    except (RefusedError, OSError, ValueError) as err:
        return {**base, 'origin': 'locator', 'path': None, 'found': False,
                'detail': f'the source location record was ignored ({err})'}
    value = text[:-1] if text.endswith('\n') else text
    if not value.startswith('/') or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return {**base, 'origin': 'locator', 'path': None, 'found': False,
                'detail': 'the source location record is not a plain absolute path and was ignored'}
    return {**base, 'origin': 'locator', 'path': value, 'found': Path(value).is_dir()}


def default_invocation() -> str:
    """How to run this helper again, for hints: python3 plus its own path (~ for the home folder)."""
    script = Path(__file__).absolute()
    try:
        return 'python3 ~/' + shlex.quote(script.relative_to(Path.home()).as_posix())
    except ValueError:
        return 'python3 ' + shlex.quote(str(script))


def scope_notes(home: Path, *, claude_home_given: bool, project_given: bool) -> list[str]:
    """Say which default folder was checked when the environment names another; values are never printed."""
    notes = []
    claude_dir = os.environ.get('CLAUDE_CONFIG_DIR')
    if claude_dir and not claude_home_given and Path(claude_dir).expanduser().absolute() != home / '.claude':
        notes.append('CLAUDE_CONFIG_DIR names another Claude folder; this view checked ~/.claude only. Pass '
                     '--claude-home to check another folder (the framework installers target ~/.claude).')
    codex_dir = os.environ.get('CODEX_HOME')
    if codex_dir and not project_given and Path(codex_dir).expanduser().absolute() != home / '.codex':
        notes.append('CODEX_HOME names another Codex folder; Codex user installs are supported only in ~/.codex, '
                     'which is what this view checked.')
    return notes


# ---------------------------------------------------------------- preferences

def default_preferences() -> dict:
    return {'version': PREFERENCES_VERSION, 'display': {'detail': 'concise', 'reminders': 'changes-only'},
            'reviewed': {}, 'catalog_reviewed': 0}


def _is_choice(value: object, choices: tuple[str, ...]) -> bool:
    return isinstance(value, str) and value in choices


def validate_preferences(value: object) -> dict:
    """Closed version 1 schema: exact keys, exact types (a boolean is never an integer), known enums."""
    if not isinstance(value, dict) or set(value) != PREFERENCE_KEYS:
        raise RefusedError('the preferences file has unexpected or missing keys')
    version = value['version']
    if type(version) is not int or version != PREFERENCES_VERSION:
        raise RefusedError('the preferences file has an unsupported version')
    display = value['display']
    if not isinstance(display, dict) or set(display) != DISPLAY_KEYS:
        raise RefusedError('the display preferences have unexpected or missing keys')
    if not _is_choice(display['detail'], DETAIL_LEVELS) or not _is_choice(display['reminders'], REMINDER_MODES):
        raise RefusedError('a display preference has an unsupported value')
    reviewed = value['reviewed']
    if not isinstance(reviewed, dict):
        raise RefusedError('the reviewed extras are not a mapping')
    for feature_id, state in reviewed.items():
        if feature_id not in REVIEWABLE or not _is_choice(state, ('enabled', 'disabled')):
            raise RefusedError(f'unsupported reviewed extra: {feature_id!r}')
    catalog = value['catalog_reviewed']
    if type(catalog) is not int or not 0 <= catalog <= CATALOG_VERSION:
        raise RefusedError('the reviewed catalog version is not supported')
    return {'version': version, 'display': {'detail': display['detail'], 'reminders': display['reminders']},
            'reviewed': dict(sorted(reviewed.items())), 'catalog_reviewed': catalog}


def load_preferences(path: Path) -> tuple[dict, bytes | None, str | None]:
    """(preferences, exact bytes read, refusal reason); defaults are used when absent or refused."""
    try:
        raw = read_private_file(path)
        if raw is None:
            return default_preferences(), None, None
        return validate_preferences(parse_json(raw)), raw, None
    except (RefusedError, OSError) as err:
        return default_preferences(), None, str(err)


def _prepare_private_dir(directory: Path) -> None:
    for current in (directory.parent, directory):
        link = symlink_in_path(current)
        if link is not None:
            raise RefusedError(f'{current} is reached through a symlink ({link})')
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            pass
        _check_owner_dir(current)


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_preferences(path: Path, preferences: dict, expected: bytes | None) -> None:
    """Atomically replace the file only if it still holds exactly the bytes that were read."""
    clean = validate_preferences(preferences)
    _prepare_private_dir(path.parent)
    stale = 'the preferences file changed after it was read; nothing was saved'
    if read_private_file(path) != expected:
        raise RefusedError(stale)
    data = (json.dumps(clean, indent=2, sort_keys=True) + '\n').encode()
    fd, name = tempfile.mkstemp(prefix='.framework-preferences-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if read_private_file(path) != expected:
            raise RefusedError(stale)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    _fsync_directory(path.parent)


def preferences_view(path: Path, preferences: dict, raw: bytes | None, error: str | None) -> dict:
    state = 'refused' if error else ('saved' if raw is not None else 'default')
    view = {'state': state, 'path': str(path), 'display': preferences['display'],
            'reviewed': preferences['reviewed'], 'catalog_reviewed': preferences['catalog_reviewed'],
            'grants_permission': False}
    if error:
        view['detail'] = f'{error}; defaults are used and nothing was changed'
    return view


def reminders(extras: list[dict], view: dict, invocation: str) -> list[str]:
    """Changes since a recorded review only; an extra never reviewed produces no reminder.

    The new-extras notice needs an earlier completed review (catalog_reviewed > 0, written only by
    --acknowledge-all or a finished --review) of an older catalog. Saving a display preference or
    acknowledging one extra records no catalog review, so it never triggers the notice, and the
    first catalog is never announced as new.
    """
    if view['state'] == 'refused' or view['display']['reminders'] == 'off':
        return []
    notes = []
    for extra in extras:
        reviewed = view['reviewed'].get(extra['id'])
        if reviewed is None or REVIEW_VALUES.get(extra['state']) == reviewed:
            continue
        notes.append(f'{extra["label"]}: you reviewed it as {reviewed}; it is now {STATE_LABELS[extra["state"]]}.')
    if view['state'] == 'saved' and 0 < view['catalog_reviewed'] < CATALOG_VERSION:
        notes.append(f'New optional extras are available to review: {invocation} settings')
    return notes


# ---------------------------------------------------------------- report

def headline(components: list[dict], extras: list[dict], preferences: dict) -> dict:
    states = [component['state'] for component in components]
    if (ATTENTION in states or any(extra['state'] == ATTENTION for extra in extras)
            or preferences['state'] == 'refused'):
        state = ATTENTION
    elif all(value == NOT_INSTALLED for value in states):
        state = NOT_INSTALLED
    elif all(value in (READY, NOT_INSTALLED) for value in states):
        state = READY
    else:
        state = NOT_CHECKED
    return {'state': state, 'label': HEADLINES[state]}


def collect(*, home: Path, claude_home: Path, project: Path | None, cwd: Path, source: Path | None,
            invocation: str, claude_home_given: bool = False) -> dict:
    fields, marker_error = load_marker_safely(claude_home)
    codex = codex_component(home if project is None else project, user=project is None)
    components = [claude_framework_component(claude_home, fields, marker_error), delivery_component(claude_home),
                  codex]
    extras = [*claude_extras(fields, marker_error), *codex_extras(home, codex), model_policy_extra(home),
              controller_extra(project or cwd),
              _extra('hook_templates', REFERENCE, 'Reference examples only; nothing is wired in.')]
    return {
        'schema': SCHEMA,
        'components': components,
        'extras': extras,
        'host_only': [{'id': key, 'label': label, 'state': UNKNOWN, 'detail': detail}
                      for key, (label, detail) in HOST_ONLY.items()],
        'native_cli': {'claude': shutil.which('claude') is not None, 'codex': shutil.which('codex') is not None,
                       'note': 'Found on PATH only; sign-in and model access were not checked.'},
        'source': source_info(source, claude_home),
        'invocation': invocation,
        'scope_notes': scope_notes(home, claude_home_given=claude_home_given, project_given=project is not None),
    }


def attach_preferences(report: dict, view: dict) -> dict:
    report['preferences'] = view
    report['reminders'] = reminders(report['extras'], view, report['invocation'])
    report['headline'] = headline(report['components'], report['extras'], view)
    return report


def installed_report(*, home: Path, claude_home: Path, project: Path | None, cwd: Path, source: Path | None,
                     invocation: str, claude_home_given: bool,
                     loaded: tuple[dict, bytes | None, str | None] | None = None) -> dict:
    """The complete read-only report with preferences attached; `loaded` reuses an earlier read."""
    path = home / PREFERENCES_FILE
    preferences, raw, error = loaded if loaded is not None else load_preferences(path)
    report = collect(home=home, claude_home=claude_home, project=project, cwd=cwd, source=source,
                     invocation=invocation, claude_home_given=claude_home_given)
    return attach_preferences(report, preferences_view(path, preferences, raw, error))


def exit_code(report: dict) -> int:
    return 1 if report['headline']['state'] == ATTENTION else 0


def attention_items(report: dict) -> list[str]:
    items = []
    for component in report['components']:
        if component['state'] != ATTENTION:
            continue
        text = f'{component["label"]}: {component["summary"]}'
        if component['problems']:
            text += ' (' + '; '.join(component['problems'][:3]) + ('; ...' if len(component['problems']) > 3 else '') + ')'
        if component['next']:
            text += f'. Next: {component["next"]}'
        items.append(text)
    items += [f'{extra["label"]}: {extra["detail"]}' for extra in report['extras'] if extra['state'] == ATTENTION]
    if report['preferences']['state'] == 'refused':
        items.append(f'Display preferences: {report["preferences"]["detail"]}')
    return items


def _host_line(report: dict) -> str:
    labels = ', '.join(item['label'] for item in report['host_only'])
    return f'Not checked here: {labels} (your host app shows these).'


def _scope_lines(report: dict) -> list[str]:
    if not report['scope_notes']:
        return []
    return ['Scope:'] + [f'  - {note}' for note in report['scope_notes']]


def render_status(report: dict, detail: str) -> str:
    full = detail == 'full'
    lines = [report['headline']['label']]
    if report['headline']['state'] == NOT_CHECKED and not full:
        lines.append('  Some installed parts have no per-file record, so they were not checked.')
    for component in report['components']:
        text = STATE_LABELS[component['state']]
        if component['summary'] and (full or component['state'] != NOT_INSTALLED):
            text += f' - {component["summary"]}'
        lines.append(f'  {component["label"]}: {text}')
        if full:
            lines += [f'      {problem}' for problem in component['problems'][:50]]
            if component['next'] and component['state'] in (ATTENTION, NOT_CHECKED):
                lines.append(f'      Next: {component["next"]}')
    attention = attention_items(report)
    if attention:
        lines.append('Needs attention:')
        lines += [f'  - {item}' for item in attention]
    if full:
        lines.append('Extras:')
        lines += [f'  {extra["label"]}: {STATE_LABELS[extra["state"]]} - {extra["detail"]}' for extra in report['extras']]
        source = report['source']
        lines.append(f'Source folder: {source["path"] or "not recorded"} ({source["origin"]})')
        if source.get('detail'):
            lines.append(f'  {source["detail"]}')
        lines.append(f'  {source["note"]}')
    else:
        lines.append('Extras: ' + ', '.join(f'{extra["short"]} {STATE_LABELS[extra["state"]]}'
                                            for extra in report['extras']))
    lines.append(_host_line(report))
    lines += _scope_lines(report)
    if report['reminders']:
        lines.append('Reminders:')
        lines += [f'  - {note}' for note in report['reminders']]
    if not full:
        lines.append(f'More: {report["invocation"]} status --detail full | {report["invocation"]} settings')
    return '\n'.join(lines)


def render_settings(report: dict) -> str:
    view = report['preferences']
    origin = {'saved': 'saved', 'default': 'defaults, nothing saved', 'refused': 'defaults, file not used'}[view['state']]
    lines = ['Framework settings', '', f'Display ({origin}):',
             f'  Detail: {view["display"]["detail"]}   Reminders: {view["display"]["reminders"]}',
             f'  Change with: {report["invocation"]} settings --set-detail concise|full  or  '
             '--set-reminders changes-only|off',
             '  These only change how status is shown; they grant no permission.']
    if view['state'] == 'refused':
        lines.append(f'  Preferences file not used: {view["detail"]}')
    lines += ['', 'Optional extras (this view changes nothing; the agent can do setup steps for you):']
    for extra in report['extras']:
        heading = f'  {extra["label"]}: {STATE_LABELS[extra["state"]]}'
        if extra['reviewable']:
            reviewed = view['reviewed'].get(extra['id'])
            heading += f' (reviewed as {reviewed})' if reviewed else ' (not reviewed)'
        lines += [heading, f'    {extra["about"]}', f'    Now: {extra["detail"]}', f'    How to change: {extra["change"]}']
    lines += ['', 'Host only (never marked as passed here):']
    lines += [f'  {item["label"]}: {STATE_LABELS[item["state"]]} - {item["detail"]}' for item in report['host_only']]
    lines += _scope_lines(report)
    attention = attention_items(report)
    if attention:
        lines += ['', 'Needs attention:'] + [f'  - {item}' for item in attention]
    command = report['invocation']
    lines += ['', f'Remember a reviewed extra: {command} settings --acknowledge FEATURE '
                  f'(or {command} settings --review on a terminal).']
    return '\n'.join(lines)


# ---------------------------------------------------------------- settings actions

def apply_settings_changes(args: argparse.Namespace, preferences: dict, report: dict) -> dict:
    staged = copy.deepcopy(preferences)
    if args.set_detail:
        staged['display']['detail'] = args.set_detail
    if args.set_reminders:
        staged['display']['reminders'] = args.set_reminders
    states = {extra['id']: extra['state'] for extra in report['extras']}
    targets = list(args.acknowledge or [])
    if args.acknowledge_all:
        targets += [feature_id for feature_id in REVIEWABLE if states.get(feature_id) in REVIEW_VALUES]
        staged['catalog_reviewed'] = CATALOG_VERSION
    for feature_id in targets:
        value = REVIEW_VALUES.get(states.get(feature_id, UNKNOWN))
        if value is None:
            label, state = FEATURES[feature_id]['label'], STATE_LABELS[states.get(feature_id, UNKNOWN)]
            raise RefusedError(f'{label} is {state}, so it cannot be remembered as reviewed yet')
        staged['reviewed'][feature_id] = value
    for feature_id in args.forget or []:
        staged['reviewed'].pop(feature_id, None)
    return staged


def _prompt(ask: Callable[[str], str], text: str) -> str | None:
    try:
        return ask(text).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None


def _review_extras(report: dict, staged: dict, ask: Callable[[str], str], out: TextIO) -> bool:
    """Stage reviewed states; False when the owner stopped early."""
    for extra in report['extras']:
        if not extra['reviewable']:
            continue
        value = REVIEW_VALUES.get(extra['state'])
        out.write(f'\n{extra["label"]}: {STATE_LABELS[extra["state"]]}\n  {extra["about"]}\n'
                  f'  Now: {extra["detail"]}\n  How to change: {extra["change"]}\n')
        if value is None:
            out.write('  It can be remembered once it is clearly on or off.\n')
            continue
        if staged['reviewed'].get(extra['id']) == value:
            out.write(f'  Already reviewed as {value}.\n')
            continue
        answer = _prompt(ask, f'  Remember "{extra["label"]}" as reviewed ({value})? [y/N, q to stop] ')
        if answer is None or answer == 'q':
            return False
        if answer in ('y', 'yes'):
            staged['reviewed'][extra['id']] = value
    return True


def _review_display(staged: dict, ask: Callable[[str], str], out: TextIO) -> bool:
    for key, choices, question in (('detail', DETAIL_LEVELS, 'Status detail'),
                                   ('reminders', REMINDER_MODES, 'Reminders')):
        current = staged['display'][key]
        answer = _prompt(ask, f'{question} ({" or ".join(choices)})? [Enter keeps {current}] ')
        if answer is None:
            return False
        if answer in choices:
            staged['display'][key] = answer
        elif answer:
            out.write(f'  Not recognized; keeping {current}.\n')
    return True


def guided_review(report: dict, preferences: dict, raw: bytes | None, path: Path,
                  ask: Callable[[str], str], out: TextIO) -> int:
    staged = copy.deepcopy(preferences)
    out.write('Guided review of optional extras. Nothing is saved unless you confirm at the end.\n'
              'This only records what you reviewed; to change an extra, follow its "How to change" step.\n')
    if _review_extras(report, staged, ask, out) and _review_display(staged, ask, out):
        staged['catalog_reviewed'] = CATALOG_VERSION
    if staged == preferences:
        out.write('\nNothing to save.\n')
        return 0
    if _prompt(ask, f'\nSave these display preferences to {path}? [y/N] ') not in ('y', 'yes'):
        out.write('Not saved.\n')
        return 0
    save_preferences(path, staged, raw)
    out.write('Saved. They only change how status is shown; nothing else was changed.\n')
    return 0


# ---------------------------------------------------------------- command line

def build_parser(prog: str) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--json', action='store_true', help='print machine-readable JSON (never prompts)')
    common.add_argument('--detail', choices=DETAIL_LEVELS, help='detail level for this run only (nothing is saved)')
    common.add_argument('--project', type=Path,
                        help="check a project Codex install and that project's controller setup")
    common.add_argument('--claude-home', type=Path, help='Claude home to check (default: ~/.claude)')
    common.add_argument('--source', type=Path, help='framework source folder to report (location only)')
    parser = argparse.ArgumentParser(prog=prog, description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', parents=[common], help='show whether the framework files are ready (default)')
    settings = commands.add_parser('settings', parents=[common], help='show extras and manage display preferences')
    settings.add_argument('--set-detail', choices=DETAIL_LEVELS, help='save the default status detail level')
    settings.add_argument('--set-reminders', choices=REMINDER_MODES, help='save the reminder mode')
    settings.add_argument('--acknowledge', action='append', choices=REVIEWABLE, metavar='FEATURE',
                          help='remember an extra as reviewed in its current on/off state: ' + ', '.join(REVIEWABLE))
    settings.add_argument('--acknowledge-all', action='store_true',
                          help='remember every extra that is clearly on or off as reviewed')
    settings.add_argument('--forget', action='append', choices=REVIEWABLE, metavar='FEATURE',
                          help='forget a remembered review')
    settings.add_argument('--review', action='store_true', help='guided review (interactive terminal only)')
    return parser


def _has_changes(args: argparse.Namespace) -> bool:
    return args.command == 'settings' and any((args.set_detail, args.set_reminders, args.acknowledge,
                                                args.acknowledge_all, args.forget))


def parse_args(argv: list[str], prog: str) -> argparse.Namespace:
    if not argv or argv[0] not in (*COMMANDS, '-h', '--help'):
        argv = ['status', *argv]
    parser = build_parser(prog)
    args = parser.parse_args(argv)
    if args.command == 'settings' and args.review and _has_changes(args):
        parser.error('--review cannot be combined with other settings changes')
    return args


def _change_settings(args: argparse.Namespace, report: dict, preferences: dict, raw: bytes | None,
                     path: Path, out: TextIO, err: TextIO) -> int:
    if report['preferences']['state'] == 'refused':
        err.write(f'Preferences not changed: {report["preferences"]["detail"]}\n')
        return 2
    try:
        staged = apply_settings_changes(args, preferences, report)
        if staged != preferences:
            save_preferences(path, staged, raw)
    except (RefusedError, OSError) as exc:
        err.write(f'Preferences not changed: {exc}\n')
        return 2
    attach_preferences(report, preferences_view(path, *load_preferences(path)))
    out.write(json.dumps(report, indent=2, sort_keys=True) + '\n' if args.json else render_settings(report) + '\n')
    return 0


def _run(argv: list[str], *, interactive: bool, ask: Callable[[str], str], out: TextIO, err: TextIO,
         cwd: Path, invocation: str | None = None) -> int:
    invocation = invocation or default_invocation()
    try:
        args = parse_args(list(argv), invocation)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    home = Path.home()
    claude_home = (args.claude_home or home / '.claude').expanduser().absolute()
    project = args.project.expanduser().absolute() if args.project else None
    path = home / PREFERENCES_FILE
    preferences, raw, error = load_preferences(path)
    report = installed_report(home=home, claude_home=claude_home, project=project, cwd=cwd, source=args.source,
                              invocation=invocation, claude_home_given=args.claude_home is not None,
                              loaded=(preferences, raw, error))
    if args.command == 'status':
        detail = args.detail or preferences['display']['detail']
        out.write(json.dumps(report, indent=2, sort_keys=True) + '\n' if args.json else render_status(report, detail) + '\n')
        return exit_code(report)
    if args.review:
        if args.json or not interactive:
            err.write('The guided review needs an interactive terminal; nothing was changed. '
                      f'Use {invocation} settings --acknowledge FEATURE instead.\n')
            return 2
        if error:
            err.write(f'Preferences not changed: {report["preferences"]["detail"]}\n')
            return 2
        try:
            return guided_review(report, preferences, raw, path, ask, out)
        except (RefusedError, OSError) as exc:
            err.write(f'Preferences not changed: {exc}\n')
            return 2
    if _has_changes(args):
        return _change_settings(args, report, preferences, raw, path, out, err)
    out.write(json.dumps(report, indent=2, sort_keys=True) + '\n' if args.json else render_settings(report) + '\n')
    return exit_code(report)


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get('CI')


def main(argv: list[str] | None = None, *, invocation: str | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    return _run(arguments, interactive=_is_interactive(), ask=input, out=sys.stdout, err=sys.stderr, cwd=Path.cwd(),
                invocation=invocation)


if __name__ == '__main__':
    raise SystemExit(main())
