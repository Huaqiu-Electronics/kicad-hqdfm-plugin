import json

import pytest

from kicad_dfm.headless import (
    AnalysisReport,
    CheckResult,
    _compute_status,
    _run_and_collect,
)


pytestmark = pytest.mark.pure


class TestCheckResult:
    def test_pass(self):
        cr = CheckResult(name="test", display="0.5", color="black", violations=0)
        assert cr.status == "pass"

    def test_warn(self):
        cr = CheckResult(name="test", display="0.3", color="gold", violations=3)
        assert cr.status == "warn"

    def test_fail(self):
        cr = CheckResult(name="test", display="0.1", color="red", violations=5)
        assert cr.status == "fail"

    def test_defaults(self):
        cr = CheckResult(name="x", display="", color="black")
        assert cr.violations == 0
        assert cr.status == "pass"


class TestAnalysisReport:
    def test_empty(self):
        report = AnalysisReport(board_path="test.kicad_pcb")
        assert report.status == "pass"
        assert report.exit_code == 0
        assert report.checks == []
        assert report.errors == []

    def test_to_dict(self):
        report = AnalysisReport(
            board_path="board.kicad_pcb",
            status="fail",
            exit_code=2,
            checks=[
                CheckResult(
                    name="Trace Width", display="0.12", color="red", violations=3
                ),
                CheckResult(
                    name="Annular Ring", display="0.15", color="gold", violations=1
                ),
            ],
            errors=["Failed to load"],
        )
        d = report.to_dict()
        assert d["board"] == "board.kicad_pcb"
        assert d["status"] == "fail"
        assert d["exit_code"] == 2
        assert len(d["checks"]) == 2
        assert d["checks"][0]["name"] == "Trace Width"
        assert d["checks"][0]["status"] == "fail"
        assert d["checks"][1]["status"] == "warn"
        assert d["errors"] == ["Failed to load"]

    def test_to_dict_is_json_serializable(self):
        report = AnalysisReport(
            board_path="board.kicad_pcb",
            checks=[
                CheckResult(name="Pads", display="正常", color="black", violations=0)
            ],
        )
        data = report.to_dict()
        json_str = json.dumps(data, ensure_ascii=False)
        assert "board.kicad_pcb" in json_str
        assert "正常" in json_str


class TestComputeStatus:
    def test_all_black_is_pass(self):
        report = AnalysisReport(
            board_path="x",
            checks=[
                CheckResult("a", "ok", "black"),
                CheckResult("b", "ok", "black"),
            ],
        )
        _compute_status(report)
        assert report.status == "pass"
        assert report.exit_code == 0

    def test_gold_is_warn(self):
        report = AnalysisReport(
            board_path="x",
            checks=[
                CheckResult("a", "ok", "black"),
                CheckResult("b", "warn", "gold"),
            ],
        )
        _compute_status(report)
        assert report.status == "warn"
        assert report.exit_code == 1

    def test_red_is_fail(self):
        report = AnalysisReport(
            board_path="x",
            checks=[
                CheckResult("a", "fail", "red"),
                CheckResult("b", "warn", "gold"),
            ],
        )
        _compute_status(report)
        assert report.status == "fail"
        assert report.exit_code == 2

    def test_red_overrides_gold(self):
        report = AnalysisReport(
            board_path="x",
            checks=[
                CheckResult("a", "fail", "red"),
                CheckResult("b", "warn", "gold"),
                CheckResult("c", "ok", "black"),
            ],
        )
        _compute_status(report)
        assert report.status == "fail"
        assert report.exit_code == 2


class TestRunAndCollect:
    def test_valid_result_dict(self):
        checks: list[CheckResult] = []
        _run_and_collect(
            checker=None,
            name="Test Check",
            result={
                "display": 0.5,
                "color": "gold",
                "check": [{"result": [{"a": 1}, {"a": 2}]}],
            },
            checks=checks,
        )
        assert len(checks) == 1
        assert checks[0].name == "Test Check"
        assert checks[0].color == "gold"
        assert checks[0].display == "0.5"
        assert checks[0].violations == 2

    def test_empty_result_string(self):
        checks: list[CheckResult] = []
        _run_and_collect(checker=None, name="Empty", result="", checks=checks)
        assert len(checks) == 1
        assert checks[0].color == "black"
        assert checks[0].violations == 0
        assert checks[0].display == "no data"
