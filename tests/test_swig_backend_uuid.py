import unittest
import sys
import types

from kicad_dfm.kicad.swig import SwigBackend


class FakeUuid:
    def __init__(self, value):
        self.value = value

    def AsString(self):
        return self.value

    def __str__(self):
        return "<Swig Object proxy>"


class FakeItem:
    def __init__(self, value, pads=()):
        self.m_Uuid = FakeUuid(value)
        self._pads = pads

    def Pads(self):
        return self._pads


class FakeConnectedItem(FakeItem):
    def __init__(self, value, layers=()):
        super().__init__(value)
        self.layers = set(layers)

    def IsOnLayer(self, layer_id):
        return layer_id in self.layers


class FakeSelectableItem:
    def __init__(self):
        self.selected = False

    def SetSelected(self, value=True):
        self.selected = value

    def GetLayer(self):
        return 0


class FakePadWithoutGetWidth:
    def __init__(self, size=(800000, 400000)):
        self.size = size

    def GetSizeX(self):
        return self.size[0]

    def GetSizeY(self):
        return self.size[1]


class FakeVectorSize:
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


class FakeCustomPad(FakePadWithoutGetWidth):
    def GetAttribute(self):
        return 1

    def GetShape(self):
        return 6

    def GetBoundingBox(self):
        return FakeBox(0, 0, 1500000, 1200000)


class FakePadWithGetSizeOnly:
    def __init__(self, size=(800000, 400000)):
        self.size = size

    def GetSize(self):
        return FakeVectorSize(*self.size)


class FakeLayerPad(FakePadWithoutGetWidth):
    def __init__(self, layers, reported_layer=0):
        super().__init__()
        self.layers = set(layers)
        self.reported_layer = reported_layer

    def IsOnLayer(self, layer_id):
        return layer_id in self.layers

    def GetLayer(self):
        return self.reported_layer


class FakeLayerItem:
    def __init__(self, layer_id, reported_name):
        self.layer_id = layer_id
        self.reported_name = reported_name

    def GetLayer(self):
        return self.layer_id

    def GetLayerName(self):
        return self.reported_name


class FakeViaType:
    def __init__(self, via_type, top=0, bottom=2):
        self.via_type = via_type
        self.top = top
        self.bottom = bottom

    def GetViaType(self):
        return self.via_type

    def TopLayer(self):
        return self.top

    def BottomLayer(self):
        return self.bottom


class FakeCollisionShape:
    def __init__(self, width, collision_width):
        self.width = int(width)
        self.collision_width = int(collision_width)

    def Collide(self, other, _clearance):
        return self.width >= other.collision_width

    def GetWidth(self):
        return self.width

    def Clone(self):
        return FakeCollisionShape(self.width, self.collision_width)

    def SetWidth(self, width):
        self.width = int(width)

    def GetStart(self):
        return (0, 0)

    def GetEnd(self):
        return (0, 0)


class FakeHoleWithEffectiveShape:
    def __init__(self, width, collision_width):
        self.shape = FakeCollisionShape(width, collision_width)

    def GetEffectiveHoleShape(self):
        return self.shape


class FakePadEffectiveShape:
    def __init__(self, collision_width):
        self.collision_width = int(collision_width)
        self.layers = []

    def GetEffectiveShape(self, layer_id):
        self.layers.append(layer_id)
        return self

    def PointInside(self, _point, _accuracy=0):
        return self.collision_width <= 0


class FakeBoard:
    def __init__(
        self,
        tracks=(),
        footprints=(),
        resolved=None,
        layer_names=None,
        standard_layer_names=None,
    ):
        self._tracks = tracks
        self._footprints = footprints
        self.resolved = resolved
        self.layer_names = layer_names or {}
        self.standard_layer_names = standard_layer_names
        self.track_scan_count = 0

    def GetTracks(self):
        self.track_scan_count += 1
        return self._tracks

    def GetFootprints(self):
        return self._footprints

    def Zones(self):
        return ()

    def GetDrawings(self):
        return ()

    def ResolveItem(self, item_id):
        return self.resolved

    def GetLayerName(self, layer_id):
        return self.layer_names.get(layer_id, str(layer_id))

    def GetStandardLayerName(self, layer_id):
        if self.standard_layer_names is None:
            raise AttributeError("standard layer names unavailable")
        return self.standard_layer_names.get(layer_id, str(layer_id))


