import pytest

from kicad_dfm.settings.point_to_line_distance import LINE_WIDTH_EXTENT, point_to_line_distance

pytestmark = pytest.mark.pure


def test_point_to_line_distance_horizontal():
    line = {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": 0}
    dist = point_to_line_distance((5, 5), line)
    assert abs(dist - 5.0) < 1e-9


def test_point_to_line_distance_vertical():
    line = {"start_x": 0, "start_y": 0, "end_x": 0, "end_y": 10}
    dist = point_to_line_distance((5, 5), line)
    assert abs(dist - 5.0) < 1e-9


def test_point_to_line_distance_on_line():
    line = {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": 10}
    dist = point_to_line_distance((5, 5), line)
    assert abs(dist) < 1e-9


def test_point_to_line_distance_zero_length_segment():
    line = {"start_x": 0, "start_y": 0, "end_x": 0, "end_y": 0}
    dist = point_to_line_distance((5, 5), line)
    assert dist == float("inf")


def test_point_to_line_distance_off_segment():
    line = {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": 0}
    point = (50, 5)
    dist = point_to_line_distance(point, line)
    projection_within_bounds = -LINE_WIDTH_EXTENT <= point[0] <= 10 + LINE_WIDTH_EXTENT
    if projection_within_bounds:
        assert abs(dist - 5.0) < 1e-9
    else:
        assert dist == 1000000


def test_point_to_line_distance_diagonal():
    line = {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": 10}
    dist = point_to_line_distance((0, 10), line)
    expected = abs(100) / (10**2 + 10**2) ** 0.5
    assert abs(dist - expected) < 1e-9


def test_point_to_line_distance_diagonal_off_segment():
    line = {"start_x": 0, "start_y": 0, "end_x": 10, "end_y": 10}
    dist = point_to_line_distance((200000, 0), line)
    assert dist == 1000000
