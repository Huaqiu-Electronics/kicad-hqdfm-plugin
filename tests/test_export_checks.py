import math
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from kicad_dfm.core.models import ExportResult
from kicad_dfm.core.rule_profiles import rules_for_profile
from kicad_dfm.services.board_statistics import BoardStatistics
from kicad_dfm.services import export_checks
from kicad_dfm.services import export_scanners
from kicad_dfm.services.export_checks import (
    ExportChecks,
    STRICT_SCANNER_CATEGORIES,
    analyze_export,
    analyze_export_with_results,
    is_blocking_export_issue,
    parse_gerber_scan,
    scan_gerber,
)
from kicad_dfm.services.export_geometry_core import DrillPrimitive
from kicad_dfm.services.export_geometry_core import GerberPrimitive
from kicad_dfm.services.export_geometry_core import GerberSegment
from kicad_dfm.services.export_geometry_core import drill_to_primitive_gap
from kicad_dfm.services.export_geometry_core import gerber_arc_segments
from kicad_dfm.services.export_geometry_core import outline_open_gap
from kicad_dfm.services.export_geometry_core import outline_open_points
from kicad_dfm.services.export_geometry_core import primitive_segment_gap
from kicad_dfm.services.export_geometry_core import primitive_gap
from kicad_dfm.services.export_geometry_core import primitive_gap_within
from kicad_dfm.services.export_geometry_core import region_to_region_gap
from kicad_dfm.services.export_geometry_core import simplify_polygon_points
from kicad_dfm.services.export_result_helpers import grouped_native_results
from kicad_dfm.services.export_result_helpers import aggregate_physical_native_results
from kicad_dfm.services.export_result_helpers import location_fields
from kicad_dfm.services.export_parsers import parse_excellon_scan
from kicad_dfm.services.export_gerber_apertures import parse_gerber_aperture
from kicad_dfm.services.export_scan_models import ExcellonScan
from kicad_dfm.services.export_scan_models import GerberScan
from kicad_dfm.services.export_scan_models import ScanFinding


PLOT_PLAN = (
    ("CuTop", 0, "Top layer"),
    ("CuBottom", 31, "Bottom layer"),
    ("SilkTop", 21, "Silk top"),
    ("EdgeCuts", 44, "Edges"),
)


