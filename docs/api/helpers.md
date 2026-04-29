# `kicad_dfm.helpers`

Mixed utility functions that depend on wxPython and KiCad's pcbnew API.
Pure functions (bit manipulation, natural sort) live in
:doc:`pure` instead.

## Version / scale helpers

| Function | Returns | Description |
|---|---|---|
| `getWxWidgetsVersion()` | `int` | wxWidgets version as integer (e.g. 315) |
| `getVersion()` | `str` | Plugin version from ``VERSION`` file |
| `GetScaleFactor(window)` | `float` | DPI scale factor (workaround) |
| `HighResWxSize(window, size)` | `tuple` | ``FromDIP`` workaround |

## Bitmap loading

| Function | Description |
|---|---|
| `loadBitmapScaled(filename, scale, static)` | Load and scale a bitmap |
| `loadIconScaled(filename, scale)` | Load and scale an icon |
| `GetListIcon(value, scale_factor)` | Check/close icon for list |

## Footprint property helpers

| Function | Description |
|---|---|
| `get_lcsc_value(fp)` | Extract LCSC number from footprint |
| `get_valid_footprints(board)` | Get all non-REF** footprints |
| `get_footprint_keys(fp)` | Sort keys for a footprint |
| `get_footprint_by_ref(board, ref)` | Find footprint by reference |

## Attribute get/set/toggle helpers

Each of ``THT``, ``SMD``, ``EXCLUDE_FROM_POS``, ``EXCLUDE_FROM_BOM``,
``NOT_IN_SCHEMATIC`` has a matching set of:

- ``get_{name}(footprint) -> bool``
- ``set_{name}(footprint)``
- ``toggle_{name}(footprint)``
