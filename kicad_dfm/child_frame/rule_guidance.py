from kicad_dfm.core.i18n import _
from kicad_dfm.core.rule_catalog import RULE_CATALOG, normalize_name
from kicad_dfm.core.rule_contract import rule_key
from kicad_dfm.core.units import mm_to_inches, mm_to_mils


SENTINEL_LIMIT = 900.0
ITEM_ALIASES = {
    "tracemissing": "tracemssing",
}


def rule_metadata(category, result):
    """Return stable catalog metadata for a localized or legacy result row."""
    result = result or {}
    stable_key = str(result.get("rule_key") or "")
    item_name = ITEM_ALIASES.get(
        normalize_name(result.get("item")), normalize_name(result.get("item"))
    )
    for metadata in RULE_CATALOG.get(category, ()):
        if stable_key and stable_key == rule_key(category, metadata.get("item")):
            return metadata
        catalog_item = normalize_name(metadata.get("item"))
        localized_item = normalize_name(_(metadata.get("item") or ""))
        if item_name and item_name in (catalog_item, localized_item):
            return metadata
    return None


def current_rule_text(category, result, unit_mode):
    metadata = rule_metadata(category, result)
    rule = str((result or {}).get("rule") or (metadata or {}).get("rule") or "")
    parts = numeric_rule_parts(rule)
    if not parts:
        return _("Rule: qualitative check")
    unit = (metadata or {}).get("unit", "mm")
    values, display_unit = formatted_rule_values(parts, unit, unit_mode)
    suffix = " {0}".format(display_unit) if display_unit else ""
    return _("Rule: {values}{unit}").format(
        values=", ".join(values),
        unit=suffix,
    )


def current_rule_guidance(category, result, unit_mode):
    metadata = rule_metadata(category, result)
    if metadata is None:
        return _("No rule description is available for this analysis item.")
    description = _(metadata.get("description") or "")
    if metadata.get("description_only"):
        return description
    rule = str((result or {}).get("rule") or metadata.get("rule") or "")
    parts = numeric_rule_parts(rule)
    kind = metadata.get("kind", "")
    if not parts or kind == "boolean":
        return _(
            "{description} This is a qualitative check. Avoid the condition or review every occurrence before production."
        ).format(description=description)

    values, display_unit = formatted_rule_values(parts, metadata.get("unit", "mm"), unit_mode)
    if kind == "range" and len(values) >= 3:
        return _(
            "{description} Values outside {lower} to {upper} are high risk. Recommended range: {recommended} to {upper}."
        ).format(
            description=description,
            lower=with_unit(values[0], display_unit),
            recommended=with_unit(values[1], display_unit),
            upper=with_unit(values[2], display_unit),
        )
    if kind == "max" or (len(parts) >= 2 and parts[0] > parts[1]):
        recommendation = with_unit(values[1] if len(values) > 1 else values[0], display_unit)
        if abs(parts[0]) >= SENTINEL_LIMIT:
            return _("{description} Recommended value: {recommended} or less.").format(
                description=description,
                recommended=recommendation,
            )
        return _(
            "{description} Values above {alarm} are high risk. Recommended value: {recommended} or less."
        ).format(
            description=description,
            alarm=with_unit(values[0], display_unit),
            recommended=recommendation,
        )

    recommendation = with_unit(values[1] if len(values) > 1 else values[0], display_unit)
    if abs(parts[0]) >= SENTINEL_LIMIT:
        return _("{description} Recommended value: {recommended} or greater.").format(
            description=description,
            recommended=recommendation,
        )
    return _(
        "{description} Values below {alarm} are high risk. Recommended value: {recommended} or greater."
    ).format(
        description=description,
        alarm=with_unit(values[0], display_unit),
        recommended=recommendation,
    )


def numeric_rule_parts(rule):
    parts = []
    for value in str(rule or "").split(","):
        try:
            parts.append(float(value))
        except (TypeError, ValueError):
            return ()
    return tuple(parts)


def formatted_rule_values(parts, unit, unit_mode):
    display_unit = display_unit_for(unit, unit_mode)
    return (
        tuple(format_rule_number(convert_rule_value(value, unit, unit_mode)) for value in parts),
        display_unit,
    )


def convert_rule_value(value, unit, unit_mode):
    if abs(value) >= SENTINEL_LIMIT:
        return None
    if unit != "mm":
        return value
    if unit_mode == 0:
        return mm_to_inches(value)
    if unit_mode == 5:
        return mm_to_mils(value)
    return value


def display_unit_for(unit, unit_mode):
    if unit != "mm":
        return _("ratio") if unit == "ratio" else str(unit or "")
    if unit_mode == 0:
        return "inch"
    if unit_mode == 5:
        return "mil"
    return "mm"


def format_rule_number(value):
    if value is None:
        return "∞"
    precision = 6 if 0 < abs(value) < 0.001 else 3
    text = format(value, ".{0}f".format(precision))
    return text.rstrip("0").rstrip(".") or "0"


def with_unit(value, unit):
    return "{0} {1}".format(value, unit) if unit else value
