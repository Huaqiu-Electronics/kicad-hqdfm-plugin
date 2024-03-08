import wx
from kicad_dfm.dfm_maindialog.ui_dfm_maindialog import UiDfmMaindialog


class DfmMaindailogView(UiDfmMaindialog):
    def __init__(self, parent, _control):
        super().__init__(parent)
        # self.control = _control
        self.grid.SetColSize(0, 160)
        self.grid.SetColSize(1, 170)
        self.grid.Bind(wx.EVT_SIZE, self.on_grid_size)

        DFM_JSON_NAME = [
            _("Layer Count"),
            _("Dimensions"),
            _("Signal Integrity"),
            _("Smallest Trace Width"),
            _("Smallest Trace Spacing"),
            _("Pad size"),
            _("Pad Spacing"),
            _("Hatched Copper Pour"),
            _("Hole Diameter"),
            _("RingHole"),
            _("Drill Hole Spacing"),
            _("Drill to Copper"),
            _("Board Edge Clearance"),
            _("Special Drill Holes"),
            _("Holes on SMD Pads"),
            _("Missing SMask Openings"),
            _("Drill Hole Density"),
            _("Surface Finish Area"),
            _("Test Point Count"),
        ]

        for index, value in enumerate(DFM_JSON_NAME):
            self.grid.SetRowSize(index, 35)
            self.grid.SetCellValue(index, 0, DFM_JSON_NAME[index])
            self.grid.SetCellAlignment(index, 0, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # for index, value in enumerate(self.control["json_name"]):
        #     self.grid.SetRowSize(index, 35)
        #     self.grid.SetCellValue(index, 0, self.control["json_name"][index])
        #     self.grid.SetCellAlignment(index, 0, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        self.Refresh()
        self.Update()
        self.Layout()

    def on_grid_size(self, event):
        self.adjust_grid_size()
        event.Skip()

    def adjust_grid_size(self):
        # Calculate the size of each row and column
        num_cols = self.grid.GetNumberCols()
        total_width = self.grid.GetSize().GetWidth()
        col_size = (total_width - 2) / num_cols
        for col in range(num_cols):
            self.grid.SetColSize(col, int(col_size))