class ExportChecksTest(unittest.TestCase):
    def test_mapped_drill_spacing_uses_network_and_hole_types(self):
        class Item:
            def __init__(self, net, via=True, blind=False):
                self.net = net
                self.via = via
                self.blind = blind

        class Backend:
            def item_net_name(self, item):
                return item.net

            def is_via(self, item):
                return item.via

            def is_blind_buried_via(self, item):
                return item.blind

        class Mapper:
            def __init__(self, left, right):
                self.left = left
                self.right = right

            def map_pair(self, _data):
                left = type("Mapping", (), {"status": "matched", "item": self.left})()
                right = type("Mapping", (), {"status": "matched", "item": self.right})()
                return left, right

        checks = ExportChecks(None)
        checks.backend = Backend()

        cases = (
            (Item("POWER"), Item("POWER"), "Same Net Via Spacing"),
            (Item("A"), Item("B"), "Different Net Via Spacing"),
            (Item("A", via=False), Item("B", via=False), "Different Net PTH Spacing"),
            (Item("POWER", via=False), Item("POWER", via=False), ""),
            (Item("A", blind=True), Item("B", blind=True), "Blind/Buried Via Spacing"),
        )
        for left, right, expected in cases:
            checks.result_mapper = Mapper(left, right)
            data = {
                "item": "Different Net PTH Spacing",
                "value": "0.200000",
                "raw": {},
            }
            self.assertEqual(
                "Different Net PTH Spacing",
                checks._mapped_drill_spacing_item(data),
            )
            if expected:
                self.assertEqual(expected, data["raw"]["native_item"])
            else:
                self.assertEqual("same_net", data["raw"]["suppressed_reason"])

    def test_unresolved_mapped_drill_pair_keeps_gerber_finding(self):
        checks = ExportChecks(None)
        checks.backend = object()
        unresolved = type("Mapping", (), {"status": "ambiguous", "item": None})()
        checks.result_mapper = type(
            "Mapper",
            (),
            {"map_pair": lambda self, _data: (unresolved, unresolved)},
        )()

        data = {"item": "Different Net PTH Spacing", "raw": {}}
        self.assertEqual(
            "Different Net PTH Spacing",
            checks._mapped_drill_spacing_item(data),
        )
        self.assertEqual("unmapped", data["raw"]["classification_status"])

    def test_copper_spacing_reports_all_pairs_inside_configured_limit(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for center, net in (((0.0, 0.0), "A"), ((0.5, 0.0), "B"), ((1.0, 0.0), "C")):
            scan.primitives.append(
                GerberPrimitive(
                    "rect", center=center, width=0.4, height=0.4,
                    is_flash=True, function="ComponentPad", net=net,
                )
            )

        findings = list(
            export_scanners.scan_copper_spacing(
                [scan], {"Pad-to-Pad Spacing": 0.15}
            )
        )

        self.assertEqual(2, len(findings))
        self.assertTrue(all(finding.item == "Pad-to-Pad Spacing" for finding in findings))
        self.assertTrue(all(abs(finding.value - 0.1) < 1e-9 for finding in findings))

    def test_copper_spacing_excludes_vias_from_pad_spacing_categories(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.4, is_flash=True,
                    function="ComponentPad", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(0.45, 0.35), width=0.4, is_flash=True,
                    function="ViaPad", net="B",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual([], findings)

    def test_copper_spacing_collapses_composite_x2_pad_pair(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for object_id, net, offset in (("U1,1", "A", 0.0), ("U1,2", "B", 0.7)):
            scan.primitives.extend(
                (
                    GerberPrimitive(
                        "circle", center=(offset, 0.0), width=0.4, is_flash=True,
                        function="SMDPad", object_id=object_id, net=net,
                    ),
                    GerberPrimitive(
                        "segment", start=(offset, -0.1), end=(offset, 0.1), width=0.4,
                        is_flash=True, function="SMDPad", object_id=object_id, net=net,
                    ),
                )
            )

        findings = list(
            export_scanners.scan_copper_spacing(
                [scan], {"SMD Pad Spacing": 0.4}
            )
        )

        self.assertEqual(
            {"SMD Pad Spacing"},
            {finding.item for finding in findings},
        )
        self.assertTrue(all(abs(finding.value - 0.3) < 1e-9 for finding in findings))

    def test_copper_spacing_ignores_primitives_from_same_x2_pad_object(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(0.0, 0.0), width=0.5, height=0.2,
                    is_flash=True, function="SMDPad", net="A",
                    object_id="U1,1,VDD", flash_id="1:0",
                ),
                GerberPrimitive(
                    "circle", center=(0.2, 0.0), width=0.2,
                    is_flash=True, function="SMDPad", net="B",
                    object_id="U1,1,VDD", flash_id="2:0",
                ),
            )
        )

        findings = list(
            export_scanners.scan_copper_spacing(
                [scan], {"Pad-to-Pad Spacing": 0.2, "SMD Pad Spacing": 0.2}
            )
        )

        self.assertEqual([], findings)

    def test_mapped_copper_spacing_keeps_gerber_value_and_native_reference(self):
        track = type("Track", (), {})()
        pad = type("Pad", (), {})()
        matched = lambda item: type(
            "Mapping", (), {"status": "matched", "item": item}
        )()

        class Backend:
            def is_via(self, item):
                return False

            def is_track(self, item):
                return item is track

            def is_pad(self, item):
                return item is pad

            def item_clearance_nm(self, left, right, max_distance):
                self.clearance_call = (left, right, max_distance)
                return 123456

        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = type(
            "Mapper", (), {"map_pair": lambda self, _data: (matched(track), matched(pad))}
        )()
        finding = ScanFinding(
            "Trace Spacing",
            "Gerber spacing",
            category="Smallest Trace Spacing",
            value=0.09,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        row = checks.native_results["Smallest Trace Spacing"][0]
        self.assertEqual("Trace Spacing", row["item"])
        self.assertEqual("0.090000", row["value"])
        self.assertEqual("gerber_derived", row["geometry_basis"])
        self.assertEqual("0.090000", row["raw"]["gerber_value"])
        self.assertEqual("0.123456", row["raw"]["native_value"])
        self.assertEqual("Trace-to-Pad Spacing", row["raw"]["native_item"])
        self.assertEqual(
            "kicad_effective_shape",
            row["raw"]["native_measurement_basis"],
        )

    def test_copper_mapping_does_not_change_strict_finding_contract(self):
        track = object()
        pad = object()

        class Backend:
            def is_via(self, _item):
                return False

            def is_track(self, item):
                return item is track

            def is_pad(self, item):
                return item is pad

            def item_clearance_nm(self, _left, _right, _max_distance):
                return 123456

        class Mapper:
            def map_pair(self, _data):
                return (
                    type(
                        "Mapping",
                        (),
                        {
                            "status": "matched",
                            "item": track,
                            "item_id": "track-uuid",
                        },
                    )(),
                    type(
                        "Mapping",
                        (),
                        {
                            "status": "matched",
                            "item": pad,
                            "item_id": "pad-uuid",
                        },
                    )(),
                )

        finding = ScanFinding(
            "Trace Spacing",
            "Gerber spacing",
            category="Smallest Trace Spacing",
            value=0.09,
            layer=["F.Cu"],
            raw={
                "file": "F_Cu.gbr",
                "primary": {
                    "file": "F_Cu.gbr",
                    "segment": ((0.0, 0.0), (1.0, 0.0)),
                    "bbox": (0.0, -0.1, 1.0, 0.1),
                },
                "related": {
                    "file": "F_Cu.gbr",
                    "point": (0.5, 0.3),
                    "bbox": (0.4, 0.2, 0.6, 0.4),
                },
            },
        )
        plain = ExportChecks(None, rules=rules_for_profile("standard"))
        mapped = ExportChecks(None, rules=rules_for_profile("standard"))
        mapped.backend = Backend()
        mapped.result_mapper = Mapper()

        plain._add_scan_finding(finding)
        mapped._add_scan_finding(finding)
        plain_row = plain.native_results["Smallest Trace Spacing"][0]
        mapped_row = mapped.native_results["Smallest Trace Spacing"][0]

        for field in ("item", "value", "color", "finding_key"):
            self.assertEqual(plain_row[field], mapped_row[field])
        self.assertEqual("Trace-to-Pad Spacing", mapped_row["raw"]["native_item"])

    def test_mapped_copper_spacing_suppresses_authoritative_same_net_pair(self):
        left = type("Item", (), {"net": "GND"})()
        right = type("Item", (), {"net": "GND"})()

        class Backend:
            def item_net_name(self, item):
                return item.net

            def is_via(self, _item):
                return False

            def is_track(self, _item):
                return True

            def is_pad(self, _item):
                return False

            def item_clearance_nm(self, *_args):
                raise AssertionError("same-net pair must be suppressed before measuring")

        matched = lambda item: type(
            "Mapping", (), {"status": "matched", "item": item, "item_id": ""}
        )()
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = type(
            "Mapper",
            (),
            {"map_pair": lambda self, _data: (matched(left), matched(right))},
        )()
        finding = ScanFinding(
            "Trace Spacing",
            "Gerber spacing with stale X2 nets",
            category="Smallest Trace Spacing",
            value=0.0,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        self.assertNotIn("Smallest Trace Spacing", checks.native_results)

    def test_mapped_copper_spacing_suppresses_explicit_native_net_tie_pair(self):
        left = type("Item", (), {"net": "+5V", "item_id": "pad-1"})()
        right = type(
            "Item", (), {"net": "SENSE_5V", "item_id": "pad-2"}
        )()

        class Backend:
            def item_net_name(self, item):
                return item.net

            def item_id(self, item):
                return item.item_id

            def net_tie_pad_groups(self):
                return ((('pad-1', '+5V'), ('pad-2', 'SENSE_5V')),)

            def is_via(self, _item):
                return False

            def is_track(self, _item):
                return False

            def is_pad(self, _item):
                return True

            def is_smd_pad(self, _item):
                return True

            def item_clearance_nm(self, *_args):
                return 0

        matched = lambda item: type(
            "Mapping", (), {"status": "matched", "item": item, "item_id": ""}
        )()
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = type(
            "Mapper",
            (),
            {"map_pair": lambda self, _data: (matched(left), matched(right))},
        )()
        finding = ScanFinding(
            "SMD Pad Spacing",
            "Gerber spacing across an explicit net tie",
            category="SMD Spacing",
            value=0.0,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        self.assertNotIn("SMD Spacing", checks.native_results)

    def test_amulet_ambiguous_net_tie_contacts_choose_zero_gap_native_candidate(self):
        class Item:
            def __init__(self, item_id, net, gap_nm=None):
                self.item_id = item_id
                self.net = net
                self.gap_nm = gap_nm

        mapping = lambda status, item=None: type(
            "Mapping",
            (),
            {
                "status": status,
                "item": item,
                "item_id": item.item_id if item is not None else "",
            },
        )()

        cases = (
            ("NT11", "related", (199999, 199999, 282841)),
            ("NT12", "related", (199999, 199999, 282843)),
            ("NT8", "primary", (199999, 199999, 282843)),
            ("NT9", "primary", (199999, 199999, 282843)),
            ("NT2", "related", (199999, 199999, 267185, 424264)),
            ("NT5", "primary", (199999, 199999, 247487, 266422)),
            ("NT6", "related", (199999, 199999, 318197)),
        )
        for reference, ambiguous_side, extra_gaps in cases:
            with self.subTest(reference=reference):
                fixed = Item(reference + "-fixed", "NET_A")
                contact = Item(reference + "-contact", "NET_B", 0)
                member = Item(reference + "-member", "NET_B", extra_gaps[0])
                extras = (contact, member) + tuple(
                    Item(
                        "{0}-candidate-{1}".format(reference, index),
                        "NET_B",
                        gap_nm,
                    )
                    for index, gap_nm in enumerate(extra_gaps[1:], 1)
                )

                class Backend:
                    def item_net_name(self, item):
                        return item.net

                    def item_id(self, item):
                        return item.item_id

                    def net_tie_pad_groups(self):
                        return (
                            (
                                (fixed.item_id, fixed.net),
                                (contact.item_id, contact.net),
                                (member.item_id, member.net),
                            ),
                        )

                    def is_via(self, _item):
                        return False

                    def is_track(self, _item):
                        return False

                    def is_pad(self, _item):
                        return True

                    def is_smd_pad(self, _item):
                        return True

                    def item_clearance_nm(self, left, right, _max_distance):
                        return left.gap_nm if left.gap_nm is not None else right.gap_nm

                class Mapper:
                    def map_pair(self, _data):
                        if ambiguous_side == "primary":
                            return mapping("ambiguous"), mapping("matched", fixed)
                        return mapping("matched", fixed), mapping("ambiguous")

                    def map_pair_candidates(self, _data):
                        candidates = tuple(mapping("matched", item) for item in extras)
                        if ambiguous_side == "primary":
                            return candidates, (mapping("matched", fixed),)
                        return (mapping("matched", fixed),), candidates

                checks = ExportChecks(None, rules=rules_for_profile("standard"))
                checks.backend = Backend()
                checks.result_mapper = Mapper()
                finding = ScanFinding(
                    "SMD Pad Spacing",
                    "Gerber zero-gap contact at " + reference,
                    category="SMD Spacing",
                    value=0.0,
                    layer=["F.Cu"],
                    raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
                )

                checks._add_scan_finding(finding)

                self.assertNotIn("SMD Spacing", checks.native_results)

    def test_ambiguous_net_tie_tie_keeps_unsuppressed_zero_gap_candidate(self):
        class Item:
            def __init__(self, item_id, net):
                self.item_id = item_id
                self.net = net

        fixed = Item("fixed-member", "NET_A")
        tied_member = Item("tied-member", "NET_B")
        ordinary_pad = Item("ordinary-pad", "NET_B")
        mapping = lambda status, item=None: type(
            "Mapping",
            (),
            {
                "status": status,
                "item": item,
                "item_id": item.item_id if item is not None else "",
            },
        )()

        class Backend:
            def item_net_name(self, item):
                return item.net

            def item_id(self, item):
                return item.item_id

            def net_tie_pad_groups(self):
                return (((fixed.item_id, fixed.net), (tied_member.item_id, tied_member.net)),)

            def is_via(self, _item):
                return False

            def is_track(self, _item):
                return False

            def is_pad(self, _item):
                return True

            def is_smd_pad(self, _item):
                return True

            def item_clearance_nm(self, _left, _right, _max_distance):
                return 0

        class Mapper:
            def map_pair(self, _data):
                return mapping("matched", fixed), mapping("ambiguous")

            def map_pair_candidates(self, _data):
                return (mapping("matched", fixed),), (
                    mapping("matched", tied_member),
                    mapping("matched", ordinary_pad),
                )

        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = Mapper()
        finding = ScanFinding(
            "SMD Pad Spacing",
            "Gerber zero-gap contact with tied native candidates",
            category="SMD Spacing",
            value=0.0,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        rows = checks.native_results["SMD Spacing"]
        self.assertEqual(1, len(rows))
        self.assertEqual("ordinary-pad", rows[0]["related_id"])
        self.assertEqual(2, rows[0]["raw"]["closest_native_pair_count"])

    def test_zero_gap_nonmember_pad_is_not_suppressed_as_local_net_tie(self):
        class Item:
            def __init__(self, item_id, net):
                self.item_id = item_id
                self.net = net

        left = Item("member-a", "NET_A")
        declared_right = Item("member-b", "NET_B")
        ordinary_right = Item("ordinary-b", "NET_B")
        mapping = lambda item: type(
            "Mapping",
            (),
            {"status": "matched", "item": item, "item_id": item.item_id},
        )()

        class Backend:
            def item_net_name(self, item):
                return item.net

            def item_id(self, item):
                return item.item_id

            def net_tie_pad_groups(self):
                return (((left.item_id, left.net), (declared_right.item_id, declared_right.net)),)

            def is_via(self, _item):
                return False

            def is_track(self, _item):
                return False

            def is_pad(self, _item):
                return True

            def is_smd_pad(self, _item):
                return True

            def item_clearance_nm(self, _left, _right, _max_distance):
                return 0

        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = type(
            "Mapper",
            (),
            {"map_pair": lambda self, _data: (mapping(left), mapping(ordinary_right))},
        )()
        finding = ScanFinding(
            "SMD Pad Spacing",
            "Gerber zero-gap contact outside the declared net-tie pads",
            category="SMD Spacing",
            value=0.0,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        rows = checks.native_results["SMD Spacing"]
        self.assertEqual(1, len(rows))
        self.assertEqual("ordinary-b", rows[0]["related_id"])

    def test_local_net_tie_requires_pad_uuid_and_declared_net_to_match(self):
        class Item:
            def __init__(self, item_id, net, kind):
                self.item_id = item_id
                self.net = net
                self.kind = kind

        mapping = lambda item: type(
            "Mapping",
            (),
            {"status": "matched", "item": item, "item_id": item.item_id},
        )()

        class Backend:
            def item_net_name(self, item):
                return item.net

            def item_id(self, item):
                return item.item_id

            def net_tie_pad_groups(self):
                return ((("member-a", "NET_A"), ("member-b", "NET_B")),)

            def is_via(self, _item):
                return False

            def is_track(self, item):
                return item.kind == "track"

            def is_pad(self, item):
                return item.kind == "pad"

            def is_smd_pad(self, item):
                return item.kind == "pad"

            def item_clearance_nm(self, _left, _right, _max_distance):
                return 0

        cases = (
            ("pad-pad", Item("member-b", "NET_B", "pad")),
            ("pad-track", Item("track-b", "NET_B", "track")),
        )
        for name, right in cases:
            with self.subTest(name=name):
                # The UUID is declared, but the mapped pad's current network is
                # not the network recorded for that member in the net-tie group.
                left = Item("member-a", "RENAMED_A", "pad")
                checks = ExportChecks(None, rules=rules_for_profile("standard"))
                checks.backend = Backend()
                checks.result_mapper = type(
                    "Mapper",
                    (),
                    {"map_pair": lambda self, _data: (mapping(left), mapping(right))},
                )()
                finding = ScanFinding(
                    "SMD Pad Spacing",
                    "Gerber zero-gap contact with a stale net-tie member network",
                    category="SMD Spacing",
                    value=0.0,
                    layer=["F.Cu"],
                    raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
                )

                checks._add_scan_finding(finding)

                self.assertEqual(
                    1,
                    len(checks.native_results["SMD Spacing"]),
                )

    def test_mapped_smd_spacing_suppresses_positive_gap_between_net_tie_members(self):
        left = type("Item", (), {"net": "+5V", "item_id": "pad-1"})()
        right = type(
            "Item", (), {"net": "SENSE_5V", "item_id": "pad-2"}
        )()

        class Backend:
            def item_net_name(self, item):
                return item.net

            def item_id(self, item):
                return item.item_id

            def net_tie_pad_groups(self):
                return ((('pad-1', '+5V'), ('pad-2', 'SENSE_5V')),)

            def is_via(self, _item):
                return False

            def is_track(self, _item):
                return False

            def is_pad(self, _item):
                return True

            def is_smd_pad(self, _item):
                return True

            def item_clearance_nm(self, *_args):
                return 100000

        matched = lambda item: type(
            "Mapping", (), {"status": "matched", "item": item, "item_id": ""}
        )()
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = type(
            "Mapper",
            (),
            {"map_pair": lambda self, _data: (matched(left), matched(right))},
        )()
        finding = ScanFinding(
            "SMD Pad Spacing",
            "Gerber spacing near an explicit net tie",
            category="SMD Spacing",
            value=0.1,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        self.assertNotIn("SMD Spacing", checks.native_results)

    def test_mapped_smd_spacing_suppresses_pad_locally_attached_to_net_tie(self):
        class Item:
            def __init__(self, item_id, net, local_clearance_nm=0):
                self.item_id = item_id
                self.net = net
                self.local_clearance_nm = local_clearance_nm

            def GetLocalClearance(self):
                return self.local_clearance_nm

        ordinary = Item("r18-pad", "+5V")
        member_a = Item("net-tie-a", "+5V", 10000)
        member_b = Item("net-tie-b", "SENSE_5V", 10000)
        items = {
            item.item_id: item
            for item in (ordinary, member_a, member_b)
        }

        class Backend:
            def item_net_name(self, item):
                return item.net

            def item_id(self, item):
                return item.item_id

            def resolve_item(self, item_id):
                return items.get(item_id)

            def net_tie_pad_groups(self):
                return (
                    (
                        (member_a.item_id, member_a.net),
                        (member_b.item_id, member_b.net),
                    ),
                )

            def is_via(self, _item):
                return False

            def is_track(self, _item):
                return False

            def is_pad(self, _item):
                return True

            def is_smd_pad(self, _item):
                return True

            def item_clearance_nm(self, left, right, _max_distance):
                pair = {left.item_id, right.item_id}
                if pair == {ordinary.item_id, member_a.item_id}:
                    return 8680
                if pair == {ordinary.item_id, member_b.item_id}:
                    return 25000
                return 5000001

        matched = lambda item: type(
            "Mapping",
            (),
            {"status": "matched", "item": item, "item_id": item.item_id},
        )()
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = type(
            "Mapper",
            (),
            {
                "map_pair": lambda self, _data: (
                    matched(ordinary),
                    matched(member_b),
                )
            },
        )()
        finding = ScanFinding(
            "SMD Pad Spacing",
            "Gerber spacing beside a locally attached net tie",
            category="SMD Spacing",
            value=0.025,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        self.assertNotIn("SMD Spacing", checks.native_results)

    def test_mapped_smd_spacing_keeps_same_net_pad_outside_net_tie_locality(self):
        class Item:
            def __init__(self, item_id, net, local_clearance_nm=0):
                self.item_id = item_id
                self.net = net
                self.local_clearance_nm = local_clearance_nm

            def GetLocalClearance(self):
                return self.local_clearance_nm

        ordinary = Item("remote-pad", "+5V")
        member_a = Item("net-tie-a", "+5V", 10000)
        member_b = Item("net-tie-b", "SENSE_5V", 10000)
        items = {
            item.item_id: item
            for item in (ordinary, member_a, member_b)
        }

        class Backend:
            def item_net_name(self, item):
                return item.net

            def item_id(self, item):
                return item.item_id

            def resolve_item(self, item_id):
                return items.get(item_id)

            def net_tie_pad_groups(self):
                return (
                    (
                        (member_a.item_id, member_a.net),
                        (member_b.item_id, member_b.net),
                    ),
                )

            def is_via(self, _item):
                return False

            def is_track(self, _item):
                return False

            def is_pad(self, _item):
                return True

            def is_smd_pad(self, _item):
                return True

            def item_clearance_nm(self, left, right, _max_distance):
                pair = {left.item_id, right.item_id}
                if pair == {ordinary.item_id, member_a.item_id}:
                    return 10001
                if pair == {ordinary.item_id, member_b.item_id}:
                    return 25000
                return 5000001

        matched = lambda item: type(
            "Mapping",
            (),
            {"status": "matched", "item": item, "item_id": item.item_id},
        )()
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = type(
            "Mapper",
            (),
            {
                "map_pair": lambda self, _data: (
                    matched(ordinary),
                    matched(member_b),
                )
            },
        )()
        finding = ScanFinding(
            "SMD Pad Spacing",
            "Gerber spacing outside a net tie's local clearance",
            category="SMD Spacing",
            value=0.025,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        rows = checks.native_results["SMD Spacing"]
        self.assertEqual(1, len(rows))
        self.assertEqual("remote-pad", rows[0]["id"])
        self.assertEqual("net-tie-b", rows[0]["related_id"])

    def test_mapped_smd_spacing_does_not_exempt_member_of_adjacent_net_tie(self):
        class Item:
            def __init__(self, item_id, net, local_clearance_nm=10000):
                self.item_id = item_id
                self.net = net
                self.local_clearance_nm = local_clearance_nm

            def GetLocalClearance(self):
                return self.local_clearance_nm

        first_a = Item("first-a", "SHARED")
        first_b = Item("first-b", "FIRST_B")
        second_a = Item("second-a", "SHARED")
        second_b = Item("second-b", "SECOND_B")
        items = {
            item.item_id: item
            for item in (first_a, first_b, second_a, second_b)
        }

        class Backend:
            def item_net_name(self, item):
                return item.net

            def item_id(self, item):
                return item.item_id

            def resolve_item(self, item_id):
                return items.get(item_id)

            def net_tie_pad_groups(self):
                return (
                    ((first_a.item_id, first_a.net), (first_b.item_id, first_b.net)),
                    (
                        (second_a.item_id, second_a.net),
                        (second_b.item_id, second_b.net),
                    ),
                )

            def is_via(self, _item):
                return False

            def is_track(self, _item):
                return False

            def is_pad(self, _item):
                return True

            def is_smd_pad(self, _item):
                return True

            def item_clearance_nm(self, left, right, _max_distance):
                pair = {left.item_id, right.item_id}
                if pair == {second_a.item_id, first_a.item_id}:
                    return 0
                if pair == {second_a.item_id, first_b.item_id}:
                    return 25000
                return 5000001

        matched = lambda item: type(
            "Mapping",
            (),
            {"status": "matched", "item": item, "item_id": item.item_id},
        )()
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = type(
            "Mapper",
            (),
            {
                "map_pair": lambda self, _data: (
                    matched(second_a),
                    matched(first_b),
                )
            },
        )()
        finding = ScanFinding(
            "SMD Pad Spacing",
            "Adjacent net ties sharing a net name",
            category="SMD Spacing",
            value=0.025,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        rows = checks.native_results["SMD Spacing"]
        self.assertEqual(1, len(rows))
        self.assertEqual("second-a", rows[0]["id"])
        self.assertEqual("first-b", rows[0]["related_id"])

    def test_same_net_drill_mapping_keeps_strict_evidence(self):
        left = object()
        right = object()

        class Backend:
            def item_net_name(self, _item):
                return "GND"

            def is_via(self, _item):
                return True

            def is_blind_buried_via(self, _item):
                return False

        class Mapper:
            def map_pair(self, _data):
                return (
                    type(
                        "Mapping",
                        (),
                        {"status": "matched", "item": left, "item_id": "via-1"},
                    )(),
                    type(
                        "Mapping",
                        (),
                        {"status": "matched", "item": right, "item_id": "via-2"},
                    )(),
                )

        finding = ScanFinding(
            "Different Net PTH Spacing",
            "Excellon spacing",
            category="Drill Hole Spacing",
            value=0.2,
            layer=["Drl"],
            raw={
                "file": "board-PTH.drl",
                "segment": ((0.0, 0.0), (0.5, 0.0)),
                "primary": {"item_type": "drill", "point": (0.0, 0.0)},
                "related": {"item_type": "drill", "point": (0.5, 0.0)},
            },
        )
        plain = ExportChecks(None, rules=rules_for_profile("standard"))
        mapped = ExportChecks(None, rules=rules_for_profile("standard"))
        mapped.backend = Backend()
        mapped.result_mapper = Mapper()

        plain._add_scan_finding(finding)
        mapped._add_scan_finding(finding)
        plain_row = plain.native_results["Drill Hole Spacing"][0]
        mapped_row = mapped.native_results["Drill Hole Spacing"][0]

        for field in ("item", "value", "color", "finding_key"):
            self.assertEqual(plain_row[field], mapped_row[field])
        self.assertEqual("same_net", mapped_row["raw"]["suppressed_reason"])
        self.assertEqual("Same Net Via Spacing", mapped_row["raw"]["native_item"])

    def test_mapped_pad_size_keeps_gerber_measurement_and_native_reference(self):
        pad = object()

        class Backend:
            def is_pad(self, item):
                return item is pad

            def pad_size_mm(self, item):
                self.measured_item = item
                return 0.6, 0.22

        class Mapper:
            def apply_mapping(self, data):
                data["id"] = "pad-uuid"
                return type(
                    "Mapping", (), {"status": "matched", "item": pad}
                )()

        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = Mapper()
        finding = ScanFinding(
            "Short Pads",
            "Gerber fragment width",
            category="Pad size",
            value=0.11,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "pad_size": (0.11, 0.11)},
        )

        checks._add_scan_finding(finding)

        row = checks.native_results["Pad size"][0]
        self.assertEqual("Short Pads", row["item"])
        self.assertEqual("0.110000", row["value"])
        self.assertEqual("pad-uuid", row["id"])
        self.assertEqual("gerber_derived", row["geometry_basis"])
        self.assertEqual("0.110000", row["raw"]["gerber_value"])
        self.assertEqual((0.11, 0.11), row["raw"]["pad_size"])
        self.assertEqual("0.220000", row["raw"]["native_value"])
        self.assertEqual((0.6, 0.22), row["raw"]["native_pad_size"])
        self.assertEqual("Long Pads", row["raw"]["native_item"])

    def test_solder_mask_finding_maps_both_native_location_objects(self):
        class Mapper:
            def apply_mapping(self, data):
                data["id"] = "pad-1-uuid"
                data["related_id"] = "pad-2-uuid"
                return type("Mapping", (), {"status": "matched"})()

        class Backend:
            def net_tie_footprint_pad_ids(self):
                return frozenset(("pad-1-uuid", "pad-2-uuid"))

        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = Mapper()
        finding = ScanFinding(
            "Solder Mask Bridge",
            "Gerber mask bridge",
            category="Solder Mask Analysis",
            value=0.01,
            layer=["F.Mask"],
            raw={
                "file": "MaskTop.gbr",
                "segment": ((0.0, 0.0), (0.01, 0.0)),
                "primary": {"object_id": "U6,1"},
                "related": {"object_id": "U6,2"},
            },
        )

        checks._add_scan_finding(finding)

        row = checks.native_results["Solder Mask Analysis"][0]
        self.assertEqual("pad-1-uuid", row["id"])
        self.assertEqual("pad-2-uuid", row["related_id"])

    def test_missing_smask_strict_keeps_and_enriched_suppresses_net_tie_pad(self):
        class Backend:
            def net_tie_footprint_pad_ids(self):
                return frozenset(("net-tie-pad",))

        class Mapper:
            def apply_mapping(self, data):
                data["id"] = "net-tie-pad"
                return type(
                    "Mapping",
                    (),
                    {"status": "matched", "item_id": "net-tie-pad"},
                )()

        finding = ScanFinding(
            "Missing SMask Opening",
            "Gerber pad has no mask opening",
            category="Missing SMask Openings",
            value=1.0,
            layer=["F.Cu"],
            color="red",
            raw={"file": "F_Cu.gbr", "primary": {"object_id": "NT1,1"}},
        )
        strict = ExportChecks(None, rules=rules_for_profile("standard"))
        enriched = ExportChecks(None, rules=rules_for_profile("standard"))
        enriched.backend = Backend()
        enriched.result_mapper = Mapper()

        strict._add_scan_finding(finding)
        enriched._add_scan_finding(finding)

        self.assertEqual(
            1,
            len(strict.native_results["Missing SMask Openings"]),
        )
        self.assertNotIn("Missing SMask Openings", enriched.native_results)

    def test_missing_smask_enriched_keeps_ordinary_or_ambiguous_mapping(self):
        class Backend:
            def net_tie_footprint_pad_ids(self):
                return frozenset(("net-tie-pad",))

        class Mapper:
            def __init__(self, status, item_id=""):
                self.status = status
                self.item_id = item_id

            def apply_mapping(self, data):
                if self.status == "matched":
                    data["id"] = self.item_id
                return type(
                    "Mapping",
                    (),
                    {"status": self.status, "item_id": self.item_id},
                )()

        finding = ScanFinding(
            "Missing SMask Opening",
            "Gerber pad has no mask opening",
            category="Missing SMask Openings",
            value=1.0,
            layer=["F.Cu"],
            color="red",
            raw={"file": "F_Cu.gbr", "primary": {"object_id": "U1,1"}},
        )
        for status, item_id in (
            ("matched", "ordinary-pad"),
            ("ambiguous", ""),
        ):
            with self.subTest(status=status):
                checks = ExportChecks(None, rules=rules_for_profile("standard"))
                checks.backend = Backend()
                checks.result_mapper = Mapper(status, item_id)

                checks._add_scan_finding(finding)

                self.assertEqual(
                    1,
                    len(checks.native_results["Missing SMask Openings"]),
                )

    def test_holes_on_smd_finding_maps_hole_and_exact_native_pad(self):
        class Mapper:
            def apply_mapping(self, data):
                data["id"] = "via-uuid"
                data["related_id"] = "custom-pad-uuid"
                return type("Mapping", (), {"status": "matched"})()

        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.result_mapper = Mapper()
        finding = ScanFinding(
            "Via on SMD Pad",
            "Gerber hole on custom pad",
            category="Holes on SMD Pads",
            value=0.5,
            layer=["F.Cu"],
            raw={
                "file": "PTH.drl",
                "primary": {"item_type": "drill", "point": (1.0, 2.0)},
                "related": {
                    "item_type": "gerber",
                    "component": "U1",
                    "object_id": "U1,2,2",
                },
            },
        )

        checks._add_scan_finding(finding)

        row = checks.native_results["Holes on SMD Pads"][0]
        self.assertEqual("via-uuid", row["id"])
        self.assertEqual("custom-pad-uuid", row["related_id"])

    def test_mapped_copper_spacing_measures_ambiguous_track_junction(self):
        left = type("Track", (), {})()
        right_a = type("Track", (), {})()
        right_b = type("Track", (), {})()
        mapping = lambda status, item=None: type(
            "Mapping", (), {"status": status, "item": item}
        )()

        class Backend:
            def is_via(self, item):
                return False

            def is_track(self, item):
                return True

            def is_pad(self, item):
                return False

            def item_clearance_nm(self, first, second, max_distance):
                return 200000 if second is right_a else 225000

        class Mapper:
            def map_pair(self, _data):
                return mapping("matched", left), mapping("ambiguous")

            def map_pair_candidates(self, _data):
                return (mapping("matched", left),), (
                    mapping("matched", right_a),
                    mapping("matched", right_b),
                )

        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.backend = Backend()
        checks.result_mapper = Mapper()
        finding = ScanFinding(
            "Trace Spacing",
            "Gerber spacing",
            category="Smallest Trace Spacing",
            value=0.197774,
            layer=["F.Cu"],
            raw={"file": "F_Cu.gbr", "primary": {}, "related": {}},
        )

        checks._add_scan_finding(finding)

        row = checks.native_results["Smallest Trace Spacing"][0]
        self.assertEqual("Trace Spacing", row["item"])
        self.assertEqual("0.197774", row["value"])
        self.assertEqual("gerber_derived", row["geometry_basis"])
        self.assertEqual("0.200000", row["raw"]["native_value"])
        self.assertEqual(2, row["raw"]["candidate_pair_count"])

    def test_copper_spacing_keeps_all_distinct_tied_black_minima(self):
        def row(item, value, left, right):
            return {
                "item": item,
                "item_type": "gerber",
                "color": "black",
                "value": "{0:.6f}".format(value),
                "id": left,
                "related_id": right,
                "raw": {},
            }

        for spacing_item in (
            "Trace Spacing",
            "Trace-to-Pad Spacing",
            "Pad-to-Pad Spacing",
            "SMD Pad Spacing",
        ):
            checks = ExportChecks(None, rules=rules_for_profile("standard"))
            checks._record_native_result(
                "Smallest Trace Spacing",
                row(spacing_item, 0.2, "item-a", "item-b"),
            )
            checks._record_native_result(
                "Smallest Trace Spacing",
                row(spacing_item, 0.20002, "item-c", "item-d"),
            )
            checks._record_native_result(
                "Smallest Trace Spacing",
                row(spacing_item, 0.21, "item-e", "item-f"),
            )
            checks._record_native_result(
                "Smallest Trace Spacing",
                row(spacing_item, 0.2, "item-b", "item-a"),
            )

            rows = checks.native_results["Smallest Trace Spacing"]
            self.assertEqual(2, len(rows), spacing_item)
            self.assertEqual(
                {("item-a", "item-b"), ("item-c", "item-d")},
                {(item["id"], item["related_id"]) for item in rows},
            )
            mapped = checks.native_result_map()["Smallest Trace Spacing"]
            self.assertEqual(
                2,
                sum(len(group["result"]) for group in mapped["check"]),
            )

    def test_pad_size_keeps_all_pads_inside_shape_rule_reporting_limit(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))

        for pad_id, value in (
            ("U6,1", 0.22),
            ("U2,1", 0.24),
            ("U2,2", 0.24),
            ("U1,1", 0.28),
        ):
            checks._record_native_result(
                "Pad size",
                {
                    "item": "Long Pads",
                    "item_type": "gerber",
                    "color": "black",
                    "value": "{0:.6f}".format(value),
                    "id": pad_id,
                    "layer": ["F.Cu"],
                    "rule": "0.152400,0.177800,0.254000",
                    "source": "gerber",
                    "geometry_basis": "gerber_derived",
                    "raw": {},
                },
            )

        rows = checks.native_results["Pad size"]
        self.assertEqual(["U6,1", "U2,1", "U2,2"], [row["id"] for row in rows])
        mapped = checks.native_result_map()["Pad size"]
        self.assertEqual(3, sum(len(group["result"]) for group in mapped["check"]))
        self.assertEqual(2, len(mapped["check"]))

    def test_native_map_aggregates_through_hole_layers_with_measurements(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.native_results = {
            "RingHole": [
                {
                    "id": "via-uuid",
                    "related_id": "via-uuid",
                    "rule_key": "ringhole:viaannularring",
                    "item": "Via Annular Ring",
                    "value": value,
                    "layer": [layer],
                    "rule": "0.101600,0.127000,0.152400",
                    "color": "red" if value == "0.090000" else "gold",
                    "item_type": "gerber",
                    "source": "gerber",
                    "geometry_basis": "gerber_derived",
                    "raw": {
                        "file": file_name,
                        "primary": {
                            "aperture_function": "ViaPad",
                            "point": (1.0, 2.0),
                        },
                        "related": {
                            "item_type": "drill",
                            "point": (1.0, 2.0),
                            "diameter": 0.3,
                        },
                    },
                }
                for layer, file_name, value in (
                    ("F.Cu", "board-F_Cu.gbr", "0.100000"),
                    ("B.Cu", "board-B_Cu.gbr", "0.090000"),
                )
            ]
        }

        mapped = checks.native_result_map()["RingHole"]
        rows = [row for group in mapped["check"] for row in group["result"]]

        self.assertEqual(1, len(rows))
        self.assertEqual("0.090000", rows[0]["value"])
        self.assertEqual(["F.Cu", "B.Cu"], rows[0]["layer"])
        self.assertEqual(2, rows[0]["raw"]["physical_measurement_count"])
        self.assertEqual(2, len(rows[0]["raw"]["per_layer_measurements"]))
        self.assertEqual(2, mapped["checked_count"])
        self.assertEqual(1, mapped["displayed_count"])
        self.assertEqual("partial", mapped["coverage"])

    def test_native_map_aggregates_board_edge_through_hole_layers(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.native_results = {
            "Copper-to-Board Edge": [
                {
                    "id": "board-{0}.gbr".format(layer),
                    "rule_key": "coppertoboardedge:coppertoboardedge",
                    "item": "Copper-to-Board Edge",
                    "value": value,
                    "layer": [layer],
                    "rule": "0.203000,0.381000,0.508000",
                    "color": color,
                    "item_type": "gerber",
                    "source": "gerber",
                    "geometry_basis": "gerber_derived",
                    "raw": {
                        "file": "board-{0}.gbr".format(layer),
                        "primary": {
                            "item_type": "gerber",
                            "aperture_function": "ComponentPad",
                            "bbox": bbox,
                            "net": "CHASSIS",
                            "through_hole": True,
                        },
                    },
                }
                for layer, value, color, bbox in (
                    ("F.Cu", "0.250000", "gold", (9.5, 19.5, 10.5, 20.5)),
                    ("In1.Cu", "0.300000", "gold", (9.7, 19.7, 10.3, 20.3)),
                    ("B.Cu", "0.190000", "red", (9.4, 19.4, 10.6, 20.6)),
                )
            ]
        }

        mapped = checks.native_result_map()["Copper-to-Board Edge"]
        rows = [row for group in mapped["check"] for row in group["result"]]

        self.assertEqual(3, mapped["checked_count"])
        self.assertEqual(1, mapped["displayed_count"])
        self.assertEqual(1, len(rows))
        self.assertEqual("0.190000", rows[0]["value"])
        self.assertEqual("red", rows[0]["color"])
        self.assertEqual(["F.Cu", "In1.Cu", "B.Cu"], rows[0]["layer"])
        self.assertEqual(3, rows[0]["raw"]["physical_measurement_count"])
        self.assertEqual(
            ["0.250000", "0.300000", "0.190000"],
            [
                measurement["value"]
                for measurement in rows[0]["raw"]["per_layer_measurements"]
            ],
        )

    def test_board_edge_through_hole_aggregation_uses_excellon_identity(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        drill_identity = {
            "file": "board-PTH.drl",
            "item_type": "drill",
            "kind": "slot",
            "segment": ((20.0, 65.7), (20.0, 66.8)),
            "bbox": (19.7, 65.4, 20.3, 67.1),
            "diameter": 0.6,
            "plated": True,
            "layer_span": (1, 6),
        }

        def edge_row(layer, primary):
            return {
                "id": "board-{0}.gbr".format(layer),
                "rule_key": "coppertoboardedge:coppertoboardedge",
                "item": "Copper-to-Board Edge",
                "value": "0.250000",
                "layer": [layer],
                "rule": "0.203000,0.279000,0.381000",
                "color": "gold",
                "item_type": "gerber",
                "source": "gerber",
                "geometry_basis": "gerber_derived",
                "raw": {
                    "file": "board-{0}.gbr".format(layer),
                    "primary": {
                        **primary,
                        "item_type": "gerber",
                        "aperture_function": "ComponentPad",
                        "net": "CHASSIS",
                        "through_hole": True,
                        "drill_identity": dict(drill_identity),
                    },
                },
            }

        checks.native_results = {
            "Copper-to-Board Edge": [
                edge_row(
                    "F.Cu",
                    {
                        "component": "J2",
                        "object_id": "J2,MP2,MP2",
                        "bbox": (19.55, 65.25, 19.73, 67.25),
                    },
                ),
                # Inner copper has no X2 object identity, and the nearest
                # custom-pad member's bbox centre is not the slot axis.
                edge_row(
                    "In1.Cu",
                    {"bbox": (19.55, 65.25, 19.73, 67.25)},
                ),
            ]
        }

        mapped = checks.native_result_map()["Copper-to-Board Edge"]
        rows = [row for group in mapped["check"] for row in group["result"]]

        self.assertEqual(1, len(rows))
        self.assertEqual(["F.Cu", "In1.Cu"], rows[0]["layer"])
        self.assertEqual(2, rows[0]["raw"]["physical_measurement_count"])
        self.assertEqual(
            "slot",
            rows[0]["raw"]["primary"]["drill_identity"]["kind"],
        )
        self.assertEqual(
            ["J2,MP2,MP2", ""],
            [
                measurement["primary"].get("object_id", "")
                for measurement in rows[0]["raw"]["per_layer_measurements"]
            ],
        )
        self.assertTrue(
            all(
                measurement["primary"]["drill_identity"]["kind"] == "slot"
                for measurement in rows[0]["raw"]["per_layer_measurements"]
            )
        )

    def test_single_board_edge_zone_is_not_marked_physically_aggregated(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.native_results = {
            "Copper-to-Board Edge": [
                {
                    "id": "board-In1_Cu.gbr",
                    "rule_key": "coppertoboardedge:coppertoboardedge",
                    "item": "Copper-to-Board Edge",
                    "value": "0.250000",
                    "layer": ["In1.Cu"],
                    "rule": "0.203000,0.279000,0.381000",
                    "color": "gold",
                    "item_type": "gerber",
                    "source": "gerber",
                    "geometry_basis": "gerber_derived",
                    "raw": {
                        "file": "board-In1_Cu.gbr",
                        "primary": {
                            "item_type": "gerber",
                            "kind": "region",
                            "aperture_function": "Conductor",
                            "net": "GND",
                            "bbox": (1.0, 2.0, 3.0, 4.0),
                            "layer": ["In1.Cu"],
                        },
                    },
                }
            ]
        }

        mapped = checks.native_result_map()["Copper-to-Board Edge"]
        row = mapped["check"][0]["result"][0]

        self.assertNotIn("physical_measurement_count", row["raw"])
        self.assertNotIn("per_layer_measurements", row["raw"])

    def test_mapped_board_edge_zone_aggregates_contours_only_within_layer(self):
        def zone_row(layer, bbox, value):
            return {
                "id": "zone-uuid",
                "rule_key": "coppertoboardedge:coppertoboardedge",
                "item": "Copper-to-Board Edge",
                "value": value,
                "layer": [layer],
                "color": "gold",
                "raw": {
                    "primary": {
                        "kind": "region",
                        "aperture_function": "Conductor",
                        "bbox": bbox,
                    },
                    "uuid_mapping": {
                        "status": "matched",
                        "id": "zone-uuid",
                    },
                },
            }

        rows = aggregate_physical_native_results(
            "Copper-to-Board Edge",
            (
                zone_row("F.Cu", (1.0, 2.0, 3.0, 4.0), "0.250000"),
                zone_row("F.Cu", (5.0, 2.0, 7.0, 4.0), "0.260000"),
                zone_row("In1.Cu", (1.0, 2.0, 3.0, 4.0), "0.255000"),
            ),
        )

        self.assertEqual(2, len(rows))
        front = next(row for row in rows if row["layer"] == ["F.Cu"])
        inner = next(row for row in rows if row["layer"] == ["In1.Cu"])
        self.assertEqual("0.250000", front["value"])
        self.assertEqual(2, front["raw"]["physical_measurement_count"])
        self.assertNotIn("physical_measurement_count", inner["raw"])

    def test_board_edge_reaggregation_preserves_all_layer_measurements(self):
        def partial(layers, measurements):
            return {
                "id": "pth-pad-uuid",
                "rule_key": "coppertoboardedge:coppertoboardedge",
                "item": "Copper-to-Board Edge",
                "value": measurements[0]["value"],
                "layer": list(layers),
                "color": "gold",
                "raw": {
                    "primary": {
                        "kind": "rect",
                        "through_hole": True,
                    },
                    "uuid_mapping": {
                        "status": "matched",
                        "id": "pth-pad-uuid",
                    },
                    "physical_measurement_count": len(measurements),
                    "per_layer_measurements": list(measurements),
                },
            }

        outer = [
            {"layer": ["F.Cu"], "value": "0.250000"},
            {"layer": ["B.Cu"], "value": "0.249999"},
        ]
        inner = [
            {"layer": ["In1.Cu"], "value": "0.250000"},
            {"layer": ["In2.Cu"], "value": "0.250000"},
            {"layer": ["In3.Cu"], "value": "0.250000"},
            {"layer": ["In4.Cu"], "value": "0.250000"},
        ]

        rows = aggregate_physical_native_results(
            "Copper-to-Board Edge",
            (partial(("F.Cu", "B.Cu"), outer), partial(
                ("In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu"), inner
            )),
        )

        self.assertEqual(1, len(rows))
        self.assertEqual(6, rows[0]["raw"]["physical_measurement_count"])
        self.assertEqual(
            ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu"],
            [
                measurement["layer"][0]
                for measurement in rows[0]["raw"]["per_layer_measurements"]
            ],
        )

    def test_ring_aggregation_uses_drill_identity_when_pad_diameters_differ(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        layers = ("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu")
        rows = []
        for index, layer in enumerate(layers):
            outer_layer = layer in ("F.Cu", "B.Cu")
            pad_diameter = 0.8 if outer_layer else 0.5
            ring = "0.080000" if layer == "In3.Cu" else (
                "0.250000" if outer_layer else "0.100000"
            )
            rows.append(
                {
                    "id": "board-{0}.gbr".format(layer),
                    "rule_key": "ringhole:pthannularring",
                    "item": "PTH Annular Ring",
                    "value": ring,
                    "layer": [layer],
                    "rule": "0.101600,0.127000,0.152400",
                    "color": "red" if ring == "0.080000" else "black",
                    "item_type": "gerber",
                    "source": "gerber",
                    "geometry_basis": "gerber_derived",
                    "raw": {
                        "file": "board-{0}.gbr".format(layer),
                        "primary": {
                            "item_type": "gerber",
                            "aperture_function": "ComponentPad",
                            "point": (10.0, 20.0),
                            "width": pad_diameter,
                        },
                        "related": {
                            "file": "board-PTH.drl",
                            "item_type": "drill",
                            "kind": "circle",
                            "point": (10.0, 20.0),
                            "diameter": 0.3,
                        },
                        "pad_size": (pad_diameter, pad_diameter),
                    },
                }
            )
        checks.native_results = {"RingHole": rows}

        mapped = checks.native_result_map()["RingHole"]
        physical_rows = [
            row for group in mapped["check"] for row in group["result"]
        ]

        self.assertEqual(6, mapped["checked_count"])
        self.assertEqual(1, mapped["displayed_count"])
        self.assertEqual(1, len(physical_rows))
        physical = physical_rows[0]
        self.assertEqual("0.080000", physical["value"])
        self.assertEqual("red", physical["color"])
        self.assertEqual(list(layers), physical["layer"])
        self.assertEqual(6, physical["raw"]["physical_measurement_count"])
        self.assertEqual(
            list(layers),
            [
                measurement["layer"][0]
                for measurement in physical["raw"]["per_layer_measurements"]
            ],
        )
        self.assertEqual(
            ["0.250000", "0.100000", "0.100000", "0.080000", "0.100000", "0.250000"],
            [
                measurement["value"]
                for measurement in physical["raw"]["per_layer_measurements"]
            ],
        )

    def test_ring_aggregation_keeps_distinct_drills_separate(self):
        def ring_row(layer, point, drill_file, layer_span):
            return {
                "id": "board-{0}-{1}.gbr".format(layer, drill_file),
                "rule_key": "ringhole:viaannularring",
                "item": "Via Annular Ring",
                "value": "0.090000",
                "layer": [layer],
                "rule": "0.101600,0.127000,0.152400",
                "color": "red",
                "item_type": "gerber",
                "source": "gerber",
                "geometry_basis": "gerber_derived",
                "raw": {
                    "file": "board-{0}.gbr".format(layer),
                    "primary": {
                        "item_type": "gerber",
                        "aperture_function": "ViaPad",
                        "point": point,
                        "width": 0.5,
                    },
                    "related": {
                        "file": drill_file,
                        "item_type": "drill",
                        "kind": "circle",
                        "point": point,
                        "diameter": 0.3,
                        "layer_span": layer_span,
                    },
                },
            }

        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.native_results = {
            "RingHole": [
                # One physical through hole represented on two copper layers.
                ring_row("F.Cu", (1.0, 2.0), "board-PTH.drl", (1, 6)),
                ring_row("B.Cu", (1.0, 2.0), "board-PTH.drl", (1, 6)),
                # A different position must remain a different hole.
                ring_row("F.Cu", (2.0, 2.0), "board-PTH.drl", (1, 6)),
                ring_row("B.Cu", (2.0, 2.0), "board-PTH.drl", (1, 6)),
                # Stacked blind holes may share position and diameter but are
                # distinct physical drills because their sources/spans differ.
                ring_row("F.Cu", (3.0, 2.0), "board-L1-L2.drl", (1, 2)),
                ring_row("In1.Cu", (3.0, 2.0), "board-L1-L2.drl", (1, 2)),
                ring_row("In2.Cu", (3.0, 2.0), "board-L3-L4.drl", (3, 4)),
                ring_row("In3.Cu", (3.0, 2.0), "board-L3-L4.drl", (3, 4)),
            ]
        }

        mapped = checks.native_result_map()["RingHole"]
        physical_rows = [
            row for group in mapped["check"] for row in group["result"]
        ]

        self.assertEqual(8, mapped["checked_count"])
        self.assertEqual(4, mapped["displayed_count"])
        self.assertEqual(4, len(physical_rows))
        self.assertEqual(
            [2, 2, 2, 2],
            sorted(
                row["raw"]["physical_measurement_count"]
                for row in physical_rows
            ),
        )

    def test_native_map_does_not_merge_overlapping_front_back_smd_geometry(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.native_results = {
            "Pad size": [
                {
                    "id": file_name,
                    "rule_key": "padsize:shortpads",
                    "item": "Short Pads",
                    "value": "0.300000",
                    "layer": [layer],
                    "rule": "0.203200,0.304800,0.508000",
                    "color": "gold",
                    "item_type": "gerber",
                    "source": "gerber",
                    "geometry_basis": "gerber_derived",
                    "raw": {
                        "file": file_name,
                        "primary": {
                            "aperture_function": "SMDPad",
                            "point": (10.0, 20.0),
                            "width": 0.3,
                            "layer": [layer],
                        },
                    },
                }
                for layer, file_name in (
                    ("F.Cu", "board-F_Cu.gbr"),
                    ("B.Cu", "board-B_Cu.gbr"),
                )
            ]
        }

        mapped = checks.native_result_map()["Pad size"]
        rows = [row for group in mapped["check"] for row in group["result"]]

        self.assertEqual(2, len(rows))
        self.assertEqual(2, mapped["checked_count"])
        self.assertEqual(2, mapped["displayed_count"])

    def test_native_map_reports_item_metrics_without_mixing_hole_units(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks.native_results = {
            "Hole Size": [
                {
                    "item": "Largest Drill Size",
                    "value": "0.300000",
                    "layer": ["Drl"],
                    "color": "black",
                    "rule": "4.000000,5.000000,6.000000",
                    "raw": {},
                },
                {
                    "item": "Aspect Ratio",
                    "value": "0.100000",
                    "layer": ["Drl"],
                    "color": "black",
                    "rule": "8.000000,10.000000,12.000000",
                    "raw": {},
                },
            ]
        }

        mapped = checks.native_result_map()["Hole Size"]

        self.assertEqual(0.3, mapped["display"])
        self.assertEqual(2, mapped["checked_count"])
        self.assertEqual(2, mapped["displayed_count"])
        self.assertEqual(
            "mm", mapped["item_summaries"]["Largest Drill Size"]["unit"]
        )
        self.assertEqual(
            "ratio", mapped["item_summaries"]["Aspect Ratio"]["unit"]
        )

    def test_pad_size_applies_each_shape_rule_reporting_limit(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))

        cases = (
            ("long-in", "Long Pads", 0.254, "0.152400,0.177800,0.254000"),
            ("long-out", "Long Pads", 0.255, "0.152400,0.177800,0.254000"),
            ("short-in", "Short Pads", 0.508, "0.203200,0.304800,0.508000"),
            ("short-out", "Short Pads", 0.509, "0.203200,0.304800,0.508000"),
        )
        for pad_id, item, value, rule in cases:
            checks._record_native_result(
                "Pad size",
                {
                    "item": item,
                    "item_type": "gerber",
                    "color": "black",
                    "value": "{0:.6f}".format(value),
                    "id": pad_id,
                    "rule": rule,
                    "raw": {},
                },
            )

        self.assertEqual(
            ["long-in", "short-in"],
            [row["id"] for row in checks.native_results["Pad size"]],
        )

    def test_aspect_ratio_keeps_distinct_normal_values_inside_rule_window(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))

        for index, value in enumerate((6.4, 6.4, 9.0, 11.0, 13.0)):
            finding = ScanFinding(
                "Aspect Ratio",
                "ratio",
                category="Hole Size",
                value=value,
                layer=["Drl"],
                raw={
                    "file": "board-PTH.drl",
                    "tool": index,
                    "diameter": 1.6 / value,
                    "board_thickness_mm": 1.6,
                },
            )
            checks._add_scan_finding(finding)

        result = checks.native_result_map()["Hole Size"]
        rows = [row for group in result["check"] for row in group["result"]]
        self.assertEqual([13.0, 11.0, 6.4], [float(row["value"]) for row in rows])
        self.assertEqual(["red", "gold", "black"], [row["color"] for row in rows])

    def test_gerber_via_ring_between_second_and_third_levels_is_normal(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        for flash_id, value in (("via-1", 0.15), ("via-2", 0.15), ("via-3", 0.15), ("outside", 0.16)):
            checks._add_scan_finding(
                ScanFinding(
                    "Via Annular Ring",
                    "via ring",
                    category="RingHole",
                    value=value,
                    layer=["F.Cu"],
                    raw={"file": "board-F_Cu.gbr", "flash_id": flash_id},
                )
            )

        ring = checks.native_result_map()["RingHole"]
        self.assertEqual(1, len(ring["check"]))
        details = ring["check"][0]["result"]
        self.assertEqual(3, len(details))
        self.assertEqual(
            ["via-1", "via-2", "via-3"],
            [detail["raw"]["flash_id"] for detail in details],
        )
        detail = details[0]
        self.assertEqual("Via Annular Ring", detail["item"])
        self.assertEqual("black", detail["color"])
        self.assertEqual("black", ring["color"])

    def test_region_to_pad_is_excluded_from_trace_to_pad_spacing(self):
        region = GerberPrimitive(
            "region", start=(0.0, 0.0), end=(2.0, 2.0),
            points=((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
            function="Conductor", net="GND",
        )
        pad = GerberPrimitive(
            "circle", center=(1.0, 1.0), width=0.5,
            is_flash=True, function="ComponentPad", net="SIG",
        )

        self.assertIsNone(export_scanners.copper_spacing_item(region, pad))

    def test_region_hole_is_excluded_from_copper_clearance(self):
        region = GerberPrimitive(
            "region", start=(0.0, 0.0), end=(10.0, 10.0),
            points=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
            holes=(((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)),),
        )
        pad = GerberPrimitive("circle", center=(5.0, 5.0), width=0.4, is_flash=True)

        self.assertAlmostEqual(0.8, primitive_gap(region, pad), places=6)

    def test_thresholded_region_gap_preserves_reportable_distances(self):
        region = GerberPrimitive(
            "region", start=(0.0, 0.0), end=(2.0, 2.0),
            points=((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
        )
        nearby = (
            GerberPrimitive("circle", center=(2.4, 1.0), width=0.4),
            GerberPrimitive(
                "segment", start=(2.4, 0.5), end=(2.4, 1.5), width=0.2
            ),
            GerberPrimitive(
                "region", start=(2.3, 0.0), end=(3.0, 2.0),
                points=((2.3, 0.0), (3.0, 0.0), (3.0, 2.0), (2.3, 2.0)),
            ),
        )

        for primitive in nearby:
            exact = primitive_gap(region, primitive)
            self.assertAlmostEqual(
                exact, primitive_gap_within(region, primitive, exact + 0.01)
            )
            self.assertEqual(
                float("inf"), primitive_gap_within(region, primitive, exact / 2.0)
            )

    def test_native_map_includes_computed_board_statistics(self):
        statistics = BoardStatistics(
            board_area_mm2=10000.0,
            drill_count=200,
            drill_density_per_m2=20000.0,
            surface_finish_area_mm2=1250.0,
            surface_finish_percent=12.5,
            test_point_count=321,
        )
        checks = ExportChecks(object(), board=object(), backend=object(), chinese=True)

        with mock.patch(
            "kicad_dfm.services.export_checks.calculate_board_statistics",
            return_value=statistics,
        ):
            result = checks.native_result_map()

        self.assertEqual("2.00万/m²", result["Drill Hole Density"]["display"])
        self.assertEqual("12.50%", result["Surface Finish Area"]["display"])
        self.assertEqual("321", result["Test Point Count"]["display"])

    def test_completed_spacing_scans_keep_separate_rule_subitems_without_findings(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks._completed_scanner_categories.update(
            ("Smallest Trace Spacing", "SMD Spacing")
        )

        spacing = checks.native_result_map()["Smallest Trace Spacing"]
        smd_spacing = checks.native_result_map()["SMD Spacing"]

        self.assertEqual(
            {
                "Trace Spacing",
                "Trace-to-Pad Spacing",
                "Pad-to-Pad Spacing",
                "BGA Pads",
            },
            set(spacing["item_summaries"]),
        )
        self.assertEqual(
            {"SMD Pad Spacing"},
            set(smd_spacing["item_summaries"]),
        )
        smd = smd_spacing["item_summaries"]["SMD Pad Spacing"]
        self.assertEqual("completed", smd["execution_status"])
        self.assertEqual("partial", smd["coverage"])
        self.assertEqual(0, smd["checked_count"])
        self.assertEqual(0, smd["displayed_count"])
        self.assertIsNone(smd["display"])
        self.assertEqual("black", smd["color"])
        self.assertEqual(
            "smdspacing:smdpadspacing", smd["rule_key"]
        )
        self.assertEqual(
            "0.152400,0.203200,0.254000",
            smd["rule"],
        )
        self.assertAlmostEqual(
            0.2032,
            checks._copper_spacing_reporting_limits()["SMD Pad Spacing"],
        )

    def test_location_fields_uses_bbox_centerline(self):
        fields = location_fields({"bbox": (1.0, 2.0, 5.0, 4.0)})

        self.assertEqual("1.000000", fields["sx"])
        self.assertEqual("3.000000", fields["sy"])
        self.assertEqual("5.000000", fields["ex"])
        self.assertEqual("3.000000", fields["ey"])
        vertical = location_fields({"bbox": (1.0, 2.0, 3.0, 8.0)})
        self.assertEqual("2.000000", vertical["sx"])
        self.assertEqual("2.000000", vertical["sy"])
        self.assertEqual("2.000000", vertical["ex"])
        self.assertEqual("8.000000", vertical["ey"])

    def test_grouped_native_results_keeps_source_and_geometry_separate(self):
        rows = [
            {
                "rule_key": "smallesttracewidth:smallesttracewidth",
                "item": "Smallest Trace Width",
                "value": "0.100",
                "layer": ["F.Cu"],
                "source": "gerber",
                "geometry_basis": "gerber_derived",
            },
            {
                "rule_key": "smallesttracewidth:smallesttracewidth",
                "item": "Smallest Trace Width",
                "value": "0.100",
                "layer": ["F.Cu"],
                "source": "kicad",
                "geometry_basis": "exact_kicad",
            },
        ]

        groups = grouped_native_results(rows)

        self.assertEqual(2, len(groups))

    def test_region_gap_uses_polygon_edges_not_bbox(self):
        region = GerberPrimitive(
            "region",
            start=(0.0, 0.0),
            end=(2.0, 2.0),
            points=((0.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
        )
        edge = GerberSegment((2.0, 0.0), (2.0, 0.4), width=0.0)

        self.assertAlmostEqual(1.131, primitive_segment_gap(region, edge), places=3)

    def test_simplify_polygon_points_removes_collinear_region_vertices(self):
        points = (
            (0.0, 0.0),
            (1.0, 0.0),
            (2.0, 0.0),
            (2.0, 1.0),
            (2.0, 2.0),
            (0.0, 2.0),
            (0.0, 0.0),
        )

        simplified = simplify_polygon_points(points)

        self.assertEqual(
            ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
            simplified,
        )

    def test_pad_size_ignores_drill_inside_round_pad_bbox_only(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.9, 0.9), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle",
                center=(0.0, 0.0),
                width=2.0,
                height=2.0,
                is_flash=True,
                function="SMDPad",
            )
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual([], findings)

    def test_smd_pad_size_uses_x2_smd_flashes_and_aspect_ratio(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect",
                    center=(0.0, 0.0),
                    width=0.3,
                    height=1.5,
                    is_flash=True,
                    function="SMDPad,CuDef",
                ),
                GerberPrimitive(
                    "circle",
                    center=(2.0, 0.0),
                    width=0.9,
                    height=0.9,
                    is_flash=True,
                    function="SMDPad,CuDef",
                ),
                GerberPrimitive(
                    "circle",
                    center=(4.0, 0.0),
                    width=0.4,
                    height=0.4,
                    is_flash=True,
                    function="ViaPad",
                ),
            )
        )

        findings = list(export_scanners.scan_smd_pad_size([scan]))

        self.assertEqual(
            [("Long Pads", 0.3), ("Short Pads", 0.9)],
            sorted((finding.item, finding.value) for finding in findings),
        )

    def test_smd_pad_size_keeps_every_pad_in_the_same_rule_item(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            GerberPrimitive(
                "circle",
                center=(index * 2.0, 0.0),
                width=0.1 + index * 0.01,
                is_flash=True,
                function="SMDPad,CuDef",
            )
            for index in range(3)
        )

        findings = list(export_scanners.scan_smd_pad_size([scan]))

        self.assertEqual(3, len(findings))
        self.assertEqual(["Short Pads"] * 3, [finding.item for finding in findings])

    def test_pad_drill_features_keep_every_matching_pad_and_ring(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for x in (0.0, 3.0):
            drill_scan.primitives.append(
                DrillPrimitive("circle", center=(x, 0.0), diameter=0.4)
            )
            copper_scan.primitives.append(
                GerberPrimitive(
                    "circle", center=(x, 0.0), width=1.0, is_flash=True
                )
            )

        findings = list(
            export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan])
        )

        self.assertEqual(2, sum(row.item == "Short Pads" for row in findings))
        self.assertEqual(2, sum(row.item == "PTH Annular Ring" for row in findings))

    def test_copper_to_board_edge_keeps_every_copper_object(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(
            GerberSegment((-10.0, 2.0), (10.0, 2.0), width=0.0)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.1
                ),
                GerberPrimitive(
                    "segment", start=(3.0, 0.5), end=(4.0, 0.5), width=0.1
                ),
            )
        )

        findings = list(
            export_scanners.scan_copper_to_board_edge([edge_scan, copper_scan])
        )

        self.assertEqual(2, len(findings))

    def test_hole_to_board_edge_classifies_pth_via_and_npth(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(GerberSegment((-2.0, 0.0), (4.0, 0.0)))

        plated = ExcellonScan("board-PTH.drl")
        plated.plated = True
        plated.primitives.extend(
            (
                DrillPrimitive(
                    "circle", center=(0.0, 0.5), diameter=0.2,
                    function="ComponentDrill",
                ),
                DrillPrimitive(
                    "circle", center=(1.0, 0.4), diameter=0.2,
                    function="ViaDrill",
                ),
            )
        )
        nonplated = ExcellonScan("board-NPTH.drl")
        nonplated.plated = False
        nonplated.primitives.append(
            DrillPrimitive("circle", center=(2.0, 0.3), diameter=0.2)
        )

        findings = list(
            export_scanners.scan_hole_to_board_edge(
                (plated, nonplated),
                (edge_scan,),
                {
                    "PTH-to-Board Edge": 1.0,
                    "Via-to-Board Edge": 1.0,
                    "NPTH-to-Board Edge": 1.0,
                },
            )
        )

        self.assertEqual(
            ["NPTH-to-Board Edge", "PTH-to-Board Edge", "Via-to-Board Edge"],
            sorted(finding.item for finding in findings),
        )
        self.assertEqual(
            [0.2, 0.3, 0.4],
            sorted(finding.value for finding in findings),
        )
        self.assertTrue(all(finding.category == "Hole-to-Board Edge" for finding in findings))

    def test_hole_to_board_edge_slot_uses_capsule_clearance(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(GerberSegment((-2.0, 0.0), (4.0, 0.0)))
        drill_scan = ExcellonScan("board-NPTH.drl")
        drill_scan.plated = False
        drill_scan.primitives.append(
            DrillPrimitive(
                "slot", start=(0.0, 0.4), end=(1.0, 0.4), diameter=0.2
            )
        )

        finding = next(
            export_scanners.scan_hole_to_board_edge(
                (drill_scan,),
                (edge_scan,),
                {"NPTH-to-Board Edge": 1.0},
            )
        )

        self.assertEqual("NPTH-to-Board Edge", finding.item)
        self.assertAlmostEqual(0.3, finding.value)

    def test_hole_to_board_edge_is_a_strict_export_category(self):
        self.assertIn("Hole-to-Board Edge", STRICT_SCANNER_CATEGORIES)

    def test_copper_to_board_edge_separates_smd_via_pth_trace_and_region(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(
            GerberSegment((-1.0, 2.0), (7.0, 2.0), width=0.0)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 1.0), width=0.4,
                    is_flash=True, function="ViaPad",
                ),
                GerberPrimitive(
                    "circle", center=(1.0, 1.0), width=0.6,
                    is_flash=True, function="ComponentPad",
                ),
                GerberPrimitive(
                    "rect", center=(2.0, 1.0), width=0.5, height=0.4,
                    is_flash=True, function="SMDPad",
                ),
                GerberPrimitive(
                    "rect", center=(3.0, 1.0), width=0.5, height=0.4,
                    is_flash=True, function="ComponentPad",
                ),
                GerberPrimitive(
                    "region", start=(4.0, 0.8), end=(4.5, 1.2),
                    points=((4.0, 0.8), (4.5, 0.8), (4.5, 1.2), (4.0, 1.2)),
                    function="Conductor",
                ),
                GerberPrimitive(
                    "segment", start=(5.0, 1.0), end=(5.5, 1.0),
                    width=0.1, function="Conductor",
                ),
            )
        )
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.primitives.extend(
            (
                DrillPrimitive("circle", center=(0.0, 1.0), diameter=0.2),
                DrillPrimitive("circle", center=(1.03, 1.0), diameter=0.2),
            )
        )

        findings = list(
            export_scanners.scan_copper_to_board_edge(
                [edge_scan, copper_scan], [drill_scan]
            )
        )

        self.assertEqual(
            [
                "Copper-to-Board Edge",
                "Copper-to-Board Edge",
                "SMD-to-Board Edge",
                "SMD-to-Board Edge",
                "Copper-to-Board Edge",
                "Trace-to-Board Edge",
            ],
            [finding.item for finding in findings],
        )

    def test_copper_to_board_edge_classifies_surface_role_pads_as_smd(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(
            GerberSegment((-2.0, 2.0), (8.0, 2.0), width=0.2)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for index, function in enumerate(
            (
                "TestPad",
                "BgaPad",
                "ConnectorPad",
                "HeatsinkPad",
                "FiducialPad",
            )
        ):
            copper_scan.primitives.append(
                GerberPrimitive(
                    "circle",
                    center=(float(index), 1.0),
                    width=0.4,
                    is_flash=True,
                    function=function,
                    component="P{0}".format(index),
                    object_id="P{0},1".format(index),
                    flash_id=str(index),
                )
            )

        findings = list(
            export_scanners.scan_copper_to_board_edge(
                [edge_scan, copper_scan]
            )
        )

        self.assertEqual(5, len(findings))
        self.assertEqual(
            {"SMD-to-Board Edge"},
            {finding.item for finding in findings},
        )
        # Profile aperture width is plotting metadata.  Clearance is measured
        # to the routed centreline, not to the ink edge of a 0.2 mm stroke.
        self.assertTrue(all(abs(finding.value - 0.8) < 1e-9 for finding in findings))

    def test_copper_to_board_edge_drilled_testpad_is_not_smd(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(
            GerberSegment((-2.0, 2.0), (2.0, 2.0), width=0.0)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle",
                center=(0.0, 1.0),
                width=0.6,
                is_flash=True,
                function="TestPad",
                object_id="TP1,1",
                flash_id="1",
            )
        )
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 1.0), diameter=0.3)
        )

        finding = next(
            export_scanners.scan_copper_to_board_edge(
                [edge_scan, copper_scan], [drill_scan]
            )
        )

        self.assertEqual("Copper-to-Board Edge", finding.item)
        self.assertTrue(finding.raw["primary"]["through_hole"])

    def test_copper_to_board_edge_excludes_every_primitive_of_composite_pth_pad(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(
            GerberSegment((-2.0, 2.0), (2.0, 2.0), width=0.0)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(0.0, 1.0), width=0.5, height=1.0,
                    is_flash=True, function="ComponentPad",
                    object_id="J2,MP1,MP1", flash_id="1177:0",
                ),
                GerberPrimitive(
                    "circle", center=(0.25, 1.4), width=0.2,
                    is_flash=True, function="ComponentPad",
                    object_id="J2,MP1,MP1", flash_id="1177:0",
                ),
                GerberPrimitive(
                    "segment", start=(-0.25, 0.6), end=(0.25, 0.6), width=0.2,
                    is_flash=True, function="ComponentPad",
                    object_id="J2,MP1,MP1", flash_id="1177:0",
                ),
            )
        )
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.primitives.append(
            DrillPrimitive(
                "slot", start=(0.0, 0.7), end=(0.0, 1.3), diameter=0.2
            )
        )

        findings = list(
            export_scanners.scan_copper_to_board_edge(
                [edge_scan, copper_scan], [drill_scan]
            )
        )

        self.assertEqual(1, len(findings))
        self.assertEqual(
            {"Copper-to-Board Edge"},
            {finding.item for finding in findings},
        )
        drill_identity = findings[0].raw["primary"]["drill_identity"]
        self.assertEqual("slot", drill_identity["kind"])
        self.assertEqual(((0.0, 0.7), (0.0, 1.3)), drill_identity["segment"])
        self.assertEqual(0.2, drill_identity["diameter"])

    def test_copper_to_board_edge_merges_composite_smd_pad_to_one_result(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(
            GerberSegment((-2.0, 2.0), (2.0, 2.0), width=0.0)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(0.0, 1.0), width=0.5, height=0.5,
                    is_flash=True, function="SMDPad",
                    object_id="U1,1,GND", flash_id="1177:0",
                ),
                GerberPrimitive(
                    "circle", center=(0.25, 1.2), width=0.2,
                    is_flash=True, function="SMDPad",
                    object_id="U1,1,GND", flash_id="1177:0",
                ),
            )
        )

        findings = list(
            export_scanners.scan_copper_to_board_edge([edge_scan, copper_scan])
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("SMD-to-Board Edge", findings[0].item)
        self.assertAlmostEqual(0.7, findings[0].value)

    def test_copper_to_board_edge_classifies_x2_smd_region_as_smd(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(
            GerberSegment((-2.0, 2.0), (2.0, 2.0), width=0.0)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "region",
                start=(-0.3, 0.8),
                end=(0.3, 1.2),
                points=((-0.3, 0.8), (0.3, 0.8), (0.3, 1.2), (-0.3, 1.2)),
                function="SMDPad",
                component="U1",
                object_id="U1,1,GND",
            )
        )

        findings = list(
            export_scanners.scan_copper_to_board_edge([edge_scan, copper_scan])
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("SMD-to-Board Edge", findings[0].item)
        self.assertAlmostEqual(0.8, findings[0].value)

    def test_copper_to_board_edge_reporting_limit_skips_far_normal_objects(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(
            GerberSegment((-2.0, 2.0), (4.0, 2.0), width=0.0)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0),
                    width=0.1, function="Conductor",
                ),
                GerberPrimitive(
                    "segment", start=(2.0, 1.7), end=(3.0, 1.7),
                    width=0.1, function="Conductor",
                ),
            )
        )

        findings = list(
            export_scanners.scan_copper_to_board_edge(
                [edge_scan, copper_scan],
                reporting_limits={"Trace-to-Board Edge": 0.381},
            )
        )

        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.25, findings[0].value)
        self.assertEqual("board_edge", findings[0].raw["related"]["kind"])

    def test_copper_to_board_edge_finds_left_edge_without_rectangular_assumption(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.extend(
            (
                GerberSegment((0.0, 0.0), (0.0, 10.0), width=0.0),
                GerberSegment((100.0, 0.0), (100.0, 10.0), width=0.0),
            )
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle", center=(5.0, 5.0), width=1.0,
                is_flash=True, function="SMDPad",
            )
        )

        finding = next(
            export_scanners.scan_copper_to_board_edge([edge_scan, copper_scan])
        )

        self.assertAlmostEqual(4.5, finding.value)
        self.assertEqual(
            ((0.0, 0.0), (0.0, 10.0)),
            finding.raw["related"]["segment"],
        )

    def test_board_edge_arc_tessellation_bounds_large_radius_error(self):
        radius = 35.0
        delta = math.radians(56.0)
        segments = gerber_arc_segments(
            (radius, 0.0),
            (radius * math.cos(delta), radius * math.sin(delta)),
            (-radius, 0.0),
            "ccw",
            max_sagitta=0.001,
        )

        maximum_sagitta = max(
            radius
            - math.hypot(
                (start[0] + end[0]) / 2.0,
                (start[1] + end[1]) / 2.0,
            )
            for start, end in segments
        )
        self.assertLessEqual(maximum_sagitta, 0.001000001)
        self.assertGreater(len(segments), 50)

    def test_outline_closure_checks_all_open_endpoints(self):
        segments = (
            GerberSegment((0.0, 0.0), (1.0, 0.0)),
            GerberSegment((1.01, 0.0), (2.0, 0.0)),
        )

        self.assertEqual(2, len(outline_open_points(segments, 0.05)))
        self.assertAlmostEqual(2.0, outline_open_gap(segments, 0.05))

    def test_smd_pad_size_ignores_composite_without_known_logical_size(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect",
                    center=(0.0, 0.0),
                    width=1.0,
                    height=0.3,
                    is_flash=True,
                    function="SMDPad,CuDef",
                    object_id="U1,1,GND",
                ),
                GerberPrimitive(
                    "circle",
                    center=(0.5, 0.0),
                    width=0.15,
                    is_flash=True,
                    function="SMDPad,CuDef",
                    object_id="U1,1,GND",
                ),
            )
        )

        findings = list(export_scanners.scan_smd_pad_size([scan]))

        self.assertEqual([], findings)

    def test_smd_pad_size_ignores_single_region_x2_custom_pad(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(
            GerberPrimitive(
                "region",
                start=(-0.5, -0.15),
                end=(0.5, 0.15),
                center=(0.0, 0.0),
                width=1.0,
                height=0.3,
                is_flash=True,
                function="SMDPad,CuDef",
                object_id="U1,1,GND",
            )
        )

        findings = list(export_scanners.scan_smd_pad_size([scan]))

        self.assertEqual([], findings)

    def test_smd_pad_size_merges_rotated_roundrect_macro_fragments(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        members = (
            GerberPrimitive(
                "region",
                start=(-0.21, -0.21),
                end=(0.21, 0.21),
                center=(0.0, 0.0),
                width=0.42,
                height=0.42,
                is_flash=True,
                function="SMDPad,CuDef",
                object_id="U1,1,SIG",
                flash_id="1:0",
            ),
            GerberPrimitive(
                "circle",
                center=(0.17, 0.17),
                width=0.11,
                is_flash=True,
                function="SMDPad,CuDef",
                object_id="U1,1,SIG",
                flash_id="1:0",
            ),
        )
        for member in members:
            member.shape_width = 0.6
            member.shape_height = 0.22
        scan.primitives.extend(members)

        findings = list(export_scanners.scan_smd_pad_size([scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("Long Pads", findings[0].item)
        self.assertEqual(0.22, findings[0].value)
        self.assertEqual((0.6, 0.22), findings[0].raw["pad_size"])

    def test_centerless_macro_member_is_part_of_logical_smd_pad(self):
        copper = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        members = (
            GerberPrimitive(
                "region",
                start=(-0.5, -0.1),
                end=(-0.05, 0.1),
                points=((-0.5, -0.1), (-0.05, -0.1), (-0.05, 0.1), (-0.5, 0.1)),
                is_flash=True,
                function="SMDPad",
                component="C1",
                object_id="C1,1,VDD",
                flash_id="1:0",
            ),
            GerberPrimitive(
                "segment",
                start=(-0.1, 0.0),
                end=(0.4, 0.0),
                width=0.2,
                is_flash=True,
                function="SMDPad",
                component="C1",
                object_id="C1,1,VDD",
                flash_id="1:0",
            ),
        )
        for member in members:
            member.shape_width = 0.9
            member.shape_height = 0.2
        copper.primitives.extend(members)
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.plated = True
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4)
        )

        findings = [
            finding
            for finding in export_scanners.scan_pad_drill_features(
                [drill_scan], [copper]
            )
            if finding.category == "Holes on SMD Pads"
        ]

        self.assertEqual(1, len(findings))
        self.assertEqual("Via on SMD Pad", findings[0].item)
        self.assertEqual(0.2, findings[0].value)
        self.assertEqual("composite", findings[0].raw["related"]["kind"])

    def test_logical_macro_uses_member_union_not_bounding_rectangle(self):
        copper = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper.primitives.extend(
            GerberPrimitive(
                "circle",
                center=(center, 0.0),
                width=0.4,
                is_flash=True,
                function="SMDPad",
                component="C1",
                object_id="C1,1,VDD",
                flash_id="1:0",
            )
            for center in (-1.0, 1.0)
        )
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.plated = True
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        )

        findings = list(
            export_scanners.scan_pad_drill_features([drill_scan], [copper])
        )

        self.assertNotIn("Holes on SMD Pads", [finding.category for finding in findings])

    def test_kicad_roundrect_macro_preserves_unrotated_logical_pad_size(self):
        line = (
            "%ADD120RoundRect,0.055000X0.134350X0.212132X-0.212132X"
            "-0.134350X-0.134350X-0.212132X0.212132X0.134350X0*%"
        )

        _code, aperture = parse_gerber_aperture(
            line,
            "mm",
            {"ROUNDRECT": "1,1,0.1,0,0"},
        )

        self.assertAlmostEqual(0.6, max(aperture.logical_size), places=6)
        self.assertAlmostEqual(0.22, min(aperture.logical_size), places=6)

    def test_kicad_rotrect_macro_applies_rotation_to_flash_geometry(self):
        _code, aperture = parse_gerber_aperture(
            "%ADD10RotRect,0.250000X0.600000X45.000000*%",
            "mm",
            {"ROTRECT": "21,1,$1,$2,0,0,$3"},
        )

        _polarity, primitive = aperture.macro_primitives[0]

        self.assertEqual("region", primitive.kind)
        self.assertEqual(4, len(primitive.points))
        expected_span = (0.25 + 0.6) / math.sqrt(2.0)
        self.assertAlmostEqual(expected_span, primitive.bbox[2] - primitive.bbox[0], places=6)
        self.assertAlmostEqual(expected_span, primitive.bbox[3] - primitive.bbox[1], places=6)
        self.assertEqual((0.25, 0.6), aperture.logical_size)

    def test_kicad_outline_macro_reads_closing_point_before_rotation(self):
        body = (
            "4,1,4,-1.0,-0.5,1.0,-0.5,1.0,0.5,-1.0,0.5,"
            "-1.0,-0.5,$1"
        )
        _code, aperture = parse_gerber_aperture(
            "%ADD10FreePoly,90.000000*%",
            "mm",
            {"FREEPOLY": body},
        )

        _polarity, primitive = aperture.macro_primitives[0]

        self.assertEqual("region", primitive.kind)
        self.assertEqual(5, len(primitive.points))
        self.assertAlmostEqual(1.0, primitive.bbox[2] - primitive.bbox[0], places=6)
        self.assertAlmostEqual(2.0, primitive.bbox[3] - primitive.bbox[1], places=6)

    def test_signal_integrity_scans_conductor_acute_and_ignores_nonconductor(self):
        scan = GerberScan("B_Cu.gbr", ["B.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment",
                    start=(0.0, 0.0),
                    end=(1.0, 0.0),
                    width=0.2,
                    function="Conductor",
                    net="A",
                ),
                GerberPrimitive(
                    "segment",
                    start=(0.0, 0.0),
                    end=(1.0, 1.0),
                    width=0.2,
                    function="Conductor",
                    net="A",
                ),
                GerberPrimitive(
                    "segment",
                    start=(10.0, 0.0),
                    end=(11.0, 0.0),
                    width=0.2,
                    function="NonConductor",
                ),
                GerberPrimitive(
                    "segment",
                    start=(11.0, 0.0),
                    end=(12.0, 0.0),
                    width=0.2,
                    function="NonConductor",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertEqual(1, sum(finding.item == "Acute Angle Traces" for finding in findings))
        self.assertNotIn("Floating Copper", [finding.item for finding in findings])
        self.assertTrue(
            all(
                finding.raw.get("primary", {}).get("aperture_function")
                != "NonConductor"
                for finding in findings
            )
        )

    def test_signal_integrity_does_not_treat_nonconductor_as_electrical_signal(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            GerberPrimitive(
                "segment",
                start=(index * 2.0, 0.0),
                end=(index * 2.0 + 0.5, 0.0),
                width=0.2,
                function="NonConductor",
            )
            for index in range(11)
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertEqual([], findings)

    def test_signal_integrity_reports_more_than_twenty_acute_primitives(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for index in range(21):
            origin = index * 3.0
            scan.primitives.extend(
                (
                    GerberPrimitive(
                        "segment",
                        start=(origin, 0.0),
                        end=(origin + 1.0, 0.0),
                        width=0.2,
                        function="Conductor",
                        net=str(index),
                    ),
                    GerberPrimitive(
                        "segment",
                        start=(origin, 0.0),
                        end=(origin + 1.0, 1.0),
                        width=0.2,
                        function="Conductor",
                        net=str(index),
                    ),
                )
            )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertEqual(
            21,
            sum(finding.item == "Acute Angle Traces" for finding in findings),
        )

    def test_signal_integrity_scans_inner_copper_layers(self):
        scan = GerberScan("In1_Cu.gbr", ["In1.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 1.0), width=0.2,
                    function="Conductor", net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))
        acute = [finding for finding in findings if finding.item == "Acute Angle Traces"]

        self.assertEqual(1, len(acute))
        self.assertEqual(["In1.Cu"], acute[0].layer)

    def test_acute_angle_result_contains_both_trace_geometries(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 1.0), width=0.2,
                    function="Conductor", net="A",
                ),
            )
        )

        finding = next(
            finding for finding in export_scanners.scan_signal_integrity([scan])
            if finding.item == "Acute Angle Traces"
        )

        self.assertEqual(((0.0, 0.0), (1.0, 0.0)), finding.raw["primary"]["segment"])
        self.assertEqual(((0.0, 0.0), (1.0, 1.0)), finding.raw["related"]["segment"])

    def test_signal_integrity_ignores_acute_junction_covered_by_same_net_copper(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 1.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.6, is_flash=True,
                    function="ComponentPad", net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertNotIn("Acute Angle Traces", [finding.item for finding in findings])

    def test_signal_integrity_ignores_overlapping_collinear_segments(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(2.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertNotIn("Acute Angle Traces", [finding.item for finding in findings])

    def test_nonconductor_component_is_not_reported_as_floating_signal(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment",
                    start=(0.0, 0.0),
                    end=(1.0, 0.0),
                    width=0.2,
                    function="NonConductor",
                ),
                GerberPrimitive(
                    "segment",
                    start=(1.0, 0.0),
                    end=(3.0, 0.0),
                    width=0.2,
                    function="NonConductor",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertNotIn("Floating Copper", [finding.item for finding in findings])

    def test_signal_integrity_does_not_report_nonconductor_touching_conductor(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment",
                    start=(0.0, 0.0),
                    end=(1.0, 0.0),
                    width=0.2,
                    function="NonConductor",
                ),
                GerberPrimitive(
                    "segment",
                    start=(0.5, -1.0),
                    end=(0.5, 1.0),
                    width=0.2,
                    function="Conductor",
                    net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertNotIn("Floating Copper", [finding.item for finding in findings])

    def test_signal_integrity_reports_x2_dangling_track(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(
            GerberPrimitive(
                "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                function="Conductor", net="A",
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))
        dangling = [finding for finding in findings if finding.item == "Dangling Tracks"]

        self.assertEqual(1, len(dangling))
        self.assertEqual(((0.0, 0.0), (1.0, 0.0)), dangling[0].raw["dangling_endpoints"])

    def test_signal_integrity_accepts_track_connected_to_same_net_pads(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.5, is_flash=True,
                    function="ComponentPad", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(1.0, 0.0), width=0.5, is_flash=True,
                    function="ComponentPad", net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertNotIn("Dangling Tracks", [finding.item for finding in findings])

    def test_signal_integrity_uses_track_endcap_for_pad_connection(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(-0.2, 0.0), width=0.25, is_flash=True,
                    function="ComponentPad", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(1.2, 0.0), width=0.25, is_flash=True,
                    function="ComponentPad", net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertNotIn("Dangling Tracks", [finding.item for finding in findings])

    def test_signal_integrity_reports_one_unconnected_via_across_layers(self):
        front = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        back = GerberScan("B_Cu.gbr", ["B.Cu"], is_copper=True)
        for scan in (front, back):
            scan.primitives.append(
                GerberPrimitive(
                    "circle", center=(1.0, 1.0), width=0.6, is_flash=True,
                    function="ViaPad", net="A",
                )
            )

        findings = list(export_scanners.scan_signal_integrity([front, back]))
        vias = [finding for finding in findings if finding.item == "Unconnected Vias"]

        self.assertEqual(1, len(vias))
        self.assertEqual(["F.Cu", "B.Cu"], vias[0].layer)

    def test_signal_integrity_accepts_via_connected_on_one_copper_layer(self):
        front = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        back = GerberScan("B_Cu.gbr", ["B.Cu"], is_copper=True)
        for scan in (front, back):
            scan.primitives.append(
                GerberPrimitive(
                    "circle", center=(1.0, 1.0), width=0.6, is_flash=True,
                    function="ViaPad", net="A",
                )
            )
        front.primitives.append(
            GerberPrimitive(
                "segment", start=(1.0, 1.0), end=(2.0, 1.0), width=0.2,
                function="Conductor", net="A",
            )
        )

        findings = list(export_scanners.scan_signal_integrity([front, back]))

        self.assertNotIn("Unconnected Vias", [finding.item for finding in findings])

    def test_signal_integrity_reports_disconnected_x2_net_component(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(10.0, 0.0), end=(11.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertEqual(1, sum(finding.item == "Trace Mssing" for finding in findings))

    def test_signal_integrity_joins_inner_component_pad_without_x2_object_id(self):
        front = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        inner = GerberScan("In1_Cu.gbr", ["In1.Cu"], is_copper=True)
        front.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.8, is_flash=True,
                    function="ComponentPad", object_id="J1,1", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
            )
        )
        inner.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.8, is_flash=True,
                    function="ComponentPad", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(0.0, 1.0), width=0.2,
                    function="Conductor", net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([front, inner]))

        self.assertNotIn("Trace Mssing", [finding.item for finding in findings])

    def test_signal_integrity_ignores_split_no_connect_net(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="unconnected-(J1-Pad1)",
                ),
                GerberPrimitive(
                    "segment", start=(10.0, 0.0), end=(11.0, 0.0), width=0.2,
                    function="Conductor", net="unconnected-(J1-Pad1)",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([scan]))

        self.assertNotIn("Trace Mssing", [finding.item for finding in findings])

    def test_isolated_via_is_not_duplicated_as_trace_missing(self):
        front = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        front.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.2,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(10.0, 0.0), width=0.6, is_flash=True,
                    function="ViaPad", net="A",
                ),
            )
        )

        findings = list(export_scanners.scan_signal_integrity([front]))

        self.assertEqual(1, sum(finding.item == "Unconnected Vias" for finding in findings))
        self.assertEqual(0, sum(finding.item == "Trace Mssing" for finding in findings))

    def test_missing_smask_opening_detects_uncovered_smd_pad(self):
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper.primitives.append(
            GerberPrimitive(
                "rect", center=(1.0, 1.0), width=0.8, height=0.4, is_flash=True,
                function="SMDPad", net="A", object_id="U1,1",
            )
        )

        findings = list(export_scanners.scan_missing_smask_openings([], [copper, mask]))

        self.assertEqual(["Missing SMask Opening"], [finding.item for finding in findings])

    def test_missing_smask_opening_accepts_pad_center_covered_by_mask(self):
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper.primitives.append(
            GerberPrimitive(
                "rect", center=(1.0, 1.0), width=0.8, height=0.4, is_flash=True,
                function="SMDPad", net="A", object_id="U1,1",
            )
        )
        mask.primitives.append(
            GerberPrimitive("rect", center=(1.0, 1.0), width=1.0, height=0.6, is_flash=True)
        )

        findings = list(export_scanners.scan_missing_smask_openings([], [copper, mask]))

        self.assertEqual([], findings)

    def test_missing_smask_does_not_merge_separate_pads_with_repeated_x2_id(self):
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        for center in ((1.0, 1.0), (11.0, 1.0)):
            copper.primitives.append(
                GerberPrimitive(
                    "rect",
                    center=center,
                    width=1.0,
                    height=1.0,
                    is_flash=True,
                    function="ComponentPad",
                    object_id="J1,0",
                )
            )
            mask.primitives.append(
                GerberPrimitive(
                    "rect",
                    center=center,
                    width=1.2,
                    height=1.2,
                    is_flash=True,
                )
            )

        findings = list(
            export_scanners.scan_missing_smask_openings([], [copper, mask])
        )

        self.assertEqual([], findings)

    def test_solder_mask_analysis_reports_bridge_width(self):
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        mask.primitives.extend(
            (
                GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True),
                GerberPrimitive("rect", center=(1.1, 0.0), width=1.0, height=1.0, is_flash=True),
            )
        )

        findings = list(
            export_scanners.scan_solder_mask_analysis(
                [mask], {"Solder Mask Bridge": 0.2}
            )
        )

        bridge = [row for row in findings if row.item == "Solder Mask Bridge"]
        self.assertEqual(1, len(bridge))
        self.assertAlmostEqual(0.1, bridge[0].value)
        self.assertEqual(["F.Mask"], bridge[0].layer)

    def test_solder_mask_bridge_ignores_drawn_mask_graphic_near_ep_flash(self):
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(-1.0, 0.6), end=(1.0, 0.6), width=0.1
                ),
                GerberPrimitive(
                    "rect", center=(0.0, 0.0), width=1.0, height=1.0,
                    is_flash=True, flash_id="ep:0",
                ),
            )
        )
        copper.primitives.append(
            GerberPrimitive(
                "rect", center=(0.0, 0.0), width=0.9, height=0.9,
                is_flash=True, function="SMDPad", net="GND",
                component="U6", object_id="U6,41",
            )
        )

        findings = list(
            export_scanners.scan_solder_mask_analysis(
                [mask, copper], {"Solder Mask Bridge": 0.2}
            )
        )

        self.assertEqual([], [row for row in findings if row.item == "Solder Mask Bridge"])

    def test_solder_mask_bridge_merges_all_members_of_one_macro_flash(self):
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        mask.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=1.0,
                    is_flash=True, flash_id="42:0",
                ),
                GerberPrimitive(
                    "circle", center=(1.1, 0.0), width=1.0,
                    is_flash=True, flash_id="42:0",
                ),
            )
        )

        findings = list(
            export_scanners.scan_solder_mask_analysis(
                [mask], {"Solder Mask Bridge": 0.2}
            )
        )

        self.assertEqual([], [row for row in findings if row.item == "Solder Mask Bridge"])

    def test_solder_mask_bridge_uses_copper_pad_anchors_for_location(self):
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        for center, object_id, net, flash_id in (
            ((0.0, 0.0), "U6,1", "A", "1:0"),
            ((1.1, 0.0), "U6,2", "B", "2:0"),
        ):
            mask.primitives.append(
                GerberPrimitive(
                    "rect", center=center, width=1.0, height=1.0,
                    is_flash=True, flash_id=flash_id,
                )
            )
            copper.primitives.append(
                GerberPrimitive(
                    "rect", center=center, width=0.8, height=0.8,
                    is_flash=True, function="SMDPad", net=net,
                    component="U6", object_id=object_id,
                )
            )

        bridge = next(
            row
            for row in export_scanners.scan_solder_mask_analysis(
                [mask, copper], {"Solder Mask Bridge": 0.2}
            )
            if row.item == "Solder Mask Bridge"
        )

        self.assertEqual("U6,1", bridge.raw["primary"]["object_id"])
        self.assertEqual("U6,2", bridge.raw["related"]["object_id"])
        self.assertIn("segment", bridge.raw)
        self.assertEqual("F.Mask", bridge.raw["mask_primary"]["layer"][0])

    def test_solder_mask_analysis_reports_opening_near_other_net_trace(self):
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(0.0, 0.0), width=0.6, height=0.6,
                    is_flash=True, function="SMDPad", net="A",
                ),
                GerberPrimitive(
                    "segment", start=(0.54, 0.0), end=(1.5, 0.0), width=0.02,
                    function="Conductor", net="B",
                ),
            )
        )

        findings = list(
            export_scanners.scan_solder_mask_analysis(
                [mask, copper], {"Solder Mask Covers Trace": 0.05}
            )
        )

        covered = [row for row in findings if row.item == "Solder Mask Covers Trace"]
        self.assertEqual(1, len(covered))
        self.assertAlmostEqual(0.03, covered[0].value)
        self.assertEqual("B", covered[0].raw["net"])
        self.assertEqual(("A",), covered[0].raw["opening_nets"])

    def test_solder_mask_analysis_reports_one_opening_over_multiple_nets(self):
        mask = GerberScan("MaskBottom.gbr", ["B.Mask"])
        copper = GerberScan("CuBottom.gbr", ["B.Cu"], is_copper=True)
        mask.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=3.0, height=1.0, is_flash=True)
        )
        copper.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(-0.5, 0.0), width=0.5, height=0.5,
                    is_flash=True, function="SMDPad", net="A",
                ),
                GerberPrimitive(
                    "rect", center=(0.5, 0.0), width=0.5, height=0.5,
                    is_flash=True, function="SMDPad", net="B",
                ),
            )
        )

        findings = list(export_scanners.scan_solder_mask_analysis([mask, copper]))

        multiple = [
            row for row in findings
            if row.item == "Solder Mask Covers Multiple Nets"
        ]
        self.assertEqual(1, len(multiple))
        self.assertEqual(("A", "B"), multiple[0].raw["nets"])
        self.assertEqual(["B.Mask"], multiple[0].layer)

    def test_solder_mask_analysis_does_not_report_trace_for_multi_net_opening(self):
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask.primitives.append(
            GerberPrimitive(
                "rect", center=(0.0, 0.0), width=3.0, height=1.0,
                is_flash=True, flash_id="1:0",
            )
        )
        copper.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(-0.5, 0.0), width=0.5, height=0.5,
                    is_flash=True, function="SMDPad", net="A",
                ),
                GerberPrimitive(
                    "rect", center=(0.5, 0.0), width=0.5, height=0.5,
                    is_flash=True, function="SMDPad", net="B",
                ),
                GerberPrimitive(
                    "segment", start=(-2.0, 0.0), end=(2.0, 0.0), width=0.1,
                    function="Conductor", net="C",
                ),
            )
        )

        findings = list(
            export_scanners.scan_solder_mask_analysis(
                [mask, copper], {"Solder Mask Covers Trace": 0.1}
            )
        )

        self.assertEqual(
            1,
            len([row for row in findings if row.item == "Solder Mask Covers Multiple Nets"]),
        )
        self.assertEqual(
            [], [row for row in findings if row.item == "Solder Mask Covers Trace"]
        )

    def test_solder_mask_analysis_does_not_treat_copper_region_as_trace(self):
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(0.0, 0.0), width=0.5, height=0.5,
                    is_flash=True, function="SMDPad", net="A",
                ),
                GerberPrimitive(
                    "region",
                    start=(-10.0, -10.0),
                    end=(10.0, 10.0),
                    points=((-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)),
                    net="B",
                ),
            )
        )

        findings = list(
            export_scanners.scan_solder_mask_analysis(
                [mask, copper], {"Solder Mask Covers Trace": 0.05}
            )
        )

        self.assertEqual([], findings)

    def test_castellated_hole_detects_drill_intersecting_edge(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.1, 1.0), diameter=0.4)
        )
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        edge_scan.segments.append(GerberSegment((0.0, 0.0), (0.0, 2.0)))

        findings = list(export_scanners.scan_castellated_holes([drill_scan], [edge_scan]))

        self.assertEqual(["Castellated Holes"], [finding.item for finding in findings])

    def test_via_pad_ring_is_classified_as_via_annular_ring(self):
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan = ExcellonScan("board.drl")
        pad = GerberPrimitive(
            "circle", center=(0.0, 0.0), width=0.8, is_flash=True,
            function="ViaPad", net="A",
        )
        drill = DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4)

        finding = export_scanners.ring_hole_finding(
            0.2, copper_scan, pad, drill_scan, drill
        )

        self.assertEqual("Via Annular Ring", finding.item)

    def test_export_scanners_do_not_expose_retired_via_in_pad_check(self):
        self.assertFalse(hasattr(export_scanners, "scan_via_in_pad"))

    def test_pad_size_detects_drill_edge_overlap_when_center_is_outside_pad(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(1.1, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle",
                center=(0.0, 0.0),
                width=2.0,
                height=2.0,
                is_flash=True,
            )
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Short Pads", "PTH Annular Ring"], [finding.item for finding in findings])

    def test_pad_size_includes_slot_drill_overlap(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(
            DrillPrimitive("slot", start=(-0.5, 0.0), end=(0.5, 0.0), diameter=0.3)
        )
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.2, height=0.8, is_flash=True)
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Long Pads"], [finding.item for finding in findings])
        self.assertEqual(0.8, findings[0].value)

    def test_clear_mask_removes_fully_covered_pad_from_pad_checks(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.2, height=1.2, is_flash=True)
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual([], findings)

    def test_pad_ring_uses_aperture_hole_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=0.6, height=0.6, is_flash=True)
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Short Pads", "PTH Annular Ring"], [finding.item for finding in findings])
        self.assertEqual(1.0, findings[0].value)
        self.assertEqual(0.2, findings[1].value)

    def test_pad_size_uses_rectangular_aperture_hole_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.2, height=0.8, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=0.6, height=0.3, is_flash=True)
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Long Pads"], [finding.item for finding in findings])
        self.assertEqual(0.8, findings[0].value)

    def test_pad_size_uses_largest_complete_clear_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.2, height=0.9, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=0.4, height=0.3, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=0.7, height=0.5, is_flash=True)
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Long Pads"], [finding.item for finding in findings])
        self.assertEqual(0.9, findings[0].value)

    def test_pad_size_uses_outer_shorter_side_with_aperture_hole(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.6, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=0.6, height=0.7, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=0.8, height=0.6, is_flash=True)
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Long Pads"], [finding.item for finding in findings])
        self.assertEqual(1.0, findings[0].value)

    def test_pad_size_uses_slot_clear_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(
            DrillPrimitive("slot", start=(-0.4, 0.0), end=(0.4, 0.0), diameter=0.2)
        )
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.4, height=0.8, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("segment", start=(-0.4, 0.0), end=(0.4, 0.0), width=0.4)
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Long Pads"], [finding.item for finding in findings])
        self.assertEqual(0.8, findings[0].value)

    def test_pad_size_ignores_partial_clear_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.2, 0.0), width=0.6, height=0.6, is_flash=True)
        )

        findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Short Pads", "PTH Annular Ring"], [finding.item for finding in findings])
        self.assertEqual(1.0, findings[0].value)
        self.assertEqual(0.3, findings[1].value)

    def test_drill_to_copper_detects_slot_overlap_with_region(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(
            DrillPrimitive("slot", start=(0.6, 0.8), end=(1.6, 0.8), diameter=0.3)
        )
        copper_scan.primitives.append(
            GerberPrimitive(
                "region",
                start=(0.0, 0.0),
                end=(2.0, 2.0),
                points=((0.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
            )
        )

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("NPTH-to-Copper", findings[0].item)
        self.assertEqual(0.0, findings[0].value)

    def test_drill_to_copper_reports_each_npth_and_does_not_treat_pad_overlap_as_legal(self):
        drill_scan = ExcellonScan("board-NPTH.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for x in (0.0, 2.0, 4.0):
            drill_scan.primitives.append(
                DrillPrimitive("circle", center=(x, 0.0), diameter=0.4)
            )
            copper_scan.primitives.append(
                GerberPrimitive(
                    "circle",
                    center=(x, 0.0),
                    width=0.8,
                    is_flash=True,
                    function="ComponentPad",
                    net="GND",
                )
            )

        findings = list(
            export_scanners.scan_drill_to_copper(
                [drill_scan],
                [copper_scan],
                {"NPTH-to-Copper": 0.25},
            )
        )

        self.assertEqual(3, len(findings))
        self.assertEqual({"NPTH-to-Copper"}, {finding.item for finding in findings})
        self.assertEqual({0.0}, {finding.value for finding in findings})
        self.assertEqual({("Drl",)}, {tuple(finding.layer) for finding in findings})

    def test_npth_to_copper_keeps_one_drl_result_across_copper_layers(self):
        drill_scan = ExcellonScan("board-NPTH.drl")
        drill_scan.plated = False
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        )
        front = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        front.primitives.append(
            GerberPrimitive(
                "segment", start=(0.35, -0.5), end=(0.35, 0.5),
                width=0.1, function="Conductor",
            )
        )
        back = GerberScan("B_Cu.gbr", ["B.Cu"], is_copper=True)
        back.primitives.append(
            GerberPrimitive(
                "segment", start=(0.25, -0.5), end=(0.25, 0.5),
                width=0.1, function="Conductor",
            )
        )

        findings = list(
            export_scanners.scan_drill_to_copper(
                [drill_scan],
                [front, back],
                {"NPTH-to-Copper": 0.25},
            )
        )

        self.assertEqual(1, len(findings))
        self.assertEqual(["Drl"], findings[0].layer)
        self.assertAlmostEqual(0.1, findings[0].value)
        self.assertEqual(["B.Cu"], findings[0].raw["related"]["layer"])

    def test_drill_to_copper_classifies_via_on_inner_layer_from_x2_pad(self):
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.plated = True
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        )
        outer = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        outer.primitives.append(
            GerberPrimitive(
                "circle",
                center=(0.0, 0.0),
                width=0.6,
                is_flash=True,
                function="ViaPad",
                net="A",
            )
        )
        inner = GerberScan("In1_Cu.gbr", ["In1.Cu"], is_copper=True)
        inner.primitives.append(
            GerberPrimitive(
                "segment",
                start=(0.25, 0.0),
                end=(1.0, 0.0),
                width=0.1,
                function="Conductor",
                net="B",
            )
        )

        findings = list(
            export_scanners.scan_drill_to_copper([drill_scan], [outer, inner])
        )

        self.assertEqual(["Via-to-Trace [Inner]"], [finding.item for finding in findings])
        self.assertAlmostEqual(0.1, findings[0].value)

    def test_pth_to_trace_ignores_gerber_pad_and_pour(self):
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.plated = True
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle",
                    center=(0.0, 0.0),
                    width=0.6,
                    is_flash=True,
                    function="ComponentPad",
                    net="A",
                ),
                GerberPrimitive(
                    "region",
                    start=(-1.0, -1.0),
                    end=(1.0, 1.0),
                    points=((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0)),
                    function="Conductor",
                    net="B",
                ),
                GerberPrimitive(
                    "segment",
                    start=(0.3, 0.0),
                    end=(1.0, 0.0),
                    width=0.1,
                    function="Conductor",
                    net="C",
                ),
            )
        )

        findings = list(
            export_scanners.scan_drill_to_copper([drill_scan], [copper_scan])
        )

        self.assertEqual(["PTH-to-Trace [Outer]"], [finding.item for finding in findings])
        self.assertEqual("segment", findings[0].raw["related"]["kind"])
        self.assertEqual("C", findings[0].raw["related"]["net"])
        self.assertAlmostEqual(0.15, findings[0].value)

    def test_drill_to_copper_reports_slot_to_region_clearance(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill = DrillPrimitive("slot", start=(0.5, -0.5), end=(1.5, -0.5), diameter=0.3)
        region = GerberPrimitive(
            "region",
            start=(0.0, 0.0),
            end=(2.0, 2.0),
            points=((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
        )
        drill_scan.primitives.append(drill)
        copper_scan.primitives.append(region)

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertAlmostEqual(0.35, drill_to_primitive_gap(drill, region), places=3)
        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.35, findings[0].value, places=3)

    def test_region_gap_skips_unmeasurable_edge_distance(self):
        left = GerberPrimitive(
            "region",
            start=(0.0, 0.0),
            end=(2.0, 2.0),
            points=((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
        )
        right = GerberPrimitive(
            "region",
            start=(5.0, 0.0),
            end=(7.0, 2.0),
            points=((5.0, 0.0), (7.0, 0.0), (7.0, 2.0), (5.0, 2.0)),
        )
        values = iter((None, 3.0, 4.0, 5.0))

        with mock.patch(
            "kicad_dfm.services.export_geometry_core.nearest_region_segment_distance",
            side_effect=lambda *args: next(values),
        ):
            gap = region_to_region_gap(left, right)

        self.assertEqual(3.0, gap)

    def test_drill_to_copper_uses_aperture_hole_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=0.6, height=0.6, is_flash=True)
        )

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.1, findings[0].value, places=3)

    def test_drill_to_copper_uses_rectangular_aperture_hole_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.2, height=0.8, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=0.6, height=0.3, is_flash=True)
        )

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.05, findings[0].value, places=3)

    def test_drill_to_copper_uses_slot_clear_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(
            DrillPrimitive("slot", start=(-0.4, 0.0), end=(0.4, 0.0), diameter=0.2)
        )
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.4, height=0.8, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("segment", start=(-0.4, 0.0), end=(0.4, 0.0), width=0.4)
        )

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.1, findings[0].value, places=3)

    def test_drill_to_copper_ignores_partial_slot_clear_mask_for_cleared_pad(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(
            DrillPrimitive("slot", start=(-0.4, 0.0), end=(0.4, 0.0), diameter=0.2)
        )
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=1.4, height=0.8, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("segment", start=(-0.2, 0.0), end=(0.4, 0.0), width=0.4)
        )

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.0, findings[0].value, places=3)

    def test_drill_to_copper_uses_local_clear_mask_gap(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("segment", start=(-0.5, 0.0), end=(0.5, 0.0), width=0.4)
        )

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.1, findings[0].value, places=3)

    def test_drill_to_copper_uses_slot_clear_mask_gap(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("slot", start=(-0.5, 0.0), end=(0.5, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive("segment", start=(-0.5, 0.42), end=(0.5, 0.42), width=0.1)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("segment", start=(-0.5, 0.0), end=(0.5, 0.0), width=0.8)
        )

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.3, findings[0].value, places=3)

    def test_slot_clear_mask_gap_supports_rect_and_circle_masks(self):
        drill = DrillPrimitive("slot", start=(-0.5, 0.0), end=(0.5, 0.0), diameter=0.2)
        rect_mask = GerberPrimitive("rect", center=(0.0, 0.0), width=1.4, height=0.8, is_flash=True)
        circle_mask = GerberPrimitive("circle", center=(0.0, 0.0), width=1.4, height=1.4, is_flash=True)

        self.assertAlmostEqual(0.1, export_scanners.drill_to_clear_mask_gap(drill, (rect_mask,)), places=3)
        self.assertAlmostEqual(0.092, export_scanners.drill_to_clear_mask_gap(drill, (circle_mask,)), places=3)

    def test_slot_circle_clear_mask_gap_uses_farthest_slot_corner(self):
        drill = DrillPrimitive("slot", start=(-0.5, 0.0), end=(0.5, 0.0), diameter=0.2)
        mask = GerberPrimitive("circle", center=(0.1, 0.0), width=1.4, height=1.4, is_flash=True)

        self.assertAlmostEqual(0.0, export_scanners.drill_to_clear_mask_gap(drill, (mask,)), places=3)

    def test_slot_segment_clear_mask_gap_accounts_for_axis_offset(self):
        drill = DrillPrimitive("slot", start=(-0.5, 0.0), end=(0.5, 0.0), diameter=0.2)
        mask = GerberPrimitive("segment", start=(-0.5, 0.2), end=(0.5, 0.2), width=0.8)

        self.assertAlmostEqual(0.1, export_scanners.drill_to_clear_mask_gap(drill, (mask,)), places=3)

    def test_round_drill_clear_mask_gap_accounts_for_mask_offset(self):
        drill = DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        circle_mask = GerberPrimitive("circle", center=(0.2, 0.0), width=0.8, height=0.8, is_flash=True)
        segment_mask = GerberPrimitive("segment", start=(-0.5, 0.2), end=(0.5, 0.2), width=0.8)

        self.assertAlmostEqual(0.1, export_scanners.drill_to_clear_mask_gap(drill, (circle_mask,)), places=3)
        self.assertAlmostEqual(0.1, export_scanners.drill_to_clear_mask_gap(drill, (segment_mask,)), places=3)

    def test_drill_to_copper_prunes_far_clear_masks_per_copper(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        for index in range(40):
            copper_scan.clear_masks.append(
                GerberPrimitive("circle", center=(10.0 + index * 10.0, 0.0), width=0.5, is_flash=True)
            )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=0.5, is_flash=True)
        )
        original = export_scanners.drill_to_visible_copper_gap
        mask_counts = []

        def counted_drill_to_visible_copper_gap(drill, copper, masks):
            mask_counts.append(len(masks))
            return original(drill, copper, masks)

        with mock.patch.object(export_scanners, "drill_to_visible_copper_gap", side_effect=counted_drill_to_visible_copper_gap):
            findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual([1], mask_counts)

    def test_drill_to_copper_keeps_clear_mask_near_drill(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive("segment", start=(0.5, 0.0), end=(1.0, 0.0), width=0.1)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=0.8, is_flash=True)
        )
        original = export_scanners.drill_to_visible_copper_gap
        mask_counts = []

        def counted_drill_to_visible_copper_gap(drill, copper, masks):
            mask_counts.append(len(masks))
            return original(drill, copper, masks)

        with mock.patch.object(export_scanners, "drill_to_visible_copper_gap", side_effect=counted_drill_to_visible_copper_gap):
            findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual([1], mask_counts)
        self.assertEqual(1, len(findings))
        self.assertAlmostEqual(0.35, findings[0].value, places=3)

    def test_holes_on_smd_ignores_drill_inside_round_pad_bbox_only(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.9, 0.9), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle", center=(0.0, 0.0), width=2.0, height=2.0,
                is_flash=True, function="SMDPad",
            )
        )

        findings = list(export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan]))

        self.assertEqual([], findings)

    def test_holes_on_smd_ignores_drill_edge_when_center_is_outside_pad(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(1.1, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle", center=(0.0, 0.0), width=2.0, height=2.0,
                is_flash=True, function="SMDPad",
            )
        )

        findings = list(export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan]))

        self.assertEqual([], findings)

    def test_missing_smask_opening_rejects_center_only_mask_coverage(self):
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper.primitives.append(
            GerberPrimitive(
                "rect", center=(1.0, 1.0), width=0.8, height=0.4, is_flash=True,
                function="SMDPad", net="A", object_id="U1,1",
            )
        )
        mask.primitives.append(
            GerberPrimitive(
                "rect", center=(1.0, 1.0), width=0.4, height=0.2, is_flash=True
            )
        )

        findings = list(
            export_scanners.scan_missing_smask_openings([], [copper, mask])
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("red", findings[0].color)
        self.assertEqual(
            "resolution_bounded_union_sampling",
            findings[0].raw["coverage_basis"],
        )
        self.assertGreater(findings[0].raw["coverage_ratio"], 0.0)
        self.assertLess(findings[0].raw["coverage_ratio"], 1.0)
        self.assertTrue(findings[0].raw["uncovered_sample_points"])
        self.assertGreater(findings[0].raw["sampling_resolution_mm"], 0.0)
        self.assertGreater(findings[0].raw["sampling_error_mm"], 0.0)

    def test_missing_smask_unknown_x2_pad_is_low_confidence(self):
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper.primitives.append(
            GerberPrimitive(
                "rect", center=(1.0, 1.0), width=0.8, height=0.4,
                is_flash=True,
            )
        )

        findings = list(
            export_scanners.scan_missing_smask_openings([], [copper, mask])
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("unknown", findings[0].raw["x2_classification"])
        self.assertEqual(0.35, findings[0].raw["confidence"])

    def test_missing_smask_logical_pad_accepts_union_of_mask_openings(self):
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        for center in ((0.75, 1.0), (1.25, 1.0)):
            copper.primitives.append(
                GerberPrimitive(
                    "rect", center=center, width=0.5, height=0.4,
                    is_flash=True, function="SMDPad", object_id="U1,1",
                    flash_id="logical-pad-1",
                )
            )
            mask.primitives.append(
                GerberPrimitive(
                    "rect", center=center, width=0.5, height=0.4,
                    is_flash=True,
                )
            )

        findings = list(
            export_scanners.scan_missing_smask_openings([], [copper, mask])
        )

        self.assertEqual([], findings)

    def test_missing_smask_sampled_union_requires_native_validation(self):
        copper = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        mask = GerberScan("MaskTop.gbr", ["F.Mask"])
        copper.primitives.append(
            GerberPrimitive(
                "rect", center=(0.0, 0.0), width=1.0, height=1.0,
                is_flash=True, function="SMDPad", object_id="U1,1",
                coordinate_resolution_mm=0.001,
            )
        )
        mask.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(-0.25, 0.0), width=0.5, height=1.0,
                    is_flash=True, coordinate_resolution_mm=0.001,
                ),
                GerberPrimitive(
                    "rect", center=(0.25, 0.0), width=0.5, height=1.0,
                    is_flash=True, coordinate_resolution_mm=0.001,
                ),
            )
        )

        findings = list(
            export_scanners.scan_missing_smask_openings([], [copper, mask])
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("gold", findings[0].color)
        self.assertEqual("unproven", findings[0].raw["mask_coverage_status"])
        self.assertEqual("partial", findings[0].raw["coverage"])
        self.assertTrue(findings[0].raw["needs_native_validation"])
        self.assertEqual(0.45, findings[0].raw["confidence"])
        self.assertEqual(1.0, findings[0].raw["coverage_ratio"])
        self.assertGreater(findings[0].raw["sampling_error_mm"], 0.001)

    def test_pth_on_smd_keeps_physical_drill_edge_overlap(self):
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.plated = True
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(1.1, 0.0), diameter=0.4)
        )
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=2.0, height=2.0,
                    is_flash=True, function="SMDPad",
                ),
                GerberPrimitive(
                    "circle", center=(1.1, 0.0), width=0.5, height=0.5,
                    is_flash=True, function="ComponentPad",
                ),
            )
        )

        findings = list(
            export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan])
        )

        self.assertEqual(["PTH on SMD Pad"], [finding.item for finding in findings])

    def test_holes_on_smd_slot_overlap_uses_slot_bbox_depth(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(
            DrillPrimitive("slot", start=(-0.7, 0.0), end=(0.7, 0.0), diameter=0.2)
        )
        copper_scan.primitives.append(
            GerberPrimitive(
                "rect",
                center=(0.8, 0.0),
                width=0.3,
                height=0.3,
                is_flash=True,
                function="SMDPad",
            )
        )

        findings = list(export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("Via on SMD Pad", findings[0].item)
        self.assertAlmostEqual(0.1, findings[0].value, places=3)

    def test_remote_holes_on_smd_contract_returns_every_overlap_ratio(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for index in range(12):
            center = (index * 2.0, 0.0)
            drill_scan.primitives.append(DrillPrimitive("circle", center=center, diameter=0.4))
            copper_scan.primitives.append(
                GerberPrimitive(
                    "rect",
                    center=center,
                    width=1.0,
                    height=1.0,
                    is_flash=True,
                    function="SMDPad",
                    object_id="U1,{0}".format(index),
                )
            )

        findings = list(
            export_scanners.scan_pad_drill_features(
                [drill_scan],
                [copper_scan],
                include_drilled_pad_size=False,
                holes_overlap_ratio=True,
            )
        )

        self.assertEqual(12, len(findings))
        self.assertTrue(all(finding.item == "Via on SMD Pad" for finding in findings))
        self.assertTrue(all(finding.value == 1.0 for finding in findings))

    def test_holes_on_smd_ignores_drill_inside_round_aperture_hole(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle",
                center=(0.0, 0.0),
                width=1.0,
                height=1.0,
                is_flash=True,
                function="SMDPad",
            )
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=0.6, height=0.6, is_flash=True)
        )

        findings = list(export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan]))

        self.assertEqual([], findings)

    def test_holes_on_smd_ignores_drill_inside_rectangular_aperture_hole(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2))
        copper_scan.primitives.append(
            GerberPrimitive(
                "rect",
                center=(0.0, 0.0),
                width=1.2,
                height=0.8,
                is_flash=True,
                function="SMDPad",
            )
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("rect", center=(0.0, 0.0), width=0.6, height=0.3, is_flash=True)
        )

        findings = list(export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan]))

        self.assertEqual([], findings)

    def test_holes_on_smd_ignores_unclassified_legacy_copper_flash(self):
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.plated = True
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "rect", center=(0.0, 0.0), width=1.0, height=1.0,
                is_flash=True,
            )
        )

        findings = list(
            export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan])
        )

        self.assertEqual([], findings)

    def test_holes_on_smd_classifies_npth_from_excellon_plating(self):
        drill_scan = ExcellonScan("board-NPTH.drl")
        drill_scan.plated = False
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "rect", center=(0.0, 0.0), width=1.0, height=1.0,
                is_flash=True, function="SMDPad",
            )
        )

        findings = list(
            export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan])
        )

        self.assertEqual(["NPTH on SMD Pad"], [finding.item for finding in findings])

    def test_holes_on_smd_classifies_pth_from_component_pad_annulus(self):
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.plated = True
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(0.0, 0.0), width=1.0, height=1.0,
                    is_flash=True, function="SMDPad",
                ),
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.5,
                    is_flash=True, function="ComponentPad",
                ),
            )
        )

        findings = list(
            export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan])
        )

        self.assertEqual(["PTH on SMD Pad"], [finding.item for finding in findings])

    def test_holes_on_smd_uses_custom_pad_polygon_not_its_bbox(self):
        drill_scan = ExcellonScan("board-PTH.drl")
        drill_scan.plated = True
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(1.5, 1.5), diameter=0.2)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "region",
                start=(0.0, 0.0),
                end=(2.0, 2.0),
                center=(0.5, 0.5),
                points=(
                    (0.0, 0.0), (2.0, 0.0), (2.0, 0.5),
                    (0.5, 0.5), (0.5, 2.0), (0.0, 2.0),
                ),
                is_flash=True,
                function="SMDPad",
            )
        )

        findings = list(
            export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan])
        )

        self.assertEqual([], findings)

    def test_copper_spacing_prunes_far_pairs_before_precise_gap(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for index in range(40):
            x = index * 10.0
            scan.primitives.append(
                GerberPrimitive("segment", start=(x, 0.0), end=(x + 1.0, 0.0), width=0.1)
            )

        original = export_scanners.primitive_gap
        calls = []

        def counted_gap(left, right):
            calls.append((left, right))
            return original(left, right)

        with mock.patch.object(export_scanners, "primitive_gap", side_effect=counted_gap):
            findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("Trace Spacing", findings[0].item)
        total_pairs = len(scan.primitives) * (len(scan.primitives) - 1) // 2
        self.assertLess(len(calls), total_pairs // 10)

    def test_copper_spacing_prunes_far_pairs_before_bbox_gap(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.1))
        scan.primitives.append(GerberPrimitive("segment", start=(1.2, 0.0), end=(2.2, 0.0), width=0.1))
        for index in range(40):
            x = 100.0 + index * 10.0
            scan.primitives.append(
                GerberPrimitive("segment", start=(x, 0.0), end=(x + 1.0, 0.0), width=0.1)
            )
        original = export_scanners.bbox_gap
        calls = []

        def counted_bbox_gap(left, right):
            calls.append((left, right))
            return original(left, right)

        with mock.patch.object(export_scanners, "bbox_gap", side_effect=counted_bbox_gap):
            findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("Trace Spacing", findings[0].item)
        total_pairs = len(scan.primitives) * (len(scan.primitives) - 1) // 2
        self.assertLess(len(calls), total_pairs // 10)

    def test_copper_spacing_checkpoint_can_stop_a_dense_scan(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        for index in range(80):
            scan.primitives.append(
                GerberPrimitive(
                    "segment",
                    start=(0.0, index * 0.3),
                    end=(1.0, index * 0.3),
                    width=0.1,
                    net="A" if index % 2 else "B",
                    function="Conductor",
                )
            )
        checkpoints = []

        def stop():
            checkpoints.append(True)
            raise RuntimeError("stopped")

        with self.assertRaisesRegex(RuntimeError, "stopped"):
            list(export_scanners.scan_copper_spacing([scan], checkpoint=stop))

        self.assertEqual([True], checkpoints)

    def test_native_results_are_not_truncated(self):
        checks = ExportChecks(None)
        finding = ScanFinding(
            "Dangling Tracks",
            "test",
            category="Signal Integrity",
            value=1.0,
            color="red",
            raw={"file": "CuTop.gbr"},
        )

        expected_count = 75
        for _index in range(expected_count):
            self.assertEqual(0, checks._add_scan_finding(finding))

        self.assertEqual(
            expected_count,
            len(checks.native_results["Signal Integrity"]),
        )
        mapped = checks.native_result_map()["Signal Integrity"]
        self.assertEqual(
            expected_count,
            sum(len(group["result"]) for group in mapped["check"]),
        )

    def test_copper_spacing_ignores_track_to_copper_region(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.1,
                    function="Conductor", net="A",
                ),
                GerberPrimitive(
                    "region", start=(0.0, 0.3), end=(1.0, 1.0),
                    points=((0.0, 0.3), (1.0, 0.3), (1.0, 1.0), (0.0, 1.0)),
                    function="Conductor", net="B",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual([], findings)

    def test_copper_spacing_classifies_smd_pair_only_as_smd_spacing(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(0.0, 0.0), width=0.4, height=0.4,
                    is_flash=True, function="SMDPad", net="A",
                ),
                GerberPrimitive(
                    "rect", center=(0.54, 0.0), width=0.4, height=0.4,
                    is_flash=True, function="SMDPad", net="B",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(
            {"SMD Pad Spacing"},
            {finding.item for finding in findings},
        )
        self.assertEqual(
            {"SMD Spacing"},
            {finding.category for finding in findings},
        )

    def test_copper_spacing_includes_role_specific_surface_pad_functions(self):
        for function in (
            "TestPad",
            "ConnectorPad",
            "HeatsinkPad",
            "FiducialPad",
        ):
            with self.subTest(function=function):
                scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
                scan.primitives.extend(
                    (
                        GerberPrimitive(
                            "rect", center=(0.0, 0.0), width=0.2, height=0.2,
                            is_flash=True, function=function, net="A",
                            flash_id="role-pad",
                        ),
                        GerberPrimitive(
                            "rect", center=(0.3, 0.0), width=0.2, height=0.2,
                            is_flash=True, function="SMDPad", net="B",
                            flash_id="smd-pad",
                        ),
                    )
                )

                findings = list(export_scanners.scan_copper_spacing([scan]))

                self.assertEqual(1, len(findings))
                self.assertEqual("SMD Pad Spacing", findings[0].item)
                self.assertAlmostEqual(0.1, findings[0].value)

    def test_copper_spacing_covers_all_sixteen_amulet_role_pad_pair_shapes(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        pair_functions = (
            [("TestPad", "TestPad")] * 3
            + [("TestPad", "SMDPad")]
            + [("HeatsinkPad", "SMDPad")] * 12
        )
        for index, (left_function, right_function) in enumerate(pair_functions):
            offset = float(index * 10)
            scan.primitives.extend(
                (
                    GerberPrimitive(
                        "rect", center=(offset, 0.0), width=0.2, height=0.2,
                        is_flash=True, function=left_function,
                        net="left-{0}".format(index),
                        flash_id="left-{0}".format(index),
                    ),
                    GerberPrimitive(
                        "rect", center=(offset + 0.3, 0.0), width=0.2,
                        height=0.2, is_flash=True, function=right_function,
                        net="right-{0}".format(index),
                        flash_id="right-{0}".format(index),
                    ),
                )
            )

        findings = list(
            export_scanners.scan_copper_spacing(
                [scan], {"SMD Pad Spacing": 0.15}
            )
        )

        self.assertEqual(16, len(findings))
        self.assertTrue(
            all(finding.item == "SMD Pad Spacing" for finding in findings)
        )
        self.assertTrue(all(abs(finding.value - 0.1) < 1e-9 for finding in findings))

    def test_copper_spacing_classifies_bga_before_smd(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.2,
                    is_flash=True, function="BGAPad", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(0.3, 0.0), width=0.2,
                    is_flash=True, function="SMDPad", net="B",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(["BGA Pads"], [finding.item for finding in findings])

    def test_copper_spacing_keeps_mixed_smd_and_pth_pair_in_general_rule(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.2,
                    is_flash=True, function="ComponentPad", net="A",
                ),
                GerberPrimitive(
                    "circle", center=(0.3, 0.0), width=0.2,
                    is_flash=True, function="SMDPad", net="B",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(
            ["Pad-to-Pad Spacing"], [finding.item for finding in findings]
        )

    def test_possible_copper_spacing_items_for_pure_smd_board_is_mutually_exclusive(self):
        pads = [
            GerberPrimitive(
                "circle", center=(float(index), 0.0), width=0.2,
                is_flash=True, function="SMDPad", net=str(index % 2),
            )
            for index in range(200)
        ]

        self.assertEqual(
            {"SMD Pad Spacing"},
            export_scanners.possible_copper_spacing_items(pads),
        )

    def test_copper_spacing_does_not_merge_disconnected_reused_x2_object_id(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.2,
                    is_flash=True, function="SMDPad", object_id="FM1,,",
                    flash_id="1",
                ),
                GerberPrimitive(
                    "circle", center=(0.4, 0.0), width=0.2,
                    is_flash=True, function="SMDPad", object_id="FM1,,",
                    flash_id="2",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("SMD Pad Spacing", findings[0].item)
        self.assertAlmostEqual(0.2, findings[0].value)

    def test_copper_spacing_reports_different_net_region_pad_overlap(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "region", start=(-0.2, -0.2), end=(0.2, 0.2),
                    points=((-0.2, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2)),
                    is_flash=True, function="SMDPad", net="A",
                    object_id="U1,1", flash_id="1",
                ),
                GerberPrimitive(
                    "circle", center=(0.1, 0.0), width=0.2,
                    is_flash=True, function="SMDPad", net="B",
                    object_id="U1,2", flash_id="2",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual(0.0, findings[0].value)

    def test_copper_spacing_adds_primary_related_mapping_raw(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.1))
        scan.primitives.append(GerberPrimitive("segment", start=(1.2, 0.0), end=(2.2, 0.0), width=0.1))

        findings = list(export_scanners.scan_copper_spacing([scan]))

        raw = findings[0].raw
        self.assertEqual("gerber", raw["primary"]["item_type"])
        self.assertEqual("gerber", raw["related"]["item_type"])
        self.assertEqual(((0.0, 0.0), (1.0, 0.0)), raw["primary"]["segment"])
        self.assertEqual(((1.2, 0.0), (2.2, 0.0)), raw["related"]["segment"])

    def test_copper_spacing_skips_primitives_with_incomplete_bbox(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        invalid = GerberPrimitive("segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.1)
        invalid.bbox = (None, 0.0, 1.0, 0.1)
        scan.primitives.append(invalid)
        scan.primitives.append(GerberPrimitive("segment", start=(1.2, 0.0), end=(2.2, 0.0), width=0.1))

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual([], findings)

    def test_clear_mask_removes_fully_covered_pad_from_spacing_checks(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.primitives.append(GerberPrimitive("rect", center=(1.1, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.clear_masks.append(GerberPrimitive("rect", center=(1.1, 0.0), width=1.2, height=1.2, is_flash=True))

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual([], findings)

    def test_circle_visible_mask_checks_diagonal_sample_points(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.primitives.append(GerberPrimitive("circle", center=(1.0, 0.0), width=0.4, height=0.4, is_flash=True))
        scan.clear_masks.append(GerberPrimitive("rect", center=(1.0, 0.0), width=0.4, height=0.3, is_flash=True))

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(
            {"Pad-to-Pad Spacing"},
            {finding.item for finding in findings},
        )

    def test_circle_visible_mask_uses_exact_circle_coverage(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.primitives.append(GerberPrimitive("circle", center=(1.0, 0.0), width=0.4, height=0.4, is_flash=True))
        scan.clear_masks.append(GerberPrimitive("circle", center=(1.1847759, 0.0765367), width=0.792, is_flash=True))

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(
            {"Pad-to-Pad Spacing"},
            {finding.item for finding in findings},
        )

    def test_circle_visible_mask_uses_exact_segment_coverage(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.primitives.append(GerberPrimitive("circle", center=(1.0, 0.0), width=0.4, height=0.4, is_flash=True))
        scan.clear_masks.append(
            GerberPrimitive(
                "segment",
                start=(1.9501427, -1.7712223),
                end=(0.4194091, 1.9242957),
                width=0.792,
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(
            {"Pad-to-Pad Spacing"},
            {finding.item for finding in findings},
        )

    def test_segment_visible_mask_checks_endcap_diagonal_sample_points(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.primitives.append(GerberPrimitive("segment", start=(1.0, 0.0), end=(2.0, 0.0), width=0.4))
        scan.clear_masks.append(GerberPrimitive("rect", center=(1.5, 0.0), width=1.1, height=0.4, is_flash=True))

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(1, len(findings))

    def test_segment_visible_mask_uses_exact_circle_coverage(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.primitives.append(GerberPrimitive("segment", start=(1.0, 0.0), end=(1.1, 0.0), width=0.4))
        scan.clear_masks.append(GerberPrimitive("circle", center=(0.9152241, -0.0765367), width=0.792, is_flash=True))

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(1, len(findings))

    def test_segment_rect_visible_mask_uses_exact_bbox_coverage(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        segment = GerberPrimitive("segment", start=(1.0, 0.0), end=(2.0, 0.0), width=0.4)
        mask = GerberPrimitive("rect", center=(1.5, 0.0), width=1.4, height=0.6, is_flash=True)

        with mock.patch.object(export_scanners, "point_in_primitive") as point_in_primitive:
            self.assertTrue(export_scanners.primitive_fully_covered_by_mask(segment, mask))

        point_in_primitive.assert_not_called()

    def test_visible_primitives_prunes_far_masks_before_point_checks(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True))
        for index in range(40):
            scan.clear_masks.append(
                GerberPrimitive("rect", center=(-500.0 - index * 10.0, 0.0), width=1.0, height=1.0, is_flash=True)
            )
        for index in range(40):
            scan.clear_masks.append(
                GerberPrimitive("rect", center=(10.0 + index * 10.0, 0.0), width=1.0, height=1.0, is_flash=True)
            )
        scan.clear_masks.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.2, height=1.2, is_flash=True))

        original = export_scanners.point_in_primitive
        calls = []

        def counted_point_in_primitive(point, primitive):
            calls.append((point, primitive))
            return original(point, primitive)

        with mock.patch.object(export_scanners, "point_in_primitive", side_effect=counted_point_in_primitive):
            visible = export_scanners.visible_primitives(scan)

        self.assertEqual([], visible)
        self.assertLess(len(calls), len(scan.clear_masks) // 4)

    def test_visible_primitives_prunes_left_far_masks_before_bbox_gap(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(1000.0, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.clear_masks.append(GerberPrimitive("rect", center=(500.0, 20.0), width=1200.0, height=1.0, is_flash=True))
        for index in range(40):
            scan.clear_masks.append(
                GerberPrimitive("rect", center=(900.0 + index, 5.0), width=0.5, height=0.5, is_flash=True)
            )
        scan.clear_masks.append(GerberPrimitive("rect", center=(1000.0, 0.0), width=1.2, height=1.2, is_flash=True))

        original = export_scanners.bbox_gap
        calls = []

        def counted_bbox_gap(left, right):
            calls.append((left, right))
            return original(left, right)

        with mock.patch.object(export_scanners, "bbox_gap", side_effect=counted_bbox_gap):
            visible = export_scanners.visible_primitives(scan)

        self.assertEqual([], visible)
        self.assertLess(len(calls), len(scan.clear_masks) // 10)

    def test_aperture_hole_mask_removes_fully_covered_pad_from_spacing_checks(self):
        scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.append(GerberPrimitive("rect", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True))
        scan.primitives.append(GerberPrimitive("circle", center=(0.0, 0.0), width=0.2, height=0.2, is_flash=True))
        scan.clear_masks.append(GerberPrimitive("circle", center=(0.0, 0.0), width=0.4, height=0.4, is_flash=True))

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual([], findings)

    def test_copper_to_board_edge_prunes_far_edges_before_precise_gap(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive("segment", start=(0.0, 0.0), end=(1.0, 0.0), width=0.1)
        )
        for index in range(40):
            x = index * 10.0
            edge_scan.segments.append(GerberSegment((x, 2.0), (x + 1.0, 2.0), width=0.0))

        original = export_scanners.primitive_segment_gap
        calls = []

        def counted_gap(primitive, segment):
            calls.append((primitive, segment))
            return original(primitive, segment)

        with mock.patch.object(export_scanners, "primitive_segment_gap", side_effect=counted_gap):
            findings = list(export_scanners.scan_copper_to_board_edge([edge_scan, copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("Trace-to-Board Edge", findings[0].item)
        self.assertLess(len(calls), len(edge_scan.segments) // 10)

    def test_copper_to_board_edge_skips_left_far_edges_before_precise_gap(self):
        edge_scan = GerberScan("EdgeCuts.gbr", ["Edge.Cuts"], is_edge=True)
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive("segment", start=(1000.0, 0.0), end=(1001.0, 0.0), width=0.1)
        )
        for index in range(40):
            x = index * 10.0
            edge_scan.segments.append(GerberSegment((x, 2.0), (x + 1.0, 2.0), width=0.0))
        edge_scan.segments.append(GerberSegment((1000.0, 2.0), (1001.0, 2.0), width=0.0))

        original = export_scanners.primitive_segment_gap
        calls = []

        def counted_gap(primitive, segment):
            calls.append((primitive, segment))
            return original(primitive, segment)

        with mock.patch.object(export_scanners, "primitive_segment_gap", side_effect=counted_gap):
            findings = list(export_scanners.scan_copper_to_board_edge([edge_scan, copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("Trace-to-Board Edge", findings[0].item)
        self.assertEqual(1, len(calls))

    def test_drill_to_copper_prunes_far_copper_before_precise_gap(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        for index in range(40):
            x = index * 10.0
            copper_scan.primitives.append(
                GerberPrimitive("segment", start=(x, 2.0), end=(x + 1.0, 2.0), width=0.1)
            )

        original = export_scanners.drill_to_primitive_gap
        calls = []

        def counted_gap(drill, copper):
            calls.append((drill, copper))
            return original(drill, copper)

        with mock.patch.object(export_scanners, "drill_to_primitive_gap", side_effect=counted_gap):
            findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("PTH-to-Trace [Outer]", findings[0].item)
        self.assertLess(len(calls), len(copper_scan.primitives) // 10)

    def test_drill_to_copper_adds_primary_related_mapping_raw(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("segment", start=(1.0, 0.0), end=(2.0, 0.0), width=0.1)
        )

        findings = list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        raw = findings[0].raw
        self.assertEqual("drill", raw["primary"]["item_type"])
        self.assertEqual("gerber", raw["related"]["item_type"])
        self.assertEqual("board.drl", raw["primary"]["file"])
        self.assertEqual("F_Cu.gbr", raw["related"]["file"])

    def test_drill_to_copper_keeps_every_trace_inside_the_rule_limit(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = True
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4)
        )
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment", start=(-0.35, -1.0), end=(-0.35, 1.0), width=0.1
                ),
                GerberPrimitive(
                    "segment", start=(0.35, -1.0), end=(0.35, 1.0), width=0.1
                ),
            )
        )

        findings = list(
            export_scanners.scan_drill_to_copper(
                [drill_scan],
                [copper_scan],
                {"PTH-to-Trace [Outer]": 0.2},
            )
        )

        self.assertEqual(2, len(findings))
        self.assertTrue(
            all(finding.item == "PTH-to-Trace [Outer]" for finding in findings)
        )

    def test_pad_size_prunes_non_overlapping_pad_window_before_precise_gap(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        for index in range(40):
            copper_scan.primitives.append(
                GerberPrimitive("rect", center=(10.0 + index * 10.0, 0.0), width=1.0, height=1.0, is_flash=True)
            )
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle", center=(0.0, 0.0), width=1.0, height=1.0,
                is_flash=True,
            )
        )

        original = export_scanners.drill_to_primitive_gap
        calls = []

        def counted_gap(drill, pad):
            calls.append((drill, pad))
            return original(drill, pad)

        with mock.patch.object(export_scanners, "drill_to_primitive_gap", side_effect=counted_gap):
            findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Short Pads", "PTH Annular Ring"], [finding.item for finding in findings])
        self.assertLess(len(calls), len(copper_scan.primitives) // 10)

    def test_pad_drill_features_prunes_left_far_pads_before_bbox_gap(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(1000.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("rect", center=(500.0, 20.0), width=1200.0, height=1.0, is_flash=True)
        )
        for index in range(40):
            copper_scan.primitives.append(
                GerberPrimitive("rect", center=(900.0 + index, 5.0), width=0.5, height=0.5, is_flash=True)
            )
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(1000.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        original = export_scanners.bbox_gap
        calls = []

        def counted_bbox_gap(left, right):
            calls.append((left, right))
            return original(left, right)

        with mock.patch.object(export_scanners, "bbox_gap", side_effect=counted_bbox_gap):
            findings = list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertEqual(["Short Pads", "PTH Annular Ring"], [finding.item for finding in findings])
        self.assertLess(len(calls), len(copper_scan.primitives) // 10)

    def test_holes_on_smd_prunes_non_overlapping_pad_window_before_precise_gap(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        for index in range(40):
            copper_scan.primitives.append(
                GerberPrimitive("rect", center=(10.0 + index * 10.0, 0.0), width=1.0, height=1.0, is_flash=True)
            )
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle", center=(0.0, 0.0), width=1.0, height=1.0,
                is_flash=True, function="SMDPad",
            )
        )

        original = export_scanners.drill_to_primitive_gap
        calls = []

        def counted_gap(drill, pad):
            calls.append((drill, pad))
            return original(drill, pad)

        with mock.patch.object(export_scanners, "drill_to_primitive_gap", side_effect=counted_gap):
            findings = list(export_scanners.scan_holes_on_smd_pads([drill_scan], [copper_scan]))

        self.assertEqual(1, len(findings))
        self.assertEqual("Via on SMD Pad", findings[0].item)
        self.assertLess(len(calls), len(copper_scan.primitives) // 10)

    def test_pad_drill_features_prunes_far_clear_masks_per_pad(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        for index in range(40):
            copper_scan.clear_masks.append(
                GerberPrimitive("circle", center=(10.0 + index * 10.0, 0.0), width=0.6, is_flash=True)
            )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=0.6, is_flash=True)
        )
        original = export_scanners.cleared_flash_hole_size
        mask_counts = []

        def counted_cleared_flash_hole_size(drill, pad, masks):
            mask_counts.append(len(masks))
            return original(drill, pad, masks)

        with mock.patch.object(export_scanners, "cleared_flash_hole_size", side_effect=counted_cleared_flash_hole_size):
            findings = list(export_scanners.scan_pad_drill_features([drill_scan], [copper_scan]))

        self.assertEqual({"Pad size", "RingHole"}, {finding.category for finding in findings})
        self.assertEqual([1], mask_counts)

    def test_clear_mask_index_is_cached_across_scanners(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=0.6, is_flash=True)
        )

        list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))
        first_masks = copper_scan.sorted_clear_masks
        first_starts = copper_scan.clear_mask_starts
        first_max_width = copper_scan.clear_mask_max_width
        list(export_scanners.scan_drill_to_copper([drill_scan], [copper_scan]))

        self.assertIs(first_masks, copper_scan.sorted_clear_masks)
        self.assertIs(first_starts, copper_scan.clear_mask_starts)
        self.assertEqual(first_max_width, copper_scan.clear_mask_max_width)

    def test_visible_primitives_reuses_clear_mask_index_cache(self):
        drill_scan = ExcellonScan("board.drl")
        copper_scan = GerberScan("F_Cu.gbr", ["F.Cu"], is_copper=True)
        drill_scan.primitives.append(DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4))
        copper_scan.primitives.append(
            GerberPrimitive("circle", center=(0.0, 0.0), width=1.0, height=1.0, is_flash=True)
        )
        copper_scan.clear_masks.append(
            GerberPrimitive("circle", center=(10.0, 0.0), width=0.6, is_flash=True)
        )

        self.assertEqual(1, len(export_scanners.visible_primitives(copper_scan)))
        first_masks = copper_scan.sorted_clear_masks
        first_starts = copper_scan.clear_mask_starts
        list(export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan]))

        self.assertIs(first_masks, copper_scan.sorted_clear_masks)
        self.assertIs(first_starts, copper_scan.clear_mask_starts)

    def test_valid_export_has_no_issues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir)

            issues, summary = analyze_export(result, rules_for_profile("standard"))

        self.assertEqual((), issues)
        self.assertEqual("black", summary["Gerber Export"].color)

    def test_export_analysis_profile_records_scan_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir)

            issues, summary, native_results, profile = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
                include_profile=True,
            )
            legacy_result = analyze_export_with_results(result, rules_for_profile("standard"))

        self.assertEqual(3, len(legacy_result))
        self.assertEqual((), issues)
        self.assertEqual("black", summary["Gerber Export"].color)
        self.assertIn("Smallest Trace Width", native_results)
        self.assertIn("total_ms", profile)
        self.assertIn("scan_outputs", profile)
        self.assertEqual(6, profile["scan_outputs"]["files_seen"])
        self.assertEqual(4, profile["scan_outputs"]["files_parsed"])
        self.assertEqual(3, profile["scan_outputs"]["gerber_files"])
        self.assertEqual(1, profile["scan_outputs"]["drill_files"])
        self.assertGreaterEqual(profile["scan_outputs"]["native_results"], 1)
        self.assertFalse(profile["scan_outputs"]["capped"])

    def test_standard_profile_runs_signal_integrity_scanner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir)
            finding = ScanFinding(
                "Acute Angle Traces",
                "Gerber copper geometry forms an acute angle.",
                category="Signal Integrity",
                value=0.2,
                layer=["F.Cu"],
                color="red",
                raw={"file": result.files[0], "segment": ((1.0, 1.0), (2.0, 1.0))},
            )

            with mock.patch.object(
                export_checks,
                "scan_signal_integrity",
                return_value=(finding,),
            ) as scanner:
                _, _, native_results = analyze_export_with_results(
                    result,
                    rules_for_profile("standard"),
                )

        scanner.assert_called_once()
        self.assertEqual("red", native_results["Signal Integrity"]["color"])
        self.assertEqual(
            "Acute Angle Traces",
            native_results["Signal Integrity"]["check"][0]["result"][0]["item"],
        )

    def test_export_analysis_reports_parse_errors_and_continues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir)
            original_parse_gerber_scan = export_checks.parse_gerber_scan

            def failing_parse_gerber(path):
                if os.path.basename(path) == "CuTop.gbr":
                    raise ValueError("broken gerber")
                return original_parse_gerber_scan(path)

            with mock.patch.object(export_checks, "parse_gerber_scan", side_effect=failing_parse_gerber):
                issues, summary, native_results, profile = analyze_export_with_results(
                    result,
                    rules_for_profile("standard"),
                    include_profile=True,
                )

        parse_errors = [issue for issue in issues if issue.item == "Geometry Parse Error"]
        self.assertEqual(1, len(parse_errors))
        self.assertEqual("error", parse_errors[0].severity)
        self.assertEqual("ValueError", parse_errors[0].raw["error_type"])
        self.assertTrue(is_blocking_export_issue(parse_errors[0]))
        self.assertEqual("red", summary["Gerber Export"].color)
        self.assertEqual(1, profile["scan_outputs"]["parse_errors"])
        self.assertIn("Hole Size", native_results)

    def test_missing_layer_empty_file_and_zip_missing_entry_are_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, skip=("CuBottom.gbr",), empty=("CuTop.gbr",))
            with zipfile.ZipFile(result.zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(os.path.join(result.output_dir, "CuTop.gbr"), "CuTop.gbr")

            issues, _ = analyze_export(result, rules_for_profile("standard"))

        items = [issue.item for issue in issues]
        self.assertIn("Empty Layer File", items)
        self.assertIn("Missing Layer File", items)
        self.assertIn("Copper Layer Count Mismatch", items)
        self.assertIn("Zip Package Error", items)

    def test_empty_optional_process_layer_is_not_export_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, empty=("SilkTop.gbr",))

            issues, summary = analyze_export(result, rules_for_profile("standard"))

        self.assertEqual((), issues)
        self.assertEqual("black", summary["Gerber Export"].color)

    def test_missing_drill_and_map_are_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, skip=("board.drl", "drill-map.map"))

            issues, _ = analyze_export(result, rules_for_profile("standard"))

        severities = {issue.item: issue.severity for issue in issues}
        self.assertEqual("error", severities["Missing Drill File"])
        self.assertEqual("warning", severities["Missing Drill Map"])

    def test_integrity_severity_does_not_change_by_profile(self):
        severities_by_profile = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, skip=("EdgeCuts.gbr",))
            for profile_id in ("economy", "standard", "precision"):
                issues, _ = analyze_export(result, rules_for_profile(profile_id))
                severities_by_profile[profile_id] = [
                    (issue.item, issue.severity)
                    for issue in issues
                    if issue.item == "Missing Board Outline"
                ]

        self.assertEqual(severities_by_profile["economy"], severities_by_profile["standard"])
        self.assertEqual(severities_by_profile["standard"], severities_by_profile["precision"])

    def test_fallback_output_directory_is_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir)
            result.fallback_used = True
            result.warnings = ("fallback",)

            issues, _ = analyze_export(result, rules_for_profile("standard"))

        self.assertIn("warning", [issue.severity for issue in issues if issue.item == "Wrong Output Directory"])

    def test_gerber_subdirectory_under_hqdmf_is_expected_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, output_subdir=os.path.join("HQDMF", "Gerber_video"))

            issues, _ = analyze_export(result, rules_for_profile("standard"))

        self.assertNotIn("Wrong Output Directory", [issue.item for issue in issues])

    def test_prefixed_kicad_gerber_filenames_match_plot_plan_layers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, filename_prefix="video-")

            issues, summary = analyze_export(result, rules_for_profile("standard"))

        self.assertEqual((), issues)
        self.assertEqual("black", summary["Gerber Export"].color)

    def test_gerber_aperture_uses_profile_rules(self):
        colors = {}
        native_colors = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, trace_width=0.135)
            for profile_id in ("economy", "standard", "precision"):
                issues, summary, native_results = analyze_export_with_results(
                    result,
                    rules_for_profile(profile_id),
                )
                self.assertNotIn("Smallest Trace Width", [issue.item for issue in issues])
                colors[profile_id] = summary["Gerber Export"].color
                native_colors[profile_id] = native_results["Smallest Trace Width"]["color"]

        self.assertEqual({"economy": "black", "standard": "black", "precision": "black"}, colors)
        self.assertEqual({"economy": "red", "standard": "gold", "precision": "black"}, native_colors)

    def test_rectangular_gerber_aperture_uses_smallest_dimension(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, trace_width="0.135X0.500")

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        self.assertEqual(0.135, native_results["Smallest Trace Width"]["display"])
        self.assertEqual("gold", native_results["Smallest Trace Width"]["color"])
        detail = native_results["Smallest Trace Width"]["check"][0]["result"][0]
        self.assertEqual((0.9325, 0.9325, 9.0675, 1.0675), detail["raw"]["bbox"])
        self.assertEqual("smallesttracewidth:smallesttracewidth", detail["rule_key"])
        self.assertEqual("gerber", detail["source"])
        self.assertEqual(0.65, detail["confidence"])
        self.assertEqual("gerber_derived", detail["geometry_basis"])
        self.assertEqual("gerber", detail["raw"]["primary"]["item_type"])
        self.assertEqual(["F.Cu"], detail["raw"]["primary"]["layer"])
        self.assertEqual(detail["raw"]["segment"], detail["raw"]["primary"]["segment"])
        self.assertEqual(detail["raw"]["bbox"], detail["raw"]["primary"]["bbox"])

    def test_repeated_gerber_draws_keep_every_trace_of_the_same_width(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, trace_width=0.135, repeated_draws=True)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        trace_results = native_results["Smallest Trace Width"]["check"][0]["result"]
        self.assertEqual(2, len(trace_results))

    def test_edgecuts_open_outline_is_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, open_outline=True)

            issues, summary, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        self.assertEqual((), issues)
        self.assertEqual("black", summary["Gerber Export"].color)
        edge = native_results["Copper-to-Board Edge"]
        self.assertEqual("gold", edge["color"])
        detail = edge["check"][0]["result"][0]
        self.assertEqual("Trace-to-Board Edge", detail["item"])
        self.assertEqual(0.15, detail["raw"]["width"])
        self.assertIn("bbox", detail["raw"])
        self.assertEqual("gerber", detail["raw"]["primary"]["item_type"])
        self.assertEqual(["Edge.Cuts"], detail["raw"]["primary"]["layer"])
        self.assertEqual("gerber", detail["raw"]["related"]["item_type"])
        self.assertIn(detail["raw"]["primary"]["point"], detail["raw"]["segment"])
        self.assertIn(detail["raw"]["related"]["point"], detail["raw"]["segment"])

    def test_gerber_trace_to_board_edge_maps_to_native_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, trace_y=0.25)

            issues, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        self.assertNotIn("Trace-to-Board Edge", [issue.item for issue in issues])
        edge = native_results["Copper-to-Board Edge"]
        self.assertEqual(0.15, edge["display"])
        self.assertEqual("red", edge["color"])
        self.assertEqual("Trace-to-Board Edge", edge["check"][0]["result"][0]["item"])
        detail = next(
            entry["result"][0]
            for entry in edge["check"]
            if entry["result"][0]["item"] == "Trace-to-Board Edge"
            and entry["result"][0]["sx"] == "1.000000"
            and entry["result"][0]["sy"] == "0.250000"
        )
        self.assertEqual(0, detail["type"])
        self.assertEqual("1.000000", detail["sx"])
        self.assertEqual("0.250000", detail["sy"])

    def test_gerber_flash_pad_to_board_edge_maps_to_native_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, include_flash_pad=True)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        edge = native_results["Copper-to-Board Edge"]
        self.assertEqual(0.1, edge["display"])
        detail = next(
            entry["result"][0]
            for entry in edge["check"]
            if entry["result"][0]["item"] == "SMD-to-Board Edge"
        )
        self.assertEqual("SMD-to-Board Edge", detail["item"])
        self.assertEqual("0.100000", detail["sx"])
        self.assertEqual("0.500000", detail["sy"])

    def test_gerber_obround_pad_to_board_edge_maps_to_native_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, include_obround_pad=True)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        edge = native_results["Copper-to-Board Edge"]
        self.assertEqual(0.1, edge["display"])
        detail = next(
            entry["result"][0]
            for entry in edge["check"]
            if entry["result"][0]["item"] == "SMD-to-Board Edge"
        )
        self.assertEqual("SMD-to-Board Edge", detail["item"])
        self.assertEqual("0.300000", detail["sx"])

    def test_gerber_macro_pad_to_board_edge_maps_to_native_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, include_macro_pad=True)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        edge = native_results["Copper-to-Board Edge"]
        self.assertEqual(0.3, edge["display"])
        detail = next(
            entry["result"][0]
            for entry in edge["check"]
            if entry["result"][0]["item"] == "SMD-to-Board Edge"
        )
        self.assertEqual("SMD-to-Board Edge", detail["item"])

    def test_gerber_macro_aperture_creates_flash_primitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(gerber(0.2, include_macro_pad=True))

            scan = parse_gerber_scan(path)

        self.assertTrue(any(primitive.kind == "circle" and primitive.is_flash for primitive in scan.primitives))

    def test_gerber_x2_file_function_overrides_filename_layer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "renamed-output.gbr")
            content = "%TF.FileFunction,Copper,L2,Inr*%\n" + gerber(0.2)
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(content)

            scan = parse_gerber_scan(path)
            should_scan = ExportChecks(None)._should_scan_gerber_geometry(path)

        self.assertEqual(["In1.Cu"], scan.layer)
        self.assertTrue(scan.is_copper)
        self.assertEqual("Copper,L2,Inr", scan.file_function)
        self.assertTrue(should_scan)
        self.assertAlmostEqual(0.000001, scan.coordinate_resolution_mm)
        self.assertTrue(
            all(
                primitive.coordinate_resolution_mm == scan.coordinate_resolution_mm
                for primitive in scan.primitives
            )
        )

    def test_gerber_x2_analysis_is_invariant_to_output_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            content = "%TF.FileFunction,Copper,L2,Inr*%\n" + gerber(0.2)
            scans = []
            for filename in ("renamed-a.gbr", "totally-different-name.gbr"):
                path = os.path.join(tmpdir, filename)
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(content)
                scans.append(parse_gerber_scan(path))

        signatures = []
        for scan in scans:
            signatures.append(
                (
                    tuple(scan.layer),
                    scan.is_copper,
                    tuple(
                        (finding.category, finding.item, finding.value, tuple(finding.layer))
                        for finding in scan.findings
                    ),
                    tuple(
                        (
                            primitive.kind,
                            primitive.start,
                            primitive.end,
                            primitive.center,
                            primitive.width,
                            primitive.height,
                            primitive.function,
                        )
                        for primitive in scan.primitives
                    ),
                )
            )

        self.assertTrue(signatures[0][2])
        self.assertEqual(signatures[0], signatures[1])

    def test_gerber_macro_circle_flash_keeps_primitive_offset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(offset_macro_circle_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("circle", flash.kind)
        self.assertEqual((0.25, -0.1), flash.center)
        self.assertEqual((0.4, 0.4), (flash.width, flash.height))

    def test_gerber_parameterized_macro_flash_uses_add_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(parameterized_macro_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("circle", flash.kind)
        self.assertEqual((0.45, 0.45), (flash.width, flash.height))

    def test_gerber_parameterized_macro_accepts_lowercase_x_separator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(parameterized_macro_lowercase_x_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual((0.4, 0.2), (flash.width, flash.height))

    def test_gerber_parameterized_macro_keeps_inch_values_single_scaled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(parameterized_macro_inch_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertAlmostEqual(2.54, flash.width, places=3)

    def test_gerber_parameterized_macro_evaluates_division_expression(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(parameterized_macro_expression_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual((0.3, 0.3), (flash.width, flash.height))

    def test_gerber_macro_evaluates_arithmetic_precedence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(macro_arithmetic_expression_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual((0.5, 0.5), (flash.width, flash.height))

    def test_gerber_macro_variable_assignment_feeds_later_primitives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(macro_variable_assignment_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual((0.4, 0.4), (flash.width, flash.height))

    def test_gerber_macro_flash_expands_clear_primitive_to_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(clear_macro_circle_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual((0.6, 0.6), (flash.width, flash.height))
        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual("circle", scan.clear_masks[0].kind)
        self.assertEqual((0.2, 0.2), (scan.clear_masks[0].width, scan.clear_masks[0].height))

    def test_gerber_macro_polygon_flash_creates_region_primitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(polygon_macro_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("region", flash.kind)
        self.assertEqual(5, len(flash.points))
        self.assertEqual((0.8, 0.8), (flash.width, flash.height))

    def test_gerber_macro_clear_polygon_flash_creates_region_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(clear_polygon_macro_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.primitives))
        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual("region", scan.clear_masks[0].kind)
        self.assertEqual(5, len(scan.clear_masks[0].points))

    def test_gerber_macro_outline_flash_creates_region_primitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(outline_macro_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("region", flash.kind)
        self.assertEqual(3, len(flash.points))
        self.assertEqual((0.0, 0.5), flash.center)

    def test_gerber_macro_clear_outline_flash_creates_region_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(clear_outline_macro_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.primitives))
        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual("region", scan.clear_masks[0].kind)
        self.assertEqual(3, len(scan.clear_masks[0].points))

    def test_gerber_macro_vector_line_creates_segment_primitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(vector_line_macro_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("segment", flash.kind)
        self.assertEqual((-0.5, 0.0), flash.start)
        self.assertEqual((0.5, 0.0), flash.end)
        self.assertEqual(0.2, flash.width)

    def test_gerber_macro_vector_line_code_2_creates_segment_primitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(vector_line_code_2_macro_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("segment", flash.kind)
        self.assertEqual((-0.4, 0.0), flash.start)
        self.assertEqual((0.4, 0.0), flash.end)

    def test_gerber_macro_clear_vector_line_creates_segment_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(clear_vector_line_macro_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual("segment", scan.clear_masks[0].kind)
        self.assertEqual((-0.25, 0.0), scan.clear_masks[0].start)
        self.assertEqual((0.25, 0.0), scan.clear_masks[0].end)

    def test_gerber_macro_clear_vector_line_code_2_creates_segment_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(clear_vector_line_code_2_macro_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual("segment", scan.clear_masks[0].kind)
        self.assertEqual((-0.2, 0.0), scan.clear_masks[0].start)
        self.assertEqual((0.2, 0.0), scan.clear_masks[0].end)

    def test_gerber_macro_thermal_creates_outer_copper_and_clear_masks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(thermal_macro_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("circle", flash.kind)
        self.assertEqual((1.0, 1.0), (flash.width, flash.height))
        self.assertEqual(3, len(scan.clear_masks))
        self.assertTrue(any(mask.kind == "circle" and mask.width == 0.3 for mask in scan.clear_masks))
        segments = [mask for mask in scan.clear_masks if mask.kind == "segment"]
        self.assertEqual(2, len(segments))
        self.assertTrue(any(segment.start == (-0.5, 0.0) and segment.end == (0.5, 0.0) for segment in segments))

    def test_gerber_round_aperture_hole_parameter_is_not_flash_height(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(round_aperture_with_hole_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("circle", flash.kind)
        self.assertEqual((1.0, 1.0), (flash.width, flash.height))
        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual((0.4, 0.4), (scan.clear_masks[0].width, scan.clear_masks[0].height))

    def test_gerber_rect_aperture_hole_parameter_is_not_flash_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(rect_aperture_with_hole_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("rect", flash.kind)
        self.assertEqual((1.0, 0.8), (flash.width, flash.height))
        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual((0.3, 0.3), (scan.clear_masks[0].width, scan.clear_masks[0].height))

    def test_gerber_rect_aperture_accepts_lowercase_x_and_plus_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(rect_plus_lowercase_x_aperture_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("rect", flash.kind)
        self.assertEqual((0.8, 0.4), (flash.width, flash.height))

    def test_gerber_add_aperture_allows_internal_spaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(spaced_add_aperture_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("rect", flash.kind)
        self.assertEqual((0.8, 0.4), (flash.width, flash.height))

    def test_gerber_rectangular_aperture_hole_creates_rect_clear_mask(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(rect_aperture_with_rect_hole_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual((1.0, 0.8), (flash.width, flash.height))
        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual("rect", scan.clear_masks[0].kind)
        self.assertEqual((0.4, 0.2), (scan.clear_masks[0].width, scan.clear_masks[0].height))

    def test_gerber_polygon_aperture_uses_outer_diameter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(polygon_aperture_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("region", flash.kind)
        self.assertEqual(6, len(flash.points))
        self.assertEqual((1.0, 1.0), (flash.width, flash.height))
        self.assertEqual((0.5, 0.0), flash.points[0])
        self.assertEqual([], scan.clear_masks)

    def test_gerber_polygon_aperture_keeps_inch_vertices_unscaled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(polygon_aperture_inch_gerber())

            scan = parse_gerber_scan(path)

        flash = next(primitive for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual("region", flash.kind)
        self.assertEqual(6, len(flash.points))
        self.assertAlmostEqual(2.54, flash.width, places=3)

    def test_gerber_polygon_aperture_hole_uses_fourth_parameter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(polygon_aperture_with_hole_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual((0.2, 0.2), (scan.clear_masks[0].width, scan.clear_masks[0].height))

    def test_gerber_round_draw_aperture_hole_parameter_is_not_trace_width(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(round_draw_aperture_with_hole_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1.0, scan.segments[0].width)

    def test_gerber_region_to_board_edge_maps_to_native_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, include_region=True)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        edge = native_results["Copper-to-Board Edge"]
        self.assertEqual(0.1, edge["display"])
        detail = next(
            entry["result"][0]
            for entry in edge["check"]
            if entry["result"][0]["raw"]["bbox"] == (0.1, 0.1, 0.9, 0.9)
        )
        self.assertEqual("Copper-to-Board Edge", detail["item"])
        self.assertEqual("0.100000", detail["sx"])
        self.assertEqual((0.1, 0.1, 0.9, 0.9), detail["raw"]["bbox"])
        self.assertEqual("gerber", detail["raw"]["primary"]["item_type"])
        self.assertEqual(["F.Cu"], detail["raw"]["primary"]["layer"])
        self.assertEqual((0.1, 0.1, 0.9, 0.9), detail["raw"]["primary"]["bbox"])

    def test_gerber_trace_spacing_maps_to_native_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, second_trace_y=1.349)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        spacing = native_results["Smallest Trace Spacing"]
        self.assertEqual(0.149, spacing["display"])
        self.assertEqual("gold", spacing["color"])
        detail = spacing["check"][0]["result"][0]
        self.assertEqual("Trace Spacing", detail["item"])
        self.assertEqual(0.2, detail["raw"]["width"])
        self.assertEqual((0.9, 0.9, 9.1, 1.449), detail["raw"]["bbox"])

    def test_gerber_pad_spacing_maps_to_native_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, flash_pad_pair=True)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        spacing = native_results["SMD Spacing"]
        self.assertEqual(0.1, spacing["display"])
        self.assertEqual("red", spacing["color"])
        detail = spacing["check"][0]["result"][0]
        self.assertEqual("SMD Pad Spacing", detail["item"])
        self.assertEqual("smdspacing:smdpadspacing", detail["rule_key"])
        self.assertEqual("0.152400,0.203200,0.254000", detail["rule"])
        self.assertEqual("red", detail["color"])
        self.assertEqual(0.4, detail["raw"]["width"])
        self.assertEqual((0.3, 0.3, 1.2, 0.7), detail["raw"]["bbox"])

    def test_excellon_drill_to_copper_maps_to_native_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(
                tmpdir,
                trace_y=0.45,
                drill_diameter=0.4,
                second_drill_x="020000",
            )

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        clearance = native_results["Drill to Copper"]
        self.assertEqual(0.15, clearance["display"])
        self.assertEqual("red", clearance["color"])
        detail = clearance["check"][0]["result"][0]
        self.assertEqual("PTH-to-Trace [Outer]", detail["item"])
        self.assertEqual("2.000000", detail["sx"])
        self.assertEqual("0.450000", detail["ey"])
        self.assertEqual(0.2, detail["raw"]["width"])
        self.assertEqual((0.9, -0.2, 9.1, 0.55), detail["raw"]["bbox"])

    def test_gerber_flash_and_drill_maps_to_pad_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(
                tmpdir,
                flash_pad_pair=True,
                drill_diameter=0.25,
                second_drill_x="005000",
                flash_pad_origin=True,
            )

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        pad = native_results["Pad size"]
        self.assertEqual(0.4, pad["display"])
        self.assertEqual("black", pad["color"])
        detail = pad["check"][0]["result"][0]
        self.assertEqual("Short Pads", detail["item"])
        self.assertEqual(0.4, detail["raw"]["width"])
        self.assertEqual((-0.2, -0.2, 0.2, 0.2), detail["raw"]["bbox"])
        self.assertEqual("gerber", detail["raw"]["primary"]["item_type"])
        self.assertNotIn("related", detail["raw"])

    def test_gerber_obround_flash_and_drill_maps_to_pad_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(
                tmpdir,
                include_obround_pad=True,
                drill_diameter=0.25,
                second_drill_x="005000",
                obround_pad_origin=True,
                obround_pad_size=(0.48, 0.24),
            )

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        pad = native_results["Pad size"]
        self.assertEqual(0.24, pad["display"])
        self.assertIn(
            "Long Pads",
            [group["result"][0]["item"] for group in pad["check"]],
        )

    def test_gerber_macro_flash_and_drill_maps_to_pad_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(
                tmpdir,
                include_macro_pad=True,
                macro_pad_origin=True,
                drill_diameter=0.25,
                second_drill_x="005000",
            )

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        pad = native_results["Pad size"]
        self.assertEqual(0.4, pad["display"])
        self.assertEqual("Short Pads", pad["check"][0]["result"][0]["item"])

    def test_gerber_round_flash_and_drill_maps_to_ring_hole(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(
                tmpdir,
                round_flash_pad=True,
                drill_diameter=0.25,
                second_drill_x="005000",
            )

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        ring = native_results["RingHole"]
        self.assertEqual(0.075, ring["display"])
        self.assertEqual("red", ring["color"])
        detail = ring["check"][0]["result"][0]
        self.assertEqual("PTH Annular Ring", detail["item"])
        self.assertEqual(0.4, detail["raw"]["width"])
        self.assertEqual((-0.2, -0.2, 0.2, 0.2), detail["raw"]["bbox"])
        self.assertEqual("gerber", detail["raw"]["primary"]["item_type"])
        self.assertEqual("drill", detail["raw"]["related"]["item_type"])
        self.assertEqual(["Drl"], detail["raw"]["related"]["layer"])

    def test_gerber_drill_on_flash_pad_maps_to_holes_on_smd_pads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(
                tmpdir,
                flash_pad_pair=True,
                drill_diameter=0.25,
                second_drill_x="005000",
                flash_pad_origin=True,
            )

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        holes = native_results["Holes on SMD Pads"]
        self.assertEqual(0.125, holes["display"])
        self.assertEqual("gold", holes["color"])
        detail = holes["check"][0]["result"][0]
        self.assertEqual("Via on SMD Pad", detail["item"])
        self.assertEqual("0.000000", detail["cx"])
        self.assertEqual("0.000000", detail["cy"])
        self.assertEqual("-0.200000", detail["sx"])
        self.assertEqual("0.200000", detail["ex"])
        self.assertEqual(0.4, detail["raw"]["width"])
        self.assertEqual((-0.2, -0.2, 0.2, 0.2), detail["raw"]["bbox"])
        self.assertEqual("drill", detail["raw"]["primary"]["item_type"])
        self.assertEqual(["Drl"], detail["raw"]["primary"]["layer"])
        self.assertEqual("gerber", detail["raw"]["related"]["item_type"])

    def test_gerber_coordinate_format_is_used_for_points(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(edge_gerber(size=1.0, format_header="%FSLAX35Y35*%"))

            issues = list(scan_gerber(path))

        self.assertEqual([], [issue.item for issue in issues])

    def test_gerber_trailing_zero_suppression_format_is_used_for_points(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(trailing_zero_edge_gerber())

            scan = parse_gerber_scan(path)
            issues = list(scan_gerber(path))

        self.assertEqual([], [issue.item for issue in issues])
        self.assertEqual((0.0, 0.0, 1.0, 0.0), scan.segments[0].bbox)

    def test_gerber_incremental_coordinate_mode_is_used_for_points(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(incremental_edge_gerber())

            scan = parse_gerber_scan(path)
            issues = list(scan_gerber(path))

        self.assertEqual([], [issue.item for issue in issues])
        self.assertEqual((0.0, 0.0, 1.0, 0.0), scan.segments[0].bbox)
        self.assertEqual((0.0, 0.0), scan.segments[-1].end)

    def test_gerber_g90_g91_coordinate_mode_commands_are_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(g90_g91_edge_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual((0.0, 0.0, 1.0, 0.0), scan.segments[0].bbox)
        self.assertEqual((0.0, 1.0), scan.segments[-1].end)

    def test_gerber_legacy_inch_unit_command_is_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(legacy_inch_edge_gerber())

            scan = parse_gerber_scan(path)
            issues = list(scan_gerber(path))

        self.assertEqual([], [issue.item for issue in issues])
        self.assertAlmostEqual(0.254, scan.segments[0].width, places=3)
        self.assertEqual((0.0, 0.0, 2.54, 0.0), scan.segments[0].bbox)

    def test_gerber_legacy_g54_aperture_select_is_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(legacy_g54_aperture_select_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(0.15, scan.segments[0].width)

    def test_gerber_aperture_accepts_explicit_plus_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(plus_aperture_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(0.15, scan.segments[0].width)

    def test_gerber_multiple_commands_on_one_line_are_split(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(single_line_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.segments))
        self.assertEqual(0.15, scan.segments[0].width)
        self.assertEqual((0.0, 0.0, 1.0, 0.0), scan.segments[0].bbox)

    def test_gerber_comments_and_attributes_do_not_create_geometry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(commented_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.segments))
        self.assertEqual((0.0, 0.0, 1.0, 0.0), scan.segments[0].bbox)

    def test_gerber_x2_attributes_are_attached_to_primitives(self):
        content = "\n".join(
            (
                "%FSLAX46Y46*%",
                "%MOMM*%",
                "%TA.AperFunction,SMDPad,CuDef*%",
                "%ADD10C,1.000000*%",
                "%TD*%",
                "D10*",
                "%TO.P,NT1,1,1*%",
                "%TO.N,GND*%",
                "X1000000Y2000000D03*",
                "%TD*%",
                "M02*",
                "",
            )
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(content)
            scan = parse_gerber_scan(path)

        self.assertEqual("GND", scan.primitives[0].net)
        self.assertEqual("SMDPad", scan.primitives[0].function)
        self.assertEqual("NT1", scan.primitives[0].component)
        self.assertEqual("NT1,1,1", scan.primitives[0].object_id)

    def test_copper_spacing_ignores_same_net_legal_contact(self):
        scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "segment",
                    start=(0.0, 0.0),
                    end=(1.0, 0.0),
                    width=0.2,
                    net="GND",
                    function="Conductor",
                ),
                GerberPrimitive(
                    "circle",
                    center=(1.0, 0.0),
                    width=1.0,
                    is_flash=True,
                    net="GND",
                    function="SMDPad",
                ),
            )
        )

        self.assertEqual([], list(export_scanners.scan_copper_spacing([scan])))

    def test_copper_spacing_reports_different_net_contact_without_guessing_net_tie(self):
        scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect",
                    center=(0.0, 0.0),
                    width=0.4,
                    height=0.4,
                    is_flash=True,
                    net="+5V",
                    function="SMDPad",
                    component="NT1",
                    object_id="NT1,1,1",
                ),
                GerberPrimitive(
                    "circle",
                    center=(0.3, 0.0),
                    width=0.2,
                    is_flash=True,
                    net="FB_5V",
                    function="SMDPad",
                    component="NT1",
                    object_id="NT1,2,2",
                ),
                GerberPrimitive(
                    "segment",
                    start=(0.3, 0.0),
                    end=(1.0, 0.0),
                    width=0.2,
                    net="FB_5V",
                    function="Conductor",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(
            {"SMD Pad Spacing", "Trace-to-Pad Spacing"},
            {finding.item for finding in findings},
        )
        self.assertEqual(
            {
                "SMD Pad Spacing": "SMD Spacing",
                "Trace-to-Pad Spacing": "Smallest Trace Spacing",
            },
            {finding.item: finding.category for finding in findings},
        )
        self.assertTrue(all(finding.value == 0.0 for finding in findings))

    def test_copper_spacing_keeps_separated_pad_pair_inside_net_tie(self):
        scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.2, is_flash=True,
                    net="A", function="SMDPad", component="NT1",
                    object_id="NT1,1,1", flash_id="1:0",
                ),
                GerberPrimitive(
                    "rect", center=(0.25, 0.0), width=0.3, height=0.2,
                    is_flash=True, net="A", function="SMDPad", component="NT1",
                    object_id="NT1,1,1", flash_id="2:0",
                ),
                GerberPrimitive(
                    "circle", center=(0.4, 0.0), width=0.2, is_flash=True,
                    net="B", function="SMDPad", component="NT1",
                    object_id="NT1,2,2", flash_id="3:0",
                ),
            )
        )

        findings = list(export_scanners.scan_copper_spacing([scan]))

        self.assertEqual(
            {"SMD Pad Spacing"},
            {finding.item for finding in findings},
        )
        self.assertEqual(1, len(findings))
        self.assertEqual("SMD Spacing", findings[0].category)
        self.assertEqual(0.0, findings[0].value)

    def test_copper_spacing_keeps_net_tie_pair_above_reporting_limit(self):
        scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "circle", center=(0.0, 0.0), width=0.2, is_flash=True,
                    net="A", function="SMDPad", component="NT1",
                    object_id="NT1,1,1", flash_id="1:0",
                ),
                GerberPrimitive(
                    "rect", center=(0.25, 0.0), width=0.3, height=0.2,
                    is_flash=True, net="A", function="SMDPad", component="NT1",
                    object_id="NT1,1,1", flash_id="2:0",
                ),
                GerberPrimitive(
                    "circle", center=(0.4, 0.0), width=0.2, is_flash=True,
                    net="B", function="SMDPad", component="NT1",
                    object_id="NT1,2,2", flash_id="3:0",
                ),
                GerberPrimitive(
                    "circle", center=(2.0, 0.0), width=0.2, is_flash=True,
                    net="C", function="SMDPad", component="R1", flash_id="4:0",
                ),
                GerberPrimitive(
                    "circle", center=(2.3, 0.0), width=0.2, is_flash=True,
                    net="D", function="SMDPad", component="R2", flash_id="5:0",
                ),
                GerberPrimitive(
                    "circle", center=(4.0, 0.0), width=0.2, is_flash=True,
                    net="E", function="SMDPad", component="R3", flash_id="6:0",
                ),
                GerberPrimitive(
                    "circle", center=(4.4, 0.0), width=0.2, is_flash=True,
                    net="F", function="SMDPad", component="R4", flash_id="7:0",
                ),
            )
        )

        findings = list(
            export_scanners.scan_copper_spacing(
                [scan],
                {"Pad-to-Pad Spacing": 0.15, "SMD Pad Spacing": 0.15},
            )
        )

        smd_values = sorted(
            finding.value
            for finding in findings
            if finding.item == "SMD Pad Spacing"
        )
        self.assertEqual(3, len(smd_values))
        self.assertAlmostEqual(0.0, smd_values[0])
        self.assertAlmostEqual(0.1, smd_values[1])
        self.assertAlmostEqual(0.2, smd_values[2])

    def test_copper_spacing_keeps_all_passing_trace_ties(self):
        scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        for offset, center_gap in ((0.0, 0.3), (10.0, 0.4), (20.0, 0.4)):
            scan.primitives.extend(
                (
                    GerberPrimitive(
                        "segment", start=(offset, 0.0), end=(offset + 1.0, 0.0),
                        width=0.2, net="A{0}".format(offset), function="Conductor",
                    ),
                    GerberPrimitive(
                        "segment", start=(offset, center_gap),
                        end=(offset + 1.0, center_gap), width=0.2,
                        net="B{0}".format(offset), function="Conductor",
                    ),
                )
            )

        findings = list(
            export_scanners.scan_copper_spacing(
                [scan], {"Trace Spacing": 0.15}
            )
        )

        values = sorted(
            finding.value for finding in findings if finding.item == "Trace Spacing"
        )
        self.assertEqual(3, len(values))
        self.assertAlmostEqual(0.1, values[0])
        self.assertAlmostEqual(0.2, values[1])
        self.assertAlmostEqual(0.2, values[2])

    def test_copper_spacing_keeps_all_passing_trace_to_pad_ties(self):
        scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        for offset, center_gap in ((0.0, 0.3), (10.0, 0.4), (20.0, 0.4)):
            scan.primitives.extend(
                (
                    GerberPrimitive(
                        "segment", start=(offset, 0.0), end=(offset + 1.0, 0.0),
                        width=0.2, net="A{0}".format(offset), function="Conductor",
                    ),
                    GerberPrimitive(
                        "circle", center=(offset + 0.5, center_gap), width=0.2,
                        is_flash=True, net="B{0}".format(offset), function="SMDPad",
                        flash_id="pad-{0}".format(offset),
                    ),
                )
            )

        findings = list(
            export_scanners.scan_copper_spacing(
                [scan], {"Trace-to-Pad Spacing": 0.15}
            )
        )

        values = sorted(
            finding.value
            for finding in findings
            if finding.item == "Trace-to-Pad Spacing"
        )
        self.assertEqual(3, len(values))
        self.assertAlmostEqual(0.1, values[0])
        self.assertAlmostEqual(0.2, values[1])
        self.assertAlmostEqual(0.2, values[2])

    def test_copper_spacing_keeps_tied_net_pair_outside_net_tie_component(self):
        scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        scan.primitives.extend(
            (
                GerberPrimitive(
                    "rect", center=(0.0, 0.0), width=0.4, height=0.4,
                    is_flash=True, net="A", function="SMDPad",
                    component="NT1", object_id="NT1,1,1", flash_id="1:0",
                ),
                GerberPrimitive(
                    "circle", center=(0.3, 0.0), width=0.2, is_flash=True,
                    net="B", function="SMDPad", component="NT1",
                    object_id="NT1,2,2", flash_id="2:0",
                ),
                GerberPrimitive(
                    "circle", center=(0.7, 0.0), width=0.2, is_flash=True,
                    net="A", function="SMDPad", component="R1",
                    object_id="R1,1", flash_id="3:0",
                ),
            )
        )

        findings = list(
            export_scanners.scan_copper_spacing(
                [scan], {"SMD Pad Spacing": 0.25}
            )
        )

        values = sorted(finding.value for finding in findings)
        self.assertEqual(2, len(values))
        self.assertAlmostEqual(0.0, values[0])
        self.assertAlmostEqual(0.2, values[1])

    def test_clear_region_restores_drill_to_copper_clearance(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.plated = False
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=1.0)
        )
        copper_scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "region",
                start=(-5.0, -5.0),
                end=(5.0, 5.0),
                points=((-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)),
                net="GND",
                function="Conductor",
            )
        )
        copper_scan.clear_masks.append(
            GerberPrimitive(
                "region",
                start=(-1.0, -1.0),
                end=(1.0, 1.0),
                points=((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)),
            )
        )

        findings = list(
            export_scanners.scan_drill_to_copper([drill_scan], [copper_scan])
        )

        self.assertEqual(0.5, findings[0].value)

    def test_x2_smd_pad_is_not_used_as_pth_pad_or_ring(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4)
        )
        copper_scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle",
                center=(0.0, 0.0),
                width=1.0,
                is_flash=True,
                net="GND",
                function="SMDPad",
            )
        )

        findings = list(
            export_scanners.scan_pad_drill_features([drill_scan], [copper_scan])
        )

        self.assertEqual(["Via on SMD Pad"], [finding.item for finding in findings])

    def test_x2_component_pad_matches_only_centered_drill(self):
        drill_scan = ExcellonScan("board.drl")
        drill_scan.primitives.extend(
            (
                DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.4),
                DrillPrimitive("circle", center=(0.45, 0.0), diameter=0.4),
            )
        )
        copper_scan = GerberScan("CuTop.gbr", ["F.Cu"], is_copper=True)
        copper_scan.primitives.append(
            GerberPrimitive(
                "circle",
                center=(0.0, 0.0),
                width=1.0,
                is_flash=True,
                net="GND",
                function="ComponentPad",
            )
        )

        findings = list(
            export_scanners.scan_pad_size_and_ring([drill_scan], [copper_scan])
        )

        self.assertEqual(["Short Pads", "PTH Annular Ring"], [item.item for item in findings])
        self.assertEqual(1.0, findings[0].value)
        self.assertEqual(0.3, findings[1].value)

    def test_gerber_lowercase_commands_are_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(lowercase_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.segments))
        self.assertEqual(0.15, scan.segments[0].width)
        self.assertEqual((0.0, 0.0, 1.0, 0.0), scan.segments[0].bbox)

    def test_gerber_coordinate_commands_allow_internal_spaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(spaced_coordinate_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(1, len(scan.segments))
        self.assertEqual(0.15, scan.segments[0].width)
        self.assertEqual((0.0, 0.0, 1.0, 0.0), scan.segments[0].bbox)

    def test_gerber_modal_draw_commands_are_used_for_outline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(edge_gerber(modal=True))

            issues = list(scan_gerber(path))

        self.assertEqual([], [issue.item for issue in issues])

    def test_gerber_arc_commands_are_used_for_outline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EdgeCuts.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(arc_edge_gerber())

            scan = parse_gerber_scan(path)
            issues = list(scan_gerber(path))

        self.assertEqual([], [issue.item for issue in issues])
        self.assertGreater(len(scan.segments), 4)

    def test_gerber_single_quadrant_arc_uses_nearest_center(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(single_quadrant_arc_gerber())

            scan = parse_gerber_scan(path)

        self.assertLess(len(scan.segments), 12)
        self.assertTrue(all(segment.bbox[0] >= -1e-9 and segment.bbox[1] >= -1e-9 for segment in scan.segments))

    def test_gerber_region_commands_create_region_primitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(gerber(0.2, include_region=True))

            scan = parse_gerber_scan(path)

        self.assertTrue(any(primitive.kind == "region" for primitive in scan.primitives))

    def test_gerber_region_arc_commands_add_discrete_polygon_points(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(region_arc_gerber())

            scan = parse_gerber_scan(path)

        region = next(primitive for primitive in scan.primitives if primitive.kind == "region")
        self.assertGreater(len(region.points), 4)
        self.assertTrue(any(0.0 < point[0] < 1.0 and point[1] > 0.0 for point in region.points))

    def test_gerber_step_repeat_expands_flash_primitives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(step_repeat_flash_gerber())

            scan = parse_gerber_scan(path)

        centers = sorted(primitive.center for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual([(0.0, 0.0), (1.0, 0.0), (5.0, 0.0)], centers)

    def test_gerber_step_repeat_expands_segments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(step_repeat_segment_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(2, len(scan.segments))
        self.assertEqual((0.0, 2.0, 1.0, 2.0), scan.segments[1].bbox)

    def test_gerber_lowercase_step_repeat_expands_segments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(lowercase_step_repeat_segment_gerber())

            scan = parse_gerber_scan(path)

        self.assertEqual(2, len(scan.segments))
        self.assertEqual((0.0, 2.0, 1.0, 2.0), scan.segments[1].bbox)

    def test_gerber_step_repeat_allows_internal_spaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(spaced_step_repeat_flash_gerber())

            scan = parse_gerber_scan(path)

        centers = sorted(primitive.center for primitive in scan.primitives if primitive.is_flash)
        self.assertEqual([(0.0, 0.0), (1.0, 0.0), (5.0, 0.0)], centers)

    def test_gerber_clear_polarity_flash_is_mask_not_copper_primitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(clear_flash_gerber())

            scan = parse_gerber_scan(path)

        flashes = [primitive for primitive in scan.primitives if primitive.is_flash]
        self.assertEqual(1, len(flashes))
        self.assertEqual((0.0, 0.0), flashes[0].center)
        self.assertEqual(1, len(scan.clear_masks))
        self.assertEqual((1.0, 0.0), scan.clear_masks[0].center)

    def test_gerber_clear_polarity_region_is_mask_not_copper_primitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(clear_region_gerber())

            scan = parse_gerber_scan(path)

        self.assertFalse(any(primitive.kind == "region" for primitive in scan.primitives))
        self.assertTrue(any(primitive.kind == "region" for primitive in scan.clear_masks))

    def test_gerber_region_move_starts_a_separate_contour(self):
        content = "\n".join(
            (
                "%FSLAX46Y46*%",
                "%MOMM*%",
                "%ADD10C,0.100*%",
                "D10*",
                "G36*",
                "X0Y0D02*",
                "X1000000Y0D01*",
                "X1000000Y1000000D01*",
                "X0Y1000000D01*",
                "X0Y0D01*",
                "X10000000Y0D02*",
                "X11000000Y0D01*",
                "X11000000Y1000000D01*",
                "X10000000Y1000000D01*",
                "X10000000Y0D01*",
                "G37*",
                "M02*",
                "",
            )
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "CuTop.gbr")
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(content)
            scan = parse_gerber_scan(path)

        regions = [primitive for primitive in scan.primitives if primitive.kind == "region"]
        self.assertEqual(2, len(regions))
        self.assertEqual((0.0, 0.0, 1.0, 1.0), regions[0].bbox)
        self.assertEqual((10.0, 0.0, 11.0, 1.0), regions[1].bbox)

    def test_manufacturing_capability_error_is_native_result_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, trace_width=0.135)

            issues, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("economy"),
            )

        self.assertNotIn("Smallest Trace Width", [issue.item for issue in issues])
        self.assertEqual("red", native_results["Smallest Trace Width"]["color"])

    def test_integrity_error_blocks_export_completion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, skip=("CuBottom.gbr",))

            issues, _ = analyze_export(result, rules_for_profile("standard"))

        self.assertTrue(any(is_blocking_export_issue(issue) for issue in issues))

    def test_excellon_largest_slot_width_uses_fixed_maximum_rule(self):
        colors = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, drill_diameter=7.5, slot=True)
            for profile_id in ("economy", "standard", "precision"):
                issues, _, native_results = analyze_export_with_results(
                    result,
                    rules_for_profile(profile_id),
                )
                self.assertNotIn("Smallest Slot Width", [issue.item for issue in issues])
                slot_rows = [
                    row
                    for group in native_results["Hole Size"]["check"]
                    for row in group["result"]
                    if row["item"] == "Largest Slot Width"
                ]
                colors[profile_id] = slot_rows[0]["color"]

        self.assertEqual(
            {"economy": "gold", "standard": "gold", "precision": "gold"},
            colors,
        )

    def test_excellon_smallest_slot_width_uses_fixed_minimum_rule(self):
        colors = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, drill_diameter=0.5, slot=True)
            for profile_id in ("economy", "standard", "precision"):
                _, _, native_results = analyze_export_with_results(
                    result,
                    rules_for_profile(profile_id),
                )
                slot_rows = [
                    row
                    for group in native_results["Hole Size"]["check"]
                    for row in group["result"]
                    if row["item"] == "Smallest Slot Width"
                ]
                colors[profile_id] = slot_rows[0]["color"]

        self.assertEqual(
            {"economy": "gold", "standard": "gold", "precision": "gold"},
            colors,
        )

    def test_scan_results_are_mapped_to_native_check_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, trace_width=0.135, drill_diameter=0.5, slot=True)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        trace = native_results["Smallest Trace Width"]
        hole = native_results["Hole Size"]
        self.assertEqual(0.135, trace["display"])
        self.assertEqual("gold", trace["color"])
        self.assertEqual("Smallest Trace Width", trace["check"][0]["result"][0]["item"])
        self.assertEqual("1.000000", trace["check"][0]["result"][0]["sx"])
        self.assertIn(
            "Smallest Slot Width",
            [group["result"][0]["item"] for group in hole["check"]],
        )
        slot_results = {
            group["result"][0]["item"]: group["result"][0]
            for group in hole["check"]
            if group["result"][0]["item"] in (
                "Smallest Slot Width",
                "Largest Slot Width",
                "Largest Slot Length", "Slot Aspect Ratio",
            )
        }
        self.assertEqual(0.5, slot_results["Smallest Slot Width"]["raw"]["width"])
        self.assertEqual(0.5, slot_results["Largest Slot Width"]["raw"]["width"])
        self.assertEqual(0.5, slot_results["Largest Slot Length"]["raw"]["width"])
        self.assertEqual(2.0, float(slot_results["Slot Aspect Ratio"]["value"]))
        self.assertEqual("black", slot_results["Slot Aspect Ratio"]["color"])
        self.assertEqual((1.75, -0.25, 2.75, 0.25), slot_results["Largest Slot Width"]["raw"]["bbox"])
        self.assertEqual((1.75, -0.25, 2.75, 0.25), slot_results["Largest Slot Length"]["raw"]["bbox"])
        self.assertEqual("drill", slot_results["Largest Slot Width"]["raw"]["primary"]["item_type"])
        self.assertEqual(["Drl"], slot_results["Largest Slot Width"]["raw"]["primary"]["layer"])
        self.assertEqual(((2.0, 0.0), (2.5, 0.0)), slot_results["Largest Slot Width"]["raw"]["primary"]["segment"])
        self.assertEqual("drill", slot_results["Largest Slot Length"]["raw"]["primary"]["item_type"])
        self.assertTrue(
            all(
                "sx" in result and "ex" in result
                for group in hole["check"]
                for result in group["result"]
            )
        )

    def test_excellon_drill_results_count_holes_and_use_edge_spacing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, drill_diameter=0.8, second_drill_x="010000")

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        hole = native_results["Hole Size"]
        spacing = native_results["Drill Hole Spacing"]
        self.assertEqual(2, len(hole["check"][0]["result"]))
        self.assertIn(
            "Largest Drill Size",
            [group["result"][0]["item"] for group in hole["check"]],
        )
        self.assertEqual(0.2, spacing["display"])
        self.assertEqual("red", spacing["color"])
        spacing_result = spacing["check"][0]["result"][0]
        self.assertEqual({"0.000000", "1.000000"}, {spacing_result["sx"], spacing_result["ex"]})
        self.assertEqual(0.8, spacing_result["raw"]["diameter"])
        self.assertEqual(0.8, spacing_result["raw"]["width"])
        self.assertEqual((-0.4, -0.4, 1.4, 0.4), spacing_result["raw"]["bbox"])
        self.assertEqual((-0.4, -0.4, 0.4, 0.4), hole["check"][0]["result"][0]["raw"]["bbox"])
        self.assertEqual("drill", hole["check"][0]["result"][0]["raw"]["primary"]["item_type"])
        self.assertEqual(["Drl"], hole["check"][0]["result"][0]["raw"]["primary"]["layer"])
        self.assertEqual((0.0, 0.0), hole["check"][0]["result"][0]["raw"]["primary"]["point"])
        self.assertEqual("drill", spacing_result["raw"]["primary"]["item_type"])
        self.assertEqual("drill", spacing_result["raw"]["related"]["item_type"])
        self.assertEqual({(0.0, 0.0), (1.0, 0.0)}, {spacing_result["raw"]["primary"]["point"], spacing_result["raw"]["related"]["point"]})

    def test_strict_zero_finding_categories_are_completed_in_contract(self):
        from kicad_dfm.services.analysis_results import build_analysis_contract
        from kicad_dfm.services.analysis_results import GERBER_STRICT

        with tempfile.TemporaryDirectory() as tmpdir:
            export_result = make_export(tmpdir)
            issues, summary, native_results = analyze_export_with_results(
                export_result,
                rules_for_profile("standard"),
            )

        self.assertTrue(
            all(category in native_results for category in STRICT_SCANNER_CATEGORIES)
        )
        signal = native_results["Signal Integrity"]
        self.assertEqual([], signal["check"])
        self.assertEqual("completed", signal["execution_status"])
        self.assertEqual(0, signal["checked_count"])
        self.assertEqual(0, signal["violation_count"])
        self.assertEqual(0, signal["displayed_count"])

        contract = build_analysis_contract(
            GERBER_STRICT,
            native_results,
            issues,
            summary,
            categories=STRICT_SCANNER_CATEGORIES
            + ("Drill Hole Density", "Surface Finish Area", "Test Point Count"),
        )
        signal_contract = contract["categories"]["Signal Integrity"]
        self.assertEqual("completed", signal_contract["execution_status"])
        self.assertEqual("passed", signal_contract["result_status"])
        self.assertEqual(
            {"checked": 0, "violations": 0, "displayed": 0},
            signal_contract["counts"],
        )
        for category in (
            "Drill Hole Density",
            "Surface Finish Area",
            "Test Point Count",
        ):
            self.assertNotIn(category, native_results)
            self.assertEqual(
                "not_computed",
                contract["categories"][category]["execution_status"],
            )

    def test_drill_to_copper_native_value_unit_is_millimetres(self):
        self.assertEqual(
            "mm",
            ExportChecks._native_value_unit("Drill to Copper", "NPTH-to-Copper"),
        )
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks._add_scan_finding(
            ScanFinding(
                "NPTH-to-Copper",
                "Quantized drill-to-copper clearance",
                category="Drill to Copper",
                value=0.1995,
                layer=["F.Cu"],
                raw={
                    "file": "board-NPTH.drl",
                    "uncertainty_mm": 0.001,
                    "point": (0.0, 0.0),
                },
            )
        )

        row = checks.native_results["Drill to Copper"][0]
        self.assertEqual("borderline", row["threshold_status"])
        self.assertEqual("red", row["raw"]["nominal_color"])
        self.assertEqual(("red", "gold"), row["raw"]["decision_interval_colors"])

    def test_excellon_tool_definition_selects_active_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, explicit_tool_select=False)

            _, _, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        self.assertEqual(2, len(native_results["Hole Size"]["check"][0]["result"]))

    def test_slot_only_drill_file_is_not_reported_as_no_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, drill_diameter=0.8, slot=True, drill_points=False)

            issues, _ = analyze_export(result, rules_for_profile("standard"))

        self.assertNotIn("No Drill Commands", [issue.item for issue in issues])

    def test_drill_file_structure_issues_do_not_masquerade_as_rectangular_holes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = make_export(tmpdir, no_drill_tools=True, drill_points=False)

            issues, summary, native_results = analyze_export_with_results(
                result,
                rules_for_profile("standard"),
            )

        items = [issue.item for issue in issues]
        self.assertEqual("red", summary["Gerber Export"].color)
        self.assertEqual([], native_results["Special Drill Holes"]["check"])
        self.assertIn("No Drill Tools", items)
        self.assertIn("No Drill Commands", items)

    def test_declared_empty_kicad_npth_file_is_not_a_special_drill_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "board-NPTH.drl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "\n".join(
                        (
                            "M48",
                            "; #@! TF.FileFunction,NonPlated,1,4,NPTH",
                            "INCH",
                            "%",
                            "G90",
                            "G05",
                            "M30",
                        )
                    )
                )

            scan = parse_excellon_scan(path, board_thickness_mm=1.6)

        items = [finding.raw.get("item") for finding in scan.findings]
        self.assertNotIn("No Drill Tools", items)
        self.assertNotIn("No Drill Commands", items)
        self.assertIs(False, scan.plated)

    def test_plated_excellon_uses_pth_rules_and_pcb_thickness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "board-PTH.drl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "\n".join(
                        (
                            "M48",
                            "; #@! TF.FileFunction,Plated,1,2,PTH",
                            "METRIC,TZ",
                            "; #@! TA.AperFunction,Plated,PTH,ComponentDrill",
                            "T01C0.200",
                            "%",
                            "T01",
                            "X000000Y000000",
                            "M30",
                        )
                    )
                )

            scan = parse_excellon_scan(path, board_thickness_mm=1.6)

        by_item = {finding.item: finding for finding in scan.findings}
        self.assertNotIn("Smallest Drill Size", by_item)
        self.assertIn("Largest Drill Size", by_item)
        self.assertIn("Smallest PTH", by_item)
        self.assertIn("Largest PTH Size", by_item)
        self.assertEqual(8.0, by_item["Aspect Ratio"].value)
        self.assertEqual(1.6, by_item["Aspect Ratio"].raw["board_thickness_mm"])
        self.assertIs(True, scan.plated)

    def test_excellon_via_and_component_tools_have_separate_minimum_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "board-PTH.drl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "\n".join(
                        (
                            "M48",
                            "; #@! TF.FileFunction,Plated,1,2,PTH",
                            "METRIC,TZ",
                            "; #@! TA.AperFunction,Plated,PTH,ViaDrill",
                            "T01C0.200",
                            "; #@! TA.AperFunction,Plated,PTH,ComponentDrill",
                            "T02C0.300",
                            "%",
                            "T01",
                            "X000000Y000000",
                            "T02",
                            "X010000Y000000",
                            "M30",
                        )
                    )
                )

            scan = parse_excellon_scan(path)

        via_rows = [
            finding
            for finding in scan.findings
            if finding.item == "Smallest Drill Size"
        ]
        pth_rows = [
            finding for finding in scan.findings if finding.item == "Smallest PTH"
        ]
        self.assertEqual([0.2], [finding.value for finding in via_rows])
        self.assertEqual(["VIADRILL"], [finding.raw["tool_function"] for finding in via_rows])
        self.assertEqual([0.3], [finding.value for finding in pth_rows])
        self.assertEqual(["COMPONENTDRILL"], [finding.raw["tool_function"] for finding in pth_rows])

    def test_excellon_file_function_and_coordinate_quantization_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "renamed-drill.xln")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "\n".join(
                        (
                            "M48",
                            "; #@! TF.FileFunction,Plated,1,2,PTH",
                            "INCH",
                            "T01C0.0236",
                            "%",
                            "T01",
                            "X0.7874Y2.5866",
                            "M30",
                        )
                    )
                )

            scan = parse_excellon_scan(path)

        self.assertEqual("Plated,1,2,PTH", scan.file_function)
        self.assertEqual((1, 2), scan.layer_span)
        self.assertEqual("inch", scan.units)
        self.assertAlmostEqual(0.00254, scan.coordinate_resolution_mm)
        self.assertAlmostEqual(
            0.00254, scan.primitives[0].coordinate_resolution_mm
        )
        first = scan.findings[0].raw
        self.assertAlmostEqual(0.00254, first["coordinate_resolution_mm"])
        self.assertAlmostEqual(0.00127, first["quantization_tolerance_mm"])
        self.assertEqual((1, 2), first["layer_span"])

    def test_decimal_excellon_trailing_zero_elision_uses_file_precision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "decimal-PTH.drl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "\n".join(
                        (
                            "M48",
                            "; FORMAT={-:-/ absolute / inch / decimal}",
                            "; #@! TF.FileFunction,Plated,1,2,PTH",
                            "INCH",
                            "T01C0.0100",
                            "%",
                            "T01",
                            # Decimal Excellon permits the writer to omit
                            # trailing zeroes independently for each value.
                            "X0.0Y0.0",
                            "X0.05Y0.0",
                            "X10.0000Y10.0000",
                            "M30",
                        )
                    )
                )

            scan = parse_excellon_scan(path)
            spacing = list(export_scanners.scan_drill_spacing((scan,), 0.7))

        self.assertAlmostEqual(0.00254, scan.coordinate_resolution_mm)
        self.assertTrue(
            all(
                abs(primitive.coordinate_resolution_mm - 0.00254) < 1e-12
                for primitive in scan.primitives
            )
        )
        self.assertTrue(
            all(
                abs(finding.raw["coordinate_resolution_mm"] - 0.00254) < 1e-12
                for finding in scan.findings
            )
        )
        self.assertEqual([], spacing)

    def test_nonplated_excellon_also_reports_board_thickness_ratio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "board-NPTH.drl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "\n".join(
                        (
                            "M48",
                            "; #@! TF.FileFunction,NonPlated,1,2,NPTH",
                            "METRIC,TZ",
                            "; #@! TA.AperFunction,NonPlated,NPTH,ComponentDrill",
                            "T01C0.700",
                            "%",
                            "T01",
                            "X000000Y000000",
                            "M30",
                        )
                    )
                )

            scan = parse_excellon_scan(path, board_thickness_mm=1.6)

        by_item = {finding.item: finding for finding in scan.findings}
        self.assertNotIn("Smallest Drill Size", by_item)
        self.assertNotIn("Smallest PTH", by_item)
        self.assertAlmostEqual(1.6 / 0.7, by_item["Aspect Ratio"].value, places=6)
        self.assertIs(False, scan.plated)

    def test_excellon_m15_g01_routes_are_slots_not_endpoint_drills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "board-PTH.drl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "\n".join(
                        (
                            "M48",
                            "; #@! TF.FileFunction,Plated,1,2,PTH",
                            "INCH",
                            "T5C0.0236",
                            "%",
                            "T5",
                            "G00X0.7874Y2.5866",
                            "M15",
                            "G01X0.7874Y2.6299",
                            "M16",
                            "G05",
                            "G00X1.3189Y2.5866",
                            "M15",
                            "G01X1.3189Y2.6299",
                            "M16",
                            "G05",
                            "M30",
                        )
                    )
                )

            scan = parse_excellon_scan(path, board_thickness_mm=1.6)

        slots = [primitive for primitive in scan.primitives if primitive.kind == "slot"]
        circles = [primitive for primitive in scan.primitives if primitive.kind == "circle"]
        widths = [
            finding
            for finding in scan.findings
            if finding.item == "Largest Slot Width"
        ]
        self.assertEqual(2, len(slots))
        self.assertEqual([], circles)
        self.assertEqual(2, len(widths))
        self.assertTrue(all(abs(finding.value - 0.59944) < 1e-9 for finding in widths))
        self.assertTrue(all(abs(finding.raw["length"] - 1.69926) < 1e-9 for finding in widths))
        minimum_widths = [
            finding
            for finding in scan.findings
            if finding.item == "Smallest Slot Width"
        ]
        self.assertEqual(2, len(minimum_widths))
        ratios = [finding for finding in scan.findings if finding.item == "Aspect Ratio"]
        self.assertEqual(2, len(ratios))
        self.assertTrue(
            all(abs(finding.value - 1.6 / 0.59944) < 1e-9 for finding in ratios)
        )

    def test_excellon_reports_every_drill_pair_inside_spacing_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "board-PTH.drl")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "\n".join(
                        (
                            "M48",
                            "METRIC,TZ",
                            "T01C0.200",
                            "%",
                            "T01",
                            "X000000Y000000",
                            "X003000Y000000",
                            "X006000Y000000",
                            "M30",
                        )
                    )
                )

            scan = parse_excellon_scan(path, spacing_limit=0.5)

        parser_spacing = [
            finding for finding in scan.findings
            if finding.category == "Drill Hole Spacing"
        ]
        spacing = list(export_scanners.scan_drill_spacing((scan,), 0.5))
        self.assertEqual([], parser_spacing)
        self.assertEqual(3, len(spacing))
        self.assertEqual([0.1, 0.1, 0.4], [round(row.value, 6) for row in spacing])

    def test_global_drill_spacing_crosses_pth_npth_and_deduplicates_holes(self):
        pth = ExcellonScan("board-PTH.drl")
        pth.plated = True
        pth.layer_span = (1, 4)
        pth.coordinate_resolution_mm = 0.001
        pth.primitives.append(
            DrillPrimitive(
                "circle", center=(0.0, 0.0), diameter=0.2,
                coordinate_resolution_mm=0.001,
            )
        )
        npth = ExcellonScan("board-NPTH.drl")
        npth.plated = False
        npth.layer_span = (1, 4)
        npth.coordinate_resolution_mm = 0.001
        npth.primitives.extend(
            (
                DrillPrimitive(
                    "circle", center=(0.0, 0.0), diameter=0.2,
                    coordinate_resolution_mm=0.001,
                ),
                DrillPrimitive(
                    "circle", center=(0.4, 0.0), diameter=0.2,
                    coordinate_resolution_mm=0.001,
                ),
            )
        )

        spacing = list(export_scanners.scan_drill_spacing((pth, npth), 0.5))

        self.assertEqual(1, len(spacing))
        self.assertAlmostEqual(0.2, spacing[0].value)
        self.assertEqual((1, 4), spacing[0].raw["layer_span_intersection"])
        self.assertEqual("intersecting", spacing[0].raw["layer_span_status"])
        self.assertEqual(
            ("board-NPTH.drl", "board-PTH.drl"),
            spacing[0].raw["source_files"],
        )
        self.assertEqual("mixed", spacing[0].raw["primary"]["plated"])

    def test_global_drill_spacing_ignores_disjoint_layer_spans(self):
        front_blind = ExcellonScan("front-blind.drl")
        front_blind.layer_span = (1, 2)
        front_blind.primitives.append(
            DrillPrimitive("circle", center=(0.0, 0.0), diameter=0.2)
        )
        back_blind = ExcellonScan("back-blind.drl")
        back_blind.layer_span = (3, 4)
        back_blind.primitives.append(
            DrillPrimitive("circle", center=(0.3, 0.0), diameter=0.2)
        )

        spacing = list(
            export_scanners.scan_drill_spacing((front_blind, back_blind), 0.5)
        )

        self.assertEqual([], spacing)

    def test_global_drill_spacing_checkpoints_sparse_scans(self):
        scan = ExcellonScan("sparse-PTH.drl")
        scan.layer_span = (1, 2)
        scan.primitives.extend(
            DrillPrimitive(
                "circle", center=(index * 2.0, 0.0), diameter=0.2
            )
            for index in range(300)
        )
        checkpoints = []

        findings = list(
            export_scanners.scan_drill_spacing(
                (scan,), 0.5, checkpoint=lambda: checkpoints.append(True)
            )
        )

        self.assertEqual([], findings)
        self.assertTrue(checkpoints)

    def test_drill_spacing_quantization_boundary_is_marked_partial(self):
        left = ExcellonScan("left-PTH.drl")
        left.layer_span = (1, 2)
        left.coordinate_resolution_mm = 0.001
        left.primitives.append(
            DrillPrimitive(
                "circle", center=(0.0, 0.0), diameter=0.2,
                coordinate_resolution_mm=0.001,
            )
        )
        right = ExcellonScan("right-PTH.drl")
        right.layer_span = (1, 2)
        right.coordinate_resolution_mm = 0.001
        right.primitives.append(
            DrillPrimitive(
                "circle", center=(0.59955, 0.0), diameter=0.2,
                coordinate_resolution_mm=0.001,
            )
        )
        finding = list(
            export_scanners.scan_drill_spacing((left, right), 0.5)
        )[0]
        checks = ExportChecks(None, rules=rules_for_profile("standard"))

        checks._add_scan_finding(finding)

        row = checks.native_results["Drill Hole Spacing"][0]
        self.assertEqual("gold", row["color"])
        self.assertEqual("red", row["raw"]["nominal_color"])
        self.assertEqual("borderline", row["threshold_status"])
        self.assertEqual("completed", row["execution_status"])
        self.assertAlmostEqual(0.001, row["uncertainty_mm"])
        self.assertEqual(("red", "gold"), row["raw"]["decision_interval_colors"])
        self.assertAlmostEqual(0.39855, row["measurement_interval_mm"][0])
        self.assertAlmostEqual(0.40055, row["measurement_interval_mm"][1])

    def test_nominal_black_quantization_boundary_needs_native_validation(self):
        finding = ScanFinding(
            "Different Net PTH Spacing",
            "Quantized Excellon spacing",
            category="Drill Hole Spacing",
            value=0.4505,
            layer=["Drl"],
            raw={
                "file": "board-PTH.drl",
                "uncertainty_mm": 0.001,
                "segment": ((0.0, 0.0), (0.6505, 0.0)),
                "primary": {"point": (0.0, 0.0)},
                "related": {"point": (0.6505, 0.0)},
            },
        )
        checks = ExportChecks(None, rules=rules_for_profile("standard"))

        checks._add_scan_finding(finding)

        row = checks.native_results["Drill Hole Spacing"][0]
        self.assertEqual("gold", row["color"])
        self.assertEqual("black", row["raw"]["nominal_color"])
        self.assertEqual("borderline", row["threshold_status"])
        self.assertEqual("completed", row["execution_status"])
        self.assertEqual(("gold", "black"), row["raw"]["decision_interval_colors"])

    def test_definite_red_outweighs_borderline_gold_in_native_summary(self):
        checks = ExportChecks(None, rules=rules_for_profile("standard"))
        checks._add_scan_finding(
            ScanFinding(
                "Different Net PTH Spacing",
                "Borderline quantized spacing",
                category="Drill Hole Spacing",
                value=0.4005,
                layer=["Drl"],
                raw={
                    "file": "borderline-PTH.drl",
                    "uncertainty_mm": 0.001,
                    "segment": ((0.0, 0.0), (0.6005, 0.0)),
                },
            )
        )
        checks._add_scan_finding(
            ScanFinding(
                "Different Net PTH Spacing",
                "Definite spacing violation",
                category="Drill Hole Spacing",
                value=0.2,
                layer=["Drl"],
                raw={
                    "file": "definite-PTH.drl",
                    "segment": ((0.0, 1.0), (0.4, 1.0)),
                },
            )
        )

        result = checks.native_result_map()["Drill Hole Spacing"]

        self.assertEqual("red", result["color"])
        self.assertEqual(1, result["borderline_count"])
        self.assertEqual(
            1,
            result["item_summaries"]["Different Net PTH Spacing"][
                "borderline_count"
            ],
        )


