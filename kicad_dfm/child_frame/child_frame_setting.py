from kicad_dfm.constants import (
    LAYER_B_CU,
    LAYER_B_MASK,
    LAYER_B_PASTE,
    LAYER_B_SILK,
    LAYER_COUNT_MAX,
    LAYER_EDGE_CUTS,
    LAYER_F_CU,
    LAYER_F_MASK,
    LAYER_F_PASTE,
    LAYER_F_SILK,
    LAYER_IN2_CU,
    LAYER_IN3_CU,
    LAYER_INNER_END,
    LAYER_INNER_START,
    LAYER_INNER_STEP,
    MILS_PER_MM,
    MM_PER_INCH,
    PRECISION_STANDARD,
)


class ChildFrameSetting:
    def __init__(self, _board):
        self.board = _board

    def layer_conversion(self, json_string, layer_result):
        if json_string in ("Hatched Copper Pour", "Pad size", "Smallest Trace Width", "RingHole"):
            return layer_result
        kicad_layer = {}
        for i in range(LAYER_COUNT_MAX):
            kicad_layer[f"Inner{i}"] = self.board.GetLayerName(i)

        kicad_layer["Top Silk"] = self.board.GetLayerName(LAYER_F_SILK)
        kicad_layer["Top Solder"] = self.board.GetLayerName(LAYER_F_MASK)
        kicad_layer["Top Layer"] = self.board.GetLayerName(LAYER_F_CU)
        kicad_layer["Bot Silk"] = self.board.GetLayerName(LAYER_B_SILK)
        kicad_layer["Bot Solder"] = self.board.GetLayerName(LAYER_B_MASK)
        kicad_layer["Bot Layer"] = self.board.GetLayerName(LAYER_B_CU)
        kicad_layer["Outline"] = self.board.GetLayerName(LAYER_EDGE_CUTS)
        kicad_layer["Top Paste"] = self.board.GetLayerName(LAYER_F_PASTE)
        kicad_layer["Bot Paste"] = self.board.GetLayerName(LAYER_B_PASTE)
        kicad_layer["Inner2"] = self.board.GetLayerName(LAYER_IN2_CU)
        kicad_layer["Inner3"] = self.board.GetLayerName(LAYER_IN3_CU)
        for i in range(LAYER_INNER_START, LAYER_INNER_END, LAYER_INNER_STEP):
            kicad_layer[f"Inner{i // 2}"] = self.board.GetLayerName(i)

        if isinstance(layer_result, str):
            if layer_result in kicad_layer:
                layer_result = kicad_layer[layer_result]
        elif isinstance(layer_result, list):
            for i, layer in enumerate(layer_result):
                if layer in kicad_layer:
                    layer_result[i] = kicad_layer[layer]
        return layer_result


class ChildFrameUnitConversion:
    @staticmethod
    def Millimeter2iu(value_mm):
        return round(value_mm / MM_PER_INCH, PRECISION_STANDARD)

    @staticmethod
    def Millimeter2mils(value_mm):
        return round((value_mm * MILS_PER_MM), PRECISION_STANDARD)

    @staticmethod
    def multi_string_conversion(prefix, value, length):
        return prefix + "、" + value + ", " + str(length) + _("pcs")

    @staticmethod
    def string_conversion(prefix, value):
        if isinstance(value, (int, float)):
            value = f"{value:.{PRECISION_STANDARD}f}"
        return prefix + "、" + value


CHILDFRAME_UNIT_CONVERSION = ChildFrameUnitConversion
