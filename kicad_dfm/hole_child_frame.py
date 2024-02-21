import wx
import pcbnew


class HoleChildFrame(wx.Frame):
    def __init__(self, parent, result_value, image_path):
        self.temp_layer = {""}

        rule_string1 = result_value.partition(";")
        rule_string2 = rule_string1[2].partition(";")
        rule_string3 = rule_string2[2].partition(";")
        if pcbnew.GetLanguage() == "简体中文":
            if rule_string3[0] == "":
                value = (
                    "激光孔数 0; "
                    + "“Pcs / SET”钻孔数为："
                    + rule_string1[0]
                    + "; “孔密度”为："
                    + rule_string2[0]
                )
            else:
                value = (
                    "激光孔数 "
                    + rule_string1[0]
                    + "; “Pcs / SET”钻孔数为："
                    + rule_string2[0]
                    + "; “孔密度”为："
                    + rule_string3[0]
                )
        else:
            if rule_string3[0] == "":
                value = (
                    "Laser hole number 0; "
                    + '"Pcs / SET"The number of holes is : '
                    + rule_string1[0]
                    + '; "Hole density" is : '
                    + rule_string2[0]
                )
            else:
                value = (
                    "Laser hole number "
                    + rule_string1[0]
                    + '; "Pcs / SET"The number of holes is : '
                    + rule_string2[0]
                    + '; "Hole density" is : '
                    + rule_string3[0]
                )

        picture_path = image_path.rsplit("\\")
        path = image_path.replace(
            picture_path[len(picture_path) - 1],
            "kicad_dfm\\picture\\hole_density_en.png",
        )
        super(wx.Frame, self).__init__(
            parent, title="Drill Hole Density", size=(650, 350)
        )
        panel = wx.Panel(self)
        show_box = wx.BoxSizer(wx.VERTICAL)
        text = wx.TextCtrl(
            panel, value=value, size=(650, 80), style=wx.TE_READONLY | wx.TE_CENTER
        )
        show_box.Add(text, 0, wx.Top, 5)

        image = wx.Image(path, wx.BITMAP_TYPE_PNG).Rescale(630, 250)
        bmp = wx.StaticBitmap(panel, -1, image)
        show_box.Add(bmp, 0, wx.ALL, 5)

        panel.SetSizer(show_box)
        panel.Fit()

        self.Centre()
        self.Show(True)
