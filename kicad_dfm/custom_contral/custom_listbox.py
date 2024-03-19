import wx


class CustomListBox(wx.ListBox):
    def __init__(
        self,
        parent,
        id=wx.ID_ANY,
        pos=wx.DefaultPosition,
        size=wx.DefaultSize,
        choices=[],
        style=wx.LB_SINGLE | wx.LB_OWNERDRAW,
        validator=wx.DefaultValidator,
        name=wx.ListBoxNameStr,
    ):
        super().__init__(parent, id, pos, size, choices, style, validator, name)

        self.item_colors = {}  # 用于存储每一项的颜色信息

    def SetItemForegroundColour(self, item, colour):
        self.item_colors[item] = colour
        self.Refresh()

    def OnDrawItem(self, dc, rect, item, flags):
        dc.SetBackgroundMode(wx.TRANSPARENT)

        if item in self.item_colors:
            dc.SetTextForeground(self.item_colors[item])
        else:
            dc.SetTextForeground(self.GetForegroundColour())

        dc.DrawText(self.GetString(item), rect.x, rect.y)

        if flags & wx.LIST_DRAW_SELECTED:
            dc.SetTextBackground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT))
            dc.SetTextForeground(
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
            )
            dc.SetPen(wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)))
            dc.SetBrush(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)))
            dc.DrawRectangle(rect.x, rect.y, rect.width, rect.height)
