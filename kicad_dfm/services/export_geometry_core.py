import math


class GerberAperture:
    __slots__ = (
        "shape",
        "values",
        "hole",
        "vertices",
        "rotation",
        "offset",
        "macro_primitives",
        "logical_size",
        "function",
    )

    def __init__(
        self,
        shape,
        values,
        hole=None,
        vertices=None,
        rotation=0.0,
        offset=None,
        macro_primitives=None,
        logical_size=None,
        function="",
    ):
        self.shape = str(shape or "").upper()
        self.values = tuple(values or ())
        self.hole = hole
        self.vertices = vertices
        self.rotation = float(rotation or 0.0)
        self.offset = offset or (0.0, 0.0)
        self.macro_primitives = tuple(macro_primitives or ())
        self.logical_size = tuple(logical_size or ())
        self.function = str(function or "")

    @property
    def width(self):
        if not self.values:
            return None
        if self.shape.startswith(("C", "P")):
            return self.values[0]
        if self.shape.startswith(("R", "O")) and len(self.values) >= 2:
            return min(self.values[0], self.values[1])
        return min(self.values)

    @property
    def size(self):
        if not self.values:
            return None
        width = self.values[0]
        height = self.values[1] if len(self.values) > 1 and not self.shape.startswith(("C", "P")) else width
        return width, height


class GerberSegment:
    __slots__ = ("start", "end", "width", "bbox")

    def __init__(self, start, end, width=0.0):
        self.start = start
        self.end = end
        self.width = width
        self.bbox = segment_bbox(start, end)


class GerberPrimitive:
    __slots__ = (
        "kind",
        "start",
        "end",
        "center",
        "width",
        "height",
        "shape_width",
        "shape_height",
        "is_flash",
        "bbox",
        "points",
        "holes",
        "edges",
        "edge_index",
        "edge_segments",
        "edge_segment_index",
        "net",
        "function",
        "component",
        "object_id",
        "flash_id",
        "members",
        "coordinate_resolution_mm",
    )

    def __init__(
        self,
        kind,
        start=None,
        end=None,
        center=None,
        width=0.0,
        height=0.0,
        is_flash=False,
        points=None,
        holes=None,
        net="",
        function="",
        component="",
        object_id="",
        flash_id="",
        members=None,
        coordinate_resolution_mm=None,
    ):
        self.kind = kind
        self.start = start
        self.end = end
        self.center = center
        self.width = float(width or 0.0)
        self.height = float(height or self.width)
        self.shape_width = self.width
        self.shape_height = self.height
        self.is_flash = bool(is_flash)
        self.net = str(net or "")
        self.function = str(function or "")
        self.component = str(component or "")
        self.object_id = str(object_id or "")
        self.flash_id = str(flash_id or "")
        self.members = tuple(members or ())
        self.coordinate_resolution_mm = (
            float(coordinate_resolution_mm)
            if coordinate_resolution_mm is not None
            else None
        )
        self.points = tuple(points or ())
        self.holes = tuple(tuple(contour) for contour in (holes or ()))
        self.edges = None
        self.edge_index = None
        self.edge_segments = None
        self.edge_segment_index = None
        if self.kind == "obround":
            self.start, self.end, self.width = obround_axis(center, self.width, self.height)
            self.height = self.width
        self.bbox = self._bbox()
        if self.kind == "composite":
            if self.center is None:
                self.center = (
                    (self.bbox[0] + self.bbox[2]) / 2.0,
                    (self.bbox[1] + self.bbox[3]) / 2.0,
                )
            if self.shape_width <= 0:
                self.shape_width = self.bbox[2] - self.bbox[0]
            if self.shape_height <= 0:
                self.shape_height = self.bbox[3] - self.bbox[1]

    def _bbox(self):
        if self.kind == "composite" and self.members:
            return (
                min(member.bbox[0] for member in self.members),
                min(member.bbox[1] for member in self.members),
                max(member.bbox[2] for member in self.members),
                max(member.bbox[3] for member in self.members),
            )
        if self.kind in ("segment", "obround"):
            radius = self.width / 2.0
            bbox = segment_bbox(self.start, self.end)
            return expand_bbox(bbox, radius)
        if self.kind == "region":
            return (self.start[0], self.start[1], self.end[0], self.end[1])
        half_w = self.width / 2.0
        half_h = self.height / 2.0
        return (
            self.center[0] - half_w,
            self.center[1] - half_h,
            self.center[0] + half_w,
            self.center[1] + half_h,
        )

    def location_segment(self):
        if self.kind in ("segment", "obround"):
            return self.start, self.end
        if self.kind == "region":
            cy = (self.bbox[1] + self.bbox[3]) / 2.0
            return (self.bbox[0], cy), (self.bbox[2], cy)
        return (self.bbox[0], self.center[1]), (self.bbox[2], self.center[1])


