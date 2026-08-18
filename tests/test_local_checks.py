import unittest
from dataclasses import replace
from unittest import mock

from kicad_dfm.config import Language_chinese, Language_english
from kicad_dfm.core.rule_profiles import rules_for_profile
from kicad_dfm.kicad.backend import BoardBackend
from kicad_dfm.services import local_checks as local_checks_module
from kicad_dfm.services.local_checks import LocalChecks
from kicad_dfm.services.local_checks import max_bbox_width_nm
from kicad_dfm.services.local_checks import nearby_items
from kicad_dfm.services.offline_analysis import OfflineDfmAnalysis
from kicad_dfm.settings.color_rule import ColorRule


class FakeUuid:
    def __init__(self, value):
        self.value = value

    def AsString(self):
        return self.value


class FakePoint:
    def __init__(self, x, y):
        self.x = int(x)
        self.y = int(y)


class FakeBox:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def GetLeft(self):
        return self.left

    def GetTop(self):
        return self.top

    def GetRight(self):
        return self.right

    def GetBottom(self):
        return self.bottom


class LocalChecksProgressTest(unittest.TestCase):
    def test_repeated_inner_loop_heartbeats_are_time_throttled(self):
        checks = object.__new__(LocalChecks)
        calls = []
        checks._heartbeat = lambda: calls.append(True)
        checks._heartbeat_count = 0
        checks._heartbeat_last_at = None

        with mock.patch.object(
            local_checks_module.time,
            "monotonic",
            side_effect=(0.0, 0.01, 0.06),
        ):
            for _index in range(96):
                checks._checkpoint()

        self.assertEqual(2, len(calls))


class FakeTrack:
    def __init__(self, item_id, start, end, width, layer="F.Cu", net=""):
        self.m_Uuid = FakeUuid(item_id)
        self.start = FakePoint(*start)
        self.end = FakePoint(*end)
        self.width = int(width)
        self.layer = layer
        self.net = net

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetWidth(self):
        return self.width

    def GetLayerName(self):
        return self.layer

    def GetBoundingBox(self):
        return FakeBox(
            min(self.start.x, self.end.x),
            min(self.start.y, self.end.y),
            max(self.start.x, self.end.x),
            max(self.start.y, self.end.y),
        )

    def GetNetname(self):
        return self.net

    def GetBoundingBox(self):
        half = self.width // 2
        return FakeBox(
            min(self.start.x, self.end.x) - half,
            min(self.start.y, self.end.y) - half,
            max(self.start.x, self.end.x) + half,
            max(self.start.y, self.end.y) + half,
        )


class FakeArc(FakeTrack):
    def __init__(self, item_id, start, midpoint, end, width, layer="F.Cu", net=""):
        super().__init__(item_id, start, end, width, layer, net)
        self.midpoint = FakePoint(*midpoint)

    def GetMid(self):
        return self.midpoint


class FakeVia(FakeTrack):
    def __init__(self, item_id, center, width, drill, layer="F.Cu", net="", via_type=None, layer_pair=()):
        super().__init__(item_id, center, center, width, layer, net)
        self.center = FakePoint(*center)
        self.drill = int(drill)
        self.via_type = via_type
        self.layer_pair = layer_pair

    def GetPosition(self):
        return self.center

    def GetDrill(self):
        return self.drill

    def GetViaType(self):
        return self.via_type

    def TopLayer(self):
        return self.layer_pair[0] if self.layer_pair else self.layer

    def BottomLayer(self):
        return self.layer_pair[1] if len(self.layer_pair) > 1 else self.layer

    def GetBoundingBox(self):
        half = self.width // 2
        return FakeBox(
            self.center.x - half,
            self.center.y - half,
            self.center.x + half,
            self.center.y + half,
        )


class FakePad:
    def __init__(
        self,
        item_id,
        center,
        size,
        drill=(0, 0),
        layer="F.Cu",
        net="",
        attribute=1,
        shape=0,
        drill_shape=0,
        mask_open=True,
        round_drill=None,
    ):
        self.m_Uuid = FakeUuid(item_id)
        self.center = FakePoint(*center)
        self.size = size
        self.drill = drill
        self.layer = layer
        self.net = net
        self.attribute = attribute
        self.shape = shape
        self.drill_shape = drill_shape
        self.mask_open = mask_open
        self.round_drill = round_drill

    def GetPosition(self):
        return self.center

    def GetLayerName(self):
        return self.layer

    def GetNetname(self):
        return self.net

    def GetAttribute(self):
        return self.attribute

    def GetShape(self):
        return self.shape

    def GetDrillShape(self):
        return self.drill_shape

    def GetSizeX(self):
        return self.size[0]

    def GetSizeY(self):
        return self.size[1]

    def GetDrillSizeX(self):
        return self.drill[0]

    def GetDrillSizeY(self):
        return self.drill[1]

    def GetBoundingBox(self):
        half_x = self.size[0] // 2
        half_y = self.size[1] // 2
        return FakeBox(
            self.center.x - half_x,
            self.center.y - half_y,
            self.center.x + half_x,
            self.center.y + half_y,
        )


class FakeFootprint:
    def __init__(self, pads, name="U1"):
        self._pads = pads
        self.name = name

    def Pads(self):
        return self._pads

    def GetValue(self):
        return self.name


class FakeDrawing:
    def __init__(self, start, end, layer="Edge.Cuts"):
        self.start = FakePoint(*start)
        self.end = FakePoint(*end)
        self.layer = layer

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetLayerName(self):
        return self.layer

    def GetBoundingBox(self):
        return FakeBox(
            min(self.start.x, self.end.x),
            min(self.start.y, self.end.y),
            max(self.start.x, self.end.x),
            max(self.start.y, self.end.y),
        )


class FakeShapeDrawing(FakeDrawing):
    def __init__(self, start, midpoint, end, shape, layer="Edge.Cuts"):
        super().__init__(start, end, layer=layer)
        self.midpoint = FakePoint(*midpoint)
        self.shape = shape

    def GetShape(self):
        return self.shape

    def GetArcMid(self):
        # KiCad's PCB_SHAPE exposes this method for both lines and arcs.
        return self.midpoint


class FakeZone:
    def __init__(self, item_id, center, size, layer="F.Cu", net=""):
        self.m_Uuid = FakeUuid(item_id)
        self.center = FakePoint(*center)
        self.size = size
        self.layer = layer
        self.net = net

    def GetPosition(self):
        return self.center

    def GetLayerName(self):
        return self.layer

    def GetNetname(self):
        return self.net

    def GetBoundingBox(self):
        half_x = self.size[0] // 2
        half_y = self.size[1] // 2
        return FakeBox(
            self.center.x - half_x,
            self.center.y - half_y,
            self.center.x + half_x,
            self.center.y + half_y,
        )


