import json
import os

from .models import DfmIssue, DfmSummary, Location
from .units import safe_float


CHECK_NAMES = (
    "Signal Integrity",
    "Smallest Trace Width",
    "Smallest Trace Spacing",
    "SMD Spacing",
    "Pad size",
    "Hole Size",
    "RingHole",
    "Drill Hole Spacing",
    "Drill to Copper",
    "Copper-to-Board Edge",
    "Hole-to-Board Edge",
    "Special Drill Holes",
    "Holes on SMD Pads",
    "Missing SMask Openings",
    "Solder Mask Analysis",
    "Drill Hole Density",
    "Surface Finish Area",
    "Test Point Count",
)

REMOTE_NAME_ALIASES = {
    "Signal Integrity": ("Electrical Signal", "Electrical Signals"),
    "Smallest Trace Width": ("Trace Width", "Basic Parameters"),
    "Smallest Trace Spacing": ("Trace Spacing", "Line Spacing"),
    "SMD Spacing": ("SMD Pad Spacing",),
    "Pad size": ("Pad Size", "Special Pad"),
    "Hole Size": ("Hole Diameter", "Drill Size", "Drill Diameter"),
    "RingHole": ("Annular Ring Size",),
    "Drill Hole Spacing": ("Drill Spacing",),
    "Copper-to-Board Edge": ("Copper/Edge Gap", "Board Edge Clearance"),
    "Hole-to-Board Edge": ("Hole to Board Edge", "Drill to Edge", "Hole/Edge Gap"),
    "Special Drill Holes": ("Special Drills",),
    "Holes on SMD Pads": ("Drill On Pad",),
    "Missing SMask Openings": ("Missing Mask Opening",),
    "Solder Mask Analysis": ("Soldermask Analysis", "Solder Mask"),
    "Drill Hole Density": ("Basic Parameters",),
    "Surface Finish Area": ("Surface Finish", "Finish Area"),
    "Test Point Count": ("Basic Parameters", "Flying Probe", "Test Points"),
}

STATISTIC_NAMES = ("Drill Hole Density", "Surface Finish Area", "Test Point Count")
RETIRED_CHECK_ITEMS = {
    "Special Drill Holes": ("Via-in-Pad", "盘中孔"),
}


class ParsedDfmJson:
    def __init__(self, compat, issues, summary):
        self.compat = compat
        self.issues = issues
        self.summary = summary


