import pcbnew
from kicad_dfm.core.units import mm_to_inches, mm_to_mils


class ChildFrameSetting:
    def __init__(self, _board):
        self.board = _board

    def layer_conversion(self, json_string, layer_result):
        if (
            json_string == "Pad size"
            or json_string == "Smallest Trace Width"
            or json_string == "RingHole"
        ):
            return layer_result
        kicad_layer = self.layer_name_map()

        if isinstance(layer_result, str):  # 如果 layer_result 是字符串
            if layer_result in kicad_layer.keys():
                layer_result = kicad_layer[layer_result]
        elif isinstance(layer_result, list):  # 如果 layer_result 是列表
            for i, layer in enumerate(layer_result):
                if layer in kicad_layer.keys():
                    layer_result[i] = kicad_layer[layer]
        return layer_result

    def layer_name_map(self):
        kicad_layer = {}
        for source, const_name in (
            ("Top Silk", "F_SilkS"),
            ("Top Solder", "F_Mask"),
            ("Top Layer", "F_Cu"),
            ("Bot Silk", "B_SilkS"),
            ("Bot Solder", "B_Mask"),
            ("Bot Layer", "B_Cu"),
            ("Outline", "Edge_Cuts"),
            ("Top Paste", "F_Paste"),
            ("Bot Paste", "B_Paste"),
        ):
            layer_name = self.safe_layer_name(getattr(pcbnew, const_name, None))
            if layer_name:
                kicad_layer[source] = layer_name

        try:
            copper_count = int(self.board.GetCopperLayerCount())
        except Exception:
            copper_count = 0
        for inner_index in range(1, max(copper_count - 1, 1)):
            layer_name = self.safe_layer_name(inner_index)
            if layer_name:
                kicad_layer[f"Inner{inner_index + 1}"] = layer_name
        return kicad_layer

    def safe_layer_name(self, layer_id):
        if layer_id is None:
            return None
        try:
            return self.board.GetLayerName(layer_id)
        except Exception:
            return None


class ChildFrameUnitConversion:
    def Millimeter2iu(millimeter_value):
        return round(mm_to_inches(millimeter_value), 3)

    def Millimeter2mils(millimeter_value):
        return round(mm_to_mils(millimeter_value), 3)

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
