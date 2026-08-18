import unittest
from unittest import mock

from kicad_dfm.core.progress import AnalysisCancelled
from kicad_dfm.services.export_checks import ExportChecks
from kicad_dfm.services.offline_analysis import ANALYSIS_CHECKS, LOCAL_CHECKS, OfflineDfmAnalysis


class FakeLocalChecks:
    calls = []

    def __init__(self, *_args, **_kwargs):
        self.issues = []

    def __getattr__(self, name):
        def run(_analysis_result):
            self.calls.append(name)
            return {"display": 0, "color": "black", "check": []}

        return run

    def set_heartbeat(self, heartbeat):
        self.heartbeat = heartbeat


class AnalysisProgressTest(unittest.TestCase):
    def setUp(self):
        FakeLocalChecks.calls = []

    def test_offline_progress_reports_each_rule_and_completion(self):
        updates = []
        with mock.patch(
            "kicad_dfm.services.offline_analysis.LocalChecks",
            FakeLocalChecks,
        ):
            OfflineDfmAnalysis(object(), {}).analyze(
                lambda completed, total, item: updates.append(
                    (completed, total, item)
                )
            )

        self.assertEqual("Preparing board data", updates[0][2])
        self.assertEqual([category for category, _method in ANALYSIS_CHECKS], [
            item for _completed, _total, item in updates[1:-1]
        ])
        self.assertEqual("Finalizing results", updates[-1][2])
        self.assertEqual(updates[-1][1], updates[-1][0])

    def test_offline_stop_prevents_remaining_rules(self):
        def progress(_completed, _total, item):
            return item != LOCAL_CHECKS[1][0]

        with mock.patch(
            "kicad_dfm.services.offline_analysis.LocalChecks",
            FakeLocalChecks,
        ):
            with self.assertRaises(AnalysisCancelled):
                OfflineDfmAnalysis(object(), {}).analyze(progress)

        self.assertEqual([LOCAL_CHECKS[0][1]], FakeLocalChecks.calls)

    def test_export_stop_prevents_remaining_phases(self):
        checks = ExportChecks(None)
        calls = []
        checks._check_output_dir = lambda: calls.append("directory")
        checks._check_files = lambda: calls.append("files")
        checks._check_zip = lambda: calls.append("zip")
        checks._scan_outputs = lambda: calls.append("scan")

        with self.assertRaises(AnalysisCancelled):
            checks.analyze(
                lambda _completed, _total, item: item != "Checking exported files"
            )

        self.assertEqual(["directory"], calls)


if __name__ == "__main__":
    unittest.main()
