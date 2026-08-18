import math
from dataclasses import dataclass


ARC_TESSELLATION_MAX_ERROR_NM = 1000.0


@dataclass
class BackendCapabilities:
    can_plot: bool = False
    can_drill: bool = False
    can_mark: bool = False
    can_highlight: bool = False
    can_focus_native: bool = False
    can_native_drc_marker: bool = False
    can_resolve_item: bool = False
    can_iter_zones: bool = False


class BoardBackend:
    kind = "base"

    def __init__(self, board=None):
        self.board = board

    def version(self):
        return ""

    def capabilities(self):
        return BackendCapabilities()

    def begin_analysis(self):
        """Refresh any board snapshots or caches before an analysis pass."""
        return None

    def board_name(self):
        return ""

    def file_name(self):
        return ""

    def save(self, path=None):
        raise NotImplementedError

    def copper_layer_count(self):
        raise NotImplementedError

    def layer_id(self, layer_name):
        raise NotImplementedError

    def layer_name(self, layer_id):
        raise NotImplementedError

    def canonical_layer_name(self, layer_id):
        """Return the standard KiCad layer name used by DFM rule keys."""
        return self.layer_name(layer_id)

    def vector(self, x, y):
        raise NotImplementedError

    def point(self, x, y):
        return self.vector(x, y)

    def iter_footprints(self):
        return iter(())

    def iter_pads(self, footprint):
        return iter(())

    def iter_tracks(self):
        return iter(())

    def iter_vias(self):
        return iter(())

    def iter_zones(self):
        return iter(())

    def iter_drawings(self):
        return iter(())

    def item_copper_layer_ids(self, item):
        """Return the physical copper-layer stack occupied by ``item``.

        An empty tuple means that the backend cannot provide an authoritative
        layer set.  Callers must retain their geometry fallback in that case.
        """
        return ()

    def pad_copper_layer_ids(self, pad):
        """Return authoritative copper layers for a pad when available.

        ``None`` means that the backend cannot determine pad layer membership.
        An empty tuple is authoritative and means that the pad is a
        paste/mask-only construction with no copper.  This distinction is
        important because KiCad can expose those construction apertures as
        ``PAD`` objects whose fallback ``GetLayer()`` value is F.Cu.
        """
        return None

    def net_tie_pad_groups(self):
        """Return declared net-tie groups as ``(pad_id, net_name)`` pairs.

        Net-tie clearance exemptions are local to the pads declared by the
        footprint.  Returning only net names would incorrectly make those
        nets equivalent everywhere on the board and could hide a real
        clearance violation far away from the net tie.
        """
        return ()

    def net_tie_footprint_pad_ids(self):
        """Return every pad ID owned by a footprint declared as a net tie.

        This footprint-level membership is intentionally broader than
        :meth:`net_tie_pad_groups`: rules that exclude a whole net-tie
        construction must also see helper, netless, and duplicate-number pads.
        """
        return frozenset()

    def net_tie_net_groups(self):
        """Return net names for compatibility with non-geometric callers.

        Geometry checks must use :meth:`net_tie_pad_groups`, because this
        projection deliberately loses the local pad scope.
        """
        groups = []
        for group in self.net_tie_pad_groups():
            net_names = tuple(
                dict.fromkeys(
                    str(member[1] or "")
                    for member in group
                    if isinstance(member, (tuple, list)) and len(member) >= 2
                )
            )
            net_names = tuple(net_name for net_name in net_names if net_name)
            if len(net_names) >= 2:
                groups.append(net_names)
        return tuple(groups)

    def connected_item_ids(self, item):
        """Return KiCad's transitive connectivity component for ``item``.

        ``None`` means native connectivity is unavailable.  A non-empty
        frozenset includes ``item`` itself, including for an isolated item.
        """
        return None

    def connected_copper_layer_ids(self, item):
        """Return copper layers on which ``item`` connects to other copper.

        ``None`` means native connectivity is unavailable; an empty tuple is
        an authoritative result for an electrically isolated item.
        """
        return None

    def zone_polygons(self, zone, layer_id=None):
        return ()

    def zone_name(self, zone):
        if zone is None:
            return ""
        for name in ("GetZoneName", "GetName"):
            if hasattr(zone, name):
                try:
                    return str(getattr(zone, name)() or "")
                except Exception:
                    pass
        return ""

    def is_teardrop_zone(self, zone):
        """Return whether ``zone`` is KiCad-generated teardrop copper."""
        if zone is None:
            return False
        if hasattr(zone, "IsTeardropArea"):
            try:
                if bool(zone.IsTeardropArea()):
                    return True
            except Exception:
                pass
        return self.zone_name(zone) == "$teardrop_padvia$"

    def zone_contains_point(self, zone, point, layer_id=None):
        return None

    def zone_point_distance_nm(self, zone, point, layer_id=None):
        return None

    def item_clearance_nm(self, left, right, max_distance_nm):
        return None

    def item_local_clearance_nm(self, item):
        """Return an item's explicit local-clearance override in nanometres.

        ``None`` means that the backend cannot read the override.  A numeric
        zero is authoritative and must not be confused with an unavailable
        value.
        """
        return None

    def item_to_segment_clearance_nm(
        self,
        item,
        segment,
        layer_id=None,
        max_distance_nm=0,
    ):
        """Return exact item-shape clearance to a zero-width line segment."""
        return None

    def solder_mask_opening_clearance_nm(
        self, left_pad, right_pad, mask_layer_name, max_distance_nm
    ):
        """Exact opening-to-opening distance when the backend supports it."""
        return None

    def solder_mask_opening_bbox_nm(self, pad, mask_layer_name):
        """Bounds of the expanded mask opening when supported."""
        return None

    def solder_mask_opening_to_item_clearance_nm(
        self, pad, item, mask_layer_name, max_distance_nm
    ):
        """Exact mask-opening to copper-item distance when supported."""
        return None

    def item_type(self, item):
        return type(item).__name__

    def create_shape(self):
        pcbnew = None
        try:
            pcbnew = __import__("pcbnew")
        except Exception:
            return None
        return pcbnew.PCB_SHAPE()

    def add_board_item(self, item):
        if self.board is not None and hasattr(self.board, "Add"):
            self.board.Add(item)

    def delete_board_item(self, item):
        if self.board is not None and hasattr(self.board, "Delete"):
            self.board.Delete(item)

    def set_selected(self, item, selected=True):
        if item is None:
            return
        if not selected and hasattr(item, "ClearSelected"):
            try:
                item.ClearSelected()
                return
            except TypeError:
                pass
        if not hasattr(item, "SetSelected"):
            return
        try:
            item.SetSelected(selected)
        except TypeError:
            if selected:
                item.SetSelected()

    def set_brightened(self, item, brightened=True):
        if item is None:
            return
        if not brightened and hasattr(item, "ClearBrightened"):
            item.ClearBrightened()
        elif hasattr(item, "SetBrightened"):
            try:
                item.SetBrightened(brightened)
            except TypeError:
                if brightened:
                    item.SetBrightened()

    def warning_layer(self):
        try:
            pcbnew = __import__("pcbnew")
        except Exception:
            return None
        return getattr(pcbnew, "LAYER_DRC_WARNING", getattr(pcbnew, "Dwgs_User", None))

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
        if self.board is not None and hasattr(self.board, "GetVisibleLayers"):
            try:
                return self.board.GetVisibleLayers()
            except Exception:
                pass
        return None

    def set_visible_layers(self, layers):
        if self.board is not None and hasattr(self.board, "SetVisibleLayers"):
            self.board.SetVisibleLayers(layers)

    def refresh_once(self):
        if self.board is not None and hasattr(self.board, "Refresh"):
            self.board.Refresh()

    def is_pad(self, item):
        return False

    def is_track(self, item):
        return False

    def is_via(self, item):
        return False

    def is_text(self, item):
        return False

    def is_custom_pad(self, item):
        return False

    def text_stroke_polygons(self, item):
        return ()

    def text_stroke_segments(self, item):
        return ()

    def item_id(self, item):
        return str(item.m_Uuid) if hasattr(item, "m_Uuid") else ""

    def item_layer_id(self, item):
        if hasattr(item, "GetLayer"):
            try:
                return item.GetLayer()
            except Exception:
                pass
        if hasattr(item, "GetLayerName"):
            try:
                layer_name = item.GetLayerName()
            except Exception:
                layer_name = ""
            return self.layer_id(layer_name) if layer_name else None
        return None

    def item_layer_name(self, item):
        if hasattr(item, "GetLayerName"):
            try:
                return item.GetLayerName()
            except Exception:
                pass
        layer_id = self.item_layer_id(item)
        if layer_id is not None:
            try:
                return self.layer_name(layer_id)
            except Exception:
                pass
        return ""

    def item_bbox(self, item):
        if not hasattr(item, "GetBoundingBox"):
            return None
        try:
            return self.bbox_bounds(item.GetBoundingBox())
        except Exception:
            return None

    def item_net_name(self, item):
        for name in ("GetNetname", "GetNetName"):
            if hasattr(item, name):
                try:
                    return str(getattr(item, name)() or "")
                except Exception:
                    pass
        if hasattr(item, "GetNet"):
            try:
                net = item.GetNet()
                if hasattr(net, "GetNetname"):
                    return str(net.GetNetname() or "")
            except Exception:
                pass
        return ""

    def pad_size_mm(self, pad):
        size_x = self._call_number(pad, "GetSizeX", None)
        size_y = self._call_number(pad, "GetSizeY", None)
        if size_x is None or size_y is None:
            size = self._call_value(pad, "GetSize", None)
            if size is not None:
                size_x = self._number_attr(size, "x", "GetX", "GetWidth", default=size_x)
                size_y = self._number_attr(size, "y", "GetY", "GetHeight", default=size_y)
        return (
            (size_x or 0) / 1000000.0,
            (size_y or 0) / 1000000.0,
        )

    def pad_drill_mm(self, pad):
        return (
            self._call_number(pad, "GetDrillSizeX", 0) / 1000000.0,
            self._call_number(pad, "GetDrillSizeY", 0) / 1000000.0,
        )

    def pad_attribute(self, pad):
        return self._call_number(pad, "GetAttribute", None)

    def pad_drill_shape(self, pad):
        return self._call_number(pad, "GetDrillShape", None)

    def hole_bbox(self, _hole):
        return None

    def hole_to_segment_clearance_nm(
        self,
        _hole,
        _segment,
        _max_distance_nm,
    ):
        return None

    def pad_shape(self, pad):
        return self._call_number(pad, "GetShape", None)

    def is_smd_pad(self, pad):
        return self.pad_attribute(pad) == 1

    def is_pth_pad(self, pad):
        return self.pad_attribute(pad) == 0

    def is_npth_pad(self, pad):
        return self.pad_attribute(pad) == 3

    def is_bga_pad(self, pad, footprint=None):
        text = " ".join(str(value or "") for value in self.footprint_names(footprint)).upper()
        return "BGA" in text

    def footprint_names(self, footprint):
        if footprint is None:
            return ()
        values = []
        for name in ("GetReference", "GetValue"):
            if hasattr(footprint, name):
                try:
                    values.append(getattr(footprint, name)())
                except Exception:
                    pass
        if hasattr(footprint, "GetFPID"):
            try:
                fpid = footprint.GetFPID()
                if hasattr(fpid, "GetLibItemName"):
                    values.append(fpid.GetLibItemName())
                else:
                    values.append(str(fpid))
            except Exception:
                pass
        return tuple(values)

    def pad_has_solder_mask_opening(self, pad):
        return True

    def board_thickness_mm(self):
        if self.board is None or not hasattr(self.board, "GetDesignSettings"):
            return 0.0
        try:
            settings = self.board.GetDesignSettings()
            if hasattr(settings, "GetBoardThickness"):
                return float(settings.GetBoardThickness()) / 1000000.0
        except Exception:
            pass
        return 0.0

    def board_area_mm2(self):
        """Return the effective board-outline area when the backend can provide it.

        The generic fallback uses the Edge.Cuts bounding box.  SWIG backends
        override this with KiCad's polygonized outline, including cut-outs.
        """
        segments = self.board_outline_segments()
        if not segments:
            return 0.0
        points = [point for segment in segments for point in segment]
        left = min(point[0] for point in points)
        top = min(point[1] for point in points)
        right = max(point[0] for point in points)
        bottom = max(point[1] for point in points)
        return max(0.0, (right - left) * (bottom - top) / 1000000000000.0)

    def pad_is_on_layer(self, pad, layer_name):
        try:
            layer_id = self.layer_id(layer_name)
        except Exception:
            layer_id = None
        for name in ("IsOnLayer", "HasLayer"):
            if layer_id is not None and hasattr(pad, name):
                try:
                    return bool(getattr(pad, name)(layer_id))
                except Exception:
                    pass
        if self.is_pth_pad(pad):
            return layer_name in ("F.Cu", "B.Cu")
        return self.item_layer_name(pad) == layer_name

    def pad_has_solder_mask_opening_on_layer(self, pad, layer_name):
        mask_layer = "F.Mask" if layer_name == "F.Cu" else "B.Mask"
        try:
            layer_id = self.layer_id(mask_layer)
        except Exception:
            layer_id = None
        for name in ("IsOnLayer", "HasLayer"):
            if layer_id is not None and hasattr(pad, name):
                try:
                    return bool(getattr(pad, name)(layer_id))
                except Exception:
                    pass
        return self.pad_has_solder_mask_opening(pad)

    def pad_copper_area_mm2(self, pad, layer_name=None):
        """Approximate pad copper area; SWIG overrides this with exact polygons."""
        size_x, size_y = (abs(value) for value in self.pad_size_mm(pad))
        if size_x <= 0 or size_y <= 0:
            return 0.0
        shape = self.pad_shape(pad)
        if shape == 0:  # circle/ellipse
            return math.pi * size_x * size_y / 4.0
        if shape == 2:  # oval/obround
            short = min(size_x, size_y)
            long = max(size_x, size_y)
            return (long - short) * short + math.pi * short * short / 4.0
        return size_x * size_y

    def via_has_solder_mask_opening_on_layer(self, via, layer_name):
        try:
            layer_id = self.layer_id(layer_name)
        except Exception:
            layer_id = None
        if layer_id is not None and hasattr(via, "IsTented"):
            try:
                return not bool(via.IsTented(layer_id))
            except Exception:
                pass
        return True

    def is_round_drill_pad(self, pad):
        return self.pad_drill_shape(pad) in (None, 0)

    def via_width_mm(self, via):
        return self.item_width(via) / 1000000.0

    def via_drill_mm(self, via):
        return self._call_number(via, "GetDrill", 0) / 1000000.0

    def via_type(self, via):
        return self._call_number(via, "GetViaType", None)

    def via_layer_pair_names(self, via):
        layers = []
        for name in ("TopLayer", "GetTopLayer", "GetLayer"):
            layer_id = self._call_number(via, name, None)
            if layer_id is not None:
                layers.append(self.layer_name(layer_id))
                break
        for name in ("BottomLayer", "GetBottomLayer"):
            layer_id = self._call_number(via, name, None)
            if layer_id is not None:
                layers.append(self.layer_name(layer_id))
                break
        return tuple(layer for layer in layers if layer)

    def is_micro_via(self, via):
        return "micro" in str(self.via_type(via) or "").lower()

    def is_blind_buried_via(self, via):
        via_type = str(self.via_type(via) or "").lower()
        if "blind" in via_type or "buried" in via_type:
            return True
        layers = self.via_layer_pair_names(via)
        return len(layers) == 2 and set(layers) != {"F.Cu", "B.Cu"}

    def item_width(self, item):
        return self._call_number(item, "GetWidth", 0)

    def track_segment(self, track):
        if not (hasattr(track, "GetStart") and hasattr(track, "GetEnd")):
            return None
        start = self.point_xy(track.GetStart())
        end = self.point_xy(track.GetEnd())
        if start is None or end is None:
            return None
        return start, end

    def track_geometry(
        self, track, max_error_nm=ARC_TESSELLATION_MAX_ERROR_NM
    ):
        """Return line or controlled-error arc geometry for local DFM checks."""
        segment = self.track_segment(track)
        if segment is None:
            return {}
        start, end = segment
        line_vectors = (
            (end[0] - start[0], end[1] - start[1]),
            (start[0] - end[0], start[1] - end[1]),
        )
        midpoint = self._track_arc_midpoint(track)
        if midpoint is None:
            if not self._is_straight_segment_shape(track):
                return {
                    "segment": segment,
                    "path": (),
                    "endpoint_vectors": (),
                    "geometry_basis": "kicad_shape_geometry_unavailable",
                }
            return {
                "segment": segment,
                "path": segment,
                "endpoint_vectors": line_vectors,
                "geometry_basis": "exact_kicad",
            }
        geometry = tessellated_arc_geometry(
            start,
            midpoint,
            end,
            max_error_nm=max_error_nm,
        )
        if geometry is None:
            return {
                "segment": segment,
                "path": (),
                "endpoint_vectors": (),
                "geometry_basis": "kicad_arc_geometry_unavailable",
            }
        path, endpoint_vectors = geometry
        return {
            "segment": segment,
            "path": path,
            "endpoint_vectors": endpoint_vectors,
            "geometry_basis": "kicad_arc_tessellated_{0}nm".format(
                int(round(max_error_nm))
            ),
        }

    def _track_arc_midpoint(self, track):
        """Return an arc midpoint without mistaking a straight PCB_SHAPE for an arc.

        PCB_SHAPE exposes GetArcMid for every shape in KiCad 6-10.  Calling it
        on a straight Edge.Cuts line returns a synthetic point, so method
        presence alone is not sufficient to identify an arc.  PCB_ARC and
        older wrappers expose GetMid directly; PCB_SHAPE arcs additionally
        report the stable SHAPE_T_ARC/S_ARC numeric value (2).
        """
        shape = self._call_number(track, "GetShape", None)
        if shape is not None:
            try:
                is_arc_shape = int(shape) == 2
            except (TypeError, ValueError):
                is_arc_shape = str(shape or "").strip().lower() in (
                    "arc",
                    "s_arc",
                    "shape_t_arc",
                )
            if not is_arc_shape:
                return None
        if hasattr(track, "GetMid"):
            try:
                midpoint = self.point_xy(track.GetMid())
            except Exception:
                midpoint = None
            if midpoint is not None:
                return midpoint
        if shape is None or not hasattr(track, "GetArcMid"):
            return None
        try:
            return self.point_xy(track.GetArcMid())
        except Exception:
            return None

    def _is_straight_segment_shape(self, item):
        if not hasattr(item, "GetShape"):
            return True
        shape = self._call_number(item, "GetShape", None)
        try:
            return int(shape) == 0
        except (TypeError, ValueError):
            return str(shape or "").strip().lower() in (
                "line",
                "segment",
                "s_segment",
                "shape_t_segment",
            )

    def item_position(self, item):
        for name in ("GetPosition", "GetCenter", "GetStart"):
            if hasattr(item, name):
                try:
                    point = self.point_xy(getattr(item, name)())
                except Exception:
                    point = None
                if point is not None:
                    return point
        bbox = self.item_bbox(item)
        if bbox:
            left, top, right, bottom = bbox
            return int((left + right) / 2), int((top + bottom) / 2)
        return None

    def point_xy(self, point):
        if point is None:
            return None
        if hasattr(point, "x") and hasattr(point, "y"):
            return int(point.x), int(point.y)
        x = self._call_number(point, "GetX", None)
        y = self._call_number(point, "GetY", None)
        if x is None or y is None:
            return None
        return int(x), int(y)

    def bbox_bounds(self, box):
        if box is None:
            return None
        left = self._call_number(box, "GetLeft", None)
        top = self._call_number(box, "GetTop", None)
        right = self._call_number(box, "GetRight", None)
        bottom = self._call_number(box, "GetBottom", None)
        width = self._call_number(box, "GetWidth", None)
        height = self._call_number(box, "GetHeight", None)
        if left is None:
            left = self._call_number(box, "GetX", None)
        if top is None:
            top = self._call_number(box, "GetY", None)
        if right is None and left is not None and width is not None:
            right = left + width
        if bottom is None and top is not None and height is not None:
            bottom = top + height
        if None in (left, top, right, bottom):
            return None
        return (
            min(int(left), int(right)),
            min(int(top), int(bottom)),
            max(int(left), int(right)),
            max(int(top), int(bottom)),
        )

    def board_outline_segments(self):
        segments = []
        for drawing in self.iter_drawings():
            layer_name = self.item_layer_name(drawing)
            if layer_name and layer_name != "Edge.Cuts":
                continue
            geometry = self.track_geometry(drawing)
            path = tuple(geometry.get("path") or ())
            if len(path) >= 2:
                segments.extend(zip(path, path[1:]))
        return tuple(segments)

    def _call_number(self, obj, name, default):
        return self._call_value(obj, name, default)

    def _call_value(self, obj, name, default):
        if not hasattr(obj, name):
            return default
        try:
            return getattr(obj, name)()
        except Exception:
            return default

    def _number_attr(self, obj, attr_name, *method_names, default=None):
        if hasattr(obj, attr_name):
            try:
                return int(getattr(obj, attr_name))
            except (TypeError, ValueError):
                pass
        for method_name in method_names:
            value = self._call_number(obj, method_name, None)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
        return default

    def resolve_item(self, item_id):
        raise NotImplementedError


