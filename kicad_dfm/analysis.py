import pcbnew

from kicad_dfm.constants import (
    DRILL_SHAPE_CIRCLE,
    NM_PER_MM,
    PAD_ATTR_NPTH,
    PAD_ATTR_THT,
    PAD_LONG_THRESHOLD_MM,
    PAD_SHAPE_CIRCLE,
    SENTINEL_DISPLAY_NORMAL,
    SENTINEL_UNSET,
    ZONE_FILL_MODE_HATCHED,
    Colour,
)
from kicad_dfm.models import AnalysisResult, maybe_validate
from kicad_dfm.settings.color_rule import ColorRule


class MinimumLineWidth:
    def __init__(self, control, _board):
        self.language = control
        self.board = _board

    def get_pad(self, analysis_result):
        pad_result = {}
        result_list = []
        layer_list = []
        minimum = SENTINEL_UNSET
        have_red = False
        have_yellow = False
        if analysis_result["Pad size"] == "" or analysis_result["Pad size"]["check"] is None:
            return ""

        footprints = self.board.GetFootprints()
        for footprint in footprints:
            pads = footprint.Pads()
            if pads is None:
                continue
            for pad in pads:
                pad_value = {}
                result = {}
                item_list = []
                pad_shape = pad.GetAttribute()
                size_shape = pad.GetShape()
                drill_shape = pad.GetDrillShape()
                if pad_shape in (PAD_ATTR_NPTH, PAD_ATTR_THT):
                    continue
                if size_shape == PAD_SHAPE_CIRCLE:
                    drill_x = round(pad.GetDrillSizeX() / NM_PER_MM, 3)
                    drill_y = round(pad.GetDrillSizeY() / NM_PER_MM, 3)
                    drill_minimum_width = drill_y if drill_y < drill_x else drill_x
                    different = abs(drill_x - drill_y)
                else:
                    drill_x = pad.GetSizeX()
                    drill_y = pad.GetSizeY()
                    drill_minimum_width = drill_y if drill_y < drill_x else drill_x
                    different = abs(drill_x - drill_y)
                if drill_shape == DRILL_SHAPE_CIRCLE:
                    drill_x = pad.GetDrillSizeX()
                    drill_y = pad.GetDrillSizeY()
                    drill_minimum_width = drill_y if drill_y > drill_x else drill_x
                else:
                    size_x = pad.GetSizeX()
                    size_y = pad.GetSizeY()
                    size_minimum_width = size_y if size_y > size_x else size_x

                if abs(size_minimum_width) - abs(drill_minimum_width) < minimum or minimum == SENTINEL_UNSET:
                    minimum = abs(size_minimum_width) - abs(drill_minimum_width)
                pad_value["value"] = str(round(abs(size_minimum_width) - abs(drill_minimum_width), 3))
                pad_value["id"] = pad.m_Uuid
                layer_list.append(str(pad.GetLayerName()))
                pad_value["layer"] = layer_list
                if different > PAD_LONG_THRESHOLD_MM:
                    pad_value["item"] = _("Long Pads")
                else:
                    pad_value["item"] = _("Short Pads")
                    pad_value["color"] = ColorRule().get_rule(analysis_result, "Pad size", pad_value["item"], different)
                    if pad_value["color"] == Colour.RED:
                        have_red = True
                    elif pad_value["color"] == Colour.GOLD:
                        have_yellow = True
                    else:
                        pad_value["color"] = Colour.BLACK
                item_list.append(pad_value)
                result["result"] = item_list
                result_list.append(result)

        if minimum == SENTINEL_UNSET:
            pad_result["display"] = SENTINEL_DISPLAY_NORMAL
        else:
            pad_result["display"] = minimum
        pad_result["check"] = result_list
        if have_red:
            pad_result["color"] = Colour.RED
        elif have_yellow:
            pad_result["color"] = Colour.GOLD
        else:
            pad_result["color"] = Colour.BLACK
        return maybe_validate(AnalysisResult, pad_result)

    def get_annular_ring(self, analysis_result):
        annular_ring_result = {}
        result_list = []
        annular_ring_layer = []
        annular_ring_minimum = -1
        have_red = False
        have_yellow = False
        if analysis_result["RingHole"] == "":
            return ""
        if analysis_result["RingHole"]["check"] == "":
            return ""
        via_annular_ring_value = ColorRule().filter_rule_value(analysis_result, "RingHole", _("Via Annular Ring"))
        pth_annular_ring_value = ColorRule().filter_rule_value(analysis_result, "RingHole", _("PTH Annular Ring"))
        # wx.MessageBox(f"{via_annular_ring_value}")
        tracks = self.board.GetTracks()
        for item in tracks:
            if type(item) is pcbnew.PCB_VIA:
                annular_ring = {}
                result = {}
                item_list = []
                width = round(float(item.GetWidth()) / NM_PER_MM, 3)
                drill = round(float(item.GetDrill()) / NM_PER_MM, 3)
                value = round((width - drill) / 2, 3)
                if not via_annular_ring_value:
                    break
                if value <= via_annular_ring_value:
                    annular_ring["value"] = str(value)
                    annular_ring_layer.append(item.GetLayerName())
                    annular_ring["id"] = item.m_Uuid
                    annular_ring["pad_diameter"] = width
                    annular_ring["hole_diameter"] = drill
                    annular_ring["layer"] = annular_ring_layer
                    annular_ring["item"] = _("Via Annular Ring")
                    annular_ring["color"] = ColorRule().get_rule(analysis_result, "RingHole", "Via Annular Ring", value)

                    if annular_ring["color"] == Colour.RED:
                        have_red = True
                    elif annular_ring["color"] == Colour.GOLD:
                        have_yellow = True

                    item_list.append(annular_ring)
                    result["result"] = item_list
                    result_list.append(result)
                    if value < annular_ring_minimum or annular_ring_minimum == SENTINEL_UNSET:
                        annular_ring_minimum = value
        footprints = self.board.GetFootprints()
        for footprint in footprints:
            pads = footprint.Pads()
            if pads is None:
                continue
            for pad in pads:
                result = {}
                item_list = []
                pad_shape = pad.GetAttribute()
                size_shape = pad.GetShape()
                drill_shape = pad.GetDrillShape()
                if pad_shape != PAD_ATTR_THT:
                    continue
                if size_shape == PAD_SHAPE_CIRCLE and drill_shape == DRILL_SHAPE_CIRCLE:
                    annular_ring = {}
                    size_x = round(float(pad.GetSizeX()) / NM_PER_MM, 3)
                    drill_x = round(float(pad.GetDrillSizeX()) / NM_PER_MM, 3)
                    value = round((size_x - drill_x) / 2, 3)
                    if not pth_annular_ring_value:
                        break
                    if value <= pth_annular_ring_value:
                        annular_ring["value"] = str(value)
                        annular_ring_layer.append(pad.GetLayerName())
                        annular_ring["id"] = pad.m_Uuid
                        annular_ring["pad_diameter"] = size_x
                        annular_ring["hole_diameter"] = drill_x
                        annular_ring["layer"] = annular_ring_layer
                        annular_ring["item"] = _("PTH Annular Ring")
                        annular_ring["color"] = ColorRule().get_rule(
                            analysis_result,
                            "RingHole",
                            "PTH Annular Ring",
                            value,
                        )
                        if annular_ring["color"] == Colour.RED:
                            have_red = True
                        elif annular_ring["color"] == Colour.GOLD:
                            have_yellow = True
                        item_list.append(annular_ring)
                        result["result"] = item_list
                        result_list.append(result)
                        if value < annular_ring_minimum or annular_ring_minimum == SENTINEL_UNSET:
                            annular_ring_minimum = value
        if annular_ring_minimum == SENTINEL_UNSET:
            annular_ring_result["display"] = SENTINEL_DISPLAY_NORMAL
        else:
            annular_ring_result["display"] = annular_ring_minimum
        annular_ring_result["check"] = result_list
        if have_red is True:
            annular_ring_result["color"] = Colour.RED
        elif have_yellow is True:
            annular_ring_result["color"] = Colour.GOLD
        else:
            annular_ring_result["color"] = Colour.BLACK
        if not result_list:
            annular_ring_result = ""
        if isinstance(annular_ring_result, dict):
            return maybe_validate(AnalysisResult, annular_ring_result)
        return annular_ring_result

    # 最小线宽
    def get_line_width(self, analysis_result):
        line_width_result = {}
        result_list = []
        line_width_minimum = SENTINEL_UNSET
        have_red = False
        have_yellow = False
        smallest_trace = analysis_result.get("Smallest Trace Width", {})
        if smallest_trace == "" or smallest_trace.get("check") is None:
            return ""
        for item in self.board.GetTracks():
            if type(item) is pcbnew.PCB_TRACK:
                line_width = {}
                result = {}
                item_list = []
                line_width_layer = []
                line_width["id"] = item.m_Uuid
                width = round(float(item.GetWidth()) / NM_PER_MM, 3)
                line_width_layer.append(item.GetLayerName())
                line_width["layer"] = line_width_layer
                line_width["value"] = str(width)
                line_width["info"] = item.m_Uuid
                line_width["item"] = _("Smallest Trace Width")
                line_width["color"] = ColorRule().get_rule(
                    analysis_result,
                    "Smallest Trace Width",
                    "Smallest Trace Width",
                    width,
                )
                if line_width["color"] == Colour.RED:
                    have_red = True
                elif line_width["color"] == Colour.GOLD:
                    have_yellow = True
                item_list.append(line_width)
                result["result"] = item_list
                result_list.append(result)
                if width < line_width_minimum or line_width_minimum == SENTINEL_UNSET:
                    line_width_minimum = width
        if line_width_minimum == SENTINEL_UNSET:
            line_width_result["display"] = SENTINEL_DISPLAY_NORMAL
        else:
            line_width_result["display"] = line_width_minimum

        line_width_result["check"] = result_list
        if have_red is True:
            line_width_result["color"] = Colour.RED
        elif have_yellow is True:
            line_width_result["color"] = Colour.GOLD
        else:
            line_width_result["color"] = Colour.BLACK
        return maybe_validate(AnalysisResult, line_width_result)

    def get_zone_attribute(self, analysis_result):
        if analysis_result["Hatched Copper Pour"] == "" or analysis_result["Hatched Copper Pour"]["check"] is None:
            return ""
        minimum_value = SENTINEL_UNSET
        zone_attribute_result = {}
        layer_list = []
        result_list = []
        have_red = False
        have_yellow = False
        zones = self.board.Zones()
        for zone in zones:
            result = {}
            zone_attribute = {}
            gap = round((float(zone.GetHatchGap()) / NM_PER_MM), 3)
            thickness = round((float(zone.GetHatchThickness()) / NM_PER_MM), 3)
            if zone.GetFillMode() == ZONE_FILL_MODE_HATCHED:
                zone_attribute["id"] = zone.m_Uuid
                layer_list.append(str(float(zone.GetLayerName())))
                zone_attribute["layer"] = layer_list

                if zone.GetHatchThickness() < zone.GetHatchGap():
                    zone_attribute["value"] = str(gap)
                    zone_attribute["item"] = _("Grid Spacing")
                    zone_attribute["color"] = ColorRule().get_rule(
                        analysis_result,
                        "Hatched Copper Pour",
                        zone_attribute["item"],
                        zone.GetHatchThickness(),
                    )
                else:
                    zone_attribute["value"] = str(thickness)
                    zone_attribute["item"] = _("Grid Width")
                    zone_attribute["color"] = ColorRule().get_rule(
                        analysis_result,
                        "Hatched Copper Pour",
                        zone_attribute["item"],
                        zone.GetHatchGap(),
                    )
                    if zone_attribute["color"] == Colour.RED:
                        have_red = True
                    elif zone_attribute["color"] == Colour.GOLD:
                        have_yellow = True
                if minimum_value == SENTINEL_UNSET or zone.GetHatchThickness() < minimum_value:
                    minimum_value = thickness
                elif zone.GetHatchGap() < minimum_value:
                    minimum_value = gap
                result["result"] = zone_attribute
                result_list.append(result)
        if minimum_value == SENTINEL_UNSET:
            zone_attribute_result["display"] = SENTINEL_DISPLAY_NORMAL
        else:
            zone_attribute_result["display"] = minimum_value
        zone_attribute_result["check"] = result_list
        if have_red is True:
            zone_attribute_result["color"] = Colour.RED
        elif have_yellow is True:
            zone_attribute_result["color"] = Colour.GOLD
        else:
            zone_attribute_result["color"] = Colour.BLACK
        return maybe_validate(AnalysisResult, zone_attribute_result)