def make_export(
    tmpdir,
    skip=(),
    empty=(),
    trace_width=0.2,
    drill_diameter=0.8,
    slot=False,
    drill_points=True,
    second_drill_x="020000",
    explicit_tool_select=True,
    output_subdir="HQDMF",
    open_outline=False,
    trace_y=1.0,
    repeated_draws=False,
    no_drill_tools=False,
    filename_prefix="",
    include_flash_pad=False,
    include_obround_pad=False,
    obround_pad_origin=False,
    obround_pad_size=(0.8, 0.4),
    include_macro_pad=False,
    macro_pad_origin=False,
    second_trace_y=None,
    flash_pad_pair=False,
    round_flash_pad=False,
    flash_pad_origin=False,
    include_region=False,
):
    output_dir = os.path.join(tmpdir, output_subdir)
    os.makedirs(output_dir)
    files = []
    content = {
        "CuTop.gbr": gerber(
            trace_width,
            y=trace_y,
            repeated_draws=repeated_draws,
            include_flash_pad=include_flash_pad,
            include_obround_pad=include_obround_pad,
            obround_pad_origin=obround_pad_origin,
            obround_pad_size=obround_pad_size,
            include_macro_pad=include_macro_pad,
            macro_pad_origin=macro_pad_origin,
            second_trace_y=second_trace_y,
            flash_pad_pair=flash_pad_pair,
            round_flash_pad=round_flash_pad,
            flash_pad_origin=flash_pad_origin,
            include_region=include_region,
        ),
        "CuBottom.gbr": gerber(0.2, y=2.0),
        "SilkTop.gbr": gerber(0.15),
        "EdgeCuts.gbr": edge_gerber(open_outline=open_outline),
        "board.drl": excellon(
            drill_diameter,
            slot=slot,
            drill_points=drill_points,
            second_drill_x=second_drill_x,
            explicit_tool_select=explicit_tool_select,
            no_tools=no_drill_tools,
        ),
        "drill-map.map": "map\n",
    }
    for filename, text in content.items():
        if filename in skip:
            continue
        output_filename = gerber_filename(filename, filename_prefix)
        path = os.path.join(output_dir, output_filename)
        with open(path, "w", encoding="utf-8") as fp:
            if filename not in empty:
                fp.write(text)
        files.append(path)
    zip_path = output_dir + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, os.path.relpath(path, output_dir))
    return ExportResult(
        output_dir=output_dir,
        zip_path=zip_path,
        files=tuple(files),
        plot_plan=PLOT_PLAN,
        layer_count=2,
    )