class DrillPrimitive:
    __slots__ = (
        "kind",
        "center",
        "start",
        "end",
        "diameter",
        "width",
        "bbox",
        "coordinate_resolution_mm",
        "function",
        "tool",
    )

    def __init__(
        self,
        kind,
        center=None,
        start=None,
        end=None,
        diameter=0.0,
        coordinate_resolution_mm=None,
        function="",
        tool="",
    ):
        self.kind = kind
        self.center = center
        self.start = start
        self.end = end
        self.diameter = float(diameter or 0.0)
        self.width = self.diameter
        self.coordinate_resolution_mm = (
            float(coordinate_resolution_mm)
            if coordinate_resolution_mm is not None
            else None
        )
        self.function = str(function or "")
        self.tool = str(tool or "")
        self.bbox = self._bbox()

    def _bbox(self):
        radius = self.diameter / 2.0
        if self.kind == "slot":
            return expand_bbox(segment_bbox(self.start, self.end), radius)
        return (
            self.center[0] - radius,
            self.center[1] - radius,
            self.center[0] + radius,
            self.center[1] + radius,
        )

    def location_segment(self):
        if self.kind == "slot":
            return self.start, self.end
        radius = max(self.diameter / 2.0, 0.15)
        return (self.center[0] - radius, self.center[1]), (self.center[0] + radius, self.center[1])


def obround_axis(center, width, height):
    width = float(width or 0.0)
    height = float(height or width)
    diameter = min(width, height)
    if width >= height:
        half = max(0.0, (width - diameter) / 2.0)
        return (center[0] - half, center[1]), (center[0] + half, center[1]), diameter
    half = max(0.0, (height - diameter) / 2.0)
    return (center[0], center[1] - half), (center[0], center[1] + half), diameter


def distance(left, right):
    return math.sqrt((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2)


def gerber_arc_segments(
    start,
    end,
    offset,
    direction,
    quadrant_mode="multi",
    max_sagitta=None,
):
    center = gerber_arc_center(start, end, offset, direction, quadrant_mode)
    radius = distance(start, center)
    if radius <= 0:
        return []
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    delta = gerber_arc_delta(start, end, center, direction)
    if max_sagitta is not None and 0 < float(max_sagitta) < radius:
        # Bound the chord error instead of using a fixed angle.  A fixed 10°
        # step produces more than 0.1 mm of error on the large curved outline
        # used by amulet_controller_9, which is large enough to change a DFM
        # board-edge rule result.
        cosine = max(-1.0, min(1.0, 1.0 - float(max_sagitta) / radius))
        max_step_angle = 2.0 * math.acos(cosine)
        steps = max(2, min(4096, int(math.ceil(abs(delta) / max_step_angle))))
    else:
        steps = max(2, min(96, int(math.ceil(abs(delta) / (math.pi / 18.0)))))
    points = [start]
    for step in range(1, steps):
        angle = start_angle + delta * step / steps
        points.append((center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius))
    points.append(end)
    return list(zip(points, points[1:]))


def gerber_arc_center(start, end, offset, direction, quadrant_mode):
    if quadrant_mode != "single":
        return start[0] + offset[0], start[1] + offset[1]
    best = None
    for x_sign in (-1.0, 1.0):
        for y_sign in (-1.0, 1.0):
            center = (start[0] + offset[0] * x_sign, start[1] + offset[1] * y_sign)
            delta = gerber_arc_delta(start, end, center, direction)
            radius_error = abs(distance(start, center) - distance(end, center))
            if abs(delta) <= math.pi / 2.0 + 1e-9:
                score = (radius_error, abs(delta))
                if best is None or score < best[0]:
                    best = (score, center)
    if best is not None:
        return best[1]
    return start[0] + offset[0], start[1] + offset[1]


def gerber_arc_delta(start, end, center, direction):
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
    delta = end_angle - start_angle
    if direction == "cw":
        if delta >= 0:
            delta -= math.tau
    elif delta <= 0:
        delta += math.tau
    return delta


def add_region_primitive(
    scan,
    points,
    target=None,
    net="",
    function="",
    component="",
    object_id="",
    holes=None,
):
    if not points or len(points) < 3:
        return
    points = simplify_polygon_points(tuple(points))
    if len(points) < 3:
        return
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    if bbox[0] == bbox[2] or bbox[1] == bbox[3]:
        return
    target = target if target is not None else scan.primitives
    target.append(
        GerberPrimitive(
            "region",
            start=(bbox[0], bbox[1]),
            end=(bbox[2], bbox[3]),
            points=points,
            holes=holes,
            net=net,
            function=function,
            component=component,
            object_id=object_id,
        )
    )


def simplify_polygon_points(points):
    if len(points) < 3:
        return tuple(points)

    deduped = []
    for point in points:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    if len(deduped) > 1 and deduped[0] == deduped[-1]:
        deduped.pop()
    if len(deduped) < 3:
        return tuple(deduped)

    simplified = []
    for point in deduped:
        simplified.append(point)
        while (
            len(simplified) >= 3
            and point_on_collinear_segment(simplified[-2], simplified[-3], simplified[-1])
        ):
            del simplified[-2]
    simplify_closed_polygon_endpoints(simplified)
    return tuple(simplified)


def simplify_closed_polygon_endpoints(points):
    changed = True
    while changed and len(points) >= 3:
        changed = False
        if point_on_collinear_segment(points[0], points[-1], points[1]):
            del points[0]
            changed = True
            continue
        if point_on_collinear_segment(points[-1], points[-2], points[0]):
            points.pop()
            changed = True


def point_on_collinear_segment(point, start, end):
    value = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])
    if abs(value) >= 1e-9:
        return False
    return (
        min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
        and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
    )


