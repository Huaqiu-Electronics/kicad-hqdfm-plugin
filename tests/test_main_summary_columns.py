from pathlib import Path
import tempfile
import unittest

from kicad_dfm.core.settings import DEFAULT_SUMMARY_COLUMN_WIDTHS
from kicad_dfm.core.settings import load_settings
from kicad_dfm.core.settings import normalize_summary_column_widths
from kicad_dfm.core.settings import save_settings
from kicad_dfm.ui.main_frame import HQ_DFM_CN_URL
from kicad_dfm.ui.main_frame import HQ_DFM_EN_URL
from kicad_dfm.ui.main_frame import SUMMARY_ITEMS
from kicad_dfm.ui.main_frame import hq_dfm_url


ROOT = Path(__file__).resolve().parents[1]


class MainSummaryColumnsTest(unittest.TestCase):
    def test_main_window_links_to_huaqiu_dfm(self):
        view = (
            ROOT / "kicad_dfm" / "dfm_maindialog" / "dfm_maindialog_view.py"
        ).read_text(encoding="utf-8")

        self.assertEqual("https://dfm.hqpcb.com", HQ_DFM_CN_URL)
        self.assertEqual("https://www.nextpcb.com/dfm", HQ_DFM_EN_URL)
        for language in ("简体中文", "zh_CN", "Chinese", "Default", ""):
            self.assertEqual(HQ_DFM_CN_URL, hq_dfm_url(language), language)
        for language in ("English", "en", "en_US"):
            self.assertEqual(HQ_DFM_EN_URL, hq_dfm_url(language), language)
        self.assertIn("wx.adv.HyperlinkCtrl", view)
        self.assertIn("_(\"For more advanced DFM checks, use\")", view)
        self.assertIn("_(\"Huaqiu DFM\")", view)
        self.assertIn("hq_dfm_url(language)", view)

    def test_gerber_export_is_not_a_fixed_summary_row(self):
        self.assertNotIn("Gerber Export", SUMMARY_ITEMS)

    def test_summary_headers_are_visible_and_resizable(self):
        generated_ui = (
            ROOT / "kicad_dfm" / "dfm_maindialog" / "ui_dfm_maindialog.py"
        ).read_text(encoding="utf-8")
        form = (
            ROOT / "kicad_dfm" / "dfm_maindialog" / "ui_dfm_maindialog.fbp"
        ).read_text(encoding="utf-8")
        view = (
            ROOT / "kicad_dfm" / "dfm_maindialog" / "dfm_maindialog_view.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("DV_NO_HEADER", generated_ui)
        self.assertNotIn("wxDV_NO_HEADER", form)
        self.assertIn('(_("Rule"), 0, initial_widths[0])', view)
        self.assertIn('(_("Value"), 1, initial_widths[1])', view)
        self.assertEqual(2, view.count("flags=dv.DATAVIEW_COL_RESIZABLE"))

    def test_main_actions_are_single_row_and_marker_controls_are_hidden(self):
        generated_ui = (
            ROOT / "kicad_dfm" / "dfm_maindialog" / "ui_dfm_maindialog.py"
        ).read_text(encoding="utf-8")

        self.assertIn("wx.FlexGridSizer(1, 4, 0, 8)", generated_ui)
        self.assertIn('_("Reset Layers")', generated_ui)
        self.assertIn("self.inject_drc_markers_button.Hide()", generated_ui)
        self.assertIn("self.clear_drc_markers_button.Hide()", generated_ui)
        self.assertNotIn(
            "self.action_button_sizer.Add(self.inject_drc_markers_button",
            generated_ui,
        )
        self.assertNotIn(
            "self.action_button_sizer.Add(self.clear_drc_markers_button",
            generated_ui,
        )

    def test_check_column_uses_compact_centered_action_renderer(self):
        renderer = (
            ROOT / "kicad_dfm" / "utils" / "CustomRenderer.py"
        ).read_text(encoding="utf-8")

        self.assertEqual(90, DEFAULT_SUMMARY_COLUMN_WIDTHS[2])
        self.assertIn("BUTTON_WIDTH_DIP = 82", renderer)
        self.assertIn("(button_rect.width - button_width) // 2", renderer)

    def test_dpi_refresh_does_not_reset_user_column_widths(self):
        view = (
            ROOT / "kicad_dfm" / "dfm_maindialog" / "dfm_maindialog_view.py"
        ).read_text(encoding="utf-8")
        refresh_method = view.split("    def refresh_dpi_layout(self):", 1)[1].split(
            "    def current_dpi_scale(self):", 1
        )[0]

        self.assertNotIn(".SetWidth(", refresh_method)

    def test_summary_column_widths_round_trip_through_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "settings.json")
            save_settings({"summary_column_widths": [245, 180, 85]}, path)

            loaded = load_settings(path)

        self.assertEqual([245, 180, 85], loaded["summary_column_widths"])

    def test_invalid_summary_column_widths_fall_back_per_column(self):
        self.assertEqual(
            [245, DEFAULT_SUMMARY_COLUMN_WIDTHS[1], 85],
            normalize_summary_column_widths([245, "invalid", 85]),
        )
        self.assertEqual(
            list(DEFAULT_SUMMARY_COLUMN_WIDTHS),
            normalize_summary_column_widths([245, 180]),
        )


if __name__ == "__main__":
    unittest.main()
