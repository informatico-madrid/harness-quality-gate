"""Comprehensive unit tests for DeptryAdapter.parse().

Targets every branch, early return, condition, and mutation in the parser.
Design: mutation testing / deptry_adapter coverage
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter
from harness_quality_gate.models import Finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMPTY_STDOUT = ""
VALID_JSON = json.dumps({"errors": {}})
INVALID_JSON = "not json at all"
NON_DICT_JSON = json.dumps([1, 2, 3])


@pytest.fixture
def adapter():
    return DeptryAdapter()


# ---------------------------------------------------------------------------
# parse(): early returns (empty stdout, invalid JSON, non-dict data)
# ---------------------------------------------------------------------------

class TestParseEarlyReturns:
    """Test that parse returns [] for invalid inputs."""

    def test_empty_stdout(self, adapter):
        """Empty stdout → empty findings."""
        result = adapter.parse("")
        assert result == []

    def test_whitespace_only_stdout(self, adapter):
        """Whitespace-only stdout → empty findings."""
        result = adapter.parse("   \n\t  ")
        assert result == []

    def test_none_like_non_string_returns_empty(self, adapter):
        """Empty string (the only valid empty) → []."""
        result = adapter.parse(" ")
        assert result == []

    def test_invalid_json(self, adapter):
        """Invalid JSON → empty findings."""
        result = adapter.parse(INVALID_JSON)
        assert result == []

    def test_non_dict_json(self, adapter):
        """JSON array instead of object → empty findings."""
        result = adapter.parse(NON_DICT_JSON)
        assert result == []

    def test_null_json(self, adapter):
        """JSON null instead of object → empty findings."""
        result = adapter.parse(json.dumps(None))
        assert result == []


# ---------------------------------------------------------------------------
# parse(): errors key handling
# ---------------------------------------------------------------------------

class TestParseErrorsKey:
    """Test handling of the 'errors' key variations."""

    def test_missing_errors_key(self, adapter):
        """No 'errors' key → no findings."""
        result = adapter.parse(json.dumps({"other": "data"}))
        assert result == []

    def test_errors_is_empty_dict(self, adapter):
        """Empty errors dict → no findings."""
        result = adapter.parse(json.dumps({"errors": {}}))
        assert result == []

    def test_errors_is_not_dict_list(self, adapter):
        """errors is a list → treated as non-dict, no findings."""
        result = adapter.parse(json.dumps({"errors": ["something"]}))
        assert result == []

    def test_errors_is_not_dict_string(self, adapter):
        """errors is a string → treated as non-dict, no findings."""
        result = adapter.parse(json.dumps({"errors": "garbage"}))
        assert result == []

    def test_errors_is_not_dict_number(self, adapter):
        """errors is a number → treated as non-dict, no findings."""
        result = adapter.parse(json.dumps({"errors": 42}))
        assert result == []

    def test_errors_is_not_dict_null(self, adapter):
        """errors is null → treated as non-dict, no findings."""
        result = adapter.parse(json.dumps({"errors": None}))
        assert result == []

    def test_errors_is_not_dict_bool(self, adapter):
        """errors is True → treated as non-dict, no findings."""
        result = adapter.parse(json.dumps({"errors": True}))
        assert result == []


# ---------------------------------------------------------------------------
# parse(): known categories with severity mapping
# ---------------------------------------------------------------------------

class TestParseKnownCategories:
    """Test known category → severity mappings."""

    def test_unused_imports_severity_warning(self, adapter):
        """unused_imports → severity 'warning'."""
        data = {"errors": {"unused_imports": [{"module": "unused_pkg"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].severity == "warning"
        assert result[0].rule_id == "unused_imports"
        assert result[0].tool == "deptry"
        assert result[0].layer == "L4"
        assert result[0].language == "python"

    def test_missing_imports_severity_error(self, adapter):
        """missing_imports → severity 'error'."""
        data = {"errors": {"missing_imports": [{"module": "missing_pkg"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].severity == "error"
        assert result[0].rule_id == "missing_imports"

    def test_incorrectly_placed_imports_severity_warning(self, adapter):
        """incorrectly_placed_imports → severity 'warning'."""
        data = {"errors": {"incorrectly_placed_imports": [{"module": "bad_import"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].severity == "warning"
        assert result[0].rule_id == "incorrectly_placed_imports"

    def test_type_fragment_without_import_severity_warning(self, adapter):
        """type_fragment_without_import → severity 'warning'."""
        data = {"errors": {"type_fragment_without_import": [{"module": "frag"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].severity == "warning"
        assert result[0].rule_id == "type_fragment_without_import"

    def test_unknown_category_severity_info(self, adapter):
        """Unknown category → severity 'info'."""
        data = {"errors": {"totally_unknown": [{"module": "x"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].severity == "info"
        assert result[0].rule_id == "totally_unknown"


# ---------------------------------------------------------------------------
# parse(): dict items – module/name/line/filepath
# ---------------------------------------------------------------------------

class TestParseDictItems:
    """Test dict item field extraction (module, name, filepath, line)."""

    def test_item_with_module(self, adapter):
        """Item keyed on 'module' → correct module in Finding."""
        data = {"errors": {"unused_imports": [{"module": "my_module"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].message == "unused_imports: my_module"
        assert result[0].node == "my_module"

    def test_item_with_name_no_module(self, adapter):
        """Item with 'name' but no 'module' → fallback to name."""
        data = {"errors": {"unused_imports": [{"name": "name_only"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].message == "unused_imports: name_only"
        assert result[0].node == "name_only"

    def test_item_with_module_and_name_takes_module(self, adapter):
        """Item with both 'module' and 'name' → 'module' wins."""
        data = {"errors": {"unused_imports": [{"module": "mod", "name": "nm"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].message == "unused_imports: mod"
        assert result[0].node == "mod"

    def test_item_no_module_no_name(self, adapter):
        """Item without 'module' or 'name' → empty string module."""
        data = {"errors": {"unused_imports": [{"other": "val"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].message == "unused_imports: "

    def test_item_with_filepath_and_line(self, adapter):
        """Item with filepath and line → detail includes path:line."""
        data = {"errors": {"unused_imports": [{"module": "x", "filepath": "src/a.py", "line": 42}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].node == "src/a.py"
        assert result[0].message == "src/a.py:42 — unused_imports: x"

    def test_item_with_filepath_no_line(self, adapter):
        """Item with filepath but line=0 → detail includes path only."""
        data = {"errors": {"unused_imports": [{"module": "x", "filepath": "src/b.py", "line": 0}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].node == "src/b.py"
        assert result[0].message == "src/b.py — unused_imports: x"

    def test_item_with_filepath_line_no(self, adapter):
        """Item with 'line_no' instead of 'line' → fallback works."""
        data = {"errors": {"unused_imports": [{"module": "x", "filepath": "src/c.py", "line_no": 10}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].message == "src/c.py:10 — unused_imports: x"

    def test_item_with_empty_filepath(self, adapter):
        """Empty string filepath → node falls through to module."""
        data = {"errors": {"unused_imports": [{"module": "m", "filepath": ""}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].node == "m"


# ---------------------------------------------------------------------------
# parse(): non-dict items (plain strings)
# ---------------------------------------------------------------------------

class TestParseNonDictItems:
    """Test non-dict (string) items."""

    def test_string_item(self, adapter):
        """String item → module=str(item), empty filepath, line=0."""
        data = {"errors": {"unused_imports": ["bare_string"]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].message == "unused_imports: bare_string"
        assert result[0].node == "bare_string"
        assert result[0].severity == "warning"

    def test_string_item_empty(self, adapter):
        """Empty string item → module=''."""
        data = {"errors": {"unused_imports": [""]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1

    def test_string_item_node_when_empty_module(self, adapter):
        """Empty module string item → node is '<unknown>'."""
        data = {"errors": {"unused_imports": [""]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].node == "<unknown>"


# ---------------------------------------------------------------------------
# parse(): items list mutation – non-list items skipped
# ---------------------------------------------------------------------------

class TestParseNonListItems:
    """Test that non-list error categories are skipped."""

    def test_items_is_dict_not_list(self, adapter):
        """Category value is a dict (not list) → skipped."""
        data = {"errors": {"unused_imports": {"not_a_list": True}}}
        result = adapter.parse(json.dumps(data))
        assert result == []

    def test_items_is_string_not_list(self, adapter):
        """Category value is a string (not list) → skipped."""
        data = {"errors": {"unused_imports": "not_a_list"}}
        result = adapter.parse(json.dumps(data))
        assert result == []

    def test_items_is_number_not_list(self, adapter):
        """Category value is a number (not list) → skipped."""
        data = {"errors": {"unused_imports": 42}}
        result = adapter.parse(json.dumps(data))
        assert result == []

    def test_items_is_none_not_list(self, adapter):
        """Category value is None (not list) → skipped."""
        data = {"errors": {"unused_imports": None}}
        result = adapter.parse(json.dumps(data))
        assert result == []

    def test_mixed_list_and_nonlist(self, adapter):
        """Known category with non-list → skipped, other valid categories still parsed."""
        data = {
            "errors": {
                "unused_imports": {"bad": "dict"},
                "missing_imports": [{"module": "pkg"}],
            }
        }
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].rule_id == "missing_imports"


# ---------------------------------------------------------------------------
# parse(): multiple items and findings attributes
# ---------------------------------------------------------------------------

class TestParseMultipleItems:
    """Test multiple items across categories."""

    def test_multiple_items_same_category(self, adapter):
        """Two items in same category → two findings."""
        data = {"errors": {"unused_imports": [{"module": "a"}, {"module": "b"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 2
        assert result[0].message == "unused_imports: a"
        assert result[1].message == "unused_imports: b"

    def test_multiple_categories(self, adapter):
        """Items across multiple categories → all found."""
        data = {
            "errors": {
                "unused_imports": [{"module": "a"}],
                "missing_imports": [{"module": "b"}],
            }
        }
        result = adapter.parse(json.dumps(data))
        assert len(result) == 2
        rule_ids = {r.rule_id for r in result}
        assert rule_ids == {"unused_imports", "missing_imports"}

    def test_finding_fix_hint(self, adapter):
        """Finding fix_hint contains category reference."""
        data = {"errors": {"unused_imports": [{"module": "foo"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].fix_hint == "Review unused_imports for 'foo'"

    def test_finding_fix_hint_with_name(self, adapter):
        """Finding fix_hint uses 'name' field when module is absent."""
        data = {"errors": {"unused_imports": [{"name": "bar"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].fix_hint == "Review unused_imports for 'bar'"

    def test_all_finding_fields_set(self, adapter):
        """All mandatory fields on Finding are set (not None)."""
        data = {"errors": {"unused_imports": [{"module": "m"}]}}
        result = adapter.parse(json.dumps(data))
        f = result[0]
        assert f.node == "m"
        assert f.severity == "warning"
        assert f.rule_id == "unused_imports"
        assert f.tool == "deptry"
        assert f.layer == "L4"
        assert f.language == "python"
        assert f.fix_hint is not None


# ---------------------------------------------------------------------------
# parse(): boundary and edge cases
# ---------------------------------------------------------------------------

class TestParseBoundaries:
    """Boundary conditions and edge cases."""

    def test_deeply_nested_category_names(self, adapter):
        """Multi-word category name still parsed."""
        data = {"errors": {"unused_imports": [{"module": "m"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].message == "unused_imports: m"

    def test_line_no_with_zero(self, adapter):
        """line_no = 0 → filepath shown without line."""
        data = {"errors": {"unused_imports": [{"module": "m", "filepath": "f.py", "line_no": 0}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].node == "f.py"
        assert result[0].message == "f.py — unused_imports: m"

    def test_line_with_negative(self, adapter):
        """line = -1 → truthy, shown in detail."""
        data = {"errors": {"unused_imports": [{"module": "m", "filepath": "f.py", "line": -1}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        assert "-1" in result[0].message

    def test_filepath_only_category_message(self, adapter):
        """Category name becomes part of message even without filepath."""
        data = {"errors": {"unused_imports": [{"module": "m"}]}}
        result = adapter.parse(json.dumps(data))
        assert "unused_imports:" in result[0].message


# ---------------------------------------------------------------------------
# invoke(): ToolInvocation for binary not found and with args
# ---------------------------------------------------------------------------

class TestInvoke:
    """Test invoke method paths."""

    def test_invoke_binary_not_found(self, adapter):
        """deptry not on PATH → ToolInvocation with error."""
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value=None):
            inv = adapter.invoke(Path("/tmp/empty"), [])
        assert inv.exitcode == 3
        assert "deptry not found on PATH" in inv.stderr

    def test_invoke_binary_found(self, adapter):
        """deptry on PATH → runs with --output json."""
        mock_result = MagicMock(stdout='{"errors":{}}', stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(Path("/tmp/empty"), [])
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args.args[0] == [
            "/bin/deptry", "--output", "json",
            "--extend-exclude", "mutants", "--extend-exclude", "\\.mutmut",
            ".",
        ]

    def test_invoke_with_extra_args(self, adapter):
        """Extra args appended to command."""
        mock_result = MagicMock(stdout='{"errors":{}}', stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(Path("/tmp/empty"), ["--extend-exclude", "tests/"])
        call_args = mock_run.call_args
        assert call_args.args[0] == [
            "/bin/deptry", "--output", "json",
            "--extend-exclude", "mutants", "--extend-exclude", "\\.mutmut",
            ".", "--extend-exclude", "tests/",
        ]

    def test_invoke_args_empty(self, adapter):
        """Empty args → no extra flags appended."""
        mock_result = MagicMock(stdout='{"errors":{}}', stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(Path("/tmp/empty"), [])
        call_args = mock_run.call_args
        assert call_args.args[0] == [
            "/bin/deptry", "--output", "json",
            "--extend-exclude", "mutants", "--extend-exclude", "\\.mutmut",
            ".",
        ]

    def test_invoke_with_env(self, adapter):
        """env mapping passed to _run."""
        mock_result = MagicMock(stdout='{"errors":{}}', stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(Path("/tmp/empty"), [], env={"FOO": "bar"})
        # Check env was passed
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("env") == {"FOO": "bar"}

    def test_invoke_with_timeout(self, adapter):
        """Custom timeout passed to _run."""
        mock_result = MagicMock(stdout='{"errors":{}}', stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(Path("/tmp/empty"), [], timeout=120.0)
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("timeout") == 120.0

    def test_invoke_wiring_exact_call_args(self, adapter):
        """invoke() calls _run with exact cmd list + cwd/env/timeout.

        Kills mutmut_1,3,4,5,11,23,27: cmd element mutations (binary, flags, "."),
        cwd→None, env→None. Uses §4.4 exact cmd list + kwargs §4.7.
        """
        mock_result = MagicMock(stdout='{"errors":{}}', stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(
                    Path("/tmp/deploy"),
                    ["--extend-exclude", "docs/"],
                    env={"DEPTRY_ENV": "1"},
                    timeout=150.0,
                )
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd == [
            "/bin/deptry", "--output", "json",
            "--extend-exclude", "mutants", "--extend-exclude", "\\.mutmut",
            ".", "--extend-exclude", "docs/",
        ]
        assert call_args.kwargs["cwd"] == Path("/tmp/deploy")
        assert call_args.kwargs["env"] == {"DEPTRY_ENV": "1"}
        assert call_args.kwargs["timeout"] == 150.0

    def test_invoke_default_timeout(self, adapter):
        """Default timeout=300.0 forwarded to _run.

        Kills mutmut_2: timeout default mutation (300→301).
        """
        mock_result = MagicMock(stdout='{"errors":{}}', stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(Path("/tmp/empty"), [])
        assert mock_run.call_args.kwargs["timeout"] == 300.0


# ---------------------------------------------------------------------------
# version(): method
# ---------------------------------------------------------------------------

class TestVersion:
    """Test version method."""

    def test_version_binary_not_found(self, adapter):
        """deptry not on PATH → RuntimeError."""
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="deptry not found on PATH"):
                adapter.version(Path("/tmp/empty"))

    def test_version_returns_stdout(self, adapter):
        """version returns stripped stdout."""
        mock_result = MagicMock(stdout="deptry 0.12.0\n", stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result):
                ver = adapter.version(Path("/tmp/empty"))
        assert ver == "deptry 0.12.0"

    def test_version_empty_returns_unknown(self, adapter):
        """version empty stdout → 'unknown'."""
        mock_result = MagicMock(stdout="\n", stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result):
                ver = adapter.version(Path("/tmp/empty"))
        assert ver == "unknown"

    def test_version_no_newline(self, adapter):
        """Version without trailing newline still works."""
        mock_result = MagicMock(stdout="deptry 0.14.1", stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result):
                ver = adapter.version(Path("/tmp/empty"))
        assert ver == "deptry 0.14.1"

    def test_version_with_env(self, adapter):
        """Custom env passed to _run."""
        mock_result = MagicMock(stdout="deptry 0.12.0", stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp/empty"), env={"FOO": "bar"})
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("env") == {"FOO": "bar"}

    def test_version_wiring_exact_call_args(self, adapter):
        """version() calls _run with exact binary + --version cmd + cwd + env.

        Kills mutmut survivors (11,12,14,15,17,18): cmd element mutations,
        cwd→None, env→None on version call. Uses §4.4 spy.
        """
        mock_result = MagicMock(stdout="deptry 0.12.0", stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp/empty"), env={"DEPTRY_ENV": "1"})
        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == ["/bin/deptry", "--version"]
        assert mock_run.call_args.kwargs["env"] == {"DEPTRY_ENV": "1"}

    def test_version_env_none_passed(self, adapter):
        """env=None passed to _run when not specified.

        Kills mutmut on env=env mutation: env=None → removed.
        """
        mock_result = MagicMock(stdout="deptry 0.12.0", stderr="", exitcode=0)
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp/empty"))
        assert mock_run.call_args.kwargs["env"] is None

    def test_version_shutil_which_called_with_deptry_literal(self, adapter):
        """version() calls shutil.which('deptry') verbatim (kills mutmut_2: which(None)).

        Technique H2: spy on shutil.which and assert the exact call argument.
        Under the mutant, shutil.which(None) is called → assert_called_once_with('deptry') fails.
        """
        mock_result = MagicMock(stdout="deptry 0.12.0", stderr="", exitcode=0)
        with (
            patch(
                "harness_quality_gate.adapters.python.deptry_adapter.shutil.which",
                return_value="/bin/deptry",
            ) as which_mock,
            patch.object(adapter, "_run", return_value=mock_result),
        ):
            adapter.version(Path("/tmp/empty"))
        which_mock.assert_called_once_with("deptry")


# ---------------------------------------------------------------------------
# Properties and identity
# ---------------------------------------------------------------------------

class TestProperties:
    """Test DeptryAdapter properties."""

    def test_name_property(self, adapter):
        assert adapter.name == "deptry"

    def test_name_class_attribute(self, adapter):
        assert adapter._name == "deptry"

    def test_parse_finding_full_object(self, adapter):
        """Full Finding comparison kills remaining mutmut (1,2,71,73,74).

        Mutmut_1,2: module/name field extraction → default mutations
        Mutmut_71,73,74: detail/message construction → string mutations
        Uses dense assertions on every Finding field (§4.1).
        """
        data = {
            "errors": {
                "unused_imports": [{
                    "module": "requests",
                    "filepath": "src/client.py",
                    "line": 37,
                }],
            }
        }
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        f = result[0]
        assert f.node == "src/client.py"
        assert f.severity == "warning"
        assert f.message == "src/client.py:37 — unused_imports: requests"
        assert f.fix_hint == "Review unused_imports for 'requests'"
        assert f.tool == "deptry"
        assert f.layer == "L4"
        assert f.language == "python"
        assert f.rule_id == "unused_imports"

    def test_parse_name_field_fallback(self, adapter):
        """Item with 'name' but no 'module' → module falls back to name.

        Kills mutmut_1,2: get("module"→"XXmoduleXX", get("name"→"") mutations.
        """
        data = {"errors": {"missing_imports": [{"name": "missing_pkg", "filepath": "src/app.py"}]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        f = result[0]
        assert f.node == "src/app.py"
        # with line=0 (falsy) and filepath: detail = "src/app.py — missing_imports: missing_pkg"
        assert f.message == "src/app.py — missing_imports: missing_pkg"
        assert f.severity == "error"
        assert f.rule_id == "missing_imports"
        assert f.tool == "deptry"

    def test_parse_items_string_item_full(self, adapter):
        """String item in a list → node='<unknown>' with full fields.

        Kills mutmut_71,73,74: non-dict item path mutations.
        """
        data = {"errors": {"unused_imports": ["bare_module"]}}
        result = adapter.parse(json.dumps(data))
        assert len(result) == 1
        f = result[0]
        assert f.node == "bare_module"
        assert f.severity == "warning"
        assert f.message == "unused_imports: bare_module"
        assert f.fix_hint == "Review unused_imports for 'bare_module'"
        assert f.tool == "deptry"
        assert f.rule_id == "unused_imports"
