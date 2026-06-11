"""Test that __main__.py entry point executes correctly.

This test exercises the entry point to reach 100% coverage on __main__.py
without using a no-cover pragma. The no-mutate pragma on line 9
is for mutmut only — it tells mutmut not to mutate sys.exit() because
mutating its return value doesn't change behavior.
"""
import runpy
import sys
from unittest import mock

import pytest


def test_main_entry_point_executes():
    """Run `python -m harness_quality_gate` and verify entry point executes.

    Covers lines 3 (import sys), 5 (from .cli import main), and 9 (sys.exit call).
    """
    # Mock main() to return 0 (success) so sys.exit completes without error
    with mock.patch("harness_quality_gate.cli.main", return_value=0) as mocked_main:
        # Run __main__ as if via `python -m harness_quality_gate`
        # The module will:
        #   1. import sys (line 3)
        #   2. from .cli import main (line 5)
        #   3. call sys.exit(main(sys.argv[1:])) (line 9)
        with mock.patch.object(sys, "argv", ["harness_quality_gate"]):
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_module(
                    "harness_quality_gate.__main__",
                    run_name="__main__",
                )
            # main() returned 0, so SystemExit code is 0
            assert exc_info.value.code == 0
            # Verify main was called with sys.argv[1:] (i.e., empty list)
            mocked_main.assert_called_once_with([])
