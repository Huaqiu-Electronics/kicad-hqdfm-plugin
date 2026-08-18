import os
import re


def layer_name_from_file(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    for separator in ("-", "_"):
        if separator in stem:
            candidate = stem.rsplit(separator, 1)[-1]
            if display_layer_name(candidate) != candidate:
                stem = candidate
                break
    return display_layer_name(stem)


def layer_name_from_file_function(file_function):
    """Return the KiCad layer named by a Gerber X2 FileFunction value."""
    parts = [part.strip() for part in str(file_function or "").split(",")]
    if not parts or not parts[0]:
        return ""
    function = parts[0].lower()
    qualifiers = {part.lower() for part in parts[1:]}
    if function == "copper":
        if qualifiers.intersection(("top", "front")):
            return "F.Cu"
        if qualifiers.intersection(("bot", "bottom", "back")):
            return "B.Cu"
        for part in parts[1:]:
            match = re.match(r"L(\d+)$", part, re.IGNORECASE)
            if match:
                layer_number = int(match.group(1))
                return "F.Cu" if layer_number <= 1 else "In{0}.Cu".format(
                    layer_number - 1
                )
    if function in ("soldermask", "solder_mask"):
        if qualifiers.intersection(("top", "front")):
            return "F.Mask"
        if qualifiers.intersection(("bot", "bottom", "back")):
            return "B.Mask"
    if function in ("profile", "outline"):
        return "Edge.Cuts"
    return ""


def display_layer_name(stem):
    aliases = {
        "EdgeCuts": "Edge.Cuts",
        "Edge_Cuts": "Edge.Cuts",
        "CuTop": "F.Cu",
        "CuBottom": "B.Cu",
        "MaskTop": "F.Mask",
        "MaskBottom": "B.Mask",
    }
    if stem in aliases:
        return aliases[stem]
    match = re.match(r"CuIn(\d+)$", stem)
    if match:
        return "In{0}.Cu".format(match.group(1))
    return stem


def is_copper_layer_name(layer_name):
    text = str(layer_name)
    return text.startswith("Cu") or text in ("F.Cu", "B.Cu") or bool(re.match(r"In\d+\.Cu$", text))


def is_mask_layer_name(layer_name):
    return str(layer_name) in ("F.Mask", "B.Mask", "MaskTop", "MaskBottom")


def color_to_severity(color):
    if color == "red":
        return "error"
    if color == "gold":
        return "warning"
    return "ok"


def grouped_native_results(rows):
    groups = []
    by_key = {}
    for row in rows:
        key = (
            row.get("rule_key") or row.get("item"),
            row.get("item"),
            row.get("value"),
            tuple(row.get("layer") or ()),
            row.get("rule"),
            row.get("color"),
            row.get("item_type"),
            row.get("source"),
            row.get("geometry_basis"),
        )
        if key not in by_key:
            grouped = dict(row)
            grouped["result"] = []
            by_key[key] = grouped
            groups.append(grouped)
        by_key[key]["result"].append(row)
    return groups


def aggregate_physical_native_results(category, rows):
    """Fold per-layer measurements into one physical Gerber result.

    Through-hole pads and vias are emitted on every copper layer.  The raw
    measurements remain available in ``per_layer_measurements`` while the
    report exposes one locatable physical object (or object pair).
    """
    if category not in (
        "Pad size",
        "RingHole",
        "Smallest Trace Spacing",
        "Copper-to-Board Edge",
    ):
        return list(rows)
    ordered = []
    by_key = {}
    for row in rows:
        key = physical_native_result_key(category, row)
        if key is None:
            ordered.append({"row": row, "measurements": None, "layers": None})
            continue
        measurements = physical_layer_measurements(row)
        state = by_key.get(key)
        if state is None:
            state = {
                "row": row,
                "measurements": list(measurements),
                "layers": list(row.get("layer") or ()),
            }
            by_key[key] = state
            ordered.append(state)
            continue
        state["measurements"].extend(measurements)
        for layer in row.get("layer") or ():
            if layer not in state["layers"]:
                state["layers"].append(layer)
        if _physical_result_is_worse(row, state["row"]):
            state["row"] = row

    aggregated = []
    for state in ordered:
        if state["measurements"] is None:
            aggregated.append(state["row"])
            continue
        if len(state["measurements"]) <= 1:
            # A physical-aggregation marker deliberately removes layer
            # identity from the combined finding key.  Do not attach it to a
            # row that was not actually folded with another observation;
            # zones and traces may share one native UUID across layers.
            aggregated.append(state["row"])
            continue
        row = dict(state["row"])
        raw = dict(row.get("raw") or {})
        raw["per_layer_measurements"] = state["measurements"]
        raw["physical_measurement_count"] = len(state["measurements"])
        row["raw"] = raw
        if state["layers"]:
            row["layer"] = state["layers"]
        aggregated.append(row)
    return aggregated


def physical_native_result_key(category, row):
    item_key = row.get("rule_key") or row.get("item")
    raw = row.get("raw") or {}
    row_layers = tuple(row.get("layer") or ())
    if category == "Smallest Trace Spacing":
        primary_raw = raw.get("primary") or {}
        related_raw = raw.get("related") or {}
        left = _native_endpoint_key(
            row.get("id"),
            primary_raw,
            row_layers,
            _geometry_can_cross_layers(primary_raw),
        )
        right = _native_endpoint_key(
            row.get("related_id"),
            related_raw,
            row_layers,
            _geometry_can_cross_layers(related_raw),
        )
        if left is None or right is None:
            return None
        return category, item_key, tuple(sorted((left, right), key=repr))

    primary_raw = raw.get("primary") or raw
    related_raw = raw.get("related")
    if category == "Copper-to-Board Edge" and primary_raw.get(
        "through_hole"
    ):
        mapped_id = _mapped_native_result_id(row, raw)
        if mapped_id:
            return category, item_key, ("native_through_hole", mapped_id)
        drill_raw = primary_raw.get("drill_identity")
        if isinstance(drill_raw, dict):
            drill = _physical_drill_identity("", drill_raw)
            if drill is not None:
                # The nearest piece of a composite slotted pad can be far
                # from its anchor.  The Excellon axis is the authoritative
                # physical identity and is stable on outer/inner Gerbers even
                # when X2 object attributes exist only on the outer layers.
                return category, item_key, drill
    if (
        category == "Copper-to-Board Edge"
        and str(primary_raw.get("kind") or "").lower() == "region"
    ):
        mapped_id = _mapped_native_result_id(row, raw)
        if mapped_id:
            # One multi-layer KiCad zone legitimately has a separate filled
            # copper clearance on each layer.  Gerber may split that layer's
            # fill into several region contours, which should fold together
            # without collapsing the measurements of other layers.
            return (
                category,
                item_key,
                ("native_zone", mapped_id),
                row_layers,
            )
    drill_related = isinstance(related_raw, dict) and str(
        related_raw.get("item_type") or ""
    ).lower() == "drill"
    if category == "RingHole" and drill_related:
        # Annular ring is a per-copper-layer measurement of one physical
        # drilled hole.  Outer and inner layers legitimately use different
        # pad aperture diameters, so the copper pad geometry must not be part
        # of the physical identity.  The drill identity retains location,
        # diameter/shape and drill-source metadata to keep distinct or stacked
        # holes separate.
        drill = _physical_drill_identity(row.get("related_id"), related_raw)
        if drill is not None:
            return category, item_key, drill
    primary = _native_endpoint_key(
        row.get("id"),
        primary_raw,
        row_layers,
        category == "RingHole"
        or drill_related
        or _geometry_can_cross_layers(primary_raw),
    )
    if primary is None:
        return None
    if category == "RingHole":
        related = _native_endpoint_key(
            row.get("related_id"), related_raw, (), True
        )
        if related is not None:
            return category, item_key, primary, related
    return category, item_key, primary


def _physical_drill_identity(item_id, endpoint):
    endpoint = endpoint if isinstance(endpoint, dict) else {}
    stable_id = _stable_native_id(item_id)
    if stable_id:
        return "drill_id", stable_id

    kind = str(endpoint.get("kind") or "circle").lower()
    diameter = round(
        safe_float(endpoint.get("diameter") or endpoint.get("width"), 0.0),
        6,
    )
    point = endpoint.get("point")
    segment = endpoint.get("segment")
    if point and len(point) >= 2:
        geometry = (
            "point",
            round(float(point[0]), 6),
            round(float(point[1]), 6),
        )
    elif segment and len(segment) == 2 and segment[0] and segment[1]:
        endpoints = tuple(
            sorted(
                (
                    (round(float(value[0]), 6), round(float(value[1]), 6))
                    for value in segment
                )
            )
        )
        geometry = "segment", endpoints
    else:
        bbox = endpoint.get("bbox")
        if not bbox or len(bbox) < 4:
            return None
        geometry = "bbox", tuple(round(float(value), 6) for value in bbox[:4])

    # File identity is intentionally reduced to the basename: temporary
    # export roots are unstable, while distinct blind/buried drill files at
    # one coordinate must not be collapsed into one physical hole.
    source = (
        os.path.basename(str(endpoint.get("file") or "")).lower(),
        _freeze_native_value(endpoint.get("layer_span")),
        str(endpoint.get("plated") if "plated" in endpoint else ""),
        str(endpoint.get("file_function") or "").lower(),
    )
    return "drill_geometry", kind, geometry, diameter, source


def native_finding_key(category, item, raw, layers=None):
    """Build a mapping-independent identity from exported evidence only."""
    raw = raw if isinstance(raw, dict) else {}
    primary_raw = raw.get("primary")
    if not isinstance(primary_raw, dict):
        primary_raw = raw
    related_raw = raw.get("related")
    primary = _native_endpoint_key("", primary_raw, tuple(layers or ()), False)
    related = _native_endpoint_key("", related_raw, tuple(layers or ()), False)
    location = (
        _freeze_native_value(raw.get("point")),
        _freeze_native_value(raw.get("segment")),
        _freeze_native_value(raw.get("bbox")),
    )
    return repr(
        (
            str(category or ""),
            str(item or ""),
            tuple(layers or ()),
            os.path.basename(str(raw.get("file") or "")),
            primary,
            related,
            location,
        )
    )


def physical_layer_measurement(row):
    raw = row.get("raw") or {}
    measurement = {
        "layer": list(row.get("layer") or ()),
        "value": row.get("value"),
        "file": raw.get("file"),
        "geometry_basis": row.get("geometry_basis"),
        "id": row.get("id"),
        "related_id": row.get("related_id"),
    }
    # Preserve the actual per-layer geometry/identity anchors.  The row that
    # supplies the worst clearance can be an inner-layer aperture without X2
    # component attributes, while another observation of the same PTH has an
    # authoritative outer-layer X2 identity.  Keeping both also makes a
    # same-layer multi-contour zone aggregate auditable and re-mappable.
    for name in ("primary", "related"):
        endpoint = raw.get(name)
        if isinstance(endpoint, dict):
            measurement[name] = dict(endpoint)
    return measurement


def physical_layer_measurements(row):
    """Return original observations when an aggregate is folded again."""
    raw = row.get("raw") or {}
    existing = raw.get("per_layer_measurements")
    if isinstance(existing, (tuple, list)) and existing:
        return [
            dict(measurement)
            if isinstance(measurement, dict)
            else measurement
            for measurement in existing
        ]
    return [physical_layer_measurement(row)]


def _mapped_native_result_id(row, raw):
    mapping = raw.get("uuid_mapping") if isinstance(raw, dict) else None
    if not isinstance(mapping, dict) or mapping.get("status") not in (
        "matched",
        "already_mapped",
    ):
        return ""
    return _stable_native_id(mapping.get("id") or row.get("id"))


def _native_endpoint_key(
    item_id,
    endpoint,
    layers=(),
    allow_geometry_cross_layer=False,
):
    endpoint = endpoint if isinstance(endpoint, dict) else {}
    object_id = str(endpoint.get("object_id") or "")
    component = str(endpoint.get("component") or "")
    if object_id:
        return "object", component, object_id
    point = endpoint.get("point")
    if point and len(point) >= 2:
        location = round(float(point[0]), 6), round(float(point[1]), 6)
    else:
        bbox = endpoint.get("bbox")
        if not bbox or len(bbox) < 4:
            stable_id = _stable_native_id(item_id) if not endpoint else ""
            return ("id", stable_id) if stable_id else None
        location = (
            round((float(bbox[0]) + float(bbox[2])) / 2.0, 6),
            round((float(bbox[1]) + float(bbox[3])) / 2.0, 6),
        )
    if allow_geometry_cross_layer and endpoint.get("through_hole"):
        # Copper apertures around one drilled feature may legitimately have
        # different sizes/shapes on outer and inner layers.  The drill centre
        # is the stable physical identity; the retained per-layer evidence
        # carries each layer's exact aperture and clearance measurement.
        return (
            "through_hole",
            location,
            str(endpoint.get("net") or ""),
            str(endpoint.get("component") or ""),
        )
    key = (
        "geometry",
        location,
        str(endpoint.get("aperture_function") or "").lower(),
        str(endpoint.get("net") or ""),
        round(safe_float(endpoint.get("diameter") or endpoint.get("width"), 0.0), 6),
    )
    if allow_geometry_cross_layer:
        return key
    endpoint_layers = tuple(endpoint.get("layer") or layers or ())
    return key + ("layers", endpoint_layers)


def _freeze_native_value(value):
    if isinstance(value, dict):
        return tuple(
            (key, _freeze_native_value(item))
            for key, item in sorted(value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_native_value(item) for item in value)
    if isinstance(value, float):
        return round(value, 9)
    return value


def _geometry_can_cross_layers(endpoint):
    endpoint = endpoint if isinstance(endpoint, dict) else {}
    function = str(endpoint.get("aperture_function") or "").lower()
    return function.startswith("viapad") or bool(
        endpoint.get("through_hole") or endpoint.get("drill_identity")
    )


def _stable_native_id(value):
    text = str(value or "")
    lower = text.lower()
    if not text or lower.endswith((".gbr", ".ger", ".drl", ".xln")):
        return ""
    if "/" in text or "\\" in text:
        return ""
    return text


def _physical_result_is_worse(candidate, current):
    candidate_value = safe_float(candidate.get("value"), None)
    current_value = safe_float(current.get("value"), None)
    if candidate_value is None:
        return False
    if current_value is None or candidate_value < current_value - 1e-12:
        return True
    if abs(candidate_value - current_value) <= 1e-12:
        rank = {"black": 0, "gold": 1, "red": 2}
        return rank.get(candidate.get("color"), 0) > rank.get(
            current.get("color"), 0
        )
    return False


def location_fields(raw):
    raw = raw or {}
    segment = raw.get("segment")
    if segment and len(segment) == 2 and segment[0] and segment[1]:
        return segment_location_fields(segment[0], segment[1])
    point = raw.get("point")
    if point:
        size = safe_float(raw.get("width") or raw.get("diameter"), 0.3) or 0.3
        radius = max(size / 2.0, 0.15)
        start = (point[0] - radius, point[1])
        end = (point[0] + radius, point[1])
        fields = segment_location_fields(start, end)
        fields["cx"] = "{0:.6f}".format(point[0])
        fields["cy"] = "{0:.6f}".format(point[1])
        return fields
    bbox = raw.get("bbox")
    if bbox and len(bbox) == 4:
        return bbox_location_fields(bbox)
    return {}


def bbox_location_fields(bbox):
    left, top, right, bottom = bbox
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    if abs(right - left) >= abs(bottom - top):
        return segment_location_fields((left, center_y), (right, center_y))
    return segment_location_fields((center_x, top), (center_x, bottom))


def segment_location_fields(start, end):
    return {
        "type": 0,
        "et": 0,
        "sx": "{0:.6f}".format(start[0]),
        "sy": "{0:.6f}".format(start[1]),
        "ex": "{0:.6f}".format(end[0]),
        "ey": "{0:.6f}".format(end[1]),
    }


def aggregate_color(colors):
    colors = tuple(colors)
    if "red" in colors:
        return "red"
    if "gold" in colors:
        return "gold"
    return "black"


def safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
