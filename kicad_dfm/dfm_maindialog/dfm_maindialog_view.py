import wx
from kicad_dfm.dfm_maindialog.ui_dfm_maindialog import UiDfmMaindialog
import wx.dataview as dv
from kicad_dfm.dfm_maindialog.dfm_maindialog_model import DfmMaindialogModel


class DfmMaindailogView(UiDfmMaindialog):
    def __init__(
        self,
        parent,
        _control,
    ):
        super().__init__(parent)
        # self.control = _control

        self.mainframe_data_view.AppendTextColumn(
            _("Item"),
            0,
            width=160,
            mode=dv.DATAVIEW_CELL_ACTIVATABLE,
            align=wx.ALIGN_CENTER_HORIZONTAL,
        )
        self.mainframe_data_view.AppendTextColumn(
            _("display"),
            1,
            width=-1,
            mode=dv.DATAVIEW_CELL_ACTIVATABLE,
            align=wx.ALIGN_CENTER_HORIZONTAL,
        )
        self.mainframe_data_view.SetRowHeight(35)

        self.Layout()

    def init_data_view(self, json_analysis_map):
        self.json_analysis_map = json_analysis_map

        self.DfmMaindialogModel = DfmMaindialogModel(json_analysis_map)

        self.mainframe_data_view.AssociateModel(self.DfmMaindialogModel)

        wx.CallAfter(self.m_panel3.Layout)
