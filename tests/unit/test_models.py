import pytest

from kicad_dfm.models import (
    HAS_PYDANTIC,
    AnalysisResult,
    AnalysisResultCheck,
    AnalysisResultItem,
    ColorRuleEntry,
    ColorRuleSet,
    maybe_validate,
)

pytestmark = pytest.mark.pure


class TestAnalysisResultItem:
    def test_defaults(self):
        item = AnalysisResultItem()
        assert item.value == ""
        assert item.id == ""
        assert item.layer == []
        assert item.item == ""
        assert item.color == "black"
        assert item.pad_diameter is None
        assert item.hole_diameter is None

    def test_with_values(self):
        item = AnalysisResultItem(value="0.250", id="u1", layer=["F.Cu"], item="Trace")
        assert item.value == "0.250"
        assert item.id == "u1"
        assert item.layer == ["F.Cu"]

    def test_model_dump_roundtrip(self):
        item = AnalysisResultItem(value="0.5", id="x", layer=["B.Cu"], item="Pad", color="red")
        dumped = item.model_dump()
        restored = AnalysisResultItem.model_validate(dumped)
        assert restored.value == "0.5"
        assert restored.color == "red"

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_strict_types(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AnalysisResultItem(value=123, id="x")  # type: ignore[arg-type]

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_rejects_unknown_color(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AnalysisResultItem(value="0.1", id="x", color="nonexistent")

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_rejects_empty_item(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AnalysisResultItem(value="0.1", id="x", item="  ")


class TestAnalysisResultCheck:
    def test_empty(self):
        check = AnalysisResultCheck()
        assert check.result == []

    def test_with_items(self):
        items = [AnalysisResultItem(value="1", id="a"), AnalysisResultItem(value="2", id="b")]
        check = AnalysisResultCheck(result=items)
        assert len(check.result) == 2


class TestAnalysisResult:
    def test_defaults(self):
        ar = AnalysisResult()
        assert ar.display == ""
        assert ar.check is None
        assert ar.color == "black"

    def test_with_nested_data(self):
        items = [AnalysisResultItem(value="0.25", id="u1", item="Via Annular Ring")]
        check = AnalysisResultCheck(result=items)
        ar = AnalysisResult(display=0.25, check=[check], color="gold")
        assert ar.display == 0.25
        assert ar.check is not None
        assert len(ar.check) == 1

    def test_model_dump_nested(self):
        items = [AnalysisResultItem(value="1", id="a")]
        check = AnalysisResultCheck(result=items)
        ar = AnalysisResult(display=1.0, check=[check], color="red")
        dumped = ar.model_dump()
        assert dumped["display"] == 1.0
        assert dumped["color"] == "red"
        assert len(dumped["check"]) == 1
        assert dumped["check"][0]["result"][0]["value"] == "1"

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_rejects_blank_display(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AnalysisResult(display="  ", check=[])


class TestColorRuleEntry:
    def test_defaults(self):
        rule = ColorRuleEntry()
        assert rule.name == ""
        assert rule.min is None
        assert rule.max is None
        assert rule.color == "black"

    def test_with_values(self):
        rule = ColorRuleEntry(name="test", min=0.1, max=0.5, color="red")
        assert rule.name == "test"
        assert rule.min == 0.1
        assert rule.max == 0.5

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_rejects_invalid_colour(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ColorRuleEntry(name="x", color="green")

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_rejects_max_lt_min(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ColorRuleEntry(name="x", min=5.0, max=1.0)

    def test_allows_max_gt_min(self):
        rule = ColorRuleEntry(name="x", min=1.0, max=5.0, color="gold")
        assert rule.min == 1.0
        assert rule.max == 5.0

    def test_allows_none_min_max(self):
        rule = ColorRuleEntry(name="x")
        assert rule.min is None
        assert rule.max is None


class TestColorRuleSet:
    def test_defaults(self):
        s = ColorRuleSet()
        assert s.rules == []

    def test_with_rules(self):
        rules = [ColorRuleEntry(name="a", color="red"), ColorRuleEntry(name="b", color="gold")]
        s = ColorRuleSet(rules=rules)
        assert len(s.rules) == 2


class TestMaybeValidate:
    def test_valid_data(self):
        data = {"value": "0.250", "id": "u1", "layer": ["F.Cu"], "item": "Trace"}
        result = maybe_validate(AnalysisResultItem, data)
        assert result["value"] == "0.250"
        assert result["layer"] == ["F.Cu"]

    def test_missing_optional_fields(self):
        data = {"value": "1.0", "id": "x"}
        result = maybe_validate(AnalysisResultItem, data)
        assert result["value"] == "1.0"
        assert result["color"] == "black"

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_validate_rejects_invalid_colour_in_result(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            maybe_validate(AnalysisResult, {"display": "ok", "color": "pink", "check": []})
