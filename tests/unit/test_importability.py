"""Smoke tests: verify pure modules can be imported and their public API works."""

import pytest

pytestmark = pytest.mark.pure


def test_pure_module_importable():
    from kicad_dfm.utils.pure import clear_bit, get_bit, natural_sort_collation, set_bit, toggle_bit

    assert callable(get_bit)
    assert callable(set_bit)
    assert callable(clear_bit)
    assert callable(toggle_bit)
    assert callable(natural_sort_collation)


def test_point_to_line_distance_importable():
    from kicad_dfm.settings.point_to_line_distance import LINE_WIDTH_EXTENT, point_to_line_distance

    assert callable(point_to_line_distance)
    assert isinstance(LINE_WIDTH_EXTENT, int)
    assert LINE_WIDTH_EXTENT > 0


def test_config_importable():
    from kicad_dfm.config import Language_chinese, Language_english

    assert isinstance(Language_chinese, dict)
    assert isinstance(Language_english, dict)


@pytest.mark.requires_wx
def test_helpers_bit_ops_still_accessible():
    from kicad_dfm.helpers import get_bit, set_bit

    assert callable(get_bit)
    assert callable(set_bit)