def gerber_filename(filename, prefix):
    if not prefix or not filename.lower().endswith((".gbr", ".ger")):
        return filename
    return "{0}{1}".format(prefix, filename)


def gerber(
    width,
    y=1.0,
    repeated_draws=False,
    include_flash_pad=False,
    include_obround_pad=False,
    obround_pad_origin=False,
    obround_pad_size=(0.8, 0.4),
    include_macro_pad=False,
    macro_pad_origin=False,
    second_trace_y=None,
    flash_pad_pair=False,
    round_flash_pad=False,
    flash_pad_origin=False,
    include_region=False,
):
    aperture = str(width)
    y_coord = int(round(y * 1000000))
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,{0}*%".format(aperture if "X" in aperture else "{0:.3f}".format(float(width))),
        "D10*",
        "X1000000Y{0}D02*".format(y_coord),
        "X9000000Y{0}D01*".format(y_coord),
    ]
    if repeated_draws:
        commands.extend(
            [
                "X1000000Y{0}D02*".format(y_coord + 100000),
                "X9000000Y{0}D01*".format(y_coord + 100000),
            ]
        )
    if second_trace_y is not None:
        second_y_coord = int(round(second_trace_y * 1000000))
        commands.extend(
            [
                "D10*",
                "X1000000Y{0}D02*".format(second_y_coord),
                "X9000000Y{0}D01*".format(second_y_coord),
            ]
        )
    if include_flash_pad:
        commands.extend(
            [
                "%ADD11R,0.800X0.400*%",
                "D11*",
                "X500000Y500000D03*",
            ]
        )
    if include_obround_pad:
        obround_pad = "X0Y0D03*" if obround_pad_origin else "X500000Y500000D03*"
        commands.extend(
            [
                "%ADD14O,{0:.3f}X{1:.3f}*%".format(*obround_pad_size),
                "D14*",
                obround_pad,
            ]
        )
    if include_macro_pad:
        macro_pad = "X0Y0D03*" if macro_pad_origin else "X500000Y500000D03*"
        commands.extend(
            [
                "%AMROUNDPAD*1,1,0.400,0,0*%",
                "%ADD15ROUNDPAD*%",
                "D15*",
                macro_pad,
            ]
        )
    if flash_pad_pair:
        first_pad = "X0Y0D03*" if flash_pad_origin else "X500000Y500000D03*"
        commands.extend(
            [
                "%TA.AperFunction,SMDPad,CuDef*%",
                "%ADD12R,0.400X0.400*%",
                "%TD*%",
                "D12*",
                first_pad,
                "X1000000Y500000D03*",
            ]
        )
    if round_flash_pad:
        commands.extend(
            [
                "%ADD13C,0.400*%",
                "D13*",
                "X0Y0D03*",
                "X500000Y0D03*",
            ]
        )
    if include_region:
        commands.extend(
            [
                "G36*",
                "X100000Y100000D02*",
                "X900000Y100000D01*",
                "X900000Y900000D01*",
                "X100000Y900000D01*",
                "X100000Y100000D01*",
                "G37*",
            ]
        )
    commands.extend(("M02*", ""))
    return "\n".join(commands)


