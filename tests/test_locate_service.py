import sys
import types
import unittest

from kicad_dfm.services.locate import LocatePlan, LocateService, ResultLocationPlanner


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


class FakeShape:
    def __init__(self):
        self.shape = None
        self.start_x = 0
        self.start_y = 0
        self.end_x = 0
        self.end_y = 0
        self.width = 0
        self.layer = None
        self.selected = False
        self.brightened = False
        self.line_color = None
        self.fill_color = None
        self.stroke = FakeStroke()

    def GetLayerSet(self):
        return None

    def SetLayer(self, layer):
        self.layer = layer

    def GetLayer(self):
        return self.layer

    def SetWidth(self, width):
        self.width = width

    def SetLineColor(self, color):
        self.line_color = color

    def SetFillColor(self, color):
        self.fill_color = color

    def GetStroke(self):
        return self.stroke

    def SetStroke(self, stroke):
        self.stroke = stroke

    def SetShape(self, shape):
        self.shape = shape

    def SetStartX(self, x):
        self.start_x = x

    def SetStartY(self, y):
        self.start_y = y

    def SetEndX(self, x):
        self.end_x = x

    def SetEndY(self, y):
        self.end_y = y

    def GetBoundingBox(self):
        return FakeBox(self.start_x, self.start_y, self.end_x, self.end_y)

    def SetSelected(self, value=True):
        self.selected = value

    def SetBrightened(self, value=True):
        self.brightened = value


class FakeStroke:
    def __init__(self):
        self.color = None

    def SetColor(self, color):
        self.color = color


class FakeItem:
    def __init__(self, bounds, item_id=""):
        self.bounds = bounds
        self.item_id = item_id
        self.selected = False
        self.brightened = False

    def GetBoundingBox(self):
        return FakeBox(*self.bounds)

    def SetSelected(self, value=True):
        self.selected = value

    def SetBrightened(self, value=True):
        self.brightened = value

    def ClearSelected(self):
        self.selected = False

    def ClearBrightened(self):
        self.brightened = False


class FakeBoard:
    def __init__(self):
        self.items = []
        self.visible_layers = object()
        self.restored_layers = []

    def Add(self, item):
        self.items.append(item)

    def Delete(self, item):
        try:
            self.items.remove(item)
        except ValueError:
            pass

    def GetVisibleLayers(self):
        return self.visible_layers

    def SetVisibleLayers(self, layers):
        self.restored_layers.append(layers)


class FakeBackend:
    def __init__(self, board=None):
        self.board = board
        self.focused = []
        self.refresh_count = 0
        self.update_count = 0
        self.cache_invalidated = 0
        self.add_shape_count = 0
        self.delete_shape_count = 0
        self.selected_calls = []
        self.brightened_calls = []
        self.clear_selected_count = 0
        self.clear_brightened_count = 0
        self.visible_layers_value = object()
        self.restored_layers = []
        self.items_by_id = {}
        self.events = []

    def item_bbox(self, item):
        if not hasattr(item, "GetBoundingBox"):
            return None
        box = item.GetBoundingBox()
        return (
            min(box.GetLeft(), box.GetRight()),
            min(box.GetTop(), box.GetBottom()),
            max(box.GetLeft(), box.GetRight()),
            max(box.GetTop(), box.GetBottom()),
        )

    def item_width(self, item):
        return getattr(item, "width", 0)

    def item_id(self, item):
        return getattr(item, "item_id", "")

    def capabilities(self):
        return types.SimpleNamespace(can_focus_native=True)

    def resolve_item(self, item_id):
        return self.items_by_id.get(item_id)

    def layer_id(self, layer):
        return {"F.Cu": 0, "B.Cu": 31}.get(layer, -1)

    def focus_on_item(self, item, layer_id=None):
        self.events.append("focus")
        self.focused.append((self.item_bbox(item), layer_id))

    def clear_selected(self):
        self.clear_selected_count += 1

    def clear_brightened(self):
        self.clear_brightened_count += 1

    def set_visible_alls(self):
        pass

    def refresh(self):
        self.events.append("refresh")
        self.refresh_count += 1

    def update_user_interface(self):
        self.events.append("update")
        self.update_count += 1

    def invalidate_item_cache(self):
        self.cache_invalidated += 1

    def create_shape(self):
        return FakeShape()

    def add_board_item(self, item):
        self.events.append("add")
        self.add_shape_count += 1
        if self.board is not None:
            self.board.Add(item)

    def delete_board_item(self, item):
        self.delete_shape_count += 1
        if self.board is not None:
            self.board.Delete(item)

    def set_selected(self, item, selected=True):
        self.events.append("select")
        self.selected_calls.append((item, selected))
        if hasattr(item, "SetSelected"):
            item.SetSelected(selected)

    def set_brightened(self, item, brightened=True):
        self.events.append("brighten")
        self.brightened_calls.append((item, brightened))
        if brightened and hasattr(item, "SetBrightened"):
            item.SetBrightened(brightened)
        elif not brightened and hasattr(item, "ClearBrightened"):
            item.ClearBrightened()

    def warning_layer(self):
        return 99

    def normalize_layers(self, layers):
        normalized = []
        for layer in layers or ():
            if layer is None:
                continue
            try:
                layer = int(layer)
            except (TypeError, ValueError):
                continue
            if layer not in normalized:
                normalized.append(layer)
        return tuple(normalized)

    def visible_layers(self):
        return self.visible_layers_value

    def set_visible_layers(self, layers):
        self.restored_layers.append(layers)


