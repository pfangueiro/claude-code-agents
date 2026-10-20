#!/usr/bin/env python3
"""Build and install a separately owned Codex edition. Python 3.11+, PyYAML 6."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = Path('.codex/framework/manifest.json')
BEGIN = '<!-- sdlc-codex:begin -->'
END = '<!-- sdlc-codex:end -->'
PREFIX = 'sdlc-'
# Inherited variables that would point Git at another repository, index or object store.
# Mirrors scripts/install-delivery.py so every source-identity query ignores the same set.
GIT_REDIRECT_ENV = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_COMMON_DIR',
                    'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_NAMESPACE', 'GIT_REPLACE_REF_BASE')
GIT_SAFETY = ('-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '--no-replace-objects',
              '--no-optional-locks', '--literal-pathspecs')

RUNTIME = """Codex runtime contract: discover the actual tools and their schemas first.
Use shell/file tools for reading, rg for search, apply_patch or an available editor
for changes, native collaboration for authorized delegation, and connected MCPs
only after checking availability. Claude tool names in domain prose describe roles,
not callable APIs. Skills do not automatically fork. Inherit model and permissions;
AGENTS.md and these procedures are guidance, not enforced access control.
Resolve resource paths from this skill's directory, not the shell working directory.
Do not send messages, merge, release, deploy or mutate live data unless authorized.
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def head_sha() -> str:
    """Resolve REPO's own HEAD, ignoring inherited Git repository/index selectors so an
    unrelated GIT_DIR in the environment cannot misattribute the installed source SHA."""
    env = {key: value for key, value in os.environ.items() if key not in GIT_REDIRECT_ENV}
    return subprocess.check_output(['git', *GIT_SAFETY, '-C', str(REPO), 'rev-parse', 'HEAD'],
                                   text=True, env=env).strip()


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    match = re.match(r'\A---\n(.*?)\n---\n(.*)\Z', text, re.S)
    if not match:
        raise ValueError(f'missing frontmatter: {path}')
    meta = yaml.safe_load(match[1])
    if not isinstance(meta, dict) or not isinstance(meta.get('description'), str):
        raise ValueError(f'invalid frontmatter: {path}')
    return meta, match[2]


def source_inventory() -> dict[str, list[str]]:
    return {
        'skills': sorted(p.parent.name for p in (REPO / '.claude/skills').glob('*/SKILL.md')),
        'commands': sorted(p.stem for p in (REPO / '.claude/commands').glob('*.md') if p.stem != 'README'),
        'agents': sorted(p.stem for p in (REPO / '.claude/agents').glob('*.md')),
    }


def adapt(text: str, inventory: dict) -> str:
    """Mechanical syntax adaptation only; runtime behavior uses handwritten overrides."""
    text = text.replace('CLAUDE.md', 'AGENTS.md').replace('Claude Code', 'Codex')
    text = text.replace('Claude Agents', 'SDLC framework').replace('worker Claudes', 'workers')
    text = text.replace('prompts Claude', 'prompts the model')
    text = text.replace('$ARGUMENTS', 'the task arguments supplied by the user')
    text = text.replace('~/.claude/sessions', '${CODEX_HOME:-$HOME/.codex}/framework/sessions')
    text = text.replace('while minimizing costs by using the Haiku model', 'using the active model')
    text = text.replace('Immediately escalate and force Opus model', 'Immediately escalate to the coordinator')
    text = text.replace('Immediately escalate and force Opus', 'Immediately escalate to the coordinator')
    text = text.replace('ALWAYS use Opus', 'use the active model and independent verification')
    text = text.replace('Opus model', 'active model').replace('(Opus)', '(active model)')
    text = text.replace('which uses Opus for maximum intelligence', 'which uses the active model and evidence-based review')
    text = text.replace('cannot be overridden by user instructions', 'apply within the user-authorized scope')
    text = text.replace('They cannot be overridden.', 'They apply within the user-authorized scope.')
    text = text.replace('These rules are always enforced.', 'Follow these project instructions.')
    for name in inventory['skills'] + inventory['commands']:
        text = re.sub(rf'(?<![\w:/.-])/{re.escape(name)}\b', '$' + PREFIX + name, text)
        text = re.sub(rf'(?<![\w])\${re.escape(name)}\b', '$' + PREFIX + name, text)
    for name in inventory['agents']:
        text = re.sub(rf'(?<![\w])\${re.escape(name)}\b', '$sdlc-agent-' + name, text)
    text = re.sub(r'(?:~?/)?\.claude/skills/([a-z-]+)', r'../sdlc-\1', text)
    text = text.replace('.claude/skills/README.md', 'references/framework/runtime.md')
    text = re.sub(r'(?:~?/)?\.claude/lib/[a-z.-]+', 'references/framework/runtime.md', text)
    return text


