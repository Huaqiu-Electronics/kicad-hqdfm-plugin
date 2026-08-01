"""Pydantic models for plugin data structures (optional dependency).

When Pydantic v2 is installed, models provide full validation, serialization,
and schema generation.  Without Pydantic, the model classes still exist as
simple data containers and validation helpers become no-ops.
"""

from __future__ import annotations

from typing import Any

try:
    from pydantic import BaseModel as _PydanticBase
    from pydantic import Field, field_validator, model_validator

    HAS_PYDANTIC = True

    class _Base(_PydanticBase):
        """Base class used when Pydantic IS available."""

except ImportError:  # pragma: no cover
    HAS_PYDANTIC = False

    class _Base:
        """Minimal stand-in so code that imports models doesn't crash."""

        def __init__(self, **data: Any) -> None:
            self.__dict__.update(data)

        def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
            return self.__dict__.copy()

        @classmethod
        def model_validate(cls, obj: Any, **_kwargs: Any) -> _Base:
            if isinstance(obj, dict):
                return cls(**obj)
            return obj

    def Field(*, default: Any = None, default_factory: Any = None, **_kwargs: Any) -> Any:
        return default_factory() if default_factory is not None else default

    def field_validator(*_args: Any, **_kwargs: Any) -> Any:
        """No-op decorator when Pydantic is absent."""

        def wrapper(func: Any) -> Any:
            return func

        return wrapper

    def model_validator(*_args: Any, **_kwargs: Any) -> Any:
        def wrapper(func: Any) -> Any:
            return func

        return wrapper


from kicad_dfm.constants import VALID_COLOURS as _VALID_COLORS
from kicad_dfm.constants import Colour

_VALID_COLORS = _VALID_COLORS


class AnalysisResultItem(_Base):
    """A single row in the analysis results table.

    Each row corresponds to one PCB element (trace, pad, via, zone)
    that was flagged during an analysis pass.
    """

    value: str = ""
    id: str = ""
    layer: list[str] = Field(default_factory=list)
    item: str = ""
    color: str = Colour.BLACK
    pad_diameter: float | None = None
    hole_diameter: float | None = None

    if HAS_PYDANTIC:

        @field_validator("color")
        @classmethod
        def _must_be_known_colour(cls, v: str) -> str:
            if v not in _VALID_COLORS:
                msg = f"color must be one of {sorted(_VALID_COLORS)}, got {v!r}"
                raise ValueError(msg)
            return v

        @field_validator("item")
        @classmethod
        def _item_non_empty(cls, v: str) -> str:
            if not v.strip():
                msg = "item must be a non-empty string"
                raise ValueError(msg)
            return v

        @model_validator(mode="after")
        def _check_pad_diameter_coherence(self) -> AnalysisResultItem:
            if self.pad_diameter is not None and self.hole_diameter is None:
                msg = "pad_diameter set but hole_diameter is None"
                raise ValueError(msg)
            return self


class AnalysisResultCheck(_Base):
    """A group of related :class:`AnalysisResultItem` objects.

    Typically corresponds to one check type (e.g. annular ring
    violations) with multiple matching elements.
    """

    result: list[AnalysisResultItem] = Field(default_factory=list)


class AnalysisResult(_Base):
    """Top-level container for one analysis check category.

    Maps directly to the JSON structure returned by the DFM analysis
    API and consumed by the UI models.
    """

    display: str | float = ""
    check: list[AnalysisResultCheck] | None = None
    color: str = Colour.BLACK

    if HAS_PYDANTIC:

        @field_validator("color")
        @classmethod
        def _must_be_known_colour(cls, v: str) -> str:
            if v not in _VALID_COLORS:
                msg = f"color must be one of {sorted(_VALID_COLORS)}, got {v!r}"
                raise ValueError(msg)
            return v

        @field_validator("display")
        @classmethod
        def _display_not_blank(cls, v: str | float) -> str | float:
            if isinstance(v, str) and not v.strip():
                msg = "display must not be blank when it is a string"
                raise ValueError(msg)
            return v

        @model_validator(mode="after")
        def _check_consistent(self) -> AnalysisResult:
            has_items = self.check is not None and len(self.check) > 0
            if self.color == "red" and not has_items and isinstance(self.display, str) and self.display:
                msg = "color is red but check list is empty — inconsistent result"
                raise ValueError(msg)
            return self


class ColorRuleEntry(_Base):
    """A single threshold rule for colour-coding analysis results.

    Example: pads with width ``min < x < max`` are coloured ``"gold"``.
    """

    name: str = ""
    min: float | None = None
    max: float | None = None
    color: str = Colour.BLACK

    if HAS_PYDANTIC:

        @field_validator("color")
        @classmethod
        def _must_be_known_colour(cls, v: str) -> str:
            if v not in _VALID_COLORS:
                msg = f"color must be one of {sorted(_VALID_COLORS)}, got {v!r}"
                raise ValueError(msg)
            return v

        @field_validator("max")
        @classmethod
        def _max_gte_min(cls, v: float | None, info: Any) -> float | None:
            if v is not None and info.data.get("min") is not None and v < info.data["min"]:
                msg = f"max ({v}) must be >= min ({info.data['min']})"
                raise ValueError(msg)
            return v


class ColorRuleSet(_Base):
    """A collection of :class:`ColorRuleEntry` thresholds."""

    rules: list[ColorRuleEntry] = Field(default_factory=list)


def maybe_validate(model_cls: Any, data: dict) -> dict:
    """Validate *data* as *model_cls* and return a plain dict.

    When Pydantic is not installed this is a no-op — *data* is
    returned unchanged.
    """
    if HAS_PYDANTIC:
        return model_cls.model_validate(data).model_dump()
    return data
