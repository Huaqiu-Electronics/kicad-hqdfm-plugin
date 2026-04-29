# `kicad_dfm.analysis`

Local KiCad analysis engine.  Runs design-rule checks directly against
the board object without calling the cloud API.

## `MinimumLineWidth`

Main analysis class.  Instantiated with a language-control dict and the
board, then each ``get_*`` method returns an :class:`~kicad_dfm.models.AnalysisResult` dict.

```python
checker = MinimumLineWidth(control, board)
pad_result = checker.get_pad(analysis_result)
ring_result = checker.get_annular_ring(analysis_result)
width_result = checker.get_line_width(analysis_result)
zone_result = checker.get_zone_attribute(analysis_result)
```
