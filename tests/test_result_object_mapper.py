import unittest

from kicad_dfm.services.result_object_mapper import GerberResultObjectMapper


class FakePoint:
    def __init__(self, x, y):
        self.x = x
        self.y = y


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


class FakeTrack:
    def __init__(self, item_id, start, end, width=100000, layer="F.Cu", net=""):
        self.item_id = item_id
        self.start = FakePoint(*start)
        self.end = FakePoint(*end)
        self.width = width
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

    def GetNetname(self):
        return self.net

    def GetBoundingBox(self):
        return FakeBox(
            min(self.start.x, self.end.x) - self.width // 2,
            min(self.start.y, self.end.y) - self.width // 2,
            max(self.start.x, self.end.x) + self.width // 2,
            max(self.start.y, self.end.y) + self.width // 2,
        )


class FakePad:
    def __init__(
        self,
        item_id,
        center,
        size=(1000000, 1000000),
        drill=(0, 0),
        layer="F.Cu",
        attribute=1,
        copper_layers=(),
        reference="U1",
        number="1",
        net="",
    ):
        self.item_id = item_id
        self.center = FakePoint(*center)
        self.size = size
        self.drill = drill
        self.layer = layer
        self.attribute = attribute
        self.copper_layers = tuple(copper_layers)
        self.reference = reference
        self.number = number
        self.net = net

    def GetPosition(self):
        return self.center

    def GetWidth(self):
        return max(self.size)

    def GetLayerName(self):
        return self.layer

    def GetDrillSizeX(self):
        return self.drill[0]

    def GetDrillSizeY(self):
        return self.drill[1]

    def GetAttribute(self):
        return self.attribute

    def GetNumber(self):
        return self.number

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


class FakeZone:
    def __init__(self, item_id, bbox, polygons, layer="F.Cu", net="GND"):
        self.item_id = item_id
        self.bbox = tuple(bbox)
        self.polygons = tuple(polygons)
        self.layer = layer
        self.net = net
        self.copper_layers = (0,)

    def GetLayerName(self):
        return self.layer

    def GetNetname(self):
        return self.net

    def GetWidth(self):
        return 0

    def GetBoundingBox(self):
        return FakeBox(*self.bbox)


class FakeFootprint:
    def __init__(self, reference, pads):
        self._reference = reference
        self._pads = tuple(pads)

    def GetReference(self):
        return self._reference

    def Pads(self):
        return self._pads


class FakeBackend:
    def __init__(self, tracks=(), vias=(), pads=(), zones=()):
        self.tracks = tuple(tracks)
        self.vias = tuple(vias)
        self.pads = tuple(pads)
        self.zones = tuple(zones)
        self.iter_tracks_calls = 0
        self.track_segment_calls = 0
        self.item_width_calls = 0
        self.item_bbox_calls = 0
        self.item_position_calls = 0

    def iter_tracks(self):
        self.iter_tracks_calls += 1
        return iter(self.tracks)

    def iter_vias(self):
        return iter(self.vias)

    def iter_footprints(self):
        by_reference = {}
        for pad in self.pads:
            by_reference.setdefault(pad.reference, []).append(pad)
        return iter(
            FakeFootprint(reference, pads)
            for reference, pads in by_reference.items()
        )

    def iter_pads(self, footprint):
        return iter(footprint.Pads())

    def iter_drawings(self):
        return iter(())

    def iter_zones(self):
        return iter(self.zones)

    def is_pad(self, item):
        return isinstance(item, FakePad)

    def is_via(self, item):
        return item in self.vias

    def is_npth_pad(self, item):
        return isinstance(item, FakePad) and item.GetAttribute() == 3

    def item_id(self, item):
        return item.item_id

    def item_layer_name(self, item):
        return item.GetLayerName()

    def item_width(self, item):
        self.item_width_calls += 1
        return item.GetWidth()

    def item_bbox(self, item):
        self.item_bbox_calls += 1
        box = item.GetBoundingBox()
        return box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom()

    def item_position(self, item):
        self.item_position_calls += 1
        if hasattr(item, "GetPosition"):
            point = item.GetPosition()
            return point.x, point.y
        box = self.item_bbox(item)
        return int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2)

    def item_net_name(self, item):
        return item.GetNetname() if hasattr(item, "GetNetname") else ""

    def item_copper_layer_ids(self, item):
        return tuple(getattr(item, "copper_layers", ()))

    def track_segment(self, item):
        if not hasattr(item, "GetStart") or not hasattr(item, "GetEnd"):
            return None
        self.track_segment_calls += 1
        return (item.GetStart().x, item.GetStart().y), (item.GetEnd().x, item.GetEnd().y)

    def pad_drill_mm(self, pad):
        return pad.GetDrillSizeX() / 1000000.0, pad.GetDrillSizeY() / 1000000.0

    def layer_constant(self, name):
        constants = {"F_Cu": 0, "B_Cu": 31}
        if name.startswith("In") and name.endswith("_Cu"):
            return int(name[2:-3])
        return constants[name]

    def layer_name(self, layer_id):
        return {0: "F.Cu", 1: "L2 (PWR)", 31: "B.Cu"}.get(layer_id, "")

    def item_type(self, item):
        return type(item).__name__

    def zone_polygons(self, zone, _layer_id=None):
        return zone.polygons


