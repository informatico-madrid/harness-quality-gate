"""Unit tests for the doctor (tool check) module.

Covers tool detection, report format, and asdict serialization
per Coverage Table.
"""

from __future__ import annotations

from harness_quality_gate.doctor import DoctorReport, ToolCheckReport, asdict, run


def test_doctor_report_json_mode(tmp_path) -> None:
    """Doctor runs in JSON mode and returns a report with tool checks."""
    result = run(tmp_path, json_mode=True)
    assert isinstance(result, DoctorReport)
    assert isinstance(result.tools, list)
    assert len(result.tools) > 0


def test_doctor_report_human_mode(tmp_path) -> None:
    """Doctor runs in human mode and returns a report."""
    result = run(tmp_path, json_mode=False)
    assert isinstance(result, DoctorReport)


def test_doctor_asdict_serialization() -> None:
    """DoctorReport.asdict() serializes to dict with expected keys."""
    report = DoctorReport(
        verdict="ready",
        python_version="3.12",
        php_version="0.0.0",
        composer_version="0.0.0",
        tools=[
            ToolCheckReport(tool="ruff", exit_code=0, output="", error=None),
        ],
        warnings=["some warning"],
    )
    data = asdict(report)
    assert data["verdict"] == "ready"
    assert data["python_version"] == "3.12"
    assert data["php_version"] == "0.0.0"
    assert data["composer_version"] == "0.0.0"
    assert len(data["tools"]) == 1
    assert data["tools"][0]["tool"] == "ruff"
    assert data["tools"][0]["exit_code"] == 0
    assert data["warnings"] == ["some warning"]
