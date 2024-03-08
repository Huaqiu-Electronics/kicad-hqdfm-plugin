import wx
import pcbnew
from kicad_dfm.picture import GetImagePath
from kicad_dfm.hole_childframe.ui_hole_childframe import UiHoleChildframe


class HoleChildFrameView(UiHoleChildframe):
    def __init__(self, parent, result_value):
        super().__init__(parent)

        rule_string1 = result_value.partition(";")
        rule_string2 = rule_string1[2].partition(";")
        rule_string3 = rule_string2[2].partition(";")
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

        # 显示窗口
        self.Show()
