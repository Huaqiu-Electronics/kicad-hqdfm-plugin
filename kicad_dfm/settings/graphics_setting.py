from decimal import Decimal
import pcbnew
from kicad_dfm.settings.color_rule import ColorRule
import wx
from math import sqrt
from .point_to_line_distance import point_to_line_distance

ERROR_RANGE = 0
EDGE_WIDTH_EXTEN = 100000
LINE_WIDTH_EXTEN = 80000

RECTANGLE = 1
ROUNDRECT = 4
CHAMFERED_RECT = 5


def analysis_line_and_arc(items, line_coordinates):
    for item in items:  # Can be VIA or TRACK
        if (
            type(item) is pcbnew.PCB_TRACK
            and line_coordinates["layer"] == item.GetLayerName()
        ):
            line = {
                "layer": item.GetLayerName(),
                "start_x": item.GetStart().x,
                "start_y": item.GetStart().y,
                "end_x": item.GetEndX(),
                "end_y": item.GetEndY(),
            }
            if (
                abs(line_coordinates["start_x"] - line["start_x"]) < 10000
                and abs(line_coordinates["start_y"] - line["start_y"]) < 10000
                and abs(line_coordinates["end_x"] - line["end_x"]) < 10000
                and abs(line_coordinates["end_y"] - line["end_y"]) < 10000
            ):
                return item


