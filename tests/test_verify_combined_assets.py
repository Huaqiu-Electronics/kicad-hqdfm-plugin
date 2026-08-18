import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from tools import verify_combined_assets as verifier


class VerifyCombinedAssetsTest(unittest.TestCase):
    @staticmethod
    def verification_args(assets_dir, gerber_source):
        return types.SimpleNamespace(
            assets_dir=str(assets_dir),
            skip_native=True,
            skip_slow=False,
            skip_gerber=False,
            gerber_source=gerber_source,
            skip_temp_export=False,
            kicad_python="kicad-python",
            profile="standard",
            load_timeout=1.0,
            native_timeout=1.0,
            gerber_timeout=1.0,
            repo=str(verifier.REPO_ROOT),
            contract_dir=None,
            skip_combined=True,
        )

    def test_worker_timeout_keeps_the_load_board_phase(self):
        calls = []

        def timeout_runner(command, **kwargs):
            calls.append((command, kwargs))
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        result = verifier.run_worker_phase(
            "kicad-python",
            verifier.LOAD_BOARD,
            ("--board", "example.kicad_pcb"),
            1.25,
            runner=timeout_runner,
        )

        self.assertEqual("timeout", result["status"])
        self.assertEqual("load_board", result["phase"])
        self.assertEqual(1.25, result["timeout_seconds"])
        self.assertIn("--worker-phase", calls[0][0])
        self.assertEqual(1.25, calls[0][1]["timeout"])

    def test_confirmed_video_gates_accept_physical_gerber_rows(self):
        native = {
            "categories": {
                "Signal Integrity": {
                    "rows": 3,
                    "items": {
                        "Acute Angle Traces": 3,
                    },
                }
            }
        }
        gerber = {
            "holes_on_smd": {
                "physical_rows": 13,
                "nonconductor_related_rows": 0,
            },
            "blocking_export_issue_count": 0,
        }
        combined = {"source_modes": ["kicad_native", "gerber_strict"]}

        gates = verifier.evaluate_gates("video", native, gerber, combined)

        self.assertTrue(gates)
        self.assertTrue(all(gate["status"] == "passed" for gate in gates))

    def test_confirmed_amulet_gate_requires_all_six_layer_measurements(self):
        native = {
            "categories": {
                "Signal Integrity": {
                    "rows": 0,
                    "items": {},
                }
            }
        }
        layer_counts = {
            layer: 1253 for layer in verifier.AMULET_COPPER_LAYERS
        }
        gerber = {
            "ring_evidence": {
                "physical_rows": 1253,
                "rows_with_per_layer_measurements": 1253,
                "rows_with_matching_physical_measurement_count": 1253,
                "per_layer_measurement_total": 7518,
                "measurement_layers": layer_counts,
                "rows_covering_all_amulet_copper_layers": 1253,
            },
            "blocking_export_issue_count": 0,
        }

        gates = verifier.evaluate_gates(
            "amulet",
            native_summary=native,
            gerber_summary=gerber,
        )

        self.assertTrue(all(gate["status"] == "passed" for gate in gates))

    def test_amulet_gate_rejects_regression_of_signal_false_positives(self):
        native = {
            "categories": {
                "Signal Integrity": {
                    "rows": 1,
                    "items": {"Unconnected Vias": 1},
                }
            }
        }

        gates = verifier.evaluate_gates("amulet", native_summary=native)
        signal_gate = next(
            gate
            for gate in gates
            if gate["name"] == "amulet_native_signal_rows"
        )

        self.assertEqual("failed", signal_gate["status"])

    def test_skip_native_existing_gerber_skips_load_board_and_runs_strict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "assets"
            assets_dir.mkdir()
            board = assets_dir / verifier.ASSETS["flat"]
            board.write_text("board", encoding="utf-8")
            verifier.existing_gerber_dir(assets_dir, board).mkdir(parents=True)
            args = self.verification_args(assets_dir, "existing")
            calls = []

            def run_phase(_python, phase, _worker_args, _timeout, **_kwargs):
                calls.append(phase)
                return {
                    "status": "completed",
                    "phase": phase,
                    "summary": {
                        "categories": {},
                        "blocking_export_issue_count": 0,
                    },
                }

            with mock.patch.object(verifier, "run_worker_phase", side_effect=run_phase):
                result = verifier.verify_asset(args, "flat", Path(temp_dir) / "work")

        self.assertEqual([verifier.GERBER_STRICT], calls)
        self.assertEqual("skipped", result["phases"][verifier.LOAD_BOARD]["status"])
        self.assertIn(
            "does not require load_board",
            result["phases"][verifier.LOAD_BOARD]["reason"],
        )
        self.assertEqual(
            "completed", result["phases"][verifier.GERBER_STRICT]["status"]
        )

    def test_skip_native_temporary_export_still_requires_load_board(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "assets"
            assets_dir.mkdir()
            (assets_dir / verifier.ASSETS["flat"]).write_text(
                "board", encoding="utf-8"
            )
            args = self.verification_args(assets_dir, "export")
            calls = []

            def run_phase(_python, phase, _worker_args, _timeout, **_kwargs):
                calls.append(phase)
                if phase == verifier.LOAD_BOARD:
                    return {
                        "status": "completed",
                        "phase": phase,
                        "summary": {
                            "board_thickness_mm": 1.6,
                            "copper_layer_count": 2,
                        },
                    }
                return {
                    "status": "completed",
                    "phase": phase,
                    "summary": {
                        "categories": {},
                        "blocking_export_issue_count": 0,
                    },
                }

            with mock.patch.object(verifier, "run_worker_phase", side_effect=run_phase):
                result = verifier.verify_asset(args, "flat", Path(temp_dir) / "work")

        self.assertEqual([verifier.LOAD_BOARD, verifier.GERBER_STRICT], calls)
        self.assertEqual("completed", result["phases"][verifier.LOAD_BOARD]["status"])

    def test_output_write_failure_prints_complete_json_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            stderr = io.StringIO()
            argv = [
                "--repo",
                str(verifier.REPO_ROOT),
                "--assets-dir",
                str(Path(temp_dir) / "assets"),
                "--assets",
                "pic",
                "--kicad-python",
                sys.executable,
                "--output",
                str(Path(temp_dir) / "result.json"),
                "--compact",
            ]
            asset_result = {
                "asset": "pic",
                "status": "passed",
                "phases": {},
                "gates": [],
            }
            with (
                mock.patch.object(verifier, "verify_asset", return_value=asset_result),
                mock.patch.object(
                    verifier.Path,
                    "write_text",
                    side_effect=PermissionError("write denied"),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = verifier.parent_main(argv)

        report = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertEqual("verify_combined_assets", report["tool"])
        self.assertEqual("passed", report["assets"]["pic"]["status"])
        self.assertIn("Unable to write --output", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
