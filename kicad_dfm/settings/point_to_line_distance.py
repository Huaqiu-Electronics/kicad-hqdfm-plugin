from __future__ import annotations

from math import sqrt
from typing import TypedDict

from kicad_dfm.constants import LINE_WIDTH_EXTENT_NM, SENTINEL_DISTANCE_FALLBACK

LINE_WIDTH_EXTENT = LINE_WIDTH_EXTENT_NM


class LineDict(TypedDict):
    start_x: int
    start_y: int
    end_x: int
    end_y: int


Point2D = tuple[int | float, int | float]


def point_to_line_distance(p: Point2D, line: dict) -> float:
    C = (line["start_x"], line["start_y"])
    D = (line["end_x"], line["end_y"])

    numerator = abs((D[1] - C[1]) * (p[0] - C[0]) - (D[0] - C[0]) * (p[1] - C[1]))
    denominator = sqrt((D[1] - C[1]) ** 2 + (D[0] - C[0]) ** 2)

    if denominator == 0:
        return float("inf")
    distance = numerator / denominator

    if (D[1] - C[1]) == 0:
        P_prime_x = p[0]
        P_prime_y = D[1]
    elif (D[0] - C[0]) == 0:
        P_prime_x = D[0]
        P_prime_y = p[1]
    else:
        factor_denominator = (D[0] - C[0]) ** 2 + (D[1] - C[1]) ** 2
        factor = ((p[0] - C[0]) * (D[0] - C[0]) + (p[1] - C[1]) * (D[1] - C[1])) / factor_denominator
        P_prime_x = C[0] + factor * (D[0] - C[0])
        P_prime_y = C[1] + factor * (D[1] - C[1])

    is_on_segment = (
        (
            C[0] - LINE_WIDTH_EXTENT <= P_prime_x <= D[0] + LINE_WIDTH_EXTENT
            and C[1] - LINE_WIDTH_EXTENT <= P_prime_y <= D[1] + LINE_WIDTH_EXTENT
        )
        or (
            D[0] - LINE_WIDTH_EXTENT <= P_prime_x <= C[0] + LINE_WIDTH_EXTENT
            and D[1] - LINE_WIDTH_EXTENT <= P_prime_y <= C[1] + LINE_WIDTH_EXTENT
        )
        or (
            D[0] - LINE_WIDTH_EXTENT <= P_prime_x <= C[0] + LINE_WIDTH_EXTENT
            and C[1] - LINE_WIDTH_EXTENT <= P_prime_y <= D[1] + LINE_WIDTH_EXTENT
        )
        or (
            C[0] - LINE_WIDTH_EXTENT <= P_prime_x <= D[0] + LINE_WIDTH_EXTENT
            and D[1] - LINE_WIDTH_EXTENT <= P_prime_y <= C[1] + LINE_WIDTH_EXTENT
        )
    )
    if is_on_segment:
        return distance
    return SENTINEL_DISTANCE_FALLBACK
