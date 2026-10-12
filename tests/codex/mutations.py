#!/usr/bin/env python3
"""Prove selected guards with in-memory defects; never alter repository source."""
import io
from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_framework as acceptance


def mutant(original, before, after):
    path = Path(original.__file__)
    source = path.read_text()
    if source.count(before) != 1:
        raise RuntimeError(f'mutation anchor is not unique in {path.name}')
    module = types.ModuleType(original.__name__)
    module.__file__ = str(path)
    exec(compile(source.replace(before, after, 1), str(path), 'exec'), module.__dict__)
    return module


def run(case):
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([case]))
    return result.wasSuccessful()


def main():
    cases = [
        ('foreign ownership', 'f', acceptance.FrameworkAcceptance, 'test_foreign_collision_changes_nothing',
         "if exists and (rel not in old['files'] or digest(path.read_bytes()) != old['files'][rel]):", 'if False:'),
        ('customized ownership', 'f', acceptance.FrameworkAcceptance, 'test_modified_owned_file_survives_update_and_uninstall',
         "if exists and (rel not in old['files'] or digest(path.read_bytes()) != old['files'][rel]):", 'if False:'),
        ('symlink destinations', 'f', acceptance.FrameworkAcceptance, 'test_symlink_root_parent_and_file_rejected',
         'if parent.is_symlink():', 'if False:'),
        ('symlink root ancestors', 'f', acceptance.FrameworkAcceptance, 'test_symlink_root_parent_and_file_rejected',
         'if any(parent.is_symlink() for parent in (root, *root.parents)):', 'if False:'),
        ('rollback', 'f', acceptance.FrameworkAcceptance, 'test_io_failure_rolls_back_files_and_manifest',
         "for path, data in reversed(list(locals().get('originals', {}).items())):", 'for path, data in []:'),
        ('direct credential patch', 'hook', acceptance.HookAcceptance, 'test_patch_sensitive_add_update_delete_move_and_multiple_files',
         'if sensitive(path) or sensitive(resolved):', 'if False:'),
        ('metadata privacy', 'hook', acceptance.HookAcceptance, 'test_logging_excludes_tool_arguments_and_unsupported_costs',
         "path = STATE / 'events.jsonl'", "row['tool_input'] = event.get('tool_input')\n    path = STATE / 'events.jsonl'"),
        ('cross-skill invocation', 'f', acceptance.FrameworkAcceptance, 'test_generated_skill_invocations_resolve',
         "text = re.sub(rf'(?<![\\w])\\${re.escape(name)}\\b', '$' + PREFIX + name, text)", 'text = text'),
        ('exported resource dependency', 'f', acceptance.FrameworkAcceptance, 'test_packaged_resources_retain_executable_behavior',
         'data = resource.read_bytes()', "data = resource.read_bytes()\n                    if resource.name == 'health_check.py':\n                        data = data.replace(b'import requests', b'import codex_missing_dependency_probe')"),
    ]
    for label, attr, case_class, test, before, after in cases:
        original = getattr(acceptance, attr)
        if not run(case_class(test)):
            raise RuntimeError(f'{label}: baseline is red')
        setattr(acceptance, attr, mutant(original, before, after))
        try:
            if run(case_class(test)):
                raise RuntimeError(f'{label}: defect survived')
        finally:
            setattr(acceptance, attr, original)
        # Actual unmutated rerun is a negative control, not just the original verdict.
        if not run(case_class(test)):
            raise RuntimeError(f'{label}: negative control is red')
        print(f'PASS: {label}: mutation detected; restored negative control passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
