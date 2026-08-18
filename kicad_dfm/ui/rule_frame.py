from kicad_dfm.core.rule_catalog import RULE_CATALOG, default_rule_items
from kicad_dfm.services.offline_analysis import IMPLEMENTED_LOCAL_CATEGORIES


def build_rule_rows(result_json, unit, transform, translate=None):
    translate = translate or (lambda value: value)
    rows = []
    number = 0
    unit_name = unit_name_for(unit)
    for item, rules in merged_rule_map(result_json).items():
        for result in rules:
            number += 1
            sub_item = list(result.keys())[0]
            rule_unit = rule_unit_for(item, sub_item)
            rows.append(
                [
                    str(number),
                    translate(item),
                    translate(sub_item),
                    dispose_rule(
                        result[sub_item],
                        lambda value, source_unit=rule_unit: transform_rule_value(
                            value, source_unit, transform
                        ),
                    ),
                    unit_name if rule_unit == "mm" else rule_unit,
                ]
            )
    return rows


def rules_to_result_json(rules):
    result = {}
    for category, entries in (rules or {}).items():
        result[category] = [{entry["item"]: entry["rule"]} for entry in entries if entry.get("item")]
    return result


def merged_rule_map(result_json):
    merged = {}
    categories = list(default_categories())
    for item in result_json or {}:
        if item not in categories:
            categories.append(item)
    for item in categories:
        rules = []
        for sub_item, rule in default_rule_items(item):
            append_rule(rules, sub_item, rule)
        for result in (result_json or {}).get(item, ()):
            if not result:
                continue
            sub_item = list(result.keys())[0]
            append_rule(rules, sub_item, result[sub_item])
        if rules:
            merged[item] = rules
    return merged


def default_categories():
    return IMPLEMENTED_LOCAL_CATEGORIES


def append_rule(rules, sub_item, rule):
    normalized = normalize_name(sub_item)
    for index, existing in enumerate(rules):
        existing_name = list(existing.keys())[0]
        if normalize_name(existing_name) == normalized:
            rules[index] = {sub_item: rule}
            return
    rules.append({sub_item: rule})


def normalize_name(value):
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def unit_name_for(unit):
    if unit == 0:
        return "inch"
    if unit == 5:
        return "mil"
    return "mm"


def rule_unit_for(category, item):
    normalized = normalize_name(item)
    for metadata in RULE_CATALOG.get(category, ()):
        if normalize_name(metadata.get("item")) == normalized:
            return str(metadata.get("unit") or "mm")
    return "mm"


def transform_rule_value(value, rule_unit, transform):
    if value == "-" or rule_unit != "mm":
        return value
    return transform(value)


def dispose_rule(rule, transform):
    parts = str(rule or "").split(",")
    parts.extend([""] * (3 - len(parts)))
    return ",".join(transform(part) for part in parts[:3])