class LocateServiceTest(unittest.TestCase):
    def setUp(self):
        self.original_pcbnew = sys.modules.get("pcbnew")
        fake_pcbnew = types.SimpleNamespace(
            PCB_SHAPE=FakeShape,
            S_RECT=1,
            S_SEGMENT=2,
            LAYER_DRC_WARNING=99,
            Dwgs_User=100,
            COLOR4D=lambda: types.SimpleNamespace(
                FromCSSRGBA=lambda red, green, blue, alpha=1.0: (red, green, blue, alpha)
            ),
        )
        sys.modules["pcbnew"] = fake_pcbnew

    def tearDown(self):
        if self.original_pcbnew is None:
            sys.modules.pop("pcbnew", None)
        else:
            sys.modules["pcbnew"] = self.original_pcbnew

    def test_deferred_focus_uses_union_of_all_marked_item_bounds(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)
        service.begin(defer_focus=True)

        service.show_item(FakeItem((0, 0, 1000, 1000)), focus=False)
        service.show_item(FakeItem((10000, 5000, 12000, 8000)), focus=False)

        self.assertEqual((0, 0, 12000, 8000), service._last_focus_bounds)
        self.assertTrue(service.flush_focus())
        self.assertEqual(1, len(backend.focused))
        left, top, right, bottom = backend.focused[0][0]
        self.assertLessEqual(left, 0)
        self.assertLessEqual(top, 0)
        self.assertGreaterEqual(right, 12000)
        self.assertGreaterEqual(bottom, 8000)

    def test_deferred_focus_includes_unmarked_bulk_items(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)
        service.begin(defer_focus=True)

        service.show_item(FakeItem((0, 0, 1000, 1000)), focus=False, marker=True)
        service.show_item(FakeItem((50000, 60000, 51000, 61000)), focus=False, marker=False)

        self.assertEqual((0, 0, 51000, 61000), service._last_focus_bounds)
        self.assertTrue(service.flush_focus())
        left, top, right, bottom = backend.focused[0][0]
        self.assertLessEqual(left, 0)
        self.assertLessEqual(top, 0)
        self.assertGreaterEqual(right, 51000)
        self.assertGreaterEqual(bottom, 61000)

    def test_show_bbox_deferred_focus_merges_with_item_bounds(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)
        service.begin(defer_focus=True)

        service.show_item(FakeItem((1000, 1000, 2000, 2000)), focus=False)
        service.show_bbox((100000, 200000, 101000, 201000))

        self.assertEqual((1000, 1000, 101000, 201000), service._last_focus_bounds)

    def test_focus_marker_is_deleted_immediately_when_delay_is_zero(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend, focus_marker_cleanup_delay_ms=0)

        self.assertTrue(service.focus_bounds((0, 0, 1000, 1000)))

        self.assertEqual([], service.focus_markers)
        self.assertEqual([], board.items)

    def test_focus_marker_uses_default_delayed_cleanup(self):
        original_wx = sys.modules.get("wx")
        callbacks = []
        sys.modules["wx"] = types.SimpleNamespace(
            CallLater=lambda delay, func, *args: callbacks.append((delay, func, args))
        )
        try:
            board = FakeBoard()
            backend = FakeBackend(board)
            service = LocateService(board, [], [], backend)

            self.assertTrue(service.focus_bounds((0, 0, 1000, 1000)))
            self.assertEqual(1, len(service.focus_markers))
            self.assertEqual(1, len(board.items))

            delay, func, args = callbacks.pop()
            self.assertEqual(250, delay)
            func(*args)

            self.assertEqual([], service.focus_markers)
            self.assertEqual([], board.items)
        finally:
            if original_wx is None:
                sys.modules.pop("wx", None)
            else:
                sys.modules["wx"] = original_wx

    def test_focus_updates_ui_before_focusing_new_marker(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend, focus_marker_cleanup_delay_ms=0)

        self.assertTrue(service.focus_bounds((0, 0, 1000, 1000)))

        self.assertLess(backend.events.index("add"), backend.events.index("focus"))
        self.assertLess(backend.events.index("update"), backend.events.index("focus"))
        self.assertLess(backend.events.index("refresh"), backend.events.index("focus"))
        self.assertEqual([], backend.selected_calls)
        self.assertEqual([], backend.brightened_calls)

    def test_focus_unavailable_keeps_marker_without_backend_focus(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        backend.capabilities = lambda: types.SimpleNamespace(can_focus_native=False)
        service = LocateService(board, [], [], backend, focus_marker_cleanup_delay_ms=0)

        self.assertTrue(service.focus_bounds((0, 0, 1000, 1000)))

        self.assertEqual([], backend.focused)
        self.assertTrue(service.profile["focus_unavailable"])

    def test_marker_shapes_use_green_line_color_when_supported(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)

        shape = service.create_warning_shape()

        self.assertEqual((0, 220, 90, 1.0), shape.line_color)
        self.assertEqual((0, 220, 90, 1.0), shape.fill_color)
        self.assertEqual((0, 220, 90, 1.0), shape.stroke.color)

    def test_focus_marker_can_be_deleted_after_delay(self):
        original_wx = sys.modules.get("wx")
        callbacks = []
        sys.modules["wx"] = types.SimpleNamespace(
            CallLater=lambda delay, func, *args: callbacks.append((delay, func, args))
        )
        try:
            board = FakeBoard()
            backend = FakeBackend(board)
            service = LocateService(
                board,
                [],
                [],
                backend,
                focus_marker_cleanup_delay_ms=25,
            )

            self.assertTrue(service.focus_bounds((0, 0, 1000, 1000)))
            self.assertEqual(1, len(service.focus_markers))
            self.assertEqual(1, len(board.items))

            delay, func, args = callbacks.pop()
            self.assertEqual(25, delay)
            func(*args)

            self.assertEqual([], service.focus_markers)
            self.assertEqual([], board.items)
        finally:
            if original_wx is None:
                sys.modules.pop("wx", None)
            else:
                sys.modules["wx"] = original_wx

    def test_stale_delayed_focus_cleanup_does_not_delete_new_marker(self):
        original_wx = sys.modules.get("wx")
        callbacks = []
        sys.modules["wx"] = types.SimpleNamespace(
            CallLater=lambda delay, func, *args: callbacks.append((delay, func, args))
        )
        try:
            board = FakeBoard()
            backend = FakeBackend(board)
            service = LocateService(
                board,
                [],
                [],
                backend,
                focus_marker_cleanup_delay_ms=25,
            )

            self.assertTrue(service.focus_bounds((0, 0, 1000, 1000)))
            first_marker = service.focus_markers[0]
            self.assertTrue(service.focus_bounds((10000, 10000, 11000, 11000)))
            second_marker = service.focus_markers[-1]

            _delay, func, args = callbacks.pop(0)
            func(*args)

            self.assertNotIn(first_marker, service.focus_markers)
            self.assertIn(second_marker, service.focus_markers)

            _delay, func, args = callbacks.pop(0)
            func(*args)

            self.assertNotIn(second_marker, service.focus_markers)
            self.assertEqual([], service.focus_markers)
        finally:
            if original_wx is None:
                sys.modules.pop("wx", None)
            else:
                sys.modules["wx"] = original_wx

    def test_clear_and_focus_only_refresh_once_each(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)

        service.begin(defer_focus=True)
        self.assertEqual(1, backend.cache_invalidated)
        service.show_item(FakeItem((0, 0, 1000, 1000)), focus=False)
        self.assertEqual(0, backend.refresh_count)
        self.assertGreater(backend.add_shape_count, 0)

        service.clear()
        self.assertEqual(1, backend.refresh_count)
        self.assertEqual(backend.add_shape_count, backend.delete_shape_count)
        self.assertIn("clear_old_state_ms", service.profile)
        self.assertIn("refresh_ms", service.profile)

        service.focus_bounds((0, 0, 1000, 1000))
        self.assertEqual(3, backend.refresh_count)
        self.assertEqual(1, backend.update_count)
        self.assertIn("focus_ms", service.profile)

    def test_clear_always_uses_board_wide_selection_cleanup(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        item = FakeItem((0, 0, 1000, 1000))
        service = LocateService(board, [], [item], backend)

        service.clear(refresh=False)

        self.assertFalse(item.selected)
        self.assertFalse(item.brightened)
        self.assertEqual(1, backend.clear_selected_count)
        self.assertEqual(1, backend.clear_brightened_count)

    def test_begin_clears_previous_state_for_all_native_item_kinds(self):
        class FakeTrack(FakeItem):
            pass

        class FakePad(FakeItem):
            pass

        class FakeVia(FakeItem):
            pass

        class FakeFootprint(FakeItem):
            pass

        class FakeDrawing(FakeItem):
            pass

        class FakeZone(FakeItem):
            pass

        board = FakeBoard()
        backend = FakeBackend(board)
        items = [
            item_type((index * 2000, 0, index * 2000 + 1000, 1000))
            for index, item_type in enumerate(
                (FakeTrack, FakePad, FakeVia, FakeFootprint, FakeDrawing, FakeZone)
            )
        ]
        service = LocateService(board, [], [], backend)
        service.apply_plan(LocatePlan(items=items, focus=False))

        self.assertTrue(all(item.selected and item.brightened for item in items))

        service.begin(defer_focus=True)

        self.assertTrue(all(not item.selected and not item.brightened for item in items))
        self.assertEqual([], service.item_list)

    def test_clear_attempts_brightening_cleanup_when_selection_cleanup_fails(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        item = FakeItem((0, 0, 1000, 1000))
        item.selected = True
        item.brightened = True

        def fail_selection(_item, _selected=True):
            raise RuntimeError("unsupported selection state")

        backend.set_selected = fail_selection
        service = LocateService(board, [], [item], backend)

        service.clear(refresh=False)

        self.assertFalse(item.brightened)
        self.assertEqual([], service.item_list)

    def test_clear_attempts_board_brightening_cleanup_when_selection_api_fails(self):
        board = FakeBoard()
        backend = FakeBackend(board)

        def fail_clear_selected():
            raise RuntimeError("unsupported board selection cleanup")

        backend.clear_selected = fail_clear_selected
        service = LocateService(board, [], [], backend)

        service.clear(refresh=False)

        self.assertEqual(1, backend.clear_brightened_count)

    def test_begin_saves_and_clear_restores_visible_layers(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)

        service.begin(defer_focus=True)
        service.clear()

        self.assertEqual([backend.visible_layers_value], backend.restored_layers)

    def test_deferred_flush_records_total_locate_time(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)

        service.begin(defer_focus=True)
        service.show_bbox((0, 0, 1000, 1000))
        self.assertTrue(service.flush_focus())

        self.assertIn("create_markers_ms", service.profile)
        self.assertIn("focus_ms", service.profile)
        self.assertIn("refresh_ms", service.profile)
        self.assertIn("total_locate_ms", service.profile)

    def test_item_markers_use_uuid_when_available(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)
        item = FakeItem((0, 0, 1000, 1000), item_id="uuid-1")

        service.show_item(item, focus=False)

        self.assertIn("uuid-1", service.item_markers)
        self.assertNotIn(id(item), service.item_markers)

    def test_item_markers_fall_back_to_object_id_without_uuid(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)
        item = FakeItem((0, 0, 1000, 1000))

        service.show_item(item, focus=False)

        self.assertIn(id(item), service.item_markers)

    def test_apply_plan_shows_items_and_bboxes(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        service = LocateService(board, [], [], backend)
        service.begin(defer_focus=True)
        first = FakeItem((0, 0, 1000, 1000), item_id="first")
        second = FakeItem((2000, 0, 3000, 1000), item_id="second")

        shown = service.apply_plan(
            LocatePlan(
                items=[first, second],
                bboxes_nm=[(10000, 10000, 11000, 11000)],
                marker_limit=1,
            )
        )

        self.assertEqual([first, second], shown)
        self.assertIn("first", service.item_markers)
        self.assertNotIn("second", service.item_markers)
        self.assertEqual((0, 0, 11000, 11000), service._last_focus_bounds)

    def test_result_location_planner_plans_native_items(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        item = FakeItem((0, 0, 1000, 1000), item_id="main")
        related = FakeItem((2000, 0, 3000, 1000), item_id="related")
        backend.items_by_id = {"main": item, "related": related}

        plan = ResultLocationPlanner(backend).plan_native_items(
            {"id": "main", "related_id": "related"}
        )

        self.assertEqual([item, related], plan.items)
        self.assertEqual([], plan.bboxes_nm)

    def test_result_location_planner_falls_back_to_bboxes(self):
        board = FakeBoard()
        backend = FakeBackend(board)

        plan = ResultLocationPlanner(backend).plan_native_items(
            {
                "id": "missing",
                "bbox_nm": (1, 2, 3, 4),
                "related_id": "also-missing",
                "related_bbox_nm": (5, 6, 7, 8),
            }
        )

        self.assertEqual([], plan.items)
        self.assertEqual([(1, 2, 3, 4), (5, 6, 7, 8)], plan.bboxes_nm)

    def test_result_location_planner_plans_file_result_shapes(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        calls = []

        def set_segment(shape, result):
            calls.append(result["name"])
            return shape

        plan = ResultLocationPlanner(backend).plan_file_results(
            [{"name": "drawn", "draw": True}, {"name": "skipped", "draw": False}],
            create_shape=backend.create_shape,
            set_segment=set_segment,
            result_width=lambda result: 250000,
            result_layer=lambda result: 7,
            is_drawable=lambda result: result["draw"],
        )

        self.assertEqual(["drawn"], calls)
        self.assertEqual(1, len(plan.temporary_shapes))
        self.assertEqual([7], plan.layers)
        self.assertEqual(250000, plan.temporary_shapes[0].width)
        self.assertTrue(plan.status)

    def test_result_location_planner_plans_drawable_shape(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        shape = FakeShape()

        plan = ResultLocationPlanner(backend).plan_drawable_result(
            {"type": 0},
            create_shape=lambda: shape,
            draw_shape=lambda line, result: line,
            result_layer=lambda result: 3,
        )

        self.assertEqual([shape], plan.temporary_shapes)
        self.assertEqual([3], plan.layers)

    def test_result_location_planner_uses_bbox_when_drawable_missing(self):
        board = FakeBoard()
        backend = FakeBackend(board)

        plan = ResultLocationPlanner(backend).plan_drawable_result(
            {"bbox_nm": (1, 2, 3, 4)},
            create_shape=backend.create_shape,
            draw_shape=lambda line, result: None,
            result_layer=lambda result: 3,
        )

        self.assertEqual([], plan.temporary_shapes)
        self.assertEqual([(1, 2, 3, 4)], plan.bboxes_nm)

    def test_result_location_planner_uses_bbox_after_draw_error(self):
        board = FakeBoard()
        backend = FakeBackend(board)

        def draw_shape(line, result):
            raise KeyError("missing coordinate")

        plan = ResultLocationPlanner(backend).plan_drawable_result(
            {"bbox_nm": (5, 6, 7, 8)},
            create_shape=backend.create_shape,
            draw_shape=draw_shape,
            result_layer=lambda result: 3,
        )

        self.assertEqual([], plan.temporary_shapes)
        self.assertEqual([(5, 6, 7, 8)], plan.bboxes_nm)

    def test_result_location_planner_prefers_items_over_drawable_fallback(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        item = FakeItem((0, 0, 1000, 1000), item_id="main")

        def draw_shape(line, result):
            raise AssertionError("fallback should not be used")

        plan = ResultLocationPlanner(backend).plan_item_or_drawable_results(
            [{"id": "main", "layer": ["F.Cu"]}],
            resolve_items=lambda result: [item],
            create_shape=backend.create_shape,
            draw_shape=draw_shape,
            result_layer=lambda result: 0,
        )

        self.assertEqual([item], plan.items)
        self.assertEqual([], plan.temporary_shapes)
        self.assertIn(0, plan.layers)

    def test_result_location_planner_uses_drawable_fallback_without_items(self):
        board = FakeBoard()
        backend = FakeBackend(board)
        shape = FakeShape()

        plan = ResultLocationPlanner(backend).plan_item_or_drawable_results(
            [{"layer": ["B.Cu"]}],
            resolve_items=lambda result: [],
            create_shape=lambda: shape,
            draw_shape=lambda line, result: line,
            result_layer=lambda result: 31,
        )

        self.assertEqual([], plan.items)
        self.assertEqual([shape], plan.temporary_shapes)
        self.assertIn(31, plan.layers)


if __name__ == "__main__":
    unittest.main()
