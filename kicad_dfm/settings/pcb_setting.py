class PcbSetting:
    def __init__(self, _board):
        self.board = _board

    # 处理 kicad 获取的层尺寸信息
    def get_layer_size(self):
        drawings = self.board.GetDrawings()
        width = 0
        for drawing in drawings:
            if drawing.GetLayer() == 44:
                width = drawing.GetWidth() / 1000000

        box = self.board.GetBoardEdgesBoundingBox()
        box_x = box.GetWidth() / 1000000
        box_y = box.GetHeight() / 1000000
        if box_x == 0.0 or box_y == 0.0:
            return "0"
        return str(round(box_x - width, 2)) + "*" + str(round(box_y - width, 2))
