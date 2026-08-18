from bisect import bisect_left
import math

from kicad_dfm.services.export_geometry_core import bbox_gap
from kicad_dfm.services.export_geometry_core import distance
from kicad_dfm.services.export_geometry_core import drill_to_primitive_gap
from kicad_dfm.services.export_geometry_core import GerberPrimitive
from kicad_dfm.services.export_geometry_core import primitive_center
from kicad_dfm.services.export_geometry_core import primitive_gap
from kicad_dfm.services.export_geometry_core import primitive_gap_within
from kicad_dfm.services.export_geometry_core import primitive_segment_gap
from kicad_dfm.services.export_geometry_core import point_in_primitive
from kicad_dfm.services.export_geometry_core import point_to_segment_distance
from kicad_dfm.services.export_geometry_core import region_edges
from kicad_dfm.services.export_geometry_core import segment_distance
from kicad_dfm.services.export_geometry_core import spacing_location
from kicad_dfm.services.export_scan_models import ScanFinding
from kicad_dfm.core.pad_size import pad_shorter_side_mm, pad_size_item


COPPER_SPACING_TIE_TOLERANCE_MM = 0.00005
COPPER_SPACING_PASSING_WINDOW_MM = 0.254
BOARD_EDGE_DRILL_MATCH_TOLERANCE_MM = 0.05
BOARD_EDGE_INITIAL_SEARCH_MM = 0.5


def periodic_checkpoint(checkpoint, count, interval=1024):
    if checkpoint is not None and count % interval == 0:
        checkpoint()


def scan_drill_spacing(drill_scans, reporting_limit=None, checkpoint=None):
    """Scan physical holes globally across every Excellon file."""
    holes = logical_drill_holes(drill_scans)
    if len(holes) < 2:
        return
    candidate_count = 0
    matches = []
    limit = float(reporting_limit) if reporting_limit is not None else None
    if limit is not None and limit > 0:
        maximum_resolution = max(
            (hole["coordinate_resolution_mm"] or 0.0 for hole in holes),
            default=0.0,
        )
        index = BboxGridIndex(
            tuple((offset, hole["drill"]) for offset, hole in enumerate(holes))
        )
        for left_index, left in enumerate(holes):
            # Keep progress/cancellation responsive even for sparse drill
            # sets where the spatial index returns no pair candidates.
            periodic_checkpoint(checkpoint, left_index + 1, interval=256)
            search_margin = limit + (
                (left["coordinate_resolution_mm"] or 0.0)
                + maximum_resolution
            ) / 2.0
            for right_index, _right_drill in index.candidates(
                left["drill"].bbox, search_margin
            ):
                if right_index <= left_index:
                    continue
                candidate_count += 1
                periodic_checkpoint(checkpoint, candidate_count)
                match = drill_spacing_match(left, holes[right_index], limit)
                if match is not None:
                    matches.append(match)
    else:
        for left_index, left in enumerate(holes):
            for right in holes[left_index + 1:]:
                candidate_count += 1
                periodic_checkpoint(checkpoint, candidate_count)
                match = drill_spacing_match(left, right, None)
                if match is not None:
                    matches.append(match)
        if matches:
            matches = [min(matches, key=lambda match: match[0])]

    for gap, left, right, uncertainty, intersection, span_status in sorted(
        matches, key=lambda match: match[0]
    ):
        primary = logical_drill_mapping_raw(left)
        related = logical_drill_mapping_raw(right)
        diameter = min(left["drill"].diameter, right["drill"].diameter)
        yield ScanFinding(
            "Different Net PTH Spacing",
            "Global Excellon drill spacing is {0:.3f}mm.".format(gap),
            category="Drill Hole Spacing",
            value=round(gap, 6),
            layer=["Drl"],
            raw={
                "file": primary.get("file", ""),
                "source_files": tuple(
                    sorted(set(left["source_files"] + right["source_files"]))
                ),
                "segment": (left["drill"].center, right["drill"].center),
                "diameter": diameter,
                "width": diameter,
                "bbox": union_bbox(left["drill"].bbox, right["drill"].bbox),
                "primary": primary,
                "related": related,
                "layer_span_intersection": intersection,
                "layer_span_status": span_status,
                "coordinate_resolution_mm": max(
                    left["coordinate_resolution_mm"] or 0.0,
                    right["coordinate_resolution_mm"] or 0.0,
                ),
                "uncertainty_mm": uncertainty,
                "measurement_interval_mm": (
                    max(0.0, gap - uncertainty),
                    gap + uncertainty,
                ),
                "physical_hole_count": 2,
            },
        )


def logical_drill_holes(drill_scans):
    by_key = {}
    ordered = []
    for scan in drill_scans:
        span = normalized_layer_span(getattr(scan, "layer_span", None))
        for drill in scan.primitives:
            if (
                drill.kind != "circle"
                or drill.center is None
                or drill.diameter <= 0
                or not valid_bbox_item(drill)
            ):
                continue
            key = (
                round(drill.center[0], 6),
                round(drill.center[1], 6),
                round(drill.diameter, 6),
                span,
            )
            logical = by_key.get(key)
            if logical is None:
                logical = {
                    "drill": drill,
                    "source_scans": [scan],
                    "source_files": [scan.path],
                    "plating": {scan.plated},
                    "layer_span": span,
                    "coordinate_resolution_mm": (
                        drill.coordinate_resolution_mm
                        if drill.coordinate_resolution_mm is not None
                        else getattr(scan, "coordinate_resolution_mm", None)
                    ),
                }
                by_key[key] = logical
                ordered.append(logical)
                continue
            logical["source_scans"].append(scan)
            if scan.path not in logical["source_files"]:
                logical["source_files"].append(scan.path)
            logical["plating"].add(scan.plated)
            resolution = (
                drill.coordinate_resolution_mm
                if drill.coordinate_resolution_mm is not None
                else getattr(scan, "coordinate_resolution_mm", None)
            )
            if resolution is not None:
                logical["coordinate_resolution_mm"] = max(
                    logical["coordinate_resolution_mm"] or 0.0,
                    resolution,
                )
    return ordered


def normalized_layer_span(span):
    if not span or len(span) < 2:
        return None
    first, second = int(span[0]), int(span[1])
    return min(first, second), max(first, second)


def drill_layer_span_intersection(left, right):
    left_span = left.get("layer_span")
    right_span = right.get("layer_span")
    if left_span is None or right_span is None:
        return True, None, "unknown"
    start = max(left_span[0], right_span[0])
    end = min(left_span[1], right_span[1])
    if start > end:
        return False, None, "disjoint"
    return True, (start, end), "intersecting"


def drill_spacing_match(left, right, reporting_limit):
    intersects, intersection, span_status = drill_layer_span_intersection(
        left, right
    )
    if not intersects:
        return None
    gap = max(
        0.0,
        distance(left["drill"].center, right["drill"].center)
        - left["drill"].diameter / 2.0
        - right["drill"].diameter / 2.0,
    )
    uncertainty = (
        (left["coordinate_resolution_mm"] or 0.0)
        + (right["coordinate_resolution_mm"] or 0.0)
    ) / 2.0
    if (
        reporting_limit is not None
        and reporting_limit > 0
        and gap - uncertainty > reporting_limit
    ):
        return None
    return gap, left, right, uncertainty, intersection, span_status


def logical_drill_mapping_raw(logical):
    scan = logical["source_scans"][0]
    data = primitive_mapping_raw(
        logical["drill"], scan.path, scan.layer, "drill"
    )
    data["source_files"] = tuple(sorted(logical["source_files"]))
    data["layer_span"] = logical["layer_span"]
    plating = logical["plating"]
    data["plated"] = next(iter(plating)) if len(plating) == 1 else "mixed"
    resolution = logical["coordinate_resolution_mm"]
    if resolution is not None:
        data["coordinate_resolution_mm"] = resolution
        data["quantization_tolerance_mm"] = resolution / 2.0
    return data


def scan_signal_integrity(scans, checkpoint=None):
    all_copper_scans = tuple(scan for scan in scans if scan.is_copper)
    copper_scans = all_copper_scans
    for scan in copper_scans:
        primitives = tuple(
            primitive
            for primitive in visible_primitives(scan)
            if valid_bbox_item(primitive)
        )
        signal_segments = tuple(
            primitive
            for primitive in primitives
            if primitive.kind == "segment"
            and primitive.function == "Conductor"
        )
        primitive_index = BboxGridIndex(tuple((None, primitive) for primitive in primitives))
        acute_pairs = tuple(
            (left, right)
            for left, right in acute_signal_segment_pairs(signal_segments)
            if gerber_acute_junction_is_exposed(
                left,
                right,
                primitives,
                primitive_index,
            )
        )
        for primary, related in acute_pairs:
            yield ScanFinding(
                "Acute Angle Traces",
                "Gerber copper geometry forms an acute angle.",
                category="Signal Integrity",
                value=round(float(min(primary.width or 0.0, related.width or 0.0)), 6),
                layer=scan.layer,
                color="red",
                raw={
                    "file": scan.path,
                    "segment": primary.location_segment(),
                    "width": primary.width,
                    "bbox": component_bbox((primary, related)),
                    "primary": primitive_mapping_raw(
                        primary,
                        scan.path,
                        scan.layer,
                        "gerber",
                    ),
                    "related": primitive_mapping_raw(
                        related,
                        scan.path,
                        scan.layer,
                        "gerber",
                    ),
                },
            )

        electrical_primitives = tuple(
            primitive
            for primitive in primitives
            if primitive.function != "NonConductor"
        )
        electrical_index = BboxGridIndex(
            tuple((None, primitive) for primitive in electrical_primitives)
        )
        track_count = 0
        for track in (
            primitive
            for primitive in signal_segments
            if primitive.function == "Conductor" and primitive.net
        ):
            track_count += 1
            periodic_checkpoint(checkpoint, track_count)
            dangling_endpoints = tuple(
                endpoint
                for endpoint in (track.start, track.end)
                if not gerber_point_connected(
                    endpoint,
                    track,
                    electrical_primitives,
                    electrical_index,
                )
            )
            if not dangling_endpoints:
                continue
            yield ScanFinding(
                "Dangling Tracks",
                "Gerber conductor has an endpoint that is not connected to same-net copper.",
                category="Signal Integrity",
                value=1.0,
                layer=scan.layer,
                color="red",
                raw={
                    "file": scan.path,
                    "segment": track.location_segment(),
                    "width": track.width,
                    "bbox": track.bbox,
                    "dangling_endpoints": dangling_endpoints,
                    "primary": primitive_mapping_raw(
                        track,
                        scan.path,
                        scan.layer,
                        "gerber",
                    ),
                },
            )

    yield from scan_unconnected_vias(all_copper_scans, checkpoint=checkpoint)
    yield from scan_trace_missing(all_copper_scans, checkpoint=checkpoint)


def gerber_point_connected(point, source, candidates, candidate_index=None):
    endpoint_radius = max(0.0, float(source.width or 0.0) / 2.0)
    endpoint_cap = GerberPrimitive(
        "circle",
        center=point,
        width=endpoint_radius * 2.0,
    )
    nearby = (
        (
            item[1]
            for item in candidate_index.candidates(
                (point[0], point[1], point[0], point[1]), endpoint_radius
            )
        )
        if candidate_index is not None
        else candidates
    )
    for candidate in nearby:
        if candidate is source or not nets_compatible(source, candidate):
            continue
        if primitive_gap(endpoint_cap, candidate) <= 1e-9:
            return True
    return False


def nets_compatible(left, right):
    return bool(left.net and right.net and left.net == right.net)


def scan_unconnected_vias(scans, checkpoint=None):
    scan_primitives = []
    via_groups = {}
    for scan in scans:
        primitives = tuple(
            primitive
            for primitive in visible_primitives(scan)
            if valid_bbox_item(primitive) and primitive.function != "NonConductor"
        )
        scan_primitives.append((scan, primitives))
        for primitive in primitives:
            if primitive.function != "ViaPad" or not primitive.net or primitive.center is None:
                continue
            key = (point_key(primitive.center), primitive.net)
            via_groups.setdefault(key, []).append((scan, primitive))

    copper_index = BboxGridIndex(
        tuple(
            (scan, primitive)
            for scan, primitives in scan_primitives
            for primitive in primitives
        )
    )
    group_count = 0
    for group in via_groups.values():
        group_count += 1
        periodic_checkpoint(checkpoint, group_count)
        connected = False
        for _via_scan, via in group:
            for _scan, candidate in copper_index.candidates(via.bbox, 0.0):
                if candidate.function == "ViaPad" or not nets_compatible(via, candidate):
                    continue
                if primitive_gap(via, candidate) <= 1e-9:
                    connected = True
                    break
            if connected:
                break
        if connected:
            continue
        primary_scan, primary = group[0]
        layers = []
        for scan, _via in group:
            for layer in scan.layer or ():
                if layer not in layers:
                    layers.append(layer)
        yield ScanFinding(
            "Unconnected Vias",
            "Gerber via pad is not connected to same-net copper on any exported copper layer.",
            category="Signal Integrity",
            value=1.0,
            layer=layers or primary_scan.layer,
            color="red",
            raw={
                "file": primary_scan.path,
                "point": primary.center,
                "width": primary.width,
                "bbox": component_bbox(tuple(via for _scan, via in group)),
                "via_layers": layers,
                "primary": primitive_mapping_raw(
                    primary,
                    primary_scan.path,
                    primary_scan.layer,
                    "gerber",
                ),
            },
        )


