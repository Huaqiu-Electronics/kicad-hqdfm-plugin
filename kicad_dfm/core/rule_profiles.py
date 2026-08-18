import copy
import json
import os

from .paths import resource_path
from .rule_catalog import RULE_CATALOG


DEFAULT_PROFILE_ID = "standard"

PROFILE_DEFINITIONS = (
    {
        "id": "economy",
        "name": "Economy",
        "display": "Basic",
        "description": "Relaxed limits for common low-cost prototype and standard production.",
        "factor": 1.25,
    },
    {
        "id": "standard",
        "name": "Standard",
        "display": "Standard",
        "description": "Balanced default limits for typical reliable fabrication.",
        "factor": 1.0,
    },
    {
        "id": "precision",
        "name": "Precision",
        "display": "Advanced",
        "description": "Tighter limits for finer features and higher-end fabrication.",
        "factor": 0.8,
    },
)


PROFILE_LABELS = {profile["id"]: profile["display"] for profile in PROFILE_DEFINITIONS}
PROFILE_SCALE_AUTO = "auto"
PROFILE_SCALE_FIXED = "fixed"


def profiles_path():
    return resource_path("settings", "rule_profiles.json")


def default_profiles():
    profiles = {}
    for profile in PROFILE_DEFINITIONS:
        rules = scaled_rules(profile["factor"])
        profiles[profile["id"]] = {
            "name": profile["name"],
            "display": profile["display"],
            "description": profile["description"],
            "rules": rules,
        }
    return profiles


def load_profiles(path=None):
    path = path or profiles_path()
    profiles = default_profiles()
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError):
        return profiles
    if not isinstance(data, dict):
        return profiles
    for profile_id, profile in data.items():
        if profile_id not in profiles or not isinstance(profile, dict):
            continue
        rules = profile.get("rules")
        if isinstance(rules, dict):
            profiles[profile_id]["rules"] = merge_rules(profiles[profile_id]["rules"], migrate_legacy_rules(rules))
    return profiles


