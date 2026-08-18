import json
import os
import logging
import locale
import re
from pathlib import Path


class KiCadSetting:
    @staticmethod
    def read_lang_setting():
        lang = KiCadSetting.read_lang_setting_from_json()
        if lang:
            return KiCadSetting.normalize_language(lang)
        return KiCadSetting.read_system_language()

    @staticmethod
    def normalize_language(lang):
        value = str(lang or "").strip()
        lower_value = value.lower().replace("-", "_")
        if not value or lower_value in ("default", "system", "auto"):
            return KiCadSetting.read_system_language()
        return KiCadSetting.normalize_language_value(value) or "English"

    @staticmethod
    def read_system_language():
        for lang in KiCadSetting.system_language_candidates():
            if lang:
                normalized = KiCadSetting.normalize_language_value(lang)
                if normalized:
                    return normalized
        return "English"

    @staticmethod
    def normalize_language_value(lang):
        value = str(lang or "").strip()
        lower_value = value.lower().replace("-", "_")
        if lower_value.startswith("zh") or "中文" in value or "chinese" in lower_value:
            return "简体中文"
        if lower_value.startswith("en") or "english" in lower_value or "英语" in value or "英文" in value:
            return "English"
        return ""

    @staticmethod
    def system_language_candidates():
        candidates = []
        try:
            candidates.extend(locale.getlocale())
        except Exception:
            pass
        try:
            candidates.extend(locale.getdefaultlocale())
        except Exception:
            pass
        try:
            candidates.append(locale.getlocale(locale.LC_MESSAGES)[0])
        except Exception:
            pass
        for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            candidates.append(os.environ.get(name, ""))
        return candidates

    @staticmethod
    def read_lang_setting_from_json():
        for kicad_common_json in KiCadSetting.kicad_common_json_candidates():
            try:
                with open(kicad_common_json, encoding="utf-8") as f:
                    data = json.load(f)
                lang = data.get("system", {}).get("language", "")
                if lang:
                    logging.info(f"Kicad language setting path {kicad_common_json}")
                    return lang
            except Exception:
                pass
        logging.info("Cannot read the language setting of KiCad; falling back to system language.")
        return ""

    @staticmethod
    def kicad_common_json_candidates():
        paths = []
        for base in KiCadSetting.kicad_config_base_paths():
            if base:
                paths.extend(KiCadSetting.versioned_kicad_common_json_paths(Path(base)))

        seen = set()
        for path in paths:
            path = Path(path)
            if path in seen:
                continue
            seen.add(path)
            yield path

    @staticmethod
    def kicad_config_base_paths():
        home = Path.home()
        bases = [
            KiCadSetting.path_from_env("KICAD_CONFIG_HOME"),
            KiCadSetting.path_from_env("APPDATA", "kicad"),
            KiCadSetting.path_from_env("LOCALAPPDATA", "kicad"),
            home / "AppData" / "Roaming" / "kicad",
            home / ".config" / "kicad",
            home / "Library" / "Preferences" / "kicad",
            KiCadSetting.documents_kicad_path(),
        ]
        return [base for base in bases if base]

    @staticmethod
    def path_from_env(name, *children):
        value = os.environ.get(name)
        if not value:
            return None
        path = Path(value)
        for child in children:
            path /= child
        return path

    @staticmethod
    def versioned_kicad_common_json_paths(base):
        candidates = []
        version = KiCadSetting.plugin_kicad_version()
        if version:
            candidates.append(base / version / "kicad_common.json")
        candidates.append(base / "kicad_common.json")
        if base.exists():
            candidates.extend(
                path / "kicad_common.json"
                for path in sorted(
                    base.iterdir(),
                    key=KiCadSetting.version_sort_key,
                    reverse=True,
                )
                if path.is_dir() and KiCadSetting.is_version_dir(path)
            )
        return candidates

    @staticmethod
    def version_sort_key(path):
        parts = [int(part) for part in re.findall(r"\d+", path.name)]
        return parts or [-1]

    @staticmethod
    def is_version_dir(path):
        return bool(re.match(r"^\d+(?:\.\d+)*$", path.name))

    @staticmethod
    def plugin_kicad_version():
        parts = Path(__file__).parts
        for index, part in enumerate(parts[:-1]):
            if part.lower() == "kicad":
                candidate = parts[index + 1]
                if candidate[:1].isdigit():
                    return candidate
        return ""

    @staticmethod
    def documents_kicad_path():
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            return Path(user_profile) / "Documents" / "KiCad"
        return Path.home() / "Documents" / "KiCad"
