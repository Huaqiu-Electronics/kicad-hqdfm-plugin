import unittest

from kicad_dfm.ui.dpi import dpi_scale
from kicad_dfm.ui.dpi import scaled_dip
from kicad_dfm.ui.dpi import summary_row_layout
from kicad_dfm.ui.dpi import unscaled_dip
from kicad_dfm.ui.main_frame import format_board_dimensions
from kicad_dfm.core.units import mm_to_mils, mils_to_mm


class FakeDpiWindow:
    def __init__(self, scale, converter=True):
        self.scale = scale
        self.converter = converter

    def GetDPIScaleFactor(self):
        return self.scale

    def FromDIP(self, value):
        if not self.converter:
            raise TypeError("FromDIP unavailable")
        return round(value * self.scale)

    def ToDIP(self, value):
        if not self.converter:
            raise TypeError("ToDIP unavailable")
        return round(value / self.scale)


class UiDpiTest(unittest.TestCase):
    def test_scaled_dip_uses_current_monitor_conversion(self):
        window = FakeDpiWindow(1.5)

        self.assertEqual(45, scaled_dip(window, 30))
        self.assertEqual(52, scaled_dip(window, 35))

    def test_scaled_dip_falls_back_to_dpi_factor(self):
        window = FakeDpiWindow(2.0, converter=False)

        self.assertEqual(60, scaled_dip(window, 30))

    def test_unscaled_dip_round_trips_current_monitor_conversion(self):
        window = FakeDpiWindow(1.5)

        self.assertEqual(30, unscaled_dip(window, scaled_dip(window, 30)))

    def test_unscaled_dip_falls_back_to_dpi_factor(self):
        window = FakeDpiWindow(2.0, converter=False)

        self.assertEqual(30, unscaled_dip(window, 60))

    def test_invalid_scale_falls_back_to_one(self):
        window = FakeDpiWindow(0.0, converter=False)

        self.assertEqual(1.0, dpi_scale(window))
        self.assertEqual(30, scaled_dip(window, 30))

    def test_summary_buttons_use_one_exact_row_slot_at_fractional_dpi(self):
        window = FakeDpiWindow(1.5)

        row_height, button_height = summary_row_layout(window)

        self.assertEqual(scaled_dip(window, 35), row_height)
        self.assertEqual(scaled_dip(window, 30), button_height)
        self.assertLessEqual(button_height, row_height)

    def test_summary_button_never_exceeds_small_row_slot(self):
        window = FakeDpiWindow(0.5)

        row_height, button_height = summary_row_layout(
            window, row_height_dip=20, button_height_dip=30
        )

        self.assertEqual(row_height, button_height)

    def test_board_dimensions_always_use_millimetres(self):
        self.assertEqual("160.4*99.44 mm", format_board_dimensions("160.4*99.44"))

    def test_empty_board_dimensions_still_show_unit(self):
        self.assertEqual("0 mm", format_board_dimensions("0"))

    def test_three_mil_conversion_uses_exact_inch_definition(self):
        self.assertAlmostEqual(3.0, mm_to_mils(0.0762), places=12)
        self.assertAlmostEqual(0.0762, mils_to_mm(3.0), places=12)


if __name__ == "__main__":
    unittest.main()
