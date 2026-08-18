class PcbSetting:
    def __init__(self, _board):
        self.board = _board

    @staticmethod
    def _drawing_line_width_nm(drawing):
        # KiCad 9+ replaced PCB_SHAPE.GetWidth() with GetStroke().GetWidth()
        for method in ("GetWidth", "GetLineWidth"):
            if hasattr(drawing, method):
                try:
                    return getattr(drawing, method)()
                except Exception:
                    pass
        if hasattr(drawing, "GetStroke"):
            try:
                return drawing.GetStroke().GetWidth()
            except Exception:
                pass
        return 0

    # 处理 kicad 获取的层尺寸信息
    def get_layer_size(self):
        drawings = self.board.GetDrawings()
        width = 0
        for drawing in drawings:
            try:
                if drawing.GetLayer() == 44:
                    width = self._drawing_line_width_nm(drawing) / 1000000
            except Exception:
                pass

        try:
            box = self.board.GetBoardEdgesBoundingBox()
            box_x = box.GetWidth() / 1000000
            box_y = box.GetHeight() / 1000000
        except Exception:
            return "0"
        if box_x == 0.0 or box_y == 0.0:
            return "0"
        return str(round(box_x - width, 2)) + "*" + str(round(box_y - width, 2))
