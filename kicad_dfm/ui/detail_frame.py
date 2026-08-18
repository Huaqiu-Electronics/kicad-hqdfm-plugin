import csv


STATISTIC_ITEMS = ("Drill Hole Density", "Surface Finish Area", "Test Point Count")


def is_statistic_item(name):
    return name in STATISTIC_ITEMS


def statistic_display(analysis_result, name, empty_text=""):
    item = analysis_result.get(name, "") if analysis_result else ""
    if isinstance(item, dict):
        return str(item.get("display", empty_text))
    return empty_text


def flatten_results(detail_result):
    rows = []
    if not detail_result or detail_result == "":
        return rows
    for group in detail_result.get("check") or ():
        result = group.get("result", [])
        if isinstance(result, dict):
            result = [result]
        rows.extend(result)
    return rows


def filter_results(rows, search="", layers=None, types=None, severities=None):
    search = (search or "").lower()
    layers = set(layers or ())
    types = set(types or ())
    severities = set(severities or ())
    filtered = []
    for row in rows:
        row_text = " ".join(str(value) for value in row.values()).lower()
        row_layers = set(row.get("layer") or ())
        severity = color_to_severity(row.get("color", "black"))
        if search and search not in row_text:
            continue
        if layers and not (row_layers & layers):
            continue
        if types and row.get("item") not in types:
            continue
        if severities and severity not in severities:
            continue
        filtered.append(row)
    return filtered


def copy_text(row):
    return "\t".join(
        str(row.get(key, ""))
        for key in ("item", "value", "rule", "color", "layer")
    )


def export_csv(rows, path):
    fieldnames = ("item", "value", "rule", "color", "layer")
    with open(path, "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return path


def color_to_severity(color):
    if color == "red":
        return "error"
    if color == "gold":
        return "warning"
    return "ok"
