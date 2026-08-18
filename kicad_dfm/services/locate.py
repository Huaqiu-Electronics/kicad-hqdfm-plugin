import time
from dataclasses import dataclass, field

from kicad_dfm.core.errors import LocateError
from kicad_dfm.kicad.swig import SwigBackend
from kicad_dfm.services.focus import FocusService


ZOOM_MARGIN_NM = 2000000
ZOOM_MIN_SPAN_NM = 6000000
MARKER_WIDTH_NM = 150000
TARGET_MIN_SPAN_NM = 2000000
TARGET_MARKER_WIDTH_NM = 300000
DEFAULT_FOCUS_MARKER_CLEANUP_DELAY_MS = 250
MARKER_GREEN_RGBA = (0, 220, 90, 1.0)


@dataclass
class LocatePlan:
    items: list = field(default_factory=list)
    bboxes_nm: list = field(default_factory=list)
    temporary_shapes: list = field(default_factory=list)
    layers: list = field(default_factory=list)
    marker_limit: int = None
    focus: bool = True
    status: str = ""


class ResultLocationPlanner:
    def __init__(self, backend):
        self.backend = backend

    def plan_native_items(self, result):
        items = []
        bboxes_nm = []
        item = self._resolve(result.get("id"))
        related = self._resolve(result.get("related_id"))
        if item is not None:
            items.append(item)
        elif result.get("bbox_nm"):
            bboxes_nm.append(result["bbox_nm"])
        if related is not None:
            items.append(related)
        elif result.get("related_bbox_nm"):
            bboxes_nm.append(result["related_bbox_nm"])
        return LocatePlan(items=items, bboxes_nm=bboxes_nm)

    def plan_file_results(self, results, create_shape, set_segment, result_width, result_layer, is_drawable):
        temporary_shapes = []
        layers = []
        for result in results or ():
            if not is_drawable(result):
                continue
            shape = create_shape()
            shape = set_segment(shape, result)
            width = result_width(result)
            if width:
                shape.SetWidth(width)
            layer = result_layer(result)
            layers.append(layer)
            temporary_shapes.append(shape)
        status = ""
        if temporary_shapes:
            status = "Selected {shown} item(s), marked {markers}.".format(
                shown=len(temporary_shapes),
                markers=len(temporary_shapes),
            )
        return LocatePlan(temporary_shapes=temporary_shapes, layers=layers, status=status)

    def plan_drawable_result(self, result, create_shape, draw_shape, result_layer):
        try:
            shape = draw_shape(create_shape(), result)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            if result.get("bbox_nm"):
                return LocatePlan(bboxes_nm=[result["bbox_nm"]])
            return LocatePlan()
        if shape is not None:
            return LocatePlan(temporary_shapes=[shape], layers=[result_layer(result)])
        if result.get("bbox_nm"):
            return LocatePlan(bboxes_nm=[result["bbox_nm"]])
        return LocatePlan()

    def plan_item_or_drawable_results(self, results, resolve_items, create_shape, draw_shape, result_layer):
        items = []
        bboxes_nm = []
        temporary_shapes = []
        layers = []
        for result in results or ():
            result_items = resolve_items(result)
            if result_items:
                items.extend(result_items)
            else:
                plan = self.plan_drawable_result(result, create_shape, draw_shape, result_layer)
                bboxes_nm.extend(plan.bboxes_nm)
                temporary_shapes.extend(plan.temporary_shapes)
                layers.extend(plan.layers)
            for layer in result.get("layer") or ():
                layer_id = self._layer_id(layer)
                if layer_id is not None:
                    layers.append(layer_id)
        return LocatePlan(items=items, bboxes_nm=bboxes_nm, temporary_shapes=temporary_shapes, layers=layers)

    def _resolve(self, item_id):
        if not item_id:
            return None
        return self.backend.resolve_item(item_id)

    def _layer_id(self, layer):
        if not hasattr(self.backend, "layer_id"):
            return None
        try:
            return self.backend.layer_id(layer)
        except Exception:
            return None


