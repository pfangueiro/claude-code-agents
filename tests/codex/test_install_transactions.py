"""Regression for the Codex install transaction rollback (SEC-01).

A caught first-write failure must roll back only the mutations it actually attempted. The
earlier version rebuilt `originals` from every PLANNED write and reversed all of them, so a
later destination a concurrent local writer created or edited after preflight was unlinked
even though this transaction never wrote it — losing the owner's file. `transaction` now
appends each path to `applied` immediately before mutating it and reverses only that list,
mirroring scripts/install-delivery.py. These checks assert the preserved-file behaviour and
pin the one documented limitation (an already-applied path's concurrent edit is reverted).
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

real_mkdir = Path.mkdir

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'codex'))
import framework as f  # noqa: E402

LOCK = '.sdlc-codex-install.lock'


class TransactionRollback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='codex-txn-')
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def owned(self, name: str) -> Path:
        # A path inside adapter ownership so transaction's safe_path preflight accepts it.
        return self.root / '.codex/agents' / name

    def test_unattempted_later_destination_created_concurrently_survives(self):
        first, later = self.owned('first.toml'), self.owned('later.toml')
        owner_bytes = b'owner content written by a concurrent local writer\n'
        writes = {first: b'first payload\n', later: b'later payload\n'}
        expected = {first: None, later: None}  # both absent at preflight
        real_write = f.atomic_write

        def fail_before_first(path, data):
            if path == first:
                # A separate local writer creates the later destination after preflight,
                # then this transaction's first write fails before it is reached.
                later.parent.mkdir(parents=True, exist_ok=True)
                later.write_bytes(owner_bytes)
                raise OSError('simulated disk write error')
            return real_write(path, data)

        with patch.object(f, 'atomic_write', fail_before_first):
            with self.assertRaises(OSError):
                f.transaction(self.root, writes, expected)

        self.assertTrue(later.exists(), 'rollback must not delete an unwritten later destination')
        self.assertEqual(later.read_bytes(), owner_bytes)
        self.assertFalse(first.exists(), 'the attempted, originally-absent path is restored (removed)')
        self.assertFalse((self.root / LOCK).exists(), 'lock cleanup must complete')

    def test_attempted_existing_path_restored_and_unwritten_edit_preserved(self):
        first, later = self.owned('first.toml'), self.owned('later.toml')
        first.parent.mkdir(parents=True, exist_ok=True)
        orig_first = b'original owner content of first\n'
        orig_later = b'original owner content of later\n'
        first.write_bytes(orig_first)
        later.write_bytes(orig_later)
        edited_later = b'later edited by a concurrent writer after preflight\n'
        writes = {first: b'new first\n', later: b'new later\n'}
        expected = {first: orig_first, later: orig_later}
        real_write = f.atomic_write

        def fail_before_first(path, data):
            if path == first:
                later.write_bytes(edited_later)  # concurrent edit of the not-yet-written dest
                raise OSError('simulated disk write error')
            return real_write(path, data)

        with patch.object(f, 'atomic_write', fail_before_first):
            with self.assertRaises(OSError):
                f.transaction(self.root, writes, expected)

        self.assertEqual(first.read_bytes(), orig_first, 'attempted existing path restored to original')
        self.assertEqual(later.read_bytes(), edited_later, 'unwritten later destination keeps the owner edit')
        self.assertFalse((self.root / LOCK).exists())

    def test_parent_mkdir_race_preserves_unattempted_destination(self):
        # SAFETY-IR03: a destination must be marked applied only at its real mutation
        # boundary. If a concurrent writer wins the parent-directory race, the installer's
        # own mkdir raises FileExistsError BEFORE any atomic_write. Rollback must not then
        # delete the concurrent owner file at a destination this transaction never wrote.
        dest = self.owned('newdir/file.toml')
        later = self.owned('later.toml')
        owner_bytes = b'concurrent owner content\n'
        writes = {dest: b'framework payload\n', later: b'later payload\n'}
        expected = {dest: None, later: None}  # both absent at preflight
        attempted: list[str] = []

        def race_mkdir(self_path, *args, **kwargs):
            if self_path == dest.parent:
                real_mkdir(self_path, *args, **kwargs)     # the concurrent writer's dir
                dest.write_bytes(owner_bytes)              # ... and its file
                raise FileExistsError('synthetic concurrent writer won the mkdir race')
            return real_mkdir(self_path, *args, **kwargs)

        def record_write(path, data):
            attempted.append(str(path))
            raise AssertionError('no atomic_write may be attempted once mkdir raced')

        with patch.object(Path, 'mkdir', race_mkdir), patch.object(f, 'atomic_write', record_write):
            with self.assertRaises(FileExistsError):
                f.transaction(self.root, writes, expected)

        self.assertEqual(attempted, [], 'zero atomic writes before the mkdir race failure')
        self.assertTrue(dest.exists(), 'concurrent owner file at an unattempted dest survives')
        self.assertEqual(dest.read_bytes(), owner_bytes)
        self.assertFalse(later.exists(), 'the later destination was never created')
        self.assertFalse((self.root / LOCK).exists(), 'lock cleanup must complete')

    def test_partial_atomic_replace_then_error_restores_original(self):
        # Positive control for the moved boundary: when atomic_write genuinely replaces an
        # existing destination and THEN a later write raises, rollback must restore the
        # original bytes -- so the attempt is tracked immediately before atomic_write.
        first, later = self.owned('first.toml'), self.owned('later.toml')
        first.parent.mkdir(parents=True, exist_ok=True)
        orig_first = b'original owner content of first\n'
        first.write_bytes(orig_first)
        writes = {first: b'new first\n', later: b'new later\n'}
        expected = {first: orig_first, later: None}
        real_write = f.atomic_write
        calls: list[str] = []

        def replace_then_fail(path, data):
            calls.append(str(path))
            real_write(path, data)                     # genuinely replaces the destination
            if path == later:
                raise OSError('simulated error after a real replacement')

        with patch.object(f, 'atomic_write', replace_then_fail):
            with self.assertRaises(OSError):
                f.transaction(self.root, writes, expected)

        self.assertEqual(first.read_bytes(), orig_first, 'first restored to original bytes')
        self.assertFalse(later.exists(), 'originally-absent later removed on rollback')
        # Forward pass genuinely attempted both writes before the error (the rollback restore
        # of first is a third call through the same patched atomic_write).
        self.assertEqual(calls[:2], [str(first), str(later)], 'both forward writes attempted')
        self.assertFalse((self.root / LOCK).exists())

    def test_already_applied_path_concurrent_edit_is_reverted_documented_limitation(self):
        # Honest limitation: once a path's write has SUCCEEDED, a concurrent edit to it is
        # overwritten when a LATER write fails. This is out of scope for the minimal fix and
        # is pinned here so it is not mistaken as solved.
        first, later = self.owned('first.toml'), self.owned('later.toml')
        first.parent.mkdir(parents=True, exist_ok=True)
        orig_first = b'original owner content of first\n'
        first.write_bytes(orig_first)
        writes = {first: b'new first\n', later: b'new later\n'}
        expected = {first: orig_first, later: None}
        real_write = f.atomic_write

        def fail_on_later(path, data):
            if path == later:
                first.write_bytes(b'concurrent edit after first succeeded\n')
                raise OSError('simulated disk write error')
            return real_write(path, data)

        with patch.object(f, 'atomic_write', fail_on_later):
            with self.assertRaises(OSError):
                f.transaction(self.root, writes, expected)

        self.assertEqual(first.read_bytes(), orig_first, 'already-applied path is reverted to its pre-state')
        self.assertFalse(later.exists())
        self.assertFalse((self.root / LOCK).exists())


if __name__ == '__main__':
    unittest.main()
