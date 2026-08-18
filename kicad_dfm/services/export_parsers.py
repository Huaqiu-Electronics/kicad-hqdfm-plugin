import os
import re

from kicad_dfm.services.export_gerber_apertures import gerber_flash_kind as gerber_flash_kind
from kicad_dfm.services.export_gerber_apertures import macro_aperture as macro_aperture
from kicad_dfm.services.export_gerber_apertures import macro_primitive_size as macro_primitive_size
from kicad_dfm.services.export_gerber_apertures import parse_gerber_aperture
from kicad_dfm.services.export_gerber_apertures import parse_gerber_macro
from kicad_dfm.services.export_gerber_primitives import add_gerber_draw
from kicad_dfm.services.export_gerber_primitives import add_gerber_flash
from kicad_dfm.services.export_gerber_primitives import add_region_primitives
from kicad_dfm.services.export_geometry_core import point_in_polygon
from kicad_dfm.services.export_gerber_primitives import add_trace_width_finding
from kicad_dfm.services.export_gerber_primitives import gerber_segment_bbox
from kicad_dfm.services.export_gerber_commands import gerber_aperture_select
from kicad_dfm.services.export_gerber_commands import gerber_coordinate_mode_command
from kicad_dfm.services.export_gerber_commands import gerber_ignored_command
from kicad_dfm.services.export_gerber_commands import gerber_interpolation
from kicad_dfm.services.export_gerber_commands import gerber_operation
from kicad_dfm.services.export_gerber_commands import gerber_polarity_command
from kicad_dfm.services.export_gerber_commands import gerber_coord_spec
from kicad_dfm.services.export_gerber_commands import gerber_point_format
from kicad_dfm.services.export_gerber_commands import gerber_quadrant_mode_command
from kicad_dfm.services.export_gerber_commands import gerber_region_end
from kicad_dfm.services.export_gerber_commands import gerber_region_start
from kicad_dfm.services.export_gerber_commands import gerber_unit_command
from kicad_dfm.services.export_gerber_commands import iter_gerber_commands
from kicad_dfm.services.export_gerber_commands import iter_text_lines
from kicad_dfm.services.export_gerber_commands import parse_gerber_arc_offset as parse_gerber_arc_offset
from kicad_dfm.services.export_gerber_commands import parse_gerber_coord as parse_gerber_coord
from kicad_dfm.services.export_gerber_commands import parse_gerber_coord_format
from kicad_dfm.services.export_gerber_commands import parse_gerber_format as parse_gerber_format
from kicad_dfm.services.export_gerber_commands import parse_gerber_point
from kicad_dfm.services.export_gerber_commands import parse_gerber_step_repeat
from kicad_dfm.services.export_gerber_commands import set_gerber_coordinate_mode
from kicad_dfm.services.export_gerber_commands import to_mm
from kicad_dfm.services.export_geometry_core import DrillPrimitive
from kicad_dfm.services.export_geometry_core import distance
from kicad_dfm.services.export_geometry_core import outline_open_gap
from kicad_dfm.services.export_geometry_core import outline_open_gap_endpoints
from kicad_dfm.services.export_result_helpers import is_copper_layer_name
from kicad_dfm.services.export_result_helpers import layer_name_from_file
from kicad_dfm.services.export_result_helpers import layer_name_from_file_function
from kicad_dfm.services.export_scan_models import ExcellonScan
from kicad_dfm.services.export_scan_models import GerberScan
from kicad_dfm.services.export_scan_models import ScanFinding


OUTLINE_OPEN_GAP_MM = 0.05


def gerber_file_function(path):
    """Read the X2 FileFunction without parsing the complete Gerber file."""
    for command in iter_gerber_commands(path):
        attribute = gerber_x2_attribute(command.strip())
        if attribute is not None and attribute[:2] == ("TF", "FILEFUNCTION"):
            return attribute[2]
    return ""


