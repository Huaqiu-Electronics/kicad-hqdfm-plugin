def dpi_scale(window):
    reader = getattr(window, "GetDPIScaleFactor", None)
    if reader is None:
        return 1.0
    try:
        scale = float(reader())
    except (TypeError, ValueError):
        return 1.0
    return scale if scale > 0 else 1.0


def scaled_dip(window, value):
    converter = getattr(window, "FromDIP", None)
    if converter is not None:
        try:
            return int(converter(int(value)))
        except (AttributeError, TypeError, ValueError):
            pass
    return max(0, int(round(float(value) * dpi_scale(window))))


def unscaled_dip(window, value):
    converter = getattr(window, "ToDIP", None)
    if converter is not None:
        try:
            return int(converter(int(value)))
        except (AttributeError, TypeError, ValueError):
            pass
    return max(0, int(round(float(value) / dpi_scale(window))))


def summary_row_layout(window, row_height_dip=35, button_height_dip=30):
    """Return one physical row slot and a button that fits inside it.

    Scaling the button and its margins independently accumulates rounding
    differences against native DataView rows.  The row slot is therefore the
    single source of truth; the sizer centers the smaller button inside it.
    """
    row_height = scaled_dip(window, row_height_dip)
    button_height = min(row_height, scaled_dip(window, button_height_dip))
    return row_height, button_height
