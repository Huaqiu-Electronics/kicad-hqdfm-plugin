# -*- coding: utf-8 -*-

###########################################################################
## Python code generated with wxFormBuilder (version 4.0.0-0-g0efcecf)
## http://www.wxformbuilder.org/
##
## PLEASE DO *NOT* EDIT THIS FILE!
###########################################################################

import wx
import wx.xrc
import wx.grid

###########################################################################
## Class UiDfmMaindialog
###########################################################################


class UiDfmMaindialog(wx.Panel):
    def __init__(
        self,
        parent,
        id=wx.ID_ANY,
        pos=wx.DefaultPosition,
        size=wx.Size(-1, -1),
        style=wx.TAB_TRAVERSAL,
        name=wx.EmptyString,
    ):
        wx.Panel.__init__(
            self, parent, id=id, pos=pos, size=size, style=style, name=name
        )

        bSizer1 = wx.BoxSizer(wx.VERTICAL)

        self.m_panel9 = wx.Panel(
            self, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, wx.TAB_TRAVERSAL
        )
        bSizer11 = wx.BoxSizer(wx.VERTICAL)

        self.m_panel8 = wx.Panel(
            self.m_panel9,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.Size(-1, 15),
            wx.TAB_TRAVERSAL,
        )
        bSizer11.Add(self.m_panel8, 0, wx.EXPAND | wx.ALL, 0)

        bSizer2 = wx.BoxSizer(wx.HORIZONTAL)

        bSizer2.Add((0, 0), 1, wx.EXPAND, 5)

        self.dfm_run_button = wx.Button(
            self.m_panel9,
            wx.ID_ANY,
            _("DFM Analysis"),
            wx.DefaultPosition,
            wx.Size(110, 35),
            0,
        )
        bSizer2.Add(self.dfm_run_button, 0, wx.ALL | wx.EXPAND, 15)

        self.rule_manager_button = wx.Button(
            self.m_panel9,
            wx.ID_ANY,
            _("Rule Manager"),
            wx.DefaultPosition,
            wx.Size(110, 35),
            0,
        )
        bSizer2.Add(self.rule_manager_button, 0, wx.ALL | wx.EXPAND, 15)

        bSizer2.Add((0, 0), 1, wx.EXPAND, 5)

        bSizer11.Add(bSizer2, 0, wx.EXPAND, 5)

        self.m_panel6 = wx.Panel(
            self.m_panel9,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        bSizer71 = wx.BoxSizer(wx.HORIZONTAL)

        self.m_panel3 = wx.Panel(
            self.m_panel6,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.Size(-1, -1),
            wx.TAB_TRAVERSAL,
        )
        bSizer6 = wx.BoxSizer(wx.HORIZONTAL)

        self.grid_panel = wx.Panel(
            self.m_panel3,
            wx.ID_ANY,
            wx.DefaultPosition,
            wx.DefaultSize,
            wx.TAB_TRAVERSAL,
        )
        bSizer10 = wx.BoxSizer(wx.HORIZONTAL)

        self.grid = wx.grid.Grid(
            self.grid_panel, wx.ID_ANY, wx.DefaultPosition, wx.DefaultSize, 0
        )

        # Grid
        self.grid.CreateGrid(19, 2)
        self.grid.EnableEditing(False)
        self.grid.EnableGridLines(True)
        self.grid.SetGridLineColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNSHADOW)
        )
        self.grid.EnableDragGridSize(True)
        self.grid.SetMargins(0, 0)

        # Columns
        self.grid.AutoSizeColumns()
        self.grid.EnableDragColMove(False)
        self.grid.EnableDragColSize(False)
        self.grid.SetColLabelSize(1)
        self.grid.SetColLabelAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)

        # Rows
        self.grid.SetRowSize(0, 30)
        self.grid.AutoSizeRows()
        self.grid.EnableDragRowSize(False)
        self.grid.SetRowLabelSize(1)
        self.grid.SetRowLabelAlignment(wx.ALIGN_RIGHT, wx.ALIGN_CENTER)

        # Label Appearance
        self.grid.SetLabelBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
        )
        self.grid.SetLabelFont(
            wx.Font(
                11,
                wx.FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
                False,
                "微软雅黑",
            )
        )

        # Cell Defaults
        self.grid.SetDefaultCellFont(
            wx.Font(
                9,
                wx.FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
                False,
                "微软雅黑",
            )
        )
        self.grid.SetDefaultCellAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
        bSizer10.Add(self.grid, 1, wx.ALL, 5)

        self.grid_panel.SetSizer(bSizer10)
        self.grid_panel.Layout()
        bSizer10.Fit(self.grid_panel)
        bSizer6.Add(self.grid_panel, 21, wx.ALL | wx.EXPAND, 5)

        bSizer7 = wx.BoxSizer(wx.VERTICAL)

        bSizer7.Add((0, 5), 0, wx.EXPAND, 5)

        self.layer_count = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            wx.EmptyString,
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.layer_count, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.layer_size = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            wx.EmptyString,
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.layer_size, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.signal_integrity_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.signal_integrity_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.smallest_trace_width_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.smallest_trace_width_button, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        self.smallest_trace_spacing_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.smallest_trace_spacing_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.pad_size_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.pad_size_button, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        self.pad_spacing_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.pad_spacing_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.hatched_copper_pour_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.hatched_copper_pour_button, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        self.hole_diameter_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.hole_diameter_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.ringHole_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.ringHole_button, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        self.drill_hole_spacing_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.drill_hole_spacing_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.drill_to_copper_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.drill_to_copper_button, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        self.board_edge_clearance_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.board_edge_clearance_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.special_drill_holes_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.special_drill_holes_button, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        self.holes_on_smd_pads_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.holes_on_smd_pads_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.missing_mask_openings_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.missing_mask_openings_button, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        self.drill_hole_density_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.drill_hole_density_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        self.surface_finish_area_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            wx.EmptyString,
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.surface_finish_area_button, 0, wx.ALIGN_CENTER | wx.ALL, 2)

        self.test_point_count_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            wx.EmptyString,
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        bSizer7.Add(self.test_point_count_button, 0, wx.ALIGN_CENTER | wx.ALL, 3)

        bSizer6.Add(bSizer7, 10, wx.EXPAND, 5)

        self.m_panel3.SetSizer(bSizer6)
        self.m_panel3.Layout()
        bSizer6.Fit(self.m_panel3)
        bSizer71.Add(self.m_panel3, 1, wx.EXPAND | wx.ALL, 0)

        self.m_panel6.SetSizer(bSizer71)
        self.m_panel6.Layout()
        bSizer71.Fit(self.m_panel6)
        bSizer11.Add(self.m_panel6, 1, wx.EXPAND | wx.ALL, 5)

        self.m_panel9.SetSizer(bSizer11)
        self.m_panel9.Layout()
        bSizer11.Fit(self.m_panel9)
        bSizer1.Add(self.m_panel9, 1, wx.EXPAND | wx.ALL, 0)

        self.SetSizer(bSizer1)
        self.Layout()
        bSizer1.Fit(self)

    def __del__(self):
        pass