def parse_gerber_scan(path):
    units = "mm"
    apertures = {}
    macros = {}
    active_aperture = None
    have_format = False
    have_draw = False
    layer = [layer_name_from_file(path)]
    is_copper = is_copper_layer_name(layer[0])
    is_edge = "edge" in os.path.basename(path).lower()
    scan = GerberScan(path, layer, is_copper=is_copper, is_edge=is_edge)
    coord_decimals = (4, 4)
    fast_coord_info = fast_region_coord_info(coord_decimals)
    current = None
    current_operation = None
    active_aperture_width = None
    active_aperture_width_key = None
    interpolation = "linear"
    quadrant_mode = "multi"
    polarity = "dark"
    region_points = None
    region_polarity = None
    sr_offsets = ((0.0, 0.0),)
    active_aperture_function = ""
    active_net = ""
    active_component = ""
    active_object_id = ""
    flash_sequence = 0
    for line in iter_gerber_commands(path):
        stripped = line.strip()
        upper = stripped.upper()
        attribute = gerber_x2_attribute(stripped)
        if attribute is not None:
            scope, name, value = attribute
            if scope == "TF" and name == "FILEFUNCTION":
                scan.file_function = value
                attributed_layer = layer_name_from_file_function(value)
                if attributed_layer:
                    layer[:] = [attributed_layer]
                    scan.is_copper = is_copper_layer_name(attributed_layer)
                    scan.is_edge = attributed_layer == "Edge.Cuts"
                    is_edge = scan.is_edge
            elif scope == "TA" and name == "APERFUNCTION":
                active_aperture_function = value.split(",", 1)[0]
            elif scope == "TO" and name == "N":
                active_net = value
            elif scope == "TO" and name == "P":
                parts = value.split(",")
                active_component = parts[0] if parts else ""
                active_object_id = value
            elif scope == "TD":
                if not name:
                    active_aperture_function = ""
                    active_net = ""
                    active_component = ""
                    active_object_id = ""
                elif name == "APERFUNCTION":
                    active_aperture_function = ""
                elif name == "P":
                    active_component = ""
                    active_object_id = ""
            continue
        if region_points is not None and interpolation == "linear":
            parsed = parse_fast_region_coordinate(stripped, upper, fast_coord_info, units, current)
            if parsed is not None:
                point, operation = parsed
                if operation is not None:
                    current_operation = operation
                operation = operation or current_operation
                if operation == 2:
                    current = point
                    if region_points and region_points[-1] is not None:
                        region_points.append(None)
                    region_points.append(point)
                    continue
                if operation == 1 and current is not None:
                    if not region_points:
                        region_points.append(current)
                    region_points.append(point)
                    if (
                        scan.is_copper
                        and polarity == "dark"
                        and active_aperture_width is not None
                        and active_aperture_width_key not in scan.widths
                    ):
                        add_trace_width_finding(
                            scan,
                            path,
                            layer,
                            active_aperture,
                            current,
                            point,
                            active_aperture_width,
                            polarity,
                        )
                    have_draw = True
                    current = point
                    continue
        if gerber_ignored_command(stripped):
            continue
        unit = gerber_unit_command(stripped)
        if unit is not None:
            units = unit
        if upper in ("G70*", "G71*"):
            continue
        coordinate_mode = gerber_coordinate_mode_command(stripped)
        if coordinate_mode is not None:
            coord_decimals = set_gerber_coordinate_mode(coord_decimals, coordinate_mode)
            fast_coord_info = fast_region_coord_info(coord_decimals)
            continue
        quadrant = gerber_quadrant_mode_command(stripped)
        if quadrant is not None:
            quadrant_mode = quadrant
            continue
        if upper.startswith("%FS"):
            have_format = True
            coord_decimals = parse_gerber_coord_format(stripped) or coord_decimals
            fast_coord_info = fast_region_coord_info(coord_decimals)
        new_polarity = gerber_polarity_command(stripped)
        if new_polarity is not None:
            polarity = new_polarity
            continue
        sr = parse_gerber_step_repeat(stripped, units)
        if sr is not None:
            sr_offsets = sr
            continue
        macro = parse_gerber_macro(stripped, units)
        if macro is not None:
            macros[macro[0]] = macro[1]
            continue
        aperture = parse_gerber_aperture(stripped, units, macros)
        if aperture is not None:
            aperture[1].function = active_aperture_function
            apertures[aperture[0]] = aperture[1]
            if aperture[0] == active_aperture:
                active_aperture_width = aperture[1].width
                active_aperture_width_key = round(active_aperture_width or 0.0, 6)
            continue
        if gerber_region_start(stripped):
            region_points = []
            region_polarity = polarity
            continue
        if gerber_region_end(stripped):
            if region_polarity == "dark":
                add_compound_region_primitives(
                    scan,
                    split_region_contours(region_points),
                    sr_offsets,
                    net=active_net,
                    function=active_aperture_function,
                    component=active_component,
                    object_id=active_object_id,
                )
            elif region_polarity == "clear":
                for contour in split_region_contours(region_points):
                    add_region_primitives(
                        scan, contour, sr_offsets, scan.clear_masks
                    )
            region_points = None
            region_polarity = None
            continue
        selected = gerber_aperture_select(stripped)
        if selected is not None:
            active_aperture = selected
            aperture = apertures.get(active_aperture)
            active_aperture_width = aperture.width if aperture is not None else None
            active_aperture_width_key = round(active_aperture_width or 0.0, 6)
        arc_mode = gerber_interpolation(stripped)
        if arc_mode is not None:
            interpolation = arc_mode
        operation = gerber_operation(stripped)
        point = parse_gerber_point(stripped, coord_decimals, units, current)
        if operation is not None:
            current_operation = operation
        operation = operation or current_operation
        if operation == 2 and point is not None:
            current = point
            if region_points is not None:
                if region_points and region_points[-1] is not None:
                    region_points.append(None)
                region_points.append(point)
            continue
        if operation == 1 and point is not None:
            add_gerber_draw(
                scan,
                path,
                layer,
                apertures.get(active_aperture),
                active_aperture,
                current,
                point,
                stripped,
                coord_decimals,
                units,
                interpolation,
                quadrant_mode,
                polarity,
                region_points,
                sr_offsets,
                net=active_net,
                function=(
                    apertures.get(active_aperture).function
                    if apertures.get(active_aperture) is not None
                    else ""
                ),
                component=active_component,
                object_id=active_object_id,
            )
            have_draw = True
            current = point
        elif operation == 3 and point is not None:
            flash_sequence += 1
            add_gerber_flash(
                scan,
                apertures.get(active_aperture),
                point,
                polarity,
                sr_offsets,
                net=active_net,
                component=active_component,
                object_id=active_object_id,
                flash_id=str(flash_sequence),
            )
            current = point

    if not have_format:
        scan.findings.append(
            ScanFinding(
                "Trace Mssing",
                "{0} has no Gerber FS format header.".format(path),
                category="Signal Integrity",
                layer=layer,
                raw={"file": path, "item": "Gerber Format Missing"},
                rule="-,-,-",
            )
        )
    if not have_draw and is_edge:
        scan.findings.append(
            ScanFinding(
                "Trace-to-Board Edge",
                "{0} has no draw command.".format(path),
                severity="error",
                category="Copper-to-Board Edge",
                layer=layer,
                raw={"file": path, "item": "Empty Board Outline"},
            )
        )
    elif is_edge:
        gap = outline_open_gap(scan.segments, OUTLINE_OPEN_GAP_MM)
        if gap > OUTLINE_OPEN_GAP_MM:
            endpoints = outline_open_gap_endpoints(
                scan.segments,
                OUTLINE_OPEN_GAP_MM,
            )
            scan.findings.append(
                ScanFinding(
                    "Trace-to-Board Edge",
                    "{0} has an open outline endpoint gap of {1:.3f}mm.".format(path, gap),
                    category="Copper-to-Board Edge",
                    value=gap,
                    layer=layer,
                    raw={
                        "file": path,
                        "gap": gap,
                        "item": "Board Outline Open Gap",
                        "segment": endpoints,
                        "width": 0.15,
                        "bbox": gerber_segment_bbox(endpoints[0], endpoints[1], 0.15),
                        "primary": gerber_endpoint_mapping_raw(path, layer, endpoints[0], 0.15),
                        "related": gerber_endpoint_mapping_raw(path, layer, endpoints[1], 0.15),
                    },
                    color="gold",
                )
            )
    finalize_gerber_scan_metadata(scan, units, coord_decimals, have_format)
    return scan