def segment_bbox(start, end):
    return (
        min(start[0], end[0]),
        min(start[1], end[1]),
        max(start[0], end[0]),
        max(start[1], end[1]),
    )


def expand_bbox(bbox, margin):
    margin = float(margin or 0.0)
    return (
        bbox[0] - margin,
        bbox[1] - margin,
        bbox[2] + margin,
        bbox[3] + margin,
    )


def bbox_gap(left, right):
    dx = max(0.0, max(left[0], right[0]) - min(left[2], right[2]))
    dy = max(0.0, max(left[1], right[1]) - min(left[3], right[3]))
    if dx <= 0:
        return dy
    if dy <= 0:
        return dx
    return math.sqrt(dx * dx + dy * dy)


def segment_distance(left_start, left_end, right_start, right_end):
    if segments_intersect(left_start, left_end, right_start, right_end):
        return 0.0
    return min(
        point_to_segment_distance(left_start, right_start, right_end),
        point_to_segment_distance(left_end, right_start, right_end),
        point_to_segment_distance(right_start, left_start, left_end),
        point_to_segment_distance(right_end, left_start, left_end),
    )


def point_to_segment_distance(point, start, end):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return distance(point, start)
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    closest = (start[0] + t * dx, start[1] + t * dy)
    return distance(point, closest)


def primitive_segment_gap(primitive, segment):
    if primitive.kind == "composite":
        return min(
            (primitive_segment_gap(member, segment) for member in primitive.members),
            default=math.inf,
        )
    if primitive.kind == "region":
        return region_to_segment_gap(primitive, segment.start, segment.end)
    if primitive.kind in ("segment", "obround"):
        return max(
            0.0,
            segment_distance(primitive.start, primitive.end, segment.start, segment.end)
            - primitive.width / 2.0,
        )
    if primitive.kind == "circle":
        return max(
            0.0,
            point_to_segment_distance(primitive.center, segment.start, segment.end)
            - primitive.width / 2.0,
        )
    return rect_to_segment_distance(primitive.bbox, segment.start, segment.end)


def primitive_gap(left, right):
    if left.kind == "composite":
        return min(
            (primitive_gap(member, right) for member in left.members),
            default=bbox_gap(left.bbox, right.bbox),
        )
    if right.kind == "composite":
        return min(
            (primitive_gap(left, member) for member in right.members),
            default=bbox_gap(left.bbox, right.bbox),
        )
    if left.kind == "region":
        return region_to_primitive_gap(left, right)
    if right.kind == "region":
        return region_to_primitive_gap(right, left)
    if left.kind in ("segment", "obround") and right.kind in ("segment", "obround"):
        return max(
            0.0,
            segment_distance(left.start, left.end, right.start, right.end)
            - left.width / 2.0
            - right.width / 2.0,
        )
    if left.kind in ("segment", "obround"):
        return segment_to_primitive_gap(left, right)
    if right.kind in ("segment", "obround"):
        return segment_to_primitive_gap(right, left)
    if left.kind == "circle" and right.kind == "circle":
        return max(0.0, distance(left.center, right.center) - left.width / 2.0 - right.width / 2.0)
    if left.kind == "circle":
        return circle_rect_gap(left, right.bbox)
    if right.kind == "circle":
        return circle_rect_gap(right, left.bbox)
    return rect_to_rect_distance(left.bbox, right.bbox)


