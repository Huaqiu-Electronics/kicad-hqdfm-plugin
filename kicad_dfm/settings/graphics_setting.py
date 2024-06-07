from decimal import Decimal
import pcbnew
from kicad_dfm.settings.color_rule import ColorRule


class GraphicsSetting:
    def set_segment(self, line, result, x, y):
        line.SetShape(pcbnew.S_SEGMENT)

        line.SetEndX(int(Decimal(result["ex"]) * 1000000) + x)
        line.SetEndY(y - int(Decimal(result["ey"]) * 1000000))
        line.SetStartX(int(Decimal(result["sx"]) * 1000000) + x)
        line.SetStartY(y - int(Decimal(result["sy"]) * 1000000))

        return line

    def get_signal_integrity_segment(self, result, analysis_result, board, x, y):
        self.board = board
        line_coordinates = {
            "layer": result["layer"][0],
            "start_x": int(Decimal(result["sx"]) * 1000000) + x,
            "start_y": y - int(Decimal(result["sy"]) * 1000000),
            "end_x": int(Decimal(result["ex"]) * 1000000) + x,
            "end_y": y - int(Decimal(result["ey"]) * 1000000),
        }

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
        for item in self.board.GetTracks():  # Can be VIA or TRACK
            if (
                type(item) is pcbnew.PCB_TRACK
                and rect_coordinates["layer"] == item.GetLayerName()
            ):
                line = {
                    "layer": item.GetLayerName(),
                    "start_x": item.GetStart().x,
                    "start_y": item.GetStart().y,
                    "end_x": item.GetEndX(),
                    "end_y": item.GetEndY(),
                }

                if (
                    abs(rect_coordinates["start_x"] - line["start_x"]) < 10000
                    and abs(rect_coordinates["start_y"] - line["start_y"]) < 10000
                    and abs(rect_coordinates["end_x"] - line["end_x"]) < 10000
                    and abs(rect_coordinates["end_y"] - line["end_y"]) < 10000
                ):
                    line_uuid = item.m_Uuid
                    print(f"{line_uuid}")
                    return item

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


GRAPHICS_SETTING = GraphicsSetting