def finalize_gerber_scan_metadata(scan, units, coord_format, have_format):
    scan.units = units
    scan.coordinate_resolution_mm = gerber_coordinate_resolution_mm(
        coord_format, units
    )
    for primitive in tuple(scan.primitives) + tuple(scan.clear_masks):
        primitive.coordinate_resolution_mm = scan.coordinate_resolution_mm
    for finding in scan.findings:
        annotate_finding_format_metadata(
            finding,
            scan.coordinate_resolution_mm,
            units,
            scan.file_function,
            declared=have_format,
        )


def gerber_coordinate_resolution_mm(coord_format, units):
    _mode, x_format, y_format = gerber_point_format(coord_format)
    x_decimals = gerber_coord_spec(x_format)[2]
    y_decimals = gerber_coord_spec(y_format)[2]
    return max(
        to_mm(10.0 ** (-x_decimals), units),
        to_mm(10.0 ** (-y_decimals), units),
    )


def annotate_finding_format_metadata(
    finding,
    coordinate_resolution_mm,
    units,
    file_function="",
    layer_span=None,
    declared=True,
):
    raw = finding.raw
    raw.setdefault("units", units)
    if coordinate_resolution_mm is not None:
        # This helper runs after the complete file has been parsed.  Its
        # file-level resolution is authoritative and replaces any provisional
        # per-line estimate made while primitives were being constructed.
        raw["coordinate_resolution_mm"] = coordinate_resolution_mm
        raw["quantization_tolerance_mm"] = coordinate_resolution_mm / 2.0
    raw.setdefault("coordinate_format_declared", bool(declared))
    if file_function:
        raw.setdefault("file_function", file_function)
    if layer_span:
        raw.setdefault("layer_span", layer_span)
    for name in ("primary", "related"):
        endpoint = raw.get(name)
        if not isinstance(endpoint, dict):
            continue
        if coordinate_resolution_mm is not None:
            endpoint["coordinate_resolution_mm"] = coordinate_resolution_mm
            endpoint["quantization_tolerance_mm"] = coordinate_resolution_mm / 2.0
        if file_function:
            endpoint.setdefault("file_function", file_function)