def primitive_gap_within(left, right, max_gap):
    """Return the exact gap when it can be at most ``max_gap``.

    Region distance is otherwise proportional to the product of polygon edge
    counts.  DFM scanners always have a reporting threshold, so an edge grid
    can safely discard pairs that cannot influence the result.
    """
    max_gap = max(0.0, float(max_gap or 0.0))
    if bbox_gap(left.bbox, right.bbox) > max_gap:
        return math.inf
    if left.kind == "composite":
        return min(
            (
                primitive_gap_within(member, right, max_gap)
                for member in left.members
            ),
            default=math.inf,
        )
    if right.kind == "composite":
        return min(
            (
                primitive_gap_within(left, member, max_gap)
                for member in right.members
            ),
            default=math.inf,
        )
    if left.kind == "region":
        return region_to_primitive_gap_within(left, right, max_gap)
    if right.kind == "region":
        return region_to_primitive_gap_within(right, left, max_gap)
    value = primitive_gap(left, right)
    return value if value <= max_gap else math.inf


def region_to_primitive_gap_within(region, primitive, max_gap):
    if primitive.kind in ("segment", "obround"):
        radius = primitive.width / 2.0
        value = region_to_segment_gap_within(
            region, primitive.start, primitive.end, max_gap + radius
        )
        value = max(0.0, value - radius)
    elif primitive.kind == "circle":
        radius = primitive.width / 2.0
        value = region_to_point_gap_within(region, primitive.center, max_gap + radius)
        value = max(0.0, value - radius)
    elif primitive.kind == "region":
        value = region_to_region_gap_within(region, primitive, max_gap)
    else:
        value = region_to_rect_gap_within(region, primitive.bbox, max_gap)
    return value if value <= max_gap else math.inf


def drill_to_primitive_gap(drill, primitive):
    if drill.kind == "slot":
        slot = GerberPrimitive(
            "segment",
            start=drill.start,
            end=drill.end,
            width=drill.diameter,
        )
        return primitive_gap(slot, primitive)
    circle = GerberPrimitive("circle", center=drill.center, width=drill.diameter)
    return primitive_gap(circle, primitive)


def segment_to_primitive_gap(segment, primitive):
    if primitive.kind == "region":
        return max(0.0, polygon_to_segment_gap(primitive.points, segment.start, segment.end) - segment.width / 2.0)
    if primitive.kind == "circle":
        return max(
            0.0,
            point_to_segment_distance(primitive.center, segment.start, segment.end)
            - primitive.width / 2.0
            - segment.width / 2.0,
        )
    return max(0.0, rect_to_segment_distance(primitive.bbox, segment.start, segment.end) - segment.width / 2.0)


def circle_rect_gap(circle, rect):
    closest_x = min(max(circle.center[0], rect[0]), rect[2])
    closest_y = min(max(circle.center[1], rect[1]), rect[3])
    return max(0.0, distance(circle.center, (closest_x, closest_y)) - circle.width / 2.0)


def rect_to_rect_distance(left, right):
    return bbox_gap(left, right)


def region_to_primitive_gap(region, primitive):
    if primitive.kind in ("segment", "obround"):
        return max(0.0, region_to_segment_gap(region, primitive.start, primitive.end) - primitive.width / 2.0)
    if primitive.kind == "circle":
        return max(0.0, region_to_point_gap(region, primitive.center) - primitive.width / 2.0)
    if primitive.kind == "region":
        return region_to_region_gap(region, primitive)
    return region_to_rect_gap(region, primitive.bbox)


def primitive_pair_kind(left, right):
    if left.is_flash and right.is_flash:
        return "pad"
    return "trace"


def spacing_location(left, right):
    left_point = primitive_center(left)
    right_point = primitive_center(right)
    return left_point, right_point


