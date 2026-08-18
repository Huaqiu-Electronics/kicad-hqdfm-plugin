from kicad_dfm.services.export_gerber_apertures import aperture_hole_mask
from kicad_dfm.services.export_gerber_apertures import gerber_flash_primitive
from kicad_dfm.services.export_gerber_apertures import offset_point
from kicad_dfm.services.export_gerber_commands import parse_gerber_arc_offset
from kicad_dfm.services.export_geometry_core import GerberPrimitive
from kicad_dfm.services.export_geometry_core import GerberSegment
from kicad_dfm.services.export_geometry_core import add_region_primitive
from kicad_dfm.services.export_geometry_core import expand_bbox
from kicad_dfm.services.export_geometry_core import gerber_arc_segments
from kicad_dfm.services.export_geometry_core import segment_bbox
from kicad_dfm.services.export_scan_models import ScanFinding


def add_gerber_draw(
    scan,
    path,
    layer,
    aperture,
    active_aperture,
    current,
    point,
    line,
    coord_decimals,
    units,
    interpolation,
    quadrant_mode,
    polarity,
    region_points,
    offsets,
    net="",
    function="",
    component="",
    object_id="",
):
    width = aperture.width if aperture is not None else None
    if current is not None:
        segments = gerber_draw_segments(
            current,
            point,
            line,
            coord_decimals,
            units,
            interpolation,
            quadrant_mode,
            arc_sagitta_mm=0.001 if scan.is_edge else None,
        )
        for start, end in segments:
            if region_points is None and polarity == "dark":
                add_segment_primitives(
                    scan,
                    start,
                    end,
                    width or 0.0,
                    offsets,
                    net=net,
                    function=function,
                    component=component,
                    object_id=object_id,
                )
            elif region_points is None and polarity == "clear":
                add_segment_masks(scan, start, end, width or 0.0, offsets)
            if region_points is not None:
                if not region_points:
                    region_points.append(start)
                region_points.append(end)
    add_trace_width_finding(scan, path, layer, active_aperture, current, point, width, polarity)


def gerber_draw_segments(
    current,
    point,
    line,
    coord_decimals,
    units,
    interpolation,
    quadrant_mode,
    arc_sagitta_mm=None,
):
    if interpolation == "linear":
        return [(current, point)]
    offset = parse_gerber_arc_offset(line, coord_decimals, units)
    if offset is not None:
        segments = gerber_arc_segments(
            current,
            point,
            offset,
            interpolation,
            quadrant_mode,
            max_sagitta=arc_sagitta_mm,
        )
        if segments:
            return segments
    return [(current, point)]


def add_trace_width_finding(scan, path, layer, active_aperture, current, point, width, polarity):
    width_key = round(width or 0.0, 6)
    if not scan.is_copper or polarity != "dark" or width is None:
        return
    # Keep the set for the fast-region compatibility path, but do not use it
    # to collapse separate draw commands.  Every violating trace must remain
    # independently locatable even when many traces share one aperture width.
    scan.widths.add(width_key)
    bbox = gerber_segment_bbox(current, point, width)
    scan.findings.append(
        ScanFinding(
            "Smallest Trace Width",
            "Gerber draw aperture width is {0:.3f}mm.".format(width),
            category="Smallest Trace Width",
            value=width,
            layer=layer,
            raw={
                "file": path,
                "aperture": active_aperture,
                "segment": (current, point),
                "width": width,
                "bbox": bbox,
                "primary": {
                    "file": path,
                    "layer": layer,
                    "item_type": "gerber",
                    "segment": (current, point),
                    "width": width,
                    "bbox": bbox,
                },
            },
        )
    )


def gerber_segment_bbox(start, end, width):
    if start is None or end is None:
        return None
    return expand_bbox(segment_bbox(start, end), (width or 0.0) / 2.0)