def scan_trace_missing(scans, checkpoint=None):
    components_by_net = {}
    for scan in scans:
        primitives_by_net = {}
        for primitive in valid_visible_primitives(scan):
            if primitive.function == "NonConductor" or not primitive.net:
                continue
            primitives_by_net.setdefault(primitive.net, []).append(primitive)
        for net, primitives in primitives_by_net.items():
            for component in primitive_components(primitives, checkpoint=checkpoint):
                components_by_net.setdefault(net, []).append((scan, component))

    for net, components in components_by_net.items():
        if is_no_connect_net(net):
            continue
        if len(components) < 2:
            continue
        parents = list(range(len(components)))

        def root(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def join(left, right):
            left_root, right_root = root(left), root(right)
            if left_root != right_root:
                parents[right_root] = left_root

        bridge_owners = {}
        for index, (_scan, component) in enumerate(components):
            for primitive in component:
                keys = []
                if primitive.object_id:
                    keys.append(("object", primitive.object_id))
                if primitive.function == "ViaPad" and primitive.center is not None:
                    keys.append(("via", point_key(primitive.center), net))
                if primitive.function == "ComponentPad":
                    # KiCad omits TO.P object ids for component-pad flashes on
                    # inner copper layers.  Identical same-net pad geometry at
                    # the same position is the annulus of one plated pad and
                    # therefore bridges those layer components.
                    keys.append(("pth_pad", primitive_geometry_key(primitive), net))
                for key in keys:
                    if key in bridge_owners:
                        join(index, bridge_owners[key])
                    else:
                        bridge_owners[key] = index

        merged = {}
        for index, (scan, component) in enumerate(components):
            merged.setdefault(root(index), []).append((scan, component))
        groups = [
            group
            for group in merged.values()
            if component_group_has_routed_track(group)
        ]
        if len(groups) < 2:
            continue
        largest = max(groups, key=lambda group: sum(len(component) for _scan, component in group))
        largest_bbox = component_group_bbox(largest)
        for group in groups:
            if group is largest:
                continue
            # A component made only from ViaPad flashes is already reported by
            # Unconnected Vias.  Reporting it again as Trace Mssing obscures
            # the distinction between an isolated via and a split routed net.
            if all(
                primitive.function == "ViaPad"
                for _scan, component in group
                for primitive in component
            ):
                continue
            scan, component = group[0]
            representative = component[0]
            bbox = component_group_bbox(group)
            yield ScanFinding(
                "Trace Mssing",
                "Gerber X2 net is split into disconnected copper components.",
                category="Signal Integrity",
                value=bbox_gap(bbox, largest_bbox),
                layer=scan.layer,
                color="red",
                raw={
                    "file": scan.path,
                    "bbox": bbox,
                    "net": net,
                    "component_size": sum(len(items) for _scan, items in group),
                    "primary": primitive_mapping_raw(
                        representative, scan.path, scan.layer, "gerber"
                    ),
                },
            )


def component_group_bbox(group):
    return component_bbox(
        tuple(
            primitive
            for _scan, component in group
            for primitive in component
        )
    )


def component_group_has_routed_track(group):
    return any(
        primitive.function == "Conductor"
        and primitive.kind in ("segment", "obround")
        and not primitive.is_flash
        for _scan, component in group
        for primitive in component
    )


def primitive_geometry_key(primitive):
    return (
        primitive.kind,
        tuple(round(value, 6) for value in primitive.bbox),
    )


def is_no_connect_net(net):
    normalized = str(net or "").strip().lower()
    return normalized in ("n/c", "nc", "no_connect") or normalized.startswith(
        "unconnected-("
    )


def is_outer_copper_scan(scan):
    names = {str(layer) for layer in scan.layer or ()}
    return bool(names.intersection(("F.Cu", "B.Cu", "CuTop", "CuBottom")))


def acute_signal_segment_pairs(segments):
    endpoints = {}
    for index, primitive in enumerate(segments):
        for endpoint in (primitive.start, primitive.end):
            if endpoint is not None:
                endpoints.setdefault(point_key(endpoint), []).append((index, endpoint))
    selected = []
    selected_pairs = set()
    for entries in endpoints.values():
        for left_offset, (left_index, shared) in enumerate(entries):
            left = segments[left_index]
            for right_index, _right_shared in entries[left_offset + 1:]:
                right = segments[right_index]
                if left.net and right.net and left.net != right.net:
                    continue
                angle = segment_join_angle(left, right, shared)
                if angle <= 1.0 or angle >= 89.0:
                    continue
                pair_key = tuple(sorted((left_index, right_index)))
                if pair_key not in selected_pairs:
                    selected_pairs.add(pair_key)
                    selected.append((left, right))
    return tuple(selected)


def gerber_acute_junction_is_exposed(left, right, candidates, candidate_index=None):
    shared_keys = set((point_key(left.start), point_key(left.end))).intersection(
        (point_key(right.start), point_key(right.end))
    )
    if not shared_keys:
        return False
    shared = next(iter(shared_keys))
    nearby = (
        (
            item[1]
            for item in candidate_index.candidates(
                (shared[0], shared[1], shared[0], shared[1]), 0.0
            )
        )
        if candidate_index is not None
        else candidates
    )
    for candidate in nearby:
        if candidate is left or candidate is right:
            continue
        if not nets_compatible(left, candidate):
            continue
        if point_in_primitive(shared, candidate):
            # Pads, teardrops, zones, and additional branches make the copper
            # union at this node ambiguous; centerline angle alone cannot prove
            # that an acute copper notch remains exposed.
            return False
    return True


def acute_signal_segments(segments):
    """Compatibility helper returning the unique primitives in acute pairs."""
    selected = []
    seen = set()
    for left, right in acute_signal_segment_pairs(segments):
        for primitive in (left, right):
            identity = id(primitive)
            if identity not in seen:
                seen.add(identity)
                selected.append(primitive)
    return tuple(selected)


def segment_join_angle(left, right, shared):
    left_other = left.end if point_key(left.start) == point_key(shared) else left.start
    right_other = right.end if point_key(right.start) == point_key(shared) else right.start
    left_vector = (left_other[0] - shared[0], left_other[1] - shared[1])
    right_vector = (right_other[0] - shared[0], right_other[1] - shared[1])
    left_length = distance((0.0, 0.0), left_vector)
    right_length = distance((0.0, 0.0), right_vector)
    if left_length <= 0 or right_length <= 0:
        return 180.0
    cosine = max(
        -1.0,
        min(
            1.0,
            (
                left_vector[0] * right_vector[0]
                + left_vector[1] * right_vector[1]
            )
            / (left_length * right_length),
        ),
    )
    return math.degrees(math.acos(cosine))


def point_key(point):
    return round(point[0], 6), round(point[1], 6)


def primitive_components(primitives, checkpoint=None):
    primitives = tuple(primitives)
    if not primitives:
        return ()
    parents = list(range(len(primitives)))

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

    endpoint_indexes = {}
    for index, primitive in enumerate(primitives):
        for endpoint in (primitive.start, primitive.end):
            if endpoint is None:
                continue
            key = point_key(endpoint)
            for other in endpoint_indexes.get(key, ()):
                join(index, other)
            endpoint_indexes.setdefault(key, []).append(index)
    spatial_index = BboxGridIndex(tuple(enumerate(primitives)))
    candidate_count = 0
    for left_index, left in enumerate(primitives):
        for right_index, right in spatial_index.candidates(left.bbox, 0.0):
            if right_index <= left_index:
                continue
            candidate_count += 1
            periodic_checkpoint(checkpoint, candidate_count)
            if bbox_gap(left.bbox, right.bbox) > 0:
                continue
            if primitive_gap(left, right) <= 1e-9:
                join(left_index, right_index)
    components = {}
    for index in range(len(primitives)):
        components.setdefault(root(index), []).append(primitives[index])
    return tuple(tuple(component) for component in components.values())


def component_bbox(component):
    boxes = [primitive.bbox for primitive in component if valid_bbox_item(primitive)]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def primitive_touches_conductor(primitive, conductors, starts, max_width):
    for conductor in x_window_candidates(
        primitive,
        conductors,
        starts,
        max_width,
    ):
        if conductor.bbox[0] > primitive.bbox[2]:
            break
        if bbox_gap(primitive.bbox, conductor.bbox) > 0:
            continue
        if primitive_gap(primitive, conductor) <= 1e-9:
            return True
    return False


def scan_copper_to_board_edge(scans, drill_scans=None, reporting_limits=None):
    edge_items = [
        (scan, segment)
        for scan in scans
        if scan.is_edge
        for segment in scan.segments
        if valid_bbox_item(segment)
    ]
    if not edge_items:
        return
    edge_index = BboxGridIndex(edge_items)

    copper_primitives = [
        (scan, primitive)
        for scan in scans
        if scan.is_copper
        for primitive in valid_visible_primitives(scan)
    ]
    if not copper_primitives:
        return

    drilled_flash_index = board_edge_drill_index(drill_scans)
    drilled_primitive_matches = board_edge_drilled_primitive_matches(
        copper_primitives,
        drilled_flash_index,
    )
    drilled_primitive_ids = set(drilled_primitive_matches)
    logical_pad_groups = {}

    for scan, primitive in copper_primitives:
        logical_key = (
            board_edge_logical_pad_key(scan, primitive)
            if is_board_edge_pad_primitive(primitive)
            else None
        )
        if logical_key is not None:
            logical_pad_groups.setdefault(logical_key, [scan, []])[1].append(
                primitive
            )
            continue
        item = copper_to_board_edge_item(
            primitive,
            drilled_flash_index,
            drilled_primitive_ids,
        )
        reporting_limit = (
            reporting_limits.get(item)
            if reporting_limits is not None
            else None
        )
        match = nearest_primitive_edge_match(
            primitive,
            edge_index,
            reporting_limit,
        )
        if match is None:
            continue
        yield copper_to_board_edge_finding(
            scan,
            primitive,
            item,
            match[0],
            match[1],
            match[2],
            drill_match=drilled_primitive_matches.get(id(primitive)),
        )

    for scan, members in logical_pad_groups.values():
        for component in board_edge_logical_pad_components(members):
            item = board_edge_component_item(
                component,
                drilled_flash_index,
                drilled_primitive_ids,
            )
            reporting_limit = (
                reporting_limits.get(item)
                if reporting_limits is not None
                else None
            )
            best = min(
                (
                    (
                        nearest_primitive_edge_match(
                            primitive,
                            edge_index,
                            reporting_limit,
                        ),
                        primitive,
                    )
                    for primitive in component
                ),
                key=lambda candidate: (
                    math.inf
                    if candidate[0] is None
                    else candidate[0][0]
                ),
                default=(None, None),
            )
            match, primitive = best
            if match is not None:
                yield copper_to_board_edge_finding(
                    scan,
                    primitive,
                    item,
                    match[0],
                    match[1],
                    match[2],
                    drill_match=next(
                        (
                            drilled_primitive_matches[id(member)]
                            for member in component
                            if id(member) in drilled_primitive_matches
                        ),
                        None,
                    ),
                )


def copper_to_board_edge_finding(
    scan,
    primitive,
    item,
    gap,
    edge_scan=None,
    edge=None,
    through_hole=False,
    drill_match=None,
):
    raw = {
        "file": scan.path,
        "segment": primitive.location_segment(),
        "width": primitive.width,
        "bbox": primitive.bbox,
        "primary": primitive_mapping_raw(
            primitive,
            scan.path,
            scan.layer,
            "gerber",
        ),
    }
    if drill_match is not None:
        through_hole = True
    if through_hole:
        # Keep the per-layer Gerber evidence, while marking copper belonging
        # to one physical drilled feature so the presentation layer can fold
        # its identical layer observations into one locatable result.
        raw["primary"]["through_hole"] = True
    if drill_match is not None:
        drill_scan, drill = drill_match
        drill_identity = primitive_mapping_raw(
            drill,
            drill_scan.path,
            drill_scan.layer,
            "drill",
        )
        drill_identity["plated"] = drill_scan.plated
        drill_identity["layer_span"] = drill_scan.layer_span
        drill_identity["file_function"] = drill_scan.file_function
        raw["primary"]["drill_identity"] = drill_identity
    if edge_scan is not None and edge is not None:
        raw["related"] = {
            "file": edge_scan.path,
            "layer": edge_scan.layer,
            "item_type": "gerber",
            "kind": "board_edge",
            "segment": (edge.start, edge.end),
            "bbox": edge.bbox,
            "width": edge.width,
        }
    return ScanFinding(
        item,
        "Gerber copper-to-board-edge clearance is {0:.3f}mm.".format(gap),
        category="Copper-to-Board Edge",
        value=gap,
        layer=scan.layer,
        raw=raw,
    )


def board_edge_logical_pad_key(scan, primitive):
    if primitive.object_id:
        return scan.path, "object", primitive.object_id
    if primitive.flash_id:
        return scan.path, "flash", primitive.flash_id
    return None


def board_edge_logical_pad_components(members):
    """Keep every D03 flash together, even for disconnected custom pads."""
    by_flash = {}
    without_flash = []
    for primitive in members:
        if primitive.flash_id:
            by_flash.setdefault(primitive.flash_id, []).append(primitive)
        else:
            without_flash.append(primitive)
    yield from by_flash.values()
    yield from connected_pad_components(without_flash)


def board_edge_drilled_primitive_matches(
    copper_primitives,
    drilled_flash_index,
):
    if drilled_flash_index is None:
        return {}
    grouped = {}
    ungrouped = []
    for scan, primitive in copper_primitives:
        key = board_edge_logical_pad_key(scan, primitive)
        if key is None:
            ungrouped.append(primitive)
        else:
            grouped.setdefault(key, []).append(primitive)
    drilled = {}
    for primitive in ungrouped:
        match = board_edge_primitive_drill_match(
            primitive,
            drilled_flash_index,
        )
        if match is not None:
            drilled[id(primitive)] = match[1]
    for members in grouped.values():
        for component in board_edge_logical_pad_components(members):
            matches = [
                match
                for primitive in component
                for match in (
                    board_edge_primitive_drill_match(
                        primitive,
                        drilled_flash_index,
                    ),
                )
                if match is not None
            ]
            if matches:
                match = min(matches, key=lambda candidate: candidate[0])
                drill_match = match[1]
                drilled.update(
                    (id(primitive), drill_match) for primitive in component
                )
    return drilled


def board_edge_drilled_primitive_ids(copper_primitives, drilled_flash_index):
    """Compatibility projection of the drilled copper primitive map."""
    return set(
        board_edge_drilled_primitive_matches(
            copper_primitives,
            drilled_flash_index,
        )
    )


def board_edge_primitive_drill_match(primitive, drilled_flash_index):
    if not is_board_edge_pad_primitive(primitive):
        return None
    matches = []
    for scan, drill in drilled_flash_index.candidates(
        primitive.bbox,
        BOARD_EDGE_DRILL_MATCH_TOLERANCE_MM,
    ):
        center_distance = primitive_center_distance(drill, primitive)
        if center_distance <= BOARD_EDGE_DRILL_MATCH_TOLERANCE_MM:
            matches.append((center_distance, (scan, drill)))
    return min(matches, key=lambda candidate: candidate[0], default=None)


def board_edge_primitive_has_drill(primitive, drilled_flash_index):
    return board_edge_primitive_drill_match(
        primitive,
        drilled_flash_index,
    ) is not None


def board_edge_drill_index(drill_scans):
    drills = tuple(
        (scan, drill)
        for scan in drill_scans or ()
        for drill in scan.primitives
        if valid_bbox_item(drill)
    )
    return BboxGridIndex(drills) if drills else None


def copper_to_board_edge_item(
    primitive,
    drilled_flash_index=None,
    drilled_primitive_ids=None,
):
    """Classify the copper object instead of treating every flash as SMD."""
    function = normalized_aperture_function(primitive)
    if is_trace_copper_primitive(primitive):
        return "Trace-to-Board Edge"
    if function.startswith("viapad"):
        return "Copper-to-Board Edge"
    if drilled_primitive_ids is not None and id(primitive) in drilled_primitive_ids:
        return "Copper-to-Board Edge"
    if drilled_flash_index is not None and board_edge_primitive_has_drill(
        primitive,
        drilled_flash_index,
    ):
        return "Copper-to-Board Edge"
    if is_surface_mount_pad_primitive(primitive) or is_bga_pad_primitive(
        primitive
    ):
        return "SMD-to-Board Edge"
    if function.startswith("componentpad"):
        return "SMD-to-Board Edge"
    if primitive.is_flash and not function:
        return "SMD-to-Board Edge"
    return "Copper-to-Board Edge"


def is_board_edge_pad_primitive(primitive):
    return bool(
        primitive.is_flash
        or is_pad_copper_primitive(primitive)
        or is_via_copper_primitive(primitive)
    )


def board_edge_component_item(
    component,
    drilled_flash_index=None,
    drilled_primitive_ids=None,
):
    items = {
        copper_to_board_edge_item(
            primitive,
            drilled_flash_index,
            drilled_primitive_ids,
        )
        for primitive in component
    }
    if items == {"SMD-to-Board Edge"}:
        return "SMD-to-Board Edge"
    if items == {"Trace-to-Board Edge"}:
        return "Trace-to-Board Edge"
    return "Copper-to-Board Edge"


def nearest_primitive_edge_match(primitive, edge_index, max_gap=None):
    """Return the exact nearest edge without assuming a rectangular outline."""
    if max_gap is not None:
        candidates = tuple(edge_index.candidates(primitive.bbox, max_gap))
        best = min(
            (
                (primitive_segment_gap(primitive, edge), edge_scan, edge)
                for edge_scan, edge in candidates
            ),
            key=lambda match: match[0],
            default=None,
        )
        if best is None or best[0] > max_gap + 1e-9:
            return None
        return best
    margin = BOARD_EDGE_INITIAL_SEARCH_MM
    candidates = ()
    while margin <= 65536.0:
        candidates = tuple(edge_index.candidates(primitive.bbox, margin))
        if candidates:
            break
        margin *= 2.0
    if not candidates:
        candidates = edge_index.items
    measured_ids = {id(edge) for _edge_scan, edge in candidates}
    best = min(
        (
            (primitive_segment_gap(primitive, edge), edge_scan, edge)
            for edge_scan, edge in candidates
        ),
        key=lambda match: match[0],
        default=None,
    )
    if best is None:
        return None
    # Bbox distance is a lower bound.  A second indexed query using the first
    # exact gap proves that no segment excluded by the expanding search can be
    # closer, including concave outlines and internal cut-outs.
    for edge_scan, edge in edge_index.candidates(
        primitive.bbox,
        best[0] + 1e-9,
    ):
        if id(edge) in measured_ids:
            continue
        value = primitive_segment_gap(primitive, edge)
        if value < best[0]:
            best = (value, edge_scan, edge)
    return best


def scan_castellated_holes(drill_scans, gerber_scans):
    edges = [
        (scan, edge)
        for scan in gerber_scans
        if scan.is_edge
        for edge in scan.segments
        if valid_bbox_item(edge)
    ]
    if not edges:
        return
    for drill_scan in drill_scans:
        for drill in drill_scan.primitives:
            if not valid_bbox_item(drill):
                continue
            best = None
            for edge_scan, edge in edges:
                if drill.kind == "slot":
                    center_distance = segment_distance(
                        drill.start, drill.end, edge.start, edge.end
                    )
                else:
                    center_distance = point_to_segment_distance(
                        drill.center, edge.start, edge.end
                    )
                if best is None or center_distance < best[0]:
                    best = (center_distance, edge_scan, edge)
            if best is None or best[0] > drill.diameter / 2.0 + 1e-9:
                continue
            _distance, edge_scan, edge = best
            yield ScanFinding(
                "Castellated Holes",
                "Excellon hole intersects the routed board outline.",
                category="Special Drill Holes",
                value=1.0,
                layer=drill_scan.layer,
                color="red",
                raw={
                    "file": drill_scan.path,
                    "point": drill.center if drill.center is not None else primitive_center(drill),
                    "diameter": drill.diameter,
                    "bbox": drill.bbox,
                    "primary": primitive_mapping_raw(
                        drill, drill_scan.path, drill_scan.layer, "drill"
                    ),
                    "related": {
                        "file": edge_scan.path,
                        "layer": edge_scan.layer,
                        "item_type": "gerber",
                        "segment": (edge.start, edge.end),
                        "bbox": edge.bbox,
                    },
                },
            )


def scan_hole_to_board_edge(
    drill_scans,
    gerber_scans,
    reporting_limits=None,
    checkpoint=None,
):
    """Measure physical Excellon hole edges to the nearest routed edge."""
    edges = tuple(
        (scan, edge)
        for scan in gerber_scans
        if scan.is_edge
        for edge in scan.segments
        if valid_bbox_item(edge)
    )
    if not edges:
        return
    edge_index = BboxGridIndex(edges)
    limits = dict(reporting_limits or {})
    seen = set()
    checked = 0
    for drill_scan in drill_scans:
        for drill in drill_scan.primitives:
            checked += 1
            periodic_checkpoint(checkpoint, checked, interval=256)
            if not valid_bbox_item(drill) or drill.diameter <= 0:
                continue
            identity = hole_to_board_edge_identity(drill_scan, drill)
            if identity in seen:
                continue
            seen.add(identity)
            item = excellon_hole_to_board_edge_item(drill_scan, drill)
            limit = limits.get(item)
            if limit is None or limit <= 0:
                continue
            best = nearest_drill_edge_match(
                drill,
                edge_index,
                limit,
            )
            if best is None:
                continue
            gap, edge_scan, edge = best
            drill_resolution = drill.coordinate_resolution_mm
            if drill_resolution is None:
                drill_resolution = drill_scan.coordinate_resolution_mm
            edge_resolution = edge_scan.coordinate_resolution_mm
            uncertainty = (
                float(drill_resolution or 0.0)
                + float(edge_resolution or 0.0)
            ) / 2.0
            primary = primitive_mapping_raw(
                drill,
                drill_scan.path,
                drill_scan.layer,
                "drill",
            )
            primary.update(
                {
                    "plated": drill_scan.plated,
                    "layer_span": drill_scan.layer_span,
                    "file_function": drill_scan.file_function,
                    "tool_function": drill.function,
                    "tool": drill.tool,
                }
            )
            yield ScanFinding(
                item,
                "Excellon hole-to-board-edge clearance is {0:.3f}mm.".format(
                    gap
                ),
                category="Hole-to-Board Edge",
                value=round(gap, 6),
                layer=drill_scan.layer,
                raw={
                    "file": drill_scan.path,
                    "point": drill.center
                    if drill.center is not None
                    else primitive_center(drill),
                    "segment": drill.location_segment(),
                    "diameter": drill.diameter,
                    "bbox": drill.bbox,
                    "primary": primary,
                    "related": {
                        "file": edge_scan.path,
                        "layer": edge_scan.layer,
                        "item_type": "gerber",
                        "kind": "board_edge",
                        "segment": (edge.start, edge.end),
                        "bbox": edge.bbox,
                        "width": edge.width,
                    },
                    "coordinate_resolution_mm": max(
                        float(drill_resolution or 0.0),
                        float(edge_resolution or 0.0),
                    ),
                    "uncertainty_mm": uncertainty,
                    "measurement_interval_mm": (
                        max(0.0, gap - uncertainty),
                        gap + uncertainty,
                    ),
                },
            )


def hole_to_board_edge_identity(scan, drill):
    if drill.kind == "slot":
        geometry = tuple(
            sorted(
                (
                    (round(drill.start[0], 6), round(drill.start[1], 6)),
                    (round(drill.end[0], 6), round(drill.end[1], 6)),
                )
            )
        )
    else:
        geometry = (
            round(drill.center[0], 6),
            round(drill.center[1], 6),
        )
    return (
        drill.kind,
        geometry,
        round(drill.diameter, 6),
        normalized_layer_span(scan.layer_span),
        scan.plated,
    )


def excellon_hole_to_board_edge_item(scan, drill):
    function = "".join(
        character
        for character in str(drill.function or "").lower()
        if character.isalnum()
    )
    if scan.plated is False:
        return "NPTH-to-Board Edge"
    if function == "viadrill":
        return "Via-to-Board Edge"
    return "PTH-to-Board Edge"


def nearest_drill_edge_match(drill, edge_index, max_gap):
    candidates = edge_index.candidates(drill.bbox, max_gap)
    if drill.kind == "slot":
        matches = (
            (
                max(
                    0.0,
                    segment_distance(
                        drill.start,
                        drill.end,
                        edge.start,
                        edge.end,
                    )
                    - drill.diameter / 2.0,
                ),
                edge_scan,
                edge,
            )
            for edge_scan, edge in candidates
        )
    else:
        matches = (
            (
                max(
                    0.0,
                    point_to_segment_distance(
                        drill.center,
                        edge.start,
                        edge.end,
                    )
                    - drill.diameter / 2.0,
                ),
                edge_scan,
                edge,
            )
            for edge_scan, edge in candidates
        )
    best = min(matches, key=lambda match: match[0], default=None)
    if best is None or best[0] > max_gap + 1e-9:
        return None
    return best


def scan_copper_spacing(scans, reporting_limits=None, checkpoint=None):
    for scan in scans:
        if not scan.is_copper:
            continue
        primitives = sorted(
            (
                primitive
                for primitive in valid_visible_primitives(scan)
                if is_spacing_copper_primitive(primitive)
            ),
            key=lambda primitive: primitive.bbox[0],
        )
        logical_object_keys = copper_spacing_logical_object_keys(primitives)
        possible_items = possible_copper_spacing_items(primitives)
        best_by_item = {}
        best_by_logical_pair = {}
        candidate_count = 0
        for index, left in enumerate(primitives):
            for right in primitives[index + 1:]:
                candidate_count += 1
                periodic_checkpoint(checkpoint, candidate_count)
                search_limit = copper_spacing_global_search_limit(
                    possible_items,
                    best_by_item,
                    reporting_limits,
                )
                if (
                    search_limit is not None
                    and right.bbox[0] > left.bbox[2]
                    and right.bbox[0] - left.bbox[2]
                    > search_limit + COPPER_SPACING_TIE_TOLERANCE_MM
                ):
                    break
                if same_logical_copper_object(
                    left, right, logical_object_keys=logical_object_keys
                ):
                    continue
                if same_nonempty_net(left, right):
                    continue
                items = copper_spacing_items(left, right)
                if not items:
                    continue
                lower_bound = bbox_gap(left.bbox, right.bbox)
                if all(
                    best_by_item.get(item) is not None
                    and lower_bound
                    > copper_spacing_item_search_limit(
                        item,
                        best_by_item[item][0],
                        reporting_limits,
                    )
                    + COPPER_SPACING_TIE_TOLERANCE_MM
                    for item in items
                ):
                    continue
                gap = primitive_gap(left, right)
                if gap is None:
                    continue
                for item in items:
                    current_best = best_by_item.get(item)
                    if current_best is None or gap < current_best[0]:
                        best_by_item[item] = (gap, left, right)
                    pair_key = (
                        item,
                        copper_spacing_logical_pair_key(
                            left, right, logical_object_keys
                        ),
                    )
                    pair_best = best_by_logical_pair.get(pair_key)
                    if pair_best is None or gap < pair_best[0]:
                        best_by_logical_pair[pair_key] = (gap, left, right)
        reportable_by_item = {}
        for (item, _pair_key), finding in best_by_logical_pair.items():
            reporting_limit = (reporting_limits or {}).get(item)
            if (
                reporting_limit is not None
                and finding[0] < float(reporting_limit)
            ):
                reportable_by_item.setdefault(item, []).append(finding)
        for spacing_item in possible_items:
            reporting_limit = (reporting_limits or {}).get(spacing_item)
            if reporting_limit is None:
                continue
            passing_findings = [
                finding
                for (item, _pair_key), finding in best_by_logical_pair.items()
                if item == spacing_item
                and finding[0] >= float(reporting_limit)
            ]
            if not passing_findings:
                continue
            passing_minimum = min(finding[0] for finding in passing_findings)
            tied = reportable_by_item.setdefault(spacing_item, [])
            for finding in passing_findings:
                if (
                    finding[0]
                    <= passing_minimum + COPPER_SPACING_TIE_TOLERANCE_MM
                    and finding not in tied
                ):
                    tied.append(finding)
        for item, best in best_by_item.items():
            findings = reportable_by_item.get(item) or [best]
            findings.sort(key=lambda finding: finding[0])
            for gap, left, right in findings:
                yield copper_spacing_finding(scan, item, gap, left, right)


def possible_copper_spacing_items(primitives):
    segments = [primitive for primitive in primitives if is_trace_copper_primitive(primitive)]
    pads = [primitive for primitive in primitives if is_pad_copper_primitive(primitive)]
    smd_pads = [
        primitive
        for primitive in pads
        if is_surface_mount_pad_primitive(primitive)
    ]
    bga_pads = [
        primitive
        for primitive in pads
        if is_bga_pad_primitive(primitive)
    ]
    general_pads = [
        primitive
        for primitive in pads
        if not is_bga_pad_primitive(primitive)
        and not is_surface_mount_pad_primitive(primitive)
    ]
    possible = set()
    if compatible_pair_can_exist(segments, segments, same_collection=True):
        possible.add("Trace Spacing")
    if compatible_pair_can_exist(segments, pads):
        possible.add("Trace-to-Pad Spacing")
    if compatible_pair_can_exist(smd_pads, smd_pads, same_collection=True):
        possible.add("SMD Pad Spacing")
    if compatible_pair_can_exist(bga_pads, pads):
        possible.add("BGA Pads")
    if (
        compatible_pair_can_exist(general_pads, general_pads, same_collection=True)
        or compatible_pair_can_exist(general_pads, smd_pads)
    ):
        possible.add("Pad-to-Pad Spacing")
    return possible


def compatible_pair_can_exist(left_items, right_items, same_collection=False):
    if not left_items or not right_items:
        return False
    if same_collection and len(left_items) < 2:
        return False
    left_nets = {str(getattr(item, "net", "") or "") for item in left_items}
    if same_collection:
        return "" in left_nets or len(left_nets) > 1
    if len({id(item) for item in left_items + right_items}) < 2:
        return False
    right_nets = {str(getattr(item, "net", "") or "") for item in right_items}
    if "" in left_nets or "" in right_nets:
        return True
    return len(left_nets) > 1 or len(right_nets) > 1 or left_nets != right_nets


def copper_spacing_global_search_limit(possible_items, best_by_item, reporting_limits):
    if not possible_items or any(item not in best_by_item for item in possible_items):
        return None
    return max(
        copper_spacing_item_search_limit(
            item,
            best_by_item[item][0],
            reporting_limits,
        )
        for item in possible_items
    )


def copper_spacing_item_search_limit(item, current_best, reporting_limits):
    limit = max(
        float(current_best or 0.0),
        float((reporting_limits or {}).get(item) or 0.0),
    )
    if (reporting_limits or {}).get(item) is not None:
        limit = max(limit, COPPER_SPACING_PASSING_WINDOW_MM)
    return limit


def copper_spacing_finding(scan, item, gap, left, right):
    category = (
        "SMD Spacing"
        if item == "SMD Pad Spacing"
        else "Smallest Trace Spacing"
    )
    return ScanFinding(
        item,
        "Gerber copper spacing is {0:.3f}mm.".format(gap),
        category=category,
        value=gap,
        layer=scan.layer,
        raw={
            "file": scan.path,
            "segment": spacing_location(left, right),
            "width": highlight_width(left, right),
            "bbox": primitive_pair_bbox(left, right),
            "primary": primitive_mapping_raw(left, scan.path, scan.layer, "gerber"),
            "related": primitive_mapping_raw(right, scan.path, scan.layer, "gerber"),
        },
    )
def copper_spacing_item(left, right):
    items = copper_spacing_items(left, right)
    if "SMD Pad Spacing" in items:
        return "SMD Pad Spacing"
    return items[0] if items else None


def copper_spacing_items(left, right):
    if is_via_copper_primitive(left) or is_via_copper_primitive(right):
        return ()
    left_pad = is_pad_copper_primitive(left)
    right_pad = is_pad_copper_primitive(right)
    if left_pad and right_pad:
        if is_bga_pad_primitive(left) or is_bga_pad_primitive(right):
            return ("BGA Pads",)
        if (
            is_surface_mount_pad_primitive(left)
            and is_surface_mount_pad_primitive(right)
        ):
            return ("SMD Pad Spacing",)
        return ("Pad-to-Pad Spacing",)
    if left_pad != right_pad:
        other = right if left_pad else left
        return ("Trace-to-Pad Spacing",) if is_trace_copper_primitive(other) else ()
    if is_trace_copper_primitive(left) and is_trace_copper_primitive(right):
        return ("Trace Spacing",)
    return ()


def is_pad_copper_primitive(primitive):
    function = normalized_aperture_function(primitive)
    return bool(
        not function.startswith("viapad")
        and (
            function.startswith(
                (
                    "smdpad",
                    "componentpad",
                    "testpad",
                    "bgapad",
                    "connectorpad",
                    "heatsinkpad",
                    "castellatedpad",
                    "fiducialpad",
                    "washerpad",
                )
            )
            or (not function and primitive.is_flash)
        )
    )


def is_surface_mount_pad_primitive(primitive):
    """Return true for X2 copper functions representing surface pads.

    KiCad emits exposed thermal pads, test points, local fiducials, and edge
    connector fingers under their role-specific X2 aperture functions rather
    than ``SMDPad``.  They are still surface copper pads for clearance
    purposes.  BGA pads are handled separately so their dedicated rule wins.
    """
    return normalized_aperture_function(primitive).startswith(
        (
            "smdpad",
            "testpad",
            "connectorpad",
            "heatsinkpad",
            "fiducialpad",
        )
    )


def is_bga_pad_primitive(primitive):
    return normalized_aperture_function(primitive).startswith("bgapad")


def is_via_copper_primitive(primitive):
    return normalized_aperture_function(primitive).startswith("viapad")


def is_trace_copper_primitive(primitive):
    return bool(
        primitive.kind in ("segment", "obround")
        and not primitive.is_flash
        and not is_pad_copper_primitive(primitive)
        and not is_via_copper_primitive(primitive)
        and normalized_aperture_function(primitive) in ("", "conductor")
    )


def is_spacing_copper_primitive(primitive):
    return is_pad_copper_primitive(primitive) or is_trace_copper_primitive(primitive)


def copper_spacing_logical_pair_key(left, right, logical_object_keys=None):
    keys = (
        copper_spacing_object_key(left, logical_object_keys),
        copper_spacing_object_key(right, logical_object_keys),
    )
    return tuple(sorted(keys, key=repr))


def copper_spacing_object_key(primitive, logical_object_keys=None):
    if logical_object_keys is not None:
        key = logical_object_keys.get(id(primitive))
        if key is not None:
            return key
    if is_pad_copper_primitive(primitive) and primitive.flash_id:
        return "flash", primitive.flash_id
    if is_pad_copper_primitive(primitive) and primitive.object_id:
        return "pad", primitive.object_id
    return "primitive", id(primitive)


def copper_spacing_logical_object_keys(primitives):
    """Build spatially safe identities for X2 pad primitives.

    One D03 macro flash may expand into several primitives.  KiCad also emits
    some custom pads as several touching flashes carrying one ``TO.P`` object
    id.  Conversely, repeated unnumbered/mechanical pads may reuse an object
    id at disconnected locations.  Merge the former, but not the latter.
    """
    pads = [primitive for primitive in primitives if is_pad_copper_primitive(primitive)]
    if not pads:
        return {}

    groups = []
    flash_group_indexes = {}
    primitive_group = {}
    for pad in pads:
        flash_id = str(getattr(pad, "flash_id", "") or "")
        if flash_id:
            group_index = flash_group_indexes.get(flash_id)
            if group_index is None:
                group_index = len(groups)
                flash_group_indexes[flash_id] = group_index
                groups.append([])
        else:
            group_index = len(groups)
            groups.append([])
        groups[group_index].append(pad)
        primitive_group[id(pad)] = group_index

    parents = list(range(len(groups)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left_index, right_index):
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parents[right_root] = left_root

    object_groups = {}
    for group_index, members in enumerate(groups):
        object_ids = {
            str(getattr(member, "object_id", "") or "") for member in members
        }
        for object_id in object_ids:
            if object_id:
                object_groups.setdefault(object_id, []).append(group_index)
    for group_indexes in object_groups.values():
        for offset, left_index in enumerate(group_indexes):
            for right_index in group_indexes[offset + 1:]:
                if pad_primitive_groups_touch(
                    groups[left_index], groups[right_index]
                ):
                    union(left_index, right_index)

    return {
        id(pad): ("pad-component", find(group_index))
        for pad in pads
        for group_index in (primitive_group[id(pad)],)
    }


def pad_primitive_groups_touch(left_members, right_members):
    for left in left_members:
        for right in right_members:
            if bbox_gap(left.bbox, right.bbox) > COPPER_SPACING_TIE_TOLERANCE_MM:
                continue
            gap = primitive_gap(left, right)
            if gap is not None and gap <= COPPER_SPACING_TIE_TOLERANCE_MM:
                return True
    return False


def primitive_pair_bbox(left, right):
    return (
        min(left.bbox[0], right.bbox[0]),
        min(left.bbox[1], right.bbox[1]),
        max(left.bbox[2], right.bbox[2]),
        max(left.bbox[3], right.bbox[3]),
    )


def highlight_width(left, right):
    widths = [
        value
        for value in (
            getattr(left, "shape_width", None) or getattr(left, "width", None),
            getattr(right, "shape_width", None) or getattr(right, "width", None),
        )
        if value
    ]
    return min(widths) if widths else None


def primitive_mapping_raw(primitive, path, layer=None, item_type=None):
    data = {
        "file": path,
        "bbox": primitive.bbox,
        "kind": getattr(primitive, "kind", ""),
        "is_flash": bool(getattr(primitive, "is_flash", False)),
    }
    if layer is not None:
        data["layer"] = layer
    if item_type:
        data["item_type"] = item_type
    if getattr(primitive, "net", ""):
        data["net"] = primitive.net
    if getattr(primitive, "function", ""):
        data["aperture_function"] = primitive.function
    if getattr(primitive, "component", ""):
        data["component"] = primitive.component
    if getattr(primitive, "object_id", ""):
        data["object_id"] = primitive.object_id
    if getattr(primitive, "flash_id", ""):
        data["flash_id"] = primitive.flash_id
    segment = primitive.location_segment()
    if segment:
        data["segment"] = segment
    center = getattr(primitive, "center", None)
    if center is not None:
        data["point"] = center
    width = getattr(primitive, "shape_width", None) or getattr(primitive, "width", None)
    diameter = getattr(primitive, "diameter", None)
    if width:
        data["width"] = width
    if diameter:
        data["diameter"] = diameter
    coordinate_resolution = getattr(primitive, "coordinate_resolution_mm", None)
    if coordinate_resolution is not None:
        data["coordinate_resolution_mm"] = coordinate_resolution
        data["quantization_tolerance_mm"] = coordinate_resolution / 2.0
    return data


def scan_pad_size_and_ring(drill_scans, gerber_scans):
    for finding in scan_pad_drill_features(drill_scans, gerber_scans, include_holes_on_smd=False):
        yield finding


def scan_smd_pad_size(gerber_scans):
    for scan in gerber_scans:
        if not scan.is_copper:
            continue
        pads = [
            pad
            for pad in valid_visible_primitives(scan)
            if pad.is_flash
            and is_smd_pad_or_legacy(pad)
        ]
        for pad in merged_x2_pad_objects(pads, include_composite=False):
            if (
                pad.shape_width <= 0
                or pad.shape_height <= 0
            ):
                continue
            short = pad_shorter_side_mm(pad.shape_width, pad.shape_height)
            item = pad_size_item(pad.shape_width, pad.shape_height)
            yield smd_pad_size_finding(short, scan, pad, item)


def scan_missing_smask_openings(drill_scans, gerber_scans, checkpoint=None):
    drills = tuple(
        (scan, drill)
        for scan in drill_scans
        for drill in scan.primitives
        if valid_bbox_item(drill)
    )
    drill_index = BboxGridIndex(drills)
    masks_by_side = {"F": [], "B": []}
    mask_sides = set()
    for scan in gerber_scans:
        layer_names = {str(layer) for layer in scan.layer or ()}
        side = "F" if "F.Mask" in layer_names else "B" if "B.Mask" in layer_names else None
        if side:
            mask_sides.add(side)
            masks_by_side[side].extend(
                (scan, primitive)
                for primitive in valid_visible_primitives(scan)
            )
    mask_indexes = {
        side: BboxGridIndex(items)
        for side, items in masks_by_side.items()
    }

    pad_count = 0
    for scan in gerber_scans:
        if not scan.is_copper:
            continue
        layer_names = {str(layer) for layer in scan.layer or ()}
        side = "F" if "F.Cu" in layer_names else "B" if "B.Cu" in layer_names else None
        if side is None or side not in mask_sides:
            continue
        pads = [
            primitive
            for primitive in valid_visible_primitives(scan)
            if primitive.is_flash
            and (
                not normalized_aperture_function(primitive)
                or (
                    "pad" in normalized_aperture_function(primitive)
                    and normalized_aperture_function(primitive) != "viapad"
                )
            )
        ]
        for pad in merged_x2_pad_objects(pads):
            pad_count += 1
            periodic_checkpoint(checkpoint, pad_count, interval=256)
            if any(
                drill_pad_centers_match(drill, pad)
                for _drill_scan, drill in drill_index.candidates(pad.bbox, 0.025)
            ):
                continue
            coverage = logical_mask_opening_coverage(
                pad,
                masks_by_side[side],
                mask_indexes[side],
            )
            if coverage["complete"]:
                continue
            function = normalized_aperture_function(pad)
            x2_status = "explicit_pad" if "pad" in function else "unknown"
            needs_validation = coverage["status"] == "unproven"
            if needs_validation:
                confidence = 0.45 if x2_status == "explicit_pad" else 0.25
            else:
                confidence = 0.65 if x2_status == "explicit_pad" else 0.35
            related = coverage.get("nearest")
            coordinate_resolution = max(
                getattr(pad, "coordinate_resolution_mm", None) or 0.0,
                (
                    getattr(related[1], "coordinate_resolution_mm", None) or 0.0
                    if related is not None
                    else 0.0
                ),
            )
            raw = {
                "file": scan.path,
                "point": pad.center,
                "width": min(pad.shape_width, pad.shape_height),
                "bbox": pad.bbox,
                "mask_layer": side + ".Mask",
                "mask_source_files": tuple(
                    sorted({mask_scan.path for mask_scan, _mask in coverage["masks"]})
                ),
                "coverage_basis": coverage["basis"],
                "mask_coverage_status": coverage["status"],
                "coverage_ratio": coverage["ratio"],
                "coverage_sample_count": coverage["sample_count"],
                "uncovered_sample_points": coverage["uncovered_points"][:16],
                "coverage": "partial" if needs_validation else "complete",
                "execution_status": "completed",
                "needs_native_validation": needs_validation,
                "x2_classification": x2_status,
                "confidence": confidence,
                "primary": primitive_mapping_raw(
                    pad, scan.path, scan.layer, "gerber"
                ),
            }
            if coverage.get("sampling_resolution_mm") is not None:
                raw["sampling_resolution_mm"] = coverage["sampling_resolution_mm"]
                raw["sampling_error_mm"] = coverage["sampling_error_mm"]
                raw["format_resolution_mm"] = coverage["format_resolution_mm"]
            if related is not None:
                raw["related"] = primitive_mapping_raw(
                    related[1], related[0].path, related[0].layer, "gerber"
                )
            if coordinate_resolution > 0:
                raw["coordinate_resolution_mm"] = coordinate_resolution
                raw["uncertainty_mm"] = coordinate_resolution
            yield ScanFinding(
                "Missing SMask Opening",
                (
                    "Gerber mask-union sampling cannot prove full pad coverage; native validation is required."
                    if needs_validation
                    else "Gerber pad copper is not fully covered by a solder-mask opening on the same board side."
                ),
                category="Missing SMask Openings",
                value=1.0,
                layer=scan.layer,
                color="gold" if needs_validation else "red",
                raw=raw,
            )


def logical_mask_opening_coverage(pad, mask_items, mask_index=None):
    if mask_index is None:
        mask_index = BboxGridIndex(mask_items)
    nearby = tuple(mask_index.candidates(pad.bbox, 0.0))
    masks = tuple(item[1] for item in nearby)
    if not masks:
        return {
            "complete": False,
            "status": "missing",
            "basis": "no_overlapping_opening",
            "ratio": 0.0,
            "sample_count": 0,
            "uncovered_points": (),
            "masks": nearby,
            "nearest": None,
            "sampling_resolution_mm": None,
            "sampling_error_mm": None,
            "format_resolution_mm": None,
        }
    nearest = min(nearby, key=lambda item: primitive_gap(pad, item[1]))
    if any(primitive_fully_covered_by_mask(pad, mask) for mask in masks):
        return {
            "complete": True,
            "status": "covered",
            "basis": "analytic_single_opening",
            "ratio": 1.0,
            "sample_count": 0,
            "uncovered_points": (),
            "masks": nearby,
            "nearest": nearest,
            "sampling_resolution_mm": None,
            "sampling_error_mm": None,
            "format_resolution_mm": None,
        }
    if pad.kind == "composite" and pad.members and all(
        any(primitive_fully_covered_by_mask(member, mask) for mask in masks)
        for member in pad.members
    ):
        return {
            "complete": True,
            "status": "covered",
            "basis": "analytic_member_opening_union",
            "ratio": 1.0,
            "sample_count": 0,
            "uncovered_points": (),
            "masks": nearby,
            "nearest": nearest,
            "sampling_resolution_mm": None,
            "sampling_error_mm": None,
            "format_resolution_mm": None,
        }
    sampling_resolution, sampling_error, format_resolution = (
        mask_union_sampling_parameters(pad, masks)
    )
    points = logical_coverage_sample_points(pad, sampling_resolution)
    uncovered = tuple(
        point
        for point in points
        if not any(point_in_primitive(point, mask) for mask in masks)
    )
    covered_count = len(points) - len(uncovered)
    ratio = float(covered_count) / len(points) if points else 0.0
    return {
        # Finding one uncovered point proves a mask defect.  Conversely,
        # finite samples cannot prove coverage of the continuous copper
        # shape, so an all-covered sample remains an explicit validation
        # state rather than an unconditional pass.
        "complete": False,
        "status": "missing" if uncovered else "unproven",
        "basis": "resolution_bounded_union_sampling",
        "ratio": ratio,
        "sample_count": len(points),
        "uncovered_points": uncovered,
        "masks": nearby,
        "nearest": nearest,
        "sampling_resolution_mm": sampling_resolution,
        "sampling_error_mm": sampling_error,
        "format_resolution_mm": format_resolution,
    }


def mask_union_sampling_parameters(pad, masks, max_axis_intervals=32):
    format_resolution = max(
        (
            primitive.coordinate_resolution_mm or 0.0
            for primitive in (pad,) + tuple(masks)
        ),
        default=0.0,
    )
    width = max(0.0, pad.bbox[2] - pad.bbox[0])
    height = max(0.0, pad.bbox[3] - pad.bbox[1])
    bounded_step = max(width, height) / float(max_axis_intervals)
    sampling_resolution = max(format_resolution, bounded_step, 1e-12)
    # Half a sample-cell diagonal plus input-coordinate quantization bounds
    # how far an unsampled mask gap can be from a tested point.
    sampling_error = sampling_resolution / math.sqrt(2.0) + format_resolution
    return sampling_resolution, sampling_error, format_resolution


def logical_coverage_sample_points(primitive, sampling_resolution_mm):
    if primitive.kind == "composite":
        points = tuple(
            point
            for member in primitive.members
            for point in logical_coverage_sample_points(
                member, sampling_resolution_mm
            )
        )
        return tuple(dict.fromkeys(points))
    points = list(primitive_sample_points(primitive))
    if primitive.kind == "region" and primitive.points:
        points.append(primitive_center(primitive))
        points.extend(
            (
                (start[0] + end[0]) / 2.0,
                (start[1] + end[1]) / 2.0,
            )
            for start, end in region_edges(primitive)
        )
    left, top, right, bottom = primitive.bbox
    width = max(0.0, right - left)
    height = max(0.0, bottom - top)
    x_intervals = max(
        1, min(32, int(math.ceil(width / sampling_resolution_mm)))
    )
    y_intervals = max(
        1, min(32, int(math.ceil(height / sampling_resolution_mm)))
    )
    for x_step in range(x_intervals + 1):
        x = left + width * x_step / x_intervals
        for y_step in range(y_intervals + 1):
            y = top + height * y_step / y_intervals
            point = (x, y)
            if point_in_primitive(point, primitive):
                points.append(point)
    return tuple(dict.fromkeys(points))


def scan_solder_mask_analysis(gerber_scans, reporting_limits=None, checkpoint=None):
    """Inspect pad mask webs and the copper exposed by each pad opening.

    A Gerber mask file can also contain logos, board-level polygons and other
    graphics.  Those objects are openings in the physical mask, but they are
    not pad openings and must not be paired with an EP/custom-pad flash as a
    solder-mask bridge.  KiCad pad openings are emitted as aperture flashes
    (custom/macro flashes can expand to several primitives sharing one
    ``flash_id``), so retain only components containing such a flash here.
    """
    reporting_limits = reporting_limits or {}
    for side in ("F", "B"):
        mask_layer = side + ".Mask"
        copper_layer = side + ".Cu"
        mask_scans = [
            scan
            for scan in gerber_scans
            if mask_layer in {str(layer) for layer in scan.layer or ()}
        ]
        copper_scans = [
            scan
            for scan in gerber_scans
            if scan.is_copper
            and copper_layer in {str(layer) for layer in scan.layer or ()}
        ]
        masks = [
            (scan, primitive)
            for scan in mask_scans
            for primitive in valid_visible_primitives(scan)
            if primitive.is_flash or primitive.flash_id
        ]
        copper = [
            (scan, primitive)
            for scan in copper_scans
            for primitive in valid_visible_primitives(scan)
            if primitive.net
            and primitive.function != "NonConductor"
            and (
                primitive.is_flash
                or primitive.kind in ("segment", "obround")
            )
        ]
        if not masks:
            continue
        components = list(
            connected_mask_components(masks, checkpoint=checkpoint)
        )
        pad_copper = [
            item
            for item in copper
            if item[1].is_flash
            and "pad" in normalized_aperture_function(item[1])
        ]
        pad_index = BboxGridIndex(pad_copper)
        geometries = [
            _MaskComponentGeometry(
                component,
                pad_anchors=mask_component_pad_anchors(component, pad_index),
            )
            for component in components
        ]
        yield from solder_mask_bridge_findings(
            geometries,
            mask_layer,
            reporting_limits.get("Solder Mask Bridge"),
            checkpoint=checkpoint,
        )
        yield from solder_mask_copper_findings(
            geometries,
            copper,
            mask_layer,
            reporting_limits.get("Solder Mask Covers Trace"),
            checkpoint=checkpoint,
        )


def connected_mask_components(mask_items, checkpoint=None):
    items = tuple(mask_items)
    parents = list(range(len(items)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    # A custom/EP aperture macro is represented by several Gerber primitives.
    # They are one logical D03 flash even when polygon approximation leaves a
    # sub-nanometre seam between individual members.  Merge by flash identity
    # before doing geometric connectivity so those seams never become bridges.
    flash_members = {}
    for index, (scan, primitive) in enumerate(items):
        flash_id = str(getattr(primitive, "flash_id", "") or "")
        if not flash_id:
            continue
        key = (str(getattr(scan, "path", "") or ""), flash_id)
        members = flash_members.setdefault(key, [])
        if members:
            union(members[0], index)
        members.append(index)

    spatial_index = BboxGridIndex(tuple(enumerate(item[1] for item in items)))
    candidate_count = 0
    for left_index, (_left_scan, left) in enumerate(items):
        for right_index, right in spatial_index.candidates(left.bbox, 1e-9):
            if right_index <= left_index:
                continue
            candidate_count += 1
            periodic_checkpoint(checkpoint, candidate_count)
            if primitive_gap_within(left, right, 1e-9) <= 1e-9:
                union(left_index, right_index)

    groups = {}
    for index, item in enumerate(items):
        groups.setdefault(find(index), []).append(item)
    yield from (tuple(component) for component in groups.values())


def solder_mask_bridge_findings(components, mask_layer, reporting_limit, checkpoint=None):
    if reporting_limit is None:
        return
    indexed_components = sorted(
        (
            component
            if isinstance(component, _MaskComponentGeometry)
            else _MaskComponentGeometry(component)
            for component in components
        ),
        key=lambda geometry: geometry.bbox[0],
    )
    candidate_count = 0
    for index, left in enumerate(indexed_components):
        for right in indexed_components[index + 1:]:
            if right.bbox[0] > left.bbox[2] + reporting_limit:
                break
            candidate_count += 1
            periodic_checkpoint(checkpoint, candidate_count)
            if bbox_gap(left.bbox, right.bbox) > reporting_limit:
                continue
            gap, left_item, right_item = mask_component_gap(
                left.items,
                right.items,
                left.index,
                right.index,
                reporting_limit,
            )
            if gap <= 1e-9 or gap > reporting_limit:
                continue
            left_scan, left_primitive = left_item
            right_scan, right_primitive = right_item
            left_source = nearest_mask_pad_anchor(left, left_primitive) or left_item
            right_source = nearest_mask_pad_anchor(right, right_primitive) or right_item
            left_source_scan, left_source_primitive = left_source
            right_source_scan, right_source_primitive = right_source
            yield ScanFinding(
                "Solder Mask Bridge",
                "Solder-mask bridge width is {0:.3f}mm.".format(gap),
                category="Solder Mask Analysis",
                value=gap,
                layer=[mask_layer],
                raw={
                    "file": left_source_scan.path,
                    "segment": spacing_location(left_primitive, right_primitive),
                    "width": gap,
                    "bbox": union_bbox(left_primitive.bbox, right_primitive.bbox),
                    "primary": primitive_mapping_raw(
                        left_source_primitive,
                        left_source_scan.path,
                        left_source_scan.layer,
                        "gerber",
                    ),
                    "related": primitive_mapping_raw(
                        right_source_primitive,
                        right_source_scan.path,
                        right_source_scan.layer,
                        "gerber",
                    ),
                    "mask_primary": primitive_mapping_raw(
                        left_primitive, left_scan.path, [mask_layer], "gerber"
                    ),
                    "mask_related": primitive_mapping_raw(
                        right_primitive, right_scan.path, [mask_layer], "gerber"
                    ),
                },
            )


def solder_mask_copper_findings(
    components,
    copper,
    mask_layer,
    reporting_limit,
    checkpoint=None,
):
    copper_index = BboxGridIndex(copper)
    candidate_count = 0
    for component in components:
        geometry = (
            component
            if isinstance(component, _MaskComponentGeometry)
            else _MaskComponentGeometry(component)
        )
        component = geometry.items
        component_bbox = geometry.bbox
        exposed = []
        for item in copper_index.candidates(component_bbox, 0.0):
            candidate_count += 1
            periodic_checkpoint(checkpoint, candidate_count)
            if any(
                primitive_gap_within(mask, item[1], 1e-9) <= 1e-9
                for _scan, mask in geometry.index.candidates(item[1].bbox, 0.0)
            ):
                exposed.append(item)
        exposed_by_net = {}
        for item in exposed:
            exposed_by_net.setdefault(item[1].net, item)
        if len(exposed_by_net) > 1:
            first, second = list(exposed_by_net.values())[:2]
            yield solder_mask_multiple_nets_finding(
                component, first, second, mask_layer, tuple(sorted(exposed_by_net))
            )

        intended_nets = {
            primitive.net for _scan, primitive in geometry.pad_anchors if primitive.net
        }
        # Once one connected opening is anchored to several nets there is no
        # single "intended" pad net.  That condition is already reported by
        # Covers Multiple Nets; treating every remaining trace as another-net
        # produces redundant (and often EP/via-chain) Covers Trace false hits.
        if len(intended_nets) != 1 or reporting_limit is None:
            continue
        for copper_scan, primitive in copper_index.candidates(
            component_bbox, reporting_limit
        ):
            candidate_count += 1
            periodic_checkpoint(checkpoint, candidate_count)
            if primitive.net in intended_nets or not is_trace_primitive(primitive):
                continue
            gap, mask_item = primitive_to_mask_component_gap(
                primitive,
                component,
                geometry.index,
                reporting_limit,
            )
            if gap > reporting_limit:
                continue
            mask_scan, mask_primitive = mask_item
            related_source = (
                nearest_mask_pad_anchor(geometry, mask_primitive) or mask_item
            )
            related_scan, related_primitive = related_source
            yield ScanFinding(
                "Solder Mask Covers Trace",
                "Solder-mask opening clearance to another-net trace is {0:.3f}mm.".format(gap),
                category="Solder Mask Analysis",
                value=gap,
                layer=[mask_layer],
                raw={
                    "file": copper_scan.path,
                    "segment": spacing_location(primitive, mask_primitive),
                    "width": primitive.width,
                    "bbox": union_bbox(primitive.bbox, mask_primitive.bbox),
                    "net": primitive.net,
                    "opening_nets": tuple(sorted(intended_nets)),
                    "primary": primitive_mapping_raw(
                        primitive, copper_scan.path, copper_scan.layer, "gerber"
                    ),
                    "related": primitive_mapping_raw(
                        related_primitive,
                        related_scan.path,
                        related_scan.layer,
                        "gerber",
                    ),
                    "mask_related": primitive_mapping_raw(
                        mask_primitive, mask_scan.path, [mask_layer], "gerber"
                    ),
                },
            )


class BboxGridIndex:
    """Small uniform-grid index for repeated local Gerber geometry queries."""

    def __init__(self, items, cell_size=2.0, max_cells_per_item=256):
        self.items = tuple(items)
        self.cell_size = float(cell_size)
        self.max_cells_per_item = int(max_cells_per_item)
        self.buckets = {}
        self.oversized = []
        for item in self.items:
            keys = self._keys(item[1].bbox)
            if keys is None:
                self.oversized.append(item)
                continue
            for key in keys:
                self.buckets.setdefault(key, []).append(item)

    def _keys(self, bbox, margin=0.0):
        x1, y1, x2, y2 = (
            bbox[0] - margin,
            bbox[1] - margin,
            bbox[2] + margin,
            bbox[3] + margin,
        )
        first_x = math.floor(x1 / self.cell_size)
        last_x = math.floor(x2 / self.cell_size)
        first_y = math.floor(y1 / self.cell_size)
        last_y = math.floor(y2 / self.cell_size)
        cell_count = (last_x - first_x + 1) * (last_y - first_y + 1)
        if cell_count > self.max_cells_per_item:
            return None
        return tuple(
            (x, y)
            for x in range(first_x, last_x + 1)
            for y in range(first_y, last_y + 1)
        )

    def candidates(self, bbox, margin=0.0):
        keys = self._keys(bbox, margin)
        source_groups = (
            (self.items,)
            if keys is None
            else (self.oversized,) + tuple(self.buckets.get(key, ()) for key in keys)
        )
        seen = set()
        for group in source_groups:
            for item in group:
                identity = id(item[1])
                if identity in seen:
                    continue
                seen.add(identity)
                if bbox_gap(bbox, item[1].bbox) <= margin:
                    yield item


class _MaskComponentGeometry:
    """Cached bounds and primitive index for one connected mask opening."""

    __slots__ = ("items", "bbox", "index", "pad_anchors")

    def __init__(self, items, pad_anchors=()):
        self.items = items
        self.bbox = mask_component_bbox(items)
        self.index = BboxGridIndex(items)
        self.pad_anchors = tuple(pad_anchors)


def mask_component_pad_anchors(component, pad_index):
    """Return copper pad flashes physically exposed by one mask component."""
    if not component or pad_index is None:
        return ()
    geometry = _MaskComponentGeometry(component)
    anchors = []
    seen = set()
    for item in pad_index.candidates(geometry.bbox, 0.0):
        if any(
            primitive_gap_within(mask, item[1], 1e-9) <= 1e-9
            for _scan, mask in geometry.index.candidates(item[1].bbox, 0.0)
        ):
            identity = id(item[1])
            if identity not in seen:
                seen.add(identity)
                anchors.append(item)
    return tuple(anchors)


def nearest_mask_pad_anchor(geometry, mask_primitive):
    """Choose the native-mappable copper pad nearest a mask primitive."""
    if not geometry.pad_anchors:
        return None
    return min(
        geometry.pad_anchors,
        key=lambda item: primitive_gap(mask_primitive, item[1]),
    )


def solder_mask_multiple_nets_finding(component, first, second, mask_layer, nets):
    first_scan, first_primitive = first
    second_scan, second_primitive = second
    return ScanFinding(
        "Solder Mask Covers Multiple Nets",
        "One solder-mask opening exposes multiple copper nets.",
        category="Solder Mask Analysis",
        value=1.0,
        layer=[mask_layer],
        color="red",
        raw={
            "file": first_scan.path,
            "point": primitive_center(first_primitive),
            "bbox": mask_component_bbox(component),
            "nets": nets,
            "primary": primitive_mapping_raw(
                first_primitive, first_scan.path, first_scan.layer, "gerber"
            ),
            "related": primitive_mapping_raw(
                second_primitive, second_scan.path, second_scan.layer, "gerber"
            ),
        },
    )


def is_trace_primitive(primitive):
    return (
        not primitive.is_flash
        and primitive.kind in ("segment", "obround")
        and normalized_aperture_function(primitive) in ("conductor", "nonconductor", "")
    )


def mask_component_gap(
    left,
    right,
    left_index=None,
    right_index=None,
    reporting_limit=None,
):
    if reporting_limit is not None and left_index is not None and right_index is not None:
        if len(left) <= len(right):
            source = left
            target_index = right_index
            reverse = False
        else:
            source = right
            target_index = left_index
            reverse = True
        best = None
        for source_item in source:
            for target_item in target_index.candidates(
                source_item[1].bbox, reporting_limit
            ):
                left_item, right_item = (
                    (target_item, source_item) if reverse else (source_item, target_item)
                )
                gap = primitive_gap_within(
                    left_item[1], right_item[1], reporting_limit
                )
                if best is None or gap < best[0]:
                    best = (gap, left_item, right_item)
                    if gap <= 1e-9:
                        return best
        if best is None:
            return math.inf, left[0], right[0]
        return best

    best = None
    for left_item in left:
        for right_item in right:
            gap = primitive_gap(left_item[1], right_item[1])
            if best is None or gap < best[0]:
                best = (gap, left_item, right_item)
    return best


def primitive_to_mask_component_gap(
    primitive,
    component,
    component_index=None,
    reporting_limit=None,
):
    candidates = (
        component_index.candidates(primitive.bbox, reporting_limit)
        if component_index is not None and reporting_limit is not None
        else component
    )
    gap_function = (
        (lambda mask: primitive_gap_within(primitive, mask, reporting_limit))
        if reporting_limit is not None
        else (lambda mask: primitive_gap(primitive, mask))
    )
    return min(
        (
            (gap_function(mask), item)
            for item in candidates
            for mask in (item[1],)
        ),
        key=lambda result: result[0],
        default=(math.inf, component[0]),
    )


def mask_component_bbox(component):
    boxes = [primitive.bbox for _scan, primitive in component]
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def union_bbox(left, right):
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def merged_x2_pad_objects(pads, include_composite=True):
    """Merge connected primitives carrying one X2 object id.

    X2 ``TO.P`` identifies a component pad, but the identifier is not always
    unique: unnumbered/mechanical pads (and pad number 0) can occur more than
    once in a footprint.  Only spatially connected primitives are parts of one
    custom pad; merging every repeated identifier creates a fictitious pad
    spanning the whole footprint.
    """
    flash_groups = {}
    object_groups = {}
    ungrouped = []
    for pad in pads:
        if pad.flash_id:
            flash_groups.setdefault(pad.flash_id, []).append(pad)
        elif pad.object_id:
            object_groups.setdefault(pad.object_id, []).append(pad)
        else:
            ungrouped.append(pad)
    for pad in ungrouped:
        yield pad
    for members in flash_groups.values():
        yield from merged_pad_component(members, include_composite)
    for same_id_members in object_groups.values():
        for members in connected_pad_components(same_id_members):
            yield from merged_pad_component(members, include_composite)


def connected_pad_components(members):
    remaining = list(members)
    while remaining:
        component = [remaining.pop()]
        index = 0
        while index < len(component):
            current = component[index]
            connected = [
                candidate
                for candidate in remaining
                if primitive_gap(current, candidate) <= 1e-9
            ]
            for candidate in connected:
                remaining.remove(candidate)
                component.append(candidate)
            index += 1
        yield component


def merged_pad_component(members, include_composite):
    """Yield a singleton pad or an exact-union logical custom pad."""
    if len(members) == 1:
        if members[0].kind == "region" and not include_composite:
            return
        yield members[0]
        return
    logical_size = logical_macro_pad_size(members)
    if not include_composite and logical_size is None:
        return
    left = min(member.bbox[0] for member in members)
    top = min(member.bbox[1] for member in members)
    right = max(member.bbox[2] for member in members)
    bottom = max(member.bbox[3] for member in members)
    first = members[0]
    merged = GerberPrimitive(
        "composite",
        center=((left + right) / 2.0, (top + bottom) / 2.0),
        width=right - left,
        height=bottom - top,
        is_flash=True,
        net=first.net,
        function=first.function,
        component=first.component,
        object_id=first.object_id,
        flash_id=first.flash_id,
        members=tuple(members),
        coordinate_resolution_mm=max(
            (
                member.coordinate_resolution_mm
                for member in members
                if member.coordinate_resolution_mm is not None
            ),
            default=None,
        ),
    )
    if logical_size is not None:
        merged.shape_width, merged.shape_height = logical_size
    yield merged


def logical_macro_pad_size(members):
    flash_ids = {member.flash_id for member in members if member.flash_id}
    if len(flash_ids) != 1 or any(not member.flash_id for member in members):
        return None
    sizes = {
        (round(member.shape_width, 9), round(member.shape_height, 9))
        for member in members
    }
    if len(sizes) != 1:
        return None
    width, height = next(iter(sizes))
    return (width, height) if width > 0 and height > 0 else None


def scan_pad_drill_features(
    drill_scans,
    gerber_scans,
    include_holes_on_smd=True,
    include_drilled_pad_size=True,
    holes_overlap_ratio=False,
):
    drills = [
        (scan, drill)
        for scan in drill_scans
        for drill in scan.primitives
        if drill.diameter > 0
        and valid_bbox_item(drill)
    ]
    if not drills:
        return
    pads = []
    for scan in gerber_scans:
        if not scan.is_copper:
            continue
        primitives = [
            primitive
            for primitive in valid_visible_primitives(scan)
            if primitive.is_flash
        ]
        for pad in merged_x2_pad_objects(primitives):
            pads.append(
                (scan, pad, nearby_clear_masks(pad, *clear_mask_index(scan)))
            )
    if not pads:
        return
    pads.sort(key=lambda item: item[1].bbox[0])
    pad_starts = [pad.bbox[0] for _, pad, _ in pads]
    max_pad_width = max_bbox_width(pad for _, pad, _ in pads)
    pad_candidates = []
    ring_candidates = []
    hole_candidates = []
    for drill_scan, drill in drills:
        drill_hole_candidates = []
        coincident_drilled_pad_functions = set()
        for scan, pad, masks in x_window_candidates(drill, pads, pad_starts, max_pad_width):
            if pad.bbox[0] > drill.bbox[2]:
                break
            if drill.bbox[0] > pad.bbox[2]:
                continue
            if bbox_gap(drill.bbox, pad.bbox) > 0:
                continue
            if drill_to_primitive_gap(drill, pad) > 1e-9:
                continue
            cleared_hole = cleared_flash_hole_size(drill, pad, masks)
            aperture_function = normalized_aperture_function(pad)
            if (
                aperture_function in ("viapad", "componentpad")
                and drill_pad_centers_match(drill, pad)
            ):
                coincident_drilled_pad_functions.add(aperture_function)
            confirmed_drilled_pad = (
                cleared_hole is not None
                or not pad.function
                or (
                    is_drilled_pad_function(pad)
                    and drill_pad_centers_match(drill, pad)
                )
            )
            if drill.kind in ("circle", "slot") and confirmed_drilled_pad:
                drill_width, drill_height = effective_pad_drill_size_from_hole(pad, drill, cleared_hole)
                if (
                    pad.function
                    and (
                        drill_width > pad.shape_width + 1e-9
                        or drill_height > pad.shape_height + 1e-9
                    )
                ):
                    continue
                value = round(
                    pad_shorter_side_mm(pad.shape_width, pad.shape_height), 6
                )
                item = pad_size_item(pad.shape_width, pad.shape_height)
                if include_drilled_pad_size:
                    pad_candidates.append((value, scan, pad, drill_scan, drill, item))
                if drill.kind == "circle" and pad.kind == "circle":
                    ring = round(max(0.0, (pad.width - drill_width) / 2.0), 6)
                    ring_candidates.append((ring, scan, pad, drill_scan, drill))
            if (
                include_holes_on_smd
                and cleared_hole is None
                and is_x2_smd_pad(pad)
            ):
                overlap = drill_pad_overlap(drill, pad)
                if overlap > 1e-9:
                    drill_hole_candidates.append(
                        (overlap, scan, pad, drill_scan, drill)
                    )
        hole_item = hole_on_smd_item(
            drill_scan,
            coincident_drilled_pad_functions,
        )
        if hole_item:
            best_by_pad = {}
            for candidate in drill_hole_candidates:
                overlap, scan, pad, _drill_scan, _drill = candidate
                key = logical_smd_pad_key(scan, pad)
                previous = best_by_pad.get(key)
                if previous is None or overlap > previous[0]:
                    best_by_pad[key] = candidate
            hole_candidates.extend(
                candidate + (hole_item,)
                for candidate in best_by_pad.values()
                if not hole_item.startswith("Via on ")
                or drill_axis_on_pad(candidate[4], candidate[2])
            )
    if holes_overlap_ratio:
        hole_candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    yield from pad_drill_findings(
        pad_candidates,
        ring_candidates,
        hole_candidates,
        holes_overlap_ratio=holes_overlap_ratio,
    )


def clear_mask_index(scan):
    masks = getattr(scan, "sorted_clear_masks", None)
    starts = getattr(scan, "clear_mask_starts", None)
    max_width = getattr(scan, "clear_mask_max_width", None)
    if masks is not None and starts is not None and max_width is not None:
        return masks, starts, max_width
    masks = tuple(sorted(valid_bbox_items(getattr(scan, "clear_masks", ())), key=lambda mask: mask.bbox[0]))
    starts = tuple(mask.bbox[0] for mask in masks)
    max_width = max_bbox_width(masks)
    scan.sorted_clear_masks = masks
    scan.clear_mask_starts = starts
    scan.clear_mask_max_width = max_width
    return masks, starts, max_width


def nearby_clear_masks(primitive, masks, starts=None, max_width=None):
    if not masks:
        return ()
    if starts is None:
        starts = tuple(mask.bbox[0] for mask in masks)
    if max_width is None:
        max_width = max_bbox_width(masks)
    return tuple(
        mask
        for mask in x_window_candidates(primitive, masks, starts, max_width)
        if mask.bbox[0] <= primitive.bbox[2] and bbox_gap(primitive.bbox, mask.bbox) <= 0
    )


def nearby_drill_copper_masks(drill, copper, masks, starts=None, max_width=None):
    if not masks:
        return ()
    nearby = list(nearby_clear_masks(copper, masks, starts, max_width))
    seen = {id(mask) for mask in nearby}
    for mask in nearby_clear_masks(drill, masks, starts, max_width):
        if id(mask) not in seen:
            nearby.append(mask)
            seen.add(id(mask))
    return tuple(nearby)


def pad_drill_findings(
    pad_candidates,
    ring_candidates,
    hole_candidates=None,
    holes_overlap_ratio=False,
):
    for candidate in pad_candidates or ():
        yield pad_size_finding(*candidate)
    for candidate in ring_candidates or ():
        yield ring_hole_finding(*candidate)
    for candidate in hole_candidates or ():
        yield holes_on_smd_finding(*candidate, as_ratio=holes_overlap_ratio)


def pad_size_finding(value, scan, pad, drill_scan, drill, item):
    return ScanFinding(
        item,
        "Gerber pad shorter-side length is {0:.3f}mm.".format(value),
        category="Pad size",
        value=value,
        layer=scan.layer,
        raw={
            "file": scan.path,
            "segment": pad.location_segment(),
            "diameter": drill.diameter,
            "width": min(pad.shape_width, pad.shape_height),
            "pad_size": (pad.shape_width, pad.shape_height),
            "bbox": pad.bbox,
            "primary": primitive_mapping_raw(pad, scan.path, scan.layer, "gerber"),
            "related": primitive_mapping_raw(drill, drill_scan.path, drill_scan.layer, "drill"),
        },
    )


def smd_pad_size_finding(value, scan, pad, item):
    return ScanFinding(
        item,
        "Gerber SMD pad width is {0:.3f}mm.".format(value),
        category="Pad size",
        value=round(value, 6),
        layer=scan.layer,
        raw={
            "file": scan.path,
            "segment": pad.location_segment(),
            "width": min(pad.shape_width, pad.shape_height),
            "pad_size": (pad.shape_width, pad.shape_height),
            "bbox": pad.bbox,
            "primary": primitive_mapping_raw(pad, scan.path, scan.layer, "gerber"),
        },
    )


def ring_hole_finding(value, scan, pad, drill_scan, drill):
    return ScanFinding(
        "Via Annular Ring" if normalized_aperture_function(pad) == "viapad" else "PTH Annular Ring",
        "Gerber PTH annular ring is {0:.3f}mm.".format(value),
        category="RingHole",
        value=value,
        layer=scan.layer,
        raw={
            "file": scan.path,
            "segment": pad.location_segment(),
            "diameter": drill.diameter,
            "width": min(pad.shape_width, pad.shape_height),
            "pad_size": (pad.shape_width, pad.shape_height),
            "bbox": pad.bbox,
            "primary": primitive_mapping_raw(pad, scan.path, scan.layer, "gerber"),
            "related": primitive_mapping_raw(drill, drill_scan.path, drill_scan.layer, "drill"),
        },
    )


def pad_remaining_copper(pad, drill, drill_height=None):
    if drill_height is None:
        drill_width, drill_height = drill_footprint_size(drill)
    else:
        drill_width = drill
    return round(max(0.0, min(pad.shape_width - drill_width, pad.shape_height - drill_height)), 6)


def effective_pad_drill_size(pad, drill, masks):
    return effective_pad_drill_size_from_hole(pad, drill, cleared_flash_hole_size(drill, pad, masks))


def effective_pad_drill_size_from_hole(pad, drill, hole):
    drill_width, drill_height = drill_footprint_size(drill)
    if hole is None:
        return drill_width, drill_height
    return max(drill_width, hole[0]), max(drill_height, hole[1])


def cleared_flash_hole_size(drill, pad, masks):
    if not pad.is_flash:
        return None
    drill_primitive = drill_mask_primitive(drill)
    if drill_primitive is None:
        return None
    best = None
    for mask in masks:
        if bbox_gap(drill.bbox, mask.bbox) > 0:
            continue
        if primitive_gap(drill_primitive, mask) > 1e-9:
            continue
        if not primitive_fully_covered_by_mask(drill_primitive, mask):
            continue
        if mask.kind in ("circle", "rect", "segment", "obround"):
            hole = (mask.width, mask.height)
            if better_cleared_hole(pad, drill, hole, best):
                best = hole
    return best


def better_cleared_hole(pad, drill, candidate, current):
    if current is None:
        return True
    candidate_width, candidate_height = effective_pad_drill_size_from_hole(pad, drill, candidate)
    current_width, current_height = effective_pad_drill_size_from_hole(pad, drill, current)
    candidate_remaining = pad_remaining_copper(pad, candidate_width, candidate_height)
    current_remaining = pad_remaining_copper(pad, current_width, current_height)
    if candidate_remaining != current_remaining:
        return candidate_remaining < current_remaining
    return min(candidate) > min(current)


def drill_footprint_size(drill):
    if drill.kind == "slot":
        return drill.bbox[2] - drill.bbox[0], drill.bbox[3] - drill.bbox[1]
    return drill.diameter, drill.diameter


def primitive_fully_covered_by_mask(primitive, mask):
    if primitive.kind == "composite":
        return bool(primitive.members) and all(
            primitive_fully_covered_by_mask(member, mask)
            for member in primitive.members
        )
    if primitive.kind == "circle" and mask.kind == "circle":
        return primitive_center_distance(primitive, mask) + primitive.width / 2.0 <= mask.width / 2.0 + 1e-9
    if primitive.kind == "circle" and mask.kind == "rect":
        return bbox_inner_margin(primitive.bbox, mask.bbox) >= -1e-9
    if primitive.kind == "circle" and mask.kind in ("segment", "obround"):
        return point_to_segment_distance(primitive.center, mask.start, mask.end) + primitive.width / 2.0 <= mask.width / 2.0 + 1e-9
    if primitive.kind in ("segment", "obround") and mask.kind == "rect":
        return bbox_inner_margin(primitive.bbox, mask.bbox) >= -1e-9
    if primitive.kind in ("segment", "obround") and mask.kind == "circle":
        return segment_fully_covered_by_circle(primitive, mask)
    return all(point_in_primitive(point, mask) for point in primitive_sample_points(primitive))


def segment_fully_covered_by_circle(primitive, mask):
    farthest_axis_distance = max(distance(mask.center, primitive.start), distance(mask.center, primitive.end))
    return farthest_axis_distance + primitive.width / 2.0 <= mask.width / 2.0 + 1e-9


def drill_pad_overlap(drill, pad):
    """Return radial drill penetration into the real Gerber pad geometry."""
    if drill.kind == "slot":
        drill_axis = GerberPrimitive(
            "segment",
            start=drill.start,
            end=drill.end,
            width=0.0,
        )
    else:
        drill_axis = GerberPrimitive(
            "circle",
            center=drill.center,
            width=0.0,
        )
    overlap = drill.diameter / 2.0 - primitive_gap(drill_axis, pad)
    return round(max(0.0, overlap), 6)


def drill_axis_on_pad(drill, pad):
    """Test the via centre or routed-slot centreline against exact pad copper."""
    if drill.kind == "slot":
        drill_axis = GerberPrimitive(
            "segment",
            start=drill.start,
            end=drill.end,
            width=0.0,
        )
    else:
        drill_axis = GerberPrimitive(
            "circle",
            center=drill.center,
            width=0.0,
        )
    return primitive_gap(drill_axis, pad) <= 1e-9


def primitive_center_distance(left, right):
    left_center = left.center if left.center is not None else primitive_center(left)
    right_center = right.center if right.center is not None else primitive_center(right)
    return ((left_center[0] - right_center[0]) ** 2 + (left_center[1] - right_center[1]) ** 2) ** 0.5


def point_bbox_gap(point, bbox):
    if point is None or bbox is None:
        return 0.0
    dx = max(0.0, bbox[0] - point[0], point[0] - bbox[2])
    dy = max(0.0, bbox[1] - point[1], point[1] - bbox[3])
    return (dx * dx + dy * dy) ** 0.5


def bbox_overlap_depth(left, right):
    if left is None or right is None:
        return 0.0
    overlap_x = min(left[2], right[2]) - max(left[0], right[0])
    overlap_y = min(left[3], right[3]) - max(left[1], right[1])
    if overlap_x <= 0 or overlap_y <= 0:
        return 0.0
    return min(overlap_x, overlap_y)


def scan_holes_on_smd_pads(drill_scans, gerber_scans):
    for finding in scan_pad_drill_features(drill_scans, gerber_scans, include_holes_on_smd=True):
        if finding.category == "Holes on SMD Pads":
            yield finding


def holes_on_smd_finding(
    overlap,
    scan,
    pad,
    drill_scan,
    drill,
    item,
    as_ratio=False,
):
    ratio_overlap = overlap
    if (
        as_ratio
        and drill.kind == "circle"
        and pad.kind == "rect"
        and drill.center is not None
        and point_in_primitive(drill.center, pad)
    ):
        left, top, right, bottom = pad.bbox
        interior_depth = min(
            drill.center[0] - left,
            right - drill.center[0],
            drill.center[1] - top,
            bottom - drill.center[1],
        )
        ratio_overlap = drill.diameter / 2.0 + max(0.0, interior_depth)
    ratio = min(1.0, max(0.0, ratio_overlap / drill.diameter)) if drill.diameter > 0 else 0.0
    value = round(ratio, 6) if as_ratio else overlap
    message = (
        "Gerber drill overlaps SMD pad by {0:.2f}%.".format(ratio * 100.0)
        if as_ratio
        else "Gerber drill overlaps SMD pad by {0:.3f}mm.".format(overlap)
    )
    return ScanFinding(
        item,
        message,
        category="Holes on SMD Pads",
        value=value,
        layer=scan.layer,
        raw={
            "file": scan.path,
            "point": drill.center if drill.center is not None else primitive_center(drill),
            "diameter": drill.diameter,
            "width": min(pad.shape_width, pad.shape_height),
            "overlap_mm": overlap,
            "overlap_ratio": ratio,
            "pad_size": (pad.shape_width, pad.shape_height),
            "bbox": pad.bbox,
            "primary": primitive_mapping_raw(drill, drill_scan.path, drill_scan.layer, "drill"),
            "related": primitive_mapping_raw(pad, scan.path, scan.layer, "gerber"),
        },
    )


def scan_drill_to_copper(
    drill_scans,
    gerber_scans,
    reporting_limits=None,
    checkpoint=None,
):
    reporting_limits = reporting_limits or {}
    drill_items = [
        (scan, primitive)
        for scan in drill_scans
        for primitive in scan.primitives
        if valid_bbox_item(primitive)
    ]
    if not drill_items:
        return
    copper_items = sorted(
        [
            (scan, primitive)
            for scan in gerber_scans
            if scan.is_copper
            for primitive in valid_visible_primitives(scan)
        ],
        key=lambda item: item[1].bbox[0],
    )
    if not copper_items:
        return
    copper_starts = [primitive.bbox[0] for _, primitive in copper_items]
    max_copper_width = max_bbox_width(primitive for _, primitive in copper_items)
    copper_index = BboxGridIndex(copper_items)
    candidate_count = 0
    for drill_scan, drill in drill_items:
        is_npth = drill_scan.plated is False
        drill_kind = (
            "npth"
            if is_npth
            else inferred_drill_pad_kind(
                drill,
                copper_items,
                copper_starts,
                max_copper_width,
                copper_index=copper_index,
            )
        )
        drill_nets = set() if is_npth else inferred_drill_nets(
            drill,
            copper_items,
            copper_starts,
            max_copper_width,
            copper_index=copper_index,
        )
        search_limit = max(reporting_limits.values()) if reporting_limits else None
        candidates = (
            copper_index.candidates(drill.bbox, search_limit)
            if search_limit is not None
            else copper_items
        )
        best_by_item = {}
        reportable_by_item = {}
        for copper_scan, copper in candidates:
            candidate_count += 1
            periodic_checkpoint(checkpoint, candidate_count)
            lower_bound = bbox_gap(drill.bbox, copper.bbox)
            if search_limit is not None and lower_bound > search_limit:
                continue
            if not is_npth and not is_trace_primitive(copper):
                continue
            item = drill_to_copper_item(drill_kind, copper_scan)
            existing = best_by_item.get(item)
            if (
                not reporting_limits
                and existing is not None
                and lower_bound >= existing[0]
            ):
                continue
            masks = nearby_drill_copper_masks(
                drill, copper, *clear_mask_index(copper_scan)
            )
            if not is_npth and legal_drill_pad_contact(drill, copper, masks):
                continue
            if copper.net and copper.net in drill_nets:
                continue
            gap = drill_to_visible_copper_gap(drill, copper, masks)
            if (
                gap <= 1e-9
                and copper.kind == "region"
                and "pad" in normalized_aperture_function(copper)
            ):
                continue
            if existing is None or gap < existing[0]:
                best_by_item[item] = (gap, copper_scan, copper)
            limit = reporting_limits.get(item)
            if limit is not None and gap <= limit:
                reportable_by_item.setdefault(item, []).append(
                    (gap, copper_scan, copper)
                )
        for item, best in sorted(best_by_item.items()):
            limit = reporting_limits.get(item)
            findings = reportable_by_item.get(item)
            if not findings:
                if limit is not None and best[0] > limit:
                    continue
                findings = [best]
            elif item == "NPTH-to-Copper":
                # An NPTH is one physical through-hole, not one object per
                # copper layer.  All copper layers participate in the search,
                # but the report keeps only the globally nearest clearance.
                findings = [min(findings, key=lambda row: row[0])]
            for gap, copper_scan, copper in sorted(findings, key=lambda row: row[0]):
                yield ScanFinding(
                    item,
                    "Excellon {0} clearance is {1:.3f}mm.".format(item, gap),
                    category="Drill to Copper",
                    value=gap,
                    layer=(
                        drill_scan.layer
                        if item == "NPTH-to-Copper"
                        else copper_scan.layer
                    ),
                    raw={
                        "file": drill_scan.path,
                        "segment": spacing_location(drill, copper),
                        "diameter": drill.diameter,
                        "width": drill_copper_highlight_width(drill, copper),
                        "bbox": primitive_pair_bbox(drill, copper),
                        "copper_file": copper_scan.path,
                        "plated": drill_scan.plated,
                        "primary": primitive_mapping_raw(
                            drill, drill_scan.path, drill_scan.layer, "drill"
                        ),
                        "related": primitive_mapping_raw(
                            copper, copper_scan.path, copper_scan.layer, "gerber"
                        ),
                    },
                )


def drill_to_copper_item(drill_kind, copper_scan):
    if drill_kind == "npth":
        return "NPTH-to-Copper"
    prefix = "Via" if drill_kind == "via" else "PTH"
    suffix = "Outer" if is_outer_copper_scan(copper_scan) else "Inner"
    return "{0}-to-Trace [{1}]".format(prefix, suffix)


def same_nonempty_net(left, right):
    left_net = str(getattr(left, "net", "") or "")
    right_net = str(getattr(right, "net", "") or "")
    return bool(left_net and right_net and left_net == right_net)


def same_logical_copper_object(left, right, logical_object_keys=None):
    """Return true when two Gerber primitives are pieces of one copper pad.

    Aperture macros can expand one D03 flash into several dark primitives, and
    some producers emit several flashes for one X2 ``TO.P`` object.  Those
    pieces intentionally overlap/touch and must never be measured against each
    other as a zero-clearance pad pair.  When the scan-level identity map is
    supplied, repeated object ids are merged only through touching components;
    disconnected unnumbered pads remain distinct.  The identity test is
    deliberately limited to pad primitives so reused object metadata on
    conductor draws does not hide a real trace clearance.
    """
    if not (is_pad_copper_primitive(left) and is_pad_copper_primitive(right)):
        return False
    if logical_object_keys is not None:
        left_key = logical_object_keys.get(id(left))
        right_key = logical_object_keys.get(id(right))
        return bool(left_key is not None and left_key == right_key)
    left_flash = str(getattr(left, "flash_id", "") or "")
    right_flash = str(getattr(right, "flash_id", "") or "")
    if left_flash and left_flash == right_flash:
        return True
    left_object = str(getattr(left, "object_id", "") or "")
    right_object = str(getattr(right, "object_id", "") or "")
    return bool(left_object and left_object == right_object)


def normalized_aperture_function(primitive):
    return str(getattr(primitive, "function", "") or "").lower()


def is_smd_pad_or_legacy(primitive):
    function = normalized_aperture_function(primitive)
    return not function or function.startswith("smdpad")


def is_x2_smd_pad(primitive):
    """Return true only when X2 explicitly identifies an SMD copper pad."""
    return normalized_aperture_function(primitive).startswith("smdpad")


def hole_on_smd_item(drill_scan, coincident_pad_functions):
    """Classify a drill that intersects an explicitly identified SMD pad."""
    if drill_scan.plated is False:
        return "NPTH on SMD Pad"
    if "viapad" in coincident_pad_functions:
        return "Via on SMD Pad"
    if "componentpad" in coincident_pad_functions:
        return "PTH on SMD Pad"
    # A plated or plating-unspecified Excellon hit without a component-pad
    # annulus is the Gerber-only supplement for a via-on-SMD result.
    return "Via on SMD Pad"


def logical_smd_pad_key(scan, pad):
    if pad.flash_id:
        return scan.path, "flash", pad.flash_id
    if pad.object_id:
        return scan.path, "object", pad.object_id
    return scan.path, "primitive", id(pad)


def is_drilled_pad_function(primitive):
    function = normalized_aperture_function(primitive)
    return bool(
        function
        and (
            "viapad" in function
            or "componentpad" in function
        )
    )


def legal_drill_pad_contact(drill, copper, masks):
    return bool(
        copper.is_flash
        and is_drilled_pad_function(copper)
        and (
            cleared_flash_hole_size(drill, copper, masks) is not None
            or drill_pad_centers_match(drill, copper)
        )
    )


def drill_pad_centers_match(drill, pad, tolerance=0.025):
    if not pad.is_flash:
        return False
    return primitive_center_distance(drill, pad) <= tolerance


def inferred_drill_nets(
    drill,
    copper_items,
    copper_starts=None,
    max_copper_width=None,
    copper_index=None,
):
    nets = set()
    if copper_starts is None:
        copper_starts = [copper.bbox[0] for _, copper in copper_items]
    if max_copper_width is None:
        max_copper_width = max_bbox_width(copper for _, copper in copper_items)
    candidates = (
        copper_index.candidates(drill.bbox, 0.0)
        if copper_index is not None
        else x_window_candidates(drill, copper_items, copper_starts, max_copper_width)
    )
    for scan, copper in candidates:
        if copper_index is None and copper.bbox[0] > drill.bbox[2]:
            break
        if not copper.net or not is_drilled_pad_function(copper):
            continue
        if bbox_gap(drill.bbox, copper.bbox) > 0:
            continue
        masks = nearby_drill_copper_masks(
            drill, copper, *clear_mask_index(scan)
        )
        if legal_drill_pad_contact(drill, copper, masks):
            nets.add(copper.net)
    return nets


def inferred_drill_pad_kind(
    drill,
    copper_items,
    copper_starts=None,
    max_copper_width=None,
    copper_index=None,
):
    """Classify a plated Excellon hit from its coincident X2 pad flashes."""
    if copper_starts is None:
        copper_starts = [copper.bbox[0] for _, copper in copper_items]
    if max_copper_width is None:
        max_copper_width = max_bbox_width(copper for _, copper in copper_items)
    candidates = (
        copper_index.candidates(drill.bbox, 0.0)
        if copper_index is not None
        else x_window_candidates(drill, copper_items, copper_starts, max_copper_width)
    )
    for scan, copper in candidates:
        if copper_index is None and copper.bbox[0] > drill.bbox[2]:
            break
        function = normalized_aperture_function(copper)
        if function not in ("viapad", "componentpad"):
            continue
        if bbox_gap(drill.bbox, copper.bbox) > 0:
            continue
        masks = nearby_drill_copper_masks(
            drill, copper, *clear_mask_index(scan)
        )
        if not legal_drill_pad_contact(drill, copper, masks):
            continue
        if function == "viapad":
            return "via"
    return "pth"


def drill_copper_highlight_width(drill, copper):
    widths = [
        value
        for value in (
            getattr(drill, "diameter", None),
            getattr(copper, "shape_width", None) or getattr(copper, "width", None),
        )
        if value
    ]
    return min(widths) if widths else None


def max_bbox_width(items):
    return max((item.bbox[2] - item.bbox[0] for item in items if valid_bbox_item(item)), default=0.0)


def x_window_candidates(item, candidates, starts, max_width):
    start_index = bisect_left(starts, item.bbox[0] - max_width)
    return iter_from(candidates, start_index)


def iter_from(items, start_index):
    for index in range(start_index, len(items)):
        yield items[index]


def nearest_primitive_edge_gap(primitive, candidates, stop_at=None):
    best = None
    for candidate in candidates:
        if stop_at is not None and candidate.bbox[0] > primitive.bbox[2]:
            if candidate.bbox[0] - primitive.bbox[2] >= stop_at:
                break
        lower_bound = bbox_gap(primitive.bbox, candidate.bbox)
        if stop_at is not None and lower_bound >= stop_at:
            continue
        if best is not None:
            if candidate.bbox[0] > primitive.bbox[2] and candidate.bbox[0] - primitive.bbox[2] >= best:
                break
            if lower_bound >= best:
                continue
        value = primitive_segment_gap(primitive, candidate)
        if best is None or value < best:
            best = value
    return best


def drill_to_visible_copper_gap(drill, copper, masks):
    gap = drill_to_cleared_flash_gap(drill, copper, masks)
    if gap is not None:
        return gap
    gap = drill_to_primitive_gap(drill, copper)
    mask_gap = drill_to_clear_mask_gap(drill, masks)
    if mask_gap is not None and mask_gap > gap:
        return mask_gap
    return gap


def drill_to_cleared_flash_gap(drill, copper, masks):
    if not copper.is_flash:
        return None
    hole = cleared_flash_hole_size(drill, copper, masks)
    if hole is None or hole[0] > copper.shape_width + 1e-9 or hole[1] > copper.shape_height + 1e-9:
        return None
    return round(max(0.0, (min(hole) - drill.diameter) / 2.0), 6)


def drill_to_clear_mask_gap(drill, masks):
    drill_primitive = drill_mask_primitive(drill)
    if drill_primitive is None:
        return None
    best = None
    for mask in masks:
        if bbox_gap(drill.bbox, mask.bbox) > 0:
            continue
        if drill.center is not None and not point_in_primitive(drill.center, mask):
            continue
        gap = primitive_gap(drill_primitive, mask)
        if gap <= 1e-9:
            if not primitive_fully_covered_by_mask(drill_primitive, mask):
                continue
            value = mask_escape_gap(drill, mask)
            if best is None or value > best:
                best = value
    return round(best, 6) if best is not None else None


def drill_mask_primitive(drill):
    if drill.kind == "circle":
        return GerberPrimitive("circle", center=drill.center, width=drill.diameter)
    if drill.kind == "slot":
        return GerberPrimitive("segment", start=drill.start, end=drill.end, width=drill.diameter)
    return None


def mask_escape_gap(drill, mask):
    if drill.kind == "slot":
        return slot_mask_escape_gap(drill, mask)
    if mask.kind == "circle":
        return max(0.0, mask.width / 2.0 - distance(drill.center, mask.center) - drill.diameter / 2.0)
    if mask.kind in ("segment", "obround"):
        return max(
            0.0,
            mask.width / 2.0 - point_to_segment_distance(drill.center, mask.start, mask.end) - drill.diameter / 2.0,
        )
    if mask.kind == "rect":
        return max(0.0, min(
            drill.center[0] - mask.bbox[0],
            mask.bbox[2] - drill.center[0],
            drill.center[1] - mask.bbox[1],
            mask.bbox[3] - drill.center[1],
        ) - drill.diameter / 2.0)
    if mask.kind == "region":
        return max(
            0.0,
            min(
                point_to_segment_distance(drill.center, start, end)
                for start, end in region_edges(mask)
            )
            - drill.diameter / 2.0,
        )
    return 0.0


def slot_mask_escape_gap(drill, mask):
    if mask.kind in ("segment", "obround"):
        return max(
            0.0,
            mask.width / 2.0
            - segment_distance(drill.start, drill.end, mask.start, mask.end)
            - drill.diameter / 2.0,
        )
    if mask.kind == "rect":
        return max(0.0, bbox_inner_margin(drill.bbox, mask.bbox))
    if mask.kind == "circle":
        return max(0.0, mask.width / 2.0 - farthest_bbox_corner_distance(drill.bbox, mask.center))
    return 0.0


def bbox_inner_margin(inner, outer):
    if inner is None or outer is None:
        return 0.0
    return min(
        inner[0] - outer[0],
        outer[2] - inner[2],
        inner[1] - outer[1],
        outer[3] - inner[3],
    )


def farthest_bbox_corner_distance(bbox, point):
    if bbox is None or point is None:
        return 0.0
    corners = (
        (bbox[0], bbox[1]),
        (bbox[0], bbox[3]),
        (bbox[2], bbox[1]),
        (bbox[2], bbox[3]),
    )
    return max(
        ((corner[0] - point[0]) ** 2 + (corner[1] - point[1]) ** 2) ** 0.5
        for corner in corners
    )


def nearest_segment_distance(segment, candidates, stop_at=None):
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


def visible_primitives(scan):
    cached = getattr(scan, "visible_primitives", None)
    if cached is not None:
        return cached
    masks, starts, max_width = clear_mask_index(scan)
    if not masks:
        scan.visible_primitives = scan.primitives
        return scan.visible_primitives
    scan.visible_primitives = [
        primitive for primitive in scan.primitives if not primitive_covered_by_masks(primitive, masks, starts, max_width)
    ]
    return scan.visible_primitives


def valid_visible_primitives(scan):
    return [
        primitive
        for primitive in visible_primitives(scan)
        if valid_bbox_item(primitive)
        and normalized_aperture_function(primitive) != "nonconductor"
    ]


def valid_bbox_items(items):
    return [item for item in items if valid_bbox_item(item)]


def valid_bbox_item(item):
    bbox = getattr(item, "bbox", None)
    if bbox is None or len(bbox) < 4:
        return False
    return all(value is not None for value in bbox[:4])


def primitive_covered_by_masks(primitive, masks, starts=None, max_width=None):
    if starts is None:
        starts = tuple(mask.bbox[0] for mask in masks)
    if max_width is None:
        max_width = max_bbox_width(masks)
    for mask in x_window_candidates(primitive, masks, starts, max_width):
        if mask.bbox[0] > primitive.bbox[2]:
            break
        if primitive.bbox[0] > mask.bbox[2]:
            continue
        if bbox_gap(primitive.bbox, mask.bbox) > 0:
            continue
        if primitive_fully_covered_by_mask(primitive, mask):
            return True
    return False


def primitive_sample_points(primitive):
    if primitive.kind == "composite":
        return tuple(
            point
            for member in primitive.members
            for point in primitive_sample_points(member)
        )
    if primitive.kind == "region" and primitive.points:
        return primitive.points
    if primitive.kind in ("segment", "obround"):
        return segment_sample_points(primitive)
    if primitive.kind == "circle":
        return circle_sample_points(primitive)
    x1, y1, x2, y2 = primitive.bbox
    return (
        (x1, y1),
        (x2, y1),
        (x2, y2),
        (x1, y2),
        primitive_center(primitive),
    )


def circle_sample_points(primitive):
    center = primitive.center
    radius = primitive.width / 2.0
    diagonal = radius * (0.5 ** 0.5)
    return (
        center,
        (center[0] - radius, center[1]),
        (center[0] + radius, center[1]),
        (center[0], center[1] - radius),
        (center[0], center[1] + radius),
        (center[0] - diagonal, center[1] - diagonal),
        (center[0] + diagonal, center[1] - diagonal),
        (center[0] + diagonal, center[1] + diagonal),
        (center[0] - diagonal, center[1] + diagonal),
    )


def segment_sample_points(primitive):
    center = primitive_center(primitive)
    radius = primitive.width / 2.0
    dx = primitive.end[0] - primitive.start[0]
    dy = primitive.end[1] - primitive.start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return circle_sample_points(GerberPrimitive("circle", center=center, width=primitive.width))
    ux = dx / length
    uy = dy / length
    nx = -uy
    ny = ux
    diagonal = radius * (0.5 ** 0.5)
    return (
        primitive.start,
        center,
        primitive.end,
        (primitive.start[0] - ux * radius, primitive.start[1] - uy * radius),
        (primitive.end[0] + ux * radius, primitive.end[1] + uy * radius),
        (primitive.start[0] - ux * diagonal + nx * diagonal, primitive.start[1] - uy * diagonal + ny * diagonal),
        (primitive.start[0] - ux * diagonal - nx * diagonal, primitive.start[1] - uy * diagonal - ny * diagonal),
        (primitive.end[0] + ux * diagonal + nx * diagonal, primitive.end[1] + uy * diagonal + ny * diagonal),
        (primitive.end[0] + ux * diagonal - nx * diagonal, primitive.end[1] + uy * diagonal - ny * diagonal),
        (primitive.start[0] + nx * radius, primitive.start[1] + ny * radius),
        (primitive.start[0] - nx * radius, primitive.start[1] - ny * radius),
        (center[0] + nx * radius, center[1] + ny * radius),
        (center[0] - nx * radius, center[1] - ny * radius),
        (primitive.end[0] + nx * radius, primitive.end[1] + ny * radius),
        (primitive.end[0] - nx * radius, primitive.end[1] - ny * radius),
    )