def primitive_center(primitive):
    if primitive.center is not None:
        return primitive.center
    if primitive.kind == "region":
        return ((primitive.bbox[0] + primitive.bbox[2]) / 2.0, (primitive.bbox[1] + primitive.bbox[3]) / 2.0)
    if primitive.kind == "composite":
        return ((primitive.bbox[0] + primitive.bbox[2]) / 2.0, (primitive.bbox[1] + primitive.bbox[3]) / 2.0)
    return ((primitive.start[0] + primitive.end[0]) / 2.0, (primitive.start[1] + primitive.end[1]) / 2.0)


def rect_to_segment_distance(rect, start, end):
    if point_in_rect(start, rect) or point_in_rect(end, rect):
        return 0.0
    corners = (
        (rect[0], rect[1]),
        (rect[2], rect[1]),
        (rect[2], rect[3]),
        (rect[0], rect[3]),
    )
    edges = (
        (corners[0], corners[1]),
        (corners[1], corners[2]),
        (corners[2], corners[3]),
        (corners[3], corners[0]),
    )
    minimum = None
    for edge_start, edge_end in edges:
        value = segment_distance(start, end, edge_start, edge_end)
        if minimum is None or value < minimum:
            minimum = value
    return minimum or 0.0


def point_in_rect(point, rect):
    return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]


def point_in_primitive(point, primitive):
    if not point_in_rect(point, primitive.bbox):
        return False
    if primitive.kind == "composite":
        return any(point_in_primitive(point, member) for member in primitive.members)
    if primitive.kind == "circle":
        return distance(point, primitive.center) <= primitive.width / 2.0 + 1e-9
    if primitive.kind in ("segment", "obround"):
        return point_to_segment_distance(point, primitive.start, primitive.end) <= primitive.width / 2.0 + 1e-9
    if primitive.kind == "region":
        return point_in_region(point, primitive)
    return True


def region_to_segment_gap(region, start, end):
    if not region.points:
        return 0.0
    if point_in_region(start, region) or point_in_region(end, region):
        return 0.0
    segment = GerberSegment(start, end, width=0.0)
    value = nearest_region_segment_distance(segment, region_edge_segments(region))
    return value or 0.0


def region_to_segment_gap_within(region, start, end, max_gap):
    if not region.points:
        return 0.0
    if point_in_region(start, region) or point_in_region(end, region):
        return 0.0
    segment = GerberSegment(start, end, width=0.0)
    candidates = region_edge_segments_near_bbox(region, segment.bbox, max_gap)
    if not candidates:
        return math.inf
    return min(
        segment_distance(start, end, candidate.start, candidate.end)
        for candidate in candidates
    )


def region_to_point_gap(region, point):
    if not region.points or point_in_region(point, region):
        return 0.0
    best = None
    for edge in region_edge_segments(region):
        if best is not None and edge.bbox[0] - point[0] >= best:
            break
        if best is not None and point[0] - edge.bbox[2] >= best:
            continue
        lower_bound = point_bbox_gap(point, edge.bbox)
        if best is not None and lower_bound >= best:
            continue
        value = point_to_segment_distance(point, edge.start, edge.end)
        if best is None or value < best:
            best = value
    return best or 0.0


def region_to_point_gap_within(region, point, max_gap):
    if not region.points or point_in_region(point, region):
        return 0.0
    point_bbox = (point[0], point[1], point[0], point[1])
    candidates = region_edge_segments_near_bbox(region, point_bbox, max_gap)
    if not candidates:
        return math.inf
    return min(
        point_to_segment_distance(point, candidate.start, candidate.end)
        for candidate in candidates
    )


def region_to_rect_gap(region, rect):
    corners = (
        (rect[0], rect[1]),
        (rect[2], rect[1]),
        (rect[2], rect[3]),
        (rect[0], rect[3]),
    )
    if any(point_in_region(corner, region) for corner in corners):
        return 0.0
    if any(point_in_rect(point, rect) for point in region.points):
        return 0.0
    rect_edges = tuple(zip(corners, corners[1:] + corners[:1]))
    best = None
    for start, end in rect_edges:
        value = region_to_segment_gap(region, start, end)
        if best is None or value < best:
            best = value
    return best or 0.0


def region_to_rect_gap_within(region, rect, max_gap):
    corners = (
        (rect[0], rect[1]),
        (rect[2], rect[1]),
        (rect[2], rect[3]),
        (rect[0], rect[3]),
    )
    if any(point_in_region(corner, region) for corner in corners):
        return 0.0
    if any(point_in_rect(point, rect) for point in region.points):
        return 0.0
    candidates = region_edge_segments_near_bbox(region, rect, max_gap)
    if not candidates:
        return math.inf
    rect_edges = tuple(zip(corners, corners[1:] + corners[:1]))
    return min(
        segment_distance(start, end, candidate.start, candidate.end)
        for start, end in rect_edges
        for candidate in candidates
    )


