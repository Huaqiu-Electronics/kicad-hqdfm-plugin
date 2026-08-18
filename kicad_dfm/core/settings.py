import json
import os

from .paths import resource_path


DEFAULT_SUMMARY_COLUMN_WIDTHS = (250, 230, 90)
MIN_SUMMARY_COLUMN_WIDTH = 32
MAX_SUMMARY_COLUMN_WIDTH = 4096


DEFAULT_SETTINGS = {
    "region": "auto",
    "timeout": 20,
    "unit": "mm",
    "keep_export_package": False,
    "auto_locate": True,
    "rule_profile": "standard",
    "summary_column_widths": list(DEFAULT_SUMMARY_COLUMN_WIDTHS),
}


def settings_path():
    return resource_path("settings", "settings.json")


def default_settings():
    result = DEFAULT_SETTINGS.copy()
    result["summary_column_widths"] = list(DEFAULT_SUMMARY_COLUMN_WIDTHS)
    return result


def load_settings(path=None):
    path = path or settings_path()
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            return default_settings()
    except (OSError, ValueError):
        return default_settings()
    result = default_settings()
    result.update({key: data[key] for key in DEFAULT_SETTINGS if key in data})
    result["summary_column_widths"] = normalize_summary_column_widths(
        result.get("summary_column_widths")
    )
    return result


def save_settings(settings, path=None):
    path = path or settings_path()
    data = default_settings()
    data.update({key: settings[key] for key in DEFAULT_SETTINGS if key in settings})
    data["summary_column_widths"] = normalize_summary_column_widths(
        data.get("summary_column_widths")
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def normalize_summary_column_widths(value):
    if not isinstance(value, (list, tuple)) or len(value) != len(
        DEFAULT_SUMMARY_COLUMN_WIDTHS
    ):
        return list(DEFAULT_SUMMARY_COLUMN_WIDTHS)

    widths = []
    for raw_width, default_width in zip(value, DEFAULT_SUMMARY_COLUMN_WIDTHS):
        try:
            width = int(round(float(raw_width)))
        except (TypeError, ValueError, OverflowError):
            width = default_width
        if not MIN_SUMMARY_COLUMN_WIDTH <= width <= MAX_SUMMARY_COLUMN_WIDTH:
            width = default_width
        widths.append(width)
    return widths
