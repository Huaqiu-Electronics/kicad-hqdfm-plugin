"""Headless local analysis runner.

Loads a ``.kicad_pcb`` file, runs the local DFM checks, and returns a
structured result dict.  No wxPython, no cloud API — pcbnew only.

Usage::

    from kicad_dfm.headless import analyze_board

    result = analyze_board("my_board.kicad_pcb")
    print(result["status"])      # "pass" | "warn" | "fail"
    print(result["exit_code"])   # 0 | 1 | 2
    print(result["checks"])      # list[CheckResult]

.. note::

    This module needs KiCad's ``pcbnew`` Python module to be importable.
    When testing without KiCad, the project's ``tests/pcbnew_stub.py`` is
    injected by ``conftest.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Output dataclasses ────────────────────────────────────────────────


@dataclass
class CheckResult:
    """Outcome of a single DFM check item."""

    name: str
    display: str
    color: str
    violations: int = 0

    @property
    def status(self) -> str:
        if self.color == "red":
            return "fail"
        if self.color == "gold":
            return "warn"
        return "pass"


@dataclass
class AnalysisReport:
    """Complete result of a headless analysis run."""

    board_path: str
    status: str = "pass"  # "pass" | "warn" | "fail"
    exit_code: int = 0
    checks: list[CheckResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "board": self.board_path,
            "status": self.status,
            "exit_code": self.exit_code,
            "checks": [
                {
                    "name": c.name,
                    "display": c.display,
                    "color": c.color,
                    "violations": c.violations,
                    "status": c.status,
                }
                for c in self.checks
            ],
            "errors": self.errors,
        }


# ── Analysis runner ───────────────────────────────────────────────────


def analyze_board(board_path: str) -> AnalysisReport:
    """Run local DFM checks on *board_path* and return a report."""
    import pcbnew

    report = AnalysisReport(board_path=board_path)

    board = pcbnew.LoadBoard(board_path)
    if board is None:
        report.status = "fail"
        report.exit_code = 2
        report.errors.append("Failed to load board file")
        return report

    from kicad_dfm.analysis import MinimumLineWidth

    checker = MinimumLineWidth(None, board)

    checks: list[CheckResult] = []

    analysis_result = _build_empty_analysis_result()
    _run_and_collect(
        checker, "Smallest Trace Width", checker.get_line_width(analysis_result), checks
    )
    _run_and_collect(
        checker, "RingHole", checker.get_annular_ring(analysis_result), checks
    )
    _run_and_collect(
        checker,
        "Hatched Copper Pour",
        checker.get_zone_attribute(analysis_result),
        checks,
    )
    _run_and_collect(checker, "Pad size", checker.get_pad(analysis_result), checks)

    report.checks = checks
    _compute_status(report)
    return report


def _build_empty_analysis_result() -> dict[str, Any]:
    return {
        "Smallest Trace Width": {
            "check": [{"result": [{"item": "", "rule": "0.1,0.3"}]}]
        },
        "RingHole": {"check": [{"result": [{"item": "", "rule": "0.1,0.3"}]}]},
        "Hatched Copper Pour": {
            "check": [{"result": [{"item": "", "rule": "0.1,0.3"}]}]
        },
        "Pad size": {"check": [{"result": [{"item": "", "rule": "0.1,0.3"}]}]},
    }


def _run_and_collect(
    checker: Any, name: str, result: Any, checks: list[CheckResult]
) -> None:
    if isinstance(result, dict) and result:
        item_count = 0
        if result.get("check"):
            item_count = sum(
                len(c.get("result", [])) for c in result["check"] if isinstance(c, dict)
            )
        checks.append(
            CheckResult(
                name=name,
                display=str(result.get("display", "")),
                color=str(result.get("color", "black")),
                violations=item_count,
            )
        )
    elif result == "":
        checks.append(
            CheckResult(name=name, display="no data", color="black", violations=0)
        )


def _compute_status(report: AnalysisReport) -> None:
    colors = {c.color for c in report.checks if c.color != "black"}
    if "red" in colors:
        report.status = "fail"
        report.exit_code = 2
    elif "gold" in colors:
        report.status = "warn"
        report.exit_code = 1
    else:
        report.status = "pass"
        report.exit_code = 0