def region_to_region_gap(left, right):
    if not left.points or not right.points:
        return 0.0
    # Containment is common in Gerber output assembled from overlapping region
    # primitives.  Detect it before the substantially more expensive edge-pair
    # distance scan; the old order only checked this after scanning every edge.
    if point_in_region(left.points[0], right) or point_in_region(right.points[0], left):
        return 0.0
    left_edges = region_edge_segments(left)
    right_edges = region_edge_segments(right)
    if len(left_edges) > len(right_edges):
        left_edges, right_edges = right_edges, left_edges
    best = None
    for edge in left_edges:
        value = nearest_region_segment_distance(edge, right_edges, best)
        if value is None:
            continue
        if best is None or value < best:
            best = value
            if best <= 1e-9:
                return 0.0
    return best or 0.0


def region_to_region_gap_within(left, right, max_gap):
    if not left.points or not right.points:
        return 0.0
    if point_in_region(left.points[0], right) or point_in_region(right.points[0], left):
        return 0.0
    left_edges = region_edge_segments(left)
    right_edges = region_edge_segments(right)
    if len(left_edges) > len(right_edges):
        left, right = right, left
        left_edges = right_edges
    best = None
    for edge in left_edges:
        candidates = region_edge_segments_near_bbox(right, edge.bbox, max_gap)
        for candidate in candidates:
            value = segment_distance(edge.start, edge.end, candidate.start, candidate.end)
            if best is None or value < best:
                best = value
                if best <= 1e-9:
                    return 0.0
    return best if best is not None and best <= max_gap else math.inf


def polygon_to_segment_gap(points, start, end):
    if not points:
        return 0.0
    if point_in_polygon(start, points) or point_in_polygon(end, points):
        return 0.0
    return min(segment_distance(start, end, edge[0], edge[1]) for edge in polygon_edges(points))


def polygon_to_point_gap(points, point):
    if not points or point_in_polygon(point, points):
        return 0.0
    return min(point_to_segment_distance(point, edge[0], edge[1]) for edge in polygon_edges(points))


def polygon_to_rect_gap(points, rect):
    corners = (
        (rect[0], rect[1]),
        (rect[2], rect[1]),
        (rect[2], rect[3]),
        (rect[0], rect[3]),
    )
    if any(point_in_polygon(corner, points) for corner in corners):
        return 0.0
    if any(point_in_rect(point, rect) for point in points):
        return 0.0
    rect_edges = tuple(zip(corners, corners[1:] + corners[:1]))
    return min(segment_distance(a, b, c, d) for a, b in polygon_edges(points) for c, d in rect_edges)


def polygon_to_polygon_gap(left, right):
    if not left or not right:
        return 0.0
    if any(point_in_polygon(point, right) for point in left):
        return 0.0
    if any(point_in_polygon(point, left) for point in right):
        return 0.0
    return min(segment_distance(a, b, c, d) for a, b in polygon_edges(left) for c, d in polygon_edges(right))


def polygon_edges(points):
    return tuple(zip(points, points[1:] + points[:1]))


def region_edges(region):
    if region.edges is None:
        region.edges = tuple(polygon_edges(region.points)) + tuple(
            edge
            for hole in region.holes
            for edge in polygon_edges(hole)
        )
    return region.edges


def region_edge_segments(region):
    if region.edge_segments is None:
        region.edge_segments = sorted(
            (GerberSegment(start, end, width=0.0) for start, end in region_edges(region)),
            key=lambda segment: segment.bbox[0],
        )
    return region.edge_segments


def region_edge_segments_near_bbox(region, bbox, margin):
    if region.edge_segment_index is None:
        region.edge_segment_index = build_region_edge_segment_index(
            region_edge_segments(region)
        )
    first = int(math.floor((bbox[1] - margin) / REGION_EDGE_BUCKET_SIZE))
    last = int(math.floor((bbox[3] + margin) / REGION_EDGE_BUCKET_SIZE))
    seen = set()
    result = []
    for bucket in range(first, last + 1):
        for segment in region.edge_segment_index.get(bucket, ()):
            identity = id(segment)
            if identity in seen:
                continue
            seen.add(identity)
            if bbox_gap(bbox, segment.bbox) <= margin:
                result.append(segment)
    return result


