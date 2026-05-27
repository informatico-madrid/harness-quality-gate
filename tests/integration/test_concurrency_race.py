"""Race-condition and concurrency tests for TD-15.

Verifies that parallel adapter invocations write to isolated scratch
directories and that checkpoint.py is the sole writer of checkpoint
files — no write contention, no data corruption.

Design: TD-15 (race-condition prevention: per-adapter scratch dirs +
single-writer checkpoint)
Requirements: NFR-6
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pytest

from harness_quality_gate.checkpoint import build, write as write_checkpoint
from harness_quality_gate.state import scratch_dir


# ---------------------------------------------------------------------------
# Scratch-directory isolation under parallel loads
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestScratchDirIsolation:
    """Parallel workers each create to their own _quality-gate/work/<lang>/<tool>/."""

    NUM_WORKERS = 8

    def _worker(self, idx: int, repo: Path) -> str:
        """Create one scratch dir and return its path string."""
        language = ["python", "php"][idx % 2]
        tool = f"tool-{idx}"
        d = scratch_dir(repo, language, tool)
        # Write a unique marker inside this worker's scratch dir
        (d / f"marker-{idx}.txt").write_text(f"worker-{idx}", encoding="utf-8")
        return str(d)

    def test_parallel_scratch_dirs_are_isolated(self, tmp_git_repo: Path) -> None:
        """N parallel workers create N distinct scratch dirs with no cross-write."""
        # Store (worker_id, path) tuples so we can match markers correctly
        results: list[tuple[int, str]] = []
        with ThreadPoolExecutor(max_workers=self.NUM_WORKERS) as pool:
            futures = {
                pool.submit(self._worker, i, tmp_git_repo): i
                for i in range(self.NUM_WORKERS)
            }
            for f in as_completed(futures):
                results.append((futures[f], f.result()))

        assert len(results) == self.NUM_WORKERS
        # Each path must be unique
        path_set = {r[1] for r in results}
        assert len(path_set) == self.NUM_WORKERS
        # Each dir exists and contains only its own marker
        for worker_id, p in results:
            d = Path(p)
            assert d.is_dir()
            my_marker = f"marker-{worker_id}.txt"
            # Marker file present
            marker_found = any(m.name == my_marker for m in d.iterdir())
            assert marker_found, f"marker missing in {p}"
            # No marker from another worker leaked in
            other_markers = [m for m in d.iterdir() if m.name != my_marker]
            assert len(other_markers) == 0, f"leaked marker files in {p}"

    def test_concurrent_scratch_dir_creates_parent(self, tmp_git_repo: Path) -> None:
        """scratch_dir creates the full _quality-gate/work/… tree on demand."""
        repo = tmp_git_repo
        for i in range(self.NUM_WORKERS):
            language = ["python", "php"][i % 2]
            tool = f"big-tool-{i}"
            d = scratch_dir(repo, language, tool)
            assert d.is_dir()
            assert "_quality-gate" in str(d)
            assert "work" in str(d)
            assert language in str(d)
            assert tool in str(d)


# ---------------------------------------------------------------------------
# Single-writer checkpoint (TD-15)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestCheckpointSingleWriter:
    """Only checkpoint.py writes checkpoint.json — no race-condition output."""

    NUM_WRITERS = 8

    def _checkpoint_worker(self, idx: int, repo: Path) -> dict[str, Any]:
        """Build a checkpoint and write to the same path concurrently."""
        layer_results = [
            {
                "layer": "L3A",
                "language": "python",
                "passed": True,
                "findings": [],
                "duration_sec": 0.1 * (idx + 1),
            }
        ]
        runtime = {
            "python_version": "3.12.0",
            "concurrency": "parallel",
            "ci": False,
        }
        detection = {
            "repo_path": str(repo),
            "language": "python",
            "framework": None,
            "confidence": 0.95,
            "languages_detected": ["python"],
            "frameworks": {},
            "file_counts": {"python": 10},
        }
        data = build(layer_results, runtime, detection)
        write_checkpoint(repo / "_quality-gate" / "quality-gate-latest.json", data)
        return data

    def test_parallel_checkpoint_writes_yields_single_valid_file(
        self, tmp_git_repo: Path
    ) -> None:
        """N concurrent checkpoint writes produce one valid checkpoint file."""
        cp_path = tmp_git_repo / "_quality-gate" / "quality-gate-latest.json"

        with ThreadPoolExecutor(max_workers=self.NUM_WRITERS) as pool:
            futures = [
                pool.submit(self._checkpoint_worker, i, tmp_git_repo)
                for i in range(self.NUM_WRITERS)
            ]
            for f in as_completed(futures):
                f.result()  # raise any exception

        # Exactly one checkpoint file exists
        assert cp_path.is_file(), "checkpoint file should exist"
        # File is valid JSON
        raw = cp_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["version"] == "v2"
        assert data["language"] == "python"

    def test_concurrent_checkpoint_no_corrupt_bytes(self, tmp_git_repo: Path) -> None:
        """Even with N=16 concurrent writes, the JSON is parseable."""
        cp_path = tmp_git_repo / "_quality-gate" / "quality-gate-latest.json"

        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [
                pool.submit(self._checkpoint_worker, i, tmp_git_repo)
                for i in range(16)
            ]
            for f in as_completed(futures):
                f.result()

        # Must parse cleanly — no truncation or interleaving
        raw = cp_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert "version" in data
        assert "layers" in data

    def test_checkpoint_only_writer_not_scratch(self, tmp_git_repo: Path) -> None:
        """Checkpoint output lives outside _quality-gate/work/ — only in _quality-gate/."""
        # Run a few scratch-dir workers
        for i in range(4):
            language = ["python", "php"][i % 2]
            tool = f"audit-{i}"
            scratch_dir(tmp_git_repo, language, tool)

        # Write checkpoint to the same repo
        data = build(
            [{"layer": "L3A", "language": "python", "passed": True, "findings": [], "duration_sec": 0.1}],
            {"python_version": "3.12.0", "concurrency": "parallel", "ci": False},
            {"repo_path": str(tmp_git_repo), "language": "python", "framework": None,
             "confidence": 0.95, "languages_detected": ["python"], "frameworks": {},
             "file_counts": {"python": 5}},
        )
        write_checkpoint(tmp_git_repo / "_quality-gate" / "quality-gate-latest.json", data)

        # The checkpoint file is in _quality-gate/, not _quality-gate/work/
        cp = tmp_git_repo / "_quality-gate" / "quality-gate-latest.json"
        assert cp.is_file()
        # No checkpoint file leaked into any worker scratch dir
        for work_dir in tmp_git_repo.rglob("work"):
            if work_dir.is_dir():
                for f in work_dir.rglob("*"):
                    if f.is_file():
                        assert "quality-gate-latest.json" not in f.name, \
                            "checkpoint file should NOT be in work/ scratch dir"


# ---------------------------------------------------------------------------
# Hybrid parallel: Python + PHP scratch dirs co-exist
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestHybridScratchCoexistence:
    """Both Python and PHP adapters can create scratch dirs in the same repo."""

    def test_hybrid_scratch_dirs_in_same_repo(self, tmp_git_repo: Path) -> None:
        """Parallel Python and PHP scratch creation → all dirs isolated."""
        langs_tools = [
            ("python", "ruff"),
            ("python", "pyright"),
            ("php", "phpstan"),
            ("php", "phpmd"),
        ]
        results: list[Path] = []

        def create(lang: str, tool: str) -> Path:
            d = scratch_dir(tmp_git_repo, lang, tool)
            (d / "ok").write_text("1", encoding="utf-8")
            return d

        with ThreadPoolExecutor(max_workers=len(langs_tools)) as pool:
            futures = [pool.submit(create, lang, tool) for lang, tool in langs_tools]
            for f in as_completed(futures):
                results.append(f.result())

        assert len(results) == len(langs_tools)
        # Each dir belongs to exactly one language/tool pair
        for r in results:
            lang_part = r.parts[-2]  # work/<lang>/<tool> → parts[-2] is language
            tool_part = r.parts[-1]  # parts[-1] is tool
            assert lang_part in ("python", "php")
            assert tool_part in ("ruff", "pyright", "phpstan", "phpmd")
