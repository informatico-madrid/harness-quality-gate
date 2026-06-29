"""Unit tests for RectorAdapter (PHP Rector).

Tests parse(), invoke(), and edge cases. The adapter itself does not exist yet
— this is the RED phase. Imports will fail until the adapter is created.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_quality_gate.adapters.php.rector_adapter import RectorAdapter
from harness_quality_gate.models import Finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "", stderr: str = "", exitcode: int = 0) -> object:
    from harness_quality_gate.adapters.base import ToolInvocation
    return ToolInvocation(stdout=stdout, stderr=stderr, exitcode=exitcode, duration_seconds=0.0)


# ---------------------------------------------------------------------------
# Rector JSON shapes
# ---------------------------------------------------------------------------

_RECTOR_EMPTY = {}

_RECTOR_IDIOM = {
    "file_diffs": [
        {
            "file": "src/Foo.php",
            "diff": "--- a/src/Foo.php\n+++ b/src/Foo.php\n-old()\n+new()\n",
            "applied_rectors": [
                "Rector\\Php83\\Rector\\FuncCall\\StringableForNullToStringRector"
            ],
        }
    ],
}

_RECTOR_MULTIPLE = {
    "file_diffs": [
        {
            "file": "src/A.php",
            "diff": "diff1",
            "applied_rectors": [
                "Rector\\DeadCode\\Rector\\If_\\RemoveAlwaysTrueConditionRector"
            ],
        },
        {
            "file": "src/B.php",
            "diff": "diff2",
            "applied_rectors": [
                "Rector\\Php8\\Rector\\Class_\\ReadOnlyClassesRector"
            ],
        },
    ],
}

_RECTOR_DEPRECATION = {
    "file_diffs": [
        {
            "file": "src/Old.php",
            "diff": "diff",
            "applied_rectors": [
                "Rector\\Php80\\Rector\\Class_"
                "\\AnnotationToAttributeRector"
            ],
        }
    ],
}

_RECTOR_DEPRECATION_REMOVED = {
    "file_diffs": [
        {
            "file": "src/Removed.php",
            "diff": "diff",
            "applied_rectors": [
                "Rector\\Removed\\Rector\\FuncCall\\RemovedFuncRector"
            ],
        }
    ],
}

_RECTOR_NO_DIFFS = {
    "changed_files": [],
    "file_diffs": [],
}

_RECTOR_NO_FILES_KEY = {"other": 1}

_RECTOR_FILEDIFFS_NOT_LIST = {
    "changed_files": [],
    "file_diffs": "bad",
}

_RECTOR_FILEDIFF_ITEM_NOT_DICT = {
    "changed_files": [],
    "file_diffs": ["not-a-dict"],
}

_RECTOR_APPLIED_RECTORS_NOT_LIST = {
    "changed_files": [],
    "file_diffs": [
        {"file": "x.php", "diff": "d", "applied_rectors": "bad"},
    ],
}

_RECTOR_APPLIED_RECTOR_ITEM_NOT_STRING = {
    "changed_files": [],
    "file_diffs": [
        {"file": "x.php", "diff": "d", "applied_rectors": [123]},
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRectorAdapter:
    def test_name(self) -> None:
        assert RectorAdapter().name == "rector"

    def test_clean_run_zero_findings(self) -> None:
        """Empty stdout → [] findings."""
        assert RectorAdapter().parse("", "", 0) == []

    def test_parse_invalid_json_returns_empty(self) -> None:
        """Non-JSON stdout → [] findings."""
        assert RectorAdapter().parse("not json", "", 1) == []

    def test_parse_no_files_key_returns_empty(self) -> None:
        """JSON without expected keys → [] findings."""
        assert RectorAdapter().parse(json.dumps(_RECTOR_NO_FILES_KEY), "", 0) == []

    def test_parse_idiom_proposal_emits_findings(self) -> None:
        """Rector idiom proposal → Finding with tool='rector', layer='L3A'."""
        findings = RectorAdapter().parse(json.dumps(_RECTOR_IDIOM), "", 5)
        assert len(findings) >= 1
        f = findings[0]
        assert isinstance(f, Finding)
        assert f.tool == "rector"
        assert f.layer == "L3A"
        assert f.severity == "error"
        assert f.node == "src/Foo.php"
        # rule_id should be the FQCN of the applied rector
        assert (
            f.rule_id
            == "Rector\\Php83\\Rector\\FuncCall\\StringableForNullToStringRector"
        )

    def test_parse_multiple_file_diffs(self) -> None:
        """Multiple file diffs → multiple Findings."""
        findings = RectorAdapter().parse(json.dumps(_RECTOR_MULTIPLE), "", 5)
        # Both changed_files and file_diffs contribute
        assert len(findings) >= 2
        nodes = {f.node for f in findings}
        assert "src/A.php" in nodes
        assert "src/B.php" in nodes

    def test_deprecation_finding_marked(self) -> None:
        """Deprecation-class FQCN appears in rule_id."""
        findings = RectorAdapter().parse(json.dumps(_RECTOR_DEPRECATION), "", 5)
        assert len(findings) >= 1
        f = findings[0]
        # The FQCN contains "Php8" which is a deprecation marker
        assert "Php8" in f.rule_id
        assert f.tool == "rector"

    def test_removed_finding_marked(self) -> None:
        """'Removed' in FQCN is also a deprecation marker."""
        findings = RectorAdapter().parse(json.dumps(_RECTOR_DEPRECATION_REMOVED), "", 5)
        assert len(findings) >= 1
        f = findings[0]
        assert "Removed" in f.rule_id

    def test_parse_file_diffs_not_list(self) -> None:
        """'file_diffs' is not a list → skip."""
        findings = RectorAdapter().parse(json.dumps(_RECTOR_FILEDIFFS_NOT_LIST), "", 0)
        assert findings == []

    def test_parse_file_diff_item_not_dict(self) -> None:
        """Individual file_diff item is not a dict → skip."""
        findings = RectorAdapter().parse(json.dumps(_RECTOR_FILEDIFF_ITEM_NOT_DICT), "", 0)
        assert findings == []

    def test_parse_applied_rectors_not_list(self) -> None:
        """'applied_rectors' is not a list → skip that diff."""
        findings = RectorAdapter().parse(json.dumps(_RECTOR_APPLIED_RECTORS_NOT_LIST), "", 0)
        assert findings == []

    def test_parse_applied_rector_item_not_string(self) -> None:
        """Individual applied_rector item is not a string → skip."""
        findings = RectorAdapter().parse(json.dumps(_RECTOR_APPLIED_RECTOR_ITEM_NOT_STRING), "", 0)
        assert findings == []

    def test_binary_missing_raises_runtime_error(self, tmp_path: Path) -> None:
        """When rector binary is not found, invoke() raises RuntimeError."""
        adapter = RectorAdapter()
        with patch("harness_quality_gate.adapters.php.rector_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="rector not found"):
                adapter.invoke(tmp_path, [])

    def test_invoke_with_mocked_binary(self, tmp_path: Path) -> None:
        """When rector binary exists, invoke() calls _run with correct args."""
        adapter = RectorAdapter()
        with patch("harness_quality_gate.adapters.php.rector_adapter.shutil.which", return_value="/usr/bin/rector"):
            with patch.object(RectorAdapter, "_run", return_value=_ok("{}")) as mock_run:
                adapter.invoke(tmp_path, [
                    "process", "--dry-run", "--no-progress-bar", "--output-format=json", "src/",
                ])
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/rector"
        assert "process" in cmd
        assert "--dry-run" in cmd
        assert "--no-progress-bar" in cmd
        assert "--output-format=json" in cmd

    def test_parse_return_type_assertions(self) -> None:
        """parse() always returns list[Finding]."""
        # Empty
        r = RectorAdapter().parse("", "", 0)
        assert isinstance(r, list)
        assert len(r) == 0

        # Invalid JSON
        r = RectorAdapter().parse("garbage", "", 1)
        assert isinstance(r, list)
        assert len(r) == 0

        # Valid
        r = RectorAdapter().parse(json.dumps(_RECTOR_IDIOM), "", 5)
        assert isinstance(r, list)
        assert len(r) >= 1
        assert isinstance(r[0], Finding)

    def test_binary_fallback_to_vendor_bin(self, tmp_path: Path) -> None:
        """When rector is not on PATH, _rector_binary falls back to vendor/bin/rector."""
        adapter = RectorAdapter()
        vendor_bin = tmp_path / "vendor" / "bin" / "rector"
        vendor_bin.parent.mkdir(parents=True, exist_ok=True)
        vendor_bin.write_text("#!/bin/sh\n")
        vendor_bin.chmod(0o755)
        with patch(
            "harness_quality_gate.adapters.php.rector_adapter.shutil.which",
            return_value=None,
        ) as mock_which:
            result = adapter._rector_binary(tmp_path)
        assert result == [str(vendor_bin)]
        mock_which.assert_called_with("rector")

    def test_binary_vendor_path_not_found(self, tmp_path: Path) -> None:
        """When vendor/bin/rector does not exist, _rector_binary returns None."""
        adapter = RectorAdapter()
        with patch(
            "harness_quality_gate.adapters.php.rector_adapter.shutil.which",
            return_value=None,
        ):
            result = adapter._rector_binary(tmp_path)
        assert result is None

    def test_invoke_passes_correct_args_to_run(self, tmp_path: Path) -> None:
        """invoke() forwards correct command, cwd, env, and timeout to _run."""
        adapter = RectorAdapter()
        with patch(
            "harness_quality_gate.adapters.php.rector_adapter.shutil.which",
            return_value="/usr/bin/rector",
        ):
            with patch.object(
                RectorAdapter,
                "_run",
                return_value=_ok("{}"),
            ) as mock_run:
                adapter.invoke(tmp_path, ["process", "--dry-run", "src/"], env={"FOO": "bar"}, timeout=123.0)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == str(tmp_path)
        assert call_kwargs["env"] == {"FOO": "bar"}
        assert call_kwargs["timeout"] == 123.0
        cmd = mock_run.call_args[0][0]
        assert "process" in cmd
        assert "--dry-run" in cmd

    def test_invoke_default_timeout(self, tmp_path: Path) -> None:
        """invoke() uses 300.0s default timeout when not specified."""
        adapter = RectorAdapter()
        with patch(
            "harness_quality_gate.adapters.php.rector_adapter.shutil.which",
            return_value="/usr/bin/rector",
        ):
            with patch.object(
                RectorAdapter,
                "_run",
                return_value=_ok("{}"),
            ) as mock_run:
                adapter.invoke(tmp_path, [])
        assert mock_run.call_args[1]["timeout"] == 300.0

    def test_invoke_error_message_exact(self, tmp_path: Path) -> None:
        """invoke() raises RuntimeError with the exact expected message."""
        adapter = RectorAdapter()
        with patch(
            "harness_quality_gate.adapters.php.rector_adapter.shutil.which",
            return_value=None,
        ):
            with pytest.raises(RuntimeError) as exc_info:
                adapter.invoke(tmp_path, [])
        assert str(exc_info.value) == "rector not found on PATH or in vendor/bin"

    def test_parse_multiple_sections_one_bad_skips_all(self) -> None:
        """Multiple sections with one bad entry → all good sections still parsed."""
        payload = {
            "file_diffs": [
                {"file": "src/A.php", "diff": "d1", "applied_rectors": ["R1"]},
            ],
            "changed_files": "not-a-list",
            "other_section": [
                {"file": "src/B.php", "diff": "d2", "applied_rectors": ["R2"]},
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert len(findings) == 1
        assert findings[0].node == "src/A.php"

    def test_parse_bad_section_first_skips_rest(self) -> None:
        """Bad section first → good sections after are still parsed (kills continue→break)."""
        payload = {
            "changed_files": "not-a-list",
            "file_diffs": [
                {"file": "src/A.php", "diff": "d1", "applied_rectors": ["R1"]},
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert len(findings) == 1
        assert findings[0].node == "src/A.php"

    def test_parse_mixed_valid_invalid_entries(self) -> None:
        """Mixed valid/invalid entries → only valid ones emitted."""
        payload = {
            "file_diffs": [
                {"file": "src/A.php", "diff": "d1", "applied_rectors": ["R1"]},
                "not-a-dict",
                {"file": "src/B.php", "diff": "d2", "applied_rectors": ["R2"]},
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert len(findings) == 2
        nodes = {f.node for f in findings}
        assert nodes == {"src/A.php", "src/B.php"}

    def test_parse_mixed_valid_invalid_applied_rectors(self) -> None:
        """Mixed valid/invalid applied_rectors → only string ones emitted."""
        payload = {
            "file_diffs": [
                {
                    "file": "src/A.php",
                    "diff": "d",
                    "applied_rectors": ["R1", 123, "R2"],
                },
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert len(findings) == 2
        rule_ids = {f.rule_id for f in findings}
        assert rule_ids == {"R1", "R2"}

    def test_parse_entry_with_non_list_applied_rectors(self) -> None:
        """Entry with non-list applied_rectors → skipped (kills continue→break)."""
        payload = {
            "file_diffs": [
                {"file": "src/A.php", "diff": "d", "applied_rectors": "not-a-list"},
                {"file": "src/B.php", "diff": "d2", "applied_rectors": ["R1"]},
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert len(findings) == 1
        assert findings[0].node == "src/B.php"

    def test_parse_missing_diff_defaults_empty(self) -> None:
        """Entry missing 'diff' → default '' (not None)."""
        payload = {
            "file_diffs": [
                {"file": "src/A.php", "applied_rectors": ["R1"]},
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert len(findings) == 1
        assert findings[0].fix_hint is None

    def test_parse_with_diff_sets_fix_hint(self) -> None:
        """Entry with non-empty diff → fix_hint populated."""
        payload = {
            "file_diffs": [
                {"file": "src/A.php", "diff": "some diff text", "applied_rectors": ["R1"]},
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert len(findings) == 1
        assert findings[0].fix_hint == "some diff text"

    def test_parse_message_content(self) -> None:
        """Finding message contains rector FQCN and file name."""
        payload = {
            "file_diffs": [
                {"file": "src/A.php", "diff": "d", "applied_rectors": ["Rector\\R1"]},
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert len(findings) == 1
        assert findings[0].message == "Rector\\R1 on src/A.php"

    def test_parse_missing_file_skipped(self) -> None:
        """Entry without 'file' → skipped."""
        payload = {
            "file_diffs": [
                {"diff": "d", "applied_rectors": ["R1"]},
            ],
        }
        findings = RectorAdapter().parse(json.dumps(payload), "", 5)
        assert findings == []