def add_gerber_flash(
    scan,
    aperture,
    point,
    polarity,
    offsets,
    net="",
    component="",
    object_id="",
    flash_id="",
):
    if aperture is None or aperture.size is None:
        return
    if aperture.macro_primitives:
        add_macro_flash_primitives(
            scan,
            aperture,
            point,
            polarity,
            offsets,
            net,
            component,
            object_id,
            flash_id,
        )
        return
    primitive = gerber_flash_primitive(aperture, point)
    if polarity == "dark":
        add_flash_primitives(
            scan.primitives,
            primitive,
            offsets,
            net=net,
            function=aperture.function,
            component=component,
            object_id=object_id,
            flash_id=flash_id,
        )
        if aperture.hole:
            add_flash_primitives(scan.clear_masks, aperture_hole_mask(point, aperture.hole), offsets)
    else:
        add_flash_primitives(scan.clear_masks, primitive, offsets)


def add_segment_primitives(
    scan,
    start,
    end,
    width,
    offsets,
    net="",
    function="",
    component="",
    object_id="",
):
    for offset in offsets:
        segment_start = offset_point(start, offset)
        segment_end = offset_point(end, offset)
        scan.segments.append(GerberSegment(segment_start, segment_end, width))
        scan.primitives.append(
            GerberPrimitive(
                "segment",
                start=segment_start,
                end=segment_end,
                width=width,
                net=net,
                function=function,
                component=component,
                object_id=object_id,
            )
        )


def add_segment_masks(scan, start, end, width, offsets):
    for offset in offsets:
        scan.clear_masks.append(
            GerberPrimitive("segment", start=offset_point(start, offset), end=offset_point(end, offset), width=width)
        )


def add_flash_primitives(
    target,
    primitive,
    offsets,
    net="",
    function="",
    component="",
    object_id="",
    flash_id="",
):
    for offset_index, offset in enumerate(offsets):
        instance_flash_id = (
            "{0}:{1}".format(flash_id, offset_index) if flash_id else ""
        )
        target.append(
            offset_primitive(
                primitive,
                offset,
                net=net,
                function=function,
                component=component,
                object_id=object_id,
                flash_id=instance_flash_id,
            )
        )


def add_macro_flash_primitives(
    scan,
    aperture,
    point,
    polarity,
    offsets,
    net="",
    component="",
    object_id="",
    flash_id="",
):
    for primitive_polarity, primitive in aperture.macro_primitives:
        if polarity == "clear" and primitive_polarity == "clear":
            continue
        target = scan.primitives if polarity == "dark" and primitive_polarity == "dark" else scan.clear_masks
        start_index = len(target)
        add_flash_primitives(
            target,
            offset_primitive(
                primitive,
                point,
                net=net,
                function=aperture.function,
                component=component,
                object_id=object_id,
                flash_id=flash_id,
            ),
            offsets,
            net=net,
            function=aperture.function,
            component=component,
            object_id=object_id,
            flash_id=flash_id,
        )
        if aperture.logical_size:
            for added in target[start_index:]:
                added.shape_width, added.shape_height = aperture.logical_size


def add_region_primitives(
    scan,
    points,
    offsets,
    target=None,
    net="",
    function="",
    component="",
    object_id="",
    holes=None,
):
    for offset in offsets:
        if offset == (0.0, 0.0):
            add_region_primitive(
                scan,
                points,
                target,
                net=net,
                function=function,
                component=component,
                object_id=object_id,
                holes=holes,
            )
        else:
            add_region_primitive(
                scan,
                [offset_point(point, offset) for point in points],
                target,
                net=net,
                function=function,
                component=component,
                object_id=object_id,
                holes=[
                    [offset_point(point, offset) for point in contour]
                    for contour in (holes or ())
                ],
            )


def offset_primitive(
    primitive,
    offset,
    net=None,
    function=None,
    component=None,
    object_id=None,
    flash_id=None,
):
    return GerberPrimitive(
        primitive.kind,
        start=offset_point(primitive.start, offset) if primitive.start is not None else None,
        end=offset_point(primitive.end, offset) if primitive.end is not None else None,
        center=offset_point(primitive.center, offset) if primitive.center is not None else None,
        width=primitive.shape_width,
        height=primitive.shape_height,
        is_flash=primitive.is_flash,
        points=[offset_point(point, offset) for point in primitive.points],
        holes=[
            [offset_point(point, offset) for point in contour]
            for contour in primitive.holes
        ],
        net=primitive.net if net is None else net,
        function=primitive.function if function is None else function,
        component=primitive.component if component is None else component,
        object_id=primitive.object_id if object_id is None else object_id,
        flash_id=primitive.flash_id if flash_id is None else flash_id,
    )
