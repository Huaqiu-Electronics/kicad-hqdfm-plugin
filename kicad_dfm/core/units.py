MM_PER_INCH = 25.4
MILS_PER_INCH = 1000.0
MILS_PER_MM = MILS_PER_INCH / MM_PER_INCH


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def mm_to_nm(value):
    return int(round(safe_float(value) * 1000000))


def nm_to_mm(value):
    return safe_float(value) / 1000000.0


def mm_to_inches(value):
    return safe_float(value) / MM_PER_INCH


def mm_to_mils(value):
    return safe_float(value) * MILS_PER_MM


def mils_to_mm(value):
    return safe_float(value) / MILS_PER_MM
