"""Tests for bmad.diversity_metric — self-eval F12.

The walker swept ``.venv/`` and ``mutants/`` (thousands of third-party
test files) and the pairwise Levenshtein matrix is O(n²) — on a real
repo (2700+ tests) L2 hung for over 30 minutes.
"""

from __future__ import annotations

from pathlib import Path

from harness_quality_gate.bmad.diversity_metric import diversity


def _write_test_file(path: Path, n_tests: int, prefix: str = "t") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(
        f"def test_{prefix}_{i}():\n    assert {i} == {i}" for i in range(n_tests)
    )
    path.write_text(body + "\n", encoding="utf-8")


class TestArtifactExclusion:
    def test_venv_and_mutants_test_files_ignored(self, tmp_path: Path) -> None:
        _write_test_file(tmp_path / "tests" / "test_real.py", 2)
        _write_test_file(tmp_path / ".venv" / "lib" / "test_vendored.py", 5)
        _write_test_file(tmp_path / "mutants" / "tests" / "test_copy.py", 7)
        _write_test_file(tmp_path / "node_modules" / "x" / "test_js_helper.py", 3)
        result = diversity(tmp_path, "python")
        assert result["total_tests"] == 2

    def test_hidden_dirs_ignored(self, tmp_path: Path) -> None:
        _write_test_file(tmp_path / "tests" / "test_real.py", 1)
        _write_test_file(tmp_path / ".cache" / "test_cached.py", 4)
        result = diversity(tmp_path, "python")
        assert result["total_tests"] == 1


class TestPairwiseSampling:
    def test_large_suites_are_sampled(self, tmp_path: Path) -> None:
        """Above the cap the O(n²) matrix runs on a deterministic sample."""
        _write_test_file(tmp_path / "tests" / "test_a.py", 250, "a")
        _write_test_file(tmp_path / "tests" / "test_b.py", 250, "b")
        result = diversity(tmp_path, "python")
        assert result["total_tests"] == 500          # real count is reported
        assert result["sample_size"] == 300          # computation is capped
        assert 0.0 <= result["diversity_score"] <= 1.0

    def test_small_suites_not_sampled(self, tmp_path: Path) -> None:
        _write_test_file(tmp_path / "tests" / "test_a.py", 10)
        result = diversity(tmp_path, "python")
        assert result["total_tests"] == 10
        assert result["sample_size"] == 10

    def test_sampling_is_deterministic(self, tmp_path: Path) -> None:
        _write_test_file(tmp_path / "tests" / "test_a.py", 200, "a")
        _write_test_file(tmp_path / "tests" / "test_b.py", 200, "b")
        r1 = diversity(tmp_path, "python")
        r2 = diversity(tmp_path, "python")
        assert r1["diversity_score"] == r2["diversity_score"]
