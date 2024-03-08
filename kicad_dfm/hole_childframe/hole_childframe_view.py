import wx
import pcbnew
from kicad_dfm.picture import GetImagePath
from kicad_dfm.hole_childframe.ui_hole_childframe import UiHoleChildframe

has_hole_childframe_shown = False


class HoleChildFrameView(UiHoleChildframe):
    def __init__(self, parent, result_value):
        super().__init__(parent)

        self.has_been_shown = False
        self.temp_layer = {""}
        rule_string1 = result_value.partition(";")
        rule_string2 = rule_string1[2].partition(";")
        rule_string3 = rule_string2[2].partition(";")
        # if pcbnew.GetLanguage() == "简体中文":
        #     if rule_string3[0] == "":
        #         value = (
        #             "激光孔数 0; "
        #             + "“Pcs / SET”钻孔数为："
        #             + rule_string1[0]
        #             + "; “孔密度”为："
        #             + rule_string2[0]
        #         )
        #     else:
        #         value = (
        #             "激光孔数 "
        #             + rule_string1[0]
        #             + "; “Pcs / SET”钻孔数为："
        #             + rule_string2[0]
        #             + "; “孔密度”为："
        #             + rule_string3[0]
        #         )
        # else:
        if rule_string3[0] == "":
            value = (
                _("Laser hole number 0; ")
                + _('"Pcs / SET"The number of holes is : ')
                + rule_string1[0]
                + _('; "Hole density" is : ')
                + rule_string2[0]
            )
        else:
            value = (
                _("Laser hole number ")
                + rule_string1[0]
                + _('; "Pcs / SET"The number of holes is : ')
                + rule_string2[0]
                + _('; "Hole density" is : ')
                + rule_string3[0]
            )

        self.text.SetValue(value)
        self.bitmap.SetBitmap(wx.Bitmap(GetImagePath("hole_density_en.png")))
        self.Centre()