class LocateService:
    def __init__(
        self,
        board,
        line_list=None,
        item_list=None,
        backend=None,
        focus_marker_cleanup_delay_ms=None,
    ):
        self.board = board
        self.line_list = line_list if line_list is not None else []
        self.item_list = item_list if item_list is not None else []
        self.item_markers = {}
        self.focus_markers = []
        self._last_focus_bounds = None
        self._last_focus_layer = None
        self.defer_focus = False
        self._visible_layers = None
        self.profile = {}
        self.backend = backend or SwigBackend(board)
        self.focus_service = FocusService(self.backend)
        if focus_marker_cleanup_delay_ms is None:
            focus_marker_cleanup_delay_ms = DEFAULT_FOCUS_MARKER_CLEANUP_DELAY_MS
        self.focus_marker_cleanup_delay_ms = int(focus_marker_cleanup_delay_ms or 0)
        self._focus_generation = 0
        self._focus_cleanup_timers = []

    def clear(self, refresh=True):
        started_at = time.perf_counter()
        for item in list(self.item_list):
            try:
                self.backend.set_selected(item, False)
            except Exception:
                pass
            try:
                self.backend.set_brightened(item, False)
            except Exception:
                # Selection and brightening are independent KiCad states.
                # Some object types reject one operation, so always attempt
                # both and continue clearing the remaining objects.
                pass
        self.item_list.clear()
        self._clear_board_interaction_state()
        for line in list(self.line_list):
            self.backend.delete_board_item(line)
        self.line_list.clear()
        for marker in list(self.focus_markers):
            self.delete_marker(marker, refresh=False)
        self.focus_markers.clear()
        self.item_markers.clear()
        self._last_focus_bounds = None
        self._last_focus_layer = None
        self.defer_focus = False
        self._focus_generation += 1
        self._focus_cleanup_timers.clear()
        self._restore_visible_layers()
        self._record_profile("clear_old_state_ms", started_at)
        if refresh:
            refresh_started_at = time.perf_counter()
            self.backend.refresh()
            self._record_profile("refresh_ms", refresh_started_at)

    def begin(self, defer_focus=False):
        self.profile = {"total_start": time.perf_counter()}
        self.clear(refresh=False)
        self.defer_focus = defer_focus
        self._save_visible_layers()
        if hasattr(self.backend, "invalidate_item_cache"):
            self.backend.invalidate_item_cache()
        self._clear_board_interaction_state()
        self.backend.set_visible_alls()

    def _clear_board_interaction_state(self):
        for method_name in ("clear_selected", "clear_brightened"):
            try:
                getattr(self.backend, method_name)()
            except Exception:
                # Board-wide APIs vary across KiCad versions and do not cover
                # every child item (notably pads) consistently.  Per-item
                # cleanup above remains the primary cleanup path.
                pass

    def show(self, location):
        if location is None:
            raise LocateError("Missing location")
        item = None
        if getattr(location, "item_id", None):
            started_at = time.perf_counter()
            item = self.backend.resolve_item(location.item_id)
            self._record_profile("resolve_items_ms", started_at)
        if item is None and getattr(location, "raw", None):
            item_id = location.raw.get("id")
            if item_id:
                started_at = time.perf_counter()
                item = self.backend.resolve_item(item_id)
                self._record_profile("resolve_items_ms", started_at)
        if item is not None:
            return self.show_item(item)
        if getattr(location, "bbox_nm", None):
            return self.show_bbox(location.bbox_nm)
        if getattr(location, "x_nm", None) is not None and getattr(location, "y_nm", None) is not None:
            size = 300000
            return self.show_bbox(
                (
                    location.x_nm - size,
                    location.y_nm - size,
                    location.x_nm + size,
                    location.y_nm + size,
                )
            )
        return None

    def show_item(self, item, focus=True, marker=True):
        if item is None:
            return None
        self.backend.set_selected(item, True)
        self.backend.set_brightened(item, True)
        marker = self.add_item_marker(item) if marker else None
        self.item_list.append(item)
        if self.defer_focus and marker is None:
            bounds = self._item_focus_bounds(item)
            if bounds is not None:
                self.focus_bounds(bounds)
        if focus:
            self.focus_item(item)
        return item

    def show_items(self, items, marker_limit=None):
        shown = []
        for index, item in enumerate(items):
            show_marker = marker_limit is None or index < marker_limit
            shown_item = self.show_item(item, focus=False, marker=show_marker)
            if shown_item is not None:
                shown.append(shown_item)
        if shown:
            self.focus_item(shown[-1])
        return shown

    def apply_plan(self, plan):
        shown = []
        marker_limit = plan.marker_limit
        for index, item in enumerate(plan.items):
            show_marker = marker_limit is None or index < marker_limit
            shown_item = self.show_item(item, focus=False, marker=show_marker)
            if shown_item is not None:
                shown.append(shown_item)
        for bbox in plan.bboxes_nm:
            self.show_bbox(bbox)
        for index, shape in enumerate(plan.temporary_shapes):
            focus_layer = plan.layers[index] if index < len(plan.layers) else None
            self.add_temporary_shape(shape, focus_layer)
        if plan.focus and shown:
            self.focus_item(shown[-1])
        return shown

    def show_bbox(self, bbox_nm):
        if not bbox_nm:
            return None
        marker = self._rect_marker(
            self._target_bounds(bbox_nm),
            width=TARGET_MARKER_WIDTH_NM,
        )
        return self.add_temporary_shape(marker, focus_bounds=bbox_nm)

    def focus_item(self, item):
        if self.focus_marker_for_item(item):
            return
        if self.defer_focus:
            bounds = self._item_focus_bounds(item)
            if bounds is not None:
                self.focus_bounds(bounds)
                return
        self.focus_service.focus_item(item, profile=self.profile)

    def create_warning_shape(self):
        started_at = time.perf_counter()
        line = self.backend.create_shape()
        line.GetLayerSet()
        line.SetLayer(self.backend.warning_layer())
        line.SetWidth(100000)
        self._set_marker_color(line)
        self._record_profile("create_markers_ms", started_at)
        return line

    def add_temporary_shape(self, line, focus_layer=None, focus_bounds=None):
        started_at = time.perf_counter()
        self.backend.add_board_item(line)
        self.line_list.append(line)
        self._record_profile("create_markers_ms", started_at)
        bounds = focus_bounds or self.backend.item_bbox(line)
        if bounds:
            self.focus_bounds(bounds, focus_layer)
        else:
            self.focus_service.focus_item(line, focus_layer, self.profile)
        return line

    def add_item_marker(self, item):
        try:
            markers, _focus_marker = self.create_item_markers(item)
        except Exception:
            markers, _focus_marker = (), None
        if not markers:
            return None
        started_at = time.perf_counter()
        for marker in markers:
            self.backend.add_board_item(marker)
            self.line_list.append(marker)
        self._record_profile("create_markers_ms", started_at)
        focus_bounds = self._item_focus_bounds(item)
        if focus_bounds is not None:
            self.item_markers[self._item_marker_key(item)] = (
                "focus_bounds",
                focus_bounds,
                markers[-1],
            )
            if self.defer_focus:
                self.focus_bounds(focus_bounds)
        else:
            self.item_markers[self._item_marker_key(item)] = markers[-1]
        return markers[0]

    def focus_bounds(self, bounds, focus_layer=None, remember=True, force=False):
        bounds = tuple(int(value) for value in bounds)
        if remember:
            if self.defer_focus and not force and self._last_focus_bounds:
                bounds = self._merge_bounds(self._last_focus_bounds, bounds)
            self._last_focus_bounds = tuple(bounds)
            self._last_focus_layer = focus_layer
        if self.defer_focus and not force:
            return True
        marker = self._focus_marker(bounds)
        if marker is None:
            return False
        self.focus_with_temporary_marker(marker, focus_layer)
        return True

    def refocus_last(self):
        if not self._last_focus_bounds:
            return False
        return self.focus_bounds(
            self._last_focus_bounds,
            self._last_focus_layer,
            remember=False,
            force=True,
        )

    def flush_focus(self):
        self.defer_focus = False
        focused = self.refocus_last()
        if "total_start" in self.profile:
            self.profile["total_locate_ms"] = self._elapsed_ms(self.profile["total_start"])
        return focused

    def focus_with_temporary_marker(self, marker, focus_layer=None):
        started_at = time.perf_counter()
        self._focus_generation += 1
        generation = self._focus_generation
        self.backend.add_board_item(marker)
        self.focus_markers.append(marker)
        try:
            self.backend.update_user_interface()
            self.backend.refresh()
            self.focus_service.focus_item(marker, focus_layer, self.profile)
        finally:
            self.delete_marker_after_focus(marker, generation)
            self._record_profile("focus_ms", started_at)
            refresh_started_at = time.perf_counter()
            self.backend.refresh()
            self._record_profile("refresh_ms", refresh_started_at)

    def delete_marker_after_focus(self, marker, generation=None):
        if self.focus_marker_cleanup_delay_ms <= 0:
            self._delete_focus_marker_if_current(marker, generation)
            return
        try:
            import wx
        except Exception:
            self._delete_focus_marker_if_current(marker, generation)
            return
        if hasattr(wx, "CallLater"):
            timer = None

            def cleanup():
                self._delete_focus_marker_if_current(marker, generation)
                try:
                    self._focus_cleanup_timers.remove(timer)
                except ValueError:
                    pass

            try:
                timer = wx.CallLater(self.focus_marker_cleanup_delay_ms, cleanup)
                self._focus_cleanup_timers.append(timer)
                return
            except Exception:
                self._delete_focus_marker_if_current(marker, generation)
                return
        self._delete_focus_marker_if_current(marker, generation)

    def _delete_focus_marker_if_current(self, marker, generation=None):
        if generation is not None and generation > self._focus_generation:
            return
        self.delete_marker(marker, refresh=False)

    def delete_marker(self, marker, refresh=True):
        try:
            self.backend.delete_board_item(marker)
        except Exception:
            pass
        try:
            self.focus_markers.remove(marker)
        except ValueError:
            pass
        if refresh:
            self.backend.refresh()

    def focus_marker_for_item(self, item):
        marker = self.item_markers.get(self._item_marker_key(item))
        if isinstance(marker, tuple) and marker[0] == "focus_bounds":
            focus_bounds, fallback = marker[1], marker[2]
            try:
                return self.focus_bounds(focus_bounds)
            except Exception:
                self.focus_service.focus_item(fallback, profile=self.profile)
                return True
        if marker is not None:
            self.focus_service.focus_item(marker, profile=self.profile)
            return True
        return False

    def _item_marker_key(self, item):
        item_id = self.backend.item_id(item) if hasattr(self.backend, "item_id") else ""
        return item_id or id(item)

    def create_item_markers(self, item):
        markers = []
        if hasattr(item, "GetStart") and hasattr(item, "GetEnd"):
            exact = self._track_marker(item)
        else:
            exact = self._target_marker(item)
        if exact is not None:
            markers.append(exact)
        if hasattr(item, "GetStart") and hasattr(item, "GetEnd"):
            target = self._target_marker(item)
            if target is not None:
                markers.append(target)
        focus = self._box_marker(item)
        return markers, focus

    def _track_marker(self, item):
        start = self._point_xy(item.GetStart())
        end = self._point_xy(item.GetEnd())
        if start is None or end is None:
            return self._target_marker(item)
        marker = self.create_warning_shape()
        marker.SetShape(_pcbnew().S_SEGMENT)
        marker.SetStartX(start[0])
        marker.SetStartY(start[1])
        marker.SetEndX(end[0])
        marker.SetEndY(end[1])
        if hasattr(item, "GetWidth"):
            marker.SetWidth(max(int(self.backend.item_width(item)) * 3, 300000))
            self._set_marker_color(marker)
        return marker

    def _box_marker(self, item):
        bounds = self._item_focus_bounds(item)
        if bounds is None:
            return None
        bounds = self._zoom_bounds(bounds)
        return self._rect_marker(bounds, width=MARKER_WIDTH_NM)

    def _target_marker(self, item):
        box = item.GetBoundingBox() if hasattr(item, "GetBoundingBox") else None
        bounds = self._raw_box_bounds(box)
        if bounds is None:
            point = self._item_point(item)
            if point is None:
                return None
            x, y = point
            bounds = (x, y, x, y)
        return self._rect_marker(
            self._target_bounds(bounds),
            width=TARGET_MARKER_WIDTH_NM,
        )

    def _focus_marker(self, bounds):
        if not bounds:
            return None
        return self._rect_marker(self._zoom_bounds(bounds), width=MARKER_WIDTH_NM)

    def _rect_marker(self, bounds, width):
        left, top, right, bottom = bounds
        marker = self.create_warning_shape()
        marker.SetShape(_pcbnew().S_RECT)
        marker.SetStartX(int(left))
        marker.SetStartY(int(top))
        marker.SetEndX(int(right))
        marker.SetEndY(int(bottom))
        marker.SetWidth(width)
        self._set_marker_color(marker)
        return marker

    def _raw_box_bounds(self, box):
        if box is None:
            return None
        left = self._call_first(box, "GetLeft", "GetX")
        top = self._call_first(box, "GetTop", "GetY")
        right = self._call_first(box, "GetRight")
        bottom = self._call_first(box, "GetBottom")
        width = self._call_first(box, "GetWidth")
        height = self._call_first(box, "GetHeight")
        if right is None and left is not None and width is not None:
            right = left + width
        if bottom is None and top is not None and height is not None:
            bottom = top + height
        if None in (left, top, right, bottom):
            return None
        return (
            min(left, right),
            min(top, bottom),
            max(left, right),
            max(top, bottom),
        )

    def _target_bounds(self, bounds):
        left, top, right, bottom = (int(value) for value in bounds)
        left, right = min(left, right), max(left, right)
        top, bottom = min(top, bottom), max(top, bottom)
        width = max(right - left, 0)
        height = max(bottom - top, 0)
        center_x = int((left + right) / 2)
        center_y = int((top + bottom) / 2)
        half_width = int(max(width, TARGET_MIN_SPAN_NM) / 2)
        half_height = int(max(height, TARGET_MIN_SPAN_NM) / 2)
        return (
            center_x - half_width,
            center_y - half_height,
            center_x + half_width,
            center_y + half_height,
        )

    def _zoom_bounds(self, bounds):
        left, top, right, bottom = (int(value) for value in bounds)
        left, right = min(left, right), max(left, right)
        top, bottom = min(top, bottom), max(top, bottom)
        width = max(right - left, 0)
        height = max(bottom - top, 0)
        center_x = int((left + right) / 2)
        center_y = int((top + bottom) / 2)
        half_width = int(max(width + ZOOM_MARGIN_NM * 2, ZOOM_MIN_SPAN_NM) / 2)
        half_height = int(max(height + ZOOM_MARGIN_NM * 2, ZOOM_MIN_SPAN_NM) / 2)
        return (
            center_x - half_width,
            center_y - half_height,
            center_x + half_width,
            center_y + half_height,
        )

    def _merge_bounds(self, left_bounds, right_bounds):
        left_a, top_a, right_a, bottom_a = (int(value) for value in left_bounds)
        left_b, top_b, right_b, bottom_b = (int(value) for value in right_bounds)
        return (
            min(left_a, left_b),
            min(top_a, top_b),
            max(right_a, right_b),
            max(bottom_a, bottom_b),
        )

    def _item_focus_bounds(self, item):
        bounds = self.backend.item_bbox(item)
        if bounds is not None:
            return bounds
        point = self._item_point(item)
        if point is None:
            return None
        x, y = point
        return (x, y, x, y)

    def _item_point(self, item):
        for name in ("GetPosition", "GetCenter", "GetStart"):
            if hasattr(item, name):
                point = self._point_xy(getattr(item, name)())
                if point is not None:
                    return point
        return None

    def _point_xy(self, point):
        if point is None:
            return None
        if hasattr(point, "x") and hasattr(point, "y"):
            return int(point.x), int(point.y)
        x = self._call_first(point, "GetX")
        y = self._call_first(point, "GetY")
        if x is not None and y is not None:
            return int(x), int(y)
        return None

    def _call_first(self, obj, *names):
        for name in names:
            if hasattr(obj, name):
                return int(getattr(obj, name)())
        return None

    def hide_unrelated_layers(self, layer_nums):
        started_at = time.perf_counter()
        normalized_layers = list(self.backend.normalize_layers(layer_nums))
        warning_layer = self.backend.warning_layer()
        if warning_layer is not None and warning_layer not in normalized_layers:
            normalized_layers.append(warning_layer)
        gal_set = self.backend.visible_layers()
        if gal_set is None:
            return
        for num in [layer for layer in gal_set.Seq()]:
            if num not in normalized_layers:
                gal_set.removeLayer(num)
        self.backend.set_visible_layers(gal_set)
        self.backend.update_user_interface()
        self._record_profile("layer_visibility_ms", started_at)

    def _save_visible_layers(self):
        self._visible_layers = self.backend.visible_layers()

    def _restore_visible_layers(self):
        if self._visible_layers is None:
            return
        try:
            self.backend.set_visible_layers(self._visible_layers)
        except Exception:
            pass
        self._visible_layers = None

    def _record_profile(self, name, started_at):
        self.profile[name] = self.profile.get(name, 0.0) + self._elapsed_ms(started_at)

    def _elapsed_ms(self, started_at):
        return round((time.perf_counter() - started_at) * 1000.0, 3)

    def _set_marker_color(self, marker):
        color = self._marker_color()
        if color is None:
            return
        try:
            stroke = marker.GetStroke()
            if hasattr(stroke, "SetColor"):
                stroke.SetColor(color)
                if hasattr(marker, "SetStroke"):
                    marker.SetStroke(stroke)
        except Exception:
            pass
        for name in ("SetLineColor", "SetFillColor"):
            if hasattr(marker, name):
                try:
                    getattr(marker, name)(color)
                except Exception:
                    pass

    def _marker_color(self):
        try:
            pcbnew = _pcbnew()
            color_class = getattr(pcbnew, "COLOR4D", None)
            if color_class is None:
                return None
            color = color_class()
            if hasattr(color, "FromCSSRGBA"):
                converted = color.FromCSSRGBA(*MARKER_GREEN_RGBA)
                return converted if converted is not None else color
            if hasattr(color, "SetFromHexString"):
                color.SetFromHexString("#00DC5A")
                return color
        except Exception:
            return None
        return None


def _pcbnew():
    import pcbnew

    return pcbnew
