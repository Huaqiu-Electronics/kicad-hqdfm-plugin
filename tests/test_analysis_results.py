import unittest

from kicad_dfm.core.models import DfmIssue, DfmSummary
from kicad_dfm.services.analysis_results import COMBINED
from kicad_dfm.services.analysis_results import CombinedAnalysisService
from kicad_dfm.services.analysis_results import GERBER_ENRICHED
from kicad_dfm.services.analysis_results import GERBER_STRICT
from kicad_dfm.services.analysis_results import KICAD_NATIVE
from kicad_dfm.services.analysis_results import AnalysisStageResult
from kicad_dfm.services.analysis_results import build_analysis_contract
from kicad_dfm.services.analysis_results import merge_analysis_contracts
from kicad_dfm.services.analysis_results import merge_legacy_analysis_views
from kicad_dfm.services.analysis_results import normalize_smd_spacing_results
from kicad_dfm.services.analysis_results import source_finding_key
from kicad_dfm.services.analysis_results import stable_finding_key


class AnalysisResultContractTest(unittest.TestCase):
    def test_legacy_smd_rows_and_summary_move_to_independent_category(self):
        old_rule = "smallesttracespacing:smdpadspacing"
        result = normalize_smd_spacing_results(
            {
                "Smallest Trace Spacing": {
                    "execution_status": "completed",
                    "checked_count": 12,
                    "available_count": 12,
                    "violation_count": 2,
                    "displayed_count": 2,
                    "check": [{"result": [
                        {
                            "id": "trace-pair",
                            "item": "Trace Spacing",
                            "rule_key": "smallesttracespacing:tracespacing",
                            "value": "0.14",
                            "color": "red",
                        },
                        {
                            "id": "smd-pair",
                            "item": "SMD Pad Spacing",
                            "rule_key": old_rule,
                            "value": "0.18",
                            "color": "gold",
                        },
                    ]}],
                    "item_summaries": {
                        "smallesttracespacing:tracespacing": {
                            "item": "Trace Spacing",
                            "checked_count": 7,
                            "available_count": 7,
                            "violation_count": 1,
                            "displayed_count": 1,
                        },
                        old_rule: {
                            "item": "SMD Pad Spacing",
                            "rule_key": old_rule,
                            "checked_count": 5,
                            "available_count": 5,
                            "violation_count": 1,
                            "displayed_count": 1,
                        },
                    },
                }
            }
        )

        old = result["Smallest Trace Spacing"]
        smd = result["SMD Spacing"]
        self.assertEqual(7, old["checked_count"])
        self.assertEqual(["Trace Spacing"], [row["item"] for row in old["check"][0]["result"]])
        self.assertEqual(5, smd["checked_count"])
        row = smd["check"][0]["result"][0]
        self.assertEqual("smdspacing:smdpadspacing", row["rule_key"])
        self.assertEqual(
            {"smdspacing:smdpadspacing"},
            set(smd["item_summaries"]),
        )

    def test_contract_distinguishes_not_computed_from_completed_zero_findings(self):
        contract = build_analysis_contract(
            KICAD_NATIVE,
            {
                "Computed": {"display": "OK", "check": [], "color": "black"},
                "Missing": "",
            },
            categories=("Computed", "Missing"),
        )

        computed = contract["categories"]["Computed"]
        missing = contract["categories"]["Missing"]
        self.assertEqual("completed", computed["execution_status"])
        self.assertEqual("passed", computed["result_status"])
        self.assertEqual(0, computed["violation_count"])
        self.assertEqual(0, computed["displayed_count"])
        self.assertEqual("not_computed", missing["execution_status"])

    def test_contract_exposes_checked_violation_and_displayed_counts(self):
        result = {
            "Category": {
                "checked_count": 12,
                "check": [
                    {
                        "result": [
                            {"id": "uuid-a", "item": "Rule A", "color": "red"},
                            {"id": "uuid-b", "item": "Rule A", "color": "black"},
                        ]
                    }
                ],
            }
        }

        category = build_analysis_contract(KICAD_NATIVE, result)["categories"]["Category"]

        self.assertEqual(12, category["checked_count"])
        self.assertEqual(1, category["violation_count"])
        self.assertEqual(2, category["displayed_count"])
        self.assertEqual("provided", category["count_basis"]["checked"])

    def test_stable_key_ignores_measurement_but_preserves_layer_by_default(self):
        native = {
            "id": "ABC-UUID",
            "related_id": "DEF-UUID",
            "layer": ["F.Cu"],
            "item": "Trace Spacing",
            "rule_key": "smallesttracespacing:tracespacing",
            "value": "0.12",
            "color": "red",
        }
        gerber = dict(
            native,
            value="0.119998",
            color="gold",
            source="gerber",
        )

        self.assertEqual(
            stable_finding_key("Smallest Trace Spacing", native),
            stable_finding_key("Smallest Trace Spacing", gerber),
        )
        self.assertNotEqual(
            stable_finding_key("Smallest Trace Spacing", native),
            stable_finding_key(
                "Smallest Trace Spacing", dict(gerber, layer=["B.Cu"])
            ),
        )

    def test_explicit_physical_aggregation_can_merge_across_layers(self):
        first = {
            "id": "via-uuid",
            "item": "PTH Annular Ring",
            "rule_key": "ringhole:pthannularring",
            "layer": ["F.Cu"],
            "raw": {
                "physical_measurement_count": 2,
                "per_layer_measurements": [{"layer": "F.Cu"}, {"layer": "B.Cu"}],
            },
        }
        second = dict(first, layer=["B.Cu"])

        self.assertEqual(
            stable_finding_key("RingHole", first),
            stable_finding_key("RingHole", second),
        )

    def test_single_measurement_marker_does_not_discard_layer_identity(self):
        first = {
            "id": "zone-uuid",
            "item": "Copper-to-Board Edge",
            "rule_key": "coppertoboardedge:coppertoboardedge",
            "layer": ["F.Cu"],
            "raw": {
                "physical_measurement_count": 1,
                "per_layer_measurements": [{"layer": ["F.Cu"]}],
            },
        }
        second = dict(first, layer=["B.Cu"])

        self.assertNotEqual(
            stable_finding_key("Copper-to-Board Edge", first),
            stable_finding_key("Copper-to-Board Edge", second),
        )

    def test_same_layer_contours_do_not_discard_layer_identity(self):
        first = {
            "id": "zone-uuid",
            "item": "Copper-to-Board Edge",
            "rule_key": "coppertoboardedge:coppertoboardedge",
            "layer": ["F.Cu"],
            "raw": {
                "physical_measurement_count": 2,
                "per_layer_measurements": [
                    {"layer": ["F.Cu"]},
                    {"layer": ["F.Cu"]},
                ],
            },
        }
        second = dict(first, layer=["B.Cu"])

        self.assertNotEqual(
            stable_finding_key("Copper-to-Board Edge", first),
            stable_finding_key("Copper-to-Board Edge", second),
        )

    def test_native_pth_and_cross_layer_gerber_edge_rows_share_stable_key(self):
        native = {
            "id": "pth-pad-uuid",
            "item": "Copper-to-Board Edge",
            "rule_key": "coppertoboardedge:coppertoboardedge",
            "item_type": "PAD",
            "layer": ["F.Cu"],
        }
        enriched = {
            "id": "pth-pad-uuid",
            "item": "Copper-to-Board Edge",
            "rule_key": "coppertoboardedge:coppertoboardedge",
            "item_type": "gerber",
            "layer": ["F.Cu", "In1.Cu", "B.Cu"],
            "raw": {
                "primary": {"through_hole": True},
                "uuid_mapping": {
                    "status": "matched",
                    "id": "pth-pad-uuid",
                },
                "physical_measurement_count": 3,
                "per_layer_measurements": [
                    {"layer": ["F.Cu"]},
                    {"layer": ["In1.Cu"]},
                    {"layer": ["B.Cu"]},
                ],
            },
        }

        self.assertEqual(
            stable_finding_key("Copper-to-Board Edge", native),
            stable_finding_key("Copper-to-Board Edge", enriched),
        )

    def test_board_edge_location_witness_does_not_split_engine_identity(self):
        native = {
            "id": "zone-uuid",
            "item": "Copper-to-Board Edge",
            "rule_key": "coppertoboardedge:coppertoboardedge",
            "item_type": "ZONE",
            "layer": ["F.Cu"],
        }
        enriched = dict(
            native,
            item_type="gerber",
            related_id="edge-cuts-shape-uuid",
            related_layer="Edge.Cuts",
            raw={
                "uuid_mapping": {"status": "matched", "id": "zone-uuid"},
                "related": {"kind": "board_edge"},
            },
        )

        self.assertEqual(
            stable_finding_key("Copper-to-Board Edge", native),
            stable_finding_key("Copper-to-Board Edge", enriched),
        )

    def test_same_uuid_on_two_layers_survives_legacy_union(self):
        category = "Smallest Trace Width"
        base = {
            "id": "track-uuid",
            "item": "Trace Width",
            "rule_key": "smallesttracewidth:tracewidth",
            "color": "red",
        }
        left = {
            category: {
                "check": [{"result": [dict(base, layer=["F.Cu"])]}],
                "color": "red",
            }
        }
        right = {
            category: {
                "check": [{"result": [dict(base, layer=["B.Cu"])]}],
                "color": "red",
            }
        }

        merged = merge_legacy_analysis_views(left, right)
        rows = [
            row
            for check in merged[category]["check"]
            for row in check["result"]
        ]

        self.assertEqual(2, len(rows))
        self.assertEqual({("F.Cu",), ("B.Cu",)}, {tuple(row["layer"]) for row in rows})

    def test_legacy_union_recomputes_counts_and_item_summaries(self):
        category = "Category"
        rule = "category:rule-a"
        shared = {
            "id": "shared",
            "item": "Rule A",
            "rule_key": rule,
            "layer": ["F.Cu"],
            "value": "0.10",
            "color": "black",
        }
        native = {
            category: {
                "checked_count": 10,
                "violation_count": 99,
                "displayed_count": 99,
                "check": [
                    {
                        "result": [
                            shared,
                            dict(shared, id="native-only", value="0.20", color="black"),
                        ]
                    }
                ],
                "item_summaries": {
                    rule: {"checked_count": 7, "available_count": 7, "unit": "mm"}
                },
                "color": "red",
            }
        }
        gerber = {
            category: {
                "checked_count": 20,
                "violation_count": 77,
                "displayed_count": 77,
                "check": [
                    {
                        "result": [
                            dict(shared, value="0.099", color="red"),
                            dict(shared, id="gerber-only", value="0.30", color="gold"),
                        ]
                    }
                ],
                "item_summaries": {
                    "Rule A": {
                        "item": "Rule A",
                        "checked_count": 11,
                        "available_count": 11,
                        "unit": "mm",
                    }
                },
                "color": "gold",
            }
        }

        merged = merge_legacy_analysis_views(native, gerber)[category]

        self.assertEqual(30, merged["checked_count"])
        self.assertEqual(3, merged["displayed_count"])
        self.assertEqual(2, merged["violation_count"])
        item_summary = merged["item_summaries"][rule]
        self.assertEqual(18, item_summary["checked_count"])
        self.assertEqual(3, item_summary["displayed_count"])
        self.assertEqual(2, item_summary["violation_count"])

    def test_combined_slot_aspect_ratio_summary_keeps_the_minimum_ratio(self):
        category = "Hole Size"
        rule = "holesize:slotaspectratio"
        native = {
            category: {
                "check": [{"result": [{
                    "id": "native-slot",
                    "item": "Slot Aspect Ratio",
                    "rule_key": rule,
                    "value": "3.0",
                    "color": "black",
                }]}],
            }
        }
        gerber = {
            category: {
                "check": [{"result": [{
                    "id": "gerber-slot",
                    "item": "Slot Aspect Ratio",
                    "rule_key": rule,
                    "value": "1.75",
                    "color": "gold",
                }]}],
            }
        }

        merged = merge_legacy_analysis_views(native, gerber)[category]

        self.assertEqual(1.75, merged["item_summaries"][rule]["display"])

    def test_legacy_union_excludes_enrichment_from_strict_checked_count(self):
        category = "Category"
        row = {
            "id": "board-PTH.drl",
            "finding_key": "evidence-1",
            "item": "Rule",
            "rule_key": "category:rule",
            "layer": ["Drill"],
            "color": "red",
        }
        strict = {category: {"checked_count": 20, "check": [{"result": [row]}]}}
        enriched = {
            category: {
                "checked_count": 20,
                "check": [{"result": [dict(row, id="via-uuid")]}],
            }
        }

        merged = merge_legacy_analysis_views(
            strict,
            enriched,
            GERBER_STRICT,
            GERBER_ENRICHED,
        )[category]

        self.assertEqual(20, merged["checked_count"])
        self.assertEqual(2, merged["displayed_count"])

    def test_merged_contract_uses_combined_mode_and_keeps_source_observations(self):
        row = {"id": "uuid-a", "item": "Smallest Drill Size", "color": "red"}
        legacy = {"Hole Size": {"display": 0.2, "color": "red", "check": [{"result": [row]}]}}
        native = build_analysis_contract(KICAD_NATIVE, legacy)
        gerber = build_analysis_contract(GERBER_ENRICHED, legacy)

        merged = merge_analysis_contracts(native, gerber)

        self.assertEqual(COMBINED, merged["mode"])
        finding = merged["categories"]["Hole Size"]["findings"][0]
        self.assertEqual([KICAD_NATIVE, GERBER_ENRICHED], finding["source_modes"])
        self.assertEqual({KICAD_NATIVE, GERBER_ENRICHED}, set(merged["source_views"]))
        native["metadata"]["mutated_after_merge"] = True
        self.assertNotIn(
            "mutated_after_merge",
            merged["source_views"][KICAD_NATIVE]["metadata"],
        )

    def test_normalizing_source_views_twice_keeps_independent_snapshots(self):
        from kicad_dfm.services.analysis_results import normalize_source_views

        normalized = normalize_source_views(
            {
                KICAD_NATIVE: {
                    "analysis_result": {"Category": {"check": []}},
                    "issues": (),
                }
            }
        )

        repeated = normalize_source_views(normalized)

        self.assertEqual(normalized, repeated)
        self.assertIsNot(
            normalized[KICAD_NATIVE],
            repeated[KICAD_NATIVE],
        )
        repeated[KICAD_NATIVE]["analysis_result"]["Category"]["check"].append(
            {"result": []}
        )
        self.assertEqual(
            [],
            normalized[KICAD_NATIVE]["analysis_result"]["Category"]["check"],
        )

    def test_normalizing_source_views_canonicalizes_alias_keys(self):
        from kicad_dfm.services.analysis_results import normalize_source_views

        normalized = normalize_source_views(
            {
                "native": {
                    "source_view_schema_version": 1,
                    "mode": KICAD_NATIVE,
                    "analysis_result": {},
                }
            }
        )

        self.assertEqual({KICAD_NATIVE}, set(normalized))

    def test_source_alias_bridges_strict_enriched_and_native_identities(self):
        category = "Hole Size"
        strict_row = {
            "id": "board-PTH.drl",
            "finding_key": "immutable-export-evidence",
            "item": "Smallest Drill Size",
            "rule_key": "holesize:smallestdrillsize",
            "source": "drill",
            "color": "red",
            "raw": {"point": (1.0, 2.0)},
        }
        enriched_row = dict(strict_row, id="via-uuid")
        native_row = {
            "id": "via-uuid",
            "item": "Smallest Drill Size",
            "rule_key": "holesize:smallestdrillsize",
            "source": "kicad",
            "color": "red",
        }

        self.assertNotEqual(
            stable_finding_key(category, strict_row),
            stable_finding_key(category, enriched_row),
        )
        self.assertEqual(
            source_finding_key(category, strict_row),
            source_finding_key(category, enriched_row),
        )
        contracts = []
        for mode, row, checked_count in (
            (KICAD_NATIVE, native_row, 10),
            (GERBER_STRICT, strict_row, 20),
            (GERBER_ENRICHED, enriched_row, 20),
        ):
            contracts.append(
                build_analysis_contract(
                    mode,
                    {
                        category: {
                            "check": [{"result": [row]}],
                            "color": "red",
                            "checked_count": checked_count,
                        }
                    },
                )
            )

        merged = merge_analysis_contracts(*contracts)

        findings = merged["categories"][category]["findings"]
        self.assertEqual(1, len(findings))
        self.assertEqual(
            [KICAD_NATIVE, GERBER_STRICT, GERBER_ENRICHED],
            findings[0]["source_modes"],
        )
        native_key = contracts[0]["categories"][category]["findings"][0]["key"]
        self.assertEqual(native_key, findings[0]["key"])
        self.assertEqual(30, merged["categories"][category]["checked_count"])
        self.assertEqual(
            [KICAD_NATIVE, GERBER_ENRICHED],
            merged["categories"][category]["counted_source_modes"],
        )

    def test_combined_contract_uses_enriched_verdict_and_retains_strict_source_view(self):
        category = "Smallest Trace Spacing"
        strict_row = {
            "id": "board-F_Cu.gbr",
            "finding_key": "gerber-net-tie-contact",
            "item": "SMD Pad Spacing",
            "rule_key": "smallesttracespacing:smdpadspacing",
            "source": "gerber",
            "layer": ["F.Cu"],
            "value": "0.0",
            "color": "red",
            "raw": {"segment": ((1.0, 1.0), (1.0, 1.0))},
        }
        strict = build_analysis_contract(
            GERBER_STRICT,
            {
                category: {
                    "execution_status": "completed",
                    "checked_count": 1,
                    "violation_count": 1,
                    "displayed_count": 1,
                    "check": [{"result": [strict_row]}],
                }
            },
        )
        enriched = build_analysis_contract(
            GERBER_ENRICHED,
            {
                category: {
                    "execution_status": "completed",
                    "checked_count": 1,
                    "violation_count": 0,
                    "displayed_count": 0,
                    "suppressed_count": 1,
                    "check": [],
                }
            },
        )

        merged = merge_analysis_contracts(strict, enriched)

        result = merged["categories"][category]
        self.assertEqual([GERBER_ENRICHED], result["counted_source_modes"])
        self.assertEqual([], result["findings"])
        self.assertEqual(0, result["violation_count"])
        self.assertEqual(0, result["displayed_count"])
        self.assertEqual("passed", result["result_status"])
        self.assertEqual(
            {GERBER_STRICT, GERBER_ENRICHED},
            set(merged["source_views"]),
        )
        self.assertEqual(
            1,
            merged["source_views"][GERBER_STRICT]["categories"][category][
                "violation_count"
            ],
        )

    def test_combined_service_runs_native_then_gerber_and_unions_rows(self):
        calls = []
        native_row = {"id": "uuid-a", "item": "Rule", "color": "red", "value": "0.1"}
        gerber_row = {"id": "uuid-a", "item": "Rule", "color": "gold", "value": "0.099"}

        def native_runner():
            calls.append(KICAD_NATIVE)
            return AnalysisStageResult(
                KICAD_NATIVE,
                {"Category": {"display": 0.1, "color": "red", "check": [{"result": [native_row]}]}},
            )

        def gerber_runner():
            calls.append(GERBER_ENRICHED)
            return AnalysisStageResult(
                GERBER_ENRICHED,
                {"Category": {"display": 0.099, "color": "gold", "check": [{"result": [gerber_row]}]}},
            )

        result = CombinedAnalysisService(native_runner, gerber_runner).run()

        self.assertEqual([KICAD_NATIVE, GERBER_ENRICHED], calls)
        self.assertEqual(COMBINED, result.contract["mode"])
        rows = result.analysis_result["Category"]["check"]
        self.assertEqual(1, len(rows))
        merged_row = rows[0]["result"][0]
        self.assertEqual([KICAD_NATIVE, GERBER_ENRICHED], merged_row["_source_modes"])

    def test_combined_summary_contains_gerber_only_dfm_issue_not_package_issue(self):
        category = "Smallest Trace Width"
        gerber_row = {
            "id": "board-CuTop.gbr",
            "item": "Trace Width",
            "rule_key": "smallesttracewidth:tracewidth",
            "layer": ["F.Cu"],
            "value": "0.08",
            "rule": "0.1,0.12,0.15",
            "color": "red",
            "raw": {"point": [1.25, 2.5], "measurement_basis": "gerber"},
        }
        package_issue = DfmIssue(
            "Gerber Export",
            "Missing Layer File",
            severity="error",
            message="missing layer",
        )
        package_summary = DfmSummary(
            "Gerber Export", display="1 error(s)", color="red", issues=(package_issue,)
        )

        result = CombinedAnalysisService(
            lambda: AnalysisStageResult(
                KICAD_NATIVE,
                {category: {"check": [], "color": "black"}},
            ),
            lambda: AnalysisStageResult(
                GERBER_ENRICHED,
                {category: {"check": [{"result": [gerber_row]}], "color": "red"}},
                issues=(package_issue,),
                summary={"Gerber Export": package_summary},
            ),
        ).run()

        finding_issues = [issue for issue in result.issues if issue.category == category]
        self.assertEqual(1, len(finding_issues))
        self.assertEqual("dfm_finding", finding_issues[0].raw["issue_kind"])
        self.assertEqual(1250000, finding_issues[0].location.x_nm)
        self.assertEqual(tuple(finding_issues), result.summary[category].issues)
        self.assertEqual((package_issue,), result.summary["Gerber Export"].issues)

    def test_combined_native_pass_keeps_actual_gerber_violation_issue_and_display(self):
        category = "Smallest Trace Width"
        native_row = {
            "id": "track-uuid",
            "item": "Trace Width",
            "rule_key": "smallesttracewidth:tracewidth",
            "layer": ["F.Cu"],
            "value": "0.101",
            "rule": "0.1,0.12,0.15",
            "message": "native measurement passed",
            "color": "black",
            "source": "kicad",
        }
        for gerber_color, expected_severity in (("red", "error"), ("gold", "warning")):
            with self.subTest(gerber_color=gerber_color):
                gerber_row = dict(
                    native_row,
                    value="0.099",
                    message="actual Gerber measurement failed",
                    color=gerber_color,
                    source="gerber",
                    raw={
                        "point": [1.25, 2.5],
                        "measurement_basis": "gerber",
                    },
                )
                result = CombinedAnalysisService(
                    lambda: AnalysisStageResult(
                        KICAD_NATIVE,
                        {
                            category: {
                                "check": [{"result": [native_row]}],
                                "color": "black",
                            }
                        },
                    ),
                    lambda: AnalysisStageResult(
                        GERBER_ENRICHED,
                        {
                            category: {
                                "check": [{"result": [gerber_row]}],
                                "color": gerber_color,
                            }
                        },
                    ),
                ).run()

                merged_category = result.analysis_result[category]
                merged_row = merged_category["check"][0]["result"][0]
                self.assertEqual(gerber_color, merged_row["color"])
                self.assertEqual("0.099", merged_row["value"])
                self.assertEqual(
                    "actual Gerber measurement failed", merged_row["message"]
                )
                self.assertEqual(gerber_color, merged_category["color"])
                self.assertEqual(1, merged_category["violation_count"])
                self.assertEqual(
                    1, result.contract["categories"][category]["violation_count"]
                )

                finding_issues = [
                    issue for issue in result.issues if issue.category == category
                ]
                self.assertEqual(1, len(finding_issues))
                issue = finding_issues[0]
                self.assertEqual(expected_severity, issue.severity)
                self.assertEqual("0.099", issue.value)
                self.assertEqual("actual Gerber measurement failed", issue.message)
                self.assertEqual(GERBER_ENRICHED, issue.raw["source_mode"])
                self.assertTrue(issue.raw["engine_discrepancy"])
                self.assertEqual(1250000, issue.location.x_nm)
                self.assertEqual(tuple(finding_issues), result.summary[category].issues)

    def test_combined_native_violation_does_not_duplicate_existing_native_issue(self):
        category = "Smallest Trace Width"
        native_row = {
            "id": "track-uuid",
            "item": "Trace Width",
            "rule_key": "smallesttracewidth:tracewidth",
            "layer": ["F.Cu"],
            "value": "0.08",
            "rule": "0.1,0.12,0.15",
            "message": "native measurement failed",
            "color": "red",
            "source": "kicad",
        }
        native_issue = DfmIssue(
            category,
            "Trace Width",
            severity="error",
            layer=["F.Cu"],
            value="0.08",
            rule="0.1,0.12,0.15",
            message="native measurement failed",
            raw=native_row,
        )
        gerber_row = dict(
            native_row,
            value="0.079",
            message="Gerber measurement also failed",
            source="gerber",
            raw={"point": [1.25, 2.5], "measurement_basis": "gerber"},
        )

        result = CombinedAnalysisService(
            lambda: AnalysisStageResult(
                KICAD_NATIVE,
                {
                    category: {
                        "check": [{"result": [native_row]}],
                        "color": "red",
                    }
                },
                issues=(native_issue,),
            ),
            lambda: AnalysisStageResult(
                GERBER_ENRICHED,
                {
                    category: {
                        "check": [{"result": [gerber_row]}],
                        "color": "red",
                    }
                },
            ),
        ).run()

        finding_issues = [issue for issue in result.issues if issue.category == category]
        self.assertEqual((native_issue,), tuple(finding_issues))
        self.assertEqual((native_issue,), result.summary[category].issues)
        self.assertEqual(1, result.contract["categories"][category]["violation_count"])


if __name__ == "__main__":
    unittest.main()
