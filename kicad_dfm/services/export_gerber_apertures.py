import math
import re

from kicad_dfm.services.export_gerber_commands import to_mm
from kicad_dfm.services.export_geometry_core import GerberAperture
from kicad_dfm.services.export_geometry_core import GerberPrimitive
from kicad_dfm.services.export_geometry_core import distance


GERBER_MACRO_RE = re.compile(r"%AM([^*%]+)\*(.*)\*%", re.IGNORECASE)
GERBER_MACRO_APERTURE_RE = re.compile(r"%ADD\s*(\d+)\s*([A-Z_.$][A-Z0-9_.$]*)(?:\s*,\s*([^*%]+))?\s*\*%", re.IGNORECASE)
GERBER_STANDARD_APERTURE_RE = re.compile(
    r"%ADD\s*(\d+)\s*([A-Z]+)\s*,\s*([+-]?[0-9.]+(?:\s*X\s*[+-]?[0-9.]+)*)",
    re.IGNORECASE,
)
MACRO_ASSIGNMENT_RE = re.compile(r"^\$(\d+)=(.+)$")
MACRO_PARAM_RE = re.compile(r"\$(\d+)")
MACRO_NUMBER_RE = re.compile(r"^[+\-*/xX().0-9]+$")


def parse_gerber_macro(line, units):
    match = GERBER_MACRO_RE.match(line)
    if not match:
        return None
    body = match.group(2)
    if macro_aperture(body, units) is None:
        return None
    return match.group(1).upper(), body


def parse_gerber_aperture(line, units, macros=None):
    match = GERBER_MACRO_APERTURE_RE.search(line)
    if match:
        macro_name = match.group(2).upper()
        body = (macros or {}).get(macro_name)
        if body is not None:
            variables = macro_param_values(match.group(3))
            aperture = macro_aperture(body, units, variables)
            if aperture is not None:
                aperture.logical_size = macro_logical_pad_size(
                    macro_name, variables, units
                )
                return match.group(1), aperture
    match = GERBER_STANDARD_APERTURE_RE.search(line)
    if match:
        values = aperture_values(match.group(3))
        shape = match.group(2)
        return (
            match.group(1),
            GerberAperture(
                shape,
                aperture_shape_values(shape, values, units),
                aperture_hole(shape, values, units),
                aperture_vertices(shape, values),
                aperture_rotation(shape, values),
            ),
        )
    return None


def aperture_values(params):
    return [float(value.strip()) for value in re.split(r"[Xx]", str(params or "")) if value.strip() != ""]


def macro_param_values(params):
    values = {}
    if not params:
        return values
    for index, value in enumerate(re.split(r"[Xx]", str(params)), 1):
        values[str(index)] = parse_macro_number(value)
    return values


def macro_logical_pad_size(name, variables, units):
    """Return the unrotated pad dimensions encoded by KiCad pad macros."""
    name = str(name or "").upper()
    if name == "ROTRECT":
        width = to_mm(abs(variables.get("1", 0.0)), units)
        height = to_mm(abs(variables.get("2", 0.0)), units)
        return (width, height) if width > 0 and height > 0 else ()
    if name != "ROUNDRECT":
        return ()
    radius = to_mm(abs(variables.get("1", 0.0)), units)
    points = tuple(
        (
            to_mm(variables.get(str(index), 0.0), units),
            to_mm(variables.get(str(index + 1), 0.0), units),
        )
        for index in (2, 4, 6, 8)
    )
    if radius <= 0 or len(set(points)) < 4:
        return ()
    first_side = distance(points[0], points[1]) + radius * 2.0
    second_side = distance(points[1], points[2]) + radius * 2.0
    if first_side <= 0 or second_side <= 0:
        return ()
    return first_side, second_side


def substitute_macro_params(text, values):
    return MACRO_PARAM_RE.sub(lambda match: str(values.get(match.group(1), 0.0)), str(text or ""))


def parse_macro_number(text):
    return MacroNumberParser(str(text or "0")).parse()


