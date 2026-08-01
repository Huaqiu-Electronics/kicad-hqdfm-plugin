import pytest

from kicad_dfm.utils.pure import clear_bit, get_bit, natural_sort_collation, set_bit, toggle_bit

pytestmark = pytest.mark.pure


class TestBitManipulation:
    def test_get_bit_zero(self):
        assert not get_bit(0, 0)

    def test_get_bit_set(self):
        assert get_bit(1, 0)

    def test_get_bit_not_set(self):
        assert not get_bit(2, 0)

    def test_get_bit_returns_mask_not_bool(self):
        assert get_bit(2, 1) == 2
        assert get_bit(4, 2) == 4

    def test_get_bit_high_bits(self):
        assert get_bit(255, 7)
        assert not get_bit(127, 7)

    def test_set_bit(self):
        assert set_bit(0, 0) == 1

    def test_set_bit_already_set(self):
        assert set_bit(1, 0) == 1

    def test_set_bit_multiple_independent(self):
        assert set_bit(set_bit(0, 0), 1) == 3

    def test_set_bit_does_not_clear_other_bits(self):
        assert set_bit(2, 0) == 3

    def test_clear_bit(self):
        assert clear_bit(1, 0) == 0

    def test_clear_bit_already_clear(self):
        assert clear_bit(0, 0) == 0

    def test_clear_bit_high(self):
        assert clear_bit(8, 3) == 0

    def test_clear_bit_preserves_other_bits(self):
        assert clear_bit(7, 1) == 5

    def test_toggle_bit(self):
        assert toggle_bit(0, 0) == 1
        assert toggle_bit(1, 0) == 0

    def test_toggle_bit_multiple(self):
        assert toggle_bit(5, 2) == 1

    def test_multiple_bits_set_clear_toggle(self):
        val = set_bit(0, 0)
        val = set_bit(val, 1)
        assert get_bit(val, 0)
        assert get_bit(val, 1)
        assert not get_bit(val, 2)
        val = clear_bit(val, 0)
        assert not get_bit(val, 0)
        assert get_bit(val, 1)
        val = toggle_bit(val, 1)
        assert not get_bit(val, 1)

    def test_bit_ops_idempotent(self):
        assert set_bit(set_bit(set_bit(0, 0), 0), 0) == 1
        assert clear_bit(clear_bit(1, 0), 0) == 0

    def test_constants_match_pcb_attributes(self):
        assert get_bit(1, 0)  # THT
        assert get_bit(2, 1)  # SMD
        assert get_bit(4, 2)  # EXCLUDE_FROM_POS
        assert get_bit(8, 3)  # EXCLUDE_FROM_BOM
        assert get_bit(16, 4)  # NOT_IN_SCHEMATIC


class TestNaturalSortCollation:
    def test_equal_strings(self):
        assert natural_sort_collation("abc", "abc") == 0

    def test_numeric_sorting(self):
        assert natural_sort_collation("item2", "item10") == -1

    def test_numeric_sorting_reverse(self):
        assert natural_sort_collation("item10", "item2") == 1

    def test_alpha_sorting(self):
        assert natural_sort_collation("alpha", "beta") == -1

    def test_reverse_alpha(self):
        assert natural_sort_collation("beta", "alpha") == 1

    def test_mixed_content(self):
        assert natural_sort_collation("a1b2", "a1b10") == -1

    def test_identical_numeric(self):
        assert natural_sort_collation("item5", "item5") == 0

    def test_pure_numbers(self):
        assert natural_sort_collation("2", "10") == -1

    def test_padded_numbers(self):
        assert natural_sort_collation("01", "1") == -1

    def test_empty_strings(self):
        assert natural_sort_collation("", "a") == -1
        assert natural_sort_collation("a", "") == 1
        assert natural_sort_collation("", "") == 0

    def test_case_insensitive_stable(self):
        result = natural_sort_collation("Alpha", "alpha")
        assert result == -1  # stable sort: original order preserved when normalized keys equal

    def test_complex_path_like(self):
        result = natural_sort_collation("ref/designator_10", "ref/designator_2")
        assert result == 1

    def test_transitive_property(self):
        assert natural_sort_collation("a", "b") == -1
        assert natural_sort_collation("b", "c") == -1
        assert natural_sort_collation("a", "c") == -1

    def test_symmetric_property(self):
        assert natural_sort_collation("a", "b") == -natural_sort_collation("b", "a")

    def test_list_sort_consistency(self):
        items = ["img_2", "img_10", "img_1", "img_20"]
        import functools

        sorted_items = sorted(items, key=functools.cmp_to_key(natural_sort_collation))
        assert sorted_items == ["img_1", "img_2", "img_10", "img_20"]

    def test_list_sort_with_paths(self):
        items = ["z10/x2", "z2/x10", "z10/x10", "z2/x2"]
        import functools

        sorted_items = sorted(items, key=functools.cmp_to_key(natural_sort_collation))
        assert sorted_items == ["z2/x2", "z2/x10", "z10/x2", "z10/x10"]
