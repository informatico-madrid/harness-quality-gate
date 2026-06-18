---
title: Quality Gate Convergence Plan — Path A / Path B Unification
date: 2026-06-17
status: approved
author: system-architect
reviewed-by: malka
related:
  - plans/auto-evaluation-design.md
  - SKILL.md
  - config/quality-gate.yaml
---

# Quality Gate Convergence Plan

## 1. Problem Statement

Path A (PythonAdapters) and Path B (Step files) produce **different results** for the same tools:

1. `shutil.which()` fails inside venv for `bandit`, `vulture`, `deptry` — adapters silently skip entire layers
2. Version mismatches between system and venv binaries cause divergent findings
3. Flags differ between adapters and steps (ruff scans `tests/`, vulture missing confidence filter, pyright missing `--pythonpath`)
4. Mutmut has 3 parsers — none identifies specific survived mutants
5. No partial-run support — agents must always scan the entire repo
6. Source dir hardcoded to `src/` — doesn't work for repos with different layouts

---

## 2. Decisions Made

| Topic | Decision |
|---|---|
| Source dir | Default `src/`. If missing, LLM lists directories and **suggests** to user. User confirms. Not automatic. |
| `--max-children` | Auto-detect `os.cpu_count() // 2`, warn if user sets > cpu_count, but ultimately a **configurable setting** |
| Loop pattern | Not "Ralph Loop" — works for **any agent loop pattern** |
| Coverage threshold | **100%** default |
| Vulture confidence | **80** default (confirmed) |
| Mutmut survivors | Report `mutant_id + file_path + module`. Agent runs `mutmut show <id>` itself if it wants diffs |
| `--paths` scope | Only **Tier 1** (L3A + L1): ruff, pyright, pytest, mutmut. Fast feedback. Full gate runs without `--paths` |
| Source dir detection | Separate from language detection (Python/PHP — already exists, don't touch) |
| Config persistence | `_quality-gate/quality-gate.yaml` per project — already gitignored. Defaults from `{skill-root}/config/quality-gate.yaml`. CLI flags override at runtime |
| Mutmut parser | Fix Parser B (`mutation_analyzer.py`) as canonical base — fix bug, add survivor tracking, drop `--all true` |

---

## 3. Phase 1 — Self-Bootstrap & Tool Resolution

### 3A. Create `harness_quality_gate/bootstrap.py`

Functions:

- `ensure_venv(repo)` — create/refresh `.venv` if missing
- `install_tools(repo)` — `uv pip install` all required tools (ruff, bandit, vulture, deptry, mutmut, pytest, pyright python deps)
- `verify_tools(repo)` — run each binary with `--version`, compare against manifest
- `write_manifest(repo)` — write `.venv/hqg-tools-manifest.json` with `{name, version, path}` per tool
- `resolve_tool(name, repo) -> Path` — prioritize `.venv/bin/<name>` if exists, else system `PATH`, else raise `ToolNotAvailable(name)`
- `detect_source_dir(repo) -> str` — find production source directory (see §3C)
- `suggest_max_children() -> int` — `os.cpu_count() // 2`, warn if > cpu_count (see §3D)

Version conflict policy: if system > venv, warn but use venv (consistency > novelty).

### 3B. Replace all `shutil.which()` calls with `resolve_tool()`

Every adapter's `invoke()` currently does:
```python
binary = shutil.which("bandit")  # -> None in venv, layer silently skipped
```

Change to:
```python
from harness_quality_gate.bootstrap import resolve_tool
binary = str(resolve_tool("bandit", repo))  # -> /abs/.venv/bin/bandit
```

Files: `ruff_adapter.py`, `pyright_adapter.py`, `bandit_adapter.py`, `vulture_adapter.py`, `deptry_adapter.py`, `mutmut_adapter.py`, `pytest_adapter.py`, plus step files referencing bare tool names.

### 3C. Source Dir Detection Flow

```
1. Does _quality-gate/quality-gate.yaml exist with source_dir?
   -> YES: read source_dir from there
   -> NO: continue to step 2

2. Does src/ exist in the project?
   -> YES: suggest src/ as source_dir
   -> NO: LLM lists project directories and suggests which is the production code folder
   -> User confirms

3. Persist source_dir in _quality-gate/quality-gate.yaml
   (already in .gitignore — never commited)
```

This is **separate** from language detection (Python vs PHP — already exists in the repo, don't touch).

### 3D. CPU Detection & max-children

```python
import os

def suggest_max_children() -> int:
    cpus = os.cpu_count() or 2
    suggested = max(1, cpus // 2)
    if suggested > int(cpus * 0.75):
        # warning: high value may cause timeouts
        pass
    return suggested
```

- **Default**: `cpu_count // 2`
- **Warning** if user configures > `cpu_count` (timeout risk)
- **Persisted** in config as `mutmut_max_children`
- **Overridable** via `--max-children` CLI flag or config file

### 3E. Update `step-01-init.md` §1.5.5

Add explicit bootstrap step before any tool invocation:
```
1. Run `python -m harness_quality_gate.bootstrap --repo <repo>`
2. If source_dir not set -> run detection, suggest, user confirms
3. Verify manifest exists: `.venv/hqg-tools-manifest.json`
4. If any tool missing -> abort with install instructions
```

---

## 4. Phase 2 — Flag Unification (Adapters <-> Steps)

| Tool | Current Adapter | Current Step | Unified |
|---|---|---|---|
| **ruff** | `source_targets(repo, "src", exclude_tests=True)` -> 1 finding | Scans `.` (includes tests/) -> 123 findings | `source_dir` only, `--output-format=json`, exclude tests |
| **pyright** | No `--pythonpath` -> false positives | No `--pythonpath` -> import errors | Add `--pythonpath <sys.executable> --outputjson` |
| **pytest** | Terminal output only | Terminal output | `--junitxml=pytest-results.xml -p no:warnings` |
| **bandit** | Silently skipped (which=None) | Works via Makefile | Use `resolve_tool`, `-r -q --format json` |
| **vulture** | Silently skipped (which=None) | `--min-confidence 80` | Make confidence **configurable** (default 80) via config/CLI |
| **deptry** | Silently skipped (which=None) | Works via Makefile | Use `resolve_tool`, standard args |
| **mutmut** | Aggregate counts only, no survivor detail | No survivor detail | See Phase 3 |

All adapters should use `source_dir` (from config/detection) instead of hardcoded `"src"`.

---

## 5. Phase 3 — Mutmut Parser Unification

### 5A. Findings from Deep-Dive

| Parser | Survivors with file/line? | Per-module MSI? | Partial runs? | Verdict |
|---|---|---|---|---|
| A (adapter) | NO (counts only) | NO | YES (via args) | Discard |
| B (analyzer) | NO (buggy key via group(2)) | YES (broken) | NO | **Fix & extend** |
| C (script) | NO (emoji counts) | YES (partial) | YES (text filter) | Discard |

**None of the 3 parsers identifies specific survived mutants.** This is the critical gap.

### 5B. Fix Parser B (`mutation_analyzer.py`) as canonical base

- Fix `_extract_mutmut_module()`: change `match.group(2)` -> `match.group(1)` (dotted module path)
- Add module->filepath conversion: `harness_quality_gate.adapters.python.mutmut_adapter` -> `harness_quality_gate/adapters/python/mutmut_adapter.py`
- Change from `mutmut results --all true` (7,971 lines, 86% killed) to `mutmut results` (only survivors/timeouts ~121 lines)
- **Add survivor tracking**: collect list of `{mutant_id, module_path, file_path, status}` for all non-killed mutants

### 5C. New `parse_survivors()` method

```python
def parse_survivors(results_stdout: str) -> list[SurvivedMutant]:
    """Extract each survived/timeout mutant with actionable detail.

    Parses lines like:
      harness_quality_gate.adapters.base.x_source_targets__mutmut_8: survived
    Returns:
      mutant_id="x_source_targets__mutmut_8"
      module="harness_quality_gate.adapters.base"
      file="harness_quality_gate/adapters/base.py"
      status="survived"
    """
```

Agent can then run `mutmut show <id>` itself if it wants to see the actual diff.

### 5D. Gate decision with per-module thresholds

```python
def gate_decision(stats: dict[str, ModuleMutStats], threshold: float = 100.0) -> GateResult:
    """PASS if all modules >= threshold, else FAIL with list of underperforming modules."""
```

### 5E. Mutmut runtime configuration

- `--max-children` enforced (default from CPU detection)
- Paths configurable via CLI `--paths` (overrides `pyproject.toml` `paths_to_mutate`)
- `mutmut run <paths>` already supported by CLI — just needs threading through

---

## 6. Phase 4 — Partial Run Support (`--paths`)

### 6A. CLI change

Add `--paths` to `all` subcommand:

```python
all_p.add_argument("--paths", nargs="*", default=None,
    help="Subset of files/dirs to scan — runs only Tier 1 (L3A + L1)")
```

When `--paths` is provided, **only Tier 1** executes:
- **L3A**: ruff + pyright (scoped to specified files)
- **L1**: pytest (tests for specified modules) + mutmut (only those modules)

L2, L3B, L4 are **skipped** — partial runs are for fast agent feedback, not full gate.

When `--paths` is **not** provided, full gate runs: L3A -> L1 -> L2 -> L3B -> L4.

### 6B. Thread through PythonAdapter

```python
class PythonAdapter:
    def __init__(self, paths: list[str] | None = None):
        self.paths = paths
```

Each `_run_*` method in L3A and L1 receives `self.paths` and uses it instead of full-repo discovery.

### 6C. Tool-specific scoping (Tier 1 only)

| Tool | Scoping mechanism |
|---|---|
| Ruff | Pass file paths as positional args |
| Pyright | Pass file paths as positional args |
| Pytest | Pass specific test files related to changed source |
| Mutmut | `mutmut run <paths>` overrides `paths_to_mutate` |

L2, L3B, L4 tools are **not invoked** when `--paths` is set.

---

## 7. Phase 5 — Configurable Parameters

### 7A. Config locations

| Layer | Location |
|---|---|
| **Bundled defaults** | `{skill-root}/config/quality-gate.yaml` |
| **Per-project overrides** | `{project-root}/_quality-gate/quality-gate.yaml` (gitignored) |
| **Runtime overrides** | CLI flags |

Precedence: **CLI > project config > bundled defaults**

### 7B. Config parameters

| Parameter | Default | Purpose |
|---|---|---|
| `source_dir` | `"src"` (auto-detect if missing) | Production code directory |
| `vulture_confidence` | `80` | Filter dead-code noise |
| `ruff_exclude` | `["tests/"]` | Ruff scan scope exclusions |
| `mutmut_max_children` | `cpu_count // 2` | Parallel mutation workers |
| `mutation_threshold` | `100.0` | MSI gate pass/fail |
| `coverage_threshold` | `100.0` | Pytest coverage gate |

### 7C. Config YAML schema (additions to quality-gate.yaml)

```yaml
# _quality-gate/quality-gate.yaml — project-level overrides
source_dir: src                    # auto-detected if absent
vulture_confidence: 80
ruff_exclude:
  - tests/
mutmut_max_children: 4             # auto: cpu_count // 2
mutation_threshold: 100.0
coverage_threshold: 100.0
```

---

## 8. Execution Order

| Step | Files | Depends On |
|---|---|---|
| 1 | `harness_quality_gate/bootstrap.py` (new) | — |
| 2 | `resolve_tool()` in bootstrap | Step 1 |
| 3 | `detect_source_dir()` in bootstrap | Step 1 |
| 4 | `suggest_max_children()` in bootstrap | Step 1 |
| 5 | Replace `shutil.which()` in 7 adapters | Step 2 |
| 6 | Unify flags per tool (adapters + steps use `source_dir` from config) | Step 5 |
| 7 | Fix `mutation_analyzer.py` (bug group(2) -> group(1), module->filepath) | — |
| 8 | Add `parse_survivors()` (mutant_id + file_path + module) | Step 7 |
| 9 | `--paths` in CLI + PythonAdapter -> only Tier 1 | Step 6 |
| 10 | Thread `paths` through L3A + L1 adapters | Step 9 |
| 11 | Config loader additions (source_dir, thresholds, max_children) | Steps 3, 4, 9 |
| 12 | Update `step-01-init.md` bootstrap flow | Step 1 |
| 13 | Integration test: run gate end-to-end | Steps 1-12 |

---

## 9. Version Mismatches Reference

| Tool | System | Venv | Canonical |
|---|---|---|---|
| ruff | 0.15.6 | 0.15.15 | venv |
| pytest | 8.3.4 | 9.0.3 | venv |
| mutmut | 3.5.0 (BROKEN — missing trampoline) | 3.6.0 | venv (mandatory) |
| pyright | 1.1.408 (npm only) | n/a | system (npm) |
| bandit | n/a | venv | venv |
| vulture | n/a | venv | venv |
| deptry | n/a | venv | venv |

---

## 10. Critical Context

- `shutil.which("bandit|vulture|deptry")` returns `None` inside venv because CLI scripts exist only in `.venv/bin/` and the venv is not on `PATH`. Adapters silently skip the entire layer.
- Pyright is delivered strictly as an npm tool; it does not install into the Python environment, requiring `--pythonpath` to resolve `yaml`/`jsonschema` imports.
- Ruff Step path scans `tests/` (123 findings); adapter correctly restricts to production source (1 finding).
- Mutmut has 3 separate parsing scripts producing 3 different output formats. Parser B has a confirmed bug (`group(2)` returns mutation point name instead of module path).
- Source dir detection is **separate** from language detection (Python vs PHP already exists).

---

## 11. Relevant Files

### Adapters (all need `shutil.which()` -> `resolve_tool()`)
- `harness_quality_gate/adapters/python/ruff_adapter.py`
- `harness_quality_gate/adapters/python/pyright_adapter.py`
- `harness_quality_gate/adapters/python/pytest_adapter.py`
- `harness_quality_gate/adapters/python/mutmut_adapter.py`
- `harness_quality_gate/adapters/python/bandit_adapter.py`
- `harness_quality_gate/adapters/python/vulture_adapter.py`
- `harness_quality_gate/adapters/python/deptry_adapter.py`

### New files
- `harness_quality_gate/bootstrap.py`

### Step files (need flag unification + bootstrap reference)
- `.agents/skills/harness-quality-gate/steps/step-01-init.md`
- `.agents/skills/harness-quality-gate/steps/step-02-layer1.md`
- `.agents/skills/harness-quality-gate/steps/step-03a-layer3a.md`
- `.agents/skills/harness-quality-gate/steps/step-06-layer4.md`

### Mutmut parser (fix + extend)
- `harness_quality_gate/bmad/mutation_analyzer.py`

### CLI + config
- `harness_quality_gate/cli.py`
- `harness_quality_gate/config.py`
- `config/quality-gate.yaml`

### Existing helpers
- `harness_quality_gate/adapters/base.py` (`source_targets()`, `package_dirs()`)
- `harness_quality_gate/adapters/python/python_adapter.py` (`_src_dir()`)
- `Makefile`
- `pyproject.toml`