def build() -> dict[str, bytes]:
    inv = source_inventory()
    if not all(inv.values()) or set(inv['skills']) & set(inv['commands']):
        raise ValueError('empty or colliding source inventory')
    files: dict[str, bytes] = {}
    for kind in ('skills', 'commands'):
        for name in inv[kind]:
            source = REPO / '.claude' / kind / (f'{name}/SKILL.md' if kind == 'skills' else f'{name}.md')
            meta, body = frontmatter(source)
            override = REPO / f'codex/overrides/{name}.md'
            body = adapt(override.read_text() if override.exists() else body, inv)
            if name == 'git-workflow':
                # Preserve domain Git guidance, replace the Claude worktree-tool appendix.
                body = body.split('The table above compares the *git concept*')[0]
                body += '\nFor Codex isolation use $sdlc-worktree-workflow.\n'
            if kind == 'commands' and name in ('save-session', 'resume-session'):
                body = body.replace('run /compact', 'offer the native CLI /compact command')
                body = body.replace('run $sdlc-compact', 'save a handoff using $sdlc-compact')
            root = f'.agents/skills/{PREFIX}{name}'
            desc = adapt(meta['description'], inv)
            if override.exists():
                # Keep metadata discriminating; remove descriptions that promise Claude APIs.
                desc = DESCRIPTIONS.get(name, desc)
            header = yaml.safe_dump({'name': PREFIX + name, 'description': desc}, sort_keys=False).strip()
            files[f'{root}/SKILL.md'] = f'---\n{header}\n---\n\n{RUNTIME}\n{body}'.encode()
            files[f'{root}/references/framework/runtime.md'] = RUNTIME.encode()
            if meta.get('disable-model-invocation') is True:
                files[f'{root}/agents/openai.yaml'] = b'policy:\n  allow_implicit_invocation: false\n'
            if kind == 'skills':
                for resource in sorted(source.parent.rglob('*')):
                    if not resource.is_file() or resource == source or '__pycache__' in resource.parts:
                        continue
                    rel = resource.relative_to(source.parent).as_posix()
                    if resource.is_symlink():
                        raise ValueError(f'source resource symlink: {resource}')
                    data = resource.read_bytes()
                    if resource.suffix == '.md':
                        data = adapt(data.decode(), inv).encode()
                    if name == 'execute' and rel == 'references/agent-selection.md':
                        data = agent_selection(inv).encode()
                    files[f'{root}/{rel}'] = data
    for name in inv['agents']:
        meta, body = frontmatter(REPO / f'.claude/agents/{name}.md')
        if name == 'meta-agent':
            body = adapt((REPO / 'codex/overrides/meta-agent.md').read_text(), inv)
        else:
            body = adapt(body, inv)
        role = {'name': name, 'description': adapt(meta['description'], inv),
                'developer_instructions': RUNTIME + '\n' + body}
        # No sandbox_mode is emitted: sandbox_mode is a supported native field, but on a custom
        # agent it does not replace the parent permission policy or create an independent
        # read-only sandbox, so model and approval/sandbox policy are inherited unchanged.
        # Read-only review stays a developer-instruction expectation (reinforced by the fallback
        # disclaimer below); emitting the field would over-claim an enforced-sandbox effect it
        # does not deliver, not advertise an unsupported field.
        text = ''.join(f'{key} = {json.dumps(value, ensure_ascii=False)}\n' for key, value in role.items())
        tomllib.loads(text)
        files[f'.codex/agents/{name}.toml'] = text.encode()
        guide = f'.agents/skills/sdlc-agent-{name}/SKILL.md'
        if guide in files:
            raise ValueError(f'role-guide name collision: {name}')
        header = yaml.safe_dump({'name': 'sdlc-agent-' + name,
                                 'description': f'{name} specialist procedure. ' + role['description']}, sort_keys=False).strip()
        fallback = ('Use the native specialist profile if this host exposes it. Otherwise apply this '
                    'role guide inline or pass it to an authorized generic worker. This guide does '
                    'not enforce the native profile sandbox or grant additional permissions.\n\n')
        files[guide] = f'---\n{header}\n---\n\n{fallback}{role["developer_instructions"]}'.encode()
    rules = '\n\n'.join(
        '# Adapter integrity\nVerify owned file hashes with installer --check. Report drift and review conflicts; '
        'repair is explicit. Hooks must produce evidence and require native trust review. '
        'Snapshots and retention require an explicitly authorized scheduler.\n'
        if p.stem == 'framework-integrity' else adapt(p.read_text(), inv)
        for p in sorted((REPO / '.claude/rules').glob('*.md')))
    files['.codex/framework/rules.md'] = rules.encode()
    files['.codex/framework/inventory.json'] = (json.dumps(inv, indent=2) + '\n').encode()
    files['.codex/framework/mcp.example.toml'] = (REPO / 'codex/mcp.example.toml').read_bytes()
    files['.codex/framework/statusline.example.toml'] = (REPO / 'codex/statusline.example.toml').read_bytes()
    files['.codex/framework/hook.py'] = (REPO / 'codex/hook.py').read_bytes()
    files['.codex/framework/lint.py'] = (REPO / 'codex/lint.py').read_bytes()
    return files


