# `kicad_dfm.models`

Optional Pydantic v2 models for analysis result structures.
Degrades gracefully when Pydantic is not installed.

## Analysis results

### `AnalysisResultItem`

A single row in the analysis UI table.

| Field | Type | Default | Description |
|---|---|---|---|
| `value` | `str` | `""` | Display value |
| `id` | `str` | `""` | KiCad object UUID |
| `layer` | `list[str]` | `[]` | Affected layers |
| `item` | `str` | `""` | Analysis item name |
| `color` | `str` | `"black"` | Colour indicator |
| `pad_diameter` | `float\|None` | `None` | Pad outer diameter (mm) |
| `hole_diameter` | `float\|None` | `None` | Pad hole diameter (mm) |

**Validators** (Pydantic only):
- `color` must be one of `{"red", "gold", "black"}`
- `item` must be non-empty

### `AnalysisResultCheck`

A group of related result items.

| Field | Type | Default |
|---|---|---|
| `result` | `list[AnalysisResultItem]` | `[]` |

### `AnalysisResult`

Top-level container for one analysis check type.

| Field | Type | Default |
|---|---|---|
| `display` | `str\|float` | `""` |
| `check` | `list[AnalysisResultCheck]\|None` | `None` |
| `color` | `str` | `"black"` |

**Validators** (Pydantic only):
- `color` must be one of `{"red", "gold", "black"}`
- `display` must not be blank when it is a string

## Rule configuration

### `ColorRuleEntry`

A single colour rule threshold.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | `""` |
| `min` | `float\|None` | `None` |
| `max` | `float\|None` | `None` |
| `color` | `str` | `"black"` |

**Validators** (Pydantic only):
- `color` must be one of `{"red", "gold", "black"}`
- `max` must be `>= min` when both are set

### `ColorRuleSet`

| Field | Type | Default |
|---|---|---|
| `rules` | `list[ColorRuleEntry]` | `[]` |

## Helpers

### `maybe_validate(model_cls, data)`

```python
def maybe_validate(model_cls: type, data: dict) -> dict
```

Validates `data` against `model_cls` and returns a dict.
No-op without Pydantic.
