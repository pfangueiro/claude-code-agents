#!/usr/bin/env python3
"""Prove selected guards with in-memory defects; never alter repository source."""
import io
from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_agent_eval
import test_framework as acceptance
import test_lint


def mutant(original, before, after):
    path = Path(original.__file__)
    source = path.read_text()
    if source.count(before) != 1:
        raise RuntimeError(f'mutation anchor is not unique in {path.name}')
    module = types.ModuleType(original.__name__)
    module.__file__ = str(path)
    # dataclasses resolve string annotations through sys.modules[cls.__module__], so the
    # mutant is registered while it executes and the original registration is restored.
    missing = object()
    previous = sys.modules.get(original.__name__, missing)
    sys.modules[original.__name__] = module
    try:
        exec(compile(source.replace(before, after, 1), str(path), 'exec'), module.__dict__)
    finally:
        if previous is missing:
            sys.modules.pop(original.__name__, None)
        else:
            sys.modules[original.__name__] = previous
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
        # Agent evaluator guards: the selected tests call the module-level agent_eval alias.
        # Replacements keep the line count, because the harness builds its probe script with
        # inspect.getsource, which reads the on-disk file by line number.
        ('agent-eval failed adapter exit', test_agent_eval, 'agent_eval', test_agent_eval.AdapterLifecycle,
         'test_nonzero_exit_with_success_json_is_unavailable',
         "        reasons.append('adapter-nonzero-exit')", '        pass'),
        ('agent-eval protected workspace file', test_agent_eval, 'agent_eval', test_agent_eval.WorkspaceScope,
         'test_direct_protected_file_mutation_fails',
         "    ('protected_changed_by_provider', 'scope-protected-file-changed'),",
         "    ('workspace_extra_entries', 'scope-protected-file-changed'),"),
        ('agent-eval added workspace entry', test_agent_eval, 'agent_eval', test_agent_eval.WorkspaceScope,
         'test_extra_workspace_entries_fail',
         '    extra = [rel for rel in added if rel not in allowed]', '    extra = []'),
        ('agent-eval malformed findings not clean', test_agent_eval, 'agent_eval', test_agent_eval.ReviewGrading,
         'test_malformed_findings_on_clean_review_are_not_clean',
         "        raise Invalid('response-findings-invalid')", '        return []'),
        ('agent-eval fabricated review witness', test_agent_eval, 'agent_eval', test_agent_eval.ReviewGrading,
         'test_fabricated_witness_is_not_a_true_positive',
         "        'actual_matches_execution': actual is not None and finding['actual'] == actual,",
         "        'actual_matches_execution': True,"),
        ('agent-eval corpus traversal', test_agent_eval, 'agent_eval', test_agent_eval.EvaluationInputs,
         'test_unsafe_corpus_paths_rejected_before_use',
         "    if any(part in ('', '.', '..') or part.lower() == '.git' for part in pure.parts):", '    if False:'),
        ('agent-eval scope violation beside unavailability', test_agent_eval, 'agent_eval',
         test_agent_eval.WorkspaceScope, 'test_scope_violation_stays_fail_when_provider_is_unavailable',
         "        finish(record, 'FAIL' if failures else 'UNAVAILABLE', failures or list(unavailable))",
         "        finish(record, 'UNAVAILABLE', list(unavailable))"),
        ('agent-eval known failure precedence', test_agent_eval, 'agent_eval', test_agent_eval.Aggregation,
         'test_known_candidate_failure_stays_visible_beside_unavailable_trials',
         '    if candidate_failed or regressions:', '    if (candidate_failed or regressions) and not unavailable:'),
        ('agent-eval grader launch refusal', test_agent_eval, 'agent_eval', test_agent_eval.CodeGrading,
         'test_grader_launch_refusal_is_unavailable_and_executed_defects_still_fail',
         '        return make_verdict(False, [], unavailable=err.code)', '        return make_verdict(False, [err.code])'),
        # Pre-launch drift guard bypassed: the end-of-run drift check still reports the
        # change, so only the launch-state assertions catch it.
        ('agent-eval declared adapter input', test_agent_eval, 'agent_eval', test_agent_eval.AdapterInputs,
         'test_payload_changed_after_baseline_blocks_the_candidate_launch',
         '    drifted = sorted({drift_reason(subject, kind) for subject, kind in drift if kind})',
         '    drifted = []'),
        ('agent-eval adapter input alias', test_agent_eval, 'agent_eval', test_agent_eval.AdapterInputs,
         'test_input_directory_alias_retargeted_after_baseline_blocks_the_candidate_launch',
         "    if resolved_location(lexical) != item['path']:",
         '    if False:'),
        ('agent-eval incomplete grader supervision', test_agent_eval, 'agent_eval', test_agent_eval.CodeGrading,
         'test_incomplete_grader_supervision_is_unavailable',
         "            or child['descendantsOutlivedDeadline'] or child['signalsSent']):",
         '            or False):'),
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
