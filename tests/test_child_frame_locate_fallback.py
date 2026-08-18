import sys
import types
import unittest


class FakeShape:
    def SetLayer(self, layer):
        self.layer = layer

    def SetWidth(self, width):
        self.width = width


class FakeLocateService:
    def __init__(self):
        self.bboxes = []
        self.begin_count = 0
        self.clear_count = 0
        self.items_seen_before_begin = []
        self.item_list = []
        self.plans = []
        self.backend = object()

    def create_warning_shape(self):
        return FakeShape()

    def begin(self, defer_focus=False):
        self.begin_count += 1
        self.items_seen_before_begin.append(tuple(self.item_list))
        self.item_list.clear()

    def clear(self):
        self.clear_count += 1
        self.item_list.clear()

    def flush_focus(self):
        return False

    def show_bbox(self, bbox):
        self.bboxes.append(tuple(bbox))
        return bbox

    def add_temporary_shape(self, line, target_layer):
        return line

    def apply_plan(self, plan):
        self.plans.append(plan)
        return plan.items


class FakeGraphicsSetting:
    def set_segment(self, line, result, x, y):
        if result.get("raise"):
            raise KeyError("missing coordinate")
        line.segment = (result, x, y)
        return line

    def get_board_edge_judge_segment(self, result, x, y):
        line = FakeShape()
        line.edge = (result, x, y)
        return [line] if result.get("edge") else []

    def get_SMD_pads_rect_list(self, result, x, y):
        if not result.get("smd"):
            return None
        line = FakeShape()
        line.smd = (result, x, y)
        return line

    def get_signal_integrity_segment(self, result, x, y):
        line = FakeShape()
        line.signal_segment = (result, x, y)
        return line

    def get_hole_diameter_segment(self, result, x, y):
        line = FakeShape()
        line.hole_segment = (result, x, y)
        return line

    def get_signal_integrity_arc(self, result, x, y):
        line = FakeShape()
        line.signal_arc = (result, x, y)
        return line

    def get_signal_integrity_floating_copper(self, result, x, y):
        line = FakeShape()
        line.signal_float = (result, x, y)
        return line

    def get_signal_integrity_rect(self, result, x, y):
        line = FakeShape()
        line.signal_rect = (result, x, y)
        return line


class FakeEvent:
    def Skip(self):
        pass


class FakeBoard:
    def GetLayerID(self, layer):
        return 0

    def GetDesignSettings(self):
        return types.SimpleNamespace(
            GetAuxOrigin=lambda: types.SimpleNamespace(x=0, y=0)
        )


