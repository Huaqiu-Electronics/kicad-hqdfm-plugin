# `kicad_dfm.settings.color_rule`

Colour-rule evaluation engine.  Determines whether a measurement falls
into the ``"red"`` (fail), ``"gold"`` (warning), or ``"black"`` (pass)
category based on user-configured thresholds.

## `ColorRule`

```python
rule = ColorRule()
colour = rule.get_rule(analysis_result, "Pad size", "Short Pads", 0.45)
threshold = rule.filter_rule_value(analysis_result, "RingHole", "Via Annular Ring")
```

### `get_rule(analysis_result, name, item_name, different) -> str`

Looks up the rule string for *item_name* within
``analysis_result[name]["check"]``, parses the comma-separated
threshold, and returns ``"red"``, ``"gold"``, or ``"black"``.

### `filter_rule_value(analysis_result, name, item_name) -> float | None`

Same lookup but returns the third comma-separated field from the rule
string (used for advanced filtering).
