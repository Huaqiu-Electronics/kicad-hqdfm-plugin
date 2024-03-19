import pcbnew
from kicad_dfm.custom_contral.custom_listbox import CustomListBox


class ChildFrameModel:
    def __init__(self, result_json, json_string, kicad=False):
        self.result_json = result_json
        self.json_string = json_string
        self.kicad = kicad

    def get_layer(self):
        layer = []
        if self.result_json[self.json_string] == "":
            return layer
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                if self.kicad is False:
                    result["layer"] = self.layer_conversion(result["layer"])
                if result["layer"][0] not in layer:
                    layer.append(result["layer"][0])
        return layer

    def get_type(self):
        analysis_type = []
        if self.result_json[self.json_string] == "":
            return analysis_type
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                if result["item"] not in analysis_type:
                    analysis_type.append(result["item"])
        return analysis_type

    def get_result(self):
        analysis_result = []
        if self.result_json[self.json_string] == "":
            return analysis_result
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                if result["value"] not in analysis_result:
                    analysis_result.append(result["value"])
        return analysis_result

    def layer_conversion(self, layer_result):
        if (
            self.json_string == "Hatched Copper Pour"
            or self.json_string == "Pad size"
            or self.json_string == "Smallest Trace Width"
            or self.json_string == "RingHole"
        ):
            return layer_result
        kicad_layer = {}
        kicad_layer["Top Silk"] = self.board.GetLayerName(37)
        kicad_layer["Top Solder"] = self.board.GetLayerName(39)
        kicad_layer["Top Layer"] = self.board.GetLayerName(0)
        kicad_layer["Bot Silk"] = self.board.GetLayerName(36)
        kicad_layer["Bot Solder"] = self.board.GetLayerName(38)
        kicad_layer["Bot Layer"] = self.board.GetLayerName(31)
        kicad_layer["Outline"] = self.board.GetLayerName(44)
        kicad_layer["Top Paste"] = self.board.GetLayerName(35)
        kicad_layer["Bot Paste"] = self.board.GetLayerName(34)
        for i in range(2, 32):
            kicad_layer[f"Inner{i}"] = self.board.GetLayerName(i - 1)

        for k, v in enumerate(layer_result):
            layer = v
            if layer in kicad_layer.keys():
                layer = layer.replace(layer, kicad_layer[layer])
            layer_result[k] = layer

        return layer_result