def build_region_edge_segment_index(segments):
    index = {}
    for segment in segments:
        first = int(math.floor(segment.bbox[1] / REGION_EDGE_BUCKET_SIZE))
        last = int(math.floor(segment.bbox[3] / REGION_EDGE_BUCKET_SIZE))
        for bucket in range(first, last + 1):
            index.setdefault(bucket, []).append(segment)
    return index


def nearest_region_segment_distance(segment, candidates, stop_at=None):
    best = None
    for candidate in candidates:
        if stop_at is not None and candidate.bbox[0] > segment.bbox[2]:
            if candidate.bbox[0] - segment.bbox[2] >= stop_at:
                break
        lower_bound = bbox_gap(segment.bbox, candidate.bbox)
        if stop_at is not None and lower_bound >= stop_at:
            continue
        if best is not None:
            if candidate.bbox[0] > segment.bbox[2] and candidate.bbox[0] - segment.bbox[2] >= best:
                break
            if lower_bound >= best:
                continue
        value = segment_distance(segment.start, segment.end, candidate.start, candidate.end)
        if best is None or value < best:
            best = value
            if stop_at is not None and best <= stop_at:
                return best
    return best


def point_bbox_gap(point, bbox):
    dx = max(0.0, max(bbox[0] - point[0], point[0] - bbox[2]))
    dy = max(0.0, max(bbox[1] - point[1], point[1] - bbox[3]))
    if dx <= 0:
        return dy
    if dy <= 0:
        return dx
    return math.sqrt(dx * dx + dy * dy)


def point_in_region(point, region):
    if not point_in_rect(point, region.bbox):
        return False
    if not point_in_polygon_edges(point, region_edges_at_y(region, point[1])):
        return False
    return not any(point_in_polygon(point, hole) for hole in region.holes)


def region_edges_at_y(region, y):
    if region.edge_index is None:
        region.edge_index = build_region_edge_index(region_edges(region))
    bucket = int(math.floor(y / region_edge_bucket_size(region)))
    return region.edge_index.get(bucket, ())


def build_region_edge_index(edges):
    index = {}
    for start, end in edges:
        min_y = min(start[1], end[1])
        max_y = max(start[1], end[1])
        first = int(math.floor(min_y / REGION_EDGE_BUCKET_SIZE))
        last = int(math.floor(max_y / REGION_EDGE_BUCKET_SIZE))
        for bucket in range(first, last + 1):
            index.setdefault(bucket, []).append((start, end))
    return index


REGION_EDGE_BUCKET_SIZE = 1.0


def region_edge_bucket_size(region):
    return REGION_EDGE_BUCKET_SIZE


def point_in_polygon(point, polygon):
    inside = False
    x, y = point
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if point_on_segment(point, previous, current):
            return True
        if (y1 > y) != (y2 > y):
            at_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x <= at_x:
                inside = not inside
        previous = current
    return inside


def point_in_polygon_edges(point, edges):
    """Ray-cast against the y-bucketed edges that can cross the point."""
    inside = False
    x, y = point
    for start, end in edges:
        if point_on_segment(point, start, end):
            return True
        x1, y1 = start
        x2, y2 = end
        if (y1 > y) != (y2 > y):
            at_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x <= at_x:
                inside = not inside
    return inside


def point_on_segment(point, start, end):
    return orientation(start, end, point) == 0 and bbox_overlap(start, end, point, point)


def segments_intersect(a, b, c, d):
    return (
        orientation(a, b, c) * orientation(a, b, d) <= 0
        and orientation(c, d, a) * orientation(c, d, b) <= 0
        and bbox_overlap(a, b, c, d)
    )


def orientation(a, b, c):
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if abs(value) < 1e-9:
        return 0
    return 1 if value > 0 else -1


def bbox_overlap(a, b, c, d):
    return (
        max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) + 1e-9
        and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1])) + 1e-9
    )


def minimum_spacing(coordinates):
    if len(coordinates) < 2:
        return None
    minimum = None
    for index, left in enumerate(coordinates):
        for right in coordinates[index + 1:]:
            gap = distance(left, right)
            if minimum is None or gap < minimum:
                minimum = gap
    return minimum