def tessellated_arc_geometry(start, midpoint, end, max_error_nm):
    if start is None or midpoint is None or end is None:
        return None
    circle = circle_from_three_points(start, midpoint, end)
    if circle is None:
        return None
    center, radius = circle
    if radius <= 0:
        return None
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    mid_angle = math.atan2(
        midpoint[1] - center[1], midpoint[0] - center[0]
    )
    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
    ccw_total = (end_angle - start_angle) % math.tau
    ccw_mid = (mid_angle - start_angle) % math.tau
    direction = 1 if ccw_mid <= ccw_total + 1e-12 else -1
    path = [start]
    append_tessellated_arc_span(
        path,
        center,
        radius,
        start_angle,
        mid_angle,
        direction,
        midpoint,
        max_error_nm,
    )
    append_tessellated_arc_span(
        path,
        center,
        radius,
        mid_angle,
        end_angle,
        direction,
        end,
        max_error_nm,
    )
    start_radius = (start[0] - center[0], start[1] - center[1])
    end_radius = (end[0] - center[0], end[1] - center[1])
    start_vector = (
        -direction * start_radius[1],
        direction * start_radius[0],
    )
    end_vector = (
        direction * end_radius[1],
        -direction * end_radius[0],
    )
    return tuple(path), (start_vector, end_vector)


