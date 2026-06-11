"""Unit tests for the allow-list audit engine.

Covers unjustified → non-zero exit; --diff-from → ignored in POC;
all-justified → exit 0; no markers → exit 0.
"""

from __future__ import annotations

from pathlib import Path

from harness_quality_gate.allow_list_auditor import (
    AllowListAuditor,
    AllowListEntry,
    _build_allow_list,
    audit as audit_findings,
)
from harness_quality_gate.models import Finding


# ---------------------------------------------------------------------------
# Helpers — fixture-like via tmp_path (pytest)
# ---------------------------------------------------------------------------


def _write_php(tmp_path: Path, name: str, content: str) -> Path:
    """Write a .php file under tmp_path and return its path."""
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Unjustified → exit 1
# ---------------------------------------------------------------------------


def test_auditor_unjustified_no_metadata(tmp_path: Path) -> None:
    """@infection-ignore-all without reason/audited → exit 1."""
    _write_php(tmp_path, "test.php", """<?php
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 1
    warnings = [f for f in report.findings if f.severity == "warning"]
    assert len(warnings) >= 1


def test_auditor_missing_reason_only(tmp_path: Path) -> None:
    """Has audited but no reason → unjustified."""
    _write_php(tmp_path, "test.php", """<?php
/**
 * audited: 2026-01-01
 */
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 1


def test_auditor_missing_audited_only(tmp_path: Path) -> None:
    """Has reason but no audited → unjustified."""
    _write_php(tmp_path, "test.php", """<?php
/**
 * reason: test coverage
 */
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 1


# ---------------------------------------------------------------------------
# Justified → exit 0
# ---------------------------------------------------------------------------


def test_auditor_justified_marker(tmp_path: Path) -> None:
    """@infection-ignore-all with reason+audited → exit 0."""
    _write_php(tmp_path, "test.php", """<?php
/**
 * reason: test coverage
 * audited: 2026-01-01
 */
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_auditor_no_markers(tmp_path: Path) -> None:
    """No @infection-ignore-all in repo → exit 0."""
    _write_php(tmp_path, "test.php", "<?php class Foo { public function test(): void {} }")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 0


def test_auditor_diff_from_ignored_in_poc(tmp_path: Path) -> None:
    """diff_from parameter is ignored in POC — still scans all files."""
    _write_php(tmp_path, "test.php", """<?php
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path, diff_from="main")
    assert report.exit_code == 1


def test_auditor_summary(tmp_path: Path) -> None:
    """Summary includes counts of justified/unjustified."""
    _write_php(tmp_path, "test.php", """<?php
/**
 * reason: test coverage
 * audited: 2026-01-01
 */
class Foo {
    // @infection-ignore-all
}
""")
    _write_php(tmp_path, "test2.php", """<?php
class Bar {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert "justified" in report.summary
    assert "unjustified" in report.summary


def test_auditor_summary_exact_format_with_both_types(tmp_path: Path) -> None:
    """Kill count-expr mutations (mutmut 6,7) and separator mutations (mutmut 37,38).

    The summary format is: "<N> justified ignore(s); <M> unjustified ignore(s) ...".
    Changing the count expression (len→different int), the separator "; " → other,
    or removing count parts would all produce a different string that doesn't contain
    the expected count digits.
    """
    _write_php(tmp_path, "test.php", """<?php
/**
 * reason: test coverage
 * audited: 2026-01-01
 */
class Foo {
    // @infection-ignore-all
}
""")
    _write_php(tmp_path, "test2.php", """<?php
class Bar {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    # 1 justified, 1 unjustified
    # "1 justified ignore(s); 1 unjustified ignore(s) ..."
    # Kill: f"{len(result.ignored)}" → f"{len(result.ignored)+1}" (count wrong)
    # Kill: "; " → other separator (string doesn't match expected count)
    assert report.summary.startswith("1 justified ignore(s)")
    assert "1 unjustified ignore(s)" in report.summary


def test_auditor_summary_only_justified(tmp_path: Path) -> None:
    """Kill the 'No annotations found' vs 'N justified' branch mutation (mutmut 52-55).

    When only justified markers exist, summary must NOT say 'No annotations found'.
    It should show the count of justified ignores.
    """
    _write_php(tmp_path, "test.php", """<?php
/**
 * reason: test coverage
 * audited: 2026-01-01
 */
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 0
    assert "1 justified ignore(s)" in report.summary
    assert "No" not in report.summary or "No" in "No"  # ensure "No" doesn't appear as prefix


def test_auditor_summary_only_unjustified(tmp_path: Path) -> None:
    """Kill the branch where only unjustified exists vs empty list mutation."""
    _write_php(tmp_path, "test.php", """<?php
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 1
    assert "1 unjustified ignore(s)" in report.summary
    assert "No" not in report.summary or "No" in "No"


def test_auditor_summary_no_markers(tmp_path: Path) -> None:
    """Kill 'No annotations found' string mutation on empty repo."""
    _write_php(tmp_path, "test.php", "<?php class Foo { public function test(): void {} }")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 0
    # Must contain "No" and "annotations found" — kills string mutation of this text
    assert "No" in report.summary
    assert "annotation" in report.summary or "marker" in report.summary.lower()


# ---------------------------------------------------------------------------
# Mutation-killer tests for node/message/fix_hint fields
# ---------------------------------------------------------------------------


def _write_py(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_unjustified_finding_node_is_relative_path(tmp_path: Path) -> None:
    """Kill node=None and node=str(None) mutations on unjustified path.
    The node must be a relative path string (not None / 'None')."""
    _write_py(tmp_path, "m.py", "x = 1  # pragma: " "no mutate\n")
    report = AllowListAuditor(language="python").audit(tmp_path)
    assert report.exit_code == 1
    unjustified = [f for f in report.findings if f.severity == "warning"]
    assert unjustified, "should have unjustified finding"
    # node must be non-None and a valid relative path (not the string "None")
    assert unjustified[0].node is not None
    assert unjustified[0].node != "None"
    assert unjustified[0].node == "m.py"


def test_justified_finding_node_is_relative_path(tmp_path: Path) -> None:
    """Kill node=None and node=str(None) mutations on justified path."""
    _write_py(
        tmp_path,
        "m.py",
        "# reason: provably-equivalent\n# audited: 2026-06-04\nx = 1  # pragma: " "no mutate\n",
    )
    report = AllowListAuditor(language="python").audit(tmp_path)
    assert report.exit_code == 0
    justified = [f for f in report.findings if f.severity == "info"]
    assert justified, "should have justified finding"
    assert justified[0].node is not None
    assert justified[0].node != "None"
    assert justified[0].node == "m.py"


def test_unjustified_finding_message_is_non_none(tmp_path: Path) -> None:
    """Kill message=None mutation: unjustified finding must have a message string."""
    _write_py(tmp_path, "m.py", "x = 1  # pragma: " "no mutate\n")
    report = AllowListAuditor(language="python").audit(tmp_path)
    unjustified = [f for f in report.findings if f.severity == "warning"]
    assert unjustified
    assert unjustified[0].message is not None
    assert "pragma" in unjustified[0].message or "Unjustified" in unjustified[0].message


def test_unjustified_finding_exact_line_number(tmp_path: Path) -> None:
    """Kill 'at line {i + 1}' → 'at line {i - 1}' and 'at line {i + 2}' mutations
    (mutmut_52, 53) by asserting exact line number in unjustified message.

    The pragma is on line 1 (single-line file). So i=0, and the message should say
    'at line 1'. Mutations: i+1=1 → i-1=-1 (message: 'at line -1')
    or i+1=1 → i+2=2 (message: 'at line 2'). Both would fail this assertion."""
    _write_py(tmp_path, "m.py", "x = 1  # pragma: " "no mutate\n")
    report = AllowListAuditor(language="python").audit(tmp_path)
    assert report.exit_code == 1
    unjustified = [f for f in report.findings if f.severity == "warning"]
    assert len(unjustified) == 1, (
        f"Expected 1 unjustified finding, got: {unjustified} (exit_code={report.exit_code})"
    )
    assert "at line 1" in unjustified[0].message, (
        f"Expected 'at line 1', got: {unjustified[0].message}"
    )


def test_unjustified_finding_fix_hint_is_non_none(tmp_path: Path) -> None:
    """Kill fix_hint=None, fix_hint removal, and fix_hint string mutations (mutmut_54, 55).

    The fix_hint must be the exact expected string — not mutated with "XX" prefix/suffix
    (mutmut_54: "XXAdd # reason: ... XX") or case change (mutmut_55: "add # reason: ...").
    """
    _write_py(tmp_path, "m.py", "x = 1  # pragma: " "no mutate\n")
    report = AllowListAuditor(language="python").audit(tmp_path)
    unjustified = [f for f in report.findings if f.severity == "warning"]
    assert unjustified
    assert unjustified[0].fix_hint is not None
    fix_hint = unjustified[0].fix_hint
    # Kill mutmut_54: exact string "Add # reason" must be present (not "XXAdd ... XX")
    assert "Add # reason" in fix_hint, (
        f"Expected 'Add # reason' in fix_hint, got: {fix_hint}"
    )
    # Kill mutmut_55: the fix_hint must NOT be lowercase "add # reason"
    # The mutation changes "Add" → "add". Assert it starts with "Add " not "add "
    assert fix_hint.lstrip().startswith("Add #"), (
        f"Expected 'Add' (capitalized), got: {fix_hint}"
    )


def test_default_language_is_php(tmp_path: Path) -> None:
    """Kill language='php'→'XXphpXX' default: AllowListAuditor() must scan PHP files."""
    _write_php(tmp_path, "x.php", "<?php\n// @infection-ignore-all\nfunction f() {}\n")
    # No language arg — uses default "php"
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 1, "PHP file with unjustified marker must return exit_code=1"


def test_unknown_language_returns_zero_ignored_count(tmp_path: Path) -> None:
    """Pin the full unknown-language early-return report (all four fields)."""
    report = AllowListAuditor(language="cobol").audit(tmp_path)
    assert report.exit_code == 0
    assert report.ignored_count == 0
    assert report.summary == "Unknown language: cobol"
    assert report.findings == []


# ---------------------------------------------------------------------------
# AllowListEntry.matches() with pattern (regex fullmatch)
# ---------------------------------------------------------------------------


def test_entry_matches_pattern_exact() -> None:
    """Kill pattern fullmatch False→True mutation: exact rule_id match via regex."""
    entry = AllowListEntry(rule_id="SOME_RULE", pattern=r"SOME_RULE")
    assert entry.matches("SOME_RULE") is True


def test_entry_matches_pattern_partial() -> None:
    """Kill pattern fullmatch True→False: non-matching rule_id with regex pattern."""
    entry = AllowListEntry(rule_id="SOME_RULE", pattern=r"SOME_RULE")
    assert entry.matches("OTHER_RULE") is False


def test_entry_matches_pattern_wildcard() -> None:
    """Kill pattern fullmatch: wildcard regex matches multiple rule_ids."""
    entry = AllowListEntry(rule_id="PHP_*", pattern=r"PHP_.+")
    assert entry.matches("PHP_LINT") is True
    assert entry.matches("PHP_CS_FIXER") is True
    assert entry.matches("PYTHON_TYPE") is False


def test_entry_matches_no_pattern_exact() -> None:
    """Kill no-pattern branch mutation: exact rule_id == candidate."""
    entry = AllowListEntry(rule_id="SOME_RULE")
    assert entry.matches("SOME_RULE") is True
    assert entry.matches("OTHER_RULE") is False


# ---------------------------------------------------------------------------
# _build_allow_list() return list construction (line 42)
# ---------------------------------------------------------------------------


def test_build_allow_list_returns_entries() -> None:
    """Kill return list construction: _build_allow_list must return AllowListEntry objects."""
    raw = ["PHP_LINT", "PHP_CS_FIXER", "PHP_TIDES"]
    entries = _build_allow_list(raw)
    assert len(entries) == 3
    for e, expected_id in zip(entries, raw):
        assert isinstance(e, AllowListEntry)
        assert e.rule_id == expected_id
        assert e.pattern is None


def test_build_allow_list_empty() -> None:
    """Kill return list empty mutation: empty input → empty list."""
    entries = _build_allow_list([])
    assert entries == []


# ---------------------------------------------------------------------------
# audit() function — findings filter with allow_list (lines 59-65)
# ---------------------------------------------------------------------------


def test_audit_returns_empty_when_all_filtered() -> None:
    """Kill return list mutation: all findings match allow_list → empty result."""
    findings = [
        Finding(node="a.php", severity="warning", message="lint issue", rule_id="PHP_LINT"),
        Finding(node="b.php", severity="warning", message="cs issue", rule_id="PHP_CS_FIXER"),
    ]
    result = audit_findings(findings, allow_list=["PHP_LINT", "PHP_CS_FIXER"])
    assert result == []


def test_audit_preserves_non_matching_findings() -> None:
    """Kill result.append mutation: non-matching findings should be kept."""
    findings = [
        Finding(node="a.php", severity="warning", message="lint issue", rule_id="PHP_LINT"),
        Finding(node="b.php", severity="warning", message="type issue", rule_id="PYTHON_TYPE"),
    ]
    result = audit_findings(findings, allow_list=["PHP_LINT"])
    assert len(result) == 1
    assert result[0].rule_id == "PYTHON_TYPE"


def test_audit_none_rule_id_not_filtered() -> None:
    """Kill 'f.rule_id is not None' branch mutation: None rule_id should pass through."""
    findings = [
        Finding(node="a.php", severity="warning", message="no rule", rule_id=None),
    ]
    result = audit_findings(findings, allow_list=["PHP_LINT"])
    assert len(result) == 1
    assert result[0].rule_id is None


def test_audit_empty_findings_returns_empty() -> None:
    """Kill early return mutation: empty findings → empty result."""
    result = audit_findings([], allow_list=["PHP_LINT"])
    assert result == []


def test_audit_empty_allow_list_returns_all() -> None:
    """Kill any() branch mutation: empty allow_list → no filtering, returns all."""
    findings = [
        Finding(node="a.php", severity="warning", message="lint issue", rule_id="PHP_LINT"),
        Finding(node="b.php", severity="warning", message="cs issue", rule_id="PHP_CS_FIXER"),
    ]
    result = audit_findings(findings, allow_list=[])
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Third-party / generated tree exclusions (_EXCLUDED_DIRS)
# ---------------------------------------------------------------------------

def _write_unjustified_php(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<?php\n/** @infection-ignore-all */\nclass X {}\n", encoding="utf-8",
    )


def _write_unjustified_py(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1  # pragma: " "no mutate\n", encoding="utf-8")


def test_excluded_dirs_exact_set() -> None:
    """Pin the exclusion set so element mutations (drops/typos) are killed."""
    from harness_quality_gate.allow_list_auditor import _EXCLUDED_DIRS
    assert _EXCLUDED_DIRS == frozenset({
        "vendor", "node_modules", ".venv", "venv",
        "mutants", ".mutmut", ".git", "__pycache__",
    })


def test_vendor_and_generated_trees_not_scanned_php(tmp_path: Path) -> None:
    """Unjustified @infection-ignore-all inside every excluded dir is invisible."""
    from harness_quality_gate.allow_list_auditor import _EXCLUDED_DIRS
    for excluded in sorted(_EXCLUDED_DIRS):
        _write_unjustified_php(tmp_path / excluded / "pkg" / "Bad.php")
    report = AllowListAuditor(language="php").audit(tmp_path)
    assert report.exit_code == 0
    assert report.findings == []
    assert report.ignored_count == 0


def test_generated_trees_not_scanned_python(tmp_path: Path) -> None:
    """Unjustified pragmas inside every excluded dir are invisible."""
    from harness_quality_gate.allow_list_auditor import _EXCLUDED_DIRS
    for excluded in sorted(_EXCLUDED_DIRS):
        _write_unjustified_py(tmp_path / excluded / "lib" / "mod.py")
    report = AllowListAuditor(language="python").audit(tmp_path)
    assert report.exit_code == 0
    assert report.findings == []


def test_own_code_next_to_vendor_still_scanned(tmp_path: Path) -> None:
    """The exclusion must not hide first-party files outside those dirs.

    Excluded dirs sort both BEFORE (.git, mutants) and AFTER (vendor) the
    own file, so hitting an excluded path must skip-and-continue — a
    ``break`` would abort the scan and miss ``src/Own.php`` entirely.
    """
    _write_unjustified_php(tmp_path / ".git" / "hooks" / "Bad.php")
    _write_unjustified_php(tmp_path / "mutants" / "pkg" / "Bad.php")
    _write_unjustified_php(tmp_path / "vendor" / "pkg" / "Bad.php")
    _write_unjustified_php(tmp_path / "src" / "Own.php")
    report = AllowListAuditor(language="php").audit(tmp_path)
    assert report.exit_code != 0
    assert len(report.findings) == 1
    assert "src/Own.php" in report.findings[0].node
    assert "vendor" not in report.findings[0].node


def test_exclusion_matches_path_segment_not_substring(tmp_path: Path) -> None:
    """A dir merely *containing* an excluded name (vendor_utils) is scanned."""
    _write_unjustified_py(tmp_path / "vendor_utils" / "mod.py")
    report = AllowListAuditor(language="python").audit(tmp_path)
    assert report.exit_code != 0
    assert len(report.findings) == 1