def save_profiles(profiles, path=None):
    path = path or profiles_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(profiles, fp, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def profile_choices(translate=None, label_map=None):
    translate = translate or (lambda value: value)
    label_map = label_map or {}
    profiles = load_profiles()
    return [
        (profile_id, translate(profile_label(profiles[profile_id]["display"], label_map)))
        for profile_id in profile_order(profiles)
    ]


def profile_label(label, label_map=None):
    label_map = label_map or {}
    return label_map.get(str(label).lower(), label)


def rule_label(label, label_map=None, translate=None):
    """Return a localized rule category or item without changing its stored key."""
    label_map = label_map or {}
    text = str(label or "")
    if text in label_map:
        return label_map[text]
    if text.lower() in label_map:
        return label_map[text.lower()]
    return (translate or (lambda value: value))(text)


def profile_order(profiles):
    known = [profile["id"] for profile in PROFILE_DEFINITIONS if profile["id"] in profiles]
    extra = sorted(profile_id for profile_id in profiles if profile_id not in known)
    return known + extra


def selected_profile_id(settings):
    profile_id = str((settings or {}).get("rule_profile") or DEFAULT_PROFILE_ID)
    profiles = load_profiles()
    if profile_id in profiles:
        return profile_id
    return DEFAULT_PROFILE_ID


def selected_rules(settings):
    profiles = load_profiles()
    return profiles[selected_profile_id(settings)]["rules"]


def rules_for_profile(profile_id):
    profiles = load_profiles()
    profile = profiles.get(profile_id) or profiles[DEFAULT_PROFILE_ID]
    return profile["rules"]


def update_profile_rules(profile_id, rules):
    profiles = load_profiles()
    if profile_id not in profiles:
        profile_id = DEFAULT_PROFILE_ID
    # Keep unknown/missing rule fields from the bundled defaults while saving user thresholds.
    profiles[profile_id]["rules"] = merge_rules(
        profiles[profile_id]["rules"],
        migrate_legacy_rules(rules),
    )
    save_profiles(profiles)
    return profiles[profile_id]["rules"]


def merge_rules(base_rules, override_rules):
    merged = copy.deepcopy(base_rules)
    for category, rules in (override_rules or {}).items():
        if not isinstance(rules, (list, tuple)):
            continue
        by_name = {normalize_name(rule.get("item")): rule for rule in merged.get(category, ())}
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            item = rule.get("item")
            rule_text = rule.get("rule")
            if not item or rule_text is None:
                continue
            key = normalize_name(item)
            if key in by_name:
                by_name[key]["rule"] = str(rule_text)
            else:
                by_name[key] = {"item": item, "rule": str(rule_text), "unit": rule.get("unit", "mm")}
        merged[category] = tuple(by_name.values())
    return merged


def migrate_legacy_rules(rules):
    """Move former spacing rules to their canonical top-level categories."""
    migrated = copy.deepcopy(rules or {})
    legacy_hole_rules = migrated.pop("Hole Diameter", ())
    if legacy_hole_rules and "Hole Size" not in migrated:
        migrated["Hole Size"] = legacy_hole_rules
    hole_size_rules = migrated.get("Hole Size", ())
    if isinstance(hole_size_rules, (list, tuple)):
        retired_hole_rules = {
            normalize_name("Square Hole Size"),
            normalize_name("方孔尺寸"),
            normalize_name("放孔尺寸"),
        }
        smallest_slot_names = {
            normalize_name("Smallest Slot Width"),
            normalize_name("最小槽宽"),
        }
        legacy_smallest_slot_rules = {
            (0.3, 0.4, 0.6),
            (0.45, 0.6, 6.0),
            (0.562508, 0.750011, 7.50001),
            (0.36, 0.48, 4.8),
        }
        slot_aspect_names = {
            normalize_name("Slot Aspect Ratio"),
            normalize_name("槽长宽比"),
        }
        retained_hole_rules = []
        for rule in hole_size_rules:
            if not isinstance(rule, dict):
                retained_hole_rules.append(rule)
                continue
            item_key = normalize_name(rule.get("item"))
            if item_key in retired_hole_rules:
                continue
            moved = dict(rule)
            if item_key in smallest_slot_names:
                moved["item"] = "Smallest Slot Width"
                try:
                    values = tuple(
                        round(float(part), 6)
                        for part in str(moved.get("rule") or "").split(",")
                    )
                except (TypeError, ValueError):
                    values = ()
                if values in legacy_smallest_slot_rules:
                    moved["rule"] = "0.450088,0.599948,5.999988"
            elif item_key in slot_aspect_names:
                moved["item"] = "Slot Aspect Ratio"
                try:
                    values = tuple(
                        round(float(part), 6)
                        for part in str(moved.get("rule") or "").split(",")
                    )
                except (TypeError, ValueError):
                    values = ()
                if values in {
                    (1.5, 2.0, 2.0),
                    (1.499997, 1.999996, 1.999996),
                }:
                    moved["rule"] = "1.500000,2.000000,999.000000"
            retained_hole_rules.append(moved)
        migrated["Hole Size"] = tuple(retained_hole_rules)
    migrated.pop("Hatched Copper Pour", None)
    special_drill_rules = migrated.get("Special Drill Holes", ())
    if isinstance(special_drill_rules, (list, tuple)):
        retired_special_drills = {
            normalize_name("Via-in-Pad"),
            normalize_name("盘中孔"),
        }
        migrated["Special Drill Holes"] = tuple(
            rule
            for rule in special_drill_rules
            if not isinstance(rule, dict)
            or normalize_name(rule.get("item")) not in retired_special_drills
        )
    smd_item_key = normalize_name("SMD Pad Spacing")
    moved_smd_rules = []
    spacing_rules = migrated.get("Smallest Trace Spacing", ())
    if isinstance(spacing_rules, (list, tuple)):
        retained_spacing_rules = []
        for rule in spacing_rules:
            if not isinstance(rule, dict):
                retained_spacing_rules.append(rule)
                continue
            item_key = normalize_name(rule.get("item"))
            if item_key == normalize_name("Track-to-Copper Spacing"):
                continue
            if item_key == smd_item_key:
                moved_smd_rules.append(dict(rule))
                continue
            retained_spacing_rules.append(rule)
        migrated["Smallest Trace Spacing"] = tuple(retained_spacing_rules)
    legacy = migrated.pop("Pad Spacing", ())
    target = list(migrated.get("Smallest Trace Spacing", ()))
    positions = {normalize_name(rule.get("item")): index for index, rule in enumerate(target) if isinstance(rule, dict)}
    if isinstance(legacy, (list, tuple)):
        for rule in legacy:
            if not isinstance(rule, dict):
                continue
            moved = dict(rule)
            key = normalize_name(moved.get("item"))
            if key == smd_item_key:
                moved_smd_rules.append(moved)
                continue
            if key == normalize_name("Pad Spacing"):
                moved["item"] = "Pad-to-Pad Spacing"
                key = normalize_name(moved["item"])
            if not key:
                continue
            if key in positions:
                target[positions[key]] = moved
            else:
                positions[key] = len(target)
                target.append(moved)
    migrated["Smallest Trace Spacing"] = tuple(target)

    legacy_smd = migrated.pop("SMD Pad Spacing", ())
    if isinstance(legacy_smd, (list, tuple)):
        moved_smd_rules.extend(
            dict(rule) for rule in legacy_smd if isinstance(rule, dict)
        )
    explicit_smd = migrated.get("SMD Spacing", ())
    smd_target = []
    smd_positions = {}
    for rule in tuple(moved_smd_rules) + tuple(
        explicit_smd if isinstance(explicit_smd, (list, tuple)) else ()
    ):
        if not isinstance(rule, dict):
            continue
        moved = dict(rule)
        item_key = normalize_name(moved.get("item"))
        if item_key in (normalize_name("SMD Spacing"), smd_item_key):
            moved["item"] = "SMD Pad Spacing"
            item_key = smd_item_key
        if not item_key:
            continue
        if item_key in smd_positions:
            smd_target[smd_positions[item_key]] = moved
        else:
            smd_positions[item_key] = len(smd_target)
            smd_target.append(moved)
    if smd_target:
        migrated["SMD Spacing"] = tuple(smd_target)
    return migrated


def scaled_rules(factor):
    rules = copy.deepcopy(RULE_CATALOG)
    for category, entries in rules.items():
        scaled_entries = []
        for entry in entries:
            entry = dict(entry)
            entry["rule"] = scale_rule(
                entry.get("rule", ""),
                factor,
                entry.get("kind", ""),
                entry.get("profile_scale", PROFILE_SCALE_AUTO),
            )
            scaled_entries.append(entry)
        rules[category] = tuple(scaled_entries)
    return rules


def scale_rule(rule, factor, kind, profile_scale=PROFILE_SCALE_AUTO):
    if profile_scale == PROFILE_SCALE_FIXED:
        return rule
    if not rule or "-" in str(rule):
        return rule
    parts = str(rule).split(",")
    scaled = []
    for index, part in enumerate(parts):
        try:
            value = float(part)
        except ValueError:
            scaled.append(part)
            continue
        if value >= 900:
            scaled.append(part)
            continue
        if kind == "max":
            value = value / factor
        elif kind == "range":
            if index == 0:
                value = value * factor
            else:
                value = value / factor
        else:
            value = value * factor
        scaled.append("{0:.6f}".format(value))
    return ",".join(scaled)


def normalize_name(value):
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())