class GerberResultObjectMapperTest(unittest.TestCase):
    def test_flash_mapping_prefers_pad_center_over_flash_diameter_segment(self):
        exact = FakePad("exact-pad", (1000000, 1000000), size=(200000, 200000))
        overlapping = FakePad(
            "overlapping-pad", (1200000, 1000000), size=(400000, 200000)
        )
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {
                "kind": "circle",
                "is_flash": True,
                "point": (1.0, 1.0),
                "segment": ((0.9, 1.0), (1.1, 1.0)),
                "bbox": (0.9, 0.9, 1.1, 1.1),
                "width": 0.2,
            },
        }

        result = GerberResultObjectMapper(
            None, FakeBackend(pads=(exact, overlapping))
        ).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("exact-pad", row["id"])

    def test_apply_mapping_fills_uuid_for_unique_segment_match(self):
        track = FakeTrack("track-uuid", (1000000, 1000000), (9000000, 1000000))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "confidence": 0.65,
            "geometry_basis": "gerber_derived",
            "raw": {"segment": ((1.0, 1.0), (9.0, 1.0)), "file": "board-CuTop.gbr"},
        }

        result = GerberResultObjectMapper(None, FakeBackend((track,))).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("track-uuid", row["id"])
        self.assertEqual("hit_test", row["geometry_basis"])
        self.assertGreaterEqual(row["confidence"], 0.9)
        self.assertEqual("track-uuid", row["raw"]["uuid_mapping"]["id"])

    def test_apply_mapping_uses_primary_and_related_raw(self):
        primary = FakeTrack("primary-uuid", (1000000, 1000000), (9000000, 1000000))
        related = FakeTrack("related-uuid", (1000000, 2000000), (9000000, 2000000))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "confidence": 0.65,
            "geometry_basis": "gerber_derived",
            "raw": {
                "segment": ((1.0, 1.5), (9.0, 1.5)),
                "primary": {
                    "file": "board-CuTop.gbr",
                    "item_type": "gerber",
                    "layer": ["F.Cu"],
                    "segment": ((1.0, 1.0), (9.0, 1.0)),
                },
                "related": {
                    "file": "board-CuTop.gbr",
                    "item_type": "gerber",
                    "layer": ["F.Cu"],
                    "segment": ((1.0, 2.0), (9.0, 2.0)),
                },
            },
        }

        result = GerberResultObjectMapper(None, FakeBackend((primary, related))).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("primary-uuid", row["id"])
        self.assertEqual("related-uuid", row["related_id"])
        self.assertEqual("related-uuid", row["raw"]["uuid_mapping"]["related"]["id"])
        self.assertEqual("matched", row["raw"]["uuid_mapping"]["related"]["status"])

    def test_apply_mapping_does_not_reuse_primary_uuid_for_legacy_related_raw(self):
        primary = FakeTrack("primary-uuid", (1000000, 1000000), (9000000, 1000000))
        related = FakeTrack("related-uuid", (1000000, 2000000), (9000000, 2000000))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {
                "primary": {
                    "file": "board-CuTop.gbr",
                    "item_type": "gerber",
                    "layer": ["F.Cu"],
                    "segment": ((1.0, 1.0), (9.0, 1.0)),
                },
                "related_segment": ((1.0, 2.0), (9.0, 2.0)),
                "related_layer": ["F.Cu"],
                "related_item_type": "gerber",
            },
        }

        result = GerberResultObjectMapper(None, FakeBackend((primary, related))).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("primary-uuid", row["id"])
        self.assertEqual("related-uuid", row["related_id"])
        self.assertEqual("related-uuid", row["raw"]["uuid_mapping"]["related"]["id"])

    def test_apply_mapping_marks_ambiguous_without_replacing_id(self):
        tracks = (
            FakeTrack("a", (1000000, 1000000), (9000000, 1000000)),
            FakeTrack("b", (1000000, 1050000), (9000000, 1050000)),
        )
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {"segment": ((1.0, 1.025), (9.0, 1.025))},
        }

        result = GerberResultObjectMapper(None, FakeBackend(tracks)).apply_mapping(row)

        self.assertEqual("ambiguous", result.status)
        self.assertEqual("board-CuTop.gbr", row["id"])
        self.assertEqual("ambiguous", row["raw"]["uuid_mapping"]["status"])

    def test_mapper_prefers_matching_endpoints_over_crossing_track(self):
        crossing = FakeTrack("crossing", (5000000, 0), (5000000, 2000000))
        exact = FakeTrack("exact", (1000000, 1000000), (9000000, 1000000))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {"segment": ((1.0, 1.0), (9.0, 1.0)), "width": 0.1},
        }

        result = GerberResultObjectMapper(None, FakeBackend((crossing, exact))).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("segment_endpoints", result.reason)
        self.assertEqual("exact", row["id"])

    def test_mapper_filters_segment_candidates_by_x2_net(self):
        no_net = FakeTrack("no-net", (1000000, 1000000), (9000000, 1000000))
        wrong_net = FakeTrack("wrong", (1000000, 1000000), (9000000, 1000000), net="GND")
        right_net = FakeTrack("right", (1000000, 1000000), (9000000, 1000000), net="VCC")
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {"segment": ((1.0, 1.0), (9.0, 1.0)), "net": "VCC"},
        }

        result = GerberResultObjectMapper(None, FakeBackend((no_net, wrong_net, right_net))).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("right", row["id"])

    def test_apply_mapping_skips_rows_without_geometry(self):
        row = {"id": "board-CuTop.gbr", "source": "gerber", "raw": {}}

        result = GerberResultObjectMapper(None, FakeBackend()).apply_mapping(row)

        self.assertEqual("skipped", result.status)
        self.assertEqual("missing_geometry", row["raw"]["uuid_mapping"]["reason"])

    def test_mapper_reuses_candidate_cache_for_multiple_rows(self):
        tracks = tuple(
            FakeTrack(
                "track-%s" % index,
                (1000000, 1000000 + index * 1000000),
                (9000000, 1000000 + index * 1000000),
            )
            for index in range(3)
        )
        backend = FakeBackend(tracks)
        mapper = GerberResultObjectMapper(None, backend)
        rows = [
            {
                "id": "board-CuTop.gbr",
                "source": "gerber",
                "item_type": "gerber",
                "layer": ["F.Cu"],
                "raw": {"segment": ((1.0, 1.0 + index), (9.0, 1.0 + index))},
            }
            for index in range(3)
        ]

        results = [mapper.apply_mapping(row) for row in rows]

        self.assertEqual(["matched", "matched", "matched"], [result.status for result in results])
        self.assertEqual(1, backend.iter_tracks_calls)

    def test_mapper_reuses_cached_candidate_width_for_multiple_rows(self):
        track = FakeTrack("track-uuid", (1000000, 1000000), (9000000, 1000000), width=300000)
        backend = FakeBackend((track,))
        mapper = GerberResultObjectMapper(None, backend)
        rows = [
            {
                "id": "board-CuTop.gbr",
                "source": "gerber",
                "item_type": "gerber",
                "layer": ["F.Cu"],
                "raw": {"segment": ((1.0, 1.0), (9.0, 1.0))},
            }
            for _index in range(3)
        ]

        results = [mapper.apply_mapping(row) for row in rows]

        self.assertEqual(["matched", "matched", "matched"], [result.status for result in results])
        self.assertEqual(1, backend.item_width_calls)

    def test_mapper_skips_item_position_for_segment_rows(self):
        track = FakeTrack("track-uuid", (1000000, 1000000), (9000000, 1000000))
        backend = FakeBackend((track,))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {"segment": ((1.0, 1.0), (9.0, 1.0))},
        }

        result = GerberResultObjectMapper(None, backend).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual(0, backend.item_position_calls)

    def test_mapper_filters_cached_candidates_by_layer_before_scoring(self):
        front = FakeTrack("front", (1000000, 1000000), (9000000, 1000000), layer="F.Cu")
        back = FakeTrack("back", (1000000, 1000000), (9000000, 1000000), layer="B.Cu")
        backend = FakeBackend((front, back))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {"segment": ((1.0, 1.0), (9.0, 1.0))},
        }

        result = GerberResultObjectMapper(None, backend).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("front", row["id"])
        self.assertEqual(1, backend.track_segment_calls)

    def test_mapper_resolves_gerber_inner_layer_to_custom_board_layer_name(self):
        inner = FakeTrack(
            "inner", (1000000, 1000000), (9000000, 1000000), layer="L2 (PWR)"
        )
        row = {
            "id": "board-In1_Cu.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["In1.Cu"],
            "raw": {"segment": ((1.0, 1.0), (9.0, 1.0))},
        }

        result = GerberResultObjectMapper(None, FakeBackend((inner,))).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("inner", row["id"])

    def test_mapper_indexes_multilayer_pad_on_inner_copper_layers(self):
        pad = FakePad(
            "pth-pad",
            (1000000, 1000000),
            drill=(400000, 400000),
            copper_layers=(0, 1, 31),
        )
        row = {
            "id": "board-In1_Cu.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["In1.Cu"],
            "raw": {
                "kind": "circle",
                "is_flash": True,
                "point": (1.0, 1.0),
                "bbox": (0.5, 0.5, 1.5, 1.5),
                "width": 1.0,
            },
        }

        result = GerberResultObjectMapper(
            None, FakeBackend(pads=(pad,))
        ).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("pth-pad", row["id"])

    def test_mapper_uses_filled_zone_bbox_instead_of_overlapping_item_bbox(self):
        wanted_outer = (
            (1000000, 1000000),
            (3000000, 1000000),
            (3000000, 3000000),
            (1000000, 3000000),
        )
        decoy_outer = (
            (1200000, 1200000),
            (3200000, 1200000),
            (3200000, 3200000),
            (1200000, 3200000),
        )
        # Both editable zone bboxes overlap the Gerber region.  Only the first
        # filled outer contour has the same four boundaries as the export.
        wanted = FakeZone(
            "wanted-zone",
            (0, 0, 5000000, 5000000),
            ((wanted_outer, ()),),
        )
        decoy = FakeZone(
            "decoy-zone",
            (0, 0, 5000000, 5000000),
            ((decoy_outer, ()),),
        )
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {
                "kind": "region",
                "aperture_function": "Conductor",
                "net": "GND",
                "bbox": (1.004, 1.0, 3.004, 3.0),
            },
        }

        result = GerberResultObjectMapper(
            None, FakeBackend(zones=(wanted, decoy))
        ).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("zone_filled_bbox", result.reason)
        self.assertEqual("wanted-zone", row["id"])

    def test_mapper_keeps_identical_filled_zone_bboxes_ambiguous(self):
        outer = (
            (1000000, 1000000),
            (3000000, 1000000),
            (3000000, 3000000),
            (1000000, 3000000),
        )
        zones = (
            FakeZone("zone-a", (0, 0, 5000000, 5000000), ((outer, ()),)),
            FakeZone("zone-b", (0, 0, 5000000, 5000000), ((outer, ()),)),
        )
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {
                "kind": "region",
                "aperture_function": "Conductor",
                "net": "GND",
                "bbox": (1.0, 1.0, 3.0, 3.0),
            },
        }

        result = GerberResultObjectMapper(
            None, FakeBackend(zones=zones)
        ).apply_mapping(row)

        self.assertEqual("ambiguous", result.status)
        self.assertEqual("board-CuTop.gbr", row["id"])

    def test_mapper_does_not_map_custom_pad_region_to_zone(self):
        outer = (
            (1000000, 1000000),
            (3000000, 1000000),
            (3000000, 3000000),
            (1000000, 3000000),
        )
        zone = FakeZone("zone-a", (0, 0, 5000000, 5000000), ((outer, ()),))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {
                "kind": "region",
                "aperture_function": "ComponentPad",
                "net": "GND",
                "bbox": (1.0, 1.0, 3.0, 3.0),
            },
        }

        result = GerberResultObjectMapper(
            None, FakeBackend(zones=(zone,))
        ).apply_mapping(row)

        self.assertEqual("skipped", result.status)
        self.assertEqual("board-CuTop.gbr", row["id"])

    def test_mapper_uses_region_bbox_to_resolve_duplicate_x2_pad_shape(self):
        wanted = FakePad(
            "wanted-shape",
            (2000000, 2000000),
            size=(2000000, 4000000),
            reference="NT12",
            number="1",
            net="SC_N",
        )
        other_shape = FakePad(
            "other-shape",
            (4500000, 2000000),
            size=(200000, 200000),
            reference="NT12",
            number="1",
            net="SC_N",
        )
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {
                "kind": "region",
                "aperture_function": "ComponentPad",
                "component": "NT12",
                "object_id": "NT12,1,1",
                "net": "SC_N",
                "bbox": (1.0, 0.0, 3.0, 4.0),
            },
        }

        result = GerberResultObjectMapper(
            None, FakeBackend(pads=(wanted, other_shape))
        ).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("x2_component_pad_geometry", result.reason)
        self.assertEqual("wanted-shape", row["id"])

    def test_mapper_keeps_near_duplicate_x2_pad_shapes_ambiguous(self):
        exact = FakePad(
            "exact-shape",
            (2000000, 2000000),
            size=(2000000, 4000000),
            reference="NT12",
            number="1",
            net="SC_N",
        )
        near = FakePad(
            "near-shape",
            (2005000, 2000000),
            size=(2000000, 4000000),
            reference="NT12",
            number="1",
            net="SC_N",
        )
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {
                "kind": "region",
                "aperture_function": "ComponentPad",
                "component": "NT12",
                "object_id": "NT12,1,1",
                "net": "SC_N",
                "bbox": (1.0, 0.0, 3.0, 4.0),
            },
        }

        result = GerberResultObjectMapper(
            None, FakeBackend(pads=(exact, near))
        ).apply_mapping(row)

        self.assertEqual("ambiguous", result.status)
        self.assertEqual("x2_component_pad_geometry_ambiguous", result.reason)
        self.assertEqual("board-CuTop.gbr", row["id"])

    def test_mapper_rejects_duplicate_x2_pads_with_wrong_net_or_layer(self):
        wrong_net = FakePad(
            "wrong-net",
            (2000000, 2000000),
            size=(2000000, 4000000),
            reference="NT12",
            number="1",
            net="GND",
        )
        wrong_layer = FakePad(
            "wrong-layer",
            (2000000, 2000000),
            size=(2000000, 4000000),
            layer="B.Cu",
            reference="NT12",
            number="1",
            net="SC_N",
        )
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {
                "kind": "region",
                "aperture_function": "ComponentPad",
                "component": "NT12",
                "object_id": "NT12,1,1",
                "net": "SC_N",
                "bbox": (1.0, 0.0, 3.0, 4.0),
            },
        }

        result = GerberResultObjectMapper(
            None, FakeBackend(pads=(wrong_net, wrong_layer))
        ).apply_mapping(row)

        self.assertEqual("skipped", result.status)
        self.assertEqual("x2_component_pad_constraints_mismatch", result.reason)
        self.assertEqual("board-CuTop.gbr", row["id"])

    def test_mapper_prunes_far_same_layer_candidates_before_scoring(self):
        near = FakeTrack("near", (1000000, 1000000), (9000000, 1000000), layer="F.Cu")
        far_tracks = tuple(
            FakeTrack(
                "far-%s" % index,
                (100000000 + index * 10000000, 1000000),
                (101000000 + index * 10000000, 1000000),
                layer="F.Cu",
            )
            for index in range(20)
        )
        backend = FakeBackend((near,) + far_tracks)
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {"segment": ((1.0, 1.0), (9.0, 1.0))},
        }

        result = GerberResultObjectMapper(None, backend).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("near", row["id"])
        self.assertLess(backend.track_segment_calls, len(far_tracks) // 4)

    def test_mapper_treats_drl_as_all_drill_layers(self):
        drill = FakeTrack("pth", (1000000, 1000000), (1000000, 1000000), width=400000, layer="F.Cu")
        backend = FakeBackend(vias=(drill,))
        row = {
            "id": "board.drl",
            "source": "drill",
            "item_type": "drill",
            "layer": ["Drl"],
            "raw": {"point": (1.0, 1.0), "diameter": 0.4},
        }

        result = GerberResultObjectMapper(None, backend).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("pth", row["id"])
        self.assertEqual("pth", row["raw"]["uuid_mapping"]["id"])

    def test_mapper_skips_pad_without_drill_for_drill_rows(self):
        pad = FakePad("smd-pad", (1000000, 1000000), drill=(0, 0))
        backend = FakeBackend(pads=(pad,))
        row = {
            "id": "board.drl",
            "source": "drill",
            "item_type": "drill",
            "layer": ["Drl"],
            "raw": {"point": (1.0, 1.0), "diameter": 0.4},
        }

        result = GerberResultObjectMapper(None, backend).apply_mapping(row)

        self.assertEqual("skipped", result.status)
        self.assertEqual("no_candidate", row["raw"]["uuid_mapping"]["reason"])

    def test_mapper_skips_npth_pad_for_gerber_rows(self):
        npth = FakePad("npth-pad", (1000000, 1000000), drill=(400000, 400000), attribute=3)
        backend = FakeBackend(pads=(npth,))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "layer": ["F.Cu"],
            "raw": {"point": (1.0, 1.0)},
        }

        result = GerberResultObjectMapper(None, backend).apply_mapping(row)

        self.assertEqual("skipped", result.status)
        self.assertEqual("no_candidate", row["raw"]["uuid_mapping"]["reason"])

    def test_mapper_deduplicates_same_via_from_tracks_and_vias(self):
        via = FakeTrack("via-uuid", (1000000, 1000000), (1000000, 1000000), width=400000, layer="F.Cu")
        backend = FakeBackend(tracks=(via,), vias=(via,))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "raw": {"point": (1.0, 1.0)},
        }

        result = GerberResultObjectMapper(None, backend).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual("via-uuid", row["id"])

    def test_mapper_deduplicates_before_reading_candidate_geometry(self):
        via = FakeTrack("via-uuid", (1000000, 1000000), (1000000, 1000000), width=400000, layer="F.Cu")
        backend = FakeBackend(tracks=(via,), vias=(via,))
        row = {
            "id": "board-CuTop.gbr",
            "source": "gerber",
            "raw": {"point": (1.0, 1.0)},
        }

        result = GerberResultObjectMapper(None, backend).apply_mapping(row)

        self.assertEqual("matched", result.status)
        self.assertEqual(1, backend.item_width_calls)
        self.assertEqual(1, backend.item_bbox_calls)


if __name__ == "__main__":
    unittest.main()
