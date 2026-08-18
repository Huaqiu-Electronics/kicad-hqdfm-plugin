import json
import os
import tempfile
import unittest
from unittest import mock

from kicad_dfm.core.models import DfmIssue, DfmSummary, Location
from kicad_dfm.services.analysis_cache import CachePayloadTooLarge
from kicad_dfm.services.analysis_cache import CACHE_MAX_PAYLOAD_BYTES
from kicad_dfm.services.analysis_cache import CACHE_MAX_TREE_NODES
from kicad_dfm.services.analysis_cache import CACHE_NAMESPACE
from kicad_dfm.services.analysis_cache import CACHE_VERSION
from kicad_dfm.services.analysis_cache import legacy_cache_path
from kicad_dfm.services.analysis_cache import load_analysis_cache
from kicad_dfm.services.analysis_cache import save_analysis_cache
from kicad_dfm.services.analysis_results import COMBINED
from kicad_dfm.services.analysis_results import CONTRACT_VERSION
from kicad_dfm.services.analysis_results import GERBER_STRICT
from kicad_dfm.services.analysis_results import KICAD_NATIVE
from kicad_dfm.services.analysis_results import SOURCE_VIEWS_SCHEMA
from kicad_dfm.services.analysis_results import SOURCE_VIEWS_SCHEMA_VERSION
from kicad_dfm.services.analysis_results import normalize_source_views