class SwigBackendUuidTest(unittest.TestCase):
    def install_fake_focus_module(self, focus_on_item=None):
        original_pcbnew = sys.modules.get("pcbnew")
        attrs = {}
        if focus_on_item is not None:
            attrs["FocusOnItem"] = focus_on_item
        sys.modules["pcbnew"] = types.SimpleNamespace(**attrs)
        return original_pcbnew

    def restore_focus_module(self, original_pcbnew):
        if original_pcbnew is None:
            sys.modules.pop("pcbnew", None)
        else:
            sys.modules["pcbnew"] = original_pcbnew

    def test_item_id_uses_uuid_as_string(self):
        backend = SwigBackend(FakeBoard())

        self.assertEqual("abc-123", backend.item_id(FakeItem("abc-123")))

    def test_hole_pad_overlap_uses_effective_shape_and_requested_layer(self):
        backend = SwigBackend(FakeBoard())
        hole = FakeHoleWithEffectiveShape(400000, 150000)
        pad = FakePadEffectiveShape(150000)

        overlap = backend.hole_pad_overlap_nm(hole, pad, pad_layer_id=31)

        self.assertEqual(125000, overlap)
        self.assertEqual([31], pad.layers)

    def test_item_to_segment_clearance_uses_effective_shape(self):
        class EffectiveItem:
            def __init__(self):
                self.layers = []

            def GetEffectiveShape(self, layer_id):
                self.layers.append(layer_id)
                return self

            def Collide(self, _other, clearance):
                return int(clearance) >= 137

        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(
            VECTOR2I=lambda x, y: (x, y),
            SHAPE_SEGMENT=lambda start, end, width: (start, end, width),
        )
        try:
            item = EffectiveItem()
            clearance = SwigBackend(FakeBoard()).item_to_segment_clearance_nm(
                item,
                ((0, 0), (1000, 0)),
                layer_id=31,
                max_distance_nm=1000,
            )
        finally:
            self.restore_focus_module(original_pcbnew)

        self.assertEqual(137, clearance)
        self.assertEqual([31], item.layers)

    def test_shape_clearance_uses_exact_distance_with_collision_correction(self):
        class ExactShape:
            def __init__(self, collision_threshold, reported_clearance):
                self.collision_threshold = collision_threshold
                self.reported_clearance = reported_clearance
                self.collide_calls = []

            def Collide(self, _other, clearance):
                self.collide_calls.append(int(clearance))
                return int(clearance) >= self.collision_threshold

            def GetClearance(self, _other):
                return self.reported_clearance

        shape = ExactShape(138, 137)
        clearance = SwigBackend(FakeBoard())._shape_clearance_nm(
            shape,
            object(),
            1000,
        )

        self.assertEqual(138, clearance)
        self.assertEqual([0, 1000, 137, 138], shape.collide_calls)

    def test_shape_clearance_falls_back_when_exact_distance_is_unsupported(self):
        class LegacyShape:
            def __init__(self, exception_type):
                self.exception_type = exception_type

            def Collide(self, _other, clearance):
                return int(clearance) >= 137

            def GetClearance(self, _other):
                raise self.exception_type("unsupported shape pair")

        for exception_type in (TypeError, RuntimeError):
            with self.subTest(exception_type=exception_type.__name__):
                clearance = SwigBackend(FakeBoard())._shape_clearance_nm(
                    LegacyShape(exception_type),
                    object(),
                    1000,
                )

                self.assertEqual(137, clearance)

    def test_board_outline_uses_closed_polygon_outlines_and_holes(self):
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class Chain:
            def __init__(self, points):
                self.points = tuple(Point(*point) for point in points)

            def PointCount(self):
                return len(self.points)

            def CPoint(self, index):
                return self.points[index]

        class PolySet:
            def __init__(self):
                self.outer = Chain(((0, 0), (10, 0), (10, 10), (0, 10)))
                self.hole = Chain(((3, 3), (3, 7), (7, 7), (7, 3)))

            def OutlineCount(self):
                return 1

            def COutline(self, index):
                self.assert_index(index)
                return self.outer

            def HoleCount(self, outline_index):
                self.assert_index(outline_index)
                return 1

            def CHole(self, outline_index, hole_index):
                self.assert_index(outline_index)
                self.assert_index(hole_index)
                return self.hole

            def assert_index(self, index):
                if index != 0:
                    raise IndexError(index)

        polyset = PolySet()
        board = FakeBoard()
        board.GetBoardPolygonOutlines = lambda target, *_args: target is polyset
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(
            SHAPE_POLY_SET=lambda: polyset,
        )
        try:
            outline = SwigBackend(board).board_outline_segments()
        finally:
            self.restore_focus_module(original_pcbnew)

        self.assertEqual(8, len(outline))
        self.assertIn(((0, 10), (0, 0)), outline)
        self.assertIn(((7, 3), (3, 3)), outline)

    def test_hole_axis_on_pad_rejects_edge_only_collision(self):
        backend = SwigBackend(FakeBoard())
        # The full hole and KiCad's degenerate zero-width collision both say
        # "colliding", but the actual drill centre is outside the pad.
        hole = FakeHoleWithEffectiveShape(400000, 0)
        pad = FakePadEffectiveShape(150000)

        self.assertFalse(backend.hole_axis_on_pad(hole, pad, pad_layer_id=0))

    def test_hole_axis_on_pad_accepts_centerline_collision(self):
        backend = SwigBackend(FakeBoard())
        hole = FakeHoleWithEffectiveShape(400000, 0)
        pad = FakePadEffectiveShape(0)

        self.assertTrue(backend.hole_axis_on_pad(hole, pad, pad_layer_id=31))

    def test_hole_pad_overlap_rejects_bbox_only_collision(self):
        backend = SwigBackend(FakeBoard())
        hole = FakeHoleWithEffectiveShape(400000, 500000)
        pad = FakePadEffectiveShape(500000)

        self.assertEqual(0, backend.hole_pad_overlap_nm(hole, pad, pad_layer_id=0))

    def test_resolve_item_scans_tracks_and_pads_by_uuid_text(self):
        track = FakeItem("track-id")
        pad = FakeItem("pad-id")
        footprint = FakeItem("footprint-id", pads=(pad,))
        backend = SwigBackend(FakeBoard(tracks=(track,), footprints=(footprint,)))

        self.assertIs(track, backend.resolve_item("track-id"))
        self.assertIs(pad, backend.resolve_item("pad-id"))

    def test_resolve_item_uses_board_resolve_before_scanning(self):
        item = FakeItem("direct-id")
        board = FakeBoard(resolved=item)
        backend = SwigBackend(board)

        self.assertIs(item, backend.resolve_item("direct-id"))
        self.assertEqual(0, board.track_scan_count)

    def test_focus_on_item_uses_native_api_only(self):
        focus_calls = []
        original_pcbnew = self.install_fake_focus_module(
            lambda item, layer=None: focus_calls.append((item, layer))
        )
        try:
            backend = SwigBackend(FakeBoard())
            item = FakeSelectableItem()

            self.assertTrue(backend.focus_on_item(item))

            self.assertEqual([(item, None)], focus_calls)
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_focus_on_item_uses_explicit_layer_when_given(self):
        focus_calls = []
        original_pcbnew = self.install_fake_focus_module(
            lambda item, layer=None: focus_calls.append((item, layer))
        )
        try:
            backend = SwigBackend(FakeBoard())

            self.assertTrue(backend.focus_on_item(FakeSelectableItem(), layer_id=3))

            self.assertEqual([(focus_calls[0][0], 3)], focus_calls)
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_focus_on_item_falls_back_between_native_signatures_only(self):
        focus_calls = []

        def focus_on_item(*args):
            focus_calls.append(args)
            if len(args) == 2:
                raise TypeError("old signature")
            return None

        original_pcbnew = self.install_fake_focus_module(
            focus_on_item
        )
        try:
            backend = SwigBackend(FakeBoard())
            item = FakeSelectableItem()

            self.assertTrue(backend.focus_on_item(item, layer_id=3))

            self.assertEqual([(item, 3), (item,)], focus_calls)
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_focus_on_item_returns_false_without_native_api(self):
        original_pcbnew = self.install_fake_focus_module()
        try:
            backend = SwigBackend(FakeBoard())

            self.assertFalse(backend.focus_on_item(FakeSelectableItem()))
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_item_width_uses_pad_size_when_pad_has_no_get_width(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(PAD=FakePadWithoutGetWidth)
        try:
            backend = SwigBackend(FakeBoard())

            self.assertEqual(400000, backend.item_width(FakePadWithoutGetWidth()))
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_item_width_uses_get_size_when_pad_has_no_get_width(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(PAD=FakePadWithGetSizeOnly)
        try:
            backend = SwigBackend(FakeBoard())

            self.assertEqual(400000, backend.item_width(FakePadWithGetSizeOnly()))
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_custom_pad_size_uses_effective_copper_bbox(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PAD=FakeCustomPad,
            PAD_SHAPE_CUSTOM=6,
        )
        try:
            backend = SwigBackend(FakeBoard())

            self.assertEqual((1.5, 1.2), backend.pad_size_mm(FakeCustomPad()))
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_item_width_uses_size_when_item_is_not_detected_as_pad(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(PAD=type("OtherPad", (), {}))
        try:
            backend = SwigBackend(FakeBoard())

            self.assertEqual(400000, backend.item_width(FakePadWithoutGetWidth()))
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_item_layer_id_uses_single_active_copper_layer_for_smd_pad(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PAD=FakeLayerPad,
            F_Cu=0,
            B_Cu=2,
        )
        try:
            backend = SwigBackend(FakeBoard())
            bottom_pad_reporting_front = FakeLayerPad((2,), reported_layer=0)

            self.assertEqual(2, backend.item_layer_id(bottom_pad_reporting_front))
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_item_layer_name_uses_corrected_smd_copper_layer(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PAD=FakeLayerPad,
            F_Cu=0,
            B_Cu=2,
        )
        try:
            backend = SwigBackend(
                FakeBoard(layer_names={0: "top_copper", 2: "bottom_copper"})
            )
            bottom_pad_reporting_front = FakeLayerPad((2,), reported_layer=0)

            self.assertEqual(
                "bottom_copper",
                backend.item_layer_name(bottom_pad_reporting_front),
            )
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_pad_copper_layers_distinguish_paste_only_from_unknown(self):
        board = FakeBoard()
        board.GetEnabledLayers = lambda: types.SimpleNamespace(
            CuStack=lambda: (0, 4, 2)
        )
        backend = SwigBackend(board)

        self.assertEqual((), backend.pad_copper_layer_ids(FakeLayerPad(())))
        self.assertEqual((2,), backend.pad_copper_layer_ids(FakeLayerPad((2,))))
        self.assertIsNone(
            SwigBackend(FakeBoard()).pad_copper_layer_ids(FakeLayerPad(()))
        )

    def test_net_tie_pad_groups_preserve_local_members_and_declared_groups(self):
        class NetPad:
            def __init__(self, item_id, net_name):
                self.m_Uuid = FakeUuid(item_id)
                self.net_name = net_name

            def GetNetname(self):
                return self.net_name

        class NetTieFootprint:
            def __init__(self):
                self.first = (NetPad("p-a", "A"), NetPad("p-b", "B"))
                self.second = (NetPad("p-c", "C"), NetPad("p-d", "D"))
                self.helper = NetPad("p-helper", "")
                self.pads = self.first + self.second + (self.helper,)

            def IsNetTie(self):
                return True

            def Pads(self):
                return self.pads

            def GetNetTiePads(self, pad):
                if pad in self.first:
                    return self.first
                if pad in self.second:
                    return self.second
                return ()

        class OrdinaryFootprint:
            def __init__(self):
                self.pads = (NetPad("ordinary", "E"),)

            def IsNetTie(self):
                return False

            def Pads(self):
                return self.pads

        backend = SwigBackend(
            FakeBoard(footprints=(NetTieFootprint(), OrdinaryFootprint()))
        )

        self.assertEqual(
            (
                (("p-a", "A"), ("p-b", "B")),
                (("p-c", "C"), ("p-d", "D")),
            ),
            backend.net_tie_pad_groups(),
        )
        self.assertEqual(
            frozenset(("p-a", "p-b", "p-c", "p-d", "p-helper")),
            backend.net_tie_footprint_pad_ids(),
        )
        self.assertEqual(
            (("A", "B"), ("C", "D")),
            backend.net_tie_net_groups(),
        )

    def test_item_layer_name_resolves_non_pad_through_board_layer_table(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PAD=type("OtherPad", (), {}),
        )
        try:
            backend = SwigBackend(
                FakeBoard(layer_names={4: "inner_copper"})
            )
            zone_reporting_front = FakeLayerItem(4, "top_copper")

            self.assertEqual(
                "inner_copper",
                backend.item_layer_name(zone_reporting_front),
            )
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_canonical_layer_name_ignores_user_stackup_alias(self):
        backend = SwigBackend(
            FakeBoard(
                layer_names={0: "L1 (Sig, PWR)"},
                standard_layer_names={0: "F.Cu"},
            )
        )

        self.assertEqual("F.Cu", backend.canonical_layer_name(0))
        self.assertEqual("L1 (Sig, PWR)", backend.layer_name(0))

    def test_item_copper_layers_follow_physical_stack_not_numeric_order(self):
        board = FakeBoard()
        board.GetEnabledLayers = lambda: types.SimpleNamespace(
            CuStack=lambda: (0, 4, 6, 8, 10, 2)
        )
        backend = SwigBackend(board)
        multilayer_item = FakeConnectedItem("zone", layers=(4, 10))

        self.assertEqual(
            (4, 10),
            backend.item_copper_layer_ids(multilayer_item),
        )

    def test_native_connectivity_helpers_are_cached_and_authoritative(self):
        item = FakeConnectedItem("via", layers=(0, 4, 6, 8, 10, 2))
        connected = FakeConnectedItem("zone", layers=(4, 10))

        class FakeConnectivity:
            def GetConnectedItems(self, candidate):
                return (connected,) if candidate is item else ()

            def IsConnectedOnLayer(self, candidate, layer_id):
                return candidate is item and layer_id in (4, 10)

        connectivity = FakeConnectivity()
        board = FakeBoard()
        board.build_count = 0
        board.GetEnabledLayers = lambda: types.SimpleNamespace(
            CuStack=lambda: (0, 4, 6, 8, 10, 2)
        )
        board.BuildConnectivity = lambda: setattr(
            board,
            "build_count",
            board.build_count + 1,
        )
        board.GetConnectivity = lambda: connectivity
        backend = SwigBackend(board)

        self.assertEqual(
            frozenset(("via", "zone")),
            backend.connected_item_ids(item),
        )
        self.assertEqual((4, 10), backend.connected_copper_layer_ids(item))
        self.assertEqual(1, board.build_count)

    def test_begin_analysis_rebuilds_mutated_connectivity(self):
        item = FakeConnectedItem("track", layers=(0,))
        old_neighbor = FakeConnectedItem("old", layers=(0,))
        new_neighbor = FakeConnectedItem("new", layers=(0,))

        class FakeConnectivity:
            def __init__(self, neighbor):
                self.neighbor = neighbor

            def GetConnectedItems(self, _candidate):
                return (self.neighbor,)

        board = FakeBoard()
        board.GetEnabledLayers = lambda: types.SimpleNamespace(
            CuStack=lambda: (0, 2)
        )
        board.build_count = 0
        board.connectivity = FakeConnectivity(old_neighbor)
        board.BuildConnectivity = lambda: setattr(
            board,
            "build_count",
            board.build_count + 1,
        )
        board.GetConnectivity = lambda: board.connectivity
        backend = SwigBackend(board)

        self.assertEqual(
            frozenset(("track", "old")),
            backend.connected_item_ids(item),
        )
        board.connectivity = FakeConnectivity(new_neighbor)
        backend.begin_analysis()

        self.assertEqual(
            frozenset(("track", "new")),
            backend.connected_item_ids(item),
        )
        self.assertEqual(2, board.build_count)

    def test_connected_items_declines_incompatible_legacy_type_filter_argument(self):
        item = FakeConnectedItem("track", layers=(0,))

        class LegacyConnectivity:
            def __init__(self):
                self.calls = []

            def GetConnectedItems(self, *args):
                self.calls.append(args)
                if len(args) == 1:
                    raise TypeError("missing KICAD_T container")
                raise AssertionError("integer flags are not valid on KiCad 6/7")

        connectivity = LegacyConnectivity()
        board = FakeBoard()
        board.BuildConnectivity = lambda: None
        board.GetConnectivity = lambda: connectivity
        backend = SwigBackend(board)

        self.assertIsNone(backend.connected_item_ids(item))
        self.assertEqual([(item,)], connectivity.calls)

    def test_connected_layers_are_unknown_when_any_layer_query_fails(self):
        item = FakeConnectedItem("via", layers=(0, 4))

        class PartialConnectivity:
            def IsConnectedOnLayer(self, _candidate, layer_id):
                if layer_id == 4:
                    raise RuntimeError("layer graph unavailable")
                return True

        board = FakeBoard()
        board.GetEnabledLayers = lambda: types.SimpleNamespace(
            CuStack=lambda: (0, 4)
        )
        board.BuildConnectivity = lambda: None
        board.GetConnectivity = lambda: PartialConnectivity()
        backend = SwigBackend(board)

        self.assertIsNone(backend.connected_copper_layer_ids(item))

    def test_via_layer_pair_uses_canonical_names(self):
        backend = SwigBackend(
            FakeBoard(
                layer_names={0: "L1 (Sig, PWR)", 2: "L6 (Sig, PWR)"},
                standard_layer_names={0: "F.Cu", 2: "B.Cu"},
            )
        )

        self.assertEqual(
            ("F.Cu", "B.Cu"),
            backend.via_layer_pair_names(FakeViaType(4)),
        )

    def test_teardrop_zone_uses_native_area_flag_when_name_is_empty(self):
        class NativeTeardropZone:
            def IsTeardropArea(self):
                return True

            def GetZoneName(self):
                return ""

        self.assertTrue(
            SwigBackend(FakeBoard()).is_teardrop_zone(NativeTeardropZone())
        )

    def test_through_via_with_custom_layer_names_is_not_blind_buried(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PAD=type("OtherPad", (), {}),
            VIATYPE_THROUGH=4,
            VIATYPE_MICROVIA=1,
            F_Cu=0,
            B_Cu=2,
        )
        try:
            backend = SwigBackend(
                FakeBoard(layer_names={0: "top_copper", 2: "bottom_copper"})
            )

            self.assertFalse(backend.is_blind_buried_via(FakeViaType(4)))
        finally:
            self.restore_focus_module(original_pcbnew)

    def test_item_layer_id_keeps_reported_layer_for_through_hole_pad(self):
        original_pcbnew = sys.modules.get("pcbnew")
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PAD=FakeLayerPad,
            F_Cu=0,
            B_Cu=2,
        )
        try:
            backend = SwigBackend(FakeBoard())
            through_hole_pad = FakeLayerPad((0, 2), reported_layer=0)

            self.assertEqual(0, backend.item_layer_id(through_hole_pad))
        finally:
            self.restore_focus_module(original_pcbnew)


if __name__ == "__main__":
    unittest.main()