class ChildFrameLocateFallbackTest(unittest.TestCase):
    def setUp(self):
        self.original_wx = sys.modules.get("wx")
        self.original_pcbnew = sys.modules.get("pcbnew")
        fake_dataview = types.SimpleNamespace(
            DATAVIEW_CELL_INERT=0,
            DATAVIEW_CELL_ACTIVATABLE=1,
            EVT_DATAVIEW_SELECTION_CHANGED=object(),
            EVT_DATAVIEW_ITEM_ACTIVATED=object(),
        )
        sys.modules["wx"] = types.SimpleNamespace(
            ALIGN_LEFT=0,
            NOT_FOUND=-1,
            ICON_INFORMATION=0,
            Refresh=lambda: None,
            EVT_LISTBOX=object(),
            EVT_COMBOBOX=object(),
            EVT_BUTTON=object(),
            EVT_CLOSE=object(),
            YieldIfNeeded=lambda: None,
            CallAfter=lambda func, *args, **kwargs: func(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: None,
            Bitmap=lambda path: path,
            dataview=fake_dataview,
        )
        sys.modules["wx.dataview"] = fake_dataview
        sys.modules["kicad_dfm.child_frame.ui_child_frame"] = types.SimpleNamespace(
            UiChildFrame=type("UiChildFrame", (), {})
        )
        sys.modules["kicad_dfm.settings.graphics_setting"] = types.SimpleNamespace(
            GraphicsSetting=object
        )
        sys.modules["kicad_dfm.child_frame.child_frame_setting"] = types.SimpleNamespace(
            ChildFrameSetting=object,
            CHILDFRAME_UNIT_CONVERSION=types.SimpleNamespace(
                Millimeter2iu=lambda value: value,
                Millimeter2mils=lambda value: value,
            ),
        )
        sys.modules["kicad_dfm.child_frame.diagram_hint"] = types.SimpleNamespace(
            diagram_bitmap_for=lambda item: None
        )
        sys.modules["kicad_dfm.settings.timestamp"] = types.SimpleNamespace(
            TimeStamp=object
        )
        sys.modules["kicad_dfm.settings.kicad_setting"] = types.SimpleNamespace(
            KiCadSetting=types.SimpleNamespace(read_lang_setting=lambda: "English")
        )
        sys.modules["kicad_dfm.child_frame.dfm_child_frame_model"] = types.SimpleNamespace(
            DfmChildFrameModel=object
        )
        import builtins
        builtins.__dict__["_"] = lambda message: message
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PCB_SHAPE=FakeShape,
            Dwgs_User=100,
            B_Adhes=101,
            Refresh=lambda: None,
        )

    def tearDown(self):
        if self.original_wx is None:
            sys.modules.pop("wx", None)
        else:
            sys.modules["wx"] = self.original_wx
        sys.modules.pop("wx.dataview", None)
        for name in (
            "kicad_dfm.child_frame.ui_child_frame",
            "kicad_dfm.settings.graphics_setting",
            "kicad_dfm.child_frame.child_frame_setting",
            "kicad_dfm.child_frame.diagram_hint",
            "kicad_dfm.settings.timestamp",
            "kicad_dfm.settings.kicad_setting",
            "kicad_dfm.child_frame.dfm_child_frame_model",
        ):
            sys.modules.pop(name, None)
        if self.original_pcbnew is None:
            sys.modules.pop("pcbnew", None)
        else:
            sys.modules["pcbnew"] = self.original_pcbnew

    def test_draw_result_location_falls_back_to_bbox_when_segment_fails(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.locate_service = FakeLocateService()
        frame.graphics_setting = FakeGraphicsSetting()
        frame.board = FakeBoard()

        result = {
            "type": 0,
            "et": 0,
            "bbox_nm": (1, 2, 3, 4),
            "layer": ["F.Cu"],
            "raise": True,
        }

        self.assertTrue(frame.draw_result_location(result, 0, 0, []))
        self.assertEqual([(1, 2, 3, 4)], frame.locate_service.plans[0].bboxes_nm)

    def test_result_unit_conversion_receives_unrounded_millimetres(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.unit = 5

        self.assertEqual("0.0762mil", frame.format_result_value({"value": "0.076200"}))

    def test_boolean_result_is_not_formatted_as_a_length(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.unit = 5

        self.assertEqual(
            "—",
            frame.format_result_value(
                {"value": "1", "value_kind": "boolean"}
            ),
        )

    def test_hole_aspect_ratio_format_uses_stable_rule_key_in_chinese_ui(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "Hole Size"
        frame.unit = 1
        frame.board = types.SimpleNamespace(
            GetDesignSettings=lambda: types.SimpleNamespace(
                GetBoardThickness=lambda: 1600000
            )
        )

        result = {
            "item": "Aspect Ratio",
            "rule_key": "holesize:aspectratio",
            "value": "8.0",
        }

        self.assertEqual("8.00 (1.60/0.20)", frame.format_result_value(result))

    def test_hole_aspect_ratio_format_prefers_measured_thickness_and_diameter(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "Hole Size"
        frame.unit = 5
        frame.board = None
        result = {
            "item": "Aspect Ratio",
            "rule_key": "holesize:aspectratio",
            "value": "6.427768",
            "raw": {"board_thickness_mm": 1.6, "diameter": 0.24892},
        }

        self.assertEqual("6.43 (1.60/0.25)", frame.format_result_value(result))

    def test_slot_aspect_ratio_is_not_formatted_as_a_length(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "Hole Size"
        frame.unit = 5

        result = {
            "item": "槽长宽比",
            "rule_key": "holesize:slotaspectratio",
            "value": "4.0",
        }

        self.assertEqual("4.0", frame.format_result_value(result))

    def test_rule_diagram_refreshes_for_selected_item(self):
        import kicad_dfm.child_frame.dfm_child_frame as child_module

        frame = object.__new__(child_module.DfmChildFrame)
        bitmaps = []
        frame.bmp = types.SimpleNamespace(SetBitmap=bitmaps.append)
        frame.Layout = lambda: None
        original_loader = child_module.diagram_bitmap_for
        child_module.diagram_bitmap_for = lambda item, **_kwargs: "bitmap:" + item
        try:
            frame.update_rule_diagram("Floating Copper")
        finally:
            child_module.diagram_bitmap_for = original_loader

        self.assertEqual(["bitmap:Floating Copper"], bitmaps)

    def test_rule_content_refreshes_for_selected_item(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        class Label:
            def __init__(self):
                self.value = ""
                self.tooltip = ""
                self.wrap = None

            def SetLabel(self, value):
                self.value = value

            def SetToolTip(self, value):
                self.tooltip = value

            def Wrap(self, width):
                self.wrap = width

            def GetParent(self):
                return types.SimpleNamespace(
                    GetClientSize=lambda: types.SimpleNamespace(width=200)
                )

        class Description:
            def __init__(self):
                self.value = ""
                self.insertion = None

            def SetValue(self, value):
                self.value = value

            def SetInsertionPoint(self, value):
                self.insertion = value

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "Smallest Trace Spacing"
        frame.unit = 5
        frame.result_json = {
            "Smallest Trace Spacing": {
                "check": [
                    {
                        "result": [
                            {
                                "item": "Trace Spacing",
                                "rule_key": "smallesttracespacing:tracespacing",
                                "rule": "0.101600,0.152400,0.203200",
                            }
                        ]
                    }
                ]
            }
        }
        frame.rule_value_label = Label()
        frame.rule_description_text = Description()
        frame.Layout = lambda: None

        frame.update_rule_content("Trace Spacing")

        self.assertEqual("Rule: 4, 6, 8 mil", frame.rule_value_label.value)
        self.assertIn("Recommended value: 6 mil or greater", frame.rule_description_text.value)
        self.assertEqual(0, frame.rule_description_text.insertion)

    def test_long_pad_rule_uses_complete_custom_guidance(self):
        import kicad_dfm.child_frame.rule_guidance as guidance_module

        expected = (
            "长条焊盘过小无附着力低，会影响生产品质良率，可能会导致测试成本上涨，"
            "建议最小宽度≥0.15mm，推荐≥0.2mm。"
        )
        original_translate = guidance_module._
        guidance_module._ = lambda text: expected if text.startswith(
            "Undersized elongated pads"
        ) else text
        try:
            guidance = guidance_module.current_rule_guidance(
                "Pad size",
                {
                    "item": "Long Pads",
                    "rule_key": "padsize:longpads",
                    "rule": "0.152400,0.177800,0.254000",
                },
                5,
            )
        finally:
            guidance_module._ = original_translate

        self.assertEqual(expected, guidance)

    def test_analysis_process_without_location_clears_previous_location(self):
        import kicad_dfm.child_frame.dfm_child_frame as child_module

        DfmChildFrame = child_module.DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.locate_service = FakeLocateService()
        frame.locate_service.item_list.append(object())
        frame.graphics_setting = FakeGraphicsSetting()
        frame.board = FakeBoard()
        frame.result_key_from_text = lambda string_data: "issue-1"
        frame.result = {"issue-1": {"result": [{"type": 9}]}}
        frame.json_string = "Any Rule"
        frame.item_list = []
        frame.check_box = types.SimpleNamespace(GetValue=lambda: True)
        frame.set_locate_status = lambda message: None
        frame.has_no_location_result = lambda results: True

        wx = child_module.wx
        messages = []
        original_message_box = wx.MessageBox
        wx.MessageBox = lambda *args, **kwargs: messages.append(args)
        try:
            frame.analysis_process("1", FakeEvent())
        finally:
            wx.MessageBox = original_message_box

        self.assertEqual(0, frame.locate_service.begin_count)
        self.assertEqual(1, frame.locate_service.clear_count)
        self.assertEqual([], frame.locate_service.item_list)
        self.assertEqual(1, len(messages))

    def test_analysis_process_preserves_previous_items_until_begin_cleanup(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.locate_service = FakeLocateService()
        previous_item = object()
        frame.locate_service.item_list.append(previous_item)
        frame.item_list = frame.locate_service.item_list
        frame.graphics_setting = FakeGraphicsSetting()
        frame.board = FakeBoard()
        frame.result_key_from_text = lambda string_data: "issue-1"
        frame.result = {
            "issue-1": {
                "result": [
                    {
                        "type": 0,
                        "bbox_nm": (1, 2, 3, 4),
                        "layer": ["F.Cu"],
                    }
                ]
            }
        }
        frame.json_string = "Pad size"
        frame.check_box = types.SimpleNamespace(GetValue=lambda: True)
        frame._locate_status = ""
        frame.set_locate_status = lambda message: setattr(frame, "_locate_status", message)
        frame.has_no_location_result = lambda results: False

        frame.analysis_process("1", FakeEvent())

        self.assertEqual([(previous_item,)], frame.locate_service.items_seen_before_begin)
        self.assertIs(frame.item_list, frame.locate_service.item_list)

    def test_file_result_without_drawable_location_clears_previous_location(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.locate_service = FakeLocateService()
        frame.locate_service.item_list.append(object())
        frame.graphics_setting = FakeGraphicsSetting()
        frame.board = FakeBoard()
        frame.result_key_from_text = lambda string_data: "issue-1"
        frame.result = {
            "issue-1": {
                "result": [
                    {
                        "type": 9,
                        "item_type": "gerber",
                        "layer": ["F.Cu"],
                    }
                ]
            }
        }
        frame.json_string = "Any Rule"
        frame.check_box = types.SimpleNamespace(GetValue=lambda: True)
        frame._locate_status = ""
        frame.set_locate_status = lambda message: setattr(frame, "_locate_status", message)

        frame.analysis_process("1", FakeEvent())

        self.assertEqual(0, frame.locate_service.begin_count)
        self.assertEqual(1, frame.locate_service.clear_count)
        self.assertEqual([], frame.locate_service.item_list)
        self.assertEqual(
            "Gerber/Drill file result has no PCB object location.",
            frame._locate_status,
        )

    def test_set_items_brightened_uses_locate_plan(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.locate_service = FakeLocateService()
        statuses = []
        frame.set_locate_status = statuses.append

        items = [object(), object()]
        frame.set_items_Brightened(items)

        self.assertEqual(1, len(frame.locate_service.plans))
        plan = frame.locate_service.plans[0]
        self.assertEqual(items, plan.items)
        self.assertEqual(20, plan.marker_limit)

    def test_draw_file_based_results_uses_locate_plan(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.locate_service = FakeLocateService()
        frame.graphics_setting = FakeGraphicsSetting()
        frame.board = FakeBoard()
        statuses = []
        frame.set_locate_status = statuses.append

        result = {
            "type": 0,
            "sx": 1,
            "sy": 2,
            "ex": 3,
            "ey": 4,
            "layer": ["F.Cu"],
            "raw": {"width": 0.2},
        }
        layer_num = []

        self.assertTrue(frame.draw_file_based_results([result], 10, 20, layer_num))

        self.assertEqual([0], layer_num)
        self.assertEqual(1, len(frame.locate_service.plans))
        plan = frame.locate_service.plans[0]
        self.assertEqual([0], plan.layers)
        self.assertEqual(200000, plan.temporary_shapes[0].width)
        self.assertTrue(statuses)

    def test_file_result_uses_top_level_gap_when_flash_mappings_have_no_segment(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        result = {
            "type": 0,
            "sx": 1,
            "sy": 2,
            "ex": 3,
            "ey": 4,
            "layer": ["F.Mask"],
            "raw": {
                "primary": {"kind": "region", "is_flash": True},
                "related": {"kind": "circle", "is_flash": True},
            },
        }

        drawables = frame.file_result_drawables(
            result, primary_resolved=False, related_resolved=False
        )

        self.assertEqual([result], drawables)

    def test_gerber_result_hides_unrelated_layers(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)

        self.assertTrue(
            frame.should_hide_unrelated_layers([0], [{"item_type": "gerber"}])
        )

    def test_file_result_layers_include_related_copper_layer(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        result = {
            "layer": ["Drl"],
            "raw": {
                "primary": {"layer": ["Drl"]},
                "related": {"layer": ["F.Cu"]},
            },
        }

        self.assertEqual(["Drl", "F.Cu"], frame.file_result_layers(result))

    def test_paired_gerber_result_draws_both_trace_segments(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        result = {
            "type": 0,
            "et": 0,
            "sx": "0.0",
            "sy": "0.0",
            "ex": "1.0",
            "ey": "0.0",
            "layer": ["F.Cu"],
            "raw": {
                "primary": {"segment": ((0.0, 0.0), (1.0, 0.0)), "layer": ["F.Cu"]},
                "related": {"segment": ((0.0, 0.0), (1.0, 1.0)), "layer": ["F.Cu"]},
            },
        }

        drawables = frame.file_result_drawables(result)

        self.assertEqual(2, len(drawables))
        self.assertEqual("1.000000", drawables[0]["ex"])
        self.assertEqual("0.000000", drawables[0]["ey"])
        self.assertEqual("1.000000", drawables[1]["ex"])
        self.assertEqual("1.000000", drawables[1]["ey"])

    def test_zone_region_is_never_drawn_as_a_centerline(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        result = {
            "type": 0,
            "et": 0,
            "sx": "5.0",
            "sy": "5.0",
            "ex": "1.0",
            "ey": "1.0",
            "layer": ["B.Cu"],
            "raw": {
                "primary": {
                    "kind": "region",
                    "aperture_function": "Conductor",
                    "segment": ((0.0, 5.0), (10.0, 5.0)),
                },
                "related": {
                    "kind": "segment",
                    "segment": ((0.0, 1.0), (2.0, 1.0)),
                },
            },
        }

        drawables = frame.file_result_drawables(result)

        self.assertEqual(1, len(drawables))
        self.assertEqual("0.000000", drawables[0]["sx"])
        self.assertEqual("2.000000", drawables[0]["ex"])

    def test_location_items_resolves_both_acute_angle_tracks(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        primary = object()
        related = object()
        frame = object.__new__(DfmChildFrame)
        frame.locate_service = types.SimpleNamespace(
            backend=types.SimpleNamespace(
                resolve_item=lambda item_id: {"t1": primary, "t2": related}.get(item_id)
            )
        )

        self.assertEqual(
            [primary, related],
            frame.location_items_for_result({"id": "t1", "related_id": "t2"}),
        )

    def test_board_edge_result_shape_draws_explicit_result_segment(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.graphics_setting = FakeGraphicsSetting()
        line = FakeShape()

        result = {"sx": "1", "sy": "2", "ex": "3", "ey": "4"}
        shape = frame.board_edge_result_shape(line, result, 10, 20)

        self.assertEqual((result, 10, 20), shape.segment)

    def test_smd_pad_location_items_uses_smd_fallback(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.locate_service = FakeLocateService()
        frame.graphics_setting = FakeGraphicsSetting()

        items = frame.smd_pad_location_items({"result": True, "smd": True}, 10, 20)

        self.assertEqual(1, len(items))
        self.assertEqual(({"result": True, "smd": True}, 10, 20), items[0].smd)

    def test_signal_result_item_dispatches_by_rule_and_geometry(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.graphics_setting = FakeGraphicsSetting()

        frame.json_string = "Signal Integrity"
        signal = frame.signal_result_item({"type": 0, "et": 0}, 10, 20)
        self.assertEqual(({"type": 0, "et": 0}, 10, 20), signal.signal_segment)

        frame.json_string = "Hole Size"
        hole = frame.signal_result_item({"type": 0, "et": 0}, 10, 20)
        self.assertEqual(({"type": 0, "et": 0}, 10, 20), hole.hole_segment)

        rect = frame.signal_result_item({"type": 0, "et": 2}, 10, 20)
        self.assertEqual(({"type": 0, "et": 2}, 10, 20), rect.signal_rect)

    def test_close_destroys_window_even_when_locate_cleanup_fails(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        class FailingLocateService:
            def clear(self):
                raise RuntimeError("shape already deleted")

        frame = object.__new__(DfmChildFrame)
        frame.locate_service = FailingLocateService()
        destroyed = []
        frame.Destroy = lambda: destroyed.append(True)

        frame.on_close(types.SimpleNamespace())

        self.assertEqual([True], destroyed)
        self.assertTrue(frame._closing)

    def test_analysis_type_labels_use_selected_language_without_changing_keys(self):
        from kicad_dfm import config
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "Signal Integrity"
        frame.result_json = {
            "Signal Integrity": {
                "check": [{"result": [{"item": "Floating Copper"}]}]
            }
        }
        frame.message_type = config.Language_chinese

        self.assertEqual(["孤立铜(1个)"], frame.get_type_data)
        self.assertEqual("Floating Copper", frame.analysis_type_key("孤立铜(1个)"))
        self.assertEqual("悬空端点", frame.analysis_type_text("Dangling Tracks"))
        self.assertEqual("网络断连", frame.analysis_type_text("Trace Mssing"))

        frame.message_type = config.Language_english
        self.assertEqual(["Floating Copper(1pcs)"], frame.get_type_data)

    def test_analysis_type_counts_follow_selected_layers(self):
        from kicad_dfm import config
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "Signal Integrity"
        frame.message_type = config.Language_chinese
        frame.child_frame_setting = types.SimpleNamespace(
            layer_conversion=lambda _category, layer: layer
        )
        frame.result_json = {
            "Signal Integrity": {
                "check": [{
                    "result": [
                        {"item": "Floating Copper", "layer": ["F.Cu"]},
                        {"item": "Floating Copper", "layer": ["F.Cu"]},
                        {"item": "Floating Copper", "layer": ["B.Cu"]},
                        {"item": "Dangling Tracks", "layer": ["B.Cu"]},
                    ]
                }]
            }
        }

        front = frame.analysis_type_counts({"F.Cu"})
        back = frame.analysis_type_counts({"B.Cu"})

        self.assertEqual({"Floating Copper": 2}, front)
        self.assertEqual({"Floating Copper": 1, "Dangling Tracks": 1}, back)
        self.assertEqual("孤立铜(2个)", frame.analysis_type_label("Floating Copper", 2))

    def test_analysis_types_merge_localized_engine_rows_by_rule_key(self):
        from kicad_dfm import config
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "Smallest Trace Spacing"
        frame.message_type = config.Language_chinese
        frame.child_frame_setting = types.SimpleNamespace(
            layer_conversion=lambda _category, layer: layer
        )
        stable_key = "smallesttracespacing:padtopadspacing"
        native = {
            "item": "焊盘到焊盘",
            "rule_key": stable_key,
            "layer": ["F.Cu"],
        }
        gerber = {
            "item": "Pad-to-Pad Spacing",
            "rule_key": stable_key,
            "layer": ["F.Cu"],
        }
        frame.result_json = {
            "Smallest Trace Spacing": {
                "check": [{"result": [native]}, {"result": [gerber]}]
            }
        }

        self.assertEqual({"Pad-to-Pad Spacing": 2}, frame.analysis_type_counts())
        labels = frame.get_type_data
        self.assertEqual(1, len(labels))
        self.assertEqual(
            frame.analysis_type_label("Pad-to-Pad Spacing", 2),
            labels[0],
        )
        selected_item = frame.analysis_type_key(labels[0])
        self.assertEqual("Pad-to-Pad Spacing", selected_item)
        self.assertTrue(frame.result_matches_rule_item(native, selected_item))
        self.assertTrue(frame.result_matches_rule_item(gerber, selected_item))

    def test_completed_smd_summary_remains_visible_with_zero_detail_rows(self):
        from kicad_dfm import config
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "SMD Spacing"
        frame.message_type = config.Language_english
        frame.child_frame_setting = types.SimpleNamespace(
            layer_conversion=lambda _category, layer: layer
        )
        stable_key = "smdspacing:smdpadspacing"
        frame.result_json = {
            "SMD Spacing": {
                "execution_status": "completed",
                "check": [],
                "item_summaries": {
                    # Existing Gerber summaries are keyed by the item text and
                    # may not repeat item/rule_key inside the summary.
                    "SMD Pad Spacing": {
                        "execution_status": "completed",
                        "checked_count": 12,
                        "displayed_count": 0,
                    }
                },
            }
        }

        self.assertEqual({"SMD Pad Spacing": 0}, frame.analysis_type_counts())
        self.assertEqual(["SMD Pad Spacing(0pcs)"], frame.get_type_data)
        self.assertEqual(
            "SMD Pad Spacing",
            frame.analysis_type_key("SMD Pad Spacing(0pcs)"),
        )
        summary = frame.rule_result_for_item("SMD Pad Spacing")
        self.assertEqual(stable_key, summary["rule_key"])
        self.assertEqual(12, summary["checked_count"])

    def test_alarm_filter_keeps_executed_smd_type_as_zero_visible_rows(self):
        from kicad_dfm import config
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "SMD Spacing"
        frame.message_type = config.Language_english
        frame.kicad = True
        frame.delete_value = {}
        frame.combo_box = types.SimpleNamespace(GetSelection=lambda: 1)
        frame.lst_layer = types.SimpleNamespace(Set=lambda _items: None)
        visible_types = []
        frame.lst_analysis_type = types.SimpleNamespace(
            Set=lambda items: visible_types.extend(items)
        )
        frame.child_frame_setting = types.SimpleNamespace(
            layer_conversion=lambda _category, layer: layer
        )
        stable_key = "smdspacing:smdpadspacing"
        frame.result_json = {
            "SMD Spacing": {
                "execution_status": "completed",
                "check": [{
                    "result": [{
                        "item": "SMD Pad Spacing",
                        "rule_key": stable_key,
                        "layer": ["F.Cu"],
                        "color": "black",
                    }]
                }],
                "item_summaries": {
                    stable_key: {
                        "rule_key": stable_key,
                        "item": "SMD Pad Spacing",
                        "execution_status": "completed",
                        "checked_count": 1,
                        "displayed_count": 1,
                    }
                },
            }
        }

        frame.dispose_result()

        self.assertEqual([], frame.result_json[frame.json_string]["check"])
        self.assertEqual(["SMD Pad Spacing(0pcs)"], visible_types)
        self.assertEqual({"SMD Pad Spacing": 0}, frame.analysis_type_counts())

    def test_unexecuted_item_summary_is_not_presented_as_a_completed_check(self):
        from kicad_dfm import config
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "SMD Spacing"
        frame.message_type = config.Language_english
        frame.result_json = {
            "SMD Spacing": {
                "execution_status": "not_computed",
                "check": [],
                "item_summaries": {
                    "smdspacing:smdpadspacing": {
                        "item": "SMD Pad Spacing",
                        "execution_status": "completed",
                    }
                },
            }
        }

        self.assertEqual({}, frame.analysis_type_counts())
        self.assertEqual([], frame.get_type_data)

    def test_detail_result_rows_do_not_repeat_analysis_type(self):
        from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame

        frame = object.__new__(DfmChildFrame)
        frame.json_string = "Signal Integrity"
        frame.unit = 1
        frame.child_frame_setting = types.SimpleNamespace(
            layer_conversion=lambda _category, layer: layer
        )
        frame.result_json = {
            "Signal Integrity": {
                "check": [{
                    "result": [{
                        "item": "Floating Copper",
                        "value": 0.0,
                        "layer": ["F.Cu"],
                        "color": "red",
                    }]
                }]
            }
        }

        rows = frame.get_result()

        self.assertEqual(["1", "Error", "0.0mm", "F.Cu", "red"], rows[0])
        self.assertNotIn("Floating Copper", rows[0])


if __name__ == "__main__":
    unittest.main()
