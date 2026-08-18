PAD_LONG_ASPECT_RATIO = 1.2
PAD_ASPECT_RATIO_TOLERANCE = 1e-9


def pad_shorter_side_mm(size_x, size_y):
    """Return the absolute shorter side of a pad, in millimetres."""
    return min(abs(float(size_x)), abs(float(size_y)))


def pad_size_item(size_x, size_y):
    """Classify a pad from its outer-copper aspect ratio."""
    short = pad_shorter_side_mm(size_x, size_y)
    long = max(abs(float(size_x)), abs(float(size_y)))
    if short <= 0:
        return "Short Pads"
    if long / short - PAD_LONG_ASPECT_RATIO > PAD_ASPECT_RATIO_TOLERANCE:
        return "Long Pads"
    return "Short Pads"
