import math
from dataclasses import dataclass


OUTER_COPPER_LAYERS = ("F.Cu", "B.Cu")


@dataclass(frozen=True)
class BoardStatistics:
    board_area_mm2: float
    drill_count: int
    drill_density_per_m2: float
    surface_finish_area_mm2: float
    surface_finish_percent: float
    test_point_count: int


def calculate_board_statistics(backend, pads=None, vias=None):
    pads = list(pads) if pads is not None else list(iter_board_pads(backend))
    vias = list(vias) if vias is not None else list(iter_board_vias(backend))
    board_area_mm2 = max(0.0, safe_number(call_optional(backend, "board_area_mm2"), 0.0))
    if board_area_mm2 <= 0:
        board_area_mm2 = outline_bbox_area_mm2(backend)

    drilled_pads = [pad for pad in pads if pad_has_drill(backend, pad)]
    drill_count = len(drilled_pads) + len(vias)
    drill_density_per_m2 = (
        drill_count * 1000000.0 / board_area_mm2 if board_area_mm2 > 0 else 0.0
    )

    surface_finish_area_mm2 = 0.0
    accessible_pad_ids = set()
    for pad in pads:
        if call_bool(backend, "is_npth_pad", pad):
            continue
        exposed = False
        for layer_name in OUTER_COPPER_LAYERS:
            if not pad_is_on_layer(backend, pad, layer_name):
                continue
            if not pad_has_mask_opening(backend, pad, layer_name):
                continue
            exposed = True
            copper_area = pad_copper_area(backend, pad, layer_name)
            surface_finish_area_mm2 += max(
                0.0,
                copper_area - pad_drill_area(backend, pad),
            )
        if exposed and item_net_name(backend, pad):
            accessible_pad_ids.add(item_identity(backend, pad))

    accessible_via_ids = set()
    for via in vias:
        exposed_sides = sum(
            via_has_mask_opening(backend, via, layer_name)
            for layer_name in OUTER_COPPER_LAYERS
        )
        if not exposed_sides:
            continue
        annular_area = max(
            0.0,
            math.pi
            * (
                safe_number(call_optional(backend, "via_width_mm", via), 0.0) ** 2
                - safe_number(call_optional(backend, "via_drill_mm", via), 0.0) ** 2
            )
            / 4.0,
        )
        surface_finish_area_mm2 += annular_area * exposed_sides
        if item_net_name(backend, via):
            accessible_via_ids.add(item_identity(backend, via))

    surface_finish_percent = (
        surface_finish_area_mm2 * 100.0 / board_area_mm2
        if board_area_mm2 > 0
        else 0.0
    )
    return BoardStatistics(
        board_area_mm2=board_area_mm2,
        drill_count=drill_count,
        drill_density_per_m2=drill_density_per_m2,
        surface_finish_area_mm2=surface_finish_area_mm2,
        surface_finish_percent=surface_finish_percent,
        test_point_count=len(accessible_pad_ids) + len(accessible_via_ids),
    )


def statistic_result_map(statistics, chinese=False):
    density = statistics.drill_density_per_m2
    density_display = (
        "{0:.2f}万/m²".format(density / 10000.0)
        if chinese
        else "{0:,.0f}/m²".format(density)
    )
    return {
        "Drill Hole Density": statistic_result(
            density_display,
            value=density,
            drill_count=statistics.drill_count,
            board_area_mm2=statistics.board_area_mm2,
        ),
        "Surface Finish Area": statistic_result(
            "{0:.2f}%".format(statistics.surface_finish_percent),
            value=statistics.surface_finish_percent,
            area_mm2=statistics.surface_finish_area_mm2,
            board_area_mm2=statistics.board_area_mm2,
        ),
        "Test Point Count": statistic_result(
            str(statistics.test_point_count),
            value=statistics.test_point_count,
        ),
    }


def statistic_result(display, value, **metadata):
    return {
        "display": display,
        "display_inch": display,
        "value": value,
        "check": [],
        "color": "black",
        "statistics": metadata,
    }


def iter_board_pads(backend):
    for footprint in backend.iter_footprints():
        yield from backend.iter_pads(footprint)


def iter_board_vias(backend):
    iterator = getattr(backend, "iter_vias", None)
    if iterator is not None:
        yield from iterator()
        return
    for item in backend.iter_tracks():
        if call_bool(backend, "is_via", item):
            yield item


def pad_has_drill(backend, pad):
    drill = call_optional(backend, "pad_drill_mm", pad) or (0.0, 0.0)
    return any(safe_number(value, 0.0) > 0 for value in drill)


def outline_bbox_area_mm2(backend):
    segments = call_optional(backend, "board_outline_segments") or ()
    points = [point for segment in segments for point in segment]
    if not points:
        return 0.0
    left = min(point[0] for point in points)
    top = min(point[1] for point in points)
    right = max(point[0] for point in points)
    bottom = max(point[1] for point in points)
    return max(0.0, (right - left) * (bottom - top) / 1000000000000.0)


def pad_is_on_layer(backend, pad, layer_name):
    reader = getattr(backend, "pad_is_on_layer", None)
    if reader is not None:
        return bool(reader(pad, layer_name))
    if call_bool(backend, "is_pth_pad", pad):
        return True
    return str(call_optional(backend, "item_layer_name", pad) or "") == layer_name


def pad_has_mask_opening(backend, pad, layer_name):
    reader = getattr(backend, "pad_has_solder_mask_opening_on_layer", None)
    if reader is not None:
        return bool(reader(pad, layer_name))
    return call_bool(backend, "pad_has_solder_mask_opening", pad, default=True)


def via_has_mask_opening(backend, via, layer_name):
    reader = getattr(backend, "via_has_solder_mask_opening_on_layer", None)
    if reader is None:
        return True
    return bool(reader(via, layer_name))


def pad_copper_area(backend, pad, layer_name):
    reader = getattr(backend, "pad_copper_area_mm2", None)
    if reader is not None:
        return max(0.0, safe_number(reader(pad, layer_name), 0.0))
    size = call_optional(backend, "pad_size_mm", pad) or (0.0, 0.0)
    return abs(safe_number(size[0], 0.0) * safe_number(size[1], 0.0))


def pad_drill_area(backend, pad):
    drill = call_optional(backend, "pad_drill_mm", pad) or (0.0, 0.0)
    width, height = (abs(safe_number(value, 0.0)) for value in drill)
    if width <= 0 or height <= 0:
        return 0.0
    round_reader = getattr(backend, "is_round_drill_pad", None)
    if round_reader is not None and bool(round_reader(pad)):
        return math.pi * min(width, height) ** 2 / 4.0
    short = min(width, height)
    long = max(width, height)
    return (long - short) * short + math.pi * short * short / 4.0


def item_net_name(backend, item):
    return str(call_optional(backend, "item_net_name", item) or "")


def item_identity(backend, item):
    value = call_optional(backend, "item_id", item)
    return str(value) if value not in (None, "") else id(item)


def call_optional(backend, name, *args):
    reader = getattr(backend, name, None)
    if reader is None:
        return None
    try:
        return reader(*args)
    except Exception:
        return None


def call_bool(backend, name, *args, default=False):
    value = call_optional(backend, name, *args)
    return default if value is None else bool(value)


def safe_number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