def parse_file(json_path, board=None, transformation=False, translations=None):
    if json_path is None or not isinstance(json_path, str):
        return ParsedDfmJson({}, (), {})
    try:
        with open(json_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except ValueError:
        try:
            os.remove(json_path)
        except OSError:
            pass
        return ParsedDfmJson({}, (), {})
    except OSError:
        return ParsedDfmJson({}, (), {})
    return parse_data(data, board=board, transformation=transformation, translations=translations)


def parse_data(data, board=None, transformation=False, translations=None):
    compat = {}
    issues = []
    summary = {}
    spacing_json = merge_legacy_pad_spacing(
        data,
        find_item_json(data, "Smallest Trace Spacing"),
    )
    smd_json = find_item_json(data, "SMD Spacing")
    if spacing_json is not data.get("Basic Parameters"):
        spacing_json, nested_smd_json = split_smd_spacing_json(spacing_json)
        smd_json = merge_check_json(nested_smd_json, smd_json)
    for name in CHECK_NAMES:
        if name == "Smallest Trace Spacing":
            item_json = spacing_json
        elif name == "SMD Spacing":
            item_json = smd_json
        else:
            item_json = find_item_json(data, name)
        if name == "Smallest Trace Width" and item_json is data.get("Basic Parameters"):
            item_json = statistic_from_basic_parameters(data, "Line Width")
        if name == "Smallest Trace Spacing" and item_json is data.get("Basic Parameters"):
            item_json = statistic_from_basic_parameters(data, "Line Spacing")
        if item_json is None and name == "Test Point Count":
            item_json = test_point_count_from_basic_parameters(data)
        if name == "Drill Hole Density" and item_json is data.get("Basic Parameters"):
            item_json = statistic_from_basic_parameters(data, "Hole Density")
        if name == "Test Point Count" and item_json is data.get("Basic Parameters"):
            item_json = test_point_count_from_basic_parameters(data)
        if item_json is None:
            compat[name] = ""
            summary[name] = DfmSummary(category=name)
            continue
        if name in STATISTIC_NAMES:
            display = item_json.get("display", "")
            item_result = {"display": display}
            compat[name] = item_result
            issue = DfmIssue(
                category=name,
                item=name,
                severity="ok",
                value=display,
                message=display,
                raw=item_json,
            )
            issues.append(issue)
            summary[name] = DfmSummary(category=name, display=display, issues=(issue,))
            continue
        if item_json.get("check") is None:
            if item_json.get("_summary_only"):
                display = item_json.get("display", "")
                compat[name] = {"display": display, "display_inch": item_json.get("display_inch", display), "color": "black"}
                issue = DfmIssue(
                    category=name,
                    item=name,
                    severity="ok",
                    value=display,
                    message=display,
                    raw=item_json,
                )
                issues.append(issue)
                summary[name] = DfmSummary(category=name, display=display, issues=(issue,))
                continue
            if item_json.get("display") is not None and "detected" not in item_json.get("display", ""):
                compat[name] = {"display": None}
                summary[name] = DfmSummary(category=name)
            else:
                compat[name] = ""
                summary[name] = DfmSummary(category=name)
            continue
        item_result, item_issues = parse_check_item(
            name, item_json, board=board, transformation=transformation, translations=translations
        )
        compat[name] = item_result
        issues.extend(item_issues)
        summary[name] = DfmSummary(
            category=name,
            display=item_result.get("display", ""),
            display_inch=item_result.get("display_inch", ""),
            color=item_result.get("color", ""),
            issues=tuple(item_issues),
        )
    return ParsedDfmJson(compat, tuple(issues), summary)


def find_item_json(data, name):
    if not isinstance(data, dict):
        return None
    if name in data:
        return data[name]
    for alias in REMOTE_NAME_ALIASES.get(name, ()):
        if alias in data:
            return data[alias]
    folded_name = normalize_key(name)
    for key, value in data.items():
        if normalize_key(key) == folded_name:
            return value
    for alias in REMOTE_NAME_ALIASES.get(name, ()):
        folded_alias = normalize_key(alias)
        for key, value in data.items():
            if normalize_key(key) == folded_alias:
                return value
    return None


def statistic_from_basic_parameters(data, item_name):
    basic = data.get("Basic Parameters") or {}
    for check in as_list(basic.get("check")):
        for item in as_list(first_present(item_source=check, keys=("info", "items", "result", "results"))):
            if same_name(item.get("item"), item_name):
                values = as_list(first_present(item_source=item, keys=("info", "details", "result", "results")))
                if values:
                    value = str(first_present(item_source=values[0], keys=("val", "value", "display")) or "")
                    return {"display": value, "display_inch": value, "check": None, "_summary_only": True}
    return None


def test_point_count_from_basic_parameters(data):
    return statistic_from_basic_parameters(data, "Flying Probe")


def parse_check_item(name, item_json, board=None, transformation=False, translations=None):
    have_red = False
    have_yellow = False
    info_list = []
    issues = []
    rule_list = []
    for item_check in as_list(item_json.get("check")):
        dfm_show_layer = display_layer_for_check(name, item_check.get("layer", ""))
        for item_info in as_list(first_present(item_source=item_check, keys=("info", "items", "result", "results"))):
            item = canonical_spacing_item(name, item_info.get("item", ""))
            if is_retired_check_item(name, item):
                continue
            if transformation and translations and item.lower() in translations:
                item = translations[item.lower()]
            rule = item_info.get("rule", "")
            append_rule(rule_list, item, rule)
            for detail in as_list(first_present(item_source=item_info, keys=("info", "details", "result", "results"))):
                try:
                    item_layer_list = result_layers(name, dfm_show_layer, detail, board)
                    color = severity_color(rule, detail_value(detail))
                    if color == "red":
                        have_red = True
                    elif color == "gold":
                        have_yellow = True
                    result = parse_result_detail(detail, item, rule, item_layer_list, color)
                    info_list.append({"result": result})
                    issues.extend(
                        DfmIssue(
                            category=name,
                            item=entry.get("item", item),
                            severity=color_to_severity(entry.get("color", color)),
                            layer=entry.get("layer"),
                            value=entry.get("value", ""),
                            rule=entry.get("rule", rule),
                            message=item,
                            location=entry_location(entry),
                            raw=entry,
                        )
                        for entry in result
                    )
                except Exception:
                    continue
    item_result = {"check": info_list}
    if rule_list:
        item_result["_rules"] = rule_list
    if info_list:
        item_result["display"] = item_json.get("display")
        item_result["display_inch"] = item_json.get("display_inch")
    else:
        item_result["display"] = ""
        item_result["display_inch"] = ""
    if have_red:
        item_result["color"] = "red"
    elif have_yellow:
        item_result["color"] = "gold"
    else:
        item_result["color"] = "black"
    return item_result, issues


def display_layer_for_check(name, layer):
    if name == "Drill to Copper" and layer == "Drl":
        return ""
    if layer == "Drl":
        return "Top Layer"
    return layer


def result_layers(name, dfm_show_layer, detail, board=None):
    layers = []
    if dfm_show_layer == "Top Copper":
        layers.append(board.GetLayerName(0) if board is not None else "Top Copper")
    elif dfm_show_layer == "Bot Copper":
        layers.append(board.GetLayerName(2) if board is not None else "Bot Copper")
    elif dfm_show_layer:
        layers.append(dfm_show_layer)
    if dfm_show_layer in ("Bot Paste", "Top Paste"):
        layers.append("Outline")
    for layer in as_list(detail.get("layer")):
        if name == "Drill to Copper" and layer == "Drl":
            continue
        if layer == "Drl":
            layers.append("Top Layer")
        elif dfm_show_layer == "Top Copper":
            layers.append(board.GetLayerName(0) if board is not None else "Top Copper")
        elif dfm_show_layer == "Bot Copper":
            layers.append(board.GetLayerName(2) if board is not None else "Bot Copper")
        else:
            layers.append(layer)
    return layers


def severity_color(rule, value):
    first, second, _, fourth = rule_parts(rule)
    if first == "-" or second == "-":
        return "red"
    if fourth != "1":
        rule1 = safe_float(first, None)
        rule2 = safe_float(second, None)
    else:
        rule1 = percent_or_float(first)
        rule2 = percent_or_float(second)
    actual = safe_float(value, None)
    if rule1 is None or rule2 is None or actual is None:
        return "black"
    if rule1 < rule2:
        if actual < rule1:
            return "red"
        if rule1 < actual < rule2:
            return "gold"
        return "black"
    if actual > rule1:
        return "red"
    if rule2 < actual < rule1:
        return "gold"
    return "black"


def rule_parts(rule):
    values = str(rule or "").split(",")
    values.extend([""] * (4 - len(values)))
    return values[0], values[1], values[2], values[3]


def percent_or_float(value):
    value = str(value)
    if "%" in value:
        parsed = safe_float(value.strip("%"), None)
        return parsed / 100.0 if parsed is not None else None
    return safe_float(value, None)


def color_to_severity(color):
    if color == "red":
        return "error"
    if color == "gold":
        return "warning"
    return "ok"


def parse_result_detail(detail, item, rule, layers, color):
    result_type = detail_type(detail)
    if result_type == 0:
        geometries = as_list(geometry_result(detail))
        if not geometries:
            entry = common_entry(detail, item, rule, layers, color)
            entry["type"] = 9
            return [entry]
        return [entry_from_geometry(geometry, detail, item, rule, layers, color) for geometry in geometries]
    if result_type == 2:
        entry = common_entry(detail, item, rule, layers, color)
        coord = ((geometry_result(detail) or {}).get("coord") or {})
        spt = coord.get("spt") or {}
        ept = coord.get("ept") or {}
        entry["type"] = 2
        entry["sx"] = spt.get("x")
        entry["sy"] = spt.get("y")
        entry["ex"] = ept.get("x")
        entry["ey"] = ept.get("y")
        return [entry]
    if result_type == 3:
        entry = common_entry(detail, item, rule, layers, color)
        entry["type"] = 3
        entry["result"] = geometry_result(detail) or {}
        return [entry]
    entry = common_entry(detail, item, rule, layers, color)
    entry["type"] = 9
    entry["result"] = as_list(geometry_result(detail))
    return [entry]


def entry_from_geometry(geometry, detail, item, rule, layers, color):
    entry = common_entry(detail, item, rule, layers, color)
    entry["type"] = 0
    entry["et"] = geometry.get("et")
    coord = geometry.get("coord") or geometry.get("geometry") or {}
    if entry["et"] == 0:
        copy_point_fields(entry, coord, include_center=False)
    elif entry["et"] == 1:
        copy_point_fields(entry, coord, include_center=True)
    else:
        cpt = coord.get("cpt") or {}
        entry["cx"] = cpt.get("x")
        entry["cy"] = cpt.get("y")
    return entry


def common_entry(detail, item, rule, layers, color):
    return {
        "item": item,
        "rule": rule,
        "layer": layers,
        "value": detail_value(detail),
        "type": 0,
        "color": color,
    }


def copy_point_fields(entry, coord, include_center=False):
    spt = coord.get("spt") or {}
    ept = coord.get("ept") or {}
    entry["sx"] = spt.get("x")
    entry["sy"] = spt.get("y")
    entry["ex"] = ept.get("x")
    entry["ey"] = ept.get("y")
    if include_center:
        cpt = coord.get("cpt") or {}
        entry["cx"] = cpt.get("x")
        entry["cy"] = cpt.get("y")


def entry_location(entry):
    return Location(
        item_type=str(entry.get("type", "")),
        layer=entry.get("layer"),
        x_nm=maybe_mm_to_nm(entry.get("cx") or entry.get("sx")),
        y_nm=maybe_mm_to_nm(entry.get("cy") or entry.get("sy")),
    )


def maybe_mm_to_nm(value):
    if value is None:
        return None
    return int(round(safe_float(value) * 1000000))


def normalize_key(value):
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def same_name(value, expected):
    return normalize_key(value) == normalize_key(expected)


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def first_present(item_source, keys):
    if not isinstance(item_source, dict):
        return None
    for key in keys:
        value = item_source.get(key)
        if value is not None:
            return value
    return None


def detail_value(detail):
    return first_present(item_source=detail, keys=("val", "value", "actual", "display"))


def geometry_result(detail):
    return first_present(item_source=detail, keys=("result", "results", "geometry", "geometries", "coord"))


def detail_type(detail):
    try:
        return int(detail.get("type"))
    except (TypeError, ValueError):
        return detail.get("type")


def append_rule(rule_list, item, rule):
    if not item or rule is None:
        return
    rule_item = {item: rule}
    if rule_item not in rule_list:
        rule_list.append(rule_item)


def merge_legacy_pad_spacing(data, spacing_json):
    """Fold the remote service's former Pad Spacing group into spacing."""
    legacy = find_item_json(data, "Pad Spacing")
    if legacy is None:
        # Pad Spacing is no longer an active check name, so find it explicitly.
        legacy = data.get("Pad Spacing")
    if not isinstance(legacy, dict):
        return spacing_json
    merged = dict(spacing_json or {})
    checks = as_list(merged.get("check")) + as_list(legacy.get("check"))
    if checks:
        merged["check"] = checks
    if merged.get("display") is None:
        merged["display"] = legacy.get("display")
    if merged.get("display_inch") is None:
        merged["display_inch"] = legacy.get("display_inch")
    return merged


def split_smd_spacing_json(spacing_json):
    """Split legacy nested SMD rows from the general spacing payload."""
    if not isinstance(spacing_json, dict) or spacing_json.get("check") is None:
        return spacing_json, None
    general_checks = []
    smd_checks = []
    for check in as_list(spacing_json.get("check")):
        if not isinstance(check, dict):
            continue
        container_key = next(
            (
                key
                for key in ("info", "items", "result", "results")
                if check.get(key) is not None
            ),
            None,
        )
        if container_key is None:
            general_checks.append(check)
            continue
        general_items = []
        smd_items = []
        for item_info in as_list(check.get(container_key)):
            if not isinstance(item_info, dict):
                continue
            item = item_info.get("item", "")
            if same_name(item, "SMD Pad Spacing") or same_name(item, "SMD Spacing"):
                smd_items.append(item_info)
            else:
                general_items.append(item_info)
        if general_items:
            general_check = dict(check)
            general_check[container_key] = general_items
            general_checks.append(general_check)
        if smd_items:
            smd_check = dict(check)
            smd_check[container_key] = smd_items
            smd_checks.append(smd_check)

    general = dict(spacing_json)
    general["check"] = general_checks
    if not smd_checks:
        return general, None
    smd = {
        "check": smd_checks,
        "display": spacing_json.get("display"),
        "display_inch": spacing_json.get("display_inch"),
    }
    return general, smd


def merge_check_json(left, right):
    """Merge two compatible remote check payloads, preferring explicit right metadata."""
    if not isinstance(left, dict):
        return right
    if not isinstance(right, dict):
        return left
    merged = dict(left)
    merged["check"] = as_list(left.get("check")) + as_list(right.get("check"))
    for key in ("display", "display_inch"):
        if right.get(key) is not None:
            merged[key] = right.get(key)
    return merged


def canonical_spacing_item(category, item):
    if category == "Smallest Trace Spacing" and same_name(item, "Pad Spacing"):
        return "Pad-to-Pad Spacing"
    if category == "SMD Spacing" and same_name(item, "SMD Spacing"):
        return "SMD Pad Spacing"
    return item


def is_retired_check_item(category, item):
    return any(
        same_name(item, retired_item)
        for retired_item in RETIRED_CHECK_ITEMS.get(category, ())
    )
