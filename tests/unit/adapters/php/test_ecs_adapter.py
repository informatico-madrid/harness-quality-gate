"""Unit tests for EcsAdapter (PHP Easy Coding Standard).

Tests parse(), invoke(), and edge cases. The adapter itself does not exist yet
— this is the RED phase. Imports will fail until the adapter is created.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_quality_gate.adapters.php.ecs_adapter import EcsAdapter
from harness_quality_gate.models import Finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "", stderr: str = "", exitcode: int = 0) -> object:
    from harness_quality_gate.adapters.base import ToolInvocation
    return ToolInvocation(stdout=stdout, stderr=stderr, exitcode=exitcode, duration_seconds=0.0)


# ---------------------------------------------------------------------------
# ECS JSON shapes
# ---------------------------------------------------------------------------

_ECS_EMPTY = {}

_ECS_VIOLATION = {
    "files": {
        "src/Foo.php": {
            "errors": [
                {
                    "line": 42,
                    "message": "Expected indentation of 4 spaces, found 2.",
                    "source_class": "PSR12.Indentation",
                }
            ]
        }
    }
}

_ECS_MULTIPLE = {
    "files": {
        "src/A.php": {
            "errors": [
                {"line": 1, "message": "err1", "source_class": "SniffA"},
                {"line": 5, "message": "err2", "source_class": "SniffB"},
            ]
        },
        "src/B.php": {
            "errors": [
                {"line": 10, "message": "err3", "source_class": "SniffC"},
            ]
        },
    }
}

_ECS_NO_ERRORS = {
    "files": {
        "src/Clean.php": {
            "errors": []
        }
    }
}

_ECS_NO_FILES_KEY = {"other": 1}

_ECS_FILES_NOT_DICT = {"files": "bad"}

_ECS_ERROR_NOT_DICT = {
    "files": {
        "src/X.php": {
            "errors": "not-a-list"
        }
    }
}

_ECS_ERROR_ITEM_NOT_DICT = {
    "files": {
        "src/X.php": {
            "errors": ["not-a-dict"]
        }
    }
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEcsAdapter:
    def test_name(self) -> None:
        assert EcsAdapter().name == "ecs"

    def test_clean_run_zero_findings(self) -> None:
        """Empty stdout → [] findings."""
        assert EcsAdapter().parse("", "", 0) == []

    def test_parse_invalid_json_returns_empty(self) -> None:
        """Non-JSON stdout → [] findings."""
        assert EcsAdapter().parse("not json", "", 1) == []

    def test_parse_no_files_key_returns_empty(self) -> None:
        """JSON without 'files' key → [] findings."""
        assert EcsAdapter().parse(json.dumps(_ECS_NO_FILES_KEY), "", 0) == []

    def test_parse_files_not_dict_returns_empty(self) -> None:
        """'files' is not a dict → [] findings."""
        assert EcsAdapter().parse(json.dumps(_ECS_FILES_NOT_DICT), "", 0) == []

    def test_parse_violation_emits_findings(self) -> None:
        """Single violation → one Finding with tool='ecs', layer='L3A'."""
        findings = EcsAdapter().parse(json.dumps(_ECS_VIOLATION), "", 8)
        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, Finding)
        assert f.tool == "ecs"
        assert f.layer == "L3A"
        assert f.severity == "error"
        assert f.rule_id == "PSR12.Indentation"
        assert f.node == "src/Foo.php"
        assert "42" in f.message
        assert "Expected indentation" in f.message

    def test_parse_multiple_violations(self) -> None:
        """Multiple files/violations → multiple Findings."""
        findings = EcsAdapter().parse(json.dumps(_ECS_MULTIPLE), "", 8)
        assert len(findings) == 3
        nodes = {f.node for f in findings}
        assert nodes == {"src/A.php", "src/B.php"}
        for f in findings:
            assert f.tool == "ecs"
            assert f.layer == "L3A"
            assert f.severity == "error"

    def test_parse_no_errors_in_file(self) -> None:
        """File with empty errors list → no findings from that file."""
        findings = EcsAdapter().parse(json.dumps(_ECS_NO_ERRORS), "", 0)
        assert findings == []

    def test_parse_error_list_not_list(self) -> None:
        """'errors' is not a list → skip that file."""
        findings = EcsAdapter().parse(json.dumps(_ECS_ERROR_NOT_DICT), "", 0)
        assert findings == []

    def test_parse_error_item_not_dict(self) -> None:
        """Individual error item is not a dict → skip it."""
        findings = EcsAdapter().parse(json.dumps(_ECS_ERROR_ITEM_NOT_DICT), "", 0)
        assert findings == []

    def test_binary_missing_raises_runtime_error(self, tmp_path: Path) -> None:
        """When ecs binary is not found, invoke() raises RuntimeError."""
        adapter = EcsAdapter()
        with patch("harness_quality_gate.adapters.php.ecs_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="ecs not found"):
                adapter.invoke(tmp_path, [])

    def test_invoke_with_mocked_binary(self, tmp_path: Path) -> None:
        """When ecs binary exists, invoke() calls _run with correct args."""
        adapter = EcsAdapter()
        with patch("harness_quality_gate.adapters.php.ecs_adapter.shutil.which", return_value="/usr/bin/ecs"):
            with patch.object(EcsAdapter, "_run", return_value=_ok("{}")) as mock_run:
                adapter.invoke(tmp_path, ["check", "--no-progress-bar", "--output-format=json", "src/"])
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/ecs"
        assert "check" in cmd
        assert "--no-progress-bar" in cmd
        assert "--output-format=json" in cmd
        assert cmd[-1] == str(tmp_path)

    def test_parse_return_type_assertions(self) -> None:
        """parse() always returns list[Finding]."""
        from harness_quality_gate.models import Finding

        # Empty
        r = EcsAdapter().parse("", "", 0)
        assert isinstance(r, list)
        assert len(r) == 0

        # Invalid JSON
        r = EcsAdapter().parse("garbage", "", 1)
        assert isinstance(r, list)
        assert len(r) == 0

        # Valid
        r = EcsAdapter().parse(json.dumps(_ECS_VIOLATION), "", 8)
        assert isinstance(r, list)
        assert len(r) == 1
        assert isinstance(r[0], Finding)

    def test_binary_repo_bin_before_vendor_bin(self, tmp_path: Path) -> None:
        """When bin/ecs exists, it wins over vendor/bin/ecs (config.bin-dir: bin)."""
        adapter = EcsAdapter()
        bin_dir = tmp_path / "bin" / "ecs"
        bin_dir.parent.mkdir(parents=True, exist_ok=True)
        bin_dir.write_text("#!/bin/sh\n")
        bin_dir.chmod(0o755)
        # vendor/bin/ecs also exists but bin/ wins
        vendor_bin = tmp_path / "vendor" / "bin" / "ecs"
        vendor_bin.parent.mkdir(parents=True, exist_ok=True)
        vendor_bin.write_text("#!/bin/sh\n")
        vendor_bin.chmod(0o755)
        with patch(
            "harness_quality_gate.adapters.php.ecs_adapter.shutil.which",
            return_value=None,
        ):
            result = adapter._ecs_binary(tmp_path)
        assert result == [str(bin_dir)], f"Expected bin/ecs, got: {result}"

    def test_binary_fallback_to_vendor_bin(self, tmp_path: Path) -> None:
        """When bin/ecs does not exist, _ecs_binary falls back to vendor/bin/ecs."""
        adapter = EcsAdapter()
        vendor_bin = tmp_path / "vendor" / "bin" / "ecs"
        vendor_bin.parent.mkdir(parents=True, exist_ok=True)
        vendor_bin.write_text("#!/bin/sh\n")
        vendor_bin.chmod(0o755)
        with patch(
            "harness_quality_gate.adapters.php.ecs_adapter.shutil.which",
            return_value=None,
        ):
            result = adapter._ecs_binary(tmp_path)
        assert result == [str(vendor_bin)]

    def test_version_binary_not_found_raises(self, tmp_path: Path) -> None:
        """version() raises RuntimeError when ecs binary is not on PATH or in vendor/bin."""
        adapter = EcsAdapter()
        with patch(
            "harness_quality_gate.adapters.php.ecs_adapter.shutil.which",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="ecs not found"):
                adapter.version(tmp_path)

    def test_version_with_system_binary(self, tmp_path: Path) -> None:
        """version() returns output from --version when binary exists."""
        adapter = EcsAdapter()
        with (
            patch("harness_quality_gate.adapters.php.ecs_adapter.shutil.which", return_value="/usr/bin/ecs"),
            patch("harness_quality_gate.adapters.php.ecs_adapter.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type("Result", (), {
                "returncode": 0, "stdout": "ECS 12.5.0", "stderr": ""
            })()
            result = adapter.version(tmp_path)
        assert result == "ECS 12.5.0"
        mock_run.assert_called_once()

    def test_version_with_nonzero_exit(self, tmp_path: Path) -> None:
        """version() raises RuntimeError when --version fails."""
        adapter = EcsAdapter()
        with (
            patch("harness_quality_gate.adapters.php.ecs_adapter.shutil.which", return_value="/usr/bin/ecs"),
            patch("harness_quality_gate.adapters.php.ecs_adapter.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type("Result", (), {
                "returncode": 1, "stdout": "", "stderr": "error"
            })()
            with pytest.raises(RuntimeError, match="ecs --version failed"):
                adapter.version(tmp_path)

    def test_binary_vendor_path_not_found(self, tmp_path: Path) -> None:
        """When vendor/bin/ecs does not exist, _ecs_binary returns None."""
        adapter = EcsAdapter()
        with patch(
            "harness_quality_gate.adapters.php.ecs_adapter.shutil.which",
            return_value=None,
        ):
            result = adapter._ecs_binary(tmp_path)
        assert result is None

    def test_invoke_passes_correct_args_to_run(self, tmp_path: Path) -> None:
        """invoke() forwards correct command, cwd, env, and timeout to _run."""
        adapter = EcsAdapter()
        with patch(
            "harness_quality_gate.adapters.php.ecs_adapter.shutil.which",
            return_value="/usr/bin/ecs",
        ):
            with patch.object(
                EcsAdapter,
                "_run",
                return_value=_ok("{}"),
            ) as mock_run:
                adapter.invoke(tmp_path, ["check", "src/"], env={"FOO": "bar"}, timeout=123.0)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == tmp_path
        assert call_kwargs["env"] == {"FOO": "bar"}
        assert call_kwargs["timeout"] == 123.0
        cmd = mock_run.call_args[0][0]
        assert "check" in cmd
        assert str(tmp_path) in cmd

    def test_invoke_default_timeout(self, tmp_path: Path) -> None:
        """invoke() uses 300.0s default timeout when not specified."""
        adapter = EcsAdapter()
        with patch(
            "harness_quality_gate.adapters.php.ecs_adapter.shutil.which",
            return_value="/usr/bin/ecs",
        ):
            with patch.object(
                EcsAdapter,
                "_run",
                return_value=_ok("{}"),
            ) as mock_run:
                adapter.invoke(tmp_path, [])
        assert mock_run.call_args[1]["timeout"] == 300.0

    def test_invoke_error_message_exact(self, tmp_path: Path) -> None:
        """invoke() raises RuntimeError with the exact expected message."""
        adapter = EcsAdapter()
        with patch(
            "harness_quality_gate.adapters.php.ecs_adapter.shutil.which",
            return_value=None,
        ):
            with pytest.raises(RuntimeError) as exc_info:
                adapter.invoke(tmp_path, [])
        assert str(exc_info.value) == "ecs not found on PATH or in vendor/bin"

    def test_parse_multiple_errors_same_file_kills_all(self) -> None:
        """Multiple errors in one file → all findings emitted (kills continue→break)."""
        payload = {
            "files": {
                "src/Multi.php": {
                    "errors": [
                        {"line": 1, "message": "err1", "source_class": "S1"},
                        {"line": 2, "message": "err2", "source_class": "S2"},
                        {"line": 3, "message": "err3", "source_class": "S3"},
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(payload), "", 8)
        assert len(findings) == 3

    def test_parse_multiple_files_non_dict_file_data_continues_processing(self) -> None:
        """Multiple files with one non-dict file_data → continues to next files."""
        payload = {
            "files": {
                "src/Good1.php": {
                    "errors": [
                        {"line": 1, "message": "ok", "source_class": "S"},
                    ]
                },
                "src/Bad.php": "not-a-dict file_data",
                "src/Good2.php": {
                    "errors": [
                        {"line": 5, "message": "ok2", "source_class": "S2"},
                    ]
                },
            }
        }
        findings = EcsAdapter().parse(json.dumps(payload), "", 8)
        assert len(findings) == 2
        nodes = {f.node for f in findings}
        assert nodes == {"src/Good1.php", "src/Good2.php"}

    def test_parse_multiple_files_one_bad_skips_processing(self) -> None:
        """Multiple files with one bad entry → all good files still parsed."""
        payload = {
            "files": {
                "src/Good.php": {
                    "errors": [
                        {"line": 1, "message": "ok", "source_class": "S"},
                    ]
                },
                "src/Bad.php": {
                    "errors": "not-a-list"
                },
                "src/AlsoGood.php": {
                    "errors": [
                        {"line": 5, "message": "ok2", "source_class": "S2"},
                    ]
                },
            }
        }
        findings = EcsAdapter().parse(json.dumps(payload), "", 8)
        assert len(findings) == 2
        nodes = {f.node for f in findings}
        assert nodes == {"src/Good.php", "src/AlsoGood.php"}

    def test_parse_mixed_valid_invalid_errors_in_file(self) -> None:
        """Mixed valid/invalid errors in one file → only valid ones emitted."""
        payload = {
            "files": {
                "src/Mixed.php": {
                    "errors": [
                        {"line": 1, "message": "ok1", "source_class": "S1"},
                        "not-a-dict",
                        {"line": 3, "message": "ok2", "source_class": "S2"},
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(payload), "", 8)
        assert len(findings) == 2
        messages = {f.message for f in findings}
        assert messages == {"line 1: ok1", "line 3: ok2"}

    def test_parse_error_without_message_uses_empty_string(self) -> None:
        """Error dict missing 'message' → default '' (not None)."""
        payload = {
            "files": {
                "src/X.php": {
                    "errors": [
                        {"line": 1},
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(payload), "", 8)
        assert len(findings) == 1
        assert findings[0].message == "line 1: "

    def test_parse_error_without_source_class_defaults_empty(self) -> None:
        """Error dict missing 'source_class' → default '' (not None)."""
        payload = {
            "files": {
                "src/X.php": {
                    "errors": [
                        {"line": 1, "message": "boom"},
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(payload), "", 8)
        assert len(findings) == 1
        assert findings[0].rule_id is None

    def test_parse_fix_hint_always_none(self) -> None:
        """ECS parse never sets fix_hint on errors — always None."""
        findings = EcsAdapter().parse(json.dumps(_ECS_VIOLATION), "", 8)
        assert findings[0].fix_hint is None

    def test_parse_diffs_emits_findings(self) -> None:
        """ECS 12.x: 'diffs' with 'applied_checkers' → findings (autofixed violations)."""
        ecs_with_diffs = {
            "files": {
                "src/Autofixed.php": {
                    "diffs": [
                        {
                            "diff": "- echo\"bad\\n+ echo \"bad",
                            "applied_checkers": ["PSR12.Operators.SpacedOperators"],
                        }
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(ecs_with_diffs), "", 1)
        assert len(findings) == 1
        f = findings[0]
        assert f.tool == "ecs"
        assert f.layer == "L3A"
        assert f.severity == "error"
        assert f.rule_id == "PSR12.Operators.SpacedOperators"
        assert f.node == "src/Autofixed.php"
        assert "PSR12.Operators.SpacedOperators" in f.message
        assert f.fix_hint == "- echo\"bad\\n+ echo \"bad"

    def test_parse_diffs_multiple_checkers(self) -> None:
        """ECS 12.x: 'diffs' with multiple 'applied_checkers' → multiple findings."""
        ecs_with_diffs = {
            "files": {
                "src/Autofixed.php": {
                    "diffs": [
                        {
                            "diff": "- echo\"bad\\n+ echo \"bad",
                            "applied_checkers": [
                                "PSR12.Operators.SpacedOperators",
                                "PSR12.Files.FileHeader",
                            ],
                        }
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(ecs_with_diffs), "", 1)
        assert len(findings) == 2
        rules = {f.rule_id for f in findings}
        assert rules == {"PSR12.Operators.SpacedOperators", "PSR12.Files.FileHeader"}

    def test_parse_diffs_not_list(self) -> None:
        """ECS 12.x: 'diffs' is not a list → skip diffs (parse errors if present)."""
        ecs_with_diffs = {
            "files": {
                "src/File.php": {
                    "diffs": "not-a-list",
                    "errors": [
                        {"line": 1, "message": "err", "source_class": "S"},
                    ],
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(ecs_with_diffs), "", 8)
        assert len(findings) == 1  # Only the error, diffs skipped
        assert findings[0].rule_id == "S"

    def test_parse_diff_item_not_dict(self) -> None:
        """ECS 12.x: 'diffs' item is not a dict → skip it."""
        ecs_with_diffs = {
            "files": {
                "src/File.php": {
                    "diffs": ["not-a-dict"],
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(ecs_with_diffs), "", 1)
        assert findings == []

    def test_parse_applied_checkers_not_list(self) -> None:
        """ECS 12.x: 'applied_checkers' is not a list → skip that diff."""
        ecs_with_diffs = {
            "files": {
                "src/File.php": {
                    "diffs": [
                        {"applied_checkers": "not-a-list"},
                        {"applied_checkers": ["PSR12.Indentation"]},
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(ecs_with_diffs), "", 1)
        assert len(findings) == 1
        assert findings[0].rule_id == "PSR12.Indentation"

    def test_parse_applied_checkers_item_not_string(self) -> None:
        """ECS 12.x: 'applied_checkers' item is not a string → skip it (kills continue→break)."""
        ecs_with_diffs = {
            "files": {
                "src/File.php": {
                    "diffs": [
                        {
                            "applied_checkers": [123, "PSR12.Indentation"],
                        }
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(ecs_with_diffs), "", 1)
        assert len(findings) == 1
        assert findings[0].rule_id == "PSR12.Indentation"

    def test_parse_errors_and_diffs_combined(self) -> None:
        """ECS 12.x: errors (unfixable) + diffs (autofixed) → both become findings."""
        ecs_combined = {
            "files": {
                "src/File.php": {
                    "errors": [
                        {"line": 5, "message": "unfixable", "source_class": "S1"},
                    ],
                    "diffs": [
                        {
                            "diff": "- bad\\n+ good",
                            "applied_checkers": ["PSR12.Indentation"],
                        }
                    ],
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(ecs_combined), "", 8)
        assert len(findings) == 2
        rules = {f.rule_id for f in findings}
        assert rules == {"S1", "PSR12.Indentation"}

    def test_parse_diffs_non_dict_skips_first_then_processes_second(self) -> None:
        """ECS 12.x: diffs list with non-dict first → skip it, process next valid diff (kills continue→break)."""
        ecs_with_diffs = {
            "files": {
                "src/File.php": {
                    "diffs": [
                        "not-a-dict",
                        {"applied_checkers": ["PSR12.Indentation"]},
                    ]
                }
            }
        }
        findings = EcsAdapter().parse(json.dumps(ecs_with_diffs), "", 1)
        assert len(findings) == 1
        assert findings[0].rule_id == "PSR12.Indentation"

    def test_version_with_system_binary(self, tmp_path: Path) -> None:
        """version() returns output from --version."""
        adapter = EcsAdapter()
        with (
            patch("harness_quality_gate.adapters.php.ecs_adapter.shutil.which", return_value="/usr/bin/ecs"),
            patch("harness_quality_gate.adapters.php.ecs_adapter.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type("Result", (), {
                "returncode": 0, "stdout": "ECS 12.5.0", "stderr": ""
            })()
            result = adapter.version(tmp_path)
        assert result == "ECS 12.5.0"
        mock_run.assert_called_once()

    def test_version_with_nonzero_exit(self, tmp_path: Path) -> None:
        """version() raises RuntimeError on non-zero exit code."""
        adapter = EcsAdapter()
        with (
            patch("harness_quality_gate.adapters.php.ecs_adapter.shutil.which", return_value="/usr/bin/ecs"),
            patch("harness_quality_gate.adapters.php.ecs_adapter.subprocess.run") as mock_run,
        ):
            mock_run.return_value = type("Result", (), {
                "returncode": 1, "stdout": "", "stderr": "not found"
            })()
            with pytest.raises(RuntimeError, match="ecs --version failed"):
                adapter.version(tmp_path)


class TestEcsBinaryLiteral:
    def test_ecs_binary_which_exact_literal(self, tmp_path: Path) -> None:
        """Verify shutil.which is called with exactly 'ecs' (kills XX-wrap and case mutations)."""

        def check_which(name: str):
            assert name == "ecs", f"Expected exactly 'ecs' but got '{name}'"
            return "/usr/bin/ecs"

        adapter = EcsAdapter()
        with patch(
            "harness_quality_gate.adapters.php.ecs_adapter.shutil.which",
            side_effect=check_which,
        ):
            result = adapter._ecs_binary(tmp_path)
        assert result == ["/usr/bin/ecs"]
