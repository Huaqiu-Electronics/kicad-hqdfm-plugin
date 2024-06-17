# -*- coding: utf-8 -*-

###########################################################################
## Python code generated with wxFormBuilder (version 4.0.0-0-g0efcecf)
## http://www.wxformbuilder.org/
##
## PLEASE DO *NOT* EDIT THIS FILE!
###########################################################################

import wx
import wx.xrc
import wx.dataview

###########################################################################
## Class UiChildFrame
###########################################################################


class UiChildFrame(wx.Frame):
    def __init__(self, parent):
        wx.Frame.__init__(
            self,
            parent,
            id=wx.ID_ANY,
            title=wx.EmptyString,
            pos=wx.DefaultPosition,
            size=wx.Size(750, 600),
            style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP | wx.TAB_TRAVERSAL,
        )

        self.SetSizeHints(wx.DefaultSize, wx.DefaultSize)
        self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_MENU))

        bSizer1 = wx.BoxSizer(wx.VERTICAL)

        self.m_panel7 = wx.Panel(
            self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TAB_TRAVERSAL
        )
        bSizer10 = wx.BoxSizer(wx.VERTICAL)

        self.main_panel = wx.Panel(
            self.m_panel7,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        bSizer2 = wx.BoxSizer(wx.HORIZONTAL)

        self.layer_panel = wx.Panel(
            self.main_panel,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        bSizer3 = wx.BoxSizer(wx.VERTICAL)

        self.text_layer = wx.TextCtrl(
            self.layer_panel,
            wx.ID_ANY,
            _("Layer"),
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TE_CENTER,
        )
        bSizer3.Add(self.text_layer, 0, wx.EXPAND, 0)

        lst_layerChoices = []
        self.lst_layer = wx.ListBox(
            self.layer_panel,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            lst_layerChoices,
            wx.LB_EXTENDED,
        )
        bSizer3.Add(self.lst_layer, 1, wx.ALL | wx.EXPAND, 0)

        self.check_box = wx.CheckBox(
            self.layer_panel,
            wx.ID_ANY,
            _("Keep selected layers"),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizer3.Add(self.check_box, 0, wx.ALL, 5)

        combo_boxChoices = [_("Show all"), _("!! (Alarm)")]
        self.combo_box = wx.ComboBox(
            self.layer_panel,
            wx.ID_ANY,
            _("Show all"),
            wx.DefaultPosition,
            wx.DefaultSize,
            combo_boxChoices,
            0,
        )
        self.combo_box.SetSelection(1)
        bSizer3.Add(self.combo_box, 0, wx.ALL | wx.EXPAND, 5)

        self.layer_panel.SetSizer(bSizer3)
        self.layer_panel.Layout()
        bSizer3.Fit(self.layer_panel)
        bSizer2.Add(self.layer_panel, 1, wx.EXPAND | wx.ALL, 0)

        self.class_panel = wx.Panel(
            self.main_panel,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        bSizer4 = wx.BoxSizer(wx.VERTICAL)

        self.text_analysis_type = wx.TextCtrl(
            self.class_panel,
            wx.ID_ANY,
            _("Problem"),
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TE_CENTER,
        )
        bSizer4.Add(self.text_analysis_type, 0, wx.ALL | wx.EXPAND, 0)

        lst_analysis_typeChoices = []
        self.lst_analysis_type = wx.ListBox(
            self.class_panel,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            lst_analysis_typeChoices,
            wx.LB_EXTENDED,
        )
        bSizer4.Add(self.lst_analysis_type, 1, wx.ALL | wx.EXPAND, 0)

        self.class_panel.SetSizer(bSizer4)
        self.class_panel.Layout()
        bSizer4.Fit(self.class_panel)
        bSizer2.Add(self.class_panel, 1, wx.EXPAND | wx.ALL, 0)

        self.result_panel = wx.Panel(
            self.main_panel,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        bSizer5 = wx.BoxSizer(wx.VERTICAL)

        self.text_analysis_result = wx.TextCtrl(
            self.result_panel,
            wx.ID_ANY,
            _("Occurrences(Click to view)"),
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TE_CENTER,
        )
        bSizer5.Add(self.text_analysis_result, 0, wx.ALL | wx.EXPAND, 0)

        self.result_list_panel = wx.Panel(
            self.result_panel,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        bSizer8 = wx.BoxSizer(wx.VERTICAL)

        self.lst_analysis_result1 = wx.dataview.DataViewListCtrl(
            self.result_list_panel,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.dataview.DV_NO_HEADER | wx.dataview.DV_ROW_LINES | wx.dataview.DV_SINGLE,
        )
        bSizer8.Add(self.lst_analysis_result1, 1, wx.ALL | wx.EXPAND, 0)

        self.result_list_panel.SetSizer(bSizer8)
        self.result_list_panel.Layout()
        bSizer8.Fit(self.result_list_panel)
        bSizer5.Add(self.result_list_panel, 1, wx.EXPAND | wx.ALL, 0)

        bSizer6 = wx.BoxSizer(wx.HORIZONTAL)

        self.first_button = wx.Button(
            self.result_panel,
            wx.ID_ANY,
            _("First"),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizer6.Add(self.first_button, 1, wx.ALL, 2)

        self.back_button = wx.Button(
            self.result_panel, wx.ID_ANY, _("<<"), wx.DefaultPosition, wx.DefaultSize, 0
        )
        bSizer6.Add(self.back_button, 1, wx.ALL, 2)

        self.next_button = wx.Button(
            self.result_panel, wx.ID_ANY, _(">>"), wx.DefaultPosition, wx.DefaultSize, 0
        )
        bSizer6.Add(self.next_button, 1, wx.ALL, 2)

        self.last_button = wx.Button(
            self.result_panel,
            wx.ID_ANY,
            _("Last"),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizer6.Add(self.last_button, 1, wx.ALL, 2)

        bSizer5.Add(bSizer6, 0, wx.EXPAND, 0)

        self.result_panel.SetSizer(bSizer5)
        self.result_panel.Layout()
        bSizer5.Fit(self.result_panel)
        bSizer2.Add(self.result_panel, 1, wx.EXPAND | wx.ALL, 0)

        self.main_panel.SetSizer(bSizer2)
        self.main_panel.Layout()
        bSizer2.Fit(self.main_panel)
        bSizer10.Add(self.main_panel, 1, wx.ALL | wx.EXPAND, 0)

        self.m_panel5 = wx.Panel(
            self.m_panel7,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        self.m_panel5.SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        )

        bSizer7 = wx.BoxSizer(wx.VERTICAL)

        sbSizer2 = wx.StaticBoxSizer(
            wx.StaticBox(self.m_panel5, wx.ID_ANY, _("Rule description")), wx.VERTICAL
        )

        self.bmp = wx.StaticBitmap(
            sbSizer2.GetStaticBox(),
            wx.ID_ANY,
            wx.NullBitmap,
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        sbSizer2.Add(self.bmp, 1, wx.ALL | wx.EXPAND, 5)

        bSizer7.Add(sbSizer2, 1, wx.ALL | wx.EXPAND, 5)

        self.m_panel5.SetSizer(bSizer7)
        self.m_panel5.Layout()
        bSizer7.Fit(self.m_panel5)
        bSizer10.Add(self.m_panel5, 1, wx.ALL | wx.EXPAND, 0)

        self.m_panel7.SetSizer(bSizer10)
        self.m_panel7.Layout()
        bSizer10.Fit(self.m_panel7)
        bSizer1.Add(self.m_panel7, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(bSizer1)
        self.Layout()

        self.Centre(wx.BOTH)

    def __del__(self):
        pass
