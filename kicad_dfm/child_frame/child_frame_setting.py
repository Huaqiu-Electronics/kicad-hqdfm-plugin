import pcbnew


class ChildFrameSetting:
    def __init__(self, _board):
        self.board = _board

    def layer_conversion(self, json_string, layer_result):
        if (
            json_string == "Hatched Copper Pour"
            or json_string == "Pad size"
            or json_string == "Smallest Trace Width"
            or json_string == "RingHole"
        ):
            return layer_result
        kicad_layer = {}
        _layer = {}
        for i in range(0, 82):
            _layer[f"Inner{i}"] = self.board.GetLayerName(i)
        
        kicad_layer["Top Silk"] = self.board.GetLayerName(5)
        kicad_layer["Top Solder"] = self.board.GetLayerName(1)
        kicad_layer["Top Layer"] = self.board.GetLayerName(0)
        kicad_layer["Bot Silk"] = self.board.GetLayerName(7)
        kicad_layer["Bot Solder"] = self.board.GetLayerName(3)
        kicad_layer["Bot Layer"] = self.board.GetLayerName(2)
        kicad_layer["Outline"] = self.board.GetLayerName(25)
        kicad_layer["Top Paste"] = self.board.GetLayerName(35)
        kicad_layer["Bot Paste"] = self.board.GetLayerName(33)
        kicad_layer["Inner2"] = self.board.GetLayerName(4)
        kicad_layer["Inner3"] = self.board.GetLayerName(6)
        for i in range(8, 66, 2):
            kicad_layer[f"Inner{ i//2 }"] = self.board.GetLayerName( i )

        if isinstance(layer_result, str):  # 如果 layer_result 是字符串
            if layer_result in kicad_layer.keys():
                layer_result = kicad_layer[layer_result]
        elif isinstance(layer_result, list):  # 如果 layer_result 是列表
            for i, layer in enumerate(layer_result):
                if layer in kicad_layer.keys():
                    layer_result[i] = kicad_layer[layer]
        return layer_result


class ChildFrameUnitConversion:
    def Millimeter2iu(millimeter_value):
        return round(millimeter_value / 25.4, 3)

    def Millimeter2mils(millimeter_value):
        return round((millimeter_value * 39.37), 3)

    def multi_string_conversion(num, value, length):
        string = num + "、" + value + ", " + str(length) + _("pcs")
        return string

    def string_conversion(num, value):
        if isinstance(value, (int, float)):
            value = f"{value:.3f}"
        print(f"value: {str(type(value))}")
        string = num + "、" + value
        return string


CHILDFRAME_UNIT_CONVERSION = ChildFrameUnitConversion
