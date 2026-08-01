import sys

import wx
import wx.dataview as dv

from kicad_dfm.constants import COL_INDEX_DISPLAY, COL_INDEX_ITEM, COL_WIDTH_DISPLAY_AUTO, COL_WIDTH_ITEM
from kicad_dfm.dfm_maindialog.dfm_maindialog_model import DfmMaindialogModel
from kicad_dfm.dfm_maindialog.ui_dfm_maindialog import UiDfmMaindialog
from kicad_dfm.utils.CustomRenderer import MyCustomRenderer

COLUMNS = [
    ("Item", COL_INDEX_ITEM, COL_WIDTH_ITEM),
    ("display", COL_INDEX_DISPLAY, COL_WIDTH_DISPLAY_AUTO),
]


class DfmMaindailogView(UiDfmMaindialog):
    def __init__(
        self,
        parent,
        _control,
    ):
        super().__init__(parent)
        self.log = sys.stdout
        for title, col, width in COLUMNS:
            renderer = MyCustomRenderer(self.log, mode=dv.DATAVIEW_CELL_ACTIVATABLE)
            column = dv.DataViewColumn(title, renderer, col, width=width)
            column.Alignment = wx.ALIGN_CENTER_HORIZONTAL
            self.mainframe_data_view.AppendColumn(column)

        self.Layout()

    def init_data_view(self, json_analysis_map):
        self.json_analysis_map = json_analysis_map

        self.DfmMaindialogModel = DfmMaindialogModel(json_analysis_map)

        self.mainframe_data_view.AssociateModel(self.DfmMaindialogModel)

        wx.CallAfter(self.m_panel3.Layout)
