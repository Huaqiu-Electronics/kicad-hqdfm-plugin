import wx
import sys
from kicad_dfm.dfm_maindialog.ui_dfm_maindialog import UiDfmMaindialog
import wx.dataview as dv
from kicad_dfm.dfm_maindialog.dfm_maindialog_model import DfmMaindialogModel
from kicad_dfm.utils.CustomRenderer import MyCustomRenderer


class DfmMaindailogView(UiDfmMaindialog):
    def __init__(
        self,
        parent,
        _control,
    ):
        super().__init__(parent)
        self.log = sys.stdout
        for title, col, width in [("Item", 0, 170), ("display", 1, -1)]:
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
