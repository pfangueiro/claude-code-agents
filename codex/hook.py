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
SUPPORTED_EDITS = {'apply_patch', 'Write', 'Edit'}
# Canonical model-facing success text emitted by the native apply_patch tool (and its
# Write/Edit matcher aliases). Source: openai/codex apply-patch/tests/suite/tool.rs.
APPLY_PATCH_SUCCESS = 'Success. Updated the following files:'
QUALITY_GATE_REMINDER = 'Edit completed. Run the project quality gate before claiming the change is verified.'
UNCONFIRMED_EDIT_REMINDER = ('Edit result was not reported as a confirmed success, so no post-edit lint ran. '
                             'Run the project quality gate before claiming the change is verified.')


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


def edit_failed(event: dict) -> bool:
    """True only when the event explicitly reports the edit did not succeed."""
    for key in ('tool_output', 'tool_response', 'tool_result'):
        value = event.get(key)
        if isinstance(value, dict) and (value.get('error') or value.get('success') is False
                                        or value.get('status') in ('error', 'failed', 'blocked')):
            return True
    return event.get('success') is False


def edit_succeeded(event: dict) -> bool:
    """True only for a recognized positive result from a supported edit tool.

    Native apply_patch (and the Write/Edit aliases) report the canonical model-facing success
    string; structured tool results may carry {"success": true}. The native docs treat
    tool_response as arbitrary JSON, so anything else — an unknown, missing or unrecognized
    result — is never assumed to be a successful edit.
    """
    for key in ('tool_response', 'tool_output', 'tool_result'):
        if key not in event:
            continue
        value = event[key]
        if isinstance(value, str):
            return value.startswith(APPLY_PATCH_SUCCESS)
        if isinstance(value, dict) and value.get('success') is True:
            return True
        return False
    return False


def _reminder(message: str) -> dict:
    return {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': message}}


def post_edit_output(event: dict) -> dict:
    """Feedback for a supported PostToolUse edit.

    Only a recognized successful edit may run the opt-in lint (or, without opt-in, emit the
    quality-gate reminder). An explicitly failed edit yields no feedback; an unknown, missing
    or unrecognized result falls back to a reminder that does not assert the edit succeeded.
    A missing/broken lint runner never affects the credential guard; it falls back here.
    """
    if edit_failed(event):
        return {}
    if not edit_succeeded(event):
        return _reminder(UNCONFIRMED_EDIT_REMINDER)
    reminder = _reminder(QUALITY_GATE_REMINDER)
    try:
        import lint
    except ImportError:
        return reminder
    result = lint.run_lint(event)
    return result if result is not None else reminder


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
    if name == 'PostToolUse' and tool in SUPPORTED_EDITS:
        output = post_edit_output(event)
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
