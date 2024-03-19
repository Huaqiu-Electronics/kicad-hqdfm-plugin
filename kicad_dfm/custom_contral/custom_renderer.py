import wx
import wx.dataview as dv


class CustomRenderer(dv.DataViewTextRenderer):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)

    def Render(self, rect, dc, state):
        # 获取当前行的文本
        text = self.GetText()

        # 获取当前行的字体颜色
        font_color = wx.Colour(255, 0, 0)  # 这里假设使用红色字体
        dc.SetTextForeground(font_color)

        # 渲染文本
        dv.DataViewTextRenderer.Render(self, rect, dc, state)
