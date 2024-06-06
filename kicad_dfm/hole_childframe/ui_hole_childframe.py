# -*- coding: utf-8 -*-

###########################################################################
## Python code generated with wxFormBuilder (version 4.0.0-0-g0efcecf)
## http://www.wxformbuilder.org/
##
## PLEASE DO *NOT* EDIT THIS FILE!
###########################################################################

import wx
import wx.xrc

###########################################################################
## Class UiHoleChildframe
###########################################################################


class UiHoleChildframe(wx.Dialog):
    def __init__(self, parent):
        wx.Dialog.__init__(
            self,
            parent,
            id=wx.ID_ANY,
            title=_("Drill Hole Density"),
            pos=wx.DefaultPosition,
            size=wx.Size(650, 350),
            style=wx.DEFAULT_DIALOG_STYLE | wx.MAXIMIZE_BOX | wx.RESIZE_BORDER,
        )

        self.SetSizeHints(wx.DefaultSize, wx.DefaultSize)

        bSizer2 = wx.BoxSizer(wx.VERTICAL)

        self.main_panel = wx.Panel(
            self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TAB_TRAVERSAL
        )
        bSizer3 = wx.BoxSizer(wx.VERTICAL)

        self.text = wx.TextCtrl(
            self.main_panel,
            wx.ID_ANY,
            wx.EmptyString,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TE_MULTILINE,
        )
        self.text.SetFont(
            wx.Font(
                11,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
                False,
                "宋体",
            )
        )
        self.text.SetForegroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_CAPTIONTEXT)
        )
        self.text.SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNHIGHLIGHT)
        )

        bSizer3.Add(self.text, 1, wx.ALL | wx.EXPAND, 5)

        sbSizer1 = wx.StaticBoxSizer(
            wx.StaticBox(self.main_panel, wx.ID_ANY, _(" Rule description")),
            wx.VERTICAL,
        )

        self.bitmap = wx.StaticBitmap(
            sbSizer1.GetStaticBox(),
            wx.ID_ANY,
            wx.NullBitmap,
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        sbSizer1.Add(self.bitmap, 1, wx.ALL | wx.EXPAND, 5)

        bSizer3.Add(sbSizer1, 2, wx.ALL | wx.EXPAND, 5)

        self.main_panel.SetSizer(bSizer3)
        self.main_panel.Layout()
        bSizer3.Fit(self.main_panel)
        bSizer2.Add(self.main_panel, 1, wx.EXPAND | wx.ALL, 0)

        self.SetSizer(bSizer2)
        self.Layout()

        self.Centre(wx.BOTH)

    def __del__(self):
        pass
