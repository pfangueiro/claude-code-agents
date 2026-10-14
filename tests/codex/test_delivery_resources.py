"""Register the portable delivery resource suite with tests/codex discovery.

The CI job discovers only tests/codex. This bridge imports tests/delivery/test_resources.py
by path and loads every TestCase it defines, so resource regressions added there later run
without editing a case list here.
"""
import importlib.util
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1] / 'delivery/test_resources.py'


def load_tests(loader, tests, pattern):
    spec = importlib.util.spec_from_file_location('delivery_test_resources', SUITE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = loader.loadTestsFromModule(module)
    if not suite.countTestCases():
        raise RuntimeError(f'no delivery resource tests loaded from {SUITE}')
    tests.addTests(suite)
    return tests