class AnalysisCacheTest(unittest.TestCase):
    def test_current_cache_schema_and_size_limit(self):
        self.assertEqual(23, CACHE_VERSION)
        self.assertEqual("analysis-cache-v23", CACHE_NAMESPACE)
        self.assertEqual(128 * 1024 * 1024, CACHE_MAX_PAYLOAD_BYTES)
        self.assertEqual(1000000, CACHE_MAX_TREE_NODES)

    def test_full_source_views_round_trip_with_identical_runtime_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            gerber_path = os.path.join(tmpdir, "F_Cu.gbr")
            with open(gerber_path, "w", encoding="ascii") as stream:
                stream.write("G04 test*")
            issue = DfmIssue(
                "Smallest Trace Width",
                "Trace Width",
                severity="error",
                location=Location(
                    item_id="track-1",
                    layer=["F.Cu"],
                    bbox_nm=(1, 2, 3, 4),
                ),
                raw={"point": (1.0, 2.0)},
            )
            live_source_views = normalize_source_views(
                {
                    KICAD_NATIVE: {
                        "analysis_result": {"native": {"check": []}},
                        "kicad_result": {"native": {"check": []}},
                        "issues": (issue,),
                        "summary": {
                            issue.category: DfmSummary(
                                issue.category,
                                display="1",
                                color="red",
                                issues=(issue,),
                            )
                        },
                        "profile": {"total_ms": 1.25},
                        "contract": {"mode": KICAD_NATIVE},
                        "input_paths": (),
                    },
                    GERBER_STRICT: {
                        "analysis_result": {"strict": {"check": []}},
                        "kicad_result": {"strict": {"check": []}},
                        "issues": (),
                        "summary": {},
                        "profile": {"files": 1},
                        "contract": {"mode": GERBER_STRICT},
                        "input_paths": (gerber_path,),
                        "export_summary": {
                            "Gerber Export": DfmSummary(
                                "Gerber Export", display="OK", color="black"
                            )
                        },
                    },
                }
            )
            saved_path = save_analysis_cache(
                board_path,
                "standard",
                COMBINED,
                {"combined": True},
                {"combined": True},
                (issue,),
                {},
                input_paths=(gerber_path,),
                contract={
                    "mode": COMBINED,
                    "source_views": {KICAD_NATIVE: {"contract_only": True}},
                },
                source_views=live_source_views,
            )
            loaded = load_analysis_cache(
                board_path,
                "standard",
                mode=COMBINED,
                input_paths=(gerber_path,),
            )
            with open(saved_path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)

        self.assertEqual(live_source_views, loaded["source_views"])
        self.assertEqual(SOURCE_VIEWS_SCHEMA, payload["source_views"]["schema"])
        self.assertEqual(
            SOURCE_VIEWS_SCHEMA_VERSION,
            payload["source_views"]["schema_version"],
        )
        self.assertEqual(
            {KICAD_NATIVE, GERBER_STRICT},
            set(payload["source_views"]["views"]),
        )
        self.assertNotIn("contract_only", loaded["source_views"][KICAD_NATIVE])

    def test_round_trip_restores_results_dataclasses_and_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            issue = DfmIssue(
                "Signal Integrity",
                "Dangling Tracks",
                severity="error",
                location=Location(item_id="track-1", layer=["F.Cu"]),
                raw={"point": (1.0, 2.0)},
            )
            summary = {
                "Signal Integrity": DfmSummary(
                    "Signal Integrity", display="1", color="red", issues=(issue,)
                )
            }
            contract = {"contract_version": CONTRACT_VERSION, "mode": KICAD_NATIVE}

            saved_path = save_analysis_cache(
                board_path,
                "standard",
                KICAD_NATIVE,
                {"Signal Integrity": {"display": 1}},
                {"Smallest Trace Width": ""},
                (issue,),
                summary,
                contract=contract,
            )
            loaded = load_analysis_cache(board_path, "standard", mode=KICAD_NATIVE)

        self.assertIn("analysis-cache-v23", saved_path)
        self.assertEqual(KICAD_NATIVE, loaded["mode"])
        self.assertEqual(contract, loaded["contract"])
        self.assertEqual(1, loaded["analysis_result"]["Signal Integrity"]["display"])
        self.assertIsInstance(loaded["issues"][0], DfmIssue)
        self.assertIsInstance(loaded["issues"][0].location, Location)
        self.assertEqual([1.0, 2.0], loaded["issues"][0].raw["point"])
        self.assertIsInstance(loaded["summary"]["Signal Integrity"], DfmSummary)

    def test_modes_coexist_without_overwriting_each_other(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            native_path = self.save_minimal(board_path, 1, KICAD_NATIVE)
            gerber_path = self.save_minimal(board_path, 2, GERBER_STRICT)

            native = load_analysis_cache(board_path, "standard", mode=KICAD_NATIVE)
            gerber = load_analysis_cache(board_path, "standard", mode=GERBER_STRICT)

        self.assertNotEqual(native_path, gerber_path)
        self.assertEqual(1, native["analysis_result"]["value"])
        self.assertEqual(2, gerber["analysis_result"]["value"])

    def test_default_load_falls_back_when_newer_combined_inputs_are_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path, 1, KICAD_NATIVE)
            gerber_path = os.path.join(tmpdir, "F_Cu.gbr")
            with open(gerber_path, "w", encoding="ascii") as stream:
                stream.write("G04 cache input*")
            self.save_minimal(
                board_path,
                2,
                COMBINED,
                input_paths=(gerber_path,),
            )
            os.remove(gerber_path)

            loaded = load_analysis_cache(board_path, "standard")

        self.assertEqual(KICAD_NATIVE, loaded["mode"])
        self.assertEqual(1, loaded["analysis_result"]["value"])

    def test_unchanged_inputs_restore_without_rehashing_source_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path)

            with mock.patch(
                "kicad_dfm.services.analysis_cache.input_signature_from_manifest",
                side_effect=AssertionError("unchanged cache inputs were rehashed"),
            ):
                loaded = load_analysis_cache(
                    board_path,
                    "standard",
                    mode=KICAD_NATIVE,
                )

        self.assertIsNotNone(loaded)

    def test_default_limit_persists_results_larger_than_legacy_16_mib_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            payload = "x" * (17 * 1024 * 1024)

            path = save_analysis_cache(
                board_path,
                "standard",
                KICAD_NATIVE,
                {"payload": payload},
                {},
                (),
                {},
            )
            loaded = load_analysis_cache(
                board_path,
                "standard",
                mode=KICAD_NATIVE,
            )
            saved_size = os.path.getsize(path)

        self.assertGreater(saved_size, 16 * 1024 * 1024)
        self.assertEqual(len(payload), len(loaded["analysis_result"]["payload"]))

    def test_changed_board_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path)
            with open(board_path, "a", encoding="utf-8") as stream:
                stream.write("changed")

            loaded = load_analysis_cache(board_path, "standard", mode=KICAD_NATIVE)

        self.assertIsNone(loaded)

    def test_changed_export_input_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            gerber_path = os.path.join(tmpdir, "F_Cu.gbr")
            with open(gerber_path, "w", encoding="ascii") as stream:
                stream.write("first")
            self.save_minimal(board_path, mode=COMBINED, input_paths=(gerber_path,))
            with open(gerber_path, "w", encoding="ascii") as stream:
                stream.write("second")

            loaded = load_analysis_cache(
                board_path,
                "standard",
                mode=COMBINED,
                input_paths=(gerber_path,),
            )

        self.assertIsNone(loaded)

    def test_timestamp_only_change_keeps_content_addressed_cache_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path)
            stat = os.stat(board_path)
            os.utime(board_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))

            loaded = load_analysis_cache(board_path, "standard", mode=KICAD_NATIVE)

        self.assertIsNotNone(loaded)

    def test_different_rules_do_not_load_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path, rules={"Hole Size": ({"rule": "0.2"},)})

            loaded = load_analysis_cache(
                board_path,
                "standard",
                mode=KICAD_NATIVE,
                rules={"Hole Size": ({"rule": "0.3"},)},
            )

        self.assertIsNone(loaded)

    def test_different_rule_profile_does_not_load_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path)

            loaded = load_analysis_cache(board_path, "precision", mode=KICAD_NATIVE)

        self.assertIsNone(loaded)

    def test_different_language_does_not_load_localized_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path, language="English")

            loaded = load_analysis_cache(
                board_path,
                "standard",
                "简体中文",
                mode=KICAD_NATIVE,
            )

        self.assertIsNone(loaded)

    def test_different_contract_version_does_not_load_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path)

            loaded = load_analysis_cache(
                board_path,
                "standard",
                mode=KICAD_NATIVE,
                contract_version=CONTRACT_VERSION + 1,
            )

        self.assertIsNone(loaded)

    def test_previous_version_payload_is_not_a_current_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            path = legacy_cache_path(board_path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "version": CACHE_VERSION - 1,
                        "profile_id": "standard",
                        "mode": "offline",
                        "analysis_result": {"stale": True},
                        "kicad_result": {},
                    },
                    stream,
                )

            loaded = load_analysis_cache(board_path, "standard")

        self.assertIsNone(loaded)

    def test_second_save_atomically_replaces_same_cache_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            first_path = self.save_minimal(board_path, value=1)
            second_path = self.save_minimal(board_path, value=2)
            loaded = load_analysis_cache(board_path, "standard", mode=KICAD_NATIVE)

        self.assertEqual(first_path, second_path)
        self.assertEqual(2, loaded["analysis_result"]["value"])
        self.assertFalse(os.path.exists(second_path + ".tmp"))

    def test_size_limit_skips_candidate_before_json_decode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            self.save_minimal(board_path)

            with mock.patch(
                "kicad_dfm.services.analysis_cache.json.load"
            ) as decoder:
                loaded = load_analysis_cache(
                    board_path,
                    "standard",
                    mode=KICAD_NATIVE,
                    max_payload_bytes=1,
                )

        self.assertIsNone(loaded)
        decoder.assert_not_called()

    def test_requested_oversized_mode_does_not_fall_back_to_other_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            native_path = self.save_minimal(board_path, 1, KICAD_NATIVE)
            combined_path = self.save_minimal(board_path, 2, COMBINED)
            limit = os.path.getsize(native_path) + 64
            with open(combined_path, "a", encoding="utf-8") as stream:
                stream.write(" " * (limit + 1))

            loaded = load_analysis_cache(
                board_path,
                "standard",
                mode=COMBINED,
                max_payload_bytes=limit,
            )

        self.assertIsNone(loaded)

    def test_oversized_save_is_rejected_before_payload_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            with (
                mock.patch(
                    "kicad_dfm.services.analysis_cache.json_value",
                    side_effect=AssertionError("payload was copied before rejection"),
                ),
                self.assertRaises(CachePayloadTooLarge),
            ):
                save_analysis_cache(
                    board_path,
                    "standard",
                    COMBINED,
                    {"blob": "x" * 4096},
                    {},
                    (),
                    {},
                    max_payload_bytes=512,
                )

            cache_dir = os.path.join(tmpdir, "HQDMF")
            self.assertFalse(os.path.exists(cache_dir))

    def test_structurally_complex_save_is_rejected_before_payload_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            with (
                mock.patch(
                    "kicad_dfm.services.analysis_cache.json_value",
                    side_effect=AssertionError("payload was copied before rejection"),
                ),
                self.assertRaises(CachePayloadTooLarge),
            ):
                save_analysis_cache(
                    board_path,
                    "standard",
                    COMBINED,
                    {"values": list(range(20))},
                    {},
                    (),
                    {},
                    max_payload_bytes=1024 * 1024,
                    max_tree_nodes=10,
                )

            self.assertFalse(os.path.exists(os.path.join(tmpdir, "HQDMF")))

    def test_encoded_size_limit_removes_partial_cache_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board_path = self.make_board(tmpdir)
            with self.assertRaises(CachePayloadTooLarge):
                save_analysis_cache(
                    board_path,
                    "standard",
                    COMBINED,
                    {"blob": "\\" * 1000},
                    {},
                    (),
                    {},
                    max_payload_bytes=1500,
                )

            cache_dir = os.path.join(tmpdir, "HQDMF")
            files = []
            if os.path.isdir(cache_dir):
                files = [
                    os.path.join(root, name)
                    for root, _directories, names in os.walk(cache_dir)
                    for name in names
                ]
            self.assertEqual([], files)

    @staticmethod
    def make_board(tmpdir):
        path = os.path.join(tmpdir, "board.kicad_pcb")
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("(kicad_pcb)")
        return path

    @staticmethod
    def save_minimal(
        board_path,
        value=1,
        mode=KICAD_NATIVE,
        input_paths=(),
        rules=None,
        language="",
    ):
        return save_analysis_cache(
            board_path,
            "standard",
            mode,
            {"value": value},
            {},
            (),
            {},
            language,
            input_paths=input_paths,
            rules=rules,
        )


if __name__ == "__main__":
    unittest.main()
