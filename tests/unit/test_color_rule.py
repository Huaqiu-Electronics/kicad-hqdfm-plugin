import pytest

from kicad_dfm.settings.color_rule import ColorRule, RuleThreshold

pytestmark = pytest.mark.pure


class TestRuleThreshold:
    def test_parse_basic(self):
        rt = RuleThreshold.parse("0.3,0.8")
        assert rt.lower == 0.3
        assert rt.upper == 0.8
        assert rt.extra is None

    def test_parse_with_extra(self):
        rt = RuleThreshold.parse("0.1,0.5,0.75")
        assert rt.lower == 0.1
        assert rt.upper == 0.5
        assert rt.extra == 0.75

    def test_parse_filter(self):
        assert RuleThreshold.parse_filter("0.1,0.5,0.75") == 0.75
        assert RuleThreshold.parse_filter("0.1,0.5") is None

    def test_parse_descending(self):
        rt = RuleThreshold.parse("0.8,0.3")
        assert rt.lower == 0.8
        assert rt.upper == 0.3

    def test_is_frozen(self):
        rt = RuleThreshold.parse("0.3,0.8")
        from kicad_dfm.settings.color_rule import HAS_PYDANTIC

        if HAS_PYDANTIC:
            from pydantic import ValidationError

            with pytest.raises(ValidationError):
                rt.lower = 0.5  # type: ignore[misc]
        else:
            with pytest.raises(AttributeError):
                rt.lower = 0.5


def _make_analysis(name, rule_strs):
    """Build an analysis_result dict for testing.

    *name* is the top-level key (e.g. ``"Pad size"``).
    *rule_strs* is a list of (item_name, rule_string) pairs.
    """
    return {name: {"check": [{"result": [{"item": item, "rule": rule}]} for item, rule in rule_strs]}}


class TestGetRule:
    def setup_method(self):
        self.rule = ColorRule()

    def test_no_check_returns_black(self):
        data = {"Pad size": {"check": None}}
        assert self.rule.get_rule(data, "Pad size", "Short Pads", 0.5) == "black"

    def test_no_matching_item_returns_red(self):
        data = _make_analysis("Pad size", [("Long Pads", "0.3,0.8")])
        assert self.rule.get_rule(data, "Pad size", "Short Pads", 0.5) == "red"

    def test_at_threshold_ascending_passes(self):
        """Exact threshold match returns black (pass), since comparison is strict <."""
        data = _make_analysis("X", [("item", "0.3,0.8")])
        assert self.rule.get_rule(data, "X", "item", 0.3) == "black"
        assert self.rule.get_rule(data, "X", "item", 0.8) == "black"

    def test_below_lower_threshold_ascending_returns_red(self):
        """When ascending (rule[0] < rule[1]), value below BOTH thresholds is RED."""
        data = _make_analysis("X", [("item", "0.3,0.8")])
        assert self.rule.get_rule(data, "X", "item", 0.1) == "red"

    def test_between_thresholds_ascending_returns_gold(self):
        """When ascending (rule[0] < rule[1]), value between thresholds is GOLD."""
        data = _make_analysis("X", [("item", "0.3,0.8")])
        assert self.rule.get_rule(data, "X", "item", 0.5) == "gold"

    def test_above_upper_threshold_descending_returns_red(self):
        data = _make_analysis("X", [("item", "0.8,0.3")])
        assert self.rule.get_rule(data, "X", "item", 1.0) == "red"

    def test_between_thresholds_descending_returns_gold(self):
        data = _make_analysis("X", [("item", "0.8,0.3")])
        assert self.rule.get_rule(data, "X", "item", 0.5) == "gold"

    def test_below_lower_threshold_descending_returns_black(self):
        """When descending (rule[0] > rule[1]), values below both are OK (black)."""
        data = _make_analysis("X", [("item", "0.8,0.3")])
        assert self.rule.get_rule(data, "X", "item", 0.1) == "black"

    def test_last_matching_item_wins(self):
        data = _make_analysis("X", [("item", "0.8,0.3"), ("item", "0.1,0.5")])
        assert self.rule.get_rule(data, "X", "item", 0.5) == "black"


class TestFilterRuleValue:
    def setup_method(self):
        self.rule = ColorRule()

    def test_returns_third_field(self):
        data = _make_analysis("X", [("item", "0.1,0.5,0.75")])
        result = self.rule.filter_rule_value(data, "X", "item")
        assert result == 0.75

    def test_no_third_field_returns_zero(self):
        data = _make_analysis("X", [("item", "0.1,0.5")])
        result = self.rule.filter_rule_value(data, "X", "item")
        assert result == 0

    def test_no_matching_item_returns_none(self):
        data = _make_analysis("X", [("other", "0.1,0.5,0.75")])
        result = self.rule.filter_rule_value(data, "X", "item")
        assert result is None
