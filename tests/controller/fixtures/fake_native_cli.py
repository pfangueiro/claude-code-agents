#!/usr/bin/env python3
"""Synthetic native-protocol CLI for controller acceptance tests. It is never an AI, never
opens a network connection and never reads or writes a real account.

Run only through a generated per-profile wrapper:
    fake_native_cli.py --fake-provider claude|codex --fake-home DIR <native argv...>

DIR is the profile's temporary private config directory. Behaviour comes from
DIR/behavior.json; every turn appends JSON lines to DIR/log/events.jsonl. Markers under
DIR/log and DIR/control coordinate the test fixture only; the engine needs no knowledge of
them.

Fixture-only process control (never a foreign kill):
  DIR/log/live/<pid>-<token>.json  {pid, start, token}: this worker's own pid, OS start
                                   identity and a random token; removed on normal exit.
  DIR/control/crash-<token>        this worker SIGKILLs ITSELF (simulated worker failure).
  DIR/control/terminate-all        every worker of the profile SIGKILLs ITSELF (teardown).
process_state(marker) tells 'running' / 'gone' / 'unknown' from pid + start identity, so a
reused pid is never mistaken for the worker.

Native surface imitated (the shapes controller_providers parses):
  claude  --version | --help | -p --output-format stream-json --verbose (prompt on stdin)
  codex   --version | exec --help | exec --json -C <cwd> - (prompt on stdin)

Prompt data contract: the first non-blank line is SDLC_ASSIGNMENT, the next line one JSON
envelope, then END_SDLC_ASSIGNMENT, then free human instructions.
"""
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

VERSIONS = {'claude': '2.1.323 (Claude Code)', 'codex': 'codex-cli 0.169.0'}
HELP = {
    'claude': ('Usage: claude [options] [prompt]\n  -p, --print  print response and exit\n'
               '  --output-format <format>  text, json or stream-json\n'
               '  --verbose  verbose output\n'),
    'codex': ('Usage: codex exec [OPTIONS] [PROMPT]\n  --json  print events as JSONL\n'
              '  -C, --cd <DIR>  working root\n'),
}
ENVELOPE_KEYS = {'version', 'role', 'plan_id', 'task_id', 'kind', 'objective', 'base_sha',
                 'result_sha', 'write_scope', 'acceptance', 'dependencies', 'checks',
                 'evidence_manifest'}
SHA = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
PLUGIN_NAME = re.compile(r"^NAME = '([^']*)'", re.M)
PS = shutil.which('ps', path='/bin:/usr/bin')
PS_ENV = {'PATH': '/bin:/usr/bin', 'LC_ALL': 'C', 'TZ': 'UTC'}
POLL_SECONDS = 0.05


def _log(home, record):
    record = dict(record, pid=os.getpid(), ns=time.time_ns())
    line = (json.dumps(record, sort_keys=True) + '\n').encode()
    fd = os.open(os.path.join(home, 'log', 'events.jsonl'), os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, LC_ALL='C')
    git = shutil.which('git') or '/usr/bin/git'
    done = subprocess.run([git, '-C', cwd, *args], capture_output=True, env=env, timeout=60,
                          check=False)
    return done.returncode, done.stdout.decode('utf-8', 'replace').strip()