DESCRIPTIONS = {
    'execute': 'Plan and execute a substantial goal with dependency-safe tasks and independent acceptance checks.',
    'multi-agent-orchestration': 'Coordinate authorized Codex subagents, dependency-safe work and independent review.',
    'scheduled-tasks': 'Create or inspect user-requested recurring work using available scheduling capabilities.',
    'remote-triggers': 'Run an explicitly requested remote or headless task with available Codex capabilities.',
    'worktree-workflow': 'Isolate authorized Git work with separate worktrees and preserve existing changes.',
    'context-escalation': 'Preserve task continuity when context is large or a session boundary approaches.',
    'deep-analysis': 'Analyze consequential open decisions using evidence, competing options and optional Sequential Thinking MCP.',
    'skill-creator': 'Create or update a focused Codex skill with portable metadata, resources and behavior validation.',
    'investigate': 'Trace an unknown-cause defect through reproduction and source evidence, then verify an authorized fix. Handle known-cause fixes directly.',
    'compact': 'Write a verified handoff before user-invoked native compaction.',
}


def agent_selection(inv: dict) -> str:
    lines = ['# Native specialist selection', '', 'Discover available agent types before spawning. Inherit model configuration.',
             'If native role types are unavailable, load the corresponding sdlc-agent-<name> skill and apply it inline or pass its procedure to an authorized generic worker.', '']
    for name in inv['agents']:
        meta, _ = frontmatter(REPO / f'.claude/agents/{name}.md')
        lines += [f'### {name}', adapt(meta['description'], inv), '']
    return '\n'.join(lines)


