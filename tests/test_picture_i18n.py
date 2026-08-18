import ast
import os
import struct
import unittest
import zipfile

from kicad_dfm.child_frame.diagram_catalog import DIAGRAM_BY_ITEM, DIAGRAM_SPECS
from kicad_dfm.child_frame.diagram_hint import (
    diagram_bitmap_for,
    diagram_name_for,
    diagram_path_for,
    label_text,
    label_width,
    legend_entries,
    translate,
    wrap_text,
)
from kicad_dfm.child_frame.picture_catalog import PICTURE_BY_ITEM
from kicad_dfm.picture import GetImagePath


class PictureI18nTest(unittest.TestCase):
    def test_floating_copper_uses_isolated_copper_diagram(self):
        self.assertEqual("isolated_copper", diagram_name_for("Floating Copper"))

    def test_dangling_tracks_uses_dedicated_diagram_in_both_languages(self):
        for item in ("Dangling Tracks", "悬空端点", "悬空断点"):
            self.assertEqual("dangling_tracks", diagram_name_for(item))

    def test_diagram_catalog_covers_problem_pictures(self):
        self.assertEqual(set(PICTURE_BY_ITEM), set(DIAGRAM_BY_ITEM))
        self.assertEqual(set(PICTURE_BY_ITEM), set(DIAGRAM_SPECS))

    def test_each_problem_picture_has_language_free_diagram_asset(self):
        for picture_name, config in DIAGRAM_BY_ITEM.items():
            self.assertEqual(picture_name + ".png", config["image"])
            path = GetImagePath(os.path.join("diagram", config["image"]))
            self.assertTrue(os.path.exists(path), path)

    def test_diagram_loader_matches_all_aliases(self):
        for picture_name, aliases in PICTURE_BY_ITEM.items():
            for alias in aliases:
                self.assertEqual(picture_name, diagram_name_for(alias), alias)
                self.assertTrue(os.path.exists(diagram_path_for(alias)), alias)

    def test_unknown_diagram_without_fallback_does_not_need_wx(self):
        self.assertIsNone(diagram_bitmap_for("__missing__", fallback=False))

    def test_ui_call_sites_use_diagram_loader_without_language_suffix(self):
        for relative_path in (
            os.path.join("kicad_dfm", "child_frame", "dfm_child_frame.py"),
            os.path.join("kicad_dfm", "manager", "rule_manager_view.py"),
            os.path.join("kicad_dfm", "config.py"),
        ):
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), relative_path)
            with open(path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
            self.assertNotIn("picture_bitmap_for", source)
            self.assertNotIn("picture_suffix", source)
            self.assertNotIn("picture_path", source)
            self.assertNotIn('["picture_path"]', source)
            if relative_path.endswith("config.py"):
                continue
            tree = ast.parse(source)
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "diagram_bitmap_for"
            ]
            self.assertTrue(calls, relative_path)
            for call in calls:
                self.assertLessEqual(len(call.args), 1)
                self.assertFalse(any(keyword.arg == "language_string" for keyword in call.keywords))

    def test_language_free_diagrams_use_standard_canvas(self):
        diagram_names = {config["image"] for config in DIAGRAM_BY_ITEM.values()}
        diagram_names.add("hole_density.png")
        for image_name in diagram_names:
            path = GetImagePath(os.path.join("diagram", image_name))
            self.assertEqual((300, 170), self.png_size(path), path)

    def test_problem_picture_root_has_no_language_specific_assets(self):
        picture_dir = GetImagePath("")
        language_specific = [
            os.path.relpath(os.path.join(root, name), picture_dir)
            for root, _, names in os.walk(picture_dir)
            for name in names
            if name.endswith(("_zh.png", "_en.png"))
        ]
        self.assertEqual([], language_specific)

    def test_active_diagram_directory_has_no_language_specific_assets(self):
        diagram_dir = GetImagePath("diagram")
        language_specific = [
            name
            for name in os.listdir(diagram_dir)
            if name.endswith(("_zh.png", "_en.png"))
        ]
        self.assertEqual([], language_specific)

    def test_dist_zip_has_no_language_specific_picture_assets(self):
        zip_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dist",
            "HQ_DFM_kicad_plugin.zip",
        )
        if not os.path.exists(zip_path):
            self.skipTest("dist zip is not present")
        with zipfile.ZipFile(zip_path) as package:
            language_specific = [
                name
                for name in package.namelist()
                if name.endswith(("_zh.png", "_en.png"))
            ]
        self.assertEqual([], language_specific)

    def test_diagram_catalog_entries_are_complete(self):
        for picture_name, config in DIAGRAM_BY_ITEM.items():
            self.assertEqual(config["aliases"], PICTURE_BY_ITEM[picture_name])
            self.assertTrue(config.get("image"))
            self.assertTrue(config.get("aliases"))
            self.assertTrue(config.get("labels") or config.get("legend"))
            for label in config.get("labels", ()):
                self.assertTrue(label.get("key"))
                self.assertTrue(label.get("symbol"))
                self.assertIn(label.get("align"), ("left", "center", "right"))
                self.assert_point(label.get("anchor"))
                self.assert_point(label.get("label"))
            for key in config.get("legend", ()):
                self.assertTrue(key)
            self.assertTrue(legend_entries(config))

    def test_diagram_legend_keys_are_in_chinese_gettext_catalog(self):
        po_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "kicad_dfm",
            "language",
            "locale",
            "zh_CN",
            "LC_MESSAGES",
            "kicad_hqdfm_plugin.po",
        )
        with open(po_path, "r", encoding="utf-8") as po_file:
            catalog = po_file.read()
        keys = {
            key
            for config in DIAGRAM_BY_ITEM.values()
            for key in config.get("legend", ())
        }
        for key in keys:
            self.assertIn('msgid "{}"'.format(key), catalog)

    def test_diagram_text_has_english_fallback_instead_of_gettext_key(self):
        for config in DIAGRAM_BY_ITEM.values():
            for label in config.get("labels", ()):
                self.assertNotIn("diagram.", translate(label["key"], lambda value: value))
                self.assertNotIn("diagram.", label_text(label, lambda value: value))

    def test_diagram_label_text_uses_current_translator(self):
        label = {"key": "diagram.trace_width", "symbol": "W"}
        self.assertEqual("走线宽度", label_text(label, lambda value: "走线宽度"))

    def test_diagram_label_width_scales_for_small_and_large_images(self):
        self.assertEqual(93, label_width(260))
        self.assertEqual(180, label_width(520))
        self.assertEqual(48, label_width(100))

    def test_wrap_text_splits_chinese_and_long_words(self):
        dc = FakeTextDC()
        for text in ("超长中文说明文字需要换行", "Supercalifragilistic"):
            lines = wrap_text(dc, text, 40)
            self.assertGreater(len(lines), 1)
            self.assertTrue(all(dc.GetTextExtent(line)[0] <= 40 for line in lines))

    def assert_point(self, point):
        self.assertIsInstance(point, tuple)
        self.assertEqual(len(point), 2)
        for value in point:
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1)

    def png_size(self, path):
        with open(path, "rb") as png_file:
            header = png_file.read(24)
        self.assertEqual(b"\x89PNG\r\n\x1a\n", header[:8], path)
        return struct.unpack(">II", header[16:24])


class FakeTextDC:
    def GetTextExtent(self, text):
        return len(text) * 8, 12


if __name__ == "__main__":
    unittest.main()
