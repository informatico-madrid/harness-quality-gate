"""Comprehensive tests for PcovAdapter (PHP code coverage driver).

Mutation-testing / pcov_adapter coverage — 42 survivors targeted.
Design: each public method exercised with granular separate asserts.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.php.pcov_adapter import PcovAdapter
from harness_quality_gate.models import Finding, LayerResult


# ===========================================================================
# version()
# ===========================================================================

class TestVersion:
    """version() must raise NotImplementedError (line 44 of pcov_adapter.py)."""

    def test_version_raises_not_implemented(self, tmp_path: Path) -> None:
        adapter = PcovAdapter()
        with pytest.raises(NotImplementedError) as exc_ctx:
            adapter.version(tmp_path)
        msg = str(exc_ctx.value)
        assert "pcov" in msg.lower()
        assert "not implement" in msg.lower()


# ===========================================================================
# invoke()
# ===========================================================================

class TestInvoke:
    """invoke() must raise NotImplementedError (line 54 of pcov_adapter.py)."""

    def test_invoke_raises_not_implemented(self, tmp_path: Path) -> None:
        adapter = PcovAdapter()
        with pytest.raises(NotImplementedError) as exc_ctx:
            adapter.invoke(tmp_path, ["run"])
        msg = str(exc_ctx.value)
        assert "not implement" in msg.lower()


# ===========================================================================
# parse() — main mutation target
# Line 62: `return []` — mutations: change condition, remove return, swap logic
# ===========================================================================

class TestParse:
    """parse() returns [] for every input — mutations at line 62."""

    def test_parse_empty_string(self) -> None:
        findings = PcovAdapter().parse("", "", 0)
        assert findings == []

    def test_parse_none_like_stdout(self) -> None:
        findings = PcovAdapter().parse("", "stderr here", 1)
        assert findings == []

    def test_parse_only_whitespace(self) -> None:
        findings = PcovAdapter().parse("   \n\t  \n  ", "  ", 0)
        assert findings == []

    def test_parse_valid_json_in_stdout_ignored(self) -> None:
        findings = PcovAdapter().parse('{"files": []}', "", 0)
        assert findings == []

    def test_parse_valid_json_with_content_in_stdout_ignored(self) -> None:
        findings = PcovAdapter().parse('{"files": [{"path": "/x.php", "lines": 10}]}', "err", 2)
        assert findings == []

    def test_parse_exitcode_nonzero_ignored(self) -> None:
        findings = PcovAdapter().parse("", "", 42)
        assert findings == []

    def test_parse_exitcode_negative_ignored(self) -> None:
        findings = PcovAdapter().parse("", "", -1)
        assert findings == []


# ===========================================================================
# probe() — exhaustive mutation killing
# ===========================================================================

class TestProbe:
    """probe() detects PCOV / Xdebug via `php -m` and glob.search.

    Mutant targets:
      - shutil.which path (line 77-79)
      - subprocess.run call (lines 82-89)
      - returncode guard (lines 91-93)
      - module set population (lines 96-100)
      - whitespace stripping (line 98)
      - pcov check (line 102)
      - glob search (lines 111-119)
      - xdebug check (line 103)
      - final raise (line 127)
    """

    def test_probe_php_not_on_path_raises_exact_message(self, caplog: pytest.LogCaptureFixture) -> None:
        adapter = PcovAdapter()
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value=None):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(RuntimeError) as exc_ctx:
                    adapter.probe()
        # Exact message kills mutants 7 ("XX...XX" wrapping) and 8 (lowercase "path")
        assert str(exc_ctx.value) == "php not found on PATH"

    def test_probe_php_found_path(self) -> None:
        adapter = PcovAdapter()
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run") as mock:
                completed = MagicMock()
                completed.returncode = 0
                completed.stdout = ""
                mock.return_value = completed
                with patch("glob.glob", return_value=["/tmp/pcov-extract/usr/lib/php/20210902/pcov.so"]):
                    adapter.probe()
        # Exact subprocess.run args kills mutant 11 (first arg mutated to None)
        mock.assert_called_once_with(["/usr/bin/php", "-m"], capture_output=True, text=True, timeout=10)

    def test_probe_uses_real_which_and_subprocess(self) -> None:
        """Test without patching shutil.which or subprocess.run.
        Relies on: php IS installed, but PCOV/Xdebug NOT installed.
        This kills mutants 2,3,4 (shutil.which arg mutations) and
        partially mutant 11 (subprocess.run with actual args).
        """
        adapter = PcovAdapter()
        with pytest.raises(RuntimeError) as exc_ctx:
            adapter.probe()
        assert str(exc_ctx.value) == "No coverage driver found — neither PCOV nor Xdebug is loaded"

    def test_probe_subprocess_oserror_raises(self) -> None:
        adapter = PcovAdapter()
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", side_effect=OSError("permission denied")):
                with pytest.raises(RuntimeError) as exc_ctx:
                    adapter.probe()
        msg = str(exc_ctx.value)
        assert "Failed to run" in msg

    def test_probe_subprocess_timeout_raises(self) -> None:
        adapter = PcovAdapter()
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["php"], timeout=10)):
                with pytest.raises(RuntimeError) as exc_ctx:
                    adapter.probe()
        msg = str(exc_ctx.value)
        assert "Failed to run" in msg

    def test_probe_nonzero_returncode_raises(self) -> None:
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 1
        completed.stderr = "php error"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with pytest.raises(RuntimeError) as exc_ctx:
                    adapter.probe()
        msg = str(exc_ctx.value)
        assert "failed" in msg.lower()

    def test_probe_pcov_in_output_returns_pcov(self) -> None:
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "pcov\nCore\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    result = adapter.probe()
        assert result == "pcov"

    def test_probe_pcov_uppercase_in_output(self) -> None:
        """Line 98: `.lower()` on stripped line. Case-insensitive check."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "PCOV\nCore\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    result = adapter.probe()
        assert result == "pcov"

    def test_probe_pcov_tabs_in_output(self) -> None:
        """Line 97-98: .splitlines() + .strip() handles tabs."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "\tpcov\t\n  Core  \n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    result = adapter.probe()
        assert result == "pcov"

    def test_probe_empty_php_modules(self) -> None:
        """output has no modules → falls through to glob/xdebug checks."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "\n\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    with pytest.raises(RuntimeError) as exc_ctx:
                        adapter.probe()
        msg = str(exc_ctx.value)
        assert "No coverage driver found" in msg

    def test_probe_xdebug_in_output_returns_xdebug(self) -> None:
        """fallback to xdebug when no pcov but xdebug present."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "xdebug\nCore\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    result = adapter.probe()
        assert result == "xdebug"

    def test_probe_xdebug_version_prefix(self) -> None:
        """Line 103: .startswith("xdebug") matches xdebug 3.x etc."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "xdebug 3.1.5\nCore\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    result = adapter.probe()
        assert result == "xdebug"

    def test_probe_pcov_via_tmp_glob(self) -> None:
        """Line 111-119: /tmp/pcov-extract glob fallback."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Core\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=["/tmp/pcov-extract/usr/lib/php/20210902/pcov.so"]):
                    result = adapter.probe()
        assert result == "pcov"

    def test_probe_pcov_via_usr_glob(self) -> None:
        """Line 113: /usr/lib/php/*/pcov.so glob fallback."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Core\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=["/usr/lib/php/20210902/pcov.so"]):
                    result = adapter.probe()
        assert result == "pcov"

    def test_probe_neither_driver_raises(self) -> None:
        """Line 127-129: no pcov, no xdebug, no glob → RuntimeError."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Core\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    with pytest.raises(RuntimeError) as exc_ctx:
                        adapter.probe()
        msg = str(exc_ctx.value)
        assert "No coverage driver found" in msg
        assert "PCOV" in msg
        assert "Xdebug" in msg

    def test_probe_pcov_and_xdebug_prefers_pcov(self) -> None:
        """When both present → pcov wins."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "pcov\nxdebug 3.1\nCore\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    result = adapter.probe()
        assert result == "pcov"

    def test_probe_module_name_in_middle_of_output(self) -> None:
        """Module set parsing finds pcov anywhere in list."""
        adapter = PcovAdapter()
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "date\nCore\npcov\nsodium\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    result = adapter.probe()
        assert result == "pcov"


# ===========================================================================
# probe_layer_result()
# ===========================================================================

class TestProbeLayerResult:
    """probe_layer_result() wraps probe() → LayerResult.

    Three paths: pcov (success), xdebug (success + warning), failure (error).
    """

    def test_layer_result_pcov_passed(self, tmp_path: Path) -> None:
        with patch.object(PcovAdapter, "probe", return_value="pcov"):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert isinstance(result, LayerResult)
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is True
        assert result.findings == []
        assert result.duration_sec == 0.0

    def test_layer_result_xdebug_passed_with_warning(self, tmp_path: Path) -> None:
        with patch.object(PcovAdapter, "probe", return_value="xdebug"):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert isinstance(result, LayerResult)
        assert result.passed is True
        assert len(result.findings) == 1
        f = result.findings[0]
        assert isinstance(f, Finding)
        assert f.severity == "warning"
        assert "xdebug" in f.message
        assert f.node == "pcov"

    def test_layer_result_probe_failure_error(self, tmp_path: Path) -> None:
        with patch.object(PcovAdapter, "probe", side_effect=RuntimeError("no driver")):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert isinstance(result, LayerResult)
        assert result.passed is False
        assert isinstance(result.duration_sec, float)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.severity == "error"
        assert "probe failed" in f.message.lower()
        assert f.node == "pcov"

    def test_layer_result_no_env_passed(self, tmp_path: Path) -> None:
        """invoke with env=None still works."""
        with patch.object(PcovAdapter, "probe", return_value="pcov"):
            result = PcovAdapter().probe_layer_result(tmp_path, env=None)
        assert result.passed is True

    def test_layer_result_xdebug_warning_no_env(self, tmp_path: Path) -> None:
        with patch.object(PcovAdapter, "probe", return_value="xdebug"):
            result = PcovAdapter().probe_layer_result(tmp_path, env=None)
        assert result.passed is True
        assert len(result.findings) >= 1
        assert result.findings[0].severity == "warning"

    def test_layer_result_failure_error_no_env(self, tmp_path: Path) -> None:
        with patch.object(PcovAdapter, "probe", side_effect=RuntimeError("boom")):
            result = PcovAdapter().probe_layer_result(tmp_path, env=None)
        assert result.passed is False
        assert result.findings[0].severity == "error"


# ===========================================================================
# name property
# ===========================================================================

class TestName:
    """name property returns 'pcov'."""

    def test_name_property(self) -> None:
        adapter = PcovAdapter()
        n = adapter.name
        assert n == "pcov"

    def test_name_type_str(self) -> None:
        assert isinstance(PcovAdapter().name, str)