def scan_excellon(path, spacing_limit=None, board_thickness_mm=None):
    for finding in parse_excellon_scan(path, spacing_limit, board_thickness_mm).findings:
        yield finding


def parse_excellon_scan(path, spacing_limit=None, board_thickness_mm=None):
    scan = ExcellonScan(path)
    units = "inch"
    tools = {}
    tool_functions = {}
    active_tool = None
    pending_tool_function = ""
    have_units = False
    have_drill = False
    have_header = False
    have_end = False
    have_file_function = False
    plated = excellon_plating_from_filename(path)
    route_position = None
    route_active = False
    for line in iter_text_lines(path):
        stripped = line.strip()
        upper = stripped.upper()
        if upper == "M48":
            have_header = True
        elif upper == "M30":
            have_end = True
        file_function = parse_excellon_file_function(stripped)
        if file_function is not None:
            have_file_function = True
            scan.file_function = file_function
            scan.layer_span = excellon_layer_span(file_function)
            function_upper = file_function.upper()
            if "NONPLATED" in function_upper or "NPTH" in function_upper:
                plated = False
            elif "PLATED" in function_upper or "PTH" in function_upper:
                plated = True
        if "METRIC" in upper:
            units = "mm"
            have_units = True
        elif "INCH" in upper:
            units = "inch"
            have_units = True
        coordinate_resolution = excellon_coordinate_resolution_mm(upper, units)
        if coordinate_resolution is not None:
            scan.coordinate_resolution_mm = min(
                scan.coordinate_resolution_mm
                if scan.coordinate_resolution_mm is not None
                else coordinate_resolution,
                coordinate_resolution,
            )
        aperture_function = parse_excellon_aperture_function(upper)
        if aperture_function is not None:
            pending_tool_function = aperture_function
        tool = parse_excellon_tool(upper, units)
        if tool is not None:
            tools[tool[0]] = tool[1]
            tool_functions[tool[0]] = pending_tool_function
            pending_tool_function = ""
            active_tool = tool[0]
            continue
        selected = re.match(r"^T(\d+)$", upper)
        if selected:
            active_tool = selected.group(1)
            continue
        if upper == "M15":
            route_active = True
            continue
        if upper == "M16":
            route_active = False
            continue
        if upper.startswith("G05"):
            route_active = False
            route_position = None
            continue
        route = parse_excellon_route_coord(upper, units)
        if route is not None:
            mode, point = route
            if (
                mode == "linear"
                and route_active
                and route_position is not None
                and active_tool in tools
            ):
                have_drill = True
                add_excellon_slot_findings(
                    scan,
                    path,
                    active_tool,
                    (route_position, point),
                    tools[active_tool],
                    board_thickness_mm,
                    scan.coordinate_resolution_mm,
                    tool_functions.get(active_tool, ""),
                )
            route_position = point
            continue
        coord = parse_excellon_coord(upper, units)
        if coord is not None:
            have_drill = True
            diameter = tools.get(active_tool)
            if diameter is not None:
                drill = DrillPrimitive(
                    "circle",
                    center=coord,
                    diameter=diameter,
                    coordinate_resolution_mm=coordinate_resolution,
                    function=tool_functions.get(active_tool, ""),
                    tool=active_tool,
                )
                scan.primitives.append(drill)
                primary = drill_mapping_raw(drill, path, active_tool, scan.layer)
                smallest_item = excellon_smallest_hole_item(
                    tool_functions.get(active_tool, ""), plated
                )
                if smallest_item:
                    scan.findings.append(
                        ScanFinding(
                            smallest_item,
                            "Excellon drill diameter is {0:.3f}mm.".format(diameter),
                            category="Hole Size",
                            value=diameter,
                            layer=scan.layer,
                            raw={
                                "file": path,
                                "tool": active_tool,
                                "tool_function": tool_functions.get(active_tool, ""),
                                "point": coord,
                                "diameter": diameter,
                                "bbox": drill.bbox,
                                "primary": primary,
                            },
                        )
                    )
                scan.findings.append(
                    ScanFinding(
                        "Largest Drill Size",
                        "Excellon drill diameter is {0:.3f}mm.".format(diameter),
                        category="Hole Size",
                        value=diameter,
                        layer=scan.layer,
                        raw={
                            "file": path,
                            "tool": active_tool,
                            "point": coord,
                            "diameter": diameter,
                            "bbox": drill.bbox,
                            "primary": primary,
                        },
                    )
                )
                if plated is True:
                    scan.findings.append(
                        ScanFinding(
                            "Largest PTH Size",
                            "Excellon PTH diameter is {0:.3f}mm.".format(diameter),
                            category="Hole Size",
                            value=diameter,
                            layer=scan.layer,
                            raw={
                                "file": path,
                                "tool": active_tool,
                                "point": coord,
                                "diameter": diameter,
                                "bbox": drill.bbox,
                                "primary": primary,
                            },
                        )
                    )
                if board_thickness_mm and diameter > 0:
                    ratio = float(board_thickness_mm) / diameter
                    scan.findings.append(
                        ScanFinding(
                            "Aspect Ratio",
                            "PCB thickness-to-hole ratio is {0:.3f}.".format(ratio),
                            category="Hole Size",
                            value=ratio,
                            layer=scan.layer,
                            raw={
                                "file": path,
                                "tool": active_tool,
                                "point": coord,
                                "diameter": diameter,
                                "board_thickness_mm": float(board_thickness_mm),
                                "bbox": drill.bbox,
                                "primary": primary,
                            },
                        )
                    )
        slot = parse_excellon_slot(upper, units)
        if slot is not None and active_tool in tools:
            have_drill = True
            add_excellon_slot_findings(
                scan,
                path,
                active_tool,
                slot,
                tools[active_tool],
                board_thickness_mm,
                scan.coordinate_resolution_mm,
                tool_functions.get(active_tool, ""),
            )

    if not have_units:
        scan.findings.append(
            ScanFinding(
                "Drill Units Missing",
                "{0} has no Excellon unit header.".format(path),
                layer=scan.layer,
                raw={"file": path, "item": "Drill Units Missing"},
            )
        )
    valid_declared_empty_file = (
        have_header
        and have_end
        and have_units
        and have_file_function
        and not tools
        and not have_drill
    )
    if not tools and not valid_declared_empty_file:
        scan.findings.append(
            ScanFinding(
                "No Drill Tools",
                "{0} has no drill tools.".format(path),
                severity="error",
                layer=scan.layer,
                raw={"file": path, "item": "No Drill Tools"},
            )
        )
    if not have_drill and not valid_declared_empty_file:
        scan.findings.append(
            ScanFinding(
                "No Drill Commands",
                "{0} has no drill coordinates.".format(path),
                severity="error",
                layer=scan.layer,
                raw={"file": path, "item": "No Drill Commands"},
            )
        )
    scan.plated = plated
    scan.units = units
    for primitive in scan.primitives:
        # Decimal Excellon output may omit trailing zeroes independently on
        # every coordinate (``X1.0`` and ``X0.7874`` can share one file).  A
        # primitive's provisional per-line precision is therefore not the
        # file's coordinate grid; normalize every primitive after discovering
        # the finest grid represented anywhere in the file.
        primitive.coordinate_resolution_mm = scan.coordinate_resolution_mm
    for finding in scan.findings:
        annotate_finding_format_metadata(
            finding,
            scan.coordinate_resolution_mm,
            units,
            scan.file_function,
            scan.layer_span,
            declared=have_units,
        )
    return scan