def safe_path(root: Path, rel: str) -> Path:
    parts = Path(rel).parts
    if not parts or Path(rel).is_absolute() or any(p in ('.', '..') for p in parts):
        raise ValueError(f'unsafe manifest path: {rel}')
    if rel not in ('AGENTS.md', '.codex/hooks.json') and not rel.startswith(('.agents/skills/sdlc-', '.codex/agents/', '.codex/framework/')):
        raise ValueError(f'path outside adapter ownership: {rel}')
    path = root / rel
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError(f'symlink destination: {parent}')
        if parent.exists() and parent != path and not parent.is_dir():
            raise ValueError(f'not a directory: {parent}')
    return path


def instructions() -> bytes:
    return f'''{BEGIN}
## SDLC framework for Codex
Discover `.agents/skills/sdlc-*` workflows and `.codex/agents/*.toml` specialists
(user installs use the corresponding home locations). Skill selection and agent
routing use model judgment, not deterministic keyword matching. Use $sdlc-execute
for substantial goals; read $sdlc-deep-read before consequential source changes.
Route implementation outcomes through $sdlc-delivery; read-only questions do not
launch workers. Default roles: Codex coordinates and independently verifies; an
actual Claude execution implements. Only explicit owner or project instructions
override them; defaults do not start a dispatcher. Loading a skill is not
execution; report states from receipts.
If native specialist types are unavailable, use the sdlc-agent-<name> role skills
inline or give their procedures to authorized generic workers.
Read the installed `.codex/framework/rules.md` before implementing or approving work;
for a user install, resolve it under the configured Codex home.
Discover tools/MCP schemas before use. Keep coupled work sequential, parallel writes
in disjoint worktrees, and reviewers independent. Inherit model and approval policy.
The adapter does not grant permission for deployment, messages or live-data writes.
Optional hooks require native /hooks trust review.
If the host exposes a native task-title rename capability (discover its schema),
title only the current task `SDLC | <short task>` once; never rename other threads
or replace an owner-chosen title. Without it, keep the normal title and say so.
The marker means framework guidance loaded, not that checks, review or delivery
passed. Claude's custom statusline renderer, notifications, dashboard and
unattended self-heal are not installed; native footer items are an opt-in example.
{END}
'''.encode()


def merge_instructions(existing: bytes, owned: str | None, remove: bool = False) -> bytes:
    start, end = existing.count(BEGIN.encode()), existing.count(END.encode())
    if (start, end) == (0, 0):
        if owned:
            raise ValueError('managed AGENTS.md block removed locally')
        return existing if remove else existing + instructions()
    if (start, end) != (1, 1):
        raise ValueError('malformed/duplicate AGENTS.md markers')
    lo, hi = existing.index(BEGIN.encode()), existing.index(END.encode()) + len(END)
    if hi < lo:
        raise ValueError('reversed AGENTS.md markers')
    if existing[hi:hi + 1] == b'\n':
        hi += 1
    if not owned or digest(existing[lo:hi]) != owned:
        raise ValueError('foreign or locally modified AGENTS.md block')
    return existing[:lo] + (b'' if remove else instructions()) + existing[hi:]


def load_manifest(root: Path) -> dict:
    path = safe_path(root, MANIFEST.as_posix())
    if not path.exists():
        return {'version': 1, 'files': {}}
    meta = json.loads(path.read_bytes())
    if not isinstance(meta, dict) or meta.get('version') != 1 or not isinstance(meta.get('files'), dict):
        raise ValueError('invalid ownership manifest')
    if meta['files'] and (not isinstance(meta.get('user'), bool) or not isinstance(meta.get('hooks'), bool)
                          or not isinstance(meta.get('instructions'), str)):
        raise ValueError('invalid manifest scope or instruction ownership')
    for name, checksum in meta['files'].items():
        safe_path(root, name)
        if not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum):
            raise ValueError('invalid ownership checksum')
    return meta