class MacroNumberParser:
    __slots__ = ("text", "index")

    def __init__(self, text):
        self.text = re.sub(r"\s+", "", text)
        self.index = 0

    def parse(self):
        if not MACRO_NUMBER_RE.match(self.text):
            return 0.0
        try:
            value = self.expression()
            return value if self.index == len(self.text) else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0

    def expression(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            operator = self.take()
            right = self.term()
            value = value + right if operator == "+" else value - right
        return value

    def term(self):
        value = self.factor()
        while self.peek() in ("*", "/", "X", "x"):
            operator = self.take()
            right = self.factor()
            value = value / right if operator == "/" else value * right
        return value

    def factor(self):
        if self.peek() in ("+", "-"):
            return -self.factor() if self.take() == "-" else self.factor()
        if self.peek() == "(":
            self.take()
            value = self.expression()
            if self.take() != ")":
                raise ValueError
            return value
        return self.number()

    def number(self):
        start = self.index
        while self.peek().isdigit() or self.peek() == ".":
            self.index += 1
        if start == self.index:
            raise ValueError
        return float(self.text[start : self.index])

    def peek(self):
        return self.text[self.index] if self.index < len(self.text) else ""

    def take(self):
        value = self.peek()
        self.index += 1
        return value


def aperture_shape_values(shape, values, units):
    if str(shape or "").upper().startswith(("C", "P")):
        return [to_mm(value, units) for value in values[:1]]
    if str(shape or "").upper().startswith(("R", "O")):
        return [to_mm(value, units) for value in values[:2]]
    return [to_mm(value, units) for value in values]


def aperture_hole(shape, values, units):
    shape = str(shape or "").upper()
    if shape.startswith("C") and len(values) >= 2:
        return to_mm(values[1], units), to_mm(values[2] if len(values) >= 3 else values[1], units)
    if shape.startswith("P") and len(values) >= 4:
        return to_mm(values[3], units), to_mm(values[4] if len(values) >= 5 else values[3], units)
    if shape.startswith(("R", "O")) and len(values) >= 3:
        return to_mm(values[2], units), to_mm(values[3] if len(values) >= 4 else values[2], units)
    return None


def aperture_vertices(shape, values):
    if str(shape or "").upper().startswith("P") and len(values) >= 2:
        return max(3, int(round(values[1])))
    return None


def aperture_rotation(shape, values):
    if str(shape or "").upper().startswith("P") and len(values) >= 3:
        return math.radians(values[2])
    return 0.0


def aperture_hole_mask(center, hole):
    width, height = hole
    kind = "circle" if abs(width - height) < 1e-9 else "rect"
    return GerberPrimitive(kind, center=center, width=width, height=height, is_flash=True)


def macro_aperture(body, units, variables=None):
    best = None
    primitives = []
    variables = dict(variables or {})
    for primitive in str(body or "").split("*"):
        parts = [part for part in primitive.split(",") if part != ""]
        if not parts:
            continue
        assignment = macro_assignment(parts[0], variables)
        if assignment is not None:
            variables[assignment[0]] = assignment[1]
            continue
        try:
            code = int(parse_macro_number(substitute_macro_params(parts[0], variables)))
        except ValueError:
            continue
        values = []
        for part in parts[1:]:
            values.append(parse_macro_number(substitute_macro_params(part, variables)))
        candidate = macro_primitive_size(code, values, units)
        if candidate is None:
            continue
        candidates = candidate if isinstance(candidate, list) else [candidate]
        primitives.extend(candidates)
        for item in candidates:
            if best is None or macro_primitive_area(item) > macro_primitive_area(best):
                best = item
    if best is None:
        return None
    shape = "C" if abs(best["width"] - best["height"]) < 1e-9 else "R"
    return GerberAperture(
        shape,
        (best["width"], best["height"]),
        offset=best["center"],
        macro_primitives=macro_flash_primitives(primitives),
    )


def macro_assignment(text, variables):
    match = MACRO_ASSIGNMENT_RE.match(str(text or ""))
    if not match:
        return None
    return match.group(1), parse_macro_number(substitute_macro_params(match.group(2), variables))


def macro_primitive_size(code, values, units):
    if code == 1 and len(values) >= 4:
        diameter = to_mm(abs(values[1]), units)
        center = (to_mm(values[2], units), to_mm(values[3], units))
        rotation = math.radians(values[4]) if len(values) >= 5 else 0.0
        if abs(rotation) > 1e-12:
            center = rotate_point(center, rotation)
        return macro_primitive("circle", diameter, diameter, center, values[0])
    if code == 4 and len(values) >= 8:
        points = macro_outline_points(values, units)
        if len(points) < 3:
            return None
        bbox = polygon_bbox(points)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        relative_points = tuple((point[0] - center[0], point[1] - center[1]) for point in points)
        return macro_primitive("region", width, height, center, values[0], points=relative_points)
    if code == 5 and len(values) >= 5:
        vertices = max(3, int(round(values[1])))
        center = (to_mm(values[2], units), to_mm(values[3], units))
        diameter = to_mm(abs(values[4]), units)
        rotation = math.radians(values[5]) if len(values) >= 6 else 0.0
        if abs(rotation) > 1e-12:
            center = rotate_point(center, rotation)
        points = regular_polygon_points((0.0, 0.0), diameter, vertices, rotation)
        return macro_primitive("region", diameter, diameter, center, values[0], points=points)
    if code == 21 and len(values) >= 5:
        width = to_mm(abs(values[1]), units)
        height = to_mm(abs(values[2]), units)
        center = (to_mm(values[3], units), to_mm(values[4], units))
        rotation = math.radians(values[5]) if len(values) >= 6 else 0.0
        return macro_rect_primitive(width, height, center, rotation, values[0])
    if code == 22 and len(values) >= 5:
        width = to_mm(abs(values[1]), units)
        height = to_mm(abs(values[2]), units)
        lower_left = (to_mm(values[3], units), to_mm(values[4], units))
        center = (lower_left[0] + width / 2.0, lower_left[1] + height / 2.0)
        rotation = math.radians(values[5]) if len(values) >= 6 else 0.0
        return macro_rect_primitive(width, height, center, rotation, values[0])
    if code in (2, 20) and len(values) >= 6:
        width = to_mm(abs(values[1]), units)
        start = (to_mm(values[2], units), to_mm(values[3], units))
        end = (to_mm(values[4], units), to_mm(values[5], units))
        rotation = math.radians(values[6]) if len(values) >= 7 else 0.0
        if abs(rotation) > 1e-12:
            start = rotate_point(start, rotation)
            end = rotate_point(end, rotation)
        center = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        height = max(width, distance(start, end))
        return macro_primitive("segment", width, height, center, values[0], start=start, end=end)
    if code == 7 and len(values) >= 6:
        center = (to_mm(values[0], units), to_mm(values[1], units))
        outer = to_mm(abs(values[2]), units)
        inner = to_mm(abs(values[3]), units)
        gap = to_mm(abs(values[4]), units)
        rotation = math.radians(values[5])
        if abs(rotation) > 1e-12:
            center = rotate_point(center, rotation)
        return macro_thermal_primitives(center, outer, inner, gap, rotation)
    return None


def macro_rect_primitive(width, height, center, rotation, exposure):
    """Build an exact centre-line/lower-left rectangle macro primitive.

    Gerber macro rotation is around the aperture origin, not merely around the
    rectangle centre.  Represent rotated rectangles as regions so spacing uses
    their actual edges instead of the unrotated axis-aligned dimensions.
    """
    half_width = width / 2.0
    half_height = height / 2.0
    points = (
        (center[0] - half_width, center[1] - half_height),
        (center[0] + half_width, center[1] - half_height),
        (center[0] + half_width, center[1] + half_height),
        (center[0] - half_width, center[1] + half_height),
    )
    if abs(rotation) > 1e-12:
        points = tuple(rotate_point(point, rotation) for point in points)
    bbox = polygon_bbox(points)
    rotated_center = (
        (bbox[0] + bbox[2]) / 2.0,
        (bbox[1] + bbox[3]) / 2.0,
    )
    relative_points = tuple(
        (point[0] - rotated_center[0], point[1] - rotated_center[1])
        for point in points
    )
    return macro_primitive(
        "region",
        bbox[2] - bbox[0],
        bbox[3] - bbox[1],
        rotated_center,
        exposure,
        points=relative_points,
    )


def macro_thermal_primitives(center, outer, inner, gap, rotation):
    if outer <= 0:
        return None
    clear = [
        macro_primitive("circle", inner, inner, center, 0) if inner > 0 else None,
        macro_thermal_gap(center, outer, gap, rotation),
        macro_thermal_gap(center, outer, gap, rotation + math.pi / 2.0),
    ]
    return [macro_primitive("circle", outer, outer, center, 1)] + [primitive for primitive in clear if primitive is not None]


def macro_thermal_gap(center, outer, gap, angle):
    if gap <= 0:
        return None
    radius = outer / 2.0
    axis = (math.cos(angle) * radius, math.sin(angle) * radius)
    start = (center[0] - axis[0], center[1] - axis[1])
    end = (center[0] + axis[0], center[1] + axis[1])
    return macro_primitive("segment", gap, outer, center, 0, start=start, end=end)


def macro_outline_points(values, units):
    count = max(0, int(round(values[1])))
    # RS-274X outline primitives encode a start point followed by ``count``
    # vertices; the final vertex repeats the start point.  KiCad follows that
    # form, so there are ``count + 1`` coordinate pairs before rotation.  The
    # former ``count`` slice consumed the repeated start X as the rotation and
    # silently ignored KiCad's actual $1 rotation parameter.  Retain a fallback
    # for old malformed files that provide only ``count`` coordinate pairs.
    point_count = count + 1 if len(values) >= 2 + (count + 1) * 2 else count
    point_values = values[2 : 2 + point_count * 2]
    if len(point_values) < 6:
        return ()
    points = tuple(
        (to_mm(point_values[index], units), to_mm(point_values[index + 1], units))
        for index in range(0, len(point_values), 2)
    )
    rotation_index = 2 + point_count * 2
    rotation = math.radians(values[rotation_index]) if len(values) > rotation_index else 0.0
    if abs(rotation) <= 1e-12:
        return points
    return tuple(rotate_point(point, rotation) for point in points)


def macro_primitive(kind, width, height, center, exposure, points=None, start=None, end=None):
    return {
        "kind": kind,
        "width": width,
        "height": height,
        "center": center,
        "exposure": macro_exposure(exposure),
        "points": tuple(points or ()),
        "start": start,
        "end": end,
    }


def macro_primitive_area(primitive):
    return primitive["width"] * primitive["height"]


def macro_exposure(value):
    return "dark" if value else "clear"


def macro_flash_primitives(primitives):
    return tuple((primitive["exposure"], macro_flash_primitive(primitive)) for primitive in primitives)


def macro_flash_primitive(primitive):
    if primitive["kind"] == "segment":
        return GerberPrimitive(
            "segment",
            start=primitive["start"],
            end=primitive["end"],
            width=primitive["width"],
            is_flash=True,
        )
    if primitive["kind"] == "region":
        points = tuple(offset_point(point, primitive["center"]) for point in primitive["points"])
        bbox = polygon_bbox(points)
        return GerberPrimitive(
            "region",
            start=(bbox[0], bbox[1]),
            end=(bbox[2], bbox[3]),
            center=primitive["center"],
            width=primitive["width"],
            height=primitive["height"],
            is_flash=True,
            points=points,
        )
    return GerberPrimitive(
        primitive["kind"],
        center=primitive["center"],
        width=primitive["width"],
        height=primitive["height"],
        is_flash=True,
    )


def gerber_flash_primitive(aperture, point):
    center = offset_point(point, aperture.offset)
    if aperture.shape.startswith("P") and aperture.vertices:
        width, height = aperture.size
        points = regular_polygon_points(center, aperture.width, aperture.vertices, aperture.rotation)
        bbox = polygon_bbox(points)
        return GerberPrimitive(
            "region",
            start=(bbox[0], bbox[1]),
            end=(bbox[2], bbox[3]),
            center=center,
            width=width,
            height=height,
            is_flash=True,
            points=points,
        )
    width, height = aperture.size
    return GerberPrimitive(gerber_flash_kind(aperture), center=center, width=width, height=height, is_flash=True)


def gerber_flash_kind(aperture):
    if aperture.shape.startswith(("C", "P")):
        return "circle"
    if aperture.shape.startswith("O"):
        return "obround"
    return "rect"


def regular_polygon_points(center, diameter, vertices, rotation):
    radius = diameter / 2.0
    return tuple(
        (
            center[0] + math.cos(rotation + math.tau * index / vertices) * radius,
            center[1] + math.sin(rotation + math.tau * index / vertices) * radius,
        )
        for index in range(vertices)
    )


def polygon_bbox(points):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def rotate_point(point, angle):
    return (
        math.cos(angle) * point[0] - math.sin(angle) * point[1],
        math.sin(angle) * point[0] + math.cos(angle) * point[1],
    )


def offset_point(point, offset):
    return point[0] + offset[0], point[1] + offset[1]
