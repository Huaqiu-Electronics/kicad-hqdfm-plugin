import re


GERBER_STEP_REPEAT_RE = re.compile(
    r"%SR\s*X\s*(\d+)\s*Y\s*(\d+)\s*I\s*([+-]?[0-9.]+)\s*J\s*([+-]?[0-9.]+)\s*\*%",
    re.IGNORECASE,
)
GERBER_STEP_REPEAT_RESET_RE = re.compile(r"%SR\s*\*%", re.IGNORECASE)
GERBER_FORMAT_RE = re.compile(r"%FS([LT])[AI]X(\d)(\d)Y(\d)(\d)\*%", re.IGNORECASE)
GERBER_OPERATION_RE = re.compile(r"D\s*0?([123])\s*\*", re.IGNORECASE)
GERBER_APERTURE_SELECT_RE = re.compile(r"(?:^|[^A-Z0-9])(?:G54)?D\s*(\d+)\s*\*", re.IGNORECASE)
GERBER_CW_RE = re.compile(r"G\s*0?2(?:\s*\*|[XYIJ])", re.IGNORECASE)
GERBER_CCW_RE = re.compile(r"G\s*0?3(?:\s*\*|[XYIJ])", re.IGNORECASE)
GERBER_LINEAR_RE = re.compile(r"G\s*0?1(?:\s*\*|[XYIJ])", re.IGNORECASE)
GERBER_REGION_START_RE = re.compile(r"G\s*36\s*\*", re.IGNORECASE)
GERBER_REGION_END_RE = re.compile(r"G\s*37\s*\*", re.IGNORECASE)
GERBER_X_RE = re.compile(r"X\s*([+-]?[0-9.]+)", re.IGNORECASE)
GERBER_Y_RE = re.compile(r"Y\s*([+-]?[0-9.]+)", re.IGNORECASE)
GERBER_I_RE = re.compile(r"I\s*([+-]?[0-9.]+)", re.IGNORECASE)
GERBER_J_RE = re.compile(r"J\s*([+-]?[0-9.]+)", re.IGNORECASE)


def iter_gerber_commands(path):
    pending = ""
    for line in iter_text_lines(path):
        stripped = line.strip()
        if not pending and is_single_gerber_command(stripped):
            yield stripped
            continue
        pending += stripped
        while pending:
            pending = pending.lstrip()
            if not pending:
                break
            if pending.startswith("%"):
                end = pending.find("*%")
                if end < 0:
                    break
                yield pending[: end + 2]
                pending = pending[end + 2 :]
                continue
            end = pending.find("*")
            if end < 0:
                break
            yield pending[: end + 1]
            pending = pending[end + 1 :]
    if pending.strip():
        yield pending.strip()


def is_single_gerber_command(line):
    if not line:
        return False
    if line.startswith("%"):
        return line.endswith("*%") and line.count("*%") == 1 and line.count("*") == 1
    return line.endswith("*") and line.count("*") == 1


def iter_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fp:
            for line in fp:
                yield line
    except OSError:
        return


def parse_gerber_format(line):
    coord_format = parse_gerber_coord_format(line)
    if coord_format is None:
        return None
    return coord_format[1][2], coord_format[2][2]


def gerber_ignored_command(line):
    upper = line.upper()
    return upper.startswith("G04") or upper.startswith(("%TA", "%TD", "%TF", "%TO"))


def gerber_unit_command(line):
    upper = line.upper()
    if upper.startswith("%MOIN") or upper == "G70*":
        return "inch"
    if upper.startswith("%MOMM") or upper == "G71*":
        return "mm"
    return None


def gerber_coordinate_mode_command(line):
    upper = line.upper()
    if upper == "G90*":
        return "absolute"
    if upper == "G91*":
        return "incremental"
    return None


def gerber_quadrant_mode_command(line):
    upper = line.upper()
    if upper == "G74*":
        return "single"
    if upper == "G75*":
        return "multi"
    return None


def gerber_polarity_command(line):
    upper = line.upper()
    if upper.startswith("%LPD"):
        return "dark"
    if upper.startswith("%LPC"):
        return "clear"
    return None


