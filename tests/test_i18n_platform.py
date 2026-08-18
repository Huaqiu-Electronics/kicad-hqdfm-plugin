import gettext
import os
import unittest
from unittest import mock

from kicad_dfm.core.i18n import DOMAIN, locale_dir, normalize_locale
from kicad_dfm.settings.kicad_setting import KiCadSetting


class I18nPlatformTest(unittest.TestCase):
    def test_chinese_catalog_contains_new_main_window_actions(self):
        translation = gettext.translation(
            DOMAIN,
            locale_dir(),
            languages=["zh_CN"],
            fallback=True,
        )

        self.assertEqual("规则组", translation.gettext("Rule Profile"))
        self.assertEqual("重置图层", translation.gettext("Reset Layers"))
        self.assertEqual("注入 DRC 标记", translation.gettext("Inject DRC Markers"))
        self.assertEqual("清除 DRC 标记", translation.gettext("Clear DRC Markers"))
        self.assertEqual(
            "Gerber 导出检查已在本地完成。",
            translation.gettext("Gerber export check completed locally."),
        )
        self.assertEqual(
            "Gerber/Drill 文件结果没有 PCB 对象定位。",
            translation.gettext("Gerber/Drill file result has no PCB object location."),
        )

    def test_language_normalization_supports_common_kicad_values(self):
        self.assertEqual("zh_CN", normalize_locale("简体中文"))
        self.assertEqual("zh_CN", normalize_locale("zh-CN"))
        self.assertEqual("en", normalize_locale("English"))

    def test_kicad_config_candidates_cover_common_platform_locations(self):
        env = {
            "KICAD_CONFIG_HOME": "/tmp/kicad-config",
            "APPDATA": r"C:\Users\demo\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\demo\AppData\Local",
            "USERPROFILE": r"C:\Users\demo",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            paths = [str(path) for path in KiCadSetting.kicad_config_base_paths()]

        self.assertTrue(any("kicad-config" in path for path in paths))
        self.assertTrue(any("AppData" in path and "kicad" in path.lower() for path in paths))
        self.assertTrue(any(".config" in path and "kicad" in path.lower() for path in paths))
        self.assertTrue(any("Library" in path and "kicad" in path.lower() for path in paths))


if __name__ == "__main__":
    unittest.main()