def install(root: Path, *, dry_run: bool = False, uninstall: bool = False,
            check: bool = False, hooks: bool = False, user: bool = False) -> list[str]:
    root = root.absolute()
    if any(parent.is_symlink() for parent in (root, *root.parents)):
        raise ValueError('symlink installation root')
    root = root.resolve()
    safe_path(root, MANIFEST.as_posix())
    old = load_manifest(root)
    if old['files'] and old.get('user') != user:
        raise ValueError('installation scope differs from existing manifest')
    if old['files'] and not uninstall and not hooks and old.get('hooks'):
        hooks = True  # Normal updates preserve the explicitly installed hook edition.
    desired = {} if uninstall else build()
    # User agents/config live in CODEX_HOME; user skills still live in ~/.agents/skills.
    # This installer uses a home-shaped target, and supports default Codex home only.
    if hooks and not uninstall:
        command = 'python3 ' + shell_quote(str(root / '.codex/framework/hook.py'))
        events = ('SessionStart', 'SessionEnd', 'SubagentStart', 'SubagentStop', 'PermissionRequest',
                  'PreCompact', 'PostCompact', 'PreToolUse', 'PostToolUse')
        # PostToolUse may run an opt-in approved lint (<=30s command + bounded cleanup),
        # so it needs a wider outer budget than the metadata-only events.
        timeouts = {'SessionEnd': 3, 'PostToolUse': 40}
        config = {'description': 'Optional SDLC evidence hooks; review with /hooks.',
                  'hooks': {event: [{'hooks': [{'type': 'command', 'command': command,
                                              'timeout': timeouts.get(event, 10)}]}] for event in events}}
        desired['.codex/hooks.json'] = (json.dumps(config, indent=2) + '\n').encode()
    agents_path = safe_path(root, 'AGENTS.md') if not user else root / '.codex/AGENTS.md'
    # Apply the same symlink checks for the user instruction destination.
    if user:
        safe_path(root, '.codex/framework/manifest.json')
        if agents_path.is_symlink():
            raise ValueError('symlink user instructions')
    current = agents_path.read_bytes() if agents_path.exists() else b''
    merged = merge_instructions(current, old.get('instructions'), remove=uninstall)
    writes: dict[Path, bytes | None] = {}
    expected: dict[Path, bytes | None] = {}
    for rel in sorted(set(old['files']) | set(desired)):
        # hooks are a distinct opt-in shared file, still protected by ownership hashes.
        path = hook_path(root, rel) if rel == '.codex/hooks.json' else safe_path(root, rel)
        exists = path.exists()
        expected[path] = path.read_bytes() if exists and path.is_file() else None
        if exists and not path.is_file():
            raise ValueError(f'non-file collision: {rel}')
        if exists and (rel not in old['files'] or digest(path.read_bytes()) != old['files'][rel]):
            raise ValueError(f'foreign or locally modified file: {rel}')
        if rel in desired:
            if not exists or path.read_bytes() != desired[rel]:
                writes[path] = desired[rel]
        elif exists:
            writes[path] = None
    if current != merged:
        writes[agents_path] = merged if merged else None
        expected[agents_path] = current if agents_path.exists() else None
    sha = head_sha()
    manifest = {'version': 1, 'source_sha': sha, 'files': {p: digest(v) for p, v in desired.items()},
                'instructions': digest(instructions()) if not uninstall else None,
                'hooks': hooks, 'user': user}
    manifest_path = root / MANIFEST
    expected[manifest_path] = manifest_path.read_bytes() if manifest_path.exists() else None
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    if uninstall:
        if manifest_path.exists():
            writes[manifest_path] = None
    elif not manifest_path.exists() or manifest_path.read_bytes() != encoded:
        writes[manifest_path] = encoded
    changes = [str(p.relative_to(root)) for p in writes]
    if check and changes:
        raise ValueError('adapter drift: ' + ', '.join(changes))
    if not dry_run and not check:
        transaction(root, writes, expected)
    return changes


