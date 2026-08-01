import pytest

from kicad_dfm.config import Language_chinese, Language_english

pytestmark = pytest.mark.pure


class TestLanguageDicts:
    def test_chinese_has_entries(self):
        assert len(Language_chinese) > 0

    def test_english_has_entries(self):
        assert len(Language_english) > 0

    def test_chinese_values_non_empty(self):
        for key, val in Language_chinese.items():
            assert val, f"Chinese[{key!r}] is empty"

    def test_english_values_non_empty(self):
        for key, val in Language_english.items():
            assert val, f"English[{key!r}] is empty"

    def test_internal_keys_start_alpha(self):
        for key in Language_english:
            assert key[0].isalpha() or key[0].isdigit(), f"English key {key!r} starts with non-alphanumeric"

    def test_chinese_keys_start_alpha(self):
        for key in Language_chinese:
            assert key[0].isalpha() or key[0].isdigit(), f"Chinese key {key!r} starts with non-alphanumeric"

    def test_chinese_values_contain_chinese(self):
        chinese_count = sum(1 for v in Language_chinese.values() if any("\u4e00" <= c <= "\u9fff" for c in v))
        assert chinese_count >= len(Language_chinese) // 2
