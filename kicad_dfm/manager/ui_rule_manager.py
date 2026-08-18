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
## Class UiRuleManager
###########################################################################


class UiRuleManager(wx.Dialog):
    def __init__(self, parent):
        wx.Dialog.__init__(
            self,
            parent,
            id=wx.ID_ANY,
            title=_("Rule View"),
            pos=wx.DefaultPosition,
            size=wx.Size(860, 620),
            style=wx.DEFAULT_DIALOG_STYLE | wx.MAXIMIZE_BOX | wx.RESIZE_BORDER,
        )

        self.SetSizeHints(wx.Size(760, 560), wx.DefaultSize)

        bSizer3 = wx.BoxSizer(wx.VERTICAL)

        self.m_panel1 = wx.Panel(
            self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TAB_TRAVERSAL
        )
        bSizer2 = wx.BoxSizer(wx.VERTICAL)

        bSizerProfile = wx.BoxSizer(wx.HORIZONTAL)

        self.rule_profile_title = wx.StaticText(
            self.m_panel1,
            wx.ID_ANY,
            _("Rule Profile"),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizerProfile.Add(self.rule_profile_title, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.rule_profile_name = wx.StaticText(
            self.m_panel1,
            wx.ID_ANY,
            wx.EmptyString,
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizerProfile.Add(self.rule_profile_name, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        bSizer2.Add(bSizerProfile, 0, wx.EXPAND, 5)

        self.rule_hint = wx.StaticText(
            self.m_panel1,
            wx.ID_ANY,
            _("Edit rule values as red threshold, warning threshold, upper limit. Values are in the shown unit."),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        self.rule_hint.Wrap(-1)
        bSizer2.Add(self.rule_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.rule_manager_list = wx.dataview.DataViewListCtrl(
            self.m_panel1,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.Size(-1, -1),
            wx.dataview.DV_ROW_LINES | wx.dataview.DV_VERT_RULES,
        )
        self.rule_manager_list.SetFont(
            wx.Font(
                9,
                wx.FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
                False,
                "微软雅黑",
            )
        )
        self.rule_manager_list.SetForegroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        )
        self.rule_manager_list.SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        )

        bSizer2.Add(self.rule_manager_list, 1, wx.ALL | wx.EXPAND, 5)

        bSizerEditor = wx.BoxSizer(wx.HORIZONTAL)

        bSizerRuleEdit = wx.BoxSizer(wx.VERTICAL)

        self.selected_rule_title = wx.StaticText(
            self.m_panel1,
            wx.ID_ANY,
            _("Selected Rule"),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizerRuleEdit.Add(self.selected_rule_title, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)

        self.selected_rule_name = wx.StaticText(
            self.m_panel1,
            wx.ID_ANY,
            _("Select a rule to edit."),
            wx.DefaultPosition,
            wx.Size(320, -1),
            0,
        )
        self.selected_rule_name.Wrap(320)
        bSizerRuleEdit.Add(self.selected_rule_name, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.rule_value_title = wx.StaticText(
            self.m_panel1,
            wx.ID_ANY,
            _("Rule Value"),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizerRuleEdit.Add(self.rule_value_title, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)

        self.rule_value_text = wx.TextCtrl(
            self.m_panel1,
            wx.ID_ANY,
            wx.EmptyString,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TE_PROCESS_ENTER,
        )
        bSizerRuleEdit.Add(self.rule_value_text, 0, wx.EXPAND | wx.ALL, 5)

        self.rule_value_hint = wx.StaticText(
            self.m_panel1,
            wx.ID_ANY,
            _("Format: alarm threshold, warning threshold, upper limit."),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        self.rule_value_hint.Wrap(320)
        bSizerRuleEdit.Add(self.rule_value_hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        bSizerEditor.Add(bSizerRuleEdit, 1, wx.EXPAND, 5)

        self.rule_picture = wx.StaticBitmap(
            self.m_panel1,
            wx.ID_ANY,
            wx.NullBitmap,
            wx.DefaultPosition,
            wx.Size(260, 110),
            0,
        )
        bSizerEditor.Add(self.rule_picture, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        bSizer2.Add(bSizerEditor, 0, wx.EXPAND, 5)

        bSizerButtons = wx.BoxSizer(wx.HORIZONTAL)
        bSizerButtons.Add((0, 0), 1, wx.EXPAND, 5)

        self.save_button = wx.Button(
            self.m_panel1,
            wx.ID_ANY,
            _("Save Rules"),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizerButtons.Add(self.save_button, 0, wx.ALL, 5)

        self.close_button = wx.Button(
            self.m_panel1,
            wx.ID_ANY,
            _("Close"),
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        bSizerButtons.Add(self.close_button, 0, wx.ALL, 5)

        bSizer2.Add(bSizerButtons, 0, wx.EXPAND, 5)

        self.m_panel1.SetSizer(bSizer2)
        self.m_panel1.Layout()
        bSizer2.Fit(self.m_panel1)
        bSizer3.Add(self.m_panel1, 1, wx.EXPAND | wx.ALL, 0)

        self.SetSizer(bSizer3)
        self.Layout()

        self.Centre(wx.BOTH)

    def __del__(self):
        pass