def shell_quote(value: str) -> str:
    import shlex
    return shlex.quote(value)


def hook_path(root: Path, rel: str) -> Path:
    path = root / rel
    safe_path(root, '.codex/framework/hook.py')
    if path.is_symlink():
        raise ValueError('symlink hooks config')
    return path


def transaction(root: Path, writes: dict[Path, bytes | None], expected: dict[Path, bytes | None]) -> None:
    """Lock, recheck and roll back only the mutations actually attempted on a caught error.

    Rolling back every planned write (not just the attempted ones) would delete a later
    destination this transaction never wrote -- e.g. a file a concurrent local writer created
    after preflight -- because an originally absent path would be unlinked even though its
    forward write never ran. Each path is appended to ``applied`` at its real mutation
    boundary -- immediately before the ``atomic_write`` that replaces it (after all parent
    directories are prepared) or immediately before its ``unlink`` -- and the handler reverses
    only that list (mirrors scripts/install-delivery.py). Parent-directory creation is not a
    mutation of the destination, so if a concurrent writer wins the mkdir race and our own
    ``mkdir`` raises, the destination is never marked applied and its owner content is kept;
    ``atomic_write`` replaces atomically, yet is tracked before the call so a replace-then-error
    still restores the original bytes. A concurrent edit of a path whose write already succeeded
    is still overwritten on rollback and remains an explicit limitation, as does
    power-loss/process-kill recovery.
    """
    if not writes:
        return
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.sdlc-codex-install.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    made_dirs: list[Path] = []
    applied: list[Path] = []
    try:
        for path in expected:
            rel = path.relative_to(root).as_posix()
            if rel != '.codex/AGENTS.md':
                safe_path(root, rel)
            elif path.is_symlink():
                raise ValueError('symlink user instructions')
            actual = path.read_bytes() if path.exists() else None
            if actual != expected[path]:
                raise ValueError(f'concurrent modification: {rel}')
        for path, data in writes.items():
            if data is None:
                applied.append(path)  # mark applied immediately before the unlink
                path.unlink(missing_ok=True)
                continue
            for parent in reversed(path.parents):
                if parent == root or root in parent.parents:
                    if not parent.exists():
                        parent.mkdir()
                        made_dirs.append(parent)
            # Mark applied only after all parent prep, immediately before atomic_write: if a
            # parent mkdir raced and raised, this destination was never attempted and must not
            # be rolled back (which would delete a concurrent writer's file there). atomic_write
            # replaces atomically, but is tracked here so a replace-then-error still restores.
            applied.append(path)
            atomic_write(path, data)
    except BaseException:
        for path in reversed(applied):
            data = expected[path]
            if data is None:
                path.unlink(missing_ok=True)
            elif not path.exists() or path.read_bytes() != data:
                atomic_write(path, data)
        for parent in reversed(made_dirs):
            try:
                parent.rmdir()
            except OSError:
                pass
        raise
    finally:
        os.close(fd)
        lock.unlink()


def atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix='.sdlc-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--project', type=Path, help='install into this project directory')
    scope.add_argument('--user', action='store_true', help='install into default user discovery locations')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--hooks', action='store_true', help='install optional untrusted native hooks')
    args = parser.parse_args()
    if args.user and os.environ.get('CODEX_HOME') and Path(os.environ['CODEX_HOME']).absolute() != Path.home() / '.codex':
        parser.error('custom CODEX_HOME: use --project or install into the documented default home')
    try:
        changes = install(Path.home() if args.user else args.project, dry_run=args.dry_run,
                          uninstall=args.uninstall, check=args.check, hooks=args.hooks, user=args.user)
    except (ValueError, OSError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    print(('Would change' if args.dry_run else 'Changed') + f' {len(changes)} paths')
    for change in changes:
        print(change)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