def parse_gerber_step_repeat(line, units):
    upper = line.upper()
    if not upper.startswith("%SR"):
        return None
    if GERBER_STEP_REPEAT_RESET_RE.match(line):
        return ((0.0, 0.0),)
    match = GERBER_STEP_REPEAT_RE.match(line)
    if not match:
        return None
    x_count = max(1, int(match.group(1)))
    y_count = max(1, int(match.group(2)))
    x_step = to_mm(float(match.group(3)), units)
    y_step = to_mm(float(match.group(4)), units)
    return tuple((x * x_step, y * y_step) for y in range(y_count) for x in range(x_count))


def set_gerber_coordinate_mode(decimals, mode):
    _, x_format, y_format = gerber_point_format(decimals)
    return mode, x_format, y_format


def parse_gerber_coord_format(line):
    match = GERBER_FORMAT_RE.search(line)
    if not match:
        return None
    zero_suppression = match.group(1).upper()
    coordinate_mode = "incremental" if "I" in line[: match.end()].upper() else "absolute"
    return (
        coordinate_mode,
        (zero_suppression, int(match.group(2)), int(match.group(3))),
        (zero_suppression, int(match.group(4)), int(match.group(5))),
    )


def gerber_operation(line):
    match = GERBER_OPERATION_RE.search(line)
    if not match:
        return None
    return int(match.group(1))


def gerber_aperture_select(line):
    match = GERBER_APERTURE_SELECT_RE.search(line)
    if not match or int(match.group(1)) < 10:
        return None
    return match.group(1)


def gerber_interpolation(line):
    if GERBER_CW_RE.search(line):
        return "cw"
    if GERBER_CCW_RE.search(line):
        return "ccw"
    if GERBER_LINEAR_RE.search(line):
        return "linear"
    return None


def gerber_region_start(line):
    return bool(GERBER_REGION_START_RE.search(line))


def gerber_region_end(line):
    return bool(GERBER_REGION_END_RE.search(line))


def parse_gerber_point(line, decimals, units, current=None):
    x_match = GERBER_X_RE.search(line)
    y_match = GERBER_Y_RE.search(line)
    if not x_match and not y_match:
        return None
    coordinate_mode, x_format, y_format = gerber_point_format(decimals)
    x = current[0] if current is not None else None
    y = current[1] if current is not None else None
    if x_match:
        value = to_mm(parse_gerber_coord(x_match.group(1), x_format), units)
        x = (current[0] if coordinate_mode == "incremental" and current is not None else 0.0) + value
    if y_match:
        value = to_mm(parse_gerber_coord(y_match.group(1), y_format), units)
        y = (current[1] if coordinate_mode == "incremental" and current is not None else 0.0) + value
    if x is None or y is None:
        return None
    return x, y


def parse_gerber_arc_offset(line, decimals, units):
    i_match = GERBER_I_RE.search(line)
    j_match = GERBER_J_RE.search(line)
    if not i_match and not j_match:
        return None
    _, x_format, y_format = gerber_point_format(decimals)
    i_value = to_mm(parse_gerber_coord(i_match.group(1), x_format), units) if i_match else 0.0
    j_value = to_mm(parse_gerber_coord(j_match.group(1), y_format), units) if j_match else 0.0
    return i_value, j_value


def parse_gerber_coord(value, decimals):
    text = str(value)
    if "." in text:
        return float(text)
    zero_suppression, integer_digits, decimal_digits = gerber_coord_spec(decimals)
    sign = -1.0 if text.startswith("-") else 1.0
    digits = text[1:] if text.startswith(("-", "+")) else text
    if zero_suppression == "T":
        digits = digits.ljust(integer_digits + decimal_digits, "0")
    return sign * float(digits or "0") / (10.0 ** decimal_digits)


def gerber_coord_spec(decimals):
    if isinstance(decimals, (list, tuple)):
        if len(decimals) == 3:
            return str(decimals[0]).upper(), int(decimals[1]), int(decimals[2])
        if len(decimals) == 2:
            return "L", int(decimals[0]), int(decimals[1])
    return "L", 0, int(decimals)


def gerber_point_format(decimals):
    if isinstance(decimals, (list, tuple)) and len(decimals) == 3 and isinstance(decimals[0], str):
        return decimals[0], decimals[1], decimals[2]
    return "absolute", decimals[0], decimals[1]


def to_mm(value, units):
    if units == "inch":
        return value * 25.4
    return value