def circle_from_three_points(start, midpoint, end):
    bx = float(midpoint[0] - start[0])
    by = float(midpoint[1] - start[1])
    cx = float(end[0] - start[0])
    cy = float(end[1] - start[1])
    determinant = 2.0 * (bx * cy - by * cx)
    if abs(determinant) <= 1e-9:
        return None
    b_squared = bx * bx + by * by
    c_squared = cx * cx + cy * cy
    offset_x = (b_squared * cy - c_squared * by) / determinant
    offset_y = (bx * c_squared - cx * b_squared) / determinant
    center = (start[0] + offset_x, start[1] + offset_y)
    return center, math.hypot(offset_x, offset_y)


def append_tessellated_arc_span(
    path,
    center,
    radius,
    start_angle,
    end_angle,
    direction,
    exact_end,
    max_error_nm,
):
    sweep = directed_angle_delta(start_angle, end_angle, direction)
    count = arc_segment_count(radius, sweep, max_error_nm)
    for index in range(1, count):
        angle = start_angle + sweep * index / float(count)
        point = (
            int(round(center[0] + radius * math.cos(angle))),
            int(round(center[1] + radius * math.sin(angle))),
        )
        if point != path[-1]:
            path.append(point)
    if exact_end != path[-1]:
        path.append(exact_end)


def directed_angle_delta(start_angle, end_angle, direction):
    delta = (end_angle - start_angle) % math.tau
    if direction < 0 and delta > 0:
        delta -= math.tau
    return delta


def arc_segment_count(radius, sweep, max_error_nm):
    error = max(1.0, float(max_error_nm or 0.0))
    if radius <= error:
        maximum_angle = math.pi
    else:
        cosine = max(-1.0, min(1.0, 1.0 - error / radius))
        maximum_angle = 2.0 * math.acos(cosine)
    if maximum_angle <= 1e-12:
        return 1
    return max(1, int(math.ceil(abs(sweep) / maximum_angle)))