def add_excellon_slot_findings(
    scan,
    path,
    tool,
    slot,
    width,
    board_thickness_mm=None,
    coordinate_resolution_mm=None,
    tool_function="",
):
    """Record one routed slot from its centreline and cutter diameter."""
    length = distance(slot[0], slot[1]) + width
    drill = DrillPrimitive(
        "slot",
        start=slot[0],
        end=slot[1],
        diameter=width,
        coordinate_resolution_mm=coordinate_resolution_mm,
        function=tool_function,
        tool=tool,
    )
    scan.primitives.append(drill)
    primary = drill_mapping_raw(drill, path, tool, scan.layer)
    raw = {
        "file": path,
        "tool": tool,
        "tool_function": tool_function,
        "segment": slot,
        "diameter": width,
        "width": width,
        "length": length,
        "bbox": drill.bbox,
        "primary": primary,
    }
    for item, value, message in (
        (
            "Smallest Slot Width",
            width,
            "Excellon slot width is {0:.3f}mm.".format(width),
        ),
        (
            "Largest Slot Length",
            length,
            "Excellon slot length is {0:.3f}mm.".format(length),
        ),
        (
            "Largest Slot Width",
            width,
            "Excellon slot width is {0:.3f}mm.".format(width),
        ),
        (
            "Slot Aspect Ratio",
            length / width if width > 0 else 0.0,
            "Excellon slot length-to-width ratio is {0:.3f}.".format(
                length / width if width > 0 else 0.0
            ),
        ),
    ):
        scan.findings.append(
            ScanFinding(
                item,
                message,
                category="Hole Size",
                value=value,
                layer=scan.layer,
                raw=dict(raw),
            )
        )
    if board_thickness_mm and width > 0:
        ratio_raw = dict(raw)
        ratio_raw["board_thickness_mm"] = float(board_thickness_mm)
        scan.findings.append(
            ScanFinding(
                "Aspect Ratio",
                "PCB thickness-to-hole ratio is {0:.3f}.".format(
                    float(board_thickness_mm) / width
                ),
                category="Hole Size",
                value=float(board_thickness_mm) / width,
                layer=scan.layer,
                raw=ratio_raw,
            )
        )


