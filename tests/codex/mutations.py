#!/usr/bin/env python3
"""Prove selected guards with in-memory defects; never alter repository source."""
import io
from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_framework as acceptance
import test_lint


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
        ('foreign ownership', acceptance, 'f', acceptance.FrameworkAcceptance, 'test_foreign_collision_changes_nothing',
         "if exists and (rel not in old['files'] or digest(path.read_bytes()) != old['files'][rel]):", 'if False:'),
        ('customized ownership', acceptance, 'f', acceptance.FrameworkAcceptance, 'test_modified_owned_file_survives_update_and_uninstall',
         "if exists and (rel not in old['files'] or digest(path.read_bytes()) != old['files'][rel]):", 'if False:'),
        ('symlink destinations', acceptance, 'f', acceptance.FrameworkAcceptance, 'test_symlink_root_parent_and_file_rejected',
         'if parent.is_symlink():', 'if False:'),
        ('symlink root ancestors', acceptance, 'f', acceptance.FrameworkAcceptance, 'test_symlink_root_parent_and_file_rejected',
         'if any(parent.is_symlink() for parent in (root, *root.parents)):', 'if False:'),
        ('rollback', acceptance, 'f', acceptance.FrameworkAcceptance, 'test_io_failure_rolls_back_files_and_manifest',
         'for path in reversed(applied):', 'for path in []:'),
        ('direct credential patch', acceptance, 'hook', acceptance.HookAcceptance, 'test_patch_sensitive_add_update_delete_move_and_multiple_files',
         'if sensitive(path) or sensitive(resolved):', 'if False:'),
        ('metadata privacy', acceptance, 'hook', acceptance.HookAcceptance, 'test_logging_excludes_tool_arguments_and_unsupported_costs',
         "path = STATE / 'events.jsonl'", "row['tool_input'] = event.get('tool_input')\n    path = STATE / 'events.jsonl'"),
        ('cross-skill invocation', acceptance, 'f', acceptance.FrameworkAcceptance, 'test_generated_skill_invocations_resolve',
         "text = re.sub(rf'(?<![\\w])\\${re.escape(name)}\\b', '$' + PREFIX + name, text)", 'text = text'),
        ('exported resource dependency', acceptance, 'f', acceptance.FrameworkAcceptance, 'test_packaged_resources_retain_executable_behavior',
         'data = resource.read_bytes()', "data = resource.read_bytes()\n                    if resource.name == 'health_check.py':\n                        data = data.replace(b'import requests', b'import codex_missing_dependency_probe')"),
        # New opt-in lint trust/failure mechanisms.
        ('lint registry ownership', test_lint, 'lint', test_lint.RegistrySafety, 'test_not_owned_by_effective_user_rejected',
         'if info.st_uid != os.geteuid():', 'if False:'),
        ('lint registry writability', test_lint, 'lint', test_lint.RegistrySafety, 'test_group_or_world_writable_rejected',
         'if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):', 'if False:'),
        ('lint approved-root match', test_lint, 'lint', test_lint.RegistryGating, 'test_unapproved_cwd_falls_back_to_reminder',
         "entry['root'] == canonical", 'True'),
        ('lint failure visibility', test_lint, 'lint', test_lint.CommandExecution, 'test_failing_command_reports_exit_code_without_output_or_argv',
         'if proc.returncode == 0:', 'if True:'),
        ('lint descendant cleanup', test_lint, 'lint', test_lint.CommandExecution, 'test_leader_exit_cleans_lingering_descendant',
         '        _signal_group(pgid, signal.SIGKILL)\n        _wait_group_exit(pgid, GRACE)', '        pass'),
        # New remediation controls: incomplete work is not a pass, approval is owner-global,
        # and only a recognized successful edit runs lint.
        ('lint incomplete not reported as pass', test_lint, 'lint', test_lint.CommandExecution, 'test_leader_exit_cleans_lingering_descendant',
         'if killed:', 'if False:'),
        ('lint central owner-global registry', test_lint, 'lint', test_lint.RegistryLocation, 'test_registry_is_user_global_not_project_local',
         "REGISTRY = Path.home() / '.codex/framework/lint-projects.json'",
         "REGISTRY = Path(__file__).resolve().parent / 'lint-projects.json'"),
        ('lint positive-success gate', test_lint, 'hook', test_lint.HookIntegration, 'test_unrecognized_edit_result_does_not_run_lint',
         'if not edit_succeeded(event):', 'if False:'),
    ]
    for label, module, attr, case_class, test, before, after in cases:
        original = getattr(module, attr)
        if not run(case_class(test)):
            raise RuntimeError(f'{label}: baseline is red')
        setattr(module, attr, mutant(original, before, after))
        try:
            if run(case_class(test)):
                raise RuntimeError(f'{label}: defect survived')
        finally:
            setattr(module, attr, original)
        # Actual unmutated rerun is a negative control, not just the original verdict.
        if not run(case_class(test)):
            raise RuntimeError(f'{label}: negative control is red')
        print(f'PASS: {label}: mutation detected; restored negative control passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
