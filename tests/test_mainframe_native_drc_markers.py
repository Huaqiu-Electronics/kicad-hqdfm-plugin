import sys
import types
import unittest


class FakeItem:
    def __init__(self, item_id, start=(0, 0), end=(0, 0), layer="F.Cu"):
        self.item_id = item_id
        self.start = start
        self.end = end
        self.layer = layer


class FakeBackend:
    def __init__(self, native_marker=True):
        self.items = {}
        self.tracks = []
        self.native_marker = native_marker

    def resolve_item(self, item_id):
        return self.items.get(item_id)

    def capabilities(self):
        return types.SimpleNamespace(can_native_drc_marker=self.native_marker)

    def iter_tracks(self):
        return iter(self.tracks)

    def iter_vias(self):
        return iter(())

    def iter_footprints(self):
        return iter(())

    def iter_pads(self, _footprint):
        return iter(())

    def iter_drawings(self):
        return iter(())

    def item_id(self, item):
        return item.item_id

    def item_layer_name(self, item):
        return item.layer

    def item_width(self, _item):
        return 100000

    def item_bbox(self, item):
        left = min(item.start[0], item.end[0]) - 50000
        top = min(item.start[1], item.end[1]) - 50000
        right = max(item.start[0], item.end[0]) + 50000
        bottom = max(item.start[1], item.end[1]) + 50000
        return left, top, right, bottom

    def item_position(self, item):
        bbox = self.item_bbox(item)
        return int((bbox[0] + bbox[2]) / 2), int((bbox[1] + bbox[3]) / 2)

    def track_segment(self, item):
        return item.start, item.end


class FakeExporter:
    def __init__(self):
        self.markers = []
        self.exports = []
        self.clear_count = 0

    def export(self, plan, category=None):
        self.exports.append((category, list(plan.items)))
        markers = ["marker-{0}-{1}".format(category, len(self.exports))]
        self.markers.extend(markers)
        return types.SimpleNamespace(markers=markers, skipped=[])

    def clear(self):
        self.clear_count += 1
        self.markers.clear()


class FakeButton:
    def __init__(self):
        self.enabled = None
        self.tooltip = ""

    def Enable(self, enabled=True):
        self.enabled = enabled

    def SetToolTip(self, tooltip):
        self.tooltip = tooltip