def excellon_plating_from_filename(path):
    stem = os.path.splitext(os.path.basename(path))[0].upper()
    if "NPTH" in stem or "NONPLATED" in stem:
        return False
    if "PTH" in stem or "PLATED" in stem:
        return True
    return None


def split_region_contours(points):
    contours = []
    current = []
    for point in points or ():
        if point is None:
            if current:
                contours.append(current)
                current = []
            continue
        current.append(point)
    if current:
        contours.append(current)
    return contours


def add_compound_region_primitives(
    scan, contours, offsets, net="", function="", component="", object_id=""
):
    """Create region islands with nested contours represented as voids.

    Gerber permits multiple contours inside one G36/G37 region.  Treating every
    contour as dark copper fills thermal/clearance holes and creates false 0 mm
    spacing violations.  Even nesting depths are copper islands; odd depths are
    holes belonging to the nearest containing island.
    """
    contours = [tuple(contour) for contour in contours if len(contour) >= 3]
    if not contours:
        return
    parents = []
    for index, contour in enumerate(contours):
        point = contour[0]
        containers = [
            candidate
            for candidate, other in enumerate(contours)
            if candidate != index and point_in_polygon(point, other)
        ]
        parents.append(min(containers, key=lambda candidate: abs(polygon_area(contours[candidate]))) if containers else None)

    depths = [contour_depth(index, parents) for index in range(len(contours))]
    for index, contour in enumerate(contours):
        if depths[index] % 2:
            continue
        holes = [
            contours[candidate]
            for candidate, parent in enumerate(parents)
            if parent == index and depths[candidate] == depths[index] + 1
        ]
        add_region_primitives(
            scan,
            contour,
            offsets,
            net=net,
            function=function,
            component=component,
            object_id=object_id,
            holes=holes,
        )


def contour_depth(index, parents):
    depth = 0
    seen = set()
    parent = parents[index]
    while parent is not None and parent not in seen:
        seen.add(parent)
        depth += 1
        parent = parents[parent]
    return depth


def polygon_area(points):
    return sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, points[1:] + points[:1])
    ) / 2.0


def gerber_x2_attribute(command):
    match = re.match(
        r"%T([AFO])\.([^,*%]+)(?:,([^*%]*))?\*%$",
        command,
        re.IGNORECASE,
    )
    if match:
        return "T" + match.group(1).upper(), match.group(2).upper(), match.group(3) or ""
    deleted = re.match(r"%TD(?:\.([^*%]+))?\*%$", command, re.IGNORECASE)
    if deleted:
        return "TD", (deleted.group(1) or "").upper(), ""
    return None


def fast_region_coord_info(decimals):
    coordinate_mode, x_format, y_format = gerber_point_format(decimals)
    return coordinate_mode, fast_coord_spec(x_format), fast_coord_spec(y_format)


def fast_coord_spec(decimals):
    zero_suppression, integer_digits, decimal_digits = gerber_coord_spec(decimals)
    return zero_suppression, integer_digits + decimal_digits, 10.0 ** decimal_digits


