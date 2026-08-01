from __future__ import annotations

import json
import logging
import os

import wx


class KiCadSetting:
    @staticmethod
    def read_lang_setting():
        try:
            from pcbnew import GetLanguage

            lang = GetLanguage()
            if lang:
                return lang
        except ImportError:
            pass
        return KiCadSetting.read_lang_setting_from_json()

    @staticmethod
    def read_lang_setting_from_json():
        try:
            import pcbnew

            kicad_setting_path = str(pcbnew.SETTINGS_MANAGER.GetUserSettingsPath())
            logging.info("Kicad setting path %s", kicad_setting_path)
            if kicad_setting_path:
                kicad_common_json = os.path.join(kicad_setting_path, "kicad_common.json")
                with open(kicad_common_json) as f:
                    data = json.loads(f.read())
                    lang: str = data["system"]["language"]
                    if "中文" in lang:
                        return wx.LANGUAGE_CHINESE_SIMPLIFIED
                    if "日本" in lang:
                        return wx.LANGUAGE_JAPANESE_JAPAN
            else:
                logging.error("Empty KiCad config path!")
        except Exception:
            logging.exception("Cannot read the language setting of KiCad!")
        return wx.LANGUAGE_ENGLISH