def edge_gerber(size=10.0, open_outline=False, format_header="%FSLAX46Y46*%", modal=False):
    scale = 100000 if format_header == "%FSLAX35Y35*%" else 1000000
    max_coord = int(round(size * scale))
    suffix = "*" if modal else "D01*"
    commands = [
        format_header,
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "D10*",
        "X0Y0D02*",
        "X{0}Y0D01*".format(max_coord),
        "X{0}Y{0}{1}".format(max_coord, suffix),
        "X0Y{0}{1}".format(max_coord, suffix),
    ]
    if not open_outline:
        commands.append("X0Y0{0}".format(suffix))
    commands.extend(("M02*", ""))
    return "\n".join(commands)


def arc_edge_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "D10*",
        "G01*",
        "X1000000Y0D02*",
        "G03X0Y1000000I-1000000J0D01*",
        "G03X-1000000Y0I0J-1000000D01*",
        "G03X0Y-1000000I1000000J0D01*",
        "G03X1000000Y0I0J1000000D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def single_quadrant_arc_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "D10*",
        "G74*",
        "X1000000Y0D02*",
        "G03X0Y1000000I1000000J0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def trailing_zero_edge_gerber():
    commands = [
        "%FSTAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "D10*",
        "X0Y0D02*",
        "X0001Y0D01*",
        "X0001Y0001D01*",
        "X0Y0001D01*",
        "X0Y0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def incremental_edge_gerber():
    commands = [
        "%FSLIX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "D10*",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "X0Y1000000D01*",
        "X-1000000Y0D01*",
        "X0Y-1000000D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def g90_g91_edge_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "D10*",
        "X0Y0D02*",
        "G91*",
        "X1000000Y0D01*",
        "X0Y1000000D01*",
        "G90*",
        "X0Y1000000D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def legacy_inch_edge_gerber():
    commands = [
        "%FSLAX24Y24*%",
        "G70*",
        "%ADD10C,0.010*%",
        "D10*",
        "X0Y0D02*",
        "X1000Y0D01*",
        "X1000Y1000D01*",
        "X0Y1000D01*",
        "X0Y0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def legacy_g54_aperture_select_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "G54D10*",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def plus_aperture_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,+0.150*%",
        "D10*",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def single_line_gerber():
    return "%FSLAX46Y46*%%MOMM*%%ADD10C,0.150*%D10*X0Y0D02*X1000000Y0D01*M02*\n"


def commented_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%TF.FileFunction,Copper,L1,Top*%",
        "G04 X2000000Y0D01 is a comment and must not draw*",
        "%ADD10C,0.150*%",
        "D10*",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def lowercase_gerber():
    commands = [
        "%fslax46y46*%",
        "%momm*%",
        "%add10c,0.150*%",
        "d10*",
        "x0y0d02*",
        "x1000000y0d01*",
        "m02*",
        "",
    ]
    return "\n".join(commands)


def spaced_coordinate_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "D 10 *",
        "X 0 Y 0 D 02 *",
        "X 1000000 Y 0 D 01 *",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def step_repeat_flash_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.200*%",
        "D10*",
        "%SRX2Y1I1.000J0.000*%",
        "X0Y0D03*",
        "%SR*%",
        "X5000000Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def step_repeat_segment_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.200*%",
        "D10*",
        "%SRX1Y2I0.000J2.000*%",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def lowercase_step_repeat_segment_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.200*%",
        "D10*",
        "%srx1y2i0.000j2.000*%",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def spaced_step_repeat_flash_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.200*%",
        "D10*",
        "%SR X 2 Y 1 I 1.000 J 0.000 *%",
        "X0Y0D03*",
        "%SR *%",
        "X5000000Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def round_aperture_with_hole_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,1.000X0.400*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def rect_aperture_with_hole_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10R,1.000X0.800X0.300*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def rect_plus_lowercase_x_aperture_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10R,+0.800x+0.400*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def spaced_add_aperture_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD 10 R, +0.800 x +0.400 *%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def rect_aperture_with_rect_hole_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10R,1.000X0.800X0.400X0.200*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def polygon_aperture_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10P,1.000X6X0*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def polygon_aperture_inch_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "G70*",
        "%ADD10P,0.100X6X0*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def polygon_aperture_with_hole_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10P,1.000X6X0X0.200*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def offset_macro_circle_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMOFFSETCIRCLE*1,1,0.400,0.250,-0.100*%",
        "%ADD10OFFSETCIRCLE*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def parameterized_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMPARAMCIRCLE*1,1,$1,0,0*%",
        "%ADD10PARAMCIRCLE,0.450*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def parameterized_macro_inch_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "G70*",
        "%AMPARAMCIRCLE*1,1,$1,0,0*%",
        "%ADD10PARAMCIRCLE,0.100*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def parameterized_macro_lowercase_x_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMPARAMRECT*21,1,$1,$2,0,0*%",
        "%ADD10PARAMRECT,0.400x0.200*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def parameterized_macro_expression_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMPARAMHALF*1,1,$1/2,0,0*%",
        "%ADD10PARAMHALF,0.600*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def macro_arithmetic_expression_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMEXPRCIRCLE*1,1,(0.200+0.300)X1,0,0*%",
        "%ADD10EXPRCIRCLE*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def macro_variable_assignment_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMASSIGNCIRCLE*$2=$1/2*1,1,$2,0,0*%",
        "%ADD10ASSIGNCIRCLE,0.800*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def clear_macro_circle_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMTHERMALPAD*1,1,0.600,0,0*1,0,0.200,0,0*%",
        "%ADD10THERMALPAD*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def polygon_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMPOLYPAD*5,1,5,0,0,0.800,0*%",
        "%ADD10POLYPAD*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def clear_polygon_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMPOLYCLEAR*1,1,1.000,0,0*5,0,5,0,0,0.300,0*%",
        "%ADD10POLYCLEAR*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def outline_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMOUTLINEPAD*4,1,3,-0.500,0,0.500,0,0,1.000,0*%",
        "%ADD10OUTLINEPAD*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def clear_outline_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMOUTLINECLEAR*1,1,1.000,0,0*4,0,3,-0.250,0,0.250,0,0,0.500,0*%",
        "%ADD10OUTLINECLEAR*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def vector_line_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMLINEPAD*20,1,0.200,-0.500,0,0.500,0,0*%",
        "%ADD10LINEPAD*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def vector_line_code_2_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMLINEPAD2*2,1,0.200,-0.400,0,0.400,0,0*%",
        "%ADD10LINEPAD2*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def clear_vector_line_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMLINECLEAR*1,1,1.000,0,0*20,0,0.200,-0.250,0,0.250,0,0*%",
        "%ADD10LINECLEAR*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def clear_vector_line_code_2_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMLINECLEAR2*1,1,1.000,0,0*2,0,0.200,-0.200,0,0.200,0,0*%",
        "%ADD10LINECLEAR2*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def thermal_macro_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%AMTHERMALRELIEF*7,0,0,1.000,0.300,0.100,0*%",
        "%ADD10THERMALRELIEF*%",
        "D10*",
        "X0Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def round_draw_aperture_with_hole_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,1.000X0.400*%",
        "D10*",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def region_arc_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "D10*",
        "G36*",
        "G01*",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "G03X0Y0I-500000J0D01*",
        "G37*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def clear_flash_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.500*%",
        "%LPD*%",
        "D10*",
        "X0Y0D03*",
        "%LPC*%",
        "X1000000Y0D03*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def clear_region_gerber():
    commands = [
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%ADD10C,0.150*%",
        "%LPC*%",
        "D10*",
        "G36*",
        "X0Y0D02*",
        "X1000000Y0D01*",
        "X0Y1000000D01*",
        "X0Y0D01*",
        "G37*",
        "M02*",
        "",
    ]
    return "\n".join(commands)


def excellon(
    diameter,
    slot=False,
    drill_points=True,
    second_drill_x="020000",
    explicit_tool_select=True,
    no_tools=False,
):
    commands = [
        "M48",
        "METRIC,TZ",
    ]
    if not no_tools:
        commands.append("T01C{0:.3f}".format(diameter))
    commands.append("%")
    if explicit_tool_select:
        commands.append("T01")
    if drill_points:
        commands.extend(
            [
                "X000000Y000000",
                "X{0}Y000000".format(second_drill_x),
            ]
        )
    if slot:
        commands.append("X020000Y000000G85X025000Y000000")
    commands.append("M30")
    return "\n".join(commands) + "\n"


if __name__ == "__main__":
    unittest.main()
