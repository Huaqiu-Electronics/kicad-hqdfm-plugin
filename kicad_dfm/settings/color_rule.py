"""Colour-rule evaluation engine.

Determines whether a measurement falls into the ``"red"`` (fail),
``"gold"`` (warning), or ``"black"`` (pass) category based on
user-configured thresholds.

The :class:`RuleThreshold` model parses ``"a,b,c"`` comma-separated
rule strings into structured thresholds.  When Pydantic is available
it validates that all fields are floats; without Pydantic it falls
back to plain dataclass behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from pydantic import BaseModel

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False


from kicad_dfm.constants import COLOUR_BLACK, COLOUR_GOLD, COLOUR_RED

if HAS_PYDANTIC:

    class RuleThreshold(BaseModel):
        """A single rule parsed from a ``"a,b,c"`` comma-separated string."""

        model_config = {"frozen": True}
        lower: float
        upper: float
        extra: float | None = None

        @classmethod
        def parse(cls, rule_str: str) -> RuleThreshold:
            a, _, rest = rule_str.partition(",")
            b, _, c = rest.partition(",")
            return cls(
                lower=float(a),
                upper=float(b),
                extra=float(c) if c else None,
            )

        @classmethod
        def parse_filter(cls, rule_str: str) -> float | None:
            _, _, rest = rule_str.partition(",")
            _, _, c = rest.partition(",")
            return float(c) if c else None

else:

    @dataclass(frozen=True)
    class RuleThreshold:
        """A single rule parsed from a ``"a,b,c"`` comma-separated string.

        *lower* and *upper* define the acceptable range.  *extra* is an
        optional third field used for rule filtering.
        """

        lower: float
        upper: float
        extra: float | None = None

        @classmethod
        def parse(cls, rule_str: str) -> RuleThreshold:
            a, _, rest = rule_str.partition(",")
            b, _, c = rest.partition(",")
            return cls(
                lower=float(a),
                upper=float(b),
                extra=float(c) if c else None,
            )

        @classmethod
        def parse_filter(cls, rule_str: str) -> float | None:
            _, _, rest = rule_str.partition(",")
            _, _, c = rest.partition(",")
            return float(c) if c else None


class ColorRule:
    def get_rule(self, analysis_result: dict[str, Any], name: str, item_name: str, different: float) -> str:
        temp_rule = ""
        if analysis_result[name]["check"] is None:
            return COLOUR_BLACK
        for item_check in analysis_result[name]["check"]:
            for result in item_check["result"]:
                if result["item"] == item_name:
                    temp_rule = result["rule"]
        if not temp_rule:
            return COLOUR_RED
        rt = RuleThreshold.parse(temp_rule)
        if rt.lower < rt.upper:
            if different < rt.lower:
                return COLOUR_RED
            if rt.lower < different < rt.upper:
                return COLOUR_GOLD
            return COLOUR_BLACK
        if different > rt.lower:
            return COLOUR_RED
        if rt.upper < different < rt.lower:
            return COLOUR_GOLD
        return COLOUR_BLACK

    def filter_rule_value(self, analysis_result: dict[str, Any], name: str, item_name: str) -> float | None:
        for item_check in analysis_result[name]["check"]:
            for result in item_check["result"]:
                if result["item"] == item_name:
                    val = RuleThreshold.parse_filter(result["rule"])
                    return val if val is not None else 0.0
        return None
