from __future__ import annotations

from kicad_dfm.constants import EDGE_CUTS_LAYER_ID, NM_PER_MM, PRECISION_ASPECT_RATIO, SENTINEL_UNSET


class PcbSetting:
    def __init__(self, _board):
        self.board = _board

    def get_layer_size(self):
        drawings = self.board.GetDrawings()
        width = SENTINEL_UNSET
        for drawing in drawings:
            if drawing.GetLayer() == EDGE_CUTS_LAYER_ID:
                width = drawing.GetWidth() / NM_PER_MM

        box = self.board.GetBoardEdgesBoundingBox()
        box_x = box.GetWidth() / NM_PER_MM
        box_y = box.GetHeight() / NM_PER_MM
        if box_x == 0.0 or box_y == 0.0:
            return "0"
        board_w = round(box_x - width, PRECISION_ASPECT_RATIO)
        board_h = round(box_y - width, PRECISION_ASPECT_RATIO)
        return f"{board_w}*{board_h}"
