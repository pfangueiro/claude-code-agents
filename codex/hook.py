#!/usr/bin/env python3
"""Opt-in native Codex hooks: metadata evidence and direct-patch file protection.

This is not a shell/MCP sandbox. Arbitrary execution writes require native policy.
No transcripts, commands, patch contents or credentials are retained in evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
import sys

STATE = Path(__file__).resolve().parent
EVENTS = {'SessionStart', 'SessionEnd', 'SubagentStart', 'SubagentStop',
          'PermissionRequest', 'PreCompact', 'PostCompact', 'PreToolUse', 'PostToolUse'}


def patch_paths(command: str) -> list[str]:
    paths = []
    for line in command.splitlines():
        match = re.fullmatch(r'\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)', line)
        if match:
            paths.append(match[1])
    return paths


def sensitive(path: str) -> bool:
    parts = Path(path.replace('\\', '/')).parts
    for part in parts:
        if any(fnmatch.fnmatchcase(part.lower(), pattern) for pattern in
               ('.env', '.env.*', '*.key', '*.pem', '*.p12', '*.pfx', 'credentials.json', 'serviceaccount.json')):
            return True
    normalized = '/'.join(parts).lower()
    lowered = tuple(part.lower() for part in parts)
    return ('secrets' in lowered or '.aws/credentials' in normalized or '.ssh/id_' in normalized
            or '.codex/auth.json' in normalized)


def inspect_event(event: dict) -> dict:
    name = event.get('hook_event_name')
    if name not in EVENTS:
        raise ValueError('unsupported hook event')
    payload = event.get('tool_input', {})
    if not isinstance(payload, dict):
        raise ValueError('invalid tool_input')
    tool = event.get('tool_name', '')
    output: dict = {}
    if name == 'PreToolUse':
        paths = []
        if tool == 'apply_patch':
            command = payload.get('command', payload.get('patch'))
            if not isinstance(command, str) or not command.startswith('*** Begin Patch\n'):
                return {'hookSpecificOutput': {'hookEventName': name, 'permissionDecision': 'deny',
                        'permissionDecisionReason': 'Cannot inspect direct patch payload.'}}
            paths = patch_paths(command)
            if not paths:
                return {'hookSpecificOutput': {'hookEventName': name, 'permissionDecision': 'deny',
                        'permissionDecisionReason': 'Cannot identify patch destinations.'}}
        elif tool in ('Write', 'Edit'):
            value = payload.get('file_path', payload.get('filePath'))
            if not isinstance(value, str):
                return {'hookSpecificOutput': {'hookEventName': name, 'permissionDecision': 'deny',
                        'permissionDecisionReason': 'Cannot inspect file-edit destination.'}}
            paths = [value]
        cwd = event.get('cwd')
        for path in paths:
            resolved = str((Path(cwd) / path).resolve()) if isinstance(cwd, str) else path
            if sensitive(path) or sensitive(resolved):
                output = {'hookSpecificOutput': {'hookEventName': name, 'permissionDecision': 'deny',
                          'permissionDecisionReason': 'Direct edit targets a protected credential path.'}}
                break
    if name == 'PostToolUse' and tool == 'apply_patch':
        output = {'hookSpecificOutput': {'hookEventName': name, 'additionalContext':
                  'Patch completed. Run the project quality gate before claiming the change is verified.'}}
    if name == 'SessionStart':
        manifest = STATE / 'manifest.json'
        try:
            import hashlib
            owned = json.loads(manifest.read_bytes())['files']
            root = STATE.parent.parent
            if not isinstance(owned, dict) or not owned:
                raise ValueError('invalid manifest')
            for p, sha in owned.items():
                parts = Path(p).parts
                if Path(p).is_absolute() or '..' in parts or not p.startswith(('.agents/skills/sdlc-', '.codex/agents/', '.codex/framework/', '.codex/hooks.json')):
                    raise ValueError('unsafe manifest')
                if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
                    raise ValueError('invalid manifest checksum')
                target = root / p
                if any(parent.is_symlink() for parent in (target, *target.parents)):
                    raise ValueError('symlink manifest destination')
            drift = any(not (root / p).is_file() or hashlib.sha256((root / p).read_bytes()).hexdigest() != sha
                        for p, sha in owned.items())
            message = 'Adapter drift detected; run the installer --check and review conflicts.' if drift else 'Adapter files match the ownership manifest.'
        except (OSError, KeyError, TypeError, ValueError):
            message = 'Adapter manifest could not be checked; installation health is unknown.'
        output = {'hookSpecificOutput': {'hookEventName': name, 'additionalContext': message}}
    return output


def log_event(event: dict, output: dict) -> None:
    # Whitelist only identifiers; never log untrusted tool arguments or stdout.
    row = {'timestamp': datetime.now(timezone.utc).isoformat(), 'event': event['hook_event_name'],
           'blocked': output.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'}
    for key in ('session_id', 'turn_id', 'agent_id', 'agent_type', 'tool_name'):
        value = event.get(key)
        if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,200}', value):
            row[key] = value
    path = STATE / 'events.jsonl'
    if path.is_symlink():
        raise ValueError('symlink evidence file')
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps(row) + '\n')


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError('invalid event')
        output = inspect_event(event)
        log_event(event, output)
    except (OSError, ValueError, TypeError) as exc:
        # Exit 2 blocks PreToolUse. Do not print the input or exception payload.
        print('SDLC hook could not verify the event or persist evidence.', file=sys.stderr)
        return 2
    if output:
        print(json.dumps(output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