def parse_fast_region_coordinate(line, upper, coord_info, units, current):
    if not line:
        return None
    if upper[0] not in ("X", "Y") or "G" in upper or "I" in upper or "J" in upper or "%" in upper:
        return None
    if " " not in line and "\t" not in line:
        parsed = parse_compact_region_coordinate(line, upper, coord_info, units, current)
        if parsed is not None:
            return parsed

    x_text = None
    y_text = None
    operation = None
    index = 0
    length = len(line)
    while index < length:
        code = upper[index]
        if code in ("X", "Y"):
            index += 1
            while index < length and line[index].isspace():
                index += 1
            start = index
            while index < length and (line[index].isdigit() or line[index] in "+-."):
                index += 1
            if start == index:
                return None
            if code == "X":
                x_text = line[start:index]
            else:
                y_text = line[start:index]
            continue
        if code == "D":
            index += 1
            while index < length and line[index].isspace():
                index += 1
            start = index
            while index < length and line[index].isdigit():
                index += 1
            if start == index:
                return None
            value = int(line[start:index])
            if value not in (1, 2, 3):
                return None
            operation = value
            continue
        if code == "*" or line[index].isspace():
            index += 1
            continue
        return None

    if x_text is None and y_text is None:
        return None
    coordinate_mode, x_format, y_format = coord_info
    x = current[0] if current is not None else None
    y = current[1] if current is not None else None
    if x_text is not None:
        value = to_mm(parse_fast_gerber_coord(x_text, x_format), units)
        x = (current[0] if coordinate_mode == "incremental" and current is not None else 0.0) + value
    if y_text is not None:
        value = to_mm(parse_fast_gerber_coord(y_text, y_format), units)
        y = (current[1] if coordinate_mode == "incremental" and current is not None else 0.0) + value
    if x is None or y is None:
        return None
    return (x, y), operation


def parse_compact_region_coordinate(line, upper, coord_info, units, current):
    line_end = len(line) - 1 if line.endswith("*") else len(line)
    x_pos = 0 if upper[0] == "X" else upper.find("X")
    y_pos = 0 if upper[0] == "Y" else upper.find("Y")
    d_pos = upper.find("D", 1)
    operation = None
    if d_pos >= 0 and d_pos < line_end:
        try:
            operation = int(line[d_pos + 1 : line_end])
        except ValueError:
            return None
        if operation not in (1, 2, 3):
            return None

    x_text = compact_coord_text(line, x_pos, y_pos, d_pos, line_end)
    y_text = compact_coord_text(line, y_pos, x_pos, d_pos, line_end)
    if x_text is None and y_text is None:
        return None

    coordinate_mode, x_format, y_format = coord_info
    x = current[0] if current is not None else None
    y = current[1] if current is not None else None
    if x_text is not None:
        value = to_mm(parse_fast_gerber_coord(x_text, x_format), units)
        x = (current[0] if coordinate_mode == "incremental" and current is not None else 0.0) + value
    if y_text is not None:
        value = to_mm(parse_fast_gerber_coord(y_text, y_format), units)
        y = (current[1] if coordinate_mode == "incremental" and current is not None else 0.0) + value
    if x is None or y is None:
        return None
    return (x, y), operation


def compact_coord_text(line, marker_pos, other_pos, d_pos, line_end):
    if marker_pos < 0:
        return None
    end = line_end
    for position in (other_pos, d_pos):
        if position > marker_pos and position < end:
            end = position
    if end <= marker_pos + 1:
        return None
    return line[marker_pos + 1 : end]


def parse_fast_gerber_coord(value, coord_spec):
    if "." in value:
        return float(value)
    zero_suppression, total_digits, denominator = coord_spec
    sign = -1 if value.startswith("-") else 1
    digits = value[1:] if value.startswith(("-", "+")) else value
    if zero_suppression == "T":
        digits = digits.ljust(total_digits, "0")
    return sign * int(digits or "0") / denominator


def spacing_pair_diameter(pair):
    radii = [radius for radius in pair or () if radius]
    return min(radii) * 2.0 if radii else None


def drill_mapping_raw(drill, path, tool=None, layer=None):
    data = {
        "file": path,
        "item_type": "drill",
        "diameter": drill.diameter,
        "bbox": drill.bbox,
    }
    if tool is not None:
        data["tool"] = tool
    if layer is not None:
        data["layer"] = layer
    if drill.kind == "slot":
        data["segment"] = (drill.start, drill.end)
        data["width"] = drill.diameter
    elif drill.center is not None:
        data["point"] = drill.center
    if drill.coordinate_resolution_mm is not None:
        data["coordinate_resolution_mm"] = drill.coordinate_resolution_mm
        data["quantization_tolerance_mm"] = (
            drill.coordinate_resolution_mm / 2.0
        )
    return data