def _ps(pid, field):
    if PS is None:
        return None
    try:
        done = subprocess.run([PS, '-o', f'{field}=', '-p', str(pid)], env=PS_ENV,
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = ' '.join(done.stdout.split())
    return text if done.returncode == 0 and text else None


def start_identity(pid):
    """OS start identity of a live pid, or None when it cannot be observed."""
    if os.path.exists('/proc/self/stat'):
        try:
            with open(f'/proc/{pid}/stat', 'rb') as handle:
                raw = handle.read()
        except OSError:
            return None
        tail = raw.rsplit(b')', 1)[-1].split()  # starttime: field 22, index 19 after comm
        return 'ticks:' + tail[19].decode() if len(tail) > 19 else None
    value = _ps(pid, 'lstart')
    return 'lstart:' + value if value else None


def process_state(marker):
    """'running' only when the marker's pid still carries its recorded start identity and is
    not a zombie; 'gone' when provably not that process; 'unknown' otherwise. Never signals."""
    pid, recorded = marker.get('pid'), marker.get('start')
    if type(pid) is not int or pid <= 1:
        return 'unknown'
    try:
        os.kill(pid, 0)  # existence probe only; delivers no signal
    except ProcessLookupError:
        return 'gone'
    except PermissionError:
        return 'gone'  # another user's process is never this same-user fixture worker
    current = start_identity(pid)
    if current is None or recorded is None:
        return 'unknown'
    if current != recorded:
        return 'gone'
    state = _ps(pid, 'stat')
    if state is None:
        return 'unknown'
    return 'gone' if state.startswith('Z') else 'running'


def _register(home):
    """Publish this worker's positive identity: pid, OS start identity and a private token."""
    marker = {'pid': os.getpid(), 'start': start_identity(os.getpid()), 'token': uuid.uuid4().hex}
    live = os.path.join(home, 'log', 'live')
    os.makedirs(live, exist_ok=True)
    name = f"{marker['pid']}-{marker['token']}"
    tmp = os.path.join(live, f'.{name}.tmp')
    with open(tmp, 'w', encoding='utf-8') as handle:
        json.dump(marker, handle)
    path = os.path.join(live, f'{name}.json')
    os.replace(tmp, path)
    return marker, path


def _watch(home, token):
    """Fixture-only self-termination: on this worker's crash trigger or the profile-wide
    terminate trigger, the worker SIGKILLs ITSELF. No other process is ever signalled."""
    control = os.path.join(home, 'control')
    triggers = (f'crash-{token}', 'terminate-all')
    while True:
        for name in triggers:
            if os.path.exists(os.path.join(control, name)):
                _log(home, {'event': 'self_terminated', 'trigger': name})
                os.kill(os.getpid(), signal.SIGKILL)
        time.sleep(POLL_SECONDS)


def parse_assignment(prompt):
    lines = prompt.split('\n')
    while lines and not lines[0].strip():
        lines.pop(0)
    if len(lines) < 3 or lines[0].strip() != 'SDLC_ASSIGNMENT' \
            or lines[2].strip() != 'END_SDLC_ASSIGNMENT':
        return None, 'header-missing'
    if sum(1 for line in lines if line.strip() == 'SDLC_ASSIGNMENT') != 1:
        return None, 'header-repeated'
    try:
        envelope = json.loads(lines[1])
    except ValueError:
        return None, 'envelope-not-json'
    if type(envelope) is not dict or set(envelope) != ENVELOPE_KEYS or envelope['version'] != 1:
        return None, 'envelope-fields'
    role, result = envelope['role'], envelope['result_sha']
    if role not in ('implement', 'review') or not SHA.fullmatch(str(envelope['base_sha'])):
        return None, 'envelope-role-or-base'
    if (role == 'implement') != (result is None) or (result is not None and not SHA.fullmatch(result)):
        return None, 'envelope-result'
    if type(envelope['write_scope']) is not list or type(envelope['dependencies']) is not dict:
        return None, 'envelope-shape'
    return envelope, None


class Stream:
    """Native JSONL emitter; the start event is written at most once."""

    def __init__(self, provider, session, cwd):
        self.provider, self.session, self.cwd, self.started = provider, session, cwd, False

    def _emit(self, event):
        sys.stdout.write(json.dumps(event) + '\n')
        sys.stdout.flush()

    def start(self):
        if self.started:
            return
        self.started = True
        if self.provider == 'claude':
            self._emit({'type': 'system', 'subtype': 'init', 'session_id': self.session,
                        'cwd': self.cwd, 'model': 'synthetic-fixture', 'tools': []})
        else:
            self._emit({'type': 'thread.started', 'thread_id': self.session})
            self._emit({'type': 'turn.started'})

    def finish(self, text, ok=True, quota=None, error=None):
        self.start()
        if self.provider == 'codex':
            if ok:
                self._emit({'type': 'item.completed',
                            'item': {'id': 'item_0', 'type': 'agent_message', 'text': text}})
            self._emit({'type': 'turn.completed' if ok else 'turn.failed',
                        'usage': {'input_tokens': 0, 'output_tokens': 0}})
            return
        if error:
            self._emit({'type': 'assistant', 'session_id': self.session, 'error': error,
                        'message': {'role': 'assistant', 'content': []}})
        # Quota snapshot without resetsAt: no reset time is known, so none is offered.
        self._emit({'type': 'rate_limit_event', 'session_id': self.session,
                    'rate_limit_info': {'status': quota or 'allowed', 'rateLimitType': 'five_hour'}})
        self._emit({'type': 'result', 'subtype': 'success' if ok else 'error_during_execution',
                    'is_error': not ok, 'session_id': self.session, 'result': text,
                    'permission_denials': []})


def _in_scope(path, scope):
    return any(path == entry or (entry.endswith('/') and path.startswith(entry)) for entry in scope)


def _barrier(home, task, spec, marker):
    """Wait until every barrier task has a running implementer, proven by pid plus OS start
    identity (never by sleep or a bare pid)."""
    directory = os.path.join(home, 'log', 'barrier')
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f'{task}.{os.getpid()}'), 'w', encoding='utf-8') as handle:
        json.dump(marker['start'], handle)
    deadline = time.monotonic() + spec['timeout']
    while time.monotonic() < deadline:
        live = {}
        for name in os.listdir(directory):
            peer, _, pid = name.rpartition('.')
            try:
                with open(os.path.join(directory, name), encoding='utf-8') as handle:
                    start = json.load(handle)
                pid = int(pid)
            except (OSError, ValueError):
                continue  # a peer file still being written is read on the next poll
            if process_state({'pid': pid, 'start': start}) == 'running':
                live[peer] = pid
        if all(name in live for name in spec['tasks']):
            return {'met': True, 'peers': {name: live[name] for name in spec['tasks']}}
        time.sleep(POLL_SECONDS)
    return {'met': False, 'peers': {}}