class GraphicsSetting:
    def set_segment(self, line, result, x, y):
        line.SetShape(pcbnew.S_SEGMENT)

        line.SetEndX(int(Decimal(result["ex"]) * 1000000) + x)
        line.SetEndY(y - int(Decimal(result["ey"]) * 1000000))
        line.SetStartX(int(Decimal(result["sx"]) * 1000000) + x)
        line.SetStartY(y - int(Decimal(result["sy"]) * 1000000))
        return line

    def set_arc(self, line, result, x, y):
        line.SetShape(pcbnew.S_ARC)
        line.SetEndX(int(Decimal(result["ex"]) * 1000000) + x)
        line.SetEndY(y - int(Decimal(result["ey"]) * 1000000))
        line.SetStartX(int(Decimal(result["sx"]) * 1000000) + x)
        line.SetStartY(y - int(Decimal(result["sy"]) * 1000000))
        line.SetCenter(
            int(Decimal(result["cx"]) * 1000000) + x,
            y - int(Decimal(result["cy"]) * 1000000),
        )
        return line

    def set_rect(self, line, result, x, y):
        line.SetShape(pcbnew.S_RECT)
        line.SetStartX(int(Decimal(result["cx"]) * 1000000) - 250000 + x)
        line.SetStartY(y - int(Decimal(result["cy"]) * 1000000) - 250000)
        line.SetEndX(int(Decimal(result["cx"]) * 1000000) + 250000 + x)
        line.SetEndY(y - int(Decimal(result["cy"]) * 1000000) + 250000)
        return line

    def set_rect_list(self, line, result, x, y):
        line.SetShape(pcbnew.S_RECT)
        line.SetStartX(int(Decimal(result["result"][0]) * 1000000) + x)
        line.SetStartY(y - int(Decimal(result["result"][3]) * 1000000))
        line.SetEndX(int(Decimal(result["result"][1]) * 1000000) + x)
        line.SetEndY(y - int(Decimal(result["result"][2]) * 1000000))
        return line

    def get_signal_integrity_segment(self, result, board, x, y):
        self.board = board
        line_coordinates = {
            "layer": result["layer"][0],
            "start_x": int(Decimal(result["sx"]) * 1000000) + x,
            "start_y": y - int(Decimal(result["sy"]) * 1000000),
            "end_x": int(Decimal(result["ex"]) * 1000000) + x,
            "end_y": y - int(Decimal(result["ey"]) * 1000000),
        }
        start_point = pcbnew.VECTOR2I(
            line_coordinates["start_x"], line_coordinates["start_y"]
        )
        end_point = pcbnew.VECTOR2I(
            line_coordinates["start_x"], line_coordinates["start_y"]
        )
        for item in self.board.GetTracks():  # Can be VIA or TRACK
            if (
                type(item) is pcbnew.PCB_TRACK
                and line_coordinates["layer"] == item.GetLayerName()
            ):
                line = {
                    "layer": item.GetLayerName(),
                    "start_x": item.GetStart().x,
                    "start_y": item.GetStart().y,
                    "end_x": item.GetEndX(),
                    "end_y": item.GetEndY(),
                }

                if (
                    abs(line_coordinates["start_x"] - line["start_x"]) < 10000
                    and abs(line_coordinates["start_y"] - line["start_y"]) < 10000
                    and abs(line_coordinates["end_x"] - line["end_x"]) < 10000
                    and abs(line_coordinates["end_y"] - line["end_y"]) < 10000
                ):
                    line_uuid = item.m_Uuid
                    print(f"{line_uuid}")
                    return item

        Drawings = self.board.GetDrawings()
        for Drawing in Drawings:
            if type(Drawing) is pcbnew.PCB_TEXT:
                hitconsequence = Drawing.TextHitTest(start_point)
                if hitconsequence:
                    return Drawing
                elif Drawing.TextHitTest(end_point):
                    return Drawing

    def get_signal_integrity_arc(self, result, board, x, y):
        self.board = board
        arc_coordinates = {
            "layer": result["layer"][0],
            "start_x": int(Decimal(result["sx"]) * 1000000) + x,
            "start_y": y - int(Decimal(result["sy"]) * 1000000),
            "end_x": int(Decimal(result["ex"]) * 1000000) + x,
            "end_y": y - int(Decimal(result["ey"]) * 1000000),
        }
        for item in self.board.GetTracks():  # Can be VIA or TRACK
            if (
                type(item) is pcbnew.PCB_TRACK
                and arc_coordinates["layer"] == item.GetLayerName()
            ):
                line = {
                    "layer": item.GetLayerName(),
                    "start_x": item.GetStart().x,
                    "start_y": item.GetStart().y,
                    "end_x": item.GetEndX(),
                    "end_y": item.GetEndY(),
                }

                if (
                    abs(arc_coordinates["start_x"] - line["start_x"]) < 10000
                    and abs(arc_coordinates["start_y"] - line["start_y"]) < 10000
                    and abs(arc_coordinates["end_x"] - line["end_x"]) < 10000
                    and abs(arc_coordinates["end_y"] - line["end_y"]) < 10000
                ):
                    line_uuid = item.m_Uuid
                    print(f"{line_uuid}")
                    return item

    def get_signal_integrity_rect(self, result, board, x, y):
        self.board = board
        rect_coordinates = {
            "layer": result["layer"][0],
            "start_x": (int(Decimal(result["cx"]) * 1000000) - 250000 + x),
            "start_y": (y - int(Decimal(result["cy"]) * 1000000) - 250000),
            "end_x": (int(Decimal(result["cx"]) * 1000000) + 250000 + x),
            "end_y": (y - int(Decimal(result["cy"]) * 1000000) + 250000),
        }
        layer = result.get("layer", [])
        tracks = self.board.GetTracks()
        for item in tracks:
            if type(item) is pcbnew.PCB_VIA:

                circle = {
                    "layer": item.GetLayerName(),
                    "start_x": item.GetStart().x,
                    "start_y": item.GetStart().y,
                    "end_x": item.GetEndX(),
                    "end_y": item.GetEndY(),
                }
                if (
                    rect_coordinates["start_x"]
                    <= circle["end_x"]
                    <= rect_coordinates["end_x"]
                    and rect_coordinates["start_y"]
                    <= circle["end_y"]
                    <= rect_coordinates["end_y"]
                ):
                    return item
        footprints = self.board.GetFootprints()
        for footprint in footprints:
            pads = footprint.Pads()
            if pads is None:
                continue
            for pad in pads:
                circle = {
                    "layer": pad.GetLayerName(),
                    "size_x": pad.GetSizeX(),
                    "size_y": pad.GetSizeY(),
                    "pad_position_x": pad.ShapePos().x,
                    "pad_position_y": pad.ShapePos().y,
                }
                if (
                    rect_coordinates["start_x"]
                    <= circle["pad_position_x"]
                    <= rect_coordinates["end_x"]
                    and rect_coordinates["start_y"]
                    <= circle["pad_position_y"]
                    <= rect_coordinates["end_y"]
                ):
                    return pad

    def get_spacing_judge_segment(self, result, board, x, y):
        self.board = board
        items = []
        line_coordinates = {
            "layer": result["layer"][0],
            "start_x": int(Decimal(result["sx"]) * 1000000) + x,
            "start_y": y - int(Decimal(result["sy"]) * 1000000),
            "end_x": int(Decimal(result["ex"]) * 1000000) + x,
            "end_y": y - int(Decimal(result["ey"]) * 1000000),
        }
        layer = result.get("layer", [])
        tracks = self.board.GetTracks()
        for item in tracks:
            if type(item) is pcbnew.PCB_TRACK and item.GetLayerName() in layer:

                line = {
                    "layer": item.GetLayerName(),
                    "start_x": item.GetStart().x,
                    "start_y": item.GetStart().y,
                    "end_x": item.GetEndX(),
                    "end_y": item.GetEndY(),
                    "line_width_y": item.GetWidth() / 2 + LINE_WIDTH_EXTEN,
                }
                # 计算 line_coordinates 的起点和终点到 line 的距离
                distance_start = point_to_line_distance(
                    (line_coordinates["start_x"], line_coordinates["start_y"]), line
                )
                distance_end = point_to_line_distance(
                    (line_coordinates["end_x"], line_coordinates["end_y"]), line
                )
                if (
                    line["line_width_y"] - distance_start >= ERROR_RANGE
                    or line["line_width_y"] - distance_end >= ERROR_RANGE
                ):
                    items.append(item)

            if type(item) is pcbnew.PCB_VIA:
                circle = {
                    "layer": item.GetLayerName(),
                    "size_x": item.GetWidth(),
                    "size_y": item.GetWidth(),
                    "position_x": item.GetEndX(),
                    "position_y": item.GetEndY(),
                }
                radius = circle["size_x"] / 2 + EDGE_WIDTH_EXTEN

                distance_start = sqrt(
                    (circle["position_x"] - line_coordinates["start_x"]) ** 2
                    + (circle["position_y"] - line_coordinates["start_y"]) ** 2
                )
                distance_end = sqrt(
                    (circle["position_x"] - line_coordinates["end_x"]) ** 2
                    + (circle["position_y"] - line_coordinates["end_y"]) ** 2
                )

                if (
                    radius - distance_start >= ERROR_RANGE
                    or radius - distance_end >= ERROR_RANGE
                ):
                    items.append(item)
                    # continue

        footprints = self.board.GetFootprints()
        for footprint in footprints:
            pads = footprint.Pads()
            fpAngle = footprint.GetOrientationDegrees()
            if pads is None:
                continue
            for pad in pads:
                padShape = pad.GetShape()
                if (
                    padShape == RECTANGLE
                    or padShape == ROUNDRECT
                    or padShape == CHAMFERED_RECT
                ):

                    rect = {
                        "layer": pad.GetLayerName(),
                        "size_x": pad.GetSizeX() + EDGE_WIDTH_EXTEN,
                        "size_y": pad.GetSizeY() + EDGE_WIDTH_EXTEN,
                        "pad_position_x": pad.ShapePos().x,
                        "pad_position_y": pad.ShapePos().y,
                        "pad_angle": fpAngle,
                    }
                    if rect["pad_angle"] == 90.0 or rect["pad_angle"] == -90.0:
                        rect_min_x = rect["pad_position_x"] - rect["size_y"] / 2
                        rect_max_x = rect["pad_position_x"] + rect["size_y"] / 2
                        rect_min_y = rect["pad_position_y"] - rect["size_x"] / 2
                        rect_max_y = rect["pad_position_y"] + rect["size_x"] / 2
                    else:
                        rect_min_x = rect["pad_position_x"] - rect["size_x"] / 2
                        rect_max_x = rect["pad_position_x"] + rect["size_x"] / 2
                        rect_min_y = rect["pad_position_y"] - rect["size_y"] / 2
                        rect_max_y = rect["pad_position_y"] + rect["size_y"] / 2

                    if (
                        rect_max_x >= line_coordinates["start_x"] >= rect_min_x
                        and rect_max_y >= line_coordinates["start_y"] >= rect_min_y
                    ):
                        items.append(pad)
                        # continue
                    if (
                        rect_max_x >= line_coordinates["end_x"] >= rect_min_x
                        and rect_max_y >= line_coordinates["end_y"] >= rect_min_y
                    ):
                        items.append(pad)
                        # continue

                else:
                    circle = {
                        "layer": pad.GetLayerName(),
                        "size_x": pad.GetSizeX() + EDGE_WIDTH_EXTEN,
                        "size_y": pad.GetSizeY() + EDGE_WIDTH_EXTEN,
                        "pad_position_x": pad.ShapePos().x,
                        "pad_position_y": pad.ShapePos().y,
                    }
                    radius = circle["size_x"] / 2
                    distance_start = sqrt(
                        (circle["pad_position_x"] - line_coordinates["start_x"]) ** 2
                        + (circle["pad_position_y"] - line_coordinates["start_y"]) ** 2
                    )

                    distance_end = sqrt(
                        (circle["pad_position_x"] - line_coordinates["end_x"]) ** 2
                        + (circle["pad_position_y"] - line_coordinates["end_y"]) ** 2
                    )

                    if (
                        radius - distance_start >= ERROR_RANGE
                        or radius - distance_end >= ERROR_RANGE
                    ):
                        items.append(pad)

        return items

    def get_board_edge_judge_segment(self, result, board, x, y):
        self.board = board
        items = []
        line_coordinates = {
            "layer": result["layer"][0],
            "start_x": int(Decimal(result["sx"]) * 1000000) + x,
            "start_y": y - int(Decimal(result["sy"]) * 1000000),
            "end_x": int(Decimal(result["ex"]) * 1000000) + x,
            "end_y": y - int(Decimal(result["ey"]) * 1000000),
        }
        layer = result.get("layer", [])

        zones = self.board.Zones()
        iter_proxy = zones.begin()
        while iter_proxy != zones.end():
            zone = iter_proxy.next()  # next() 是 SWIG 生成的方法

            layer_name = self.board.GetLayerName(zone.GetFirstLayer())
            if layer_name in layer:
                items.append(zone)
                continue

        Drawings = self.board.GetDrawings()
        for item in Drawings:
            if type(item) is pcbnew.PCB_SHAPE:
                line = {
                    "layer": item.GetLayerName(),
                    "start_x": item.GetStart().x,
                    "start_y": item.GetStart().y,
                    "end_x": item.GetEndX(),
                    "end_y": item.GetEndY(),
                    "line_width_y": item.GetWidth() / 2 + LINE_WIDTH_EXTEN,
                }
                distance_start = point_to_line_distance(
                    (line_coordinates["start_x"], line_coordinates["start_y"]), line
                )
                distance_end = point_to_line_distance(
                    (line_coordinates["end_x"], line_coordinates["end_y"]), line
                )
                if (
                    line["line_width_y"] - distance_start >= ERROR_RANGE
                    or line["line_width_y"] - distance_end >= ERROR_RANGE
                ):
                    items.append(item)
                    continue

        tracks = self.board.GetTracks()
        for item in tracks:
            if type(item) is pcbnew.PCB_TRACK and item.GetLayerName() in layer:
                line = {
                    "layer": item.GetLayerName(),
                    "start_x": item.GetStart().x,
                    "start_y": item.GetStart().y,
                    "end_x": item.GetEndX(),
                    "end_y": item.GetEndY(),
                    "line_width_y": item.GetWidth() / 2 + LINE_WIDTH_EXTEN,
                }
                # 计算 line_coordinates 的起点和终点到 line 的距离
                distance_start = point_to_line_distance(
                    (line_coordinates["start_x"], line_coordinates["start_y"]), line
                )
                distance_end = point_to_line_distance(
                    (line_coordinates["end_x"], line_coordinates["end_y"]), line
                )
                if (
                    line["line_width_y"] - distance_start >= ERROR_RANGE
                    or line["line_width_y"] - distance_end >= ERROR_RANGE
                ):
                    items.append(item)
                    # continue
            if type(item) is pcbnew.PCB_VIA:

                circle = {
                    "layer": item.GetLayerName(),
                    "size_x": item.GetWidth(),
                    "size_y": item.GetWidth(),
                    "position_x": item.GetEndX(),
                    "position_y": item.GetEndY(),
                }
                radius = circle["size_x"] / 2 + EDGE_WIDTH_EXTEN

                distance_start = sqrt(
                    (circle["position_x"] - line_coordinates["start_x"]) ** 2
                    + (circle["position_y"] - line_coordinates["start_y"]) ** 2
                )
                distance_end = sqrt(
                    (circle["position_x"] - line_coordinates["end_x"]) ** 2
                    + (circle["position_y"] - line_coordinates["end_y"]) ** 2
                )

                if (
                    radius - distance_start >= ERROR_RANGE
                    or radius - distance_end >= ERROR_RANGE
                ):
                    items.append(item)
                    # continue

        footprints = self.board.GetFootprints()
        for footprint in footprints:
            fpAngle = footprint.GetOrientationDegrees()
            pads = footprint.Pads()
            if pads is None:
                continue
            for pad in pads:
                padShape = pad.GetShape()
                if (
                    padShape == RECTANGLE
                    or padShape == ROUNDRECT
                    or padShape == CHAMFERED_RECT
                ):

                    rect = {
                        "layer": pad.GetLayerName(),
                        "size_x": pad.GetSizeX() + EDGE_WIDTH_EXTEN,
                        "size_y": pad.GetSizeY() + EDGE_WIDTH_EXTEN,
                        "pad_position_x": pad.ShapePos().x,
                        "pad_position_y": pad.ShapePos().y,
                        "pad_angle": fpAngle,
                    }
                    if rect["pad_angle"] == 90.0 or rect["pad_angle"] == -90.0:
                        rect_min_x = rect["pad_position_x"] - rect["size_y"] / 2
                        rect_max_x = rect["pad_position_x"] + rect["size_y"] / 2
                        rect_min_y = rect["pad_position_y"] - rect["size_x"] / 2
                        rect_max_y = rect["pad_position_y"] + rect["size_x"] / 2
                    else:
                        rect_min_x = rect["pad_position_x"] - rect["size_x"] / 2
                        rect_max_x = rect["pad_position_x"] + rect["size_x"] / 2
                        rect_min_y = rect["pad_position_y"] - rect["size_y"] / 2
                        rect_max_y = rect["pad_position_y"] + rect["size_y"] / 2

                    if (
                        rect_max_x >= line_coordinates["start_x"] >= rect_min_x
                        and rect_max_y >= line_coordinates["start_y"] >= rect_min_y
                    ):
                        items.append(pad)
                        # continue
                    if (
                        rect_max_x >= line_coordinates["end_x"] >= rect_min_x
                        and rect_max_y >= line_coordinates["end_y"] >= rect_min_y
                    ):
                        items.append(pad)
                        # continue

                else:
                    circle = {
                        "layer": pad.GetLayerName(),
                        "size_x": pad.GetSizeX() + EDGE_WIDTH_EXTEN,
                        "size_y": pad.GetSizeY() + EDGE_WIDTH_EXTEN,
                        "pad_position_x": pad.ShapePos().x,
                        "pad_position_y": pad.ShapePos().y,
                    }
                    radius = circle["size_x"] / 2
                    distance_start = sqrt(
                        (circle["pad_position_x"] - line_coordinates["start_x"]) ** 2
                        + (circle["pad_position_y"] - line_coordinates["start_y"]) ** 2
                    )

                    distance_end = sqrt(
                        (circle["pad_position_x"] - line_coordinates["end_x"]) ** 2
                        + (circle["pad_position_y"] - line_coordinates["end_y"]) ** 2
                    )

                    if (
                        radius - distance_start >= ERROR_RANGE
                        or radius - distance_end >= ERROR_RANGE
                    ):
                        items.append(pad)
        return items

    def get_pad_spacing_judge_segment(self, result, board, x, y):
        self.board = board
        items = []
        line_coordinates = {
            "layer": result["layer"][0],
            "start_x": int(Decimal(result["sx"]) * 1000000) + x,
            "start_y": y - int(Decimal(result["sy"]) * 1000000),
            "end_x": int(Decimal(result["ex"]) * 1000000) + x,
            "end_y": y - int(Decimal(result["ey"]) * 1000000),
        }
        layer = result.get("layer", [])
        tracks = self.board.GetTracks()
        for item in tracks:
            if type(item) is pcbnew.PCB_VIA:

                circle = {
                    "layer": item.GetLayerName(),
                    "size_x": item.GetWidth(),
                    "size_y": item.GetWidth(),
                    "position_x": item.GetEndX(),
                    "position_y": item.GetEndY(),
                }
                radius = circle["size_x"] / 2 + EDGE_WIDTH_EXTEN
                distance_start = sqrt(
                    (circle["position_x"] - line_coordinates["start_x"]) ** 2
                    + (circle["position_y"] - line_coordinates["start_y"]) ** 2
                )
                distance_end = sqrt(
                    (circle["position_x"] - line_coordinates["end_x"]) ** 2
                    + (circle["position_y"] - line_coordinates["end_y"]) ** 2
                )
                if (
                    radius - distance_start >= ERROR_RANGE
                    or radius - distance_end >= ERROR_RANGE
                ):
                    items.append(item)

        footprints = self.board.GetFootprints()
        for footprint in footprints:
            fpAngle = footprint.GetOrientationDegrees()
            pads = footprint.Pads()
            if pads is None:
                continue
            for pad in pads:
                padShape = pad.GetShape()
                if (
                    padShape == RECTANGLE
                    or padShape == ROUNDRECT
                    or padShape == CHAMFERED_RECT
                ):

                    rect = {
                        "layer": pad.GetLayerName(),
                        "size_x": pad.GetSizeX() + EDGE_WIDTH_EXTEN,
                        "size_y": pad.GetSizeY() + EDGE_WIDTH_EXTEN,
                        "pad_position_x": pad.ShapePos().x,
                        "pad_position_y": pad.ShapePos().y,
                        "pad_angle": fpAngle,
                    }
                    if rect["pad_angle"] == 90.0 or rect["pad_angle"] == -90.0:
                        rect_min_x = rect["pad_position_x"] - rect["size_y"] / 2
                        rect_max_x = rect["pad_position_x"] + rect["size_y"] / 2
                        rect_min_y = rect["pad_position_y"] - rect["size_x"] / 2
                        rect_max_y = rect["pad_position_y"] + rect["size_x"] / 2
                    else:
                        rect_min_x = rect["pad_position_x"] - rect["size_x"] / 2
                        rect_max_x = rect["pad_position_x"] + rect["size_x"] / 2
                        rect_min_y = rect["pad_position_y"] - rect["size_y"] / 2
                        rect_max_y = rect["pad_position_y"] + rect["size_y"] / 2

                    if (
                        rect_max_x >= line_coordinates["start_x"] >= rect_min_x
                        and rect_max_y >= line_coordinates["start_y"] >= rect_min_y
                    ):
                        items.append(pad)
                        continue
                    if (
                        rect_max_x >= line_coordinates["end_x"] >= rect_min_x
                        and rect_max_y >= line_coordinates["end_y"] >= rect_min_y
                    ):
                        items.append(pad)
                        continue

                else:
                    circle = {
                        "layer": pad.GetLayerName(),
                        "size_x": pad.GetSizeX() + EDGE_WIDTH_EXTEN,
                        "size_y": pad.GetSizeY() + EDGE_WIDTH_EXTEN,
                        "pad_position_x": pad.ShapePos().x,
                        "pad_position_y": pad.ShapePos().y,
                    }
                    radius = circle["size_x"] / 2
                    distance_start = sqrt(
                        (circle["pad_position_x"] - line_coordinates["start_x"]) ** 2
                        + (circle["pad_position_y"] - line_coordinates["start_y"]) ** 2
                    )
                    distance_end = sqrt(
                        (circle["pad_position_x"] - line_coordinates["end_x"]) ** 2
                        + (circle["pad_position_y"] - line_coordinates["end_y"]) ** 2
                    )
                    if (
                        radius - distance_start >= ERROR_RANGE
                        or radius - distance_end >= ERROR_RANGE
                    ):
                        items.append(pad)
        return items

    def get_SMD_pads_rect_list(self, result, board, x, y):
        self.board = board
        rect_coordinates = {
            "layer": result["layer"][0],
            "start_x": (int(Decimal(result["result"][0]) * 1000000) + x),
            "start_y": (y - int(Decimal(result["result"][3]) * 1000000)),
            "end_x": (int(Decimal(result["result"][1]) * 1000000) + x),
            "end_y": (y - int(Decimal(result["result"][2]) * 1000000)),
        }
        layer = result.get("layer", [])

        tracks = self.board.GetTracks()
        for item in tracks:
            if type(item) is pcbnew.PCB_VIA:
                circle = {
                    "layer": item.GetLayerName(),
                    "start_x": item.GetStart().x,
                    "start_y": item.GetStart().y,
                    "end_x": item.GetEndX(),
                    "end_y": item.GetEndY(),
                }
                if (
                    rect_coordinates["start_x"]
                    <= circle["end_x"]
                    <= rect_coordinates["end_x"]
                    and rect_coordinates["start_y"]
                    <= circle["end_y"]
                    <= rect_coordinates["end_y"]
                ):
                    return item

        footprints = self.board.GetFootprints()
        for footprint in footprints:
            pads = footprint.Pads()
            if pads is None:
                continue
            for pad in pads:
                result = {}
                if pad.GetLayerName() not in layer:
                    break
                circle = {
                    "layer": pad.GetLayerName(),
                    "size_x": pad.GetSizeX(),
                    "size_y": pad.GetSizeY(),
                    "pad_position_x": pad.ShapePos().x,
                    "pad_position_y": pad.ShapePos().y,
                }
                if (
                    rect_coordinates["start_x"]
                    <= circle["pad_position_x"]
                    <= rect_coordinates["end_x"]
                    and rect_coordinates["start_y"]
                    <= circle["pad_position_y"]
                    <= rect_coordinates["end_y"]
                ):
                    return pad


GRAPHICS_SETTING = GraphicsSetting
