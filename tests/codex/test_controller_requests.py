"""Private request inbox of the persistent controller, on real private files.

No ledger, provider, network or real home is used: these tests exercise the file layer
(immutable publish, strict parsing, acknowledgement guards, read-only listing).
"""
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.claude/skills/delivery/scripts'))
import controller_requests as inbox  # noqa: E402

CONTEXT = {'epoch': 1, 'policy_digest': 'a' * 64, 'identity': {'runtime': 'b' * 64, 'rules': 'c' * 64}}


def canonical(record):
    return (json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
            + '\n').encode('utf-8')


def put(path, data, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
    os.chmod(path, mode)


class RequestInbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='controller-requests-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.state = self.tmp / 'state'
        self.state.mkdir(mode=0o700)
        self.inbox = self.state / inbox.REQUESTS_DIR

    def refresh(self, request_id=None, actor='owner', when=1700000000):
        return inbox.refresh_request('claude-1', 'claude', actor, CONTEXT, when, request_id)

    def code(self, call, *args):
        with self.assertRaises(inbox.RequestError) as caught:
            call(*args)
        return caught.exception.code

    def snapshot(self):
        entries = {}
        for path in [self.state, *sorted(self.state.rglob('*'))]:
            info = path.lstat()
            data = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
            entries[str(path)] = (info.st_mode, info.st_mtime_ns, info.st_size, data)
        return entries

    def test_enqueue_publishes_private_canonical_record(self):
        record = self.refresh()
        queued = inbox.enqueue(str(self.state), record)
        self.assertEqual(queued['status'], 'queued')
        self.assertIsNone(queued['ack'])
        path = self.inbox / f"{record['id']}.json"
        self.assertEqual(stat.S_IMODE(self.inbox.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.read_bytes(), canonical(record))
        self.assertEqual(sorted(os.listdir(self.inbox)), [path.name])
        views = inbox.list_requests(str(self.state))
        self.assertEqual([(v['id'], v['status'], v['action']) for v in views],
                         [(record['id'], 'pending', 'refresh_profile')])
        self.assertNotIn('actor', views[0]['summary'])

    def test_identical_request_is_idempotent_and_conflicting_id_refused(self):
        record = self.refresh(request_id='refresh-one')
        first = inbox.enqueue(str(self.state), record)
        again = inbox.enqueue(str(self.state), self.refresh(request_id='refresh-one'))
        self.assertEqual((again['status'], again['sha256']), ('already_queued', first['sha256']))
        before = (self.inbox / 'refresh-one.json').read_bytes()
        other = self.refresh(request_id='refresh-one', when=1700000001)
        self.assertEqual(self.code(inbox.enqueue, str(self.state), other), 'conflict')
        self.assertEqual((self.inbox / 'refresh-one.json').read_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.inbox)), ['refresh-one.json'])

    def test_publish_fsyncs_file_before_directory(self):
        real, kinds = os.fsync, []

        def spy(fd):
            kinds.append('dir' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
            return real(fd)

        with mock.patch.object(inbox.os, 'fsync', side_effect=spy):
            inbox.enqueue(str(self.state), self.refresh())
        self.assertIn('file', kinds)
        self.assertEqual(kinds[-1], 'dir')
        self.assertLess(kinds.index('file'), len(kinds) - 1)

    def test_symlinked_requests_directory_is_refused(self):
        target = self.tmp / 'elsewhere'
        target.mkdir(mode=0o700)
        os.symlink(target, self.inbox)
        self.assertEqual(self.code(inbox.enqueue, str(self.state), self.refresh()), 'insecure')
        self.assertEqual(self.code(inbox.list_requests, str(self.state)), 'insecure')
        self.assertEqual(os.listdir(target), [])

    def test_unsafe_torn_or_unknown_records_are_invalid(self):
        inbox.enqueue(str(self.state), self.refresh(request_id='good-1'))
        valid = canonical(self.refresh(request_id='torn-1'))
        put(self.inbox / 'torn-1.json', valid[:-12])
        put(self.inbox / 'dup-1.json', b'{"a":1,"a":2}\n')
        put(self.inbox / 'nan-1.json', b'{"a":NaN}\n')
        put(self.inbox / 'loose-1.json', canonical(self.refresh(request_id='loose-1')), 0o644)
        put(self.inbox / 'spaced-1.json', json.dumps(self.refresh(request_id='spaced-1'),
                                                     indent=1).encode())
        put(self.inbox / 'huge-1.json', b' ' * (inbox.MAX_REQUEST_BYTES + 1))
        os.symlink(self.inbox / 'good-1.json', self.inbox / 'link-1.json')
        shell = {'version': 1, 'id': 'shell-1', 'action': 'shell', 'context': CONTEXT,
                 'payload': {'argv': ['/bin/sh', '-c', 'true']}}
        put(self.inbox / 'shell-1.json', canonical(shell))
        put(self.inbox / '.tmp-leftover', b'partial')
        views = {v['id']: (v['status'], v['code']) for v in inbox.list_requests(str(self.state))}
        self.assertEqual(views, {
            'good-1': ('pending', None), 'torn-1': ('invalid', 'corrupt'),
            'dup-1': ('invalid', 'corrupt'), 'nan-1': ('invalid', 'corrupt'),
            'loose-1': ('invalid', 'insecure'), 'spaced-1': ('invalid', 'corrupt'),
            'huge-1': ('invalid', 'too_large'), 'link-1': ('invalid', 'insecure'),
            'shell-1': ('invalid', 'unknown_action')})
        self.assertEqual(self.code(inbox.load_request, str(self.state), 'torn-1'), 'corrupt')
        self.assertEqual(self.code(inbox.enqueue, str(self.state), shell), 'unknown_action')
        self.assertEqual(self.code(inbox.enqueue, str(self.state),
                                   self.refresh(request_id='torn-1')), 'conflict')

    def test_builders_refuse_bad_payloads_without_echo(self):
        secret = 'token=abcdef1234567890'
        with self.assertRaises(inbox.RequestError) as caught:
            self.refresh(actor=secret)
        self.assertEqual(caught.exception.code, 'credential')
        self.assertNotIn('abcdef1234567890', str(caught.exception))
        self.assertEqual(self.code(inbox.refresh_request, 'claude-1', 'shell', 'owner', CONTEXT,
                                   1700000000), 'schema')
        self.assertEqual(self.code(self.refresh, None, 'owner', 1.5), 'schema')
        self.assertEqual(self.code(self.refresh, None, 'owner', True), 'schema')
        self.assertEqual(self.code(inbox.refresh_request, 'claude-1', 'claude', 'owner',
                                   {'epoch': 1}, 1700000000), 'schema')
        plan = {'id': 'plan-1'}
        self.assertEqual(self.code(inbox.submit_request, plan, {'plan_digest': '0' * 64},
                                   CONTEXT), 'schema')
        self.assertFalse(self.inbox.exists())

    def test_listing_is_read_only(self):
        self.assertEqual(inbox.list_requests(str(self.state)), [])
        self.assertFalse(self.inbox.exists())
        inbox.enqueue(str(self.state), self.refresh(request_id='one'))
        inbox.enqueue(str(self.state), self.refresh(request_id='two', when=1700000005))
        before = self.snapshot()
        self.assertEqual(len(inbox.list_requests(str(self.state))), 2)
        inbox.load_request(str(self.state), 'one')
        self.assertEqual(before, self.snapshot())

    def test_acknowledgement_is_tied_to_exact_request_and_immutable(self):
        record = self.refresh(request_id='ack-me')
        sha = inbox.enqueue(str(self.state), record)['sha256']
        state = str(self.state)
        self.assertEqual(self.code(inbox.acknowledge, state, 'ack-me', '0' * 64, 'refused',
                                   'plan_invalid'), 'ack_mismatch')
        self.assertFalse((self.inbox / 'ack-me.ack.json').exists())
        self.assertEqual(self.code(inbox.acknowledge, state, 'absent', sha, 'refused',
                                   'plan_invalid'), 'missing')
        self.assertEqual(self.code(inbox.acknowledge, state, 'ack-me', sha, 'executed',
                                   'done'), 'schema')
        first = inbox.acknowledge(state, 'ack-me', sha, 'observed', 'operator_refresh',
                                  {'profile_id': 'claude-1'}, 3)
        again = inbox.acknowledge(state, 'ack-me', sha, 'observed', 'operator_refresh',
                                  {'profile_id': 'claude-1'}, 4)
        self.assertEqual(first, again)
        stored = (self.inbox / 'ack-me.ack.json').read_bytes()
        self.assertEqual(self.code(inbox.acknowledge, state, 'ack-me', sha, 'refused',
                                   'unknown_profile'), 'ack_conflict')
        self.assertEqual((self.inbox / 'ack-me.ack.json').read_bytes(), stored)
        self.assertEqual((self.inbox / 'ack-me.json').read_bytes(), canonical(record))
        view = inbox.list_requests(state)[0]
        self.assertEqual((view['status'], view['code']), ('observed', 'operator_refresh'))
        again = inbox.enqueue(state, record)
        self.assertEqual((again['status'], again['ack']['outcome']), ('already_queued', 'observed'))

    def test_unreadable_acknowledgement_is_never_retried(self):
        record = self.refresh(request_id='bad-ack')
        sha = inbox.enqueue(str(self.state), record)['sha256']
        put(self.inbox / 'bad-ack.ack.json', b'{not json')
        view = inbox.list_requests(str(self.state))[0]
        self.assertEqual((view['status'], view['code']), ('ack_invalid', 'corrupt'))
        self.assertEqual(self.code(inbox.acknowledge, str(self.state), 'bad-ack', sha, 'refused',
                                   'plan_invalid'), 'corrupt')
        self.assertEqual((self.inbox / 'bad-ack.ack.json').read_bytes(), b'{not json')

    def test_consumer_requires_a_controller_lease(self):
        ledger = types.SimpleNamespace(fence=None, state_dir=str(self.state))
        self.assertEqual(self.code(inbox.consume_pending, ledger, CONTEXT['identity']),
                         'lease_required')


if __name__ == '__main__':
    unittest.main()