def gerber_endpoint_mapping_raw(path, layer, point, width):
    radius = (width or 0.0) / 2.0
    return {
        "file": path,
        "layer": layer,
        "item_type": "gerber",
        "point": point,
        "width": width,
        "bbox": (
            point[0] - radius,
            point[1] - radius,
            point[0] + radius,
            point[1] + radius,
        ),
    }


def drill_spacing_bbox(pair, diameter):
    if not pair or len(pair) != 2 or pair[0] is None or pair[1] is None:
        return None
    radius = (diameter or 0.0) / 2.0
    return (
        min(pair[0][0], pair[1][0]) - radius,
        min(pair[0][1], pair[1][1]) - radius,
        max(pair[0][0], pair[1][0]) + radius,
        max(pair[0][1], pair[1][1]) + radius,
    )


def parse_excellon_tool(line, units):
    match = re.match(r"^T(\d+)C([0-9.]+)", line)
    if not match:
        return None
    return match.group(1), to_mm(float(match.group(2)), units)


def parse_excellon_aperture_function(line):
    marker = "TA.APERFUNCTION,"
    if marker not in line:
        return None
    value = line.split(marker, 1)[1].split("*", 1)[0]
    return value.split(",")[-1].strip(" ;%")


def parse_excellon_file_function(line):
    match = re.search(
        r"TF\.FILEFUNCTION,([^*%\r\n]+)",
        str(line or ""),
        re.IGNORECASE,
    )
    return match.group(1).strip(" ;") if match else None


def excellon_layer_span(file_function):
    parts = [part.strip() for part in str(file_function or "").split(",")]
    numeric = [int(part) for part in parts if part.isdigit()]
    return tuple(numeric[:2]) if len(numeric) >= 2 else None


def excellon_coordinate_resolution_mm(line, units):
    resolutions = []
    for value in re.findall(r"[XY]([+-]?[0-9.]+)", str(line or ""), re.IGNORECASE):
        text = value.lstrip("+-")
        if "." in text:
            decimal_digits = len(text.split(".", 1)[1])
        else:
            # Matches parse_coord(), whose legacy fixed format is 4 decimals.
            decimal_digits = 4
        resolutions.append(to_mm(10.0 ** (-decimal_digits), units))
    # In decimal Excellon, trailing zeroes are optional.  The finest token in
    # the file reveals the writer's available grid; a shorter token does not
    # prove a coarser grid (for example X1.0 may be an exact X1.0000).  The
    # caller retains the minimum across all lines for the same reason.
    return min(resolutions) if resolutions else None


def excellon_smallest_hole_item(tool_function, plated):
    if plated is not True:
        return ""
    function = "".join(
        character
        for character in str(tool_function or "").lower()
        if character.isalnum()
    )
    if function == "viadrill":
        return "Smallest Drill Size"
    if function == "componentdrill":
        return "Smallest PTH"
    return ""


def parse_excellon_coord(line, units):
    if "G85" in line or re.match(r"^G0?[01]", line):
        return None
    match = re.search(r"X([+-]?[0-9.]+)Y([+-]?[0-9.]+)", line)
    if not match:
        return None
    return to_mm(parse_coord(match.group(1)), units), to_mm(parse_coord(match.group(2)), units)


def parse_excellon_route_coord(line, units):
    match = re.match(
        r"^G0?([01])X([+-]?[0-9.]+)Y([+-]?[0-9.]+)", line
    )
    if not match:
        return None
    mode = "rapid" if match.group(1) == "0" else "linear"
    point = (
        to_mm(parse_coord(match.group(2)), units),
        to_mm(parse_coord(match.group(3)), units),
    )
    return mode, point


def parse_excellon_slot(line, units):
    match = re.search(r"X([+-]?[0-9.]+)Y([+-]?[0-9.]+)G85X([+-]?[0-9.]+)Y([+-]?[0-9.]+)", line)
    if not match:
        return None
    start = (to_mm(parse_coord(match.group(1)), units), to_mm(parse_coord(match.group(2)), units))
    end = (to_mm(parse_coord(match.group(3)), units), to_mm(parse_coord(match.group(4)), units))
    return start, end


def parse_coord(value):
    text = str(value)
    if "." in text:
        return float(text)
    return float(text) / 10000.0
