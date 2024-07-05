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
ERROR_ACCURACY = 30000

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

    # ----------------------------------------------------------
    # ------------------get corresponding item------------------
    # ----------------------------------------------------------

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
        result = self.analysis_singal_tracks(
            items, line_coordinates, start_point, end_point
        )
        if result is not None:
            return result

        Drawings = self.board.GetDrawings()
        result = self.analysis_singal_drawings(
            Drawings, line_coordinates, start_point, end_point
        )
        if result is not None:
            return result

    def get_hole_diameter_segment(self, result, x, y):
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
        result = self.analysis_hole_diameter_vias(items, start_point, end_point)
        if result is not None:
            return result

        footprints = self.board.GetFootprints()
        result = self.analysis_singal_footprints(footprints, start_point, end_point)
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
        result = self.analysis_singal_tracks(
            items, arc_coordinates, start_point, end_point
        )
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
        start_point = pcbnew.VECTOR2I(
            line_coordinates["start_x"], line_coordinates["start_y"]
        )
        end_point = pcbnew.VECTOR2I(
            line_coordinates["end_x"], line_coordinates["end_y"]
        )
        if result["item"] == _("Via-to-Trace (Outer)") or result["item"] == _(
            "Via-to-Trace (Inner)"
        ):
            zones = self.board.Zones()
            self.analysis_zones(zones, layer, start_point, end_point, items)

        tracks = self.board.GetTracks()
        self.analysis_spacing_tracks(tracks, layer, start_point, end_point, items)

        footprints = self.board.GetFootprints()
        self.analysis_spacing_footprints(
            footprints, layer, start_point, end_point, items
        )

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

        start_point = pcbnew.VECTOR2I(
            line_coordinates["start_x"], line_coordinates["start_y"]
        )
        end_point = pcbnew.VECTOR2I(
            line_coordinates["end_x"], line_coordinates["end_y"]
        )
        zones = self.board.Zones()
        self.analysis_borad_edge_zones(zones, layer, start_point, end_point, items)

        Drawings = self.board.GetDrawings()
        self.analysis_board_edge_drawings(Drawings, start_point, end_point, items)

        tracks = self.board.GetTracks()
        self.analysis_spacing_tracks(tracks, layer, start_point, end_point, items)

        footprints = self.board.GetFootprints()
        self.analysis_spacing_footprints(
            footprints, layer, start_point, end_point, items
        )
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
        start_point = pcbnew.VECTOR2I(
            line_coordinates["start_x"], line_coordinates["start_y"]
        )
        end_point = pcbnew.VECTOR2I(
            line_coordinates["end_x"], line_coordinates["end_y"]
        )

        layer = result.get("layer", [])
        tracks = self.board.GetTracks()
        for item in tracks:
            result = self.analysis_spacing_via(item, start_point, end_point)
            if result is not None:
                items.append(result)

        footprints = self.board.GetFootprints()
        self.analysis_spacing_footprints(
            footprints, layer, start_point, end_point, items
        )
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
                hitconsequence = Drawing.HitTest(start_point, ERROR_ACCURACY)
                if (
                    hitconsequence
                    and Drawing.HitTest(end_point, ERROR_ACCURACY)
                    and line_coordinates["layer"] == Drawing.GetLayerName()
                ):
                    return Drawing

    def analysis_board_edge_drawings(self, Drawings, start_point, end_point, items):
        for item in Drawings:
            # 边框线
            if type(item) is pcbnew.PCB_SHAPE:
                hitstart = item.HitTest(start_point, ERROR_ACCURACY)
                hitend = item.HitTest(end_point, ERROR_ACCURACY)
                if hitstart or hitend:
                    items.append(item)

    def analysis_singal_tracks(self, items, line_coordinates, start_point, end_point):
        for item in items:  # Can be VIA or TRACK
            if (
                type(item) is pcbnew.PCB_TRACK
                and line_coordinates["layer"] == item.GetLayerName()
            ):
                hitstart = item.HitTest(start_point, ERROR_ACCURACY)
                hitend = item.HitTest(end_point, ERROR_ACCURACY)
                if hitstart and hitend:
                    return item

    def analysis_hole_diameter_vias(self, items, start_point, end_point):
        for item in items:
            if type(item) is pcbnew.PCB_VIA:
                hit_start = item.HitTest(start_point, ERROR_ACCURACY)
                hit_end = item.HitTest(end_point, ERROR_ACCURACY)
                if hit_start or hit_end:
                    return item

    def analysis_singal_footprints(self, footprints, start_point, end_point):
        for footprint in footprints:
            pads = footprint.Pads()
            if pads is None:
                return
            for pad in pads:
                hit_start = pad.HitTest(start_point, ERROR_ACCURACY)
                hit_end = pad.HitTest(end_point, ERROR_ACCURACY)
                if hit_start or hit_end:
                    return pad

    def analysis_spacing_via(self, item, start_point, end_point):
        if type(item) is pcbnew.PCB_VIA:
            hit_start = item.HitTest(start_point, ERROR_ACCURACY)
            hit_end = item.HitTest(end_point, ERROR_ACCURACY)
            if hit_start or hit_end:
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

    def analysis_spacing_footprints(
        self, footprints, layer, start_point, end_point, items
    ):
        for footprint in footprints:
            pads = footprint.Pads()
            if pads is None:
                continue
            for pad in pads:
                hit_start = pad.HitTest(start_point, ERROR_ACCURACY)
                hit_end = pad.HitTest(end_point, ERROR_ACCURACY)
                if hit_start or hit_end:
                    items.append(pad)

    def judge_hit_item(self, item, start_point, end_point):
        hit_start = item.HitTest(start_point, ERROR_ACCURACY)
        hit_end = item.HitTest(end_point, ERROR_ACCURACY)
        if hit_start or hit_end:
            return item

    def analysis_spacing_tracks(self, tracks, layer, start_point, end_point, items):
        for item in tracks:
            if type(item) is pcbnew.PCB_TRACK and item.GetLayerName() in layer:
                result = self.judge_hit_item(item, start_point, end_point)
                if result is not None:
                    items.append(result)

            result = self.analysis_spacing_via(item, start_point, end_point)
            if result is not None:
                items.append(result)

    def analysis_zones(self, zones, layer, start_point, end_point, items):
        iter_proxy = zones.begin()
        while iter_proxy != zones.end():
            zone = iter_proxy.next()
            layer_name = self.board.GetLayerName(zone.GetFirstLayer())
            hits = zone.HitTestFilledArea(
                zone.GetFirstLayer(), start_point, ERROR_ACCURACY
            )
            hite = zone.HitTestFilledArea(
                zone.GetFirstLayer(), end_point, ERROR_ACCURACY
            )
            if layer_name in layer:
                if hits or hite:
                    items.append(zone)

    def analysis_borad_edge_zones(self, zones, layer, start_point, end_point, items):
        iter_proxy = zones.begin()
        while iter_proxy != zones.end():
            zone = iter_proxy.next()
            layer_name = self.board.GetLayerName(zone.GetFirstLayer())
            if layer_name in layer:
                items.append(zone)