class MainframeNativeDrcMarkersTest(unittest.TestCase):
    def setUp(self):
        self.original_wx = sys.modules.get("wx")
        self.original_pcbnew = sys.modules.get("pcbnew")
        fake_dataview = types.SimpleNamespace(
            DataViewCtrl=object,
            DataViewColumn=object,
            DataViewIndexListModel=object,
            DATAVIEW_CELL_ACTIVATABLE=1,
        )
        sys.modules["wx"] = types.SimpleNamespace(
            Frame=object,
            Panel=object,
            TopLevelWindow=object,
            DEFAULT_FRAME_STYLE=0,
            MAXIMIZE_BOX=0,
            TAB_TRAVERSAL=0,
            EVT_BUTTON=object(),
            EVT_CLOSE=object(),
            ICON_INFORMATION=0,
            MessageBox=lambda *args, **kwargs: None,
            dataview=fake_dataview,
        )
        sys.modules["wx.xrc"] = types.SimpleNamespace()
        sys.modules["wx.dataview"] = fake_dataview
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PCB_SHAPE=object,
            UpdateUserInterface=lambda: None,
            Refresh=lambda: None,
            GetUserUnits=lambda: 0,
        )
        sys.modules["kicad_dfm.child_frame.dfm_child_frame"] = types.SimpleNamespace(
            DfmChildFrame=object
        )
        sys.modules["kicad_dfm.dfm_maindialog.dfm_maindialog_view"] = types.SimpleNamespace(
            DfmMaindailogView=object
        )
        sys.modules["kicad_dfm.manager.rule_manager_view"] = types.SimpleNamespace(
            RuleManagerView=object
        )
        sys.modules["kicad_dfm.hole_childframe.hole_childframe_view"] = types.SimpleNamespace(
            HoleChildFrameView=object
        )

    def tearDown(self):
        if self.original_wx is None:
            sys.modules.pop("wx", None)
        else:
            sys.modules["wx"] = self.original_wx
        sys.modules.pop("wx.xrc", None)
        sys.modules.pop("wx.dataview", None)
        if self.original_pcbnew is None:
            sys.modules.pop("pcbnew", None)
        else:
            sys.modules["pcbnew"] = self.original_pcbnew
        for name in (
            "kicad_dfm.child_frame.dfm_child_frame",
            "kicad_dfm.dfm_maindialog.dfm_maindialog_view",
            "kicad_dfm.manager.rule_manager_view",
            "kicad_dfm.hole_childframe.hole_childframe_view",
        ):
            sys.modules.pop(name, None)

    def test_marker_buttons_are_disabled_when_backend_capability_is_unavailable(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.backend = FakeBackend(native_marker=False)
        inject = FakeButton()
        clear = FakeButton()
        frame.dfm_maindialog = types.SimpleNamespace(
            inject_drc_markers_button=inject,
            clear_drc_markers_button=clear,
        )

        frame.configure_native_drc_marker_buttons()

        self.assertFalse(inject.enabled)
        self.assertFalse(clear.enabled)
        self.assertIn("KiCad 8, 9, and 10", inject.tooltip)

    def test_marker_buttons_remain_enabled_when_backend_supports_markers(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.backend = FakeBackend(native_marker=True)
        inject = FakeButton()
        clear = FakeButton()
        frame.dfm_maindialog = types.SimpleNamespace(
            inject_drc_markers_button=inject,
            clear_drc_markers_button=clear,
        )

        frame.configure_native_drc_marker_buttons()

        self.assertTrue(inject.enabled)
        self.assertTrue(clear.enabled)

    def test_native_drc_marker_plans_deduplicate_result_rows(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        backend = FakeBackend()
        backend.items["a"] = FakeItem("a")
        backend.items["b"] = FakeItem("b")
        frame.backend = backend
        row = {"id": "a", "related_id": "b"}
        frame.kicad_result = {
            "Smallest Trace Width": {"check": [{"result": [row]}]},
        }
        frame.analysis_result = {
            "Smallest Trace Width": {"check": [{"result": [row]}]},
            "Pad size": {"check": [{"result": [{"id": "missing"}]}]},
        }

        plans = list(frame.native_drc_marker_plans())

        self.assertEqual(1, len(plans))
        self.assertEqual("Smallest Trace Width", plans[0][0])
        self.assertEqual([backend.items["a"], backend.items["b"]], plans[0][1].items)

    def test_inject_and_clear_native_drc_markers_use_session_exporter(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.backend = FakeBackend(native_marker=True)
        exporter = FakeExporter()
        frame.native_drc_marker_exporter = exporter
        frame.native_drc_marker_plans = lambda: (
            ("Smallest Trace Width", types.SimpleNamespace(items=[FakeItem("a")])),
            ("RingHole", types.SimpleNamespace(items=[FakeItem("b")])),
        )

        exported, skipped = frame.inject_native_drc_markers()

        self.assertEqual(2, exported)
        self.assertEqual(0, skipped)
        self.assertEqual(1, exporter.clear_count)
        self.assertEqual(["Smallest Trace Width", "RingHole"], [item[0] for item in exporter.exports])

        cleared = frame.clear_native_drc_markers(refresh=False)

        self.assertEqual(2, cleared)
        self.assertEqual([], exporter.markers)

    def test_close_owned_windows_only_closes_children_of_mainframe(self):
        from kicad_dfm import dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.logger = types.SimpleNamespace(debug=lambda *args, **kwargs: None)

        class Window:
            def __init__(self, parent):
                self.parent = parent
                self.closed = []

            def GetParent(self):
                return self.parent

            def Close(self, force):
                self.closed.append(force)

        owned = Window(frame)
        unrelated = Window(object())
        original = getattr(mainframe_module.wx, "GetTopLevelWindows", None)
        mainframe_module.wx.GetTopLevelWindows = lambda: [frame, owned, unrelated]
        try:
            frame.close_owned_windows()
        finally:
            if original is None:
                delattr(mainframe_module.wx, "GetTopLevelWindows")
            else:
                mainframe_module.wx.GetTopLevelWindows = original

        self.assertEqual([True], owned.closed)
        self.assertEqual([], unrelated.closed)

    def test_show_rule_manager_only_replaces_exact_rule_view_title(self):
        from kicad_dfm import dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.unit = 1
        frame.control = {}
        frame.current_rule_profile_id = lambda: "standard"

        class Window:
            def __init__(self, title):
                self.title = title
                self.destroyed = False

            def GetTitle(self):
                return self.title

            def Destroy(self):
                self.destroyed = True

        exact = Window("Rule View")
        partial = Window("Rule")
        created = []

        class RuleWindow:
            def __init__(self, *args):
                created.append(args)

            def Show(self):
                return True

        original_windows = getattr(mainframe_module.wx, "GetTopLevelWindows", None)
        original_rule_window = mainframe_module.RuleManagerView
        mainframe_module.wx.GetTopLevelWindows = lambda: [exact, partial]
        mainframe_module.RuleManagerView = RuleWindow
        try:
            frame.show_rule_manager(None)
        finally:
            mainframe_module.RuleManagerView = original_rule_window
            if original_windows is None:
                delattr(mainframe_module.wx, "GetTopLevelWindows")
            else:
                mainframe_module.wx.GetTopLevelWindows = original_windows

        self.assertTrue(exact.destroyed)
        self.assertFalse(partial.destroyed)
        self.assertEqual(1, len(created))

    def test_sync_native_drc_markers_exports_only_when_capability_enabled(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.backend = FakeBackend(native_marker=True)
        frame.logger = types.SimpleNamespace(debug=lambda *args, **kwargs: None)
        exporter = FakeExporter()
        frame.native_drc_marker_exporter = exporter
        frame.native_drc_marker_plans = lambda: (
            ("Smallest Trace Width", types.SimpleNamespace(items=[FakeItem("a")])),
        )

        exported, skipped = frame.sync_native_drc_markers()

        self.assertEqual((1, 0), (exported, skipped))
        self.assertEqual(1, exporter.clear_count)

    def test_sync_native_drc_markers_skips_for_kicad8_plus_capability(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.backend = FakeBackend(native_marker=False)
        exporter = FakeExporter()
        exporter.markers = ["old"]
        frame.native_drc_marker_exporter = exporter

        exported, skipped = frame.sync_native_drc_markers()

        self.assertEqual((0, 0), (exported, skipped))
        self.assertEqual(1, exporter.clear_count)
        self.assertEqual([], exporter.markers)

    def test_apply_gerber_native_results_maps_file_result_to_uuid(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        backend = FakeBackend()
        track = FakeItem("track-uuid", (1000000, 1000000), (9000000, 1000000))
        backend.tracks = [track]
        backend.items["track-uuid"] = track
        frame.backend = backend
        frame.board = object()
        frame.logger = types.SimpleNamespace(debug=lambda *args, **kwargs: None)
        native_results = {
            "Smallest Trace Width": {
                "display": 0.1,
                "check": [
                    {
                        "result": [
                            {
                                "id": "board-CuTop.gbr",
                                "source": "gerber",
                                "item_type": "gerber",
                                "layer": ["F.Cu"],
                                "raw": {"segment": ((1.0, 1.0), (9.0, 1.0))},
                            }
                        ]
                    }
                ],
                "color": "gold",
            }
        }

        frame.apply_gerber_native_results(native_results)

        row = frame.analysis_result["Smallest Trace Width"]["check"][0]["result"][0]
        self.assertEqual("track-uuid", row["id"])
        self.assertEqual("matched", row["raw"]["uuid_mapping"]["status"])
        plans = list(frame.native_drc_marker_plans())
        self.assertEqual([track], plans[0][1].items)


if __name__ == "__main__":
    unittest.main()