def _hold(home, task, spec, stream, cwd, scope, base, marker):
    """Leave partial work, announce readiness, then wait for the test's go marker."""
    if spec.get('once'):
        try:
            os.close(os.open(os.path.join(home, 'log', f'held-{task}'), os.O_CREAT | os.O_EXCL))
        except FileExistsError:
            return True
    with open(os.path.join(cwd, scope[0]), 'w', encoding='utf-8') as handle:
        handle.write('# partial work, interrupted fixture\n')
    stream.start()
    ready = {'pid': os.getpid(), 'pgid': os.getpgid(0), 'cwd': cwd, 'session': stream.session,
             'partial': scope[0], 'base': base, 'start': marker['start'], 'token': marker['token']}
    tmp = os.path.join(home, 'log', f'.ready-{task}.tmp')
    with open(tmp, 'w', encoding='utf-8') as handle:
        json.dump(ready, handle)
    os.replace(tmp, os.path.join(home, 'log', f'ready-{task}.json'))
    go = os.path.join(home, 'control', f'go-{task}')
    deadline = time.monotonic() + spec.get('timeout', 180)
    while time.monotonic() < deadline:
        if os.path.exists(go):
            return True
        time.sleep(POLL_SECONDS)
    return False


def implement(home, behavior, envelope, stream, cwd, record, marker):
    task, scope = envelope['task_id'], envelope['write_scope']
    earlier = [{'pid': r['pid'], 'start': r.get('proc_start')} for r in _events(home)
               if r.get('event') == 'start' and r.get('role') == 'implement'
               and r.get('task_id') == task and r['pid'] != os.getpid()]
    # A peer whose liveness cannot be told counts as alive: duplicate detection fails closed.
    record['alive_peers'] = [peer['pid'] for peer in earlier if process_state(peer) != 'gone']
    if task in behavior.get('barrier', {}).get('tasks', ()):
        record['barrier'] = _barrier(home, task, behavior['barrier'], marker)
    hold = behavior.get('hold', {})
    if task in hold.get('tasks', ()) and not _hold(home, task, hold, stream, cwd, scope,
                                                     envelope['base_sha'], marker):
        return None
    written = []
    for path, content in behavior['recipes'][task].items():
        if not _in_scope(path, scope):
            record['scope_violation'] = path
            return None
        target = os.path.join(cwd, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w', encoding='utf-8') as handle:
            # A per-session comment makes every run a different but equivalent patch.
            handle.write(f'# produced in session {stream.session}\n{content}')
        written.append(path)
    record['written'] = written
    return f'Implemented {", ".join(written)} for {task}.'


def review(behavior, envelope, cwd, record):
    base, result = envelope['base_sha'], envelope['result_sha']
    exists = all(_git(cwd, 'cat-file', '-e', f'{sha}^{{commit}}')[0] == 0 for sha in (base, result))
    record['range_ok'] = exists and _git(cwd, 'merge-base', '--is-ancestor', base, result)[0] == 0
    code, listing = _git(cwd, 'ls-tree', '-r', '--name-only', result) if exists else (1, '')
    record['files'] = sorted(listing.split('\n')) if code == 0 and listing else []
    findings = [] if record['range_ok'] else ['assigned base..result is not a Git ancestry range']
    if behavior.get('review_rule') == 'unique_plugins':
        names = []
        for path in (p for p in record['files'] if p.startswith('plugins/')):
            match = PLUGIN_NAME.search(_git(cwd, 'show', f'{result}:{path}')[1])
            names.append(match.group(1) if match else None)
        if len(set(names)) != len(names):
            findings.append(f'duplicate plugin names in the combined result: {names}')
    verdict = 'FAIL' if findings else 'PASS'
    record['verdict'] = verdict
    block = json.dumps({'version': 1, 'verdict': verdict, 'base_sha': base, 'result_sha': result,
                        'findings': findings, 'gaps': []})
    return f'Reviewed {base[:12]}..{result[:12]}.\n\n```sdlc-verdict\n{block}\n```\n'


def _events(home):
    try:
        with open(os.path.join(home, 'log', 'events.jsonl'), encoding='utf-8') as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []


def turn(provider, home, args, marker):
    cwd = os.path.realpath(os.getcwd())
    if provider == 'codex' and '-C' in args:
        declared = args[args.index('-C') + 1]
        cwd = os.path.realpath(declared) if os.path.realpath(declared) == cwd else cwd
    prompt = sys.stdin.buffer.read().decode('utf-8', 'replace')
    with open(os.path.join(home, 'behavior.json'), encoding='utf-8') as handle:
        behavior = json.load(handle)
    session = str(uuid.uuid4())
    stream = Stream(provider, session, cwd)
    selector = 'CLAUDE_CONFIG_DIR' if provider == 'claude' else 'CODEX_HOME'
    envelope, problem = parse_assignment(prompt)
    record = {'session': session, 'argv': args, 'cwd': cwd, 'pgid': os.getpgid(0),
              'proc_start': marker['start'],
              'config_env': os.environ.get(selector), 'problem': problem,
              'envelope': envelope, 'head': _git(cwd, 'rev-parse', 'HEAD')[1] or None,
              'role': envelope and envelope['role'], 'task_id': envelope and envelope['task_id']}
    _log(home, dict(record, event='start'))
    mode = behavior.get('mode', 'work')
    if problem:
        stream.finish(f'unusable assignment: {problem}', ok=False)
        outcome, code = 'bad_assignment', 1
    elif mode == 'quota':
        stream.finish('', ok=False, quota='rejected')
        outcome, code = 'quota_rejected', 1
    elif mode == 'auth':
        stream.finish('', ok=False, error='authentication_failed')
        outcome, code = 'auth_failed', 1
    else:
        text = (implement(home, behavior, envelope, stream, cwd, record, marker)
                if envelope['role'] == 'implement' else review(behavior, envelope, cwd, record))
        stream.finish(text or 'work not completed', ok=text is not None)
        outcome, code = ('done', 0) if text else ('not_done', 3)
    _log(home, dict(record, event='end', outcome=outcome))
    return code


def main(argv):
    if len(argv) < 4 or argv[0] != '--fake-provider' or argv[2] != '--fake-home':
        sys.stderr.write('fake_native_cli: wrapper arguments missing\n')
        return 64
    provider, home, args = argv[1], argv[3], argv[4:]
    if args == ['--version']:
        print(VERSIONS[provider])
        return 0
    if args == (['--help'] if provider == 'claude' else ['exec', '--help']):
        sys.stdout.write(HELP[provider])
        return 0
    native = (('-p' in args or '--print' in args) and 'stream-json' in args if provider == 'claude'
              else args[:1] == ['exec'] and '--json' in args)
    if not native:
        _log(home, {'event': 'unrecognized', 'argv': args})
        sys.stderr.write('fake_native_cli: unrecognized invocation\n')
        return 2
    marker, live_path = _register(home)
    threading.Thread(target=_watch, args=(home, marker['token']), daemon=True).start()
    try:
        return turn(provider, home, args, marker)
    finally:
        # Only a normal exit removes the marker; a self-kill leaves it for settlement proof.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(live_path)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
