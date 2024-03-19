import wx
import wx.dataview as dv


class CustomRenderer(dv.DataViewCustomRenderer):
    def __init__(self, color):
        super().__init__()
        self.color = color

    def Render(self, rect, dc, state):
        dc.SetTextForeground(self.color)
        dc.DrawText(self.GetText(), rect.x, rect.y)
