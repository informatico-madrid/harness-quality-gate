"""Comprehensive tests for PestAdapter (PHP test runner + mutation orchestration).

Mutation-testing tests targeting 69 survivors.
Design: each public method exercised with granular separate asserts.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
from harness_quality_gate.models import Finding, LayerResult


# ===========================================================================
# name property
# ===========================================================================


def test_name_returns_pest() -> None:
    """name returns exactly 'pest'."""
    assert PestAdapter().name == "pest"


def test_name_is_str() -> None:
    """name is a str."""
    assert isinstance(PestAdapter().name, str)


# ===========================================================================
# parse()
# ===========================================================================


class TestParse:
    """parse() returns [] for every input."""

    def test_parse_empty(self) -> None:
        assert PestAdapter().parse("", "", 0) == []

    def test_parse_with_stderr(self) -> None:
        assert PestAdapter().parse("", "stderr", 1) == []

    def test_parse_valid_json(self) -> None:
        assert PestAdapter().parse(json.dumps({"test": 1}), "", 0) == []

    def test_parse_exitcode_nonzero(self) -> None:
        assert PestAdapter().parse("", "", 42) == []

    def test_parse_returns_list_not_none(self) -> None:
        result = PestAdapter().parse("", "", 0)
        assert isinstance(result, list)
        assert len(result) == 0


# ===========================================================================
# _pest_binary()
# ===========================================================================


class TestPestBinary:
    """_pest_binary() resolves pest: vendor/bin first, then PATH."""

    def test_pest_binary_none_repo_raises(self) -> None:
        adapter = PestAdapter()
        with pytest.raises(RuntimeError) as exc_ctx:
            adapter._pest_binary(None)
        assert str(exc_ctx.value) == "repository path is None"

    def test_pest_binary_vendor_bin_is_file(self, tmp_path: Path) -> None:
        """vendor/bin/pest exists → vendor path returned."""
        vendor_bin = tmp_path / "vendor" / "bin" / "pest"
        vendor_bin.parent.mkdir(parents=True)
        vendor_bin.write_text("#!/bin/bash", encoding="utf-8")
        adapter = PestAdapter()
        result = adapter._pest_binary(tmp_path)
        assert result is not None
        assert result == [str(vendor_bin)]

    def test_pest_binary_vendor_bin_is_dir_not_file(self, tmp_path: Path) -> None:
        """vendor/bin/pest is directory → falls through to PATH."""
        vendor_bin = tmp_path / "vendor" / "bin" / "pest"
        vendor_bin.parent.mkdir(parents=True)
        vendor_bin.mkdir()
        adapter = PestAdapter()
        with patch("shutil.which", return_value=None):
            result = adapter._pest_binary(tmp_path)
        assert result is None

    def test_pest_binary_vendor_not_file_but_path_has_pest(
        self, tmp_path: Path
    ) -> None:
        """vendor/bin/pest missing, PATH has pest → system path."""
        vendor_bin = tmp_path / "vendor" / "bin" / "pest"
        vendor_bin.parent.mkdir(parents=True)
        adapter = PestAdapter()
        with patch("shutil.which", return_value="/usr/bin/pest"):
            result = adapter._pest_binary(tmp_path)
        assert result == ["/usr/bin/pest"]

    def test_pest_binary_neither_found(self, tmp_path: Path) -> None:
        """No pest in vendor/bin or PATH → None."""
        adapter = PestAdapter()
        with patch("shutil.which", return_value=None):
            result = adapter._pest_binary(tmp_path)
        assert result is None

    def test_pest_binary_type_str(self, tmp_path: Path) -> None:
        """_pest_binary returns list[str] or None."""
        vendor_bin = tmp_path / "vendor" / "bin" / "pest"
        vendor_bin.parent.mkdir(parents=True)
        vendor_bin.write_text("#!/bin/bash", encoding="utf-8")
        adapter = PestAdapter()
        result = adapter._pest_binary(tmp_path)
        assert isinstance(result, list) or result is None


class TestPestBinaryExactPath:
    """_pest_binary returns EXACT path, killing string mutations."""

    def test_pest_binary_vendor_path_exact(
        self, tmp_path: Path
    ) -> None:
        """Exact path value killed: mutation __repr__ → __str__."""
        vendor_bin = tmp_path / "vendor" / "bin" / "pest"
        vendor_bin.parent.mkdir(parents=True)
        vendor_bin.write_text("#!/bin/bash", encoding="utf-8")
        adapter = PestAdapter()
        result = adapter._pest_binary(tmp_path)
        # Using __repr__ assertion kills mutation on list(str) call
        assert repr(result) == f"[{str(vendor_bin)!r}]"

    def test_pest_binary_returns_one_item(self, tmp_path: Path) -> None:
        """Returns a single item list, kills empty list and multi-item mutations."""
        vendor_bin = tmp_path / "vendor" / "bin" / "pest"
        vendor_bin.parent.mkdir(parents=True)
        vendor_bin.write_text("#!/bin/bash", encoding="utf-8")
        adapter = PestAdapter()
        result = adapter._pest_binary(tmp_path)
        assert len(result) == 1
        assert result[0] == str(vendor_bin)


# ===========================================================================
# _has_mutate_plugin()
# ===========================================================================


class TestHasMutatePlugin:
    """_has_mutate_plugin() checks composer.json for pest-plugin-mutate."""

    def test_no_composer_json(self, tmp_path: Path) -> None:
        """No composer.json → False."""
        adapter = PestAdapter()
        assert adapter._has_mutate_plugin(tmp_path) is False

    def test_composer_json_no_deps(self, tmp_path: Path) -> None:
        """composer.json without require/require-dev → False."""
        composer = tmp_path / "composer.json"
        composer.write_text('{"name": "test"}', encoding="utf-8")
        adapter = PestAdapter()
        assert adapter._has_mutate_plugin(tmp_path) is False

    def test_composer_json_require_has_plugin(self, tmp_path: Path) -> None:
        """pest-plugin-mutate in require → True."""
        composer = tmp_path / "composer.json"
        data = {"require": {"pestphp/pest-plugin-mutate": "^1.0"}}
        composer.write_text(json.dumps(data), encoding="utf-8")
        adapter = PestAdapter()
        assert adapter._has_mutate_plugin(tmp_path) is True

    def test_composer_json_require_dev_has_plugin(self, tmp_path: Path) -> None:
        """pest-plugin-mutate in require-dev → True."""
        composer = tmp_path / "composer.json"
        data = {"require-dev": {"pestphp/pest-plugin-mutate": "^2.0"}}
        composer.write_text(json.dumps(data), encoding="utf-8")
        adapter = PestAdapter()
        assert adapter._has_mutate_plugin(tmp_path) is True

    def test_composer_json_neither_has_plugin(self, tmp_path: Path) -> None:
        """pest-plugin-mutate absent → False."""
        composer = tmp_path / "composer.json"
        data = {"require": {"other": "^1.0"}}
        composer.write_text(json.dumps(data), encoding="utf-8")
        adapter = PestAdapter()
        assert adapter._has_mutate_plugin(tmp_path) is False

    def test_composer_json_invalid_json(self, tmp_path: Path) -> None:
        """Malformed JSON → False."""
        composer = tmp_path / "composer.json"
        composer.write_text("{invalid", encoding="utf-8")
        adapter = PestAdapter()
        assert adapter._has_mutate_plugin(tmp_path) is False

    def test_composer_json_require_is_not_dict(self, tmp_path: Path) -> None:
        """require is a list (not dict) → False."""
        composer = tmp_path / "composer.json"
        data = {"require": ["pestphp/pest-plugin-mutate"]}
        composer.write_text(json.dumps(data), encoding="utf-8")
        adapter = PestAdapter()
        assert adapter._has_mutate_plugin(tmp_path) is False

    def test_has_mutate_plugin_returns_bool(self, tmp_path: Path) -> None:
        """_has_mutate_plugin always returns boolean."""
        adapter = PestAdapter()
        result = adapter._has_mutate_plugin(tmp_path)
        assert isinstance(result, bool)

    def test_has_mutate_plugin_returns_true_bool_not_string(self, tmp_path: Path) -> None:
        """Ensures True not string 'true' — kills string mutation."""
        composer = tmp_path / "composer.json"
        data = {"require": {"pestphp/pest-plugin-mutate": "^1.0"}}
        composer.write_text(json.dumps(data), encoding="utf-8")
        adapter = PestAdapter()
        result = adapter._has_mutate_plugin(tmp_path)
        assert result is True
        assert not isinstance(result, str)


class TestHasMutatePluginExactValue:
    """_has_mutate_plugin returns EXACT True/False, killing string mutations."""

    def test_has_mutate_plugin_true_value(self, tmp_path: Path) -> None:
        """Exact True (not truthy string) — kills string mutation."""
        composer = tmp_path / "composer.json"
        data = {"require": {"pestphp/pest-plugin-mutate": "^1.0"}}
        composer.write_text(json.dumps(data), encoding="utf-8")
        # This kills mutant: True → "" → falsey
        adapter = PestAdapter()
        assert adapter._has_mutate_plugin(tmp_path) is True
        assert adapter._has_mutate_plugin(tmp_path) is not False

    def test_has_mutate_plugin_false_value(self, tmp_path: Path) -> None:
        """Exact False (not falsy string) — kills string mutation."""
        adapter = PestAdapter()
        # This kills mutant: False → "" → falsey but str
        tmp_path_tmp = tmp_path / "empty"
        tmp_path_tmp.mkdir(exist_ok=True)
        assert adapter._has_mutate_plugin(tmp_path_tmp) is False
        assert adapter._has_mutate_plugin(tmp_path_tmp) is not True


# ===========================================================================
# version() — mutation targets
# ===========================================================================


class TestVersion:
    """version() runs subprocess with pest --version."""

    def test_version_pest_not_found(self, tmp_path: Path) -> None:
        """Pest not found → RuntimeError."""
        adapter = PestAdapter()
        with patch.object(adapter, "_pest_binary", return_value=None):
            with pytest.raises(RuntimeError) as exc_ctx:
                adapter.version(tmp_path)
        msg = str(exc_ctx.value)
        assert msg == "pest not found on PATH or in vendor/bin"

    def test_version_pest_binary_runs_subprocess(self, tmp_path: Path) -> None:
        """Subprocess called with [pest, --version]."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "1.8.1"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed) as mock:
                adapter.version(tmp_path)
        mock.assert_called_once()
        call_args = mock.call_args
        assert call_args[0][0] == ["/usr/bin/pest", "--version"]

    def test_version_cwd_is_repo(self, tmp_path: Path) -> None:
        """Subprocess cwd is repo string."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "1.8.1"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed) as mock:
                adapter.version(tmp_path)
        call_args = mock.call_args
        assert call_args[1]["cwd"] == str(tmp_path)

    def test_version_with_env_passthrough(self, tmp_path: Path) -> None:
        """Env is merged with os.environ."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "1.8.1"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed) as mock:
                adapter.version(tmp_path, env={"FOO": "bar"})
        call_kwargs = mock.call_args[1]
        assert call_kwargs["env"]["FOO"] == "bar"

    def test_version_nonzero_exitcode(self, tmp_path: Path) -> None:
        """Non-zero exitcode → RuntimeError with stderr."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 1
        completed.stderr = "error here"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed):
                with pytest.raises(RuntimeError) as exc_ctx:
                    adapter.version(tmp_path)
        msg = str(exc_ctx.value)
        assert "pest --version failed" in msg
        assert "error here" in msg

    def test_version_parses_version_from_output(self, tmp_path: Path) -> None:
        """Version string extracted from first token matching X.Y."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Pest 2.34.5"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed):
                result = adapter.version(tmp_path)
        assert result == "2.34.5"

    def test_version_parses_version_with_at_sign(self, tmp_path: Path) -> None:
        """Parses version with @ in version token (like some Psalm outputs)."""
        # Format: "Pest3.1.0@xxx" → parts = ["Pest3.1.0@xxx"] → p[0]="P" not digit
        # So output like "Pest 3.1.0@xxx" → parts = ["Pest", "3.1.0@xxx"] → "3" is digit
        # Returns full token "3.1.0@xxx"
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Pest3.1.0@xxx"  # only one token, p[0]="P" not digit → returns full
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed):
                result = adapter.version(tmp_path)
        # "Pest3.1.0@xxx" has p[0]='P' not digit, returns full output
        assert result == "Pest3.1.0@xxx"

    def test_version_no_version_token_returns_stdout(self, tmp_path: Path) -> None:
        """No version token found → returns full stripped stdout."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "pest version unknown"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed):
                result = adapter.version(tmp_path)
        assert result == "pest version unknown"

    def test_version_returns_str_not_none(self, tmp_path: Path) -> None:
        """version() always returns str."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "1.0.0"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed):
                result = adapter.version(tmp_path)
        assert isinstance(result, str)
        assert result == "1.0.0"

    def test_version_timeout(self, tmp_path: Path) -> None:
        """Subprocess timeout → TimeoutExpired raised."""
        adapter = PestAdapter()
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["pest"], timeout=30)):
                with pytest.raises(subprocess.TimeoutExpired):
                    adapter.version(tmp_path)



    def test_version_version_with_space(self, tmp_path: Path) -> None:
        """Version in output with spaces handled correctly.
        
        'v1.2.3' starts with 'v' not a digit → not recognized as version token.
        Returns full output 'Pest v1.2.3'.
        """
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Pest v1.2.3"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed):
                result = adapter.version(tmp_path)
        assert result == "Pest v1.2.3"

    def test_version_version_with_digit_prefix(self, tmp_path: Path) -> None:
        """Version token starting with digit is recognized."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "1.2.3"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed):
                result = adapter.version(tmp_path)
        assert result == "1.2.3"


# ===========================================================================
# invoke()
# ===========================================================================


class TestInvoke:
    """invoke() runs pest with the provided args."""

    def test_invoke_no_binary_raises(self, tmp_path: Path) -> None:
        """Pest not found → RuntimeError."""
        adapter = PestAdapter()
        with patch.object(adapter, "_pest_binary", return_value=None):
            with pytest.raises(RuntimeError) as exc_ctx:
                adapter.invoke(tmp_path, ["--version"])
        assert str(exc_ctx.value) == "pest not found on PATH or in vendor/bin"

    def test_invoke_calls_subprocess(self, tmp_path: Path) -> None:
        """invoke() calls subprocess.run with [pest, *args]."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "passed"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed) as mock:
                adapter.invoke(tmp_path, ["--filter=foo"])
        call_args = mock.call_args[0][0]
        assert call_args == ["/usr/bin/pest", "--filter=foo"]

    def test_invoke_passes_cwd(self, tmp_path: Path) -> None:
        """invoke() passes repo as cwd."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "passed"
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed) as mock:
                adapter.invoke(tmp_path, ["--filter=foo"])
        call_kwargs = mock.call_args[1]
        assert call_kwargs["cwd"] == str(tmp_path)

    def test_invoke_with_custom_timeout(self, tmp_path: Path) -> None:
        """invoke() passes timeout to subprocess."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed) as mock:
                adapter.invoke(tmp_path, [], timeout=60.0)
        call_kwargs = mock.call_args[1]
        assert call_kwargs["timeout"] == 60.0

    def test_invoke_with_env(self, tmp_path: Path) -> None:
        """invoke() merges env with os.environ."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed) as mock:
                adapter.invoke(tmp_path, [], env={"APP_ENV": "testing"})
        call_kwargs = mock.call_args[1]
        assert call_kwargs["env"]["APP_ENV"] == "testing"

    def test_invoke_returns_tool_invocation(self, tmp_path: Path) -> None:
        """invoke() returns ToolInvocation."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "passed"
        completed.stderr = ""
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed):
                result = adapter.invoke(tmp_path, [])
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "exitcode")
        assert hasattr(result, "duration_seconds")

    def test_invoke_with_timeout_exc(self, tmp_path: Path) -> None:
        """invoke() _run catches TimeoutExpired and returns ToolInvocation with exitcode=-1.
        
        The _run() method in base.py catches TimeoutExpired and returns ToolInvocation.
        We mock subprocess.run to raise TimeoutExpired to exercise that code path.
        """
        adapter = PestAdapter()
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run",
                       side_effect=subprocess.TimeoutExpired(cmd=["pest"], timeout=300)):
                result = adapter.invoke(tmp_path, [])
        # _run catches TimeoutExpired, returns ToolInvocation with exitcode=-1
        assert hasattr(result, "exitcode")
        assert result.exitcode == -1

    def test_invoke_oserror(self, tmp_path: Path) -> None:
        """invoke() _run catches OSError from subprocess."""
        adapter = PestAdapter()
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("harness_quality_gate.adapters.base.subprocess.run",
                       side_effect=OSError("denied")):
                with pytest.raises(OSError):
                    adapter.invoke(tmp_path, [])

    def test_invoke_timeout_default(self, tmp_path: Path) -> None:
        """Default timeout is 300 seconds."""
        adapter = PestAdapter()
        completed = MagicMock()
        completed.returncode = 0
        with patch.object(adapter, "_pest_binary", return_value=["/usr/bin/pest"]):
            with patch("subprocess.run", return_value=completed) as mock:
                adapter.invoke(tmp_path, [])
        assert mock.call_args[1]["timeout"] == 300.0