class FakeText(FakeZone):
    def __init__(self, item_id, center, size, polygons, layer="F.Cu"):
        super().__init__(item_id, center, size, layer=layer)
        self.polygons = polygons

    def GetStart(self):
        return FakePoint(self.center.x - self.size[0] // 2, self.center.y)

    def GetEnd(self):
        return FakePoint(self.center.x + self.size[0] // 2, self.center.y)


class FakeDesignSettings:
    def __init__(self, thickness):
        self.thickness = thickness

    def GetBoardThickness(self):
        return self.thickness


class FakeBoard:
    def __init__(self, tracks=(), pads=(), drawings=(), zones=(), footprint_name="U1", thickness=1600000):
        self.tracks = tracks
        self.footprints = (FakeFootprint(pads, footprint_name),)
        self.drawings = drawings
        self.zones = zones
        self.thickness = thickness

    def GetTracks(self):
        return self.tracks

    def GetFootprints(self):
        return self.footprints

    def Zones(self):
        return self.zones

    def GetDrawings(self):
        return self.drawings

    def GetLayerID(self, layer):
        return {
            "F.Cu": 0,
            "In1.Cu": 1,
            "In2.Cu": 2,
            "In3.Cu": 3,
            "B.Cu": 31,
            "F.Mask": 36,
            "B.Mask": 37,
            "Edge.Cuts": 44,
        }.get(layer, -1)

    def GetLayerName(self, layer_id):
        return {
            0: "F.Cu",
            1: "In1.Cu",
            2: "In2.Cu",
            3: "In3.Cu",
            31: "B.Cu",
            36: "F.Mask",
            37: "B.Mask",
            44: "Edge.Cuts",
        }.get(layer_id, "")

    def GetDesignSettings(self):
        return FakeDesignSettings(self.thickness)


class FakeBackend:
    def __init__(self, board):
        self.board = board

    def iter_tracks(self):
        return iter(self.board.tracks)

    def iter_footprints(self):
        return iter(self.board.footprints)

    def iter_pads(self, footprint):
        return iter(footprint.Pads())

    def footprint_names(self, footprint):
        return (footprint.GetValue(),)

    def iter_zones(self):
        return iter(self.board.zones)

    def iter_drawings(self):
        return iter(self.board.drawings)

    def zone_polygons(self, zone, layer_id=None):
        return getattr(zone, "polygons", ())

    def is_via(self, item):
        return isinstance(item, FakeVia)

    def is_text(self, item):
        return isinstance(item, FakeText)

    def is_custom_pad(self, item):
        return False

    def text_stroke_polygons(self, item):
        return item.polygons if self.is_text(item) else ()

    def text_stroke_segments(self, item):
        if not self.is_text(item):
            return ()
        return tuple(
            (
                (polygon[0][0][0], (polygon[0][0][1] + polygon[0][2][1]) / 2.0),
                (polygon[0][2][0], (polygon[0][0][1] + polygon[0][2][1]) / 2.0),
                polygon[0][2][1] - polygon[0][0][1],
            )
            for polygon in item.polygons
        )

    def is_track(self, item):
        return isinstance(item, FakeTrack) and not isinstance(item, FakeVia)

    def is_pad(self, item):
        return isinstance(item, FakePad)

    def is_round_pth_pad(self, pad):
        return pad.attribute == 0 and pad.shape == 0 and pad.drill_shape == 0

    def is_smd_pad(self, pad):
        return pad.attribute == 1

    def is_pth_pad(self, pad):
        return pad.attribute == 0

    def is_npth_pad(self, pad):
        return pad.attribute == 3

    def is_bga_pad(self, pad, footprint=None):
        return footprint is not None and "BGA" in footprint.GetValue().upper()

    def pad_has_solder_mask_opening(self, pad):
        return pad.mask_open

    def board_thickness_mm(self):
        return self.board.thickness / 1000000.0

    def item_type(self, item):
        return type(item).__name__

    def item_id(self, item):
        return item.m_Uuid.AsString()

    def item_layer_name(self, item):
        return item.GetLayerName()

    def item_layer_id(self, item):
        return self.board.GetLayerID(item.GetLayerName())

    def item_net_name(self, item):
        return item.GetNetname() if hasattr(item, "GetNetname") else ""

    def item_bbox(self, item):
        box = item.GetBoundingBox()
        return box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom()

    def hole_bbox(self, item):
        if isinstance(item, FakeVia):
            size_x = size_y = item.drill
        elif isinstance(item, FakePad):
            size_x, size_y = item.drill
        else:
            return None
        if not size_x or not size_y:
            return None
        center = item.GetPosition()
        return (
            center.x - size_x // 2,
            center.y - size_y // 2,
            center.x + size_x // 2,
            center.y + size_y // 2,
        )

    def item_width(self, item):
        return item.GetWidth()

    def via_width_mm(self, item):
        return item.width / 1000000.0

    def via_drill_mm(self, item):
        return item.drill / 1000000.0

    def via_type(self, item):
        return item.via_type

    def via_layer_pair_names(self, item):
        return item.layer_pair

    def via_has_solder_mask_opening_on_layer(self, _item, _layer_name):
        return True

    def is_micro_via(self, item):
        return item.via_type == "micro"

    def is_blind_buried_via(self, item):
        return item.via_type in ("blind", "buried", "micro")

    def pad_size_mm(self, pad):
        return pad.size[0] / 1000000.0, pad.size[1] / 1000000.0

    def pad_shape(self, pad):
        return pad.shape

    def pad_drill_mm(self, pad):
        return pad.drill[0] / 1000000.0, pad.drill[1] / 1000000.0

    def pad_drill_shape(self, pad):
        return pad.drill_shape

    def pad_attribute(self, pad):
        return pad.attribute

    def is_round_drill_pad(self, pad):
        if pad.round_drill is not None:
            return pad.round_drill
        return pad.drill_shape == 0

    def track_segment(self, item):
        if not hasattr(item, "GetStart") or not hasattr(item, "GetEnd"):
            return None
        return (item.GetStart().x, item.GetStart().y), (item.GetEnd().x, item.GetEnd().y)

    def item_position(self, item):
        if hasattr(item, "GetPosition"):
            point = item.GetPosition()
            return point.x, point.y
        return item.GetStart().x, item.GetStart().y

    def board_outline_segments(self):
        return tuple(self.track_segment(item) for item in self.board.drawings)

    def item_clearance_nm(self, left, right, max_distance_nm):
        clearances = getattr(self.board, "item_clearances", {})
        return clearances.get((self.item_id(left), self.item_id(right)))


class LocalChecksTest(unittest.TestCase):
    def test_offline_analysis_refreshes_backend_before_indexing(self):
        board = FakeBoard()

        class LifecycleBackend(FakeBackend):
            def __init__(self, current_board):
                super().__init__(current_board)
                self.begun = False

            def begin_analysis(self):
                self.begun = True

            def iter_tracks(self):
                if not self.begun:
                    raise AssertionError("backend was indexed before begin_analysis")
                return super().iter_tracks()

        backend = LifecycleBackend(board)

        OfflineDfmAnalysis(
            board,
            {},
            backend=backend,
            rules=rules_for_profile("standard"),
        ).analyze()

        self.assertTrue(backend.begun)

    def test_result_collection_does_not_stop_at_legacy_two_thousand_limit(self):
        board = FakeBoard()
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        expected_count = 2005
        rows = (
            {
                "id": "item-%d" % index,
                "item": "Trace Spacing",
                "value": "0.01",
                "color": "red",
                "rule": "0.127000,0.150000,999.000000",
                "layer": ["F.Cu"],
                "item_type": "track",
            }
            for index in range(expected_count)
        )

        result = checks._collect_minimum("Smallest Trace Spacing", rows)

        self.assertEqual(expected_count, len(result["check"]))
        self.assertEqual(expected_count, len(checks.issues))

    def test_minimum_collection_exposes_compatibility_counts(self):
        board = FakeBoard()
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        rows = (
            {
                "id": "bad",
                "item": "Trace Spacing",
                "value": "0.1",
                "color": "red",
                "layer": ["F.Cu"],
                "item_type": "track",
            },
            {
                "id": "ok",
                "item": "Trace Spacing",
                "value": "0.3",
                "color": "black",
                "layer": ["F.Cu"],
                "item_type": "track",
            },
        )

        result = checks._collect_minimum("Smallest Trace Spacing", rows)

        self.assertEqual(2, result["checked_count"])
        self.assertEqual(1, result["violation_count"])
        self.assertEqual(1, result["displayed_count"])

    def test_trace_spacing_exposes_all_rule_item_execution_summaries(self):
        result = self.analyze(FakeBoard(), "standard").kicad_result[
            "Smallest Trace Spacing"
        ]

        summaries = result["item_summaries"]
        self.assertEqual(
            {
                "Trace Spacing",
                "Trace-to-Pad Spacing",
                "Pad-to-Pad Spacing",
                "BGA Pads",
            },
            {summary["item"] for summary in summaries.values()},
        )
        for summary in summaries.values():
            self.assertTrue(summary["rule_key"])
            self.assertEqual("mm", summary["unit"])
            self.assertEqual(0, summary["checked_count"])
            self.assertEqual(0, summary["violation_count"])
            self.assertEqual(0, summary["displayed_count"])
            self.assertEqual("black", summary["color"])
            self.assertEqual("completed", summary["execution_status"])

        smd = self.analyze(FakeBoard(), "standard").kicad_result[
            "SMD Spacing"
        ]
        self.assertEqual(
            {"SMD Pad Spacing"},
            {summary["item"] for summary in smd["item_summaries"].values()},
        )

    def test_trace_spacing_summary_counts_passing_geometry_candidate(self):
        left = FakePad("p1", (0, 0), (400000, 400000), net="A")
        right = FakePad("p2", (200000, 0), (400000, 400000), net="B")
        board = FakeBoard(pads=(left, right))
        board.item_clearances = {("p1", "p2"): 300000}

        result = self.analyze(board, "standard").kicad_result["SMD Spacing"]
        summary = result["item_summaries"][
            "smdspacing:smdpadspacing"
        ]

        self.assertEqual(1, result["checked_count"])
        self.assertEqual(0, result["displayed_count"])
        self.assertEqual(1, summary["checked_count"])
        self.assertEqual(0, summary["violation_count"])
        self.assertEqual(0, summary["displayed_count"])
        self.assertEqual(0.3, summary["display"])
        self.assertEqual("black", summary["color"])
        self.assertEqual("completed", result["execution_status"])

    def test_maximum_and_summary_only_expose_compatibility_counts(self):
        board = FakeBoard()
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        rows = (
            {"item": "Hole on SMD Pad", "value": "0.2", "color": "black"},
            {"item": "Hole on SMD Pad", "value": "0.4", "color": "red"},
        )

        maximum = checks._collect_maximum("Holes on SMD Pads", iter(rows))
        summary = checks._summary_only("Signal Integrity", iter(rows))

        for result in (maximum, summary):
            self.assertEqual(2, result["checked_count"])
            self.assertEqual(1, result["violation_count"])
            self.assertEqual(1, result["displayed_count"])
            self.assertEqual("completed", result["execution_status"])

    def test_hole_size_display_excludes_dimensionless_ratios(self):
        board = FakeBoard()
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        rows = (
            {
                "rule_key": "holesize:smallestpth",
                "item": "Smallest PTH",
                "value": "0.4",
                "color": "black",
            },
            {
                "rule_key": "holesize:aspectratio",
                "item": "Aspect Ratio",
                "value": "0.2",
                "color": "red",
            },
            {
                "rule_key": "holesize:slotaspectratio",
                "item": "Slot Aspect Ratio",
                "value": "0.1",
                "color": "gold",
            },
        )

        result = checks._collect_minimum("Hole Size", rows)

        self.assertEqual(0.4, result["display"])
        self.assertEqual("mm", result["display_unit"])
        self.assertEqual(
            "minimum_dimensional_measurement",
            result["display_semantics"],
        )
        self.assertEqual(
            "mm", result["item_summaries"]["holesize:smallestpth"]["unit"]
        )
        self.assertEqual(
            "ratio", result["item_summaries"]["holesize:aspectratio"]["unit"]
        )
        self.assertEqual(
            "ratio",
            result["item_summaries"]["holesize:slotaspectratio"]["unit"],
        )

    def test_color_rule_treats_missing_measurement_as_not_reportable(self):
        color_rule = ColorRule(rules_for_profile("standard"))

        self.assertEqual(
            "black",
            color_rule.get_rule({}, "Smallest Trace Spacing", "Trace Spacing", None),
        )

    def test_via_annular_ring_between_second_and_third_levels_is_normal(self):
        via = FakeVia("via-5.9mil", (0, 0), 550000, 250000)

        result = self.analyze(
            FakeBoard(tracks=(via,)),
            "standard",
            include_passed_details=True,
        )
        row = first_row(result, "RingHole")

        self.assertEqual("Via Annular Ring", row["item"])
        self.assertEqual("0.15", row["value"])
        self.assertEqual("black", row["color"])
        self.assertEqual("black", result.kicad_result["RingHole"]["color"])

        color_rule = ColorRule(rules_for_profile("standard"))
        self.assertEqual(
            "gold",
            color_rule.get_rule({}, "RingHole", "Via Annular Ring", 4.0 * 0.0254),
        )
        self.assertEqual(
            "black",
            color_rule.get_rule({}, "RingHole", "Via Annular Ring", 5.0 * 0.0254),
        )
        self.assertEqual(
            "black",
            color_rule.get_rule({}, "RingHole", "Via Annular Ring", 5.86 * 0.0254),
        )

    def test_profile_delta_for_trace_width_boundary(self):
        board = FakeBoard(tracks=(FakeTrack("t1", (0, 0), (1000000, 0), 135000),))
        colors = {}
        rules = {}
        for profile in ("economy", "standard", "precision"):
            result = self.analyze(board, profile, include_passed_details=True)
            row = first_row(result, "Smallest Trace Width")
            colors[profile] = row["color"]
            rules[profile] = row["rule"]

        self.assertEqual({"economy": "red", "standard": "gold", "precision": "black"}, colors)
        self.assertEqual(3, len(set(rules.values())))

    def test_three_mil_trace_preserves_exact_kicad_width(self):
        board = FakeBoard(tracks=(FakeTrack("t1", (0, 0), (1000000, 0), 76200),))

        result = self.analyze(board, "standard", include_passed_details=True)
        row = first_row(result, "Smallest Trace Width")

        self.assertEqual("0.0762", row["value"])
        self.assertEqual(0.0762, result.kicad_result["Smallest Trace Width"]["display"])

    def test_offline_analysis_profile_records_category_timings(self):
        board = FakeBoard(tracks=(FakeTrack("t1", (0, 0), (1000000, 0), 100000),))
        result = self.analyze(board, "standard")

        self.assertIn("total_ms", result.profile)
        self.assertIn("index_build_ms", result.profile)
        self.assertIn("categories", result.profile)
        self.assertEqual(set(result.kicad_result), set(result.profile["categories"]))
        trace_profile = result.profile["categories"]["Smallest Trace Width"]
        self.assertIn("elapsed_ms", trace_profile)
        self.assertEqual(1, trace_profile["rows"])
        self.assertEqual(result.kicad_result["Smallest Trace Width"]["color"], trace_profile["color"])

    def test_pad_size_uses_shorter_side_without_subtracting_drill(self):
        pad = FakePad("p1", (0, 0), (200000, 400000), (150000, 150000), attribute=1)
        result = self.analyze(
            FakeBoard(pads=(pad,)), "standard", include_passed_details=True
        )
        row = first_row(result, "Pad size")

        self.assertEqual("0.2", row["value"])
        self.assertEqual("black", row["color"])
        self.assertEqual("Long Pads", row["item"])

    def test_pad_size_includes_pth_outer_pad_shorter_side(self):
        pad = FakePad(
            "p1", (0, 0), (250000, 600000), (200000, 200000), attribute=0
        )
        result = self.analyze(
            FakeBoard(pads=(pad,)), "standard", include_passed_details=True
        )
        row = first_row(result, "Pad size")

        self.assertEqual("0.25", row["value"])
        self.assertEqual("Long Pads", row["item"])

    def test_pad_size_show_all_respects_each_shape_rule_reporting_limit(self):
        pads = (
            FakePad("long-in", (0, 0), (254000, 600000)),
            FakePad("long-out", (1000000, 0), (255000, 600000)),
            FakePad("short-in", (2000000, 0), (508000, 508000)),
            FakePad("short-out", (3000000, 0), (509000, 509000)),
        )

        result = self.analyze(
            FakeBoard(pads=pads), "standard", include_passed_details=True
        )

        self.assertEqual(
            ["long-in", "short-in"],
            [row["id"] for row in rows_for(result, "Pad size")],
        )

    def test_trace_spacing_profile_delta(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 235000), (1000000, 235000), 100000, net="B")
        board = FakeBoard(tracks=(left, right))

        self.assertEqual("red", first_row(self.analyze(board, "economy"), "Smallest Trace Spacing")["color"])
        self.assertEqual("gold", first_row(self.analyze(board, "standard"), "Smallest Trace Spacing")["color"])
        self.assertEqual("black", category_color(self.analyze(board, "precision"), "Smallest Trace Spacing"))

    def test_trace_spacing_ignores_same_named_net_for_every_copper_pair_type(self):
        boards = {
            "track-to-track": FakeBoard(
                tracks=(
                    FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A"),
                    FakeTrack("t2", (0, 100000), (1000000, 100000), 100000, net="A"),
                )
            ),
            "track-to-pad": FakeBoard(
                tracks=(FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A"),),
                pads=(FakePad("p1", (500000, 0), (400000, 400000), net="A"),),
            ),
            "pad-to-pad": FakeBoard(
                pads=(
                    FakePad("p1", (0, 0), (400000, 400000), net="A"),
                    FakePad("p2", (200000, 0), (400000, 400000), net="A"),
                )
            ),
        }

        for pair_type, board in boards.items():
            with self.subTest(pair_type=pair_type):
                result = self.analyze(board, "standard")
                self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))
                self.assertEqual("black", category_color(result, "Smallest Trace Spacing"))

    def test_trace_spacing_excludes_pad_objects_without_copper_layers(self):
        copper = FakePad("copper", (0, 0), (1000000, 1000000), net="A")
        paste = FakePad("paste", (0, 0), (1000000, 1000000), net="")
        board = FakeBoard(pads=(copper, paste))

        class LayerAwareBackend(FakeBackend):
            def pad_copper_layer_ids(self, pad):
                return () if self.item_id(pad) == "paste" else (0,)

        backend = LayerAwareBackend(board)
        checks = LocalChecks(
            {},
            board,
            backend=backend,
            rules=rules_for_profile("standard"),
        )
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=backend,
            rules=rules_for_profile("standard"),
        ).analyze()

        self.assertEqual(("copper",), tuple(item.item_id for item in checks.index.copper_pads))
        self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))

    def test_trace_spacing_ignores_only_touching_declared_net_tie_members(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return ((("p1", "A"), ("p2", "B")),)

        board = FakeBoard(
            pads=(
                FakePad("p1", (0, 0), (400000, 400000), net="A"),
                FakePad("p2", (200000, 0), (400000, 400000), net="B"),
            )
        )
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))
        self.assertEqual([], rows_for(result, "SMD Spacing"))

    def test_trace_spacing_ignores_track_contact_at_declared_net_tie_pad(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return ((("anchor-a", "A"), ("p1", "B")),)

        board = FakeBoard(
            tracks=(
                FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A"),
            ),
            pads=(FakePad("p1", (500000, 0), (400000, 400000), net="B"),),
        )
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))

    def test_smd_spacing_ignores_positive_gap_between_net_tie_member_pads(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return ((("p1", "A"), ("p2", "B")),)

        board = FakeBoard(
            pads=(
                FakePad("p1", (0, 0), (400000, 400000), net="A"),
                FakePad("p2", (450000, 0), (400000, 400000), net="B"),
            )
        )
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))
        self.assertEqual([], rows_for(result, "SMD Spacing"))

    def test_smd_spacing_ignores_pad_locally_attached_to_net_tie_member(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return ((("nt-a", "A"), ("nt-b", "B")),)

            def item_local_clearance_nm(self, item):
                return 10000 if self.item_id(item) == "nt-a" else None

        board = FakeBoard(
            pads=(
                FakePad("nt-a", (0, 0), (400000, 400000), net="A"),
                FakePad("nt-b", (200000, 0), (400000, 400000), net="B"),
                FakePad("ordinary-a", (400000, 0), (400000, 400000), net="A"),
            )
        )
        board.item_clearances = {
            ("nt-b", "ordinary-a"): 30000,
            ("ordinary-a", "nt-a"): 5000,
        }
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        self.assertEqual([], rows_for(result, "SMD Spacing"))

    def test_smd_spacing_keeps_pad_outside_net_tie_local_clearance(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return ((("nt-a", "A"), ("nt-b", "B")),)

            def item_local_clearance_nm(self, item):
                return 10000 if self.item_id(item) == "nt-a" else None

        board = FakeBoard(
            pads=(
                FakePad("nt-a", (0, 0), (400000, 400000), net="A"),
                FakePad("nt-b", (200000, 0), (400000, 400000), net="B"),
                FakePad("ordinary-a", (400000, 0), (400000, 400000), net="A"),
            )
        )
        board.item_clearances = {
            ("nt-b", "ordinary-a"): 30000,
            ("ordinary-a", "nt-a"): 11000,
        }
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        row = first_row(result, "SMD Spacing")
        self.assertEqual("0.03", row["value"])
        self.assertEqual(
            {"nt-b", "ordinary-a"},
            {row["id"], row["related_id"]},
        )

    def test_smd_spacing_keeps_cross_layer_net_tie_attachment(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return ((("nt-a", "A"), ("nt-b", "B")),)

            def item_local_clearance_nm(self, item):
                return 10000 if self.item_id(item) == "nt-a" else None

        board = FakeBoard(
            pads=(
                FakePad(
                    "nt-a",
                    (0, 0),
                    (400000, 400000),
                    layer="B.Cu",
                    net="A",
                ),
                FakePad("nt-b", (200000, 0), (400000, 400000), net="B"),
                FakePad("ordinary-a", (400000, 0), (400000, 400000), net="A"),
            )
        )
        board.item_clearances = {
            ("nt-b", "ordinary-a"): 30000,
            ("ordinary-a", "nt-a"): 5000,
        }
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        row = first_row(result, "SMD Spacing")
        self.assertEqual("0.03", row["value"])
        self.assertEqual(
            {"nt-b", "ordinary-a"},
            {row["id"], row["related_id"]},
        )

    def test_trace_spacing_keeps_same_net_pair_tied_elsewhere_on_board(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return ((("nt-a", "A"), ("nt-b", "B")),)

        board = FakeBoard(
            pads=(
                FakePad("p1", (0, 0), (400000, 400000), net="A"),
                FakePad("p2", (200000, 0), (400000, 400000), net="B"),
            )
        )
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        row = first_row(result, "SMD Spacing")
        self.assertEqual("SMD Pad Spacing", row["item"])
        self.assertEqual("0.0", row["value"])

    def test_smd_spacing_keeps_pads_from_different_declared_net_tie_groups(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return (
                    (("p1", "A"), ("missing-c", "C")),
                    (("p2", "B"), ("missing-d", "D")),
                )

        board = FakeBoard(
            pads=(
                FakePad("p1", (0, 0), (400000, 400000), net="A"),
                FakePad("p2", (200000, 0), (400000, 400000), net="B"),
            )
        )
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        row = first_row(result, "SMD Spacing")
        self.assertEqual("0.0", row["value"])
        self.assertEqual({"p1", "p2"}, {row["id"], row["related_id"]})

    def test_trace_spacing_keeps_positive_track_gap_at_net_tie_pad(self):
        class NetTieBackend(FakeBackend):
            def net_tie_pad_groups(self):
                return ((("anchor-a", "A"), ("p1", "B")),)

        board = FakeBoard(
            tracks=(
                FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A"),
            ),
            pads=(FakePad("p1", (500000, 300000), (400000, 400000), net="B"),),
        )
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        row = first_row(result, "Smallest Trace Spacing")
        self.assertEqual("Trace-to-Pad Spacing", row["item"])
        self.assertEqual("0.05", row["value"])

    def test_hole_diameter_and_drill_spacing_results_have_location_fields(self):
        via1 = FakeVia("v1", (0, 0), 500000, 200000, net="A")
        via2 = FakeVia("v2", (450000, 0), 500000, 200000, net="B")
        result = self.analyze(FakeBoard(tracks=(via1, via2)), "standard")

        hole = first_row(result, "Hole Size")
        spacing = first_row(result, "Drill Hole Spacing")
        self.assertEqual("Smallest Drill Size", hole["item"])
        self.assertEqual("FakeVia", hole["item_type"])
        self.assertIn("bbox_nm", hole)
        self.assertEqual("holesize:smallestdrillsize", hole["rule_key"])
        self.assertEqual("kicad", hole["source"])
        self.assertEqual(1.0, hole["confidence"])
        self.assertEqual("exact_kicad", hole["geometry_basis"])
        self.assertEqual("Different Net Via Spacing", spacing["item"])
        self.assertEqual("v2", spacing["related_id"])

    def test_via_and_component_pth_minimum_diameters_do_not_cross_classify(self):
        via = FakeVia("via", (0, 0), 500000, 200000)
        pth = FakePad(
            "pth", (1000000, 0), (800000, 800000), (300000, 300000), attribute=0
        )
        npth = FakePad(
            "npth", (2000000, 0), (800000, 800000), (100000, 100000), attribute=3
        )

        result = self.analyze(
            FakeBoard(tracks=(via,), pads=(pth, npth)),
            "standard",
            include_passed_details=True,
        )
        rows = rows_for(result, "Hole Size")
        by_minimum_item = {
            item: [row["id"] for row in rows if row["item"] == item]
            for item in ("Smallest Drill Size", "Smallest PTH")
        }

        self.assertEqual(["via"], by_minimum_item["Smallest Drill Size"])
        self.assertEqual(["pth"], by_minimum_item["Smallest PTH"])

    def test_blind_buried_via_diameter_items(self):
        blind = FakeVia("v1", (0, 0), 500000, 120000, via_type="micro", layer_pair=("F.Cu", "In1.Cu"))
        buried_small = FakeVia("v2", (1000000, 0), 500000, 100000, via_type="buried", layer_pair=("In1.Cu", "In2.Cu"))
        buried_large = FakeVia("v3", (2000000, 0), 700000, 600000, via_type="buried", layer_pair=("In1.Cu", "In2.Cu"))
        blind_mec = FakeVia("v4", (3000000, 0), 500000, 100000, via_type="blind", layer_pair=("F.Cu", "In1.Cu"))
        buried_laser = FakeVia("v5", (4000000, 0), 500000, 80000, via_type="micro", layer_pair=("In1.Cu", "In2.Cu"))
        result = self.analyze(
            FakeBoard(tracks=(blind, buried_small, buried_large, blind_mec, buried_laser)),
            "standard",
            include_passed_details=True,
        )
        rows = rows_for(result, "Hole Size")
        items = {(row["id"], row["item"]) for row in rows}

        self.assertIn(("v1", "Smallest Blind_Laser"), items)
        self.assertIn(("v2", "Smallest Buried_mec"), items)
        self.assertIn(("v3", "Largest Blind/Buried Via"), items)
        self.assertIn(("v4", "Smallest Blind_mec"), items)
        self.assertIn(("v5", "Smallest Buried_Laser"), items)

    def test_blind_buried_via_spacing_item(self):
        left = FakeVia("v1", (0, 0), 500000, 200000, via_type="blind", layer_pair=("F.Cu", "In1.Cu"))
        right = FakeVia("v2", (450000, 0), 500000, 200000, via_type="buried", layer_pair=("In1.Cu", "B.Cu"))
        result = self.analyze(FakeBoard(tracks=(left, right)), "standard")

        row = first_row(result, "Drill Hole Spacing")
        self.assertEqual("Blind/Buried Via Spacing", row["item"])

    def test_same_net_vias_use_same_net_spacing_rule(self):
        left = FakeVia("v1", (0, 0), 500000, 200000, net="POWER")
        right = FakeVia("v2", (450000, 0), 500000, 200000, net="POWER")
        result = self.analyze(FakeBoard(tracks=(left, right)), "standard")

        row = first_row(result, "Drill Hole Spacing")
        self.assertEqual("Same Net Via Spacing", row["item"])
        # 0.45 mm center distance - two 0.10 mm drill radii = 0.25 mm.
        self.assertEqual("0.25", row["value"])

    def test_same_net_pth_pair_does_not_use_different_net_rule(self):
        left = FakePad(
            "p1",
            (0, 0),
            (1000000, 1000000),
            drill=(200000, 200000),
            attribute=0,
            net="POWER",
        )
        right = FakePad(
            "p2",
            (450000, 0),
            (1000000, 1000000),
            drill=(200000, 200000),
            attribute=0,
            net="POWER",
        )
        result = self.analyze(FakeBoard(pads=(left, right)), "standard")

        self.assertEqual([], rows_for(result, "Drill Hole Spacing"))

    def test_drill_spacing_uses_drill_bbox_for_large_pads(self):
        left = FakePad("p1", (0, 0), (10000000, 10000000), drill=(200000, 200000), attribute=0, net="A")
        right = FakePad("p2", (450000, 0), (10000000, 10000000), drill=(200000, 200000), attribute=0, net="B")
        result = self.analyze(FakeBoard(pads=(left, right)), "standard")

        row = first_row(result, "Drill Hole Spacing")
        self.assertEqual("Different Net PTH Spacing", row["item"])
        self.assertEqual("0.25", row["value"])

    def test_drill_spacing_uses_radial_distance_for_diagonal_round_holes(self):
        left = FakeVia("v1", (0, 0), 500000, 400000, net="A")
        right = FakeVia("v2", (400000, 400000), 500000, 400000, net="B")

        result = self.analyze(
            FakeBoard(tracks=(left, right)),
            "standard",
            include_passed_details=True,
        )

        row = first_row(result, "Drill Hole Spacing")
        self.assertEqual("0.165685", row["value"])

    def test_drill_spacing_uses_slot_bbox_edges(self):
        left = FakePad("p1", (0, 0), (3000000, 1000000), drill=(1600000, 200000), attribute=0, drill_shape=1, net="A")
        right = FakePad("p2", (1250000, 0), (1000000, 1000000), drill=(200000, 200000), attribute=0, net="B")
        result = self.analyze(FakeBoard(pads=(left, right)), "standard")

        row = first_row(result, "Drill Hole Spacing")
        self.assertEqual("Different Net PTH Spacing", row["item"])
        self.assertEqual("0.35", row["value"])

    def test_drill_spacing_prunes_far_large_pad_bodies(self):
        pads = tuple(
            FakePad(
                "p%s" % index,
                (index * 10000000, 0),
                (9000000, 9000000),
                drill=(200000, 200000),
                attribute=0,
                net="N%s" % index,
            )
            for index in range(30)
        )
        original_is_reportable = LocalChecks._is_reportable
        calls = []

        def counted_is_reportable(checks, analysis_result, category, item, value):
            if category == "Drill Hole Spacing":
                calls.append(value)
            return original_is_reportable(checks, analysis_result, category, item, value)

        with mock.patch.object(LocalChecks, "_is_reportable", counted_is_reportable):
            result = self.analyze(FakeBoard(pads=pads), "standard")

        total_pairs = len(pads) * (len(pads) - 1) // 2
        self.assertEqual("black", category_color(result, "Drill Hole Spacing"))
        self.assertLess(len(calls), total_pairs // 10)

    def test_smd_and_bga_pad_spacing_use_specific_rule_items(self):
        left = FakePad("p1", (0, 0), (1000000, 1000000), attribute=1, net="A")
        right = FakePad("p2", (1050000, 0), (1000000, 1000000), attribute=1, net="B")
        smd = self.analyze(FakeBoard(pads=(left, right)), "standard")
        bga = self.analyze(FakeBoard(pads=(left, right), footprint_name="BGA-100"), "standard")

        smd_row = first_row(smd, "SMD Spacing")
        self.assertEqual("SMD Pad Spacing", smd_row["item"])
        self.assertEqual("smdspacing:smdpadspacing", smd_row["rule_key"])
        self.assertIn("SMD Spacing", {issue.category for issue in smd.issues})
        self.assertEqual([], rows_for(smd, "Smallest Trace Spacing"))
        self.assertEqual("BGA Pads", first_row(bga, "Smallest Trace Spacing")["item"])
        self.assertEqual([], rows_for(bga, "SMD Spacing"))

    def test_smd_spacing_uses_six_eight_ten_mil_rule_contract(self):
        observations = (
            (140000, "red"),
            (180000, "gold"),
            (220000, "black"),
        )
        for gap, expected_color in observations:
            with self.subTest(gap=gap):
                left = FakePad(
                    "p1",
                    (0, 0),
                    (1000000, 1000000),
                    attribute=1,
                    net="A",
                )
                right = FakePad(
                    "p2",
                    (1000000 + gap, 0),
                    (1000000, 1000000),
                    attribute=1,
                    net="B",
                )
                result = self.analyze(
                    FakeBoard(pads=(left, right)),
                    "standard",
                )

                self.assertEqual(
                    expected_color,
                    category_color(result, "SMD Spacing"),
                )
                if expected_color != "black":
                    self.assertEqual(
                        "0.152400,0.203200,0.254000",
                        first_row(result, "SMD Spacing")["rule"],
                    )

    def test_rectangular_pad_spacing_uses_bbox_edges(self):
        left = FakePad("p1", (0, 0), (2000000, 400000), attribute=1, shape=1, net="A")
        right = FakePad("p2", (2140000, 0), (2000000, 400000), attribute=1, shape=1, net="B")
        result = self.analyze(FakeBoard(pads=(left, right)), "standard", include_passed_details=True)

        row = first_row(result, "SMD Spacing")
        self.assertEqual("0.14", row["value"])
        self.assertEqual("SMD Pad Spacing", row["item"])

    def test_overlapping_different_net_pads_report_zero_clearance(self):
        left = FakePad("p1", (0, 0), (1000000, 1000000), attribute=1, net="A")
        right = FakePad("p2", (500000, 0), (1000000, 1000000), attribute=1, net="B")

        result = self.analyze(FakeBoard(pads=(left, right)), "standard")
        row = first_row(result, "SMD Spacing")

        self.assertEqual("SMD Pad Spacing", row["item"])
        self.assertEqual("0.0", row["value"])
        self.assertEqual("red", row["color"])

    def test_pad_spacing_ignores_npth_pad_body(self):
        smd = FakePad("smd", (0, 0), (1000000, 1000000), attribute=1, net="A")
        npth = FakePad("npth", (1050000, 0), (1000000, 1000000), drill=(300000, 300000), attribute=3, net="B")
        result = self.analyze(FakeBoard(pads=(smd, npth)), "standard")

        self.assertEqual("black", category_color(result, "Smallest Trace Spacing"))

    def test_pad_spacing_deduplicates_pth_pair_across_copper_layers(self):
        track = FakeTrack("t1", (5000000, 0), (6000000, 0), 100000, layer="B.Cu")
        left = FakePad("p1", (0, 0), (1000000, 1000000), layer="F.Cu", attribute=0, net="A")
        right = FakePad("p2", (1050000, 0), (1000000, 1000000), layer="F.Cu", attribute=0, net="B")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(left, right)), "standard")

        rows = rows_for(result, "Smallest Trace Spacing")
        self.assertEqual(1, len(rows))
        self.assertEqual("p2", rows[0]["related_id"])

    def test_trace_to_rectangular_pad_spacing_uses_pad_edge(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        pad = FakePad("p1", (1690000, 0), (1000000, 400000), attribute=1, shape=1, net="B")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(pad,)), "standard", include_passed_details=True)

        row = first_row(result, "Smallest Trace Spacing")
        self.assertEqual("0.14", row["value"])
        self.assertEqual("Trace-to-Pad Spacing", row["item"])

    def test_smallest_trace_spacing_checks_pad_to_pad(self):
        left = FakePad("p1", (0, 0), (400000, 400000), attribute=1, net="A")
        right = FakePad("p2", (540000, 0), (400000, 400000), attribute=1, net="B")

        result = self.analyze(
            FakeBoard(pads=(left, right)),
            "standard",
            include_passed_details=True,
        )
        rows = rows_for(result, "SMD Spacing")

        self.assertEqual(1, len(rows))
        self.assertEqual("SMD Pad Spacing", rows[0]["item"])
        self.assertEqual("0.14", rows[0]["value"])
        self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))

    def test_rule_key_uses_catalog_item_when_display_item_is_translated(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        pad = FakePad("p1", (1690000, 0), (1000000, 400000), attribute=1, shape=1, net="B")
        language = {"Trace-to-Pad Spacing": "走线到焊盘间距"}
        result = self.analyze(
            FakeBoard(tracks=(track,), pads=(pad,)),
            "standard",
            include_passed_details=True,
            language=language,
        )

        row = first_row(result, "Smallest Trace Spacing")
        self.assertEqual("走线到焊盘间距", row["item"])
        self.assertEqual("smallesttracespacing:tracetopadspacing", row["rule_key"])

    def test_trace_spacing_checks_pth_pad_copper_on_other_copper_layers(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, layer="B.Cu", net="A")
        pad = FakePad("p1", (1690000, 0), (1000000, 400000), layer="F.Cu", attribute=0, shape=1, net="B")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(pad,)), "standard", include_passed_details=True)

        row = first_row(result, "Smallest Trace Spacing")
        self.assertEqual("0.14", row["value"])
        self.assertEqual("Trace-to-Pad Spacing", row["item"])
        self.assertEqual("p1", row["related_id"])
        self.assertEqual("B.Cu", row["related_layer"])

    def test_cross_layer_copper_pad_index_is_sorted_for_nearby_queries(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, layer="B.Cu", net="A")
        far_pth = FakePad("far", (10000000, 0), (1000000, 400000), layer="F.Cu", attribute=0, shape=1, net="B")
        near_pth = FakePad("near", (1690000, 0), (1000000, 400000), layer="F.Cu", attribute=0, shape=1, net="C")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(far_pth, near_pth)), "standard", include_passed_details=True)

        rows = [
            row
            for row in rows_for(result, "Smallest Trace Spacing")
            if row.get("related_id") == "near"
        ]
        self.assertEqual(1, len(rows))
        self.assertEqual("Trace-to-Pad Spacing", rows[0]["item"])
        self.assertEqual("B.Cu", rows[0]["related_layer"])

    def test_trace_spacing_ignores_npth_pad_body(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        npth = FakePad("npth", (1050000, 0), (1000000, 1000000), drill=(300000, 300000), attribute=3, net="B")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(npth,)), "standard")

        self.assertEqual("black", category_color(result, "Smallest Trace Spacing"))

    def test_trace_spacing_ignores_nearby_zone_copper(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        zone = FakeZone("z1", (500000, 240000), (1000000, 100000), layer="F.Cu", net="B")
        result = self.analyze(FakeBoard(tracks=(track,), zones=(zone,)), "standard")

        self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))

    def test_trace_spacing_excludes_pad_to_zone_copper(self):
        pad = FakePad("p1", (0, 0), (400000, 400000), attribute=1, shape=1, net="A")
        zone = FakeZone("z1", (440000, 0), (200000, 400000), layer="F.Cu", net="B")
        result = self.analyze(FakeBoard(pads=(pad,), zones=(zone,)), "standard")

        self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))

    def test_trace_spacing_prefers_native_pad_to_zone_clearance(self):
        pad = FakePad("p1", (0, 0), (400000, 400000), attribute=1, shape=1, net="A")
        zone = FakeZone("z1", (440000, 0), (200000, 400000), layer="F.Cu", net="B")
        zone.polygons = (
            (
                (
                    (340000, -200000),
                    (540000, -200000),
                    (540000, 200000),
                    (340000, 200000),
                ),
                (),
            ),
        )
        board = FakeBoard(pads=(pad,), zones=(zone,))
        board.item_clearances = {("p1", "z1"): 2000000}

        result = self.analyze(board, "standard")

        self.assertEqual("black", category_color(result, "Smallest Trace Spacing"))

    def test_equal_axis_oval_pad_is_treated_as_effectively_round(self):
        pad = FakePad("p1", (0, 0), (1600000, 1600000), attribute=0, shape=2)
        checks = LocalChecks({}, FakeBoard(pads=(pad,)), backend=FakeBackend(FakeBoard(pads=(pad,))))

        self.assertTrue(checks._is_round_pad(checks.index.pads[0]))

    def test_holes_on_smd_pads_checks_bottom_side_for_through_via(self):
        via = FakeVia(
            "v1",
            (0, 0),
            500000,
            200000,
            layer="F.Cu",
            net="A",
            layer_pair=("F.Cu", "B.Cu"),
        )
        pad = FakePad(
            "p1",
            (0, 0),
            (400000, 400000),
            layer="B.Cu",
            attribute=1,
            net="A",
        )

        result = self.analyze(FakeBoard(tracks=(via,), pads=(pad,)), "standard")

        row = first_row(result, "Holes on SMD Pads")
        self.assertEqual("v1", row["id"])
        self.assertEqual("p1", row["related_id"])

    def test_trace_spacing_ignores_npth_pad_to_zone_body(self):
        npth = FakePad("npth", (0, 0), (400000, 400000), drill=(200000, 200000), attribute=3, net="A")
        zone = FakeZone("z1", (440000, 0), (200000, 400000), layer="F.Cu", net="B")
        result = self.analyze(FakeBoard(pads=(npth,), zones=(zone,)), "standard")

        self.assertEqual("black", category_color(result, "Smallest Trace Spacing"))

    def test_trace_spacing_ignores_zone_to_zone_copper(self):
        left = FakeZone("z1", (0, 0), (400000, 400000), layer="F.Cu", net="A")
        right = FakeZone("z2", (540000, 0), (400000, 400000), layer="F.Cu", net="B")
        result = self.analyze(FakeBoard(zones=(left, right)), "standard")

        self.assertEqual([], rows_for(result, "Smallest Trace Spacing"))

    def test_pth_aspect_ratio_uses_board_thickness(self):
        pad = FakePad("p1", (0, 0), (1000000, 1000000), (200000, 200000), attribute=0)
        result = self.analyze(FakeBoard(pads=(pad,), thickness=3000000), "standard")
        rows = rows_for(result, "Hole Size")

        aspect = next(row for row in rows if row["item"] == "Aspect Ratio")
        self.assertEqual("15.0", aspect["value"])
        self.assertEqual("red", aspect["color"])

    def test_pth_aspect_ratio_lists_distinct_normal_ratios_inside_rule_window(self):
        drills = (250000, 250000, 300000, 500000, 600000, 700000, 1000000, 1500000, 2700000, 3200000)
        pads = tuple(
            FakePad(
                "p{0}".format(index),
                (index * 1000000, 0),
                (4000000, 4000000),
                (drill, drill),
                attribute=0,
            )
            for index, drill in enumerate(drills)
        )

        result = self.analyze(FakeBoard(pads=pads, thickness=1600000), "standard")
        rows = [
            row
            for row in rows_for(result, "Hole Size")
            if row["item"] == "Aspect Ratio"
        ]

        self.assertEqual(9, len(rows))
        self.assertEqual(
            [6.4, 5.333333, 3.2, 2.666667, 2.285714, 1.6, 1.066667, 0.592593, 0.5],
            [float(row["value"]) for row in rows],
        )
        self.assertTrue(all(row["color"] == "black" for row in rows))
        self.assertEqual(1.6, rows[0]["board_thickness_mm"])
        self.assertEqual(0.25, rows[0]["diameter"])

    def test_npth_uses_generic_hole_size_and_board_thickness_ratio(self):
        pad = FakePad(
            "npth",
            (0, 0),
            (1000000, 1000000),
            (200000, 200000),
            attribute=3,
        )
        result = self.analyze(
            FakeBoard(pads=(pad,), thickness=3000000),
            "standard",
            include_passed_details=True,
        )
        items = [row["item"] for row in rows_for(result, "Hole Size")]

        self.assertNotIn("Smallest Drill Size", items)
        self.assertNotIn("Smallest PTH", items)
        self.assertNotIn("Largest PTH Size", items)
        self.assertIn("Aspect Ratio", items)

    def test_large_pth_uses_largest_pth_rule(self):
        pad = FakePad(
            "pth",
            (0, 0),
            (8000000, 8000000),
            (7000000, 7000000),
            attribute=0,
        )
        result = self.analyze(FakeBoard(pads=(pad,)), "standard")
        rows = rows_for(result, "Hole Size")

        largest = next(row for row in rows if row["item"] == "Largest PTH Size")
        self.assertEqual("7.0", largest["value"])
        self.assertEqual("gold", largest["color"])

    def test_pth_aspect_ratio_reuses_cached_board_thickness(self):
        pads = tuple(
            FakePad("p%s" % index, (index * 1000000, 0), (1000000, 1000000), (200000, 200000), attribute=0)
            for index in range(3)
        )
        board = FakeBoard(pads=pads, thickness=3000000)

        class CountingBackend(FakeBackend):
            def __init__(self, board):
                super().__init__(board)
                self.board_thickness_calls = 0

            def board_thickness_mm(self):
                self.board_thickness_calls += 1
                return super().board_thickness_mm()

        backend = CountingBackend(board)
        checks = LocalChecks(
            {},
            board,
            backend=backend,
            rules=rules_for_profile("standard"),
            include_passed_details=True,
        )
        result = checks.get_hole_diameter({})
        rows = [row for check in result["check"] for row in check["result"]]

        self.assertEqual(1, len([row for row in rows if row["item"] == "Aspect Ratio"]))
        self.assertEqual(1, backend.board_thickness_calls)

    def test_via_hole_diameter_does_not_read_board_thickness(self):
        via = FakeVia("via", (0, 0), 500000, 200000)
        board = FakeBoard(tracks=(via,), thickness=3000000)

        class CountingBackend(FakeBackend):
            def __init__(self, board):
                super().__init__(board)
                self.board_thickness_calls = 0

            def board_thickness_mm(self):
                self.board_thickness_calls += 1
                return super().board_thickness_mm()

        backend = CountingBackend(board)
        checks = LocalChecks(
            {},
            board,
            backend=backend,
            rules=rules_for_profile("standard"),
            include_passed_details=True,
        )
        result = checks.get_hole_diameter({})
        rows = [row for check in result["check"] for row in check["result"]]

        self.assertNotIn("Aspect Ratio", [row["item"] for row in rows])
        self.assertEqual(0, backend.board_thickness_calls)

    def test_slot_size_items_exclude_cancelled_square_hole_size(self):
        slot = FakePad("p1", (0, 0), (17000000, 1000000), (300000, 16000000), attribute=0, drill_shape=1)
        result = self.analyze(FakeBoard(pads=(slot,)), "standard")
        items = {row["item"]: row for row in rows_for(result, "Hole Size")}

        self.assertEqual("0.3", items["Smallest Slot Width"]["value"])
        self.assertEqual("0.3", items["Largest Slot Width"]["value"])
        self.assertEqual("16.0", items["Largest Slot Length"]["value"])
        self.assertEqual("53.333333", items["Slot Aspect Ratio"]["value"])
        self.assertNotIn("Square Hole Size", items)
        self.assertNotIn(
            "Square/Rectangular Drills",
            [row["item"] for row in rows_for(result, "Special Drill Holes")],
        )

    def test_only_explicit_sharp_corner_shape_is_a_rectangular_hole(self):
        rounded_slot = FakePad(
            "rounded-slot",
            (0, 0),
            (3000000, 1000000),
            (1600000, 200000),
            attribute=0,
            drill_shape="OBLONG",
        )
        explicit_rectangle = FakePad(
            "rectangle",
            (5000000, 0),
            (3000000, 1000000),
            (1600000, 200000),
            attribute=0,
            drill_shape="RECTANGLE",
        )

        result = self.analyze(
            FakeBoard(pads=(rounded_slot, explicit_rectangle)),
            "standard",
        )
        rows = [
            row
            for row in rows_for(result, "Special Drill Holes")
            if row["item"] == "Square/Rectangular Drills"
        ]

        self.assertEqual(1, len(rows))
        self.assertEqual("rectangle", rows[0]["id"])

    def test_normal_slot_width_keeps_all_four_mounting_holes(self):
        pads = tuple(
            FakePad(
                item_id,
                (index * 3000000, 0),
                (900000, 2000000),
                (600000, 1700000),
                attribute=0,
                drill_shape=1,
            )
            for index, item_id in enumerate(("J1-MP1", "J1-MP2", "J2-MP1", "J2-MP2"))
        )

        result = self.analyze(FakeBoard(pads=pads), "standard")
        rows = [
            row
            for row in rows_for(result, "Hole Size")
            if row["item"] == "Largest Slot Width"
        ]

        self.assertEqual(4, len(rows))
        self.assertEqual(
            ["J1-MP1", "J1-MP2", "J2-MP1", "J2-MP2"],
            [row["id"] for row in rows],
        )
        self.assertTrue(all(row["value"] == "0.6" for row in rows))

    def test_largest_slot_width_summary_uses_the_maximum_short_axis(self):
        slots = (
            FakePad(
                "narrow", (0, 0), (2000000, 1000000),
                (600000, 1700000), attribute=0, drill_shape=1,
            ),
            FakePad(
                "wide", (5000000, 0), (9000000, 8000000),
                (7500000, 8500000), attribute=0, drill_shape=1,
            ),
        )

        result = self.analyze(
            FakeBoard(pads=slots),
            "standard",
            include_passed_details=True,
        ).kicad_result["Hole Size"]
        summary = result["item_summaries"]["holesize:largestslotwidth"]

        self.assertEqual(7.5, summary["display"])
        self.assertEqual("gold", summary["color"])
        self.assertEqual(2, summary["checked_count"])

    def test_slot_aspect_ratio_is_a_minimum_ratio_check(self):
        pads = tuple(
            FakePad(
                "ratio-{0}".format(ratio),
                (index * 5000000, 0),
                (4000000, 4000000),
                (1000000, int(ratio * 1000000)),
                attribute=0,
                drill_shape=1,
            )
            for index, ratio in enumerate((1.4, 1.75, 2.0, 3.0))
        )

        result = self.analyze(
            FakeBoard(pads=pads),
            "standard",
            include_passed_details=True,
        ).kicad_result["Hole Size"]
        rows = {
            row["id"]: row
            for group in result["check"]
            for row in group["result"]
            if row["item"] == "Slot Aspect Ratio"
        }

        self.assertEqual("red", rows["ratio-1.4"]["color"])
        self.assertEqual("gold", rows["ratio-1.75"]["color"])
        self.assertEqual("black", rows["ratio-2.0"]["color"])
        self.assertEqual("black", rows["ratio-3.0"]["color"])
        self.assertEqual(
            1.4,
            result["item_summaries"]["holesize:slotaspectratio"]["display"],
        )

    def test_hole_size_calculations_are_identical_in_chinese_and_english(self):
        pads = (
            FakePad(
                "pth", (0, 0), (1000000, 1000000),
                (300000, 300000), attribute=0,
            ),
            FakePad(
                "slot", (2000000, 0), (1500000, 800000),
                (1200000, 300000), attribute=0, drill_shape=1,
            ),
            FakePad(
                "npth", (4000000, 0), (1000000, 1000000),
                (400000, 400000), attribute=3,
            ),
        )
        board = FakeBoard(
            tracks=(FakeVia("via", (6000000, 0), 600000, 250000),),
            pads=pads,
            thickness=1600000,
        )

        english = self.analyze(
            board, "standard", include_passed_details=True,
            language=Language_english,
        )
        chinese = self.analyze(
            board, "standard", include_passed_details=True,
            language=Language_chinese,
        )

        def stable_rows(result):
            return sorted(
                (row["rule_key"], row["value"], row["rule"], row["color"])
                for row in rows_for(result, "Hole Size")
            )

        self.assertEqual(stable_rows(english), stable_rows(chinese))
        self.assertEqual(
            english.kicad_result["Hole Size"]["display"],
            chinese.kicad_result["Hole Size"]["display"],
        )
        self.assertEqual(
            english.kicad_result["Hole Size"]["color"],
            chinese.kicad_result["Hole Size"]["color"],
        )

    def test_round_drill_shape_can_use_nonzero_kicad_constant(self):
        pad = FakePad(
            "p1",
            (0, 0),
            (1000000, 1000000),
            (200000, 200000),
            attribute=0,
            drill_shape=1,
            round_drill=True,
        )
        result = self.analyze(FakeBoard(pads=(pad,)), "standard", include_passed_details=True)
        items = [row["item"] for row in rows_for(result, "Hole Size")]

        self.assertIn("Smallest PTH", items)
        self.assertNotIn("Square Hole Size", items)

    def test_castellated_hole_intersects_board_edge(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        pad = FakePad("p1", (100000, 1000000), (1000000, 1000000), (300000, 300000), attribute=0)
        result = self.analyze(FakeBoard(pads=(pad,), drawings=outline), "standard")
        rows = rows_for(result, "Special Drill Holes")

        self.assertIn("Castellated Holes", [row["item"] for row in rows])

    def test_round_hole_bbox_corner_touching_diagonal_edge_is_not_castellated(self):
        outline = (FakeDrawing((-1000000, -1000000), (1000000, 1000000)),)
        pad = FakePad(
            "p1",
            (0, 200000),
            (1000000, 1000000),
            (200000, 200000),
            attribute=0,
        )

        result = self.analyze(FakeBoard(pads=(pad,), drawings=outline), "standard")

        self.assertNotIn(
            "Castellated Holes",
            [row["item"] for row in rows_for(result, "Special Drill Holes")],
        )

    def test_castellated_hole_prunes_far_drills(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        pads = tuple(
            FakePad(
                "p%s" % index,
                (2000000 + index * 10000, 2000000),
                (1000000, 1000000),
                (300000, 300000),
                attribute=0,
            )
            for index in range(30)
        )
        calls = []
        original_distance = local_checks_module.point_segment_distance

        def counted_distance(point, segment):
            calls.append(point)
            return original_distance(point, segment)

        with mock.patch.object(local_checks_module, "point_segment_distance", counted_distance):
            result = self.analyze(FakeBoard(pads=pads, drawings=outline), "standard")

        rows = rows_for(result, "Special Drill Holes")
        self.assertNotIn("Castellated Holes", [row["item"] for row in rows])
        self.assertEqual([], calls)

    def test_special_drill_uses_cached_hole_items_for_pad_drills(self):
        pth = FakePad("pth", (0, 0), (1000000, 1000000), drill=(300000, 300000), attribute=0)
        pads = (pth,) + tuple(
            FakePad(
                "smd%s" % index,
                (1000000 + index * 1000000, 0),
                (500000, 500000),
                attribute=1,
            )
            for index in range(20)
        )
        original_is_castellated_hole = LocalChecks._is_castellated_hole
        calls = []

        def counted_is_castellated_hole(checks, hole):
            calls.append(hole.item.m_Uuid.AsString())
            return original_is_castellated_hole(checks, hole)

        with mock.patch.object(LocalChecks, "_is_castellated_hole", counted_is_castellated_hole):
            self.analyze(FakeBoard(pads=pads), "standard")

        self.assertEqual(["pth"], calls)

    def test_via_and_pth_overlaps_are_only_holes_on_smd_items(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, net="A")
        bga_pad = FakePad("p1", (0, 0), (1000000, 1000000), attribute=1, net="A")
        pth = FakePad("p2", (2000000, 0), (1000000, 1000000), (300000, 300000), attribute=0, net="B")
        smd = FakePad("p3", (2000000, 0), (1000000, 1000000), attribute=1, net="B")
        board = FakeBoard(tracks=(via,), pads=(bga_pad, pth, smd), footprint_name="BGA-100")
        result = self.analyze(board, "standard")

        self.assertEqual([], rows_for(result, "Special Drill Holes"))
        hole_items = [row["item"] for row in rows_for(result, "Holes on SMD Pads")]
        self.assertIn("Via on BGA Pad", hole_items)
        self.assertIn("PTH on SMD Pad", hole_items)

    def test_bottom_side_different_net_via_is_only_a_hole_on_smd_item(self):
        via = FakeVia(
            "v1",
            (0, 0),
            500000,
            200000,
            layer="F.Cu",
            net="A",
            layer_pair=("F.Cu", "B.Cu"),
        )
        pad = FakePad(
            "p1",
            (0, 0),
            (1000000, 1000000),
            layer="B.Cu",
            attribute=1,
            net="B",
        )

        result = self.analyze(FakeBoard(tracks=(via,), pads=(pad,)), "standard")

        self.assertEqual([], rows_for(result, "Special Drill Holes"))
        row = first_row(result, "Holes on SMD Pads")
        self.assertEqual("Via on SMD Pad", row["item"])
        self.assertEqual("p1", row["related_id"])
        self.assertEqual(["B.Cu"], row["layer"])

    def test_through_pth_on_bottom_smd_pad_reports_different_net_overlap(self):
        pth = FakePad(
            "pth",
            (0, 0),
            (1000000, 1000000),
            drill=(300000, 300000),
            layer="F.Cu",
            attribute=0,
            net="A",
        )
        smd = FakePad(
            "smd",
            (0, 0),
            (1000000, 1000000),
            layer="B.Cu",
            attribute=1,
            net="B",
        )

        result = self.analyze(FakeBoard(pads=(pth, smd)), "standard")

        row = first_row(result, "Holes on SMD Pads")
        self.assertEqual("PTH on SMD Pad", row["item"])
        self.assertEqual("pth", row["id"])
        self.assertEqual("smd", row["related_id"])

    def test_via_edge_grazing_rectangular_smd_pad_is_not_on_pad(self):
        via = FakeVia("v1", (840000, 0), 300000, 200000, net="A")
        pad = FakePad("p1", (0, 0), (1600000, 400000), attribute=1, shape=1, net="A")
        result = self.analyze(FakeBoard(tracks=(via,), pads=(pad,)), "standard")

        self.assertEqual([], rows_for(result, "Special Drill Holes"))
        self.assertEqual([], rows_for(result, "Holes on SMD Pads"))

    def test_holes_on_smd_uses_drill_bbox_not_via_body(self):
        via = FakeVia("v1", (0, 0), 2000000, 200000, net="A")
        pad = FakePad("p1", (900000, 0), (400000, 400000), attribute=1, shape=1, net="A")
        result = self.analyze(FakeBoard(tracks=(via,), pads=(pad,)), "standard")

        self.assertEqual([], rows_for(result, "Special Drill Holes"))
        self.assertEqual([], rows_for(result, "Holes on SMD Pads"))

    def test_holes_on_smd_prunes_far_large_via_bodies(self):
        vias = tuple(
            FakeVia("v%s" % index, (index * 10000000, 0), 9000000, 200000, net="A")
            for index in range(30)
        )
        pads = tuple(
            FakePad(
                "p%s" % index,
                (index * 10000000 + 4000000, 0),
                (400000, 400000),
                attribute=1,
                shape=1,
                net="A",
            )
            for index in range(30)
        )
        original_overlap = LocalChecks._circle_pad_overlap_mm
        calls = []

        def counted_overlap(checks, center, radius_nm, pad):
            calls.append(pad.item.m_Uuid.AsString())
            return original_overlap(checks, center, radius_nm, pad)

        with mock.patch.object(LocalChecks, "_circle_pad_overlap_mm", counted_overlap):
            result = self.analyze(FakeBoard(tracks=vias, pads=pads), "standard")

        self.assertEqual([], rows_for(result, "Special Drill Holes"))
        self.assertEqual([], rows_for(result, "Holes on SMD Pads"))
        self.assertEqual([], calls)

    def test_holes_on_smd_uses_smd_pad_candidates_only(self):
        via = FakeVia("via", (0, 0), 500000, 200000, net="A")
        pth = FakePad("pth", (0, 0), (1000000, 1000000), attribute=0, net="A")
        smd = FakePad("smd", (10000000, 0), (1000000, 1000000), attribute=1, net="A")
        original_overlap = LocalChecks._circle_pad_overlap_mm
        calls = []

        def counted_overlap(checks, center, radius_nm, pad):
            calls.append(pad.item.m_Uuid.AsString())
            return original_overlap(checks, center, radius_nm, pad)

        board = FakeBoard(tracks=(via,), pads=(pth, smd))
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )

        with mock.patch.object(LocalChecks, "_circle_pad_overlap_mm", counted_overlap):
            result = checks.get_holes_on_smd_pads({"Holes on SMD Pads": {"check": []}})

        self.assertEqual([], rows_for_category_result(result))
        self.assertNotIn("pth", calls)

    def test_holes_on_smd_pth_branch_reuses_hole_items_cache(self):
        pth = FakePad("pth", (0, 0), (1000000, 1000000), drill=(300000, 300000), attribute=0, net="A")
        smd = FakePad("smd", (0, 0), (1000000, 1000000), attribute=1, net="A")
        board = FakeBoard(pads=(pth, smd))
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )

        with mock.patch.object(checks, "_all_pads", side_effect=AssertionError("_all_pads should not be called")):
            result = checks.get_holes_on_smd_pads({"Holes on SMD Pads": {"check": []}})

        self.assertEqual("PTH on SMD Pad", rows_for_category_result(result)[0]["item"])

    def test_holes_on_smd_uses_native_effective_pad_shape_for_custom_pad(self):
        via = FakeVia("via", (0, 0), 500000, 200000, net="A")
        custom_smd = FakePad(
            "custom-smd",
            (0, 0),
            (2000000, 2000000),
            attribute=1,
            shape=6,
            net="A",
        )
        calls = []

        class EffectiveShapeBackend(FakeBackend):
            def hole_pad_overlap_nm(self, hole, pad, pad_layer_id=None):
                calls.append((hole.m_Uuid.AsString(), pad.m_Uuid.AsString(), pad_layer_id))
                return 0

        board = FakeBoard(tracks=(via,), pads=(custom_smd,))
        checks = LocalChecks(
            {},
            board,
            backend=EffectiveShapeBackend(board),
            rules=rules_for_profile("standard"),
        )

        result = checks.get_holes_on_smd_pads(
            {"Holes on SMD Pads": {"check": []}}
        )

        self.assertEqual([], rows_for_category_result(result))
        self.assertEqual([("via", "custom-smd", 0)], calls)

    def test_holes_on_smd_uses_native_overlap_measurement(self):
        via = FakeVia("via", (0, 0), 500000, 200000, net="A")
        smd = FakePad("smd", (0, 0), (1000000, 1000000), attribute=1, net="A")

        class EffectiveShapeBackend(FakeBackend):
            def hole_pad_overlap_nm(self, _hole, _pad, pad_layer_id=None):
                self.measured_layer = pad_layer_id
                return 125000

        board = FakeBoard(tracks=(via,), pads=(smd,))
        backend = EffectiveShapeBackend(board)
        checks = LocalChecks(
            {},
            board,
            backend=backend,
            rules=rules_for_profile("standard"),
        )

        result = checks.get_holes_on_smd_pads(
            {"Holes on SMD Pads": {"check": []}}
        )
        row = rows_for_category_result(result)[0]

        self.assertEqual("Via on SMD Pad", row["item"])
        self.assertEqual("0.125", row["value"])
        self.assertEqual("smd", row["related_id"])
        self.assertEqual(0, backend.measured_layer)

    def test_holes_on_smd_excludes_drilled_non_pth_pad_attributes(self):
        unsupported = FakePad(
            "unsupported",
            (0, 0),
            (1000000, 1000000),
            drill=(300000, 300000),
            attribute=2,
            net="A",
        )
        smd = FakePad("smd", (0, 0), (1000000, 1000000), attribute=1, net="A")
        result = self.analyze(
            FakeBoard(pads=(unsupported, smd)),
            "standard",
            include_passed_details=True,
        )

        self.assertEqual([], rows_for(result, "Holes on SMD Pads"))

    def test_slot_hole_on_smd_uses_slot_bbox_overlap(self):
        slot = FakePad("slot", (0, 0), (3000000, 1000000), drill=(1600000, 200000), attribute=0, drill_shape=1, net="A")
        smd = FakePad("smd", (750000, 0), (300000, 300000), attribute=1, shape=1, net="A")
        result = self.analyze(FakeBoard(pads=(slot, smd)), "standard")

        rows = rows_for(result, "Holes on SMD Pads")
        self.assertIn("PTH on SMD Pad", [row["item"] for row in rows])
        self.assertEqual("slot", rows[0]["id"])
        self.assertEqual("smd", rows[0]["related_id"])

    def test_slot_hole_on_round_smd_uses_slot_capsule_overlap(self):
        slot = FakePad("slot", (0, 0), (3000000, 1000000), drill=(1600000, 200000), attribute=0, drill_shape=1, net="A")
        smd = FakePad("smd", (790000, 190000), (300000, 300000), attribute=1, shape=0, net="A")
        result = self.analyze(FakeBoard(pads=(slot, smd)), "standard")

        self.assertEqual([], rows_for(result, "Holes on SMD Pads"))

    def test_npth_on_smd_pad_and_missing_smask_opening(self):
        npth = FakePad("p1", (0, 0), (1000000, 1000000), (300000, 300000), attribute=3, net="A")
        smd = FakePad("p2", (0, 0), (1000000, 1000000), attribute=1, net="A", mask_open=False)
        result = self.analyze(FakeBoard(pads=(npth, smd)), "standard")

        self.assertEqual("NPTH on SMD Pad", first_row(result, "Holes on SMD Pads")["item"])
        self.assertEqual("Missing SMask Opening", first_row(result, "Missing SMask Openings")["item"])
        self.assertEqual("Missing SMask Opening", analysis_first_row(result, "Missing SMask Openings")["item"])

    def test_missing_smask_excludes_only_pads_from_net_tie_footprints(self):
        class NetTieBackend(FakeBackend):
            def net_tie_footprint_pad_ids(self):
                return frozenset(("net-tie-pad",))

        board = FakeBoard(
            pads=(
                FakePad(
                    "net-tie-pad",
                    (0, 0),
                    (1000000, 1000000),
                    mask_open=False,
                ),
                FakePad(
                    "ordinary-pad",
                    (2000000, 0),
                    (1000000, 1000000),
                    mask_open=False,
                ),
            )
        )
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NetTieBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Missing SMask Openings")
        self.assertEqual(["ordinary-pad"], [row["id"] for row in rows])

    def test_missing_smask_checks_opening_on_the_pad_copper_side(self):
        class LayerMaskBackend(FakeBackend):
            def pad_has_solder_mask_opening_on_layer(self, pad, layer_name):
                if pad.m_Uuid.AsString() == "bottom-missing":
                    return layer_name == "F.Cu"
                return layer_name == "B.Cu"

        pads = (
            FakePad(
                "bottom-missing",
                (0, 0),
                (1000000, 1000000),
                layer="B.Cu",
            ),
            FakePad(
                "bottom-open",
                (2000000, 0),
                (1000000, 1000000),
                layer="B.Cu",
            ),
        )
        board = FakeBoard(pads=pads)
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=LayerMaskBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Missing SMask Openings")
        self.assertEqual(["bottom-missing"], [row["id"] for row in rows])
        self.assertEqual(["B.Cu"], rows[0]["layer"])
        self.assertIn("B.Cu", rows[0]["message"])

    def test_missing_smask_ignores_copper_zone_without_opening(self):
        copper = FakeZone("z1", (0, 0), (1000000, 1000000), layer="F.Cu", net="A")
        result = self.analyze(FakeBoard(zones=(copper,)), "standard")

        rows = rows_for(result, "Missing SMask Openings")
        self.assertNotIn("z1", [row["id"] for row in rows])

    def test_missing_smask_ignores_copper_zone_with_mask_opening(self):
        copper = FakeZone("z1", (0, 0), (1000000, 1000000), layer="F.Cu", net="A")
        opening = FakeZone("m1", (0, 0), (1000000, 1000000), layer="F.Mask")
        result = self.analyze(FakeBoard(zones=(copper, opening)), "standard")

        rows = rows_for(result, "Missing SMask Openings")
        self.assertNotIn("z1", [row["id"] for row in rows])

    def test_missing_smask_ignores_zone_with_edge_touching_mask_opening(self):
        copper = FakeZone("z1", (0, 0), (1000000, 1000000), layer="F.Cu", net="A")
        opening = FakeZone("m1", (1000000, 0), (1000000, 1000000), layer="F.Mask")
        result = self.analyze(FakeBoard(zones=(copper, opening)), "standard")

        rows = rows_for(result, "Missing SMask Openings")
        self.assertNotIn("z1", [row["id"] for row in rows])

    def test_missing_smask_does_not_scan_mask_openings_for_copper_zones(self):
        copper = FakeZone("z1", (0, 0), (1000000, 1000000), layer="F.Cu", net="A")
        openings = tuple(
            FakeZone(
                "m%s" % index,
                (index * 10000000 + 5000000, 0),
                (1000000, 1000000),
                layer="F.Mask",
            )
            for index in range(30)
        )
        original_bbox_overlaps_area = local_checks_module.bbox_overlaps_area
        calls = []

        def counted_bbox_overlaps_area(left, right):
            calls.append(right)
            return original_bbox_overlaps_area(left, right)

        with mock.patch("kicad_dfm.services.local_checks.bbox_overlaps_area", counted_bbox_overlaps_area):
            result = self.analyze(FakeBoard(zones=(copper,) + openings), "standard")

        rows = rows_for(result, "Missing SMask Openings")
        self.assertNotIn("z1", [row["id"] for row in rows])
        self.assertEqual([], calls)

    def test_solder_mask_analysis_reports_bridge(self):
        left = FakePad("p1", (0, 0), (1000000, 1000000), net="A")
        right = FakePad("p2", (1100000, 0), (1000000, 1000000), net="B")

        result = self.analyze(FakeBoard(pads=(left, right)), "standard")

        row = next(
            row for row in rows_for(result, "Solder Mask Analysis")
            if row["item"] == "Solder Mask Bridge"
        )
        self.assertEqual("0.1", row["value"])
        self.assertEqual(["F.Mask"], row["layer"])

    def test_solder_mask_analysis_excludes_pth_without_mask_layer(self):
        class LayerMaskBackend(FakeBackend):
            def pad_has_solder_mask_opening_on_layer(self, pad, layer_name):
                return pad.attribute == 1 and layer_name == "F.Cu"

        thermal_via = FakePad(
            "thermal", (0, 0), (550000, 550000), drill=(250000, 250000),
            attribute=0, net="GND",
        )
        smd = FakePad(
            "ep", (700000, 0), (550000, 550000), attribute=1, net="GND"
        )
        board = FakeBoard(pads=(thermal_via, smd))
        result = OfflineDfmAnalysis(
            board, {}, backend=LayerMaskBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        self.assertEqual(
            [],
            [
                row for row in rows_for(result, "Solder Mask Analysis")
                if row["item"] == "Solder Mask Bridge"
            ],
        )

    def test_solder_mask_analysis_uses_standard_layer_name_with_stackup_alias(self):
        class AliasedLayerBackend(FakeBackend):
            def item_layer_name(self, _item):
                return "L1 (Sig, PWR)"

            def canonical_layer_name(self, layer_id):
                return "F.Cu" if layer_id == 0 else ""

        left = FakePad("p1", (0, 0), (1000000, 1000000), net="A")
        right = FakePad("p2", (1100000, 0), (1000000, 1000000), net="B")
        board = FakeBoard(pads=(left, right))
        result = OfflineDfmAnalysis(
            board, {}, backend=AliasedLayerBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        bridges = [
            row for row in rows_for(result, "Solder Mask Analysis")
            if row["item"] == "Solder Mask Bridge"
        ]
        self.assertEqual(1, len(bridges))
        self.assertEqual(["F.Mask"], bridges[0]["layer"])

    def test_solder_mask_analysis_uses_exact_opening_shape_clearance(self):
        class ExactMaskBackend(FakeBackend):
            def solder_mask_opening_bbox_nm(self, pad, _mask_layer):
                left, top, right, bottom = self.item_bbox(pad)
                return left - 200000, top - 200000, right + 200000, bottom + 200000

            def solder_mask_opening_clearance_nm(
                self, left, right, _mask_layer, _max_distance
            ):
                if {self.item_id(left), self.item_id(right)} == {"p1", "p2"}:
                    return 100000
                return 1000001

        left = FakePad("p1", (0, 0), (1000000, 1000000), net="A")
        right = FakePad("p2", (1500000, 0), (1000000, 1000000), net="B")
        board = FakeBoard(pads=(left, right))
        result = OfflineDfmAnalysis(
            board, {}, backend=ExactMaskBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        row = next(
            row for row in rows_for(result, "Solder Mask Analysis")
            if row["item"] == "Solder Mask Bridge"
        )
        self.assertEqual("0.1", row["value"])

    def test_solder_mask_analysis_reports_other_net_trace_near_opening(self):
        pad = FakePad("p1", (0, 0), (1000000, 1000000), net="A")
        trace = FakeTrack(
            "t1", (540000, 0), (1500000, 0), 20000, layer="F.Cu", net="B"
        )

        result = self.analyze(FakeBoard(tracks=(trace,), pads=(pad,)), "standard")

        row = next(
            row for row in rows_for(result, "Solder Mask Analysis")
            if row["item"] == "Solder Mask Covers Trace"
        )
        self.assertEqual("0.03", row["value"])
        self.assertEqual(("A",), row["opening_nets"])

    def test_solder_mask_analysis_uses_exact_opening_to_trace_clearance(self):
        class ExactMaskBackend(FakeBackend):
            def solder_mask_opening_to_item_clearance_nm(
                self, _pad, _item, _mask_layer, max_distance
            ):
                return max_distance + 1

        pad = FakePad("p1", (0, 0), (1000000, 1000000), net="A")
        trace = FakeTrack(
            "t1", (540000, 0), (1500000, 0), 20000, layer="F.Cu", net="B"
        )
        board = FakeBoard(tracks=(trace,), pads=(pad,))
        result = OfflineDfmAnalysis(
            board, {}, backend=ExactMaskBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        self.assertEqual(
            [],
            [
                row for row in rows_for(result, "Solder Mask Analysis")
                if row["item"] == "Solder Mask Covers Trace"
            ],
        )

    def test_solder_mask_analysis_reports_opening_over_multiple_nets(self):
        left = FakePad("p1", (0, 0), (400000, 400000), net="A")
        right = FakePad("p2", (1000000, 0), (400000, 400000), net="B")
        opening = FakeZone(
            "mask", (500000, 0), (2000000, 1000000), layer="F.Mask"
        )

        result = self.analyze(
            FakeBoard(pads=(left, right), zones=(opening,)), "standard"
        )

        row = next(
            row for row in rows_for(result, "Solder Mask Analysis")
            if row["item"] == "Solder Mask Covers Multiple Nets"
        )
        self.assertEqual("red", row["color"])
        self.assertEqual(["F.Mask"], row["layer"])

    def test_inner_drill_to_copper_uses_inner_rule_item(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, layer="In1.Cu", net="A")
        track = FakeTrack("t1", (300000, 0), (1300000, 0), 100000, layer="In1.Cu", net="B")
        result = self.analyze(FakeBoard(tracks=(via, track)), "standard")

        row = first_row(result, "Drill to Copper")
        self.assertEqual("Via-to-Trace [Inner]", row["item"])

    def test_through_via_drill_to_copper_checks_other_copper_layers(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, layer="F.Cu", layer_pair=("F.Cu", "B.Cu"), net="A")
        track = FakeTrack("t1", (300000, 0), (1300000, 0), 100000, layer="B.Cu", net="B")
        result = self.analyze(FakeBoard(tracks=(via, track)), "standard")

        row = first_row(result, "Drill to Copper")
        self.assertEqual("Via-to-Trace [Outer]", row["item"])
        self.assertEqual("t1", row["related_id"])
        self.assertEqual("B.Cu", row["related_layer"])

    def test_blind_via_drill_to_copper_uses_spanned_inner_layer_item(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, layer="F.Cu", layer_pair=("F.Cu", "In2.Cu"), net="A")
        track = FakeTrack("t1", (300000, 0), (1300000, 0), 100000, layer="In2.Cu", net="B")
        result = self.analyze(FakeBoard(tracks=(via, track)), "standard")

        row = first_row(result, "Drill to Copper")
        self.assertEqual("Via-to-Trace [Inner]", row["item"])
        self.assertEqual("t1", row["related_id"])

    def test_blind_via_drill_to_copper_ignores_unspanned_layers(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, layer="F.Cu", layer_pair=("F.Cu", "In2.Cu"), net="A")
        track = FakeTrack("t1", (300000, 0), (1300000, 0), 100000, layer="In3.Cu", net="B")
        result = self.analyze(FakeBoard(tracks=(via, track)), "standard")

        self.assertEqual("black", category_color(result, "Drill to Copper"))

    def test_copper_layer_names_are_cached_from_tracks_pads_and_zones(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, layer="F.Cu")
        pad = FakePad("p1", (0, 0), (1000000, 1000000), layer="In1.Cu")
        npth = FakePad("npth", (0, 0), (1000000, 1000000), drill=(300000, 300000), layer="B.Cu", attribute=3)
        zone = FakeZone("z1", (0, 0), (1000000, 1000000), layer="In2.Cu")
        board = FakeBoard(tracks=(track,), pads=(pad, npth), zones=(zone,))
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )

        self.assertEqual(("F.Cu", "In1.Cu", "In2.Cu"), checks.index.copper_layer_names)
        self.assertIs(checks.index.copper_layer_names, checks._copper_layer_names())
        self.assertIs(checks._copper_layer_names(), checks._copper_layer_names())

    def test_via_span_layers_reuse_cached_layer_ids(self):
        via = FakeVia("via", (0, 0), 500000, 200000, layer="F.Cu", layer_pair=("F.Cu", "In2.Cu"))
        tracks = (
            via,
            FakeTrack("front", (1000000, 0), (2000000, 0), 100000, layer="F.Cu"),
            FakeTrack("inner1", (1000000, 1000000), (2000000, 1000000), 100000, layer="In1.Cu"),
            FakeTrack("inner2", (1000000, 2000000), (2000000, 2000000), 100000, layer="In2.Cu"),
        )

        class CountingLayerBoard(FakeBoard):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.layer_id_calls = 0

            def GetLayerID(self, layer):
                self.layer_id_calls += 1
                return super().GetLayerID(layer)

        board = CountingLayerBoard(tracks=tracks)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        indexed_via = checks.index.vias[0]
        calls_after_index = board.layer_id_calls
        original_layer_id_for_name = checks._layer_id_for_name
        layer_id_lookup_calls = []

        def counted_layer_id_for_name(layer_name):
            layer_id_lookup_calls.append(layer_name)
            return original_layer_id_for_name(layer_name)

        with mock.patch.object(checks, "_layer_id_for_name", counted_layer_id_for_name):
            first = checks._hole_copper_layers(indexed_via)
            first_lookup_count = len(layer_id_lookup_calls)
            second = checks._hole_copper_layers(indexed_via)

        self.assertEqual(("F.Cu", "In1.Cu", "In2.Cu"), first)
        self.assertEqual(first, second)
        self.assertGreater(first_lookup_count, 0)
        self.assertEqual(first_lookup_count, len(layer_id_lookup_calls))
        self.assertEqual(calls_after_index, board.layer_id_calls)

    def test_multilayer_zone_and_nonmonotonic_via_stack_are_indexed_per_layer(self):
        via = FakeVia(
            "via",
            (0, 0),
            500000,
            200000,
            layer="F.Cu",
            layer_pair=("F.Cu", "B.Cu"),
            net="PLANE",
        )
        zone = FakeZone(
            "zone",
            (0, 0),
            (1000000, 1000000),
            layer="undefined",
            net="PLANE",
        )
        zone.polygons = (
            (((-500000, -500000), (500000, -500000), (500000, 500000), (-500000, 500000)), ()),
        )
        board = FakeBoard(tracks=(via,), zones=(zone,))

        class LayerStackBackend(FakeBackend):
            layer_names = {
                0: "F.Cu",
                4: "In1.Cu",
                6: "In2.Cu",
                8: "In3.Cu",
                10: "In4.Cu",
                2: "B.Cu",
            }

            def item_copper_layer_ids(self, item):
                if item is via:
                    return (0, 4, 6, 8, 10, 2)
                if item is zone:
                    return (4, 10)
                return ()

            def canonical_layer_name(self, layer_id):
                return self.layer_names[layer_id]

            def layer_name(self, layer_id):
                return self.layer_names[layer_id]

        checks = LocalChecks(
            {},
            board,
            backend=LayerStackBackend(board),
            rules=rules_for_profile("standard"),
        )

        self.assertEqual(
            ("In1.Cu", "In4.Cu"),
            tuple(indexed.layer_name for indexed in checks.index.zones),
        )
        self.assertTrue(all(indexed.zone_polygons_nm for indexed in checks.index.zones))
        self.assertEqual(
            ("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"),
            checks._via_span_layers(checks.index.vias[0]),
        )
        rows = list(
            checks._iter_unconnected_via_results(
                {"Signal Integrity": {"check": []}}
            )
        )
        self.assertEqual([], rows)

    def test_indexed_pair_key_handles_missing_uuid(self):
        board = FakeBoard(tracks=(FakeTrack("t1", (0, 0), (1000000, 0), 100000),))
        checks = LocalChecks({}, board, backend=FakeBackend(board), rules=rules_for_profile("standard"))
        with_uuid = checks.index.tracks[0]
        without_uuid = replace(with_uuid, item=object(), item_id="")

        self.assertEqual(
            checks._indexed_pair_key(with_uuid, without_uuid),
            checks._indexed_pair_key(without_uuid, with_uuid),
        )

    def test_flat_track_pad_zone_items_are_cached(self):
        tracks = (
            FakeTrack("t1", (0, 0), (1000000, 0), 100000, layer="B.Cu"),
            FakeTrack("t2", (0, 1000000), (1000000, 1000000), 100000, layer="F.Cu"),
        )
        pads = (
            FakePad("p1", (0, 0), (1000000, 1000000), layer="B.Cu", attribute=0),
            FakePad("p2", (0, 1000000), (1000000, 1000000), layer="F.Cu", attribute=1),
            FakePad("npth", (2000000, 0), (500000, 500000), drill=(200000, 200000), layer="B.Cu", attribute=3),
        )
        zones = (
            FakeZone("z1", (0, 0), (1000000, 1000000), layer="B.Cu"),
            FakeZone("z2", (0, 1000000), (1000000, 1000000), layer="F.Cu"),
        )
        board = FakeBoard(tracks=tracks, pads=pads, zones=zones)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )

        self.assertEqual(("t1", "t2"), tuple(item.item.m_Uuid.AsString() for item in checks.index.tracks))
        self.assertEqual(("p1", "npth", "p2"), tuple(item.item.m_Uuid.AsString() for item in checks.index.pads))
        self.assertEqual(("p1", "p2"), tuple(item.item.m_Uuid.AsString() for item in checks.index.copper_pads))
        self.assertEqual(("p1",), tuple(item.item.m_Uuid.AsString() for item in checks.index.copper_pads_by_layer["B.Cu"]))
        self.assertEqual(("p1", "p2"), tuple(item.item.m_Uuid.AsString() for item in checks.index.copper_pads_by_layer["F.Cu"]))
        self.assertEqual(("p2",), tuple(item.item.m_Uuid.AsString() for item in checks.index.smd_pads))
        self.assertEqual(("p2",), tuple(item.item.m_Uuid.AsString() for item in checks.index.smd_pads_by_layer["F.Cu"]))
        self.assertEqual((), checks.index.smd_pads_by_layer["B.Cu"])
        self.assertEqual(
            tuple(item.bbox_nm[0] for item in checks.index.smd_pads_by_layer["F.Cu"]),
            checks.index.smd_pad_x_starts_by_layer["F.Cu"],
        )
        self.assertEqual(
            tuple(item.bbox_nm[0] for item in checks.index.copper_pads_by_layer["B.Cu"]),
            checks.index.copper_pad_x_starts_by_layer["B.Cu"],
        )
        self.assertEqual(1000000, checks.index.pad_max_width_by_layer["B.Cu"])
        self.assertEqual(1000000, checks.index.copper_pad_max_width_by_layer["B.Cu"])
        self.assertEqual(1000000, checks.index.smd_pad_max_width_by_layer["F.Cu"])
        self.assertEqual(1100000, checks.index.track_max_width_by_layer["B.Cu"])
        self.assertEqual(1000000, checks.index.zone_max_width_by_layer["B.Cu"])
        self.assertEqual(("z1", "z2"), tuple(item.item.m_Uuid.AsString() for item in checks.index.zones))
        self.assertIs(checks.index.tracks, checks._all_tracks())
        self.assertIs(checks.index.pads, checks._all_pads())
        self.assertIs(checks.index.copper_pads, checks._copper_pads())
        self.assertIs(checks.index.smd_pads, checks._smd_pads())
        self.assertIs(checks.index.zones, checks._all_zones())

    def test_indexed_items_cache_type_flags(self):
        track = FakeTrack("track", (0, 0), (1000000, 0), 100000)
        via = FakeVia("via", (2000000, 0), 500000, 200000)
        pad = FakePad("pad", (3000000, 0), (1000000, 1000000), drill=(300000, 300000), attribute=0)
        board = FakeBoard(tracks=(track, via), pads=(pad,))

        class CountingBackend(FakeBackend):
            def __init__(self, board):
                super().__init__(board)
                self.is_via_calls = 0
                self.is_track_calls = 0
                self.is_pad_calls = 0

            def is_via(self, item):
                self.is_via_calls += 1
                return super().is_via(item)

            def is_track(self, item):
                self.is_track_calls += 1
                return super().is_track(item)

            def is_pad(self, item):
                self.is_pad_calls += 1
                return super().is_pad(item)

        backend = CountingBackend(board)
        checks = LocalChecks(
            {},
            board,
            backend=backend,
            rules=rules_for_profile("standard"),
        )

        indexed_track = checks.index.tracks[0]
        indexed_via = checks.index.vias[0]
        indexed_pad = checks.index.pads[0]
        self.assertTrue(indexed_track.is_track)
        self.assertFalse(indexed_track.is_via)
        self.assertTrue(indexed_via.is_via)
        self.assertFalse(indexed_via.is_track)
        self.assertTrue(indexed_pad.is_pad)
        self.assertEqual(2, backend.is_via_calls)
        self.assertEqual(1, backend.is_track_calls)
        self.assertEqual(0, backend.is_pad_calls)

    def test_nearby_items_includes_wide_left_candidate_before_small_gap(self):
        wide = FakePad("wide", (500000, 0), (1000000, 100000), net="A")
        small_gap = FakePad("small_gap", (650000, 1000000), (100000, 100000), net="A")
        target = FakePad("target", (950000, 0), (100000, 100000), net="A")
        board = FakeBoard(pads=(wide, small_gap, target))
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        pads = tuple(item for item in checks.index.pads_by_layer["F.Cu"] if item.item is not target)
        starts = tuple(item.bbox_nm[0] for item in pads)
        target_indexed = next(item for item in checks.index.pads_by_layer["F.Cu"] if item.item is target)

        candidates = tuple(nearby_items(target_indexed, pads, starts, 0, max_bbox_width_nm(pads)))

        self.assertEqual(("wide",), tuple(item.item.m_Uuid.AsString() for item in candidates if item.item is wide))

    def test_hole_items_and_drill_candidates_are_cached(self):
        via = FakeVia("via", (0, 0), 500000, 200000)
        pth = FakePad("pth", (1000000, 0), (1000000, 1000000), drill=(300000, 300000), attribute=0)
        npth = FakePad("npth", (2000000, 0), (1000000, 1000000), drill=(300000, 300000), attribute=3)
        smd = FakePad("smd", (3000000, 0), (1000000, 1000000), drill=(0, 0), attribute=1)
        board = FakeBoard(tracks=(via,), pads=(pth, npth, smd))
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )

        self.assertEqual(("via", "pth", "npth"), tuple(item.item.m_Uuid.AsString() for item in checks.index.holes))
        self.assertEqual((100000.0, 150000.0, 150000.0), tuple(item.hole_radius_nm for item in checks.index.holes))
        self.assertIs(checks.index.holes, checks._hole_items())
        self.assertIs(checks.index.hole_drill_candidates, checks._drill_spacing_candidates())
        self.assertEqual(
            ("via", "pth", "npth"),
            tuple(candidate.indexed.item.m_Uuid.AsString() for candidate in checks.index.hole_drill_candidates),
        )
        self.assertEqual(
            (
                (-100000.0, -100000.0, 100000.0, 100000.0),
                (850000.0, -150000.0, 1150000.0, 150000.0),
                (1850000.0, -150000.0, 2150000.0, 150000.0),
            ),
            tuple(candidate.bbox_nm for candidate in checks.index.hole_drill_candidates),
        )

    def test_pth_drill_to_copper_uses_drill_bbox_not_pad_body(self):
        pad = FakePad("p1", (0, 0), (10000000, 10000000), drill=(200000, 200000), attribute=0, net="A")
        track = FakeTrack("t1", (4800000, 0), (5200000, 0), 100000, layer="F.Cu", net="B")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(pad,)), "standard")

        self.assertEqual("black", category_color(result, "Drill to Copper"))

    def test_slot_drill_to_copper_uses_slot_bbox_edge(self):
        slot = FakePad("slot", (0, 0), (3000000, 1000000), drill=(1600000, 200000), attribute=0, drill_shape=1, net="A")
        track = FakeTrack("t1", (950000, -500000), (950000, 500000), 100000, layer="F.Cu", net="B")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(slot,)), "standard")

        row = first_row(result, "Drill to Copper")
        self.assertEqual("PTH-to-Trace [Outer]", row["item"])
        self.assertEqual("0.1", row["value"])

    def test_slot_drill_to_track_uses_slot_capsule_edge(self):
        slot = FakePad("slot", (0, 0), (3000000, 1000000), drill=(1600000, 200000), attribute=0, drill_shape=1, net="A")
        track = FakeTrack("t1", (1000000, 200000), (1200000, 400000), 100000, layer="F.Cu", net="B")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(slot,)), "standard")

        row = first_row(result, "Drill to Copper")
        self.assertEqual("PTH-to-Trace [Outer]", row["item"])
        self.assertEqual("0.210555", row["value"])

    def test_npth_slot_to_round_copper_uses_slot_capsule_edge(self):
        slot = FakePad("slot", (0, 0), (3000000, 1000000), drill=(1600000, 200000), attribute=3, drill_shape=1, net="A")
        copper = FakePad("pad", (1000000, 200000), (200000, 200000), attribute=1, shape=0, net="B")
        result = self.analyze(FakeBoard(pads=(slot, copper)), "standard")

        row = first_row(result, "Drill to Copper")
        self.assertEqual("NPTH-to-Copper", row["item"])
        self.assertEqual("0.160555", row["value"])
        self.assertEqual(["Drl"], row["layer"])

    def test_npth_to_copper_keeps_one_drill_layer_result_across_copper_layers(self):
        hole = FakePad(
            "hole", (0, 0), (1000000, 1000000),
            drill=(200000, 200000), attribute=3, net="",
        )
        front = FakeTrack(
            "front", (350000, -500000), (350000, 500000),
            100000, layer="F.Cu", net="F",
        )
        back = FakeTrack(
            "back", (250000, -500000), (250000, 500000),
            100000, layer="B.Cu", net="B",
        )

        result = self.analyze(
            FakeBoard(tracks=(front, back), pads=(hole,)),
            "standard",
        )
        rows = [
            row
            for row in rows_for(result, "Drill to Copper")
            if row["item"] == "NPTH-to-Copper"
        ]

        self.assertEqual(1, len(rows))
        self.assertEqual(["Drl"], rows[0]["layer"])
        self.assertEqual("back", rows[0]["related_id"])
        self.assertEqual("B.Cu", rows[0]["related_layer"])
        self.assertEqual("0.1", rows[0]["value"])

    def test_pth_drill_to_copper_ignores_pad_and_zone_copper(self):
        hole = FakePad("hole", (0, 0), (1000000, 1000000), drill=(200000, 200000), attribute=0, net="A")
        copper = FakePad("pad", (420000, 0), (200000, 200000), attribute=1, net="B")
        zone = FakeZone("zone", (0, 0), (800000, 800000), layer="F.Cu", net="C")
        result = self.analyze(
            FakeBoard(pads=(hole, copper), zones=(zone,)), "standard"
        )

        self.assertEqual("black", category_color(result, "Drill to Copper"))
        self.assertEqual([], rows_for(result, "Drill to Copper"))

    def test_drill_to_copper_deduplicates_pth_copper_pad_across_layers(self):
        hole = FakePad("hole", (0, 0), (1000000, 1000000), drill=(200000, 200000), attribute=3, net="A")
        copper = FakePad("pad", (420000, 0), (200000, 200000), layer="F.Cu", attribute=0, net="B")
        track = FakeTrack("t1", (3000000, 0), (4000000, 0), 100000, layer="B.Cu", net="C")
        result = self.analyze(FakeBoard(tracks=(track,), pads=(hole, copper)), "standard")

        rows = [row for row in rows_for(result, "Drill to Copper") if row.get("related_id") == "pad"]
        self.assertEqual(1, len(rows))
        self.assertEqual("NPTH-to-Copper", rows[0]["item"])

    def test_npth_drill_to_copper_checks_nearby_zone_copper(self):
        hole = FakePad("hole", (0, 0), (1000000, 1000000), drill=(200000, 200000), attribute=3)
        zone = FakeZone("zone", (420000, 0), (200000, 400000), layer="F.Cu", net="B")
        result = self.analyze(FakeBoard(pads=(hole,), zones=(zone,)), "standard")

        row = first_row(result, "Drill to Copper")
        self.assertEqual("NPTH-to-Copper", row["item"])
        self.assertEqual(["Drl"], row["layer"])
        self.assertEqual("zone", row["related_id"])
        self.assertEqual("FakeZone", row["related_type"])

    def test_drill_to_copper_ignores_nearby_npth_pad_body_as_copper(self):
        hole = FakePad("hole", (0, 0), (1000000, 1000000), drill=(200000, 200000), attribute=3, net="A")
        npth = FakePad("npth", (420000, 0), (200000, 200000), drill=(100000, 100000), attribute=3, net="B")
        result = self.analyze(FakeBoard(pads=(hole, npth)), "standard")

        self.assertEqual("black", category_color(result, "Drill to Copper"))

    def test_drill_to_copper_ignores_same_uuid_wrapper_as_copper(self):
        hole = FakePad("hole", (0, 0), (1000000, 1000000), drill=(200000, 200000), attribute=0, net="A")
        same_uuid_wrapper = FakePad("hole", (0, 0), (1000000, 1000000), drill=(200000, 200000), attribute=0, net="B")
        board = FakeBoard(pads=(hole,))

        class WrapperBackend(FakeBackend):
            def iter_pads(self, footprint):
                return iter((hole, same_uuid_wrapper))

        checks = LocalChecks({}, board, backend=WrapperBackend(board), rules=rules_for_profile("standard"))
        result = checks.get_drill_to_copper({})

        self.assertEqual("black", result["color"])
        self.assertEqual([], result["check"])

    def test_drill_to_copper_prunes_far_large_pad_bodies(self):
        pads = tuple(
            FakePad(
                "p%s" % index,
                (index * 10000000, 0),
                (9000000, 9000000),
                drill=(200000, 200000),
                attribute=0,
                net="N%s" % index,
            )
            for index in range(30)
        )
        tracks = tuple(
            FakeTrack(
                "t%s" % index,
                (index * 10000000 + 4000000, 0),
                (index * 10000000 + 5000000, 0),
                100000,
                net="T%s" % index,
            )
            for index in range(30)
        )
        original_gap = LocalChecks._point_to_copper_gap_mm
        calls = []

        def counted_gap(checks, center, radius_nm, copper):
            calls.append(copper.item.m_Uuid.AsString())
            return original_gap(checks, center, radius_nm, copper)

        with mock.patch.object(LocalChecks, "_point_to_copper_gap_mm", counted_gap):
            result = self.analyze(FakeBoard(tracks=tracks, pads=pads), "standard")

        self.assertEqual("black", category_color(result, "Drill to Copper"))
        self.assertEqual([], calls)

    def test_drill_to_copper_prunes_far_zone_copper(self):
        hole = FakePad("hole", (0, 0), (1000000, 1000000), drill=(200000, 200000), attribute=3)
        zones = tuple(
            FakeZone(
                "z%s" % index,
                (index * 10000000 + 4000000, 0),
                (1000000, 1000000),
                layer="F.Cu",
                net="B",
            )
            for index in range(30)
        )
        original_gap = LocalChecks._point_to_copper_gap_mm
        calls = []

        def counted_gap(checks, center, radius_nm, copper):
            calls.append(copper.item.m_Uuid.AsString())
            return original_gap(checks, center, radius_nm, copper)

        with mock.patch.object(LocalChecks, "_point_to_copper_gap_mm", counted_gap):
            result = self.analyze(FakeBoard(pads=(hole,), zones=zones), "standard")

        self.assertEqual("black", category_color(result, "Drill to Copper"))
        self.assertEqual([], calls)

    def test_zone_to_board_edge_uses_copper_edge_rule_item(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        zone = FakeZone("z1", (200000, 2000000), (200000, 1000000), layer="F.Cu")
        result = self.analyze(FakeBoard(drawings=outline, zones=(zone,)), "standard")

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("Copper-to-Board Edge", row["item"])

    def test_zone_to_board_edge_uses_zone_edge_not_outline_endpoints(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        zone = FakeZone(
            "z1",
            (2000000, 570000),
            (1000000, 860000),
            layer="F.Cu",
        )
        zone.polygons = (
            (
                (
                    (1500000, 140000),
                    (2500000, 140000),
                    (2500000, 1000000),
                    (1500000, 1000000),
                ),
                (),
            ),
        )

        class MisleadingEndpointBackend(FakeBackend):
            def zone_point_distance_nm(self, _zone, _point, _layer_id=None):
                return 1500000

        board = FakeBoard(drawings=outline, zones=(zone,))
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=MisleadingEndpointBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("0.14", row["value"])

    def test_trace_to_internal_edgecut_uses_segment_prefilter(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
            FakeDrawing((2000000, 1000000), (2000000, 3000000)),
        )
        track = FakeTrack("t1", (1810000, 1500000), (1810000, 2500000), 100000)
        result = self.analyze(FakeBoard(tracks=(track,), drawings=outline), "standard")

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("Trace-to-Board Edge", row["item"])
        self.assertEqual("0.14", row["value"])

    def test_board_edge_prefilter_reuses_cached_segment_bboxes(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
            FakeDrawing((2000000, 1000000), (2000000, 3000000)),
        )
        track = FakeTrack("t1", (1810000, 1500000), (1810000, 2500000), 100000)
        board = FakeBoard(tracks=(track,), drawings=outline)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        self.assertEqual(5, len(checks.index.board_outline_segment_bboxes))

        with mock.patch.object(local_checks_module, "bbox_for_segments") as bbox_for_segments:
            result = checks.get_copper_to_board_edge({"Copper-to-Board Edge": {"check": []}})

        self.assertEqual("Trace-to-Board Edge", rows_for_category_result(result)[0]["item"])
        bbox_for_segments.assert_not_called()

    def test_board_edge_prefilter_uses_outline_x_window(self):
        outline = tuple(
            FakeDrawing((index * 10000000, 0), (index * 10000000, 4000000))
            for index in range(1, 40)
        ) + (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        track = FakeTrack("t1", (200000, 1500000), (200000, 2500000), 100000)
        board = FakeBoard(tracks=(track,), drawings=outline)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        real_bbox_near = local_checks_module.bbox_near

        with mock.patch.object(local_checks_module, "bbox_near", side_effect=real_bbox_near) as bbox_near:
            result = checks.get_copper_to_board_edge({"Copper-to-Board Edge": {"check": []}})

        self.assertEqual("Trace-to-Board Edge", rows_for_category_result(result)[0]["item"])
        self.assertLess(bbox_near.call_count, len(outline) // 4)

    def test_board_edge_distance_uses_near_outline_segments_only(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
            FakeDrawing((2000000, 1000000), (2000000, 3000000)),
        )
        track = FakeTrack("t1", (1810000, 1500000), (1810000, 2500000), 100000)
        board = FakeBoard(tracks=(track,), drawings=outline)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        real_segment_distance = local_checks_module.segment_distance

        with mock.patch.object(
            local_checks_module,
            "segment_distance",
            side_effect=real_segment_distance,
        ) as segment_distance:
            result = checks.get_copper_to_board_edge({"Copper-to-Board Edge": {"check": []}})

        self.assertEqual("Trace-to-Board Edge", rows_for_category_result(result)[0]["item"])
        self.assertEqual(1, segment_distance.call_count)

    def test_rectangular_pad_to_board_edge_uses_bbox_edge(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        pad = FakePad("p1", (640000, 2000000), (1000000, 400000), attribute=1, shape=1)
        result = self.analyze(FakeBoard(pads=(pad,), drawings=outline), "standard")

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("SMD-to-Board Edge", row["item"])
        self.assertEqual("0.14", row["value"])

    def test_non_round_pad_to_board_edge_prefers_exact_effective_shape(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        # Its axis-aligned bbox intersects the left board edge.  A rotated or
        # custom pad can still have positive effective-shape clearance.
        pad = FakePad(
            "p1",
            (200000, 2000000),
            (600000, 1200000),
            attribute=1,
            shape=1,
        )

        class EffectiveShapeBackend(FakeBackend):
            def item_to_segment_clearance_nm(
                self,
                _item,
                _segment,
                _layer_id=None,
                _max_distance_nm=0,
            ):
                return 140000

        board = FakeBoard(pads=(pad,), drawings=outline)
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=EffectiveShapeBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("0.14", row["value"])

    def test_non_smd_pad_to_board_edge_uses_copper_edge_rule_item(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        pad = FakePad("p1", (640000, 2000000), (1000000, 400000), attribute=0, shape=1)
        result = self.analyze(FakeBoard(pads=(pad,), drawings=outline), "standard")

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("Copper-to-Board Edge", row["item"])
        self.assertEqual("0.14", row["value"])

    def test_pth_pad_to_board_edge_keeps_original_pad_layer(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        track = FakeTrack("bcu", (2500000, 2000000), (3000000, 2000000), 100000, layer="B.Cu")
        pad = FakePad("pth", (640000, 2000000), (1000000, 400000), drill=(300000, 300000), attribute=0, shape=1)
        result = self.analyze(FakeBoard(tracks=(track,), pads=(pad,), drawings=outline), "standard")

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("pth", row["id"])
        self.assertEqual(["F.Cu"], row["layer"])

    def test_npth_pad_body_does_not_trigger_copper_to_board_edge(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        pad = FakePad("npth", (640000, 1000000), (1000000, 400000), drill=(300000, 300000), attribute=3, shape=1)
        result = self.analyze(FakeBoard(pads=(pad,), drawings=outline), "standard")

        self.assertEqual("black", category_color(result, "Copper-to-Board Edge"))

    def test_via_to_board_edge_uses_copper_edge_rule_item(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        via = FakeVia("v1", (390000, 2000000), 500000, 200000)
        result = self.analyze(FakeBoard(tracks=(via,), drawings=outline), "standard")

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("Copper-to-Board Edge", row["item"])
        self.assertEqual("0.14", row["value"])
        self.assertEqual("FakeVia", row["item_type"])

    def test_hole_to_board_edge_classifies_via_pth_and_npth(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        via = FakeVia("via-edge", (350000, 800000), 500000, 200000)
        pth = FakePad(
            "pth-edge", (500000, 1600000), (700000, 700000),
            drill=(200000, 200000), attribute=0,
        )
        npth = FakePad(
            "npth-edge", (300000, 2400000), (500000, 500000),
            drill=(200000, 200000), attribute=3,
        )

        result = self.analyze(
            FakeBoard(tracks=(via,), pads=(pth, npth), drawings=outline),
            "standard",
        )
        rows = rows_for(result, "Hole-to-Board Edge")
        by_id = {row["id"]: row for row in rows}

        self.assertEqual("Via-to-Board Edge", by_id["via-edge"]["item"])
        self.assertEqual("0.25", by_id["via-edge"]["value"])
        self.assertEqual("PTH-to-Board Edge", by_id["pth-edge"]["item"])
        self.assertEqual("0.4", by_id["pth-edge"]["value"])
        self.assertEqual("NPTH-to-Board Edge", by_id["npth-edge"]["item"])
        self.assertEqual("0.2", by_id["npth-edge"]["value"])

    def test_hole_to_board_edge_uses_slot_capsule_edge(self):
        outline = (FakeDrawing((0, 0), (0, 4000000)),)
        slot = FakePad(
            "slot-edge", (550000, 2000000), (1000000, 500000),
            drill=(600000, 200000), attribute=3, drill_shape=1,
        )

        result = self.analyze(FakeBoard(pads=(slot,), drawings=outline), "standard")
        row = first_row(result, "Hole-to-Board Edge")

        self.assertEqual("NPTH-to-Board Edge", row["item"])
        self.assertEqual("0.25", row["value"])

    def test_mounting_footprint_npth_is_classified_as_screw_hole(self):
        outline = (FakeDrawing((0, 0), (0, 4000000)),)
        hole = FakePad(
            "mounting-hole", (500000, 2000000), (700000, 700000),
            drill=(300000, 300000), attribute=3,
        )

        result = self.analyze(
            FakeBoard(
                pads=(hole,), drawings=outline,
                footprint_name="MountingHole_3.2mm_M3",
            ),
            "standard",
        )
        row = first_row(result, "Hole-to-Board Edge")

        self.assertEqual("Screw Hole-to-Board Edge", row["item"])
        self.assertEqual("0.35", row["value"])

    def test_zone_to_board_edge_uses_bbox_edge_distance(self):
        outline = (
            FakeDrawing((0, 0), (4000000, 0)),
            FakeDrawing((4000000, 0), (4000000, 4000000)),
            FakeDrawing((4000000, 4000000), (0, 4000000)),
            FakeDrawing((0, 4000000), (0, 0)),
        )
        zone = FakeZone("z1", (1140000, 2000000), (2000000, 1000000), layer="F.Cu")
        result = self.analyze(FakeBoard(drawings=outline, zones=(zone,)), "standard")

        row = first_row(result, "Copper-to-Board Edge")
        self.assertEqual("Copper-to-Board Edge", row["item"])
        self.assertEqual("0.14", row["value"])

    def test_signal_integrity_reports_dangling_track(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        result = self.analyze(FakeBoard(tracks=(track,)), "standard")

        row = first_row(result, "Signal Integrity")
        self.assertEqual("Dangling Tracks", row["item"])
        self.assertEqual("red", row["color"])

    def test_signal_integrity_accepts_track_connected_to_pads(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        pads = (
            FakePad("p1", (0, 0), (500000, 500000), net="A"),
            FakePad("p2", (1000000, 0), (500000, 500000), net="A"),
        )
        result = self.analyze(FakeBoard(tracks=(track,), pads=pads), "standard")

        self.assertEqual("black", category_color(result, "Signal Integrity"))

    def test_signal_integrity_accepts_track_connected_to_rectangular_pad_edge(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        pads = (
            FakePad("p1", (0, 0), (500000, 500000), net="A"),
            FakePad("p2", (1650000, 0), (1200000, 400000), attribute=1, shape=1, net="A"),
        )
        result = self.analyze(FakeBoard(tracks=(track,), pads=pads), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Dangling Tracks", [row["item"] for row in rows])
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])

    def test_signal_integrity_does_not_connect_track_to_npth_pad(self):
        track = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        npth = FakePad("npth", (0, 0), (1000000, 1000000), drill=(300000, 300000), attribute=3, net="A")
        board = FakeBoard(tracks=(track,), pads=(npth,))
        result = self.analyze(board, "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertIn("Dangling Tracks", [row["item"] for row in rows])

        checks = LocalChecks({}, board, backend=FakeBackend(board), rules=rules_for_profile("standard"))
        self.assertEqual(("t1",), tuple(item.item.m_Uuid.AsString() for item in checks.index.connectable_items_by_net["A"]))

    def test_signal_integrity_reports_unconnected_via(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, net="A")
        result = self.analyze(FakeBoard(tracks=(via,)), "standard")

        row = first_row(result, "Signal Integrity")
        self.assertEqual("Unconnected Vias", row["item"])

    def test_signal_integrity_accepts_via_connected_to_track(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, net="A")
        track = FakeTrack("t1", (-1000000, 0), (1000000, 0), 100000, net="A")
        result = self.analyze(FakeBoard(tracks=(via, track)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Unconnected Vias", [row["item"] for row in rows])

    def test_signal_integrity_prefers_native_via_connectivity(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, net="PLANE")
        board = FakeBoard(tracks=(via,))

        class NativePlaneBackend(FakeBackend):
            def connected_copper_layer_ids(self, item):
                return (4,) if item is via else ()

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NativePlaneBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Unconnected Vias", [row["item"] for row in rows])

    def test_signal_integrity_treats_empty_native_via_connectivity_as_authoritative(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, net="A")
        track = FakeTrack("t1", (-1000000, 0), (1000000, 0), 100000, net="A")
        board = FakeBoard(tracks=(via, track))

        class NativeIsolatedBackend(FakeBackend):
            def connected_copper_layer_ids(self, item):
                return () if item is via else None

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NativeIsolatedBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertIn("Unconnected Vias", [row["item"] for row in rows])

    def test_signal_integrity_accepts_blind_via_connected_to_spanned_layer_track(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, layer="F.Cu", net="A", layer_pair=("F.Cu", "In2.Cu"))
        track = FakeTrack("t1", (-1000000, 0), (1000000, 0), 100000, layer="In2.Cu", net="A")
        result = self.analyze(FakeBoard(tracks=(via, track)), "standard")

        rows = rows_for(result, "Signal Integrity")
        items = [row["item"] for row in rows]
        self.assertNotIn("Unconnected Vias", items)
        self.assertNotIn("Trace Mssing", items)

    def test_signal_integrity_rejects_blind_via_connection_outside_span(self):
        via = FakeVia("v1", (0, 0), 500000, 200000, layer="F.Cu", net="A", layer_pair=("F.Cu", "In2.Cu"))
        track = FakeTrack("t1", (-1000000, 0), (1000000, 0), 100000, layer="In3.Cu", net="A")
        result = self.analyze(FakeBoard(tracks=(via, track)), "standard")

        rows = rows_for(result, "Signal Integrity")
        items = [row["item"] for row in rows]
        self.assertIn("Dangling Tracks", items)
        self.assertIn("Unconnected Vias", items)

    def test_signal_integrity_reports_acute_angle_traces(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        result = self.analyze(FakeBoard(tracks=(left, right)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertIn("Acute Angle Traces", [row["item"] for row in rows])
        acute = next(row for row in rows if row["item"] == "Acute Angle Traces")
        self.assertEqual("t1", acute["id"])
        self.assertEqual("t2", acute["related_id"])

    def test_signal_integrity_ignores_nearby_tracks_without_shared_endpoint(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 10000), (1000000, 1010000), 100000, net="A")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right)), "standard"),
            "Signal Integrity",
        )

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_ignores_degenerate_zero_degree_join(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (2000000, 0), 100000, net="A")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right)), "standard"),
            "Signal Integrity",
        )

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_ignores_smooth_line_to_arc_tangent(self):
        arc = FakeArc(
            "arc",
            (0, 0),
            (707107, 292893),
            (1000000, 1000000),
            100000,
            net="A",
        )
        line = FakeTrack("line", (0, 0), (1000000, 0), 100000, net="A")

        class ArcBackend(FakeBackend, BoardBackend):
            pass

        board = FakeBoard(tracks=(arc, line))
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=ArcBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()
        rows = rows_for(result, "Signal Integrity")

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_accepts_one_nanometre_endpoint_rounding(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (1, 0), (1000000, 1000000), 100000, net="A")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right)), "standard"),
            "Signal Integrity",
        )

        self.assertIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_rejects_two_nanometre_endpoint_gap(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (2, 0), (1000000, 1000000), 100000, net="A")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right)), "standard"),
            "Signal Integrity",
        )

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_ignores_acute_join_covered_by_same_net_pad(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        pad = FakePad("p1", (0, 0), (500000, 500000), net="A")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right), pads=(pad,)), "standard"),
            "Signal Integrity",
        )

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_ignores_acute_join_covered_by_same_net_via(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        via = FakeVia("v1", (0, 0), 500000, 200000, net="A")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right, via)), "standard"),
            "Signal Integrity",
        )

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_ignores_acute_join_covered_by_same_net_zone(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        zone = FakeZone("z1", (0, 0), (600000, 600000), net="A")
        zone.polygons = (
            (((-300000, -300000), (300000, -300000), (300000, 300000), (-300000, 300000)), ()),
        )

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right), zones=(zone,)), "standard"),
            "Signal Integrity",
        )

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_unfilled_zone_does_not_hide_acute_join(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        unfilled = FakeZone("z1", (0, 0), (600000, 600000), net="A")
        unfilled.polygons = ()

        rows = rows_for(
            self.analyze(
                FakeBoard(tracks=(left, right), zones=(unfilled,)),
                "standard",
            ),
            "Signal Integrity",
        )

        self.assertIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_ignores_acute_join_covered_by_third_track(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        branch = FakeTrack("t3", (0, 0), (-1000000, 0), 100000, net="A")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right, branch)), "standard"),
            "Signal Integrity",
        )

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_different_net_pad_does_not_hide_acute_join(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        pad = FakePad("p1", (0, 0), (500000, 500000), net="B")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right), pads=(pad,)), "standard"),
            "Signal Integrity",
        )

        self.assertIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_different_net_branch_does_not_hide_acute_join(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        branch = FakeTrack("t3", (0, 0), (-1000000, 0), 100000, net="B")

        rows = rows_for(
            self.analyze(FakeBoard(tracks=(left, right, branch)), "standard"),
            "Signal Integrity",
        )

        self.assertIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_teardrop_copper_hides_acute_join(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        teardrop = FakeZone("td", (0, 0), (600000, 600000), net="A")
        teardrop.polygons = (
            (((-300000, -300000), (300000, -300000), (300000, 300000), (-300000, 300000)), ()),
        )
        board = FakeBoard(tracks=(left, right), zones=(teardrop,))

        class TeardropBackend(FakeBackend):
            def zone_name(self, zone):
                return "$teardrop_padvia$" if zone is teardrop else ""

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=TeardropBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()
        rows = rows_for(result, "Signal Integrity")

        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_empty_net_teardrop_does_not_hide_acute_join(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        teardrop = FakeZone("td", (0, 0), (600000, 600000), net="")
        teardrop.polygons = (
            (((-300000, -300000), (300000, -300000), (300000, 300000), (-300000, 300000)), ()),
        )
        board = FakeBoard(tracks=(left, right), zones=(teardrop,))

        class TeardropBackend(FakeBackend):
            def zone_name(self, zone):
                return "$teardrop_padvia$" if zone is teardrop else ""

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=TeardropBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()
        rows = rows_for(result, "Signal Integrity")

        self.assertIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_backend_tessellates_arc_and_preserves_endpoint_tangents(self):
        arc = FakeArc(
            "arc",
            (0, 0),
            (707107, 292893),
            (1000000, 1000000),
            100000,
            net="A",
        )

        geometry = BoardBackend().track_geometry(arc)

        self.assertEqual(
            "kicad_arc_tessellated_1000nm", geometry["geometry_basis"]
        )
        self.assertEqual((0, 0), geometry["path"][0])
        self.assertIn((707107, 292893), geometry["path"])
        self.assertEqual((1000000, 1000000), geometry["path"][-1])
        self.assertGreater(len(geometry["path"]), 3)
        start_tangent = geometry["endpoint_vectors"][0]
        self.assertGreater(start_tangent[0], 0)
        self.assertAlmostEqual(0, start_tangent[1], delta=2)

    def test_backend_does_not_tessellate_straight_shape_with_get_arc_mid(self):
        line = FakeShapeDrawing(
            (0, 0),
            (500000, 500000),
            (1000000, 0),
            shape=0,
        )
        line.GetMid = lambda: line.midpoint

        geometry = BoardBackend().track_geometry(line)

        self.assertEqual("exact_kicad", geometry["geometry_basis"])
        self.assertEqual(((0, 0), (1000000, 0)), geometry["path"])

    def test_board_outline_tessellates_only_real_edge_cuts_arcs(self):
        line = FakeShapeDrawing(
            (0, 0),
            (500000, 500000),
            (1000000, 0),
            shape=0,
        )
        arc = FakeShapeDrawing(
            (1000000, 0),
            (1707107, 292893),
            (2000000, 1000000),
            shape=2,
        )
        backend = BoardBackend()
        backend.iter_drawings = lambda: iter((line, arc))

        outline = backend.board_outline_segments()

        self.assertEqual(((0, 0), (1000000, 0)), outline[0])
        self.assertNotIn(((1000000, 0), (2000000, 1000000)), outline)
        self.assertIn((1707107, 292893), tuple(point for segment in outline for point in segment))
        self.assertGreater(len(outline), 2)

    def test_base_outline_does_not_turn_unsupported_shape_into_chord(self):
        circle = FakeShapeDrawing(
            (0, 0),
            (500000, 500000),
            (1000000, 0),
            shape=1,
        )
        backend = BoardBackend()
        backend.iter_drawings = lambda: iter((circle,))

        self.assertEqual((), backend.board_outline_segments())

    def test_signal_integrity_uses_arc_tangent_for_acute_angle(self):
        arc = FakeArc(
            "arc",
            (0, 0),
            (707107, 292893),
            (1000000, 1000000),
            100000,
            net="A",
        )
        line = FakeTrack(
            "line", (0, 0), (1000000, -1000000), 100000, net="A"
        )

        class ArcBackend(FakeBackend, BoardBackend):
            pass

        board = FakeBoard(tracks=(arc, line))
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=ArcBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()
        acute = [
            row
            for row in rows_for(result, "Signal Integrity")
            if row["item"] == "Acute Angle Traces"
        ]

        self.assertEqual(1, len(acute))
        self.assertEqual(
            "kicad_arc_tessellated_1000nm", acute[0]["geometry_basis"]
        )

    def test_signal_integrity_checks_inner_copper_tracks_in_all_profiles(self):
        left = FakeTrack(
            "inner-left",
            (0, 0),
            (1000000, 0),
            100000,
            layer="In1.Cu",
            net="A",
        )
        right = FakeTrack(
            "inner-right",
            (0, 0),
            (1000000, 1000000),
            100000,
            layer="In1.Cu",
            net="A",
        )

        for profile in ("economy", "standard", "precision"):
            rows = rows_for(
                self.analyze(FakeBoard(tracks=(left, right)), profile),
                "Signal Integrity",
            )
            self.assertEqual(
                1,
                sum(row["item"] == "Acute Angle Traces" for row in rows),
            )
            self.assertEqual(
                2,
                sum(row["item"] == "Dangling Tracks" for row in rows),
            )

    def test_signal_integrity_ignores_right_angle_traces(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (0, 1000000), 100000, net="A")
        result = self.analyze(FakeBoard(tracks=(left, right)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_uses_actual_endpoints_for_nearby_right_angle_tracks(self):
        left = FakeTrack("t1", (0, 0), (100000, 0), 300000, net="A")
        right = FakeTrack(
            "t2", (100000, 100000), (100000, 0), 300000, net="A"
        )
        result = self.analyze(FakeBoard(tracks=(left, right)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_ignores_nearly_right_angle_traces(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000, 1000000), 100000, net="A")
        result = self.analyze(FakeBoard(tracks=(left, right)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Acute Angle Traces", [row["item"] for row in rows])

    def test_signal_integrity_excludes_ordinary_copper_zones(self):
        zone = FakeZone("z1", (0, 0), (1000000, 1000000), net="A")
        for profile in ("economy", "standard", "precision"):
            result = self.analyze(FakeBoard(zones=(zone,)), profile)

            rows = rows_for(result, "Signal Integrity")
            self.assertEqual([], rows)

    def test_signal_integrity_accepts_zone_connected_to_track(self):
        zone = FakeZone("z1", (0, 0), (1000000, 1000000), net="A")
        track = FakeTrack("t1", (-1000000, 0), (1000000, 0), 100000, net="A")
        result = self.analyze(FakeBoard(tracks=(track,), zones=(zone,)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Floating Copper", [row["item"] for row in rows])

    def test_signal_integrity_accepts_zone_touching_rectangular_pad_edge(self):
        zone = FakeZone("z1", (0, 0), (1000000, 1000000), net="A")
        pad = FakePad("p1", (1100000, 0), (1200000, 400000), attribute=1, shape=1, net="A")
        result = self.analyze(FakeBoard(pads=(pad,), zones=(zone,)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Floating Copper", [row["item"] for row in rows])

    def test_signal_integrity_accepts_pth_annulus_touching_filled_inner_zone(self):
        pad = FakePad(
            "p1",
            (0, 0),
            (1200000, 1200000),
            drill=(635000, 635000),
            layer="F.Cu",
            net="POWER",
            attribute=0,
        )
        zone = FakeZone(
            "z1",
            (2000000, 0),
            (6000000, 4000000),
            layer="In1.Cu",
            net="POWER",
        )
        zone.polygons = (
            (
                (
                    (-1000000, -2000000),
                    (5000000, -2000000),
                    (5000000, 2000000),
                    (-1000000, 2000000),
                ),
                (
                    (
                        (-317500, -317500),
                        (317500, -317500),
                        (317500, 317500),
                        (-317500, 317500),
                    ),
                ),
            ),
        )

        result = self.analyze(FakeBoard(pads=(pad,), zones=(zone,)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])
        self.assertNotIn("Floating Copper", [row["item"] for row in rows])

    def test_signal_integrity_excludes_copper_text_in_all_profiles(self):
        text = FakeText(
            "txt1",
            (1600000, 500000),
            (3200000, 1000000),
            (
            (((0, 0), (1000000, 0), (1000000, 1000000), (0, 1000000)), ()),
            (((2200000, 0), (3200000, 0), (3200000, 1000000), (2200000, 1000000)), ()),
            ),
        )
        track = FakeTrack("t1", (-500000, 500000), (500000, 500000), 100000, net="A")

        for profile in ("economy", "standard", "precision"):
            result = self.analyze(
                FakeBoard(tracks=(track,), drawings=(text,)),
                profile,
            )

            rows = rows_for(result, "Signal Integrity")
            self.assertNotIn("txt1", [row.get("id") for row in rows])
            self.assertNotIn("Floating Copper", [row["item"] for row in rows])

    def test_signal_integrity_profiles_share_the_same_finding_object_domain(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (0, 0), (1000000, 1000000), 100000, net="A")
        isolated = FakeTrack(
            "t3", (50000000, 0), (51000000, 0), 100000, net="A"
        )
        board = FakeBoard(tracks=(left, right, isolated))

        finding_domains = []
        for profile in ("economy", "standard", "precision"):
            rows = rows_for(self.analyze(board, profile), "Signal Integrity")
            finding_domains.append(
                {
                    (
                        row["item"],
                        row.get("id"),
                        row.get("related_id"),
                        tuple(row.get("layer") or ()),
                    )
                    for row in rows
                }
            )

        self.assertTrue(
            all(domain == finding_domains[0] for domain in finding_domains[1:])
        )
        finding_items = {finding[0] for finding in finding_domains[0]}
        self.assertIn("Trace Mssing", finding_items)
        self.assertIn("Acute Angle Traces", finding_items)
        self.assertIn("Dangling Tracks", finding_items)
        self.assertNotIn("Floating Copper", finding_items)

    def test_signal_integrity_reports_trace_missing_for_split_net(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (50000000, 0), (51000000, 0), 100000, net="A")
        result = self.analyze(FakeBoard(tracks=(left, right)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertIn("Trace Mssing", [row["item"] for row in rows])

    def test_trace_missing_uses_native_connectivity_components(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (50000000, 0), (51000000, 0), 100000, net="A")
        board = FakeBoard(tracks=(left, right))

        class NativeConnectedBackend(FakeBackend):
            def connected_item_ids(self, _item):
                return frozenset(("t1", "t2"))

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NativeConnectedBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])

    def test_trace_missing_reads_complete_native_component_once(self):
        tracks = (
            FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A"),
            FakeTrack("t2", (50000000, 0), (51000000, 0), 100000, net="A"),
            FakeTrack("t3", (100000000, 0), (101000000, 0), 100000, net="A"),
        )
        board = FakeBoard(tracks=tracks)

        class NativeComponentBackend(FakeBackend):
            connected_item_ids_are_components = True

            def __init__(self, current_board):
                super().__init__(current_board)
                self.connected_item_calls = 0

            def connected_item_ids(self, _item):
                self.connected_item_calls += 1
                return frozenset(("t1", "t2", "t3"))

        backend = NativeComponentBackend(board)
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=backend,
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])
        self.assertEqual(1, backend.connected_item_calls)

    def test_trace_missing_reports_distinct_native_connectivity_components(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (50000000, 0), (51000000, 0), 100000, net="A")
        board = FakeBoard(tracks=(left, right))

        class NativeSplitBackend(FakeBackend):
            def connected_item_ids(self, item):
                return frozenset((self.item_id(item),))

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NativeSplitBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertIn("Trace Mssing", [row["item"] for row in rows])

    def test_trace_missing_walks_transitive_native_connectivity(self):
        tracks = (
            FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A"),
            FakeTrack("t2", (50000000, 0), (51000000, 0), 100000, net="A"),
            FakeTrack("t3", (100000000, 0), (101000000, 0), 100000, net="A"),
        )
        board = FakeBoard(tracks=tracks)

        class NativeAdjacencyBackend(FakeBackend):
            adjacency = {
                "t1": ("t1", "t2"),
                "t2": ("t1", "t2", "t3"),
                "t3": ("t2", "t3"),
            }

            def connected_item_ids(self, item):
                return frozenset(self.adjacency[self.item_id(item)])

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NativeAdjacencyBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])

    def test_trace_missing_geometry_fallback_reports_split_with_filled_zone(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="PLANE")
        right = FakeTrack(
            "t2",
            (50000000, 0),
            (51000000, 0),
            100000,
            net="PLANE",
        )
        zone = FakeZone(
            "z1",
            (100000000, 0),
            (1000000, 1000000),
            net="PLANE",
        )
        zone.polygons = (
            (
                (
                    (99500000, -500000),
                    (100500000, -500000),
                    (100500000, 500000),
                    (99500000, 500000),
                ),
                (),
            ),
        )

        result = self.analyze(
            FakeBoard(tracks=(left, right), zones=(zone,)),
            "standard",
        )
        rows = rows_for(result, "Signal Integrity")

        self.assertIn("Trace Mssing", [row["item"] for row in rows])
        self.assertEqual(
            "completed",
            result.analysis_result["Signal Integrity"]["execution_status"],
        )

    def test_trace_missing_does_not_merge_multilayer_zone_clones_by_uuid(self):
        front = FakeTrack(
            "front", (-1000000, 0), (0, 0), 100000, layer="F.Cu", net="A"
        )
        inner = FakeTrack(
            "inner", (1000000, 0), (2000000, 0), 100000, layer="In1.Cu", net="A"
        )
        zone = FakeZone("zone", (500000, 0), (1000000, 1000000), net="A")
        polygon = (
            (((0, -500000), (1000000, -500000), (1000000, 500000), (0, 500000)), ()),
        )
        zone.polygons_by_layer = {0: polygon, 1: polygon}
        board = FakeBoard(tracks=(front, inner), zones=(zone,))

        class MultiLayerNativeBackend(FakeBackend):
            def __init__(self, current_board):
                super().__init__(current_board)
                self.native_calls = 0

            def item_copper_layer_ids(self, item):
                return (0, 1) if item is zone else ()

            def zone_polygons(self, item, layer_id=None):
                return item.polygons_by_layer.get(layer_id, ())

            def connected_item_ids(self, _item):
                self.native_calls += 1
                item_id = self.item_id(_item)
                return frozenset((item_id, "zone"))

        backend = MultiLayerNativeBackend(board)
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=backend,
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertIn("Trace Mssing", [row["item"] for row in rows])
        self.assertEqual(2, backend.native_calls)

    def test_trace_missing_geometry_connects_multilayer_zones_through_via(self):
        front = FakeTrack(
            "front", (-1000000, 0), (0, 0), 100000, layer="F.Cu", net="A"
        )
        inner = FakeTrack(
            "inner", (1000000, 0), (2000000, 0), 100000, layer="In1.Cu", net="A"
        )
        via = FakeVia(
            "via",
            (500000, 0),
            500000,
            200000,
            layer="F.Cu",
            layer_pair=("F.Cu", "In1.Cu"),
            net="A",
        )
        zone = FakeZone("zone", (500000, 0), (1000000, 1000000), net="A")
        polygon = (
            (((0, -500000), (1000000, -500000), (1000000, 500000), (0, 500000)), ()),
        )
        zone.polygons_by_layer = {0: polygon, 1: polygon}
        board = FakeBoard(tracks=(front, inner, via), zones=(zone,))

        class MultiLayerBackend(FakeBackend):
            def item_copper_layer_ids(self, item):
                if item is zone:
                    return (0, 1)
                if item is via:
                    return (0, 1)
                return ()

            def zone_polygons(self, item, layer_id=None):
                return item.polygons_by_layer.get(layer_id, ())

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=MultiLayerBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])

    def test_native_multilayer_zone_connects_layers_only_when_via_is_in_component(self):
        front = FakeTrack(
            "front", (-1000000, 0), (0, 0), 100000, layer="F.Cu", net="A"
        )
        inner = FakeTrack(
            "inner", (1000000, 0), (2000000, 0), 100000, layer="In1.Cu", net="A"
        )
        via = FakeVia(
            "via",
            (500000, 0),
            500000,
            200000,
            layer="F.Cu",
            layer_pair=("F.Cu", "In1.Cu"),
            net="A",
        )
        zone = FakeZone("zone", (500000, 0), (1000000, 1000000), net="A")
        polygon = (
            (((0, -500000), (1000000, -500000), (1000000, 500000), (0, 500000)), ()),
        )
        zone.polygons_by_layer = {0: polygon, 1: polygon}
        board = FakeBoard(tracks=(front, inner, via), zones=(zone,))

        class NativeViaBackend(FakeBackend):
            def item_copper_layer_ids(self, item):
                return (0, 1) if item in (zone, via) else ()

            def zone_polygons(self, item, layer_id=None):
                return item.polygons_by_layer.get(layer_id, ())

            def connected_item_ids(self, _item):
                return frozenset(("front", "inner", "via", "zone"))

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=NativeViaBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])

    def test_filled_zone_connectivity_ignores_layer_ambiguous_raw_clearance(self):
        left = FakeTrack("left", (-1000000, 0), (0, 0), 100000, net="A")
        right = FakeTrack("right", (1000000, 0), (2000000, 0), 100000, net="A")
        zone = FakeZone("zone", (500000, 0), (1000000, 1000000), net="A")
        zone.polygons = (
            (((0, -500000), (1000000, -500000), (1000000, 500000), (0, 500000)), ()),
        )
        board = FakeBoard(tracks=(left, right), zones=(zone,))

        class AmbiguousClearanceBackend(FakeBackend):
            def __init__(self, current_board):
                super().__init__(current_board)
                self.clearance_calls = 0

            def item_clearance_nm(self, _left, _right, _max_distance_nm):
                self.clearance_calls += 1
                return 2

        backend = AmbiguousClearanceBackend(board)
        result = OfflineDfmAnalysis(
            board,
            {},
            backend=backend,
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])
        self.assertEqual(0, backend.clearance_calls)

    def test_trace_missing_geometry_uses_teardrop_filled_copper(self):
        left = FakeTrack("left", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("right", (1400000, 0), (2400000, 0), 100000, net="A")
        teardrop = FakeZone("td", (1200000, 0), (500000, 300000), net="A")
        teardrop.polygons = (
            (((950000, -150000), (1450000, -150000), (1450000, 150000), (950000, 150000)), ()),
        )
        board = FakeBoard(tracks=(left, right), zones=(teardrop,))

        class TeardropBackend(FakeBackend):
            def zone_name(self, item):
                return "$teardrop_padvia$" if item is teardrop else ""

        result = OfflineDfmAnalysis(
            board,
            {},
            backend=TeardropBackend(board),
            rules=rules_for_profile("standard"),
        ).analyze()

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])

    def test_signal_integrity_does_not_call_split_pad_only_net_trace_missing(self):
        pads = (
            FakePad("p1", (0, 0), (1000000, 1000000), net="A"),
            FakePad("p2", (50000000, 0), (1000000, 1000000), net="A"),
        )

        result = self.analyze(FakeBoard(pads=pads), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])

    def test_trace_missing_stably_uses_routed_track_as_primary(self):
        main_tracks = (
            FakeTrack("main-1", (0, 0), (1000000, 0), 100000, net="A"),
            FakeTrack("main-2", (1000000, 0), (2000000, 0), 100000, net="A"),
            FakeTrack("main-3", (2000000, 0), (3000000, 0), 100000, net="A"),
        )
        split_tracks = (
            FakeTrack("split-left", (50000000, 0), (51000000, 0), 100000, net="A"),
            FakeTrack("split-right", (51000000, 0), (52000000, 0), 100000, net="A"),
        )
        pads = (
            FakePad("main-pad", (0, 0), (500000, 500000), net="A"),
            FakePad("split-pad", (50000000, 0), (500000, 500000), net="A"),
        )
        board = FakeBoard(tracks=main_tracks + split_tracks, pads=pads)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )

        rows = list(
            checks._iter_trace_missing_results(
                {"Signal Integrity": {"check": []}}
            )
        )

        self.assertEqual(1, len(rows))
        self.assertEqual("split-left", rows[0]["id"])
        self.assertEqual("FakeTrack", rows[0]["item_type"])

    def test_signal_integrity_component_search_prunes_far_same_net_items(self):
        tracks = tuple(
            FakeTrack(
                "t%s" % index,
                (index * 10000000, 0),
                (index * 10000000 + 1000000, 0),
                100000,
                net="A",
            )
            for index in range(30)
        )
        original_items_connected = LocalChecks._items_connected
        calls = []

        def counted_items_connected(checks, left, right):
            calls.append((left.item.m_Uuid.AsString(), right.item.m_Uuid.AsString()))
            return original_items_connected(checks, left, right)

        with mock.patch.object(LocalChecks, "_items_connected", counted_items_connected):
            result = self.analyze(FakeBoard(tracks=tracks), "standard")

        total_pairs = len(tracks) * (len(tracks) - 1) // 2
        rows = rows_for(result, "Signal Integrity")
        self.assertIn("Trace Mssing", [row["item"] for row in rows])
        self.assertLess(len(calls), total_pairs // 4)

    def test_trace_missing_reuses_cached_connectable_x_starts(self):
        tracks = tuple(
            FakeTrack(
                "t%s" % index,
                (index * 10000000, 0),
                (index * 10000000 + 1000000, 0),
                100000,
                net="A",
            )
            for index in range(5)
        )
        board = FakeBoard(tracks=tracks)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        original_copper_components = LocalChecks._copper_components
        calls = []

        def counted_copper_components(checks_self, items, sorted_items=None, starts=None):
            calls.append((items, sorted_items, starts))
            return original_copper_components(
                checks_self,
                items,
                sorted_items=sorted_items,
                starts=starts,
            )

        with mock.patch.object(LocalChecks, "_copper_components", counted_copper_components):
            rows = list(checks._iter_trace_missing_results({"Signal Integrity": {"check": []}}))

        self.assertIn("Trace Mssing", [row["item"] for row in rows])
        self.assertEqual(1, len(calls))
        items, sorted_items, starts = calls[0]
        self.assertIs(checks.index.connectable_items_by_net["A"], items)
        self.assertIs(checks.index.connectable_items_by_net["A"], sorted_items)
        self.assertIs(checks.index.connectable_x_starts_by_net["A"], starts)

    def test_trace_missing_computes_component_max_width_once(self):
        tracks = tuple(
            FakeTrack(
                "t%s" % index,
                (index * 10000000, 0),
                (index * 10000000 + 1000000, 0),
                100000,
                net="A",
            )
            for index in range(6)
        )
        board = FakeBoard(tracks=tracks)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        original_max_bbox_width_nm = local_checks_module.max_bbox_width_nm
        calls = []

        def counted_max_bbox_width_nm(items):
            calls.append(items)
            return original_max_bbox_width_nm(items)

        with mock.patch.object(local_checks_module, "max_bbox_width_nm", side_effect=counted_max_bbox_width_nm):
            rows = list(checks._iter_trace_missing_results({"Signal Integrity": {"check": []}}))

        self.assertIn("Trace Mssing", [row["item"] for row in rows])
        self.assertEqual(1, len(calls))
        self.assertIs(checks.index.connectable_items_by_net["A"], calls[0])

    def test_connection_candidates_use_net_x_window_when_gap_is_known(self):
        source = FakeTrack("source", (0, 0), (1000000, 0), 100000, net="A")
        touching = FakeTrack("touching", (1000000, 0), (2000000, 0), 100000, net="A")
        far_tracks = tuple(
            FakeTrack(
                "far%s" % index,
                (index * 10000000, 0),
                (index * 10000000 + 1000000, 0),
                100000,
                net="A",
            )
            for index in range(2, 30)
        )
        board = FakeBoard(tracks=(source, touching) + far_tracks)
        checks = LocalChecks(
            {},
            board,
            backend=FakeBackend(board),
            rules=rules_for_profile("standard"),
        )
        indexed_source = next(
            item
            for item in checks.index.items_by_net["A"]
            if item.item.m_Uuid.AsString() == "source"
        )

        all_candidates = checks._connection_candidates(indexed_source)
        nearby_candidates = checks._connection_candidates(indexed_source, max_gap_nm=indexed_source.width_nm / 2.0)

        self.assertEqual(len((source, touching) + far_tracks), len(all_candidates))
        self.assertEqual(
            {"source", "touching"},
            {item.item.m_Uuid.AsString() for item in nearby_candidates},
        )

    def test_connection_candidates_use_cached_connectable_items_by_net(self):
        class NonConnectableBackend(FakeBackend):
            def item_bbox(self, item):
                if item.m_Uuid.AsString() == "empty":
                    return None
                return super().item_bbox(item)

            def track_segment(self, item):
                if item.m_Uuid.AsString() == "empty":
                    return None
                return super().track_segment(item)

            def item_position(self, item):
                if item.m_Uuid.AsString() == "empty":
                    return None
                return super().item_position(item)

        source = FakeTrack("source", (0, 0), (1000000, 0), 100000, net="A")
        empty = FakeTrack("empty", (2000000, 0), (3000000, 0), 100000, net="A")
        board = FakeBoard(tracks=(source, empty))
        checks = LocalChecks(
            {},
            board,
            backend=NonConnectableBackend(board),
            rules=rules_for_profile("standard"),
        )
        indexed_source = next(
            item
            for item in checks.index.items_by_net["A"]
            if item.item.m_Uuid.AsString() == "source"
        )

        self.assertEqual(
            {"source", "empty"},
            {item.item.m_Uuid.AsString() for item in checks.index.items_by_net["A"]},
        )
        self.assertEqual(
            {"source"},
            {item.item.m_Uuid.AsString() for item in checks.index.connectable_items_by_net["A"]},
        )
        self.assertEqual(
            {"source"},
            {item.item.m_Uuid.AsString() for item in checks._connection_candidates(indexed_source)},
        )

    def test_dangling_track_endpoint_candidates_ignore_long_track_middle_items(self):
        source = FakeTrack("source", (0, 0), (10000000, 0), 100000, net="A")
        start_pad = FakePad("start", (0, 0), (300000, 300000), net="A")
        end_pad = FakePad("end", (10000000, 0), (300000, 300000), net="A")
        middle_pads = tuple(
            FakePad(
                "middle%s" % index,
                (1000000 + index * 250000, 1000000),
                (100000, 100000),
                net="A",
            )
            for index in range(30)
        )
        original_point_touches_item = LocalChecks._point_touches_item
        calls = []

        def counted_point_touches_item(checks, point, radius_nm, indexed):
            calls.append(indexed.item.m_Uuid.AsString())
            return original_point_touches_item(checks, point, radius_nm, indexed)

        with mock.patch.object(LocalChecks, "_point_touches_item", counted_point_touches_item):
            result = self.analyze(FakeBoard(tracks=(source,), pads=(start_pad, end_pad) + middle_pads), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Dangling Tracks", [row["item"] for row in rows])
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])
        self.assertIn("start", calls)
        self.assertIn("end", calls)
        self.assertFalse(any(item.startswith("middle") for item in calls))

    def test_signal_integrity_accepts_connected_same_net(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 100000, net="A")
        right = FakeTrack("t2", (1000000, 0), (2000000, 0), 100000, net="A")
        result = self.analyze(FakeBoard(tracks=(left, right)), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])

    def test_signal_integrity_accepts_same_net_copper_touching_by_width(self):
        left = FakeTrack("t1", (0, 0), (1000000, 0), 200000, net="A")
        right = FakeTrack("t2", (1200000, 0), (2200000, 0), 200000, net="A")
        pads = (
            FakePad("p1", (0, 0), (500000, 500000), net="A"),
            FakePad("p2", (2200000, 0), (500000, 500000), net="A"),
        )
        result = self.analyze(FakeBoard(tracks=(left, right), pads=pads), "standard")

        rows = rows_for(result, "Signal Integrity")
        self.assertNotIn("Trace Mssing", [row["item"] for row in rows])
        self.assertNotIn("Dangling Tracks", [row["item"] for row in rows])

    def test_board_statistics_show_computed_values_instead_of_normal(self):
        outline = (
            FakeDrawing((0, 0), (100000000, 0)),
            FakeDrawing((100000000, 0), (100000000, 100000000)),
            FakeDrawing((100000000, 100000000), (0, 100000000)),
            FakeDrawing((0, 100000000), (0, 0)),
        )
        pads = (
            FakePad(
                "pth",
                (10000000, 10000000),
                (2000000, 2000000),
                drill=(1000000, 1000000),
                net="A",
                attribute=0,
            ),
            FakePad(
                "smd",
                (20000000, 10000000),
                (2000000, 1000000),
                net="B",
                attribute=1,
            ),
        )
        via = FakeVia(
            "via",
            (30000000, 10000000),
            1000000,
            500000,
            net="C",
        )
        board = FakeBoard(tracks=(via,), pads=pads, drawings=outline)

        chinese = self.analyze(board, "standard", language=Language_chinese)
        english = self.analyze(board, "standard", language=Language_english)

        self.assertEqual("0.02万/m²", chinese.kicad_result["Drill Hole Density"]["display"])
        self.assertEqual("200/m²", english.kicad_result["Drill Hole Density"]["display"])
        self.assertEqual("3", chinese.kicad_result["Test Point Count"]["display"])
        self.assertRegex(chinese.kicad_result["Surface Finish Area"]["display"], r"^\d+\.\d{2}%$")
        for category in ("Drill Hole Density", "Surface Finish Area", "Test Point Count"):
            self.assertNotEqual("正常", chinese.kicad_result[category]["display"])

    def analyze(self, board, profile, include_passed_details=False, language=None):
        return OfflineDfmAnalysis(
            board,
            language or {},
            backend=FakeBackend(board),
            rules=rules_for_profile(profile),
            include_passed_details=include_passed_details,
        ).analyze()


def first_row(result, category):
    return rows_for(result, category)[0]


def rows_for(result, category):
    data = result.kicad_result[category]
    return [row for check in data.get("check") or [] for row in check.get("result") or []]


def rows_for_category_result(data):
    return [row for check in data.get("check") or [] for row in check.get("result") or []]


def category_color(result, category):
    return result.kicad_result[category]["color"]


def analysis_first_row(result, category):
    data = result.analysis_result[category]
    return [row for check in data.get("check") or [] for row in check.get("result") or []][0]


if __name__ == "__main__":
    unittest.main()
