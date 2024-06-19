from decimal import Decimal
import pcbnew
from kicad_dfm.settings.color_rule import ColorRule
import wx
from math import sqrt
from .point_to_line_distance import point_to_line_distance
from kicad_dfm.settings.timestamp import TimeStamp

ERROR_RANGE = 0
EDGE_WIDTH_EXTEN = 100000
LINE_WIDTH_EXTEN = 80000

RECTANGLE = 1
ROUNDRECT = 4
CHAMFERED_RECT = 5

B_PASTE = 34
F_PASTE = 35


class GraphicsSetting:
    def __init__(self, _board):
        self.board = _board
        self.timestamp_logger = TimeStamp()

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

    def get_signal_integrity_segment(self, result, x, y):

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
            line_coordinates["end_x"], line_coordinates["end_y"]
        )
        items = self.board.GetTracks()

        result = self.analysis_singal_tracks(items, line_coordinates)
        if result is not None:
            return result

        Drawings = self.board.GetDrawings()
        result = self.analysis_singal_drawings(
            Drawings, line_coordinates, start_point, end_point
        )
        if result is not None:
            return result

    def get_signal_integrity_arc(self, result, x, y):
        arc_coordinates = {
            "layer": result["layer"][0],
            "start_x": int(Decimal(result["sx"]) * 1000000) + x,
            "start_y": y - int(Decimal(result["sy"]) * 1000000),
            "end_x": int(Decimal(result["ex"]) * 1000000) + x,
            "end_y": y - int(Decimal(result["ey"]) * 1000000),
        }
        start_point = pcbnew.VECTOR2I(
            arc_coordinates["start_x"], arc_coordinates["start_y"]
        )
        end_point = pcbnew.VECTOR2I(arc_coordinates["end_x"], arc_coordinates["end_x"])
        items = self.board.GetTracks()
        result = self.analysis_singal_tracks(items, arc_coordinates)
        if result is not None:
            return result

        Drawings = self.board.GetDrawings()
        result = self.analysis_singal_drawings(
            Drawings, arc_coordinates, start_point, end_point
        )
        if result is not None:
            return result

    def get_signal_integrity_rect(self, result, x, y):
        rect_coordinates = {
            "layer": result["layer"][0],
            "start_x": (int(Decimal(result["cx"]) * 1000000) - 250000 + x),
            "start_y": (y - int(Decimal(result["cy"]) * 1000000) - 250000),
            "end_x": (int(Decimal(result["cx"]) * 1000000) + 250000 + x),
            "end_y": (y - int(Decimal(result["cy"]) * 1000000) + 250000),
        }
        layer = result.get("layer", [])

        tracks = self.board.GetTracks()
        result = self.analysis_rect_to_vias(tracks, rect_coordinates)
        if result is not None:
            return result

        footprints = self.board.GetFootprints()
        result = self.analysis_rect_to_footprints(footprints, rect_coordinates, layer)
        if result is not None:
            return result

    def get_spacing_judge_segment(self, result, x, y):
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

        self.analysis_spacing_tracks(tracks, layer, line_coordinates, items)

        footprints = self.board.GetFootprints()
        self.analysis_spacing_footprints(footprints, layer, line_coordinates, items)

        return items

    def get_board_edge_judge_segment(self, result, x, y):
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
            zone = iter_proxy.next()
            layer_name = self.board.GetLayerName(zone.GetFirstLayer())
            if layer_name in layer:
                items.append(zone)
                continue

        Drawings = self.board.GetDrawings()
        self.analysis_board_edge_drawings(Drawings, line_coordinates, items)

        tracks = self.board.GetTracks()
        self.analysis_spacing_tracks(tracks, layer, line_coordinates, items)

        footprints = self.board.GetFootprints()
        self.analysis_spacing_footprints(footprints, layer, line_coordinates, items)

        return items

    def get_pad_spacing_judge_segment(self, result, x, y):
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
            result = self.analysis_spacing_via(item, line_coordinates)
            if result is not None:
                items.append(result)

        footprints = self.board.GetFootprints()
        self.analysis_spacing_footprints(footprints, layer, line_coordinates, items)
        return items

    def get_SMD_pads_rect_list(self, result, x, y):
        rect_coordinates = {
            "layer": result["layer"][0],
            "start_x": (int(Decimal(result["result"][0]) * 1000000) + x),
            "start_y": (y - int(Decimal(result["result"][3]) * 1000000)),
            "end_x": (int(Decimal(result["result"][1]) * 1000000) + x),
            "end_y": (y - int(Decimal(result["result"][2]) * 1000000)),
        }
        layer = result.get("layer", [])

        tracks = self.board.GetTracks()
        result = self.analysis_rect_to_vias(tracks, rect_coordinates)
        if result is not None:
            return result

        footprints = self.board.GetFootprints()
        result = self.analysis_rect_to_footprints(footprints, rect_coordinates, layer)
        if result is not None:
            return result

    # ---------------------------------------------------------------------
    # ---------------- Get board_item from kicad  -------------------------
    # ---------------------------------------------------------------------

    def analysis_singal_drawings(
        self, Drawings, line_coordinates, start_point, end_point
    ):
        for Drawing in Drawings:
            if type(Drawing) is pcbnew.PCB_TEXT:
                hitconsequence = Drawing.HitTest(start_point, 0)
                if (
                    hitconsequence
                    and Drawing.HitTest(end_point, 0)
                    and line_coordinates["layer"] == Drawing.GetLayerName()
                ):
                    return Drawing

    def analysis_board_edge_drawings(self, Drawings, line_coordinates, items):
        for item in Drawings:
            # 边框线
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

    def analysis_singal_tracks(self, items, line_coordinates):
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

    def analysis_spacing_via(self, item, line_coordinates):
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
                return item

    def analysis_rect_to_vias(self, tracks, rect_coordinates):
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

    def analysis_rect_to_footprints(self, footprints, rect_coordinates, layer):
        for footprint in footprints:
            pads = footprint.Pads()
            fpLayerName = self.board.GetLayerName(footprint.GetSide())
            fpTypeName = footprint.GetTypeName()
            if pads is None:
                return
            for pad in pads:
                if fpTypeName == "SMD":
                    if fpLayerName not in layer:
                        break
                    circle = {
                        "layer": fpLayerName,
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
                else:
                    circle = {
                        "layer": fpLayerName,
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

    def analysis_spacing_footprints(self, footprints, layer, line_coordinates, items):
        for footprint in footprints:
            pads = footprint.Pads()
            fpAngle = footprint.GetOrientationDegrees()
            fpLayerName = self.board.GetLayerName(footprint.GetSide())
            fpTypeName = footprint.GetTypeName()
            if pads is None:
                continue
            if fpTypeName == "SMD":
                if (
                    fpLayerName in layer
                    or self.board.GetLayerName(F_PASTE) in layer
                    or self.board.GetLayerName(B_PASTE) in layer
                ):
                    for pad in pads:
                        result = self.analysis_footprint_in_pad(
                            pad, fpAngle, line_coordinates
                        )
                        if result is not None:
                            items.append(result)
            else:
                for pad in pads:
                    result = self.analysis_footprint_in_pad(
                        pad, fpAngle, line_coordinates
                    )
                    if result is not None:
                        items.append(result)

    def analysis_footprint_in_pad(self, pad, fpAngle, line_coordinates):
        padShape = pad.GetShape()
        if padShape in {RECTANGLE, ROUNDRECT, CHAMFERED_RECT}:
            rect = {
                "layer": "",
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
                return pad
            if (
                rect_max_x >= line_coordinates["end_x"] >= rect_min_x
                and rect_max_y >= line_coordinates["end_y"] >= rect_min_y
            ):
                return pad
        else:
            circle = {
                "layer": "",
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
                return pad

    def analysis_spacing_tracks(self, tracks, layer, line_coordinates, items):
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

            result = self.analysis_spacing_via(item, line_coordinates)
            if result is not None:
                items.append(result)
