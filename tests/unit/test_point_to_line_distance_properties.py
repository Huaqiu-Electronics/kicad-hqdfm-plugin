"""Property-based tests for point_to_line_distance.

These verify mathematical invariants without needing hypothesis.
"""

from math import isclose

import pytest

from kicad_dfm.settings.point_to_line_distance import point_to_line_distance

pytestmark = pytest.mark.pure


def test_distance_is_symmetric():
    line = {"start_x": 0, "start_y": 0, "end_x": 100, "end_y": 0}
    d1 = point_to_line_distance((30, 10), line)
    d2 = point_to_line_distance((70, -10), line)
    assert isclose(d1, d2, rel_tol=1e-9)


def test_point_on_line_returns_zero():
    for x in range(0, 101, 10):
        line = {"start_x": 0, "start_y": 0, "end_x": 100, "end_y": 50}
        t = x / 100
        px = 0 + t * 100
        py = 0 + t * 50
        dist = point_to_line_distance((px, py), line)
        assert isclose(dist, 0.0, abs_tol=1e-9), f"Point on line at t={t} returned {dist}"


def test_distance_non_negative():
    line = {"start_x": -50, "start_y": -50, "end_x": 50, "end_y": 50}
    for x in range(-100, 101, 10):
        for y in range(-100, 101, 10):
            dist = point_to_line_distance((x, y), line)
            assert dist >= 0 or isclose(dist, 0.0), f"Negative distance at ({x},{y}): {dist}"


def test_zero_length_segment():
    line = {"start_x": 5, "start_y": 5, "end_x": 5, "end_y": 5}
    for x, y in [(0, 0), (5, 5), (10, 10)]:
        dist = point_to_line_distance((x, y), line)
        assert dist == float("inf"), f"Expected inf for zero-length segment at ({x},{y})"


def test_vertical_line():
    line = {"start_x": 50, "start_y": 0, "end_x": 50, "end_y": 100}
    d = point_to_line_distance((30, 50), line)
    assert isclose(d, 20.0, rel_tol=1e-9)

    d = point_to_line_distance((80, 50), line)
    assert isclose(d, 30.0, rel_tol=1e-9)


def test_horizontal_line():
    line = {"start_x": 0, "start_y": 50, "end_x": 100, "end_y": 50}
    d = point_to_line_distance((50, 20), line)
    assert isclose(d, 30.0, rel_tol=1e-9)

    d = point_to_line_distance((50, 80), line)
    assert isclose(d, 30.0, rel_tol=1e-9)


def test_distance_continuity():
    """Small changes in input produce small changes in output."""
    line = {"start_x": 0, "start_y": 0, "end_x": 100, "end_y": 100}
    d1 = point_to_line_distance((25, 30), line)
    d2 = point_to_line_distance((26, 31), line)
    assert abs(d2 - d1) < 2.0