class LimitedMinimumSpacing:
    __slots__ = (
        "limit", "minimum", "minimum_pair", "minimum_radii", "minimum_data",
        "pairs", "points", "cells", "cell_size",
    )

    def __init__(self, limit):
        self.limit = limit
        self.minimum = None
        self.minimum_pair = None
        self.minimum_radii = None
        self.minimum_data = None
        self.pairs = []
        self.points = []
        self.cells = {}
        self.cell_size = max(float(limit or 0), 10.0)

    def add(self, point, radius=0.0, data=None):
        if self.limit is None or self.limit <= 0:
            for previous, previous_radius, previous_data in self.points:
                self._record(
                    edge_gap(point, radius, previous, previous_radius),
                    point,
                    previous,
                    radius,
                    previous_radius,
                    data,
                    previous_data,
                )
            self.points.append((point, radius, data))
            return

        cell = self._cell(point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for previous, previous_radius, previous_data in self.cells.get((cell[0] + dx, cell[1] + dy), ()):
                    gap = edge_gap(point, radius, previous, previous_radius)
                    if gap <= self.limit:
                        self._record(gap, point, previous, radius, previous_radius, data, previous_data)
        self.cells.setdefault(cell, []).append((point, radius, data))

    def _record(self, gap, left=None, right=None, left_radius=None, right_radius=None, left_data=None, right_data=None):
        if self.limit is not None and self.limit > 0:
            self.pairs.append(
                (
                    gap,
                    (left, right),
                    (left_radius, right_radius),
                    (left_data, right_data),
                )
            )
        if self.minimum is None or gap < self.minimum:
            self.minimum = gap
            self.minimum_pair = (left, right)
            self.minimum_radii = (left_radius, right_radius)
            self.minimum_data = (left_data, right_data)

    def _cell(self, point):
        return int(math.floor(point[0] / self.cell_size)), int(math.floor(point[1] / self.cell_size))


def edge_gap(left, left_radius, right, right_radius):
    return max(0.0, distance(left, right) - left_radius - right_radius)


def outline_open_gap(segments, join_tolerance=0.0):
    open_points = outline_open_points(segments, join_tolerance)
    if len(open_points) < 2:
        return 0.0
    open_points.sort()
    minimum = None
    for index, left in enumerate(open_points):
        for right in open_points[index + 1:]:
            if minimum is not None and right[0] - left[0] >= minimum:
                break
            gap = distance(left, right)
            if minimum is None or gap < minimum:
                minimum = gap
    return minimum or 0.0


def outline_open_gap_endpoints(segments, join_tolerance=0.0):
    open_points = outline_open_points(segments, join_tolerance)
    if len(open_points) < 2:
        return None
    open_points.sort()
    best = None
    for index, left in enumerate(open_points):
        for right in open_points[index + 1:]:
            if best is not None and right[0] - left[0] >= best[0]:
                break
            gap = distance(left, right)
            if best is None or gap < best[0]:
                best = (gap, left, right)
    if best is None:
        return None
    return best[1], best[2]


def outline_open_points(segments, join_tolerance=0.0):
    """Return unmatched outline nodes after joining nearby Gerber endpoints.

    Plotters may round the two commands meeting at one source Edge.Cuts node
    differently by a few micrometres.  Counting exact coordinate keys makes a
    valid contour look open.  Conversely, the former implementation accepted
    an outline as soon as *one* pair of open endpoints happened to be close.
    Cluster every endpoint within the allowed join tolerance, then require all
    node degrees to be even.
    """
    points = [
        point
        for segment in segments
        for point in (segment.start, segment.end)
        if point is not None
    ]
    if not points:
        return []
    tolerance = max(float(join_tolerance or 0.0), 1e-6)
    parents = list(range(len(points)))
    buckets = {}

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def join(left, right):
        left_root = root(left)
        right_root = root(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for index, point in enumerate(points):
        cell = (
            int(math.floor(point[0] / tolerance)),
            int(math.floor(point[1] / tolerance)),
        )
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for previous in buckets.get((cell[0] + dx, cell[1] + dy), ()):
                    if distance(point, points[previous]) <= tolerance + 1e-12:
                        join(index, previous)
        buckets.setdefault(cell, []).append(index)

    groups = {}
    for index, point in enumerate(points):
        group = groups.setdefault(root(index), [])
        group.append(point)
    return [
        (
            sum(point[0] for point in group) / len(group),
            sum(point[1] for point in group) / len(group),
        )
        for group in groups.values()
        if len(group) % 2 == 1
    ]


def point_key(point):
    return round(point[0], 6), round(point[1], 6)
