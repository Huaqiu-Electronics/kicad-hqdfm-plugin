import unittest

from kicad_dfm.core.pad_size import pad_shorter_side_mm, pad_size_item


class PadSizeTest(unittest.TestCase):
    def test_exact_aspect_ratio_boundary_is_ordinary(self):
        self.assertEqual("Short Pads", pad_size_item(1.2, 1.0))

    def test_parser_noise_does_not_flip_boundary_pad(self):
        self.assertEqual("Short Pads", pad_size_item(1.2000000005, 1.0))

    def test_pad_above_aspect_ratio_boundary_is_long(self):
        self.assertEqual("Long Pads", pad_size_item(1.200001, 1.0))

    def test_classification_is_axis_and_sign_independent(self):
        self.assertEqual("Long Pads", pad_size_item(-0.5, 1.0))
        self.assertEqual("Long Pads", pad_size_item(1.0, -0.5))

    def test_zero_sized_pad_does_not_divide_by_zero(self):
        self.assertEqual("Short Pads", pad_size_item(0.0, 1.0))

    def test_shorter_side_uses_absolute_outer_dimensions(self):
        self.assertEqual(0.25, pad_shorter_side_mm(-0.25, 0.6))


if __name__ == "__main__":
    unittest.main()
