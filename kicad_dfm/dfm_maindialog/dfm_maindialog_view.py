import wx
import wx.adv
import sys
from kicad_dfm.dfm_maindialog.ui_dfm_maindialog import UiDfmMaindialog
import wx.dataview as dv
from kicad_dfm.core.i18n import _
from kicad_dfm.dfm_maindialog.dfm_maindialog_model import DfmMaindialogModel
from kicad_dfm.core.settings import normalize_summary_column_widths
from kicad_dfm.ui.dpi import dpi_scale
from kicad_dfm.ui.dpi import scaled_dip
from kicad_dfm.ui.dpi import unscaled_dip
from kicad_dfm.ui.main_frame import hq_dfm_url
from kicad_dfm.utils.CustomRenderer import MyCustomRenderer
from kicad_dfm.utils.CustomRenderer import SummaryActionRenderer


class DfmMaindailogView(UiDfmMaindialog):
    def __init__(
        self,
        parent,
        _control,
        column_widths=None,
        language=None,
    ):
        super().__init__(parent)
        self.smd_spacing_button = self.pad_spacing_button
        self.main_action_buttons = (
            self.dfm_run_button,
            self.gerber_dfm_button,
            self.rule_manager_button,
            self.reset_visible_layers_button,
        )
        self._build_progress_ui()
        self._build_dfm_hint_ui(language)
        self.mainframe_data_view.SetMinSize(wx.Size(395, 735))

        button_sizer = self.test_point_count_button.GetContainingSizer()
        self.solder_mask_analysis_button = wx.Button(
            self.m_panel3,
            wx.ID_ANY,
            _("Check"),
            wx.DefaultPosition,
            wx.Size(100, 30),
            0,
        )
        button_sizer.Add(
            self.solder_mask_analysis_button, 0, wx.ALIGN_CENTER | wx.ALL, 3
        )
        self.check_buttons = (
            self.layer_count,
            self.layer_size,
            self.signal_integrity_button,
            self.smallest_trace_width_button,
            self.smallest_trace_spacing_button,
            self.smd_spacing_button,
            self.pad_size_button,
            self.hole_diameter_button,
            self.ringHole_button,
            self.drill_hole_spacing_button,
            self.drill_to_copper_button,
            self.board_edge_clearance_button,
            self.hole_to_board_edge_button,
            self.special_drill_holes_button,
            self.holes_on_smd_pads_button,
            self.missing_mask_openings_button,
            self.solder_mask_analysis_button,
            self.drill_hole_density_button,
            self.surface_finish_area_button,
            self.test_point_count_button,
        )
        self._button_sizer = button_sizer
        # The generated UI placed actions in a separate vertical sizer.  Such
        # controls cannot follow DataView scrolling, so keep them only as
        # hidden event targets and render their actions as a DataView column.
        panel_sizer = self.m_panel3.GetSizer()
        if panel_sizer:
            panel_sizer.Hide(button_sizer)
        self._data_column_item = panel_sizer.GetItem(0) if panel_sizer else None
        self._data_column_border_dip = (
            self._data_column_item.GetBorder() if self._data_column_item else 0
        )
        self.log = sys.stdout
        initial_widths = normalize_summary_column_widths(column_widths)
        summary_columns = []
        for title, col, width in [
            (_("Rule"), 0, initial_widths[0]),
            (_("Value"), 1, initial_widths[1]),
        ]:
            renderer = MyCustomRenderer(
                self.log,
                owner=self.mainframe_data_view,
                mode=dv.DATAVIEW_CELL_ACTIVATABLE,
            )
            column = dv.DataViewColumn(
                title,
                renderer,
                col,
                width=scaled_dip(self, width),
                flags=dv.DATAVIEW_COL_RESIZABLE,
            )
            column.Alignment = wx.ALIGN_CENTER_HORIZONTAL
            self.mainframe_data_view.AppendColumn(column)
            summary_columns.append(column)

        action_renderer = SummaryActionRenderer(
            self.mainframe_data_view,
            self.check_buttons,
            mode=dv.DATAVIEW_CELL_ACTIVATABLE,
        )
        self._action_renderer = action_renderer
        action_column = dv.DataViewColumn(
            _("Check"),
            action_renderer,
            3,
            width=scaled_dip(self, initial_widths[2]),
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        action_column.Alignment = wx.ALIGN_CENTER_HORIZONTAL
        self.mainframe_data_view.AppendColumn(action_column)
        summary_columns.append(action_column)
        self._summary_columns = tuple(summary_columns)

        self.refresh_dpi_layout()
        self.Layout()

    def _build_progress_ui(self):
        self.progress_panel = wx.Panel(self.m_panel9)
        progress_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.progress_status = wx.StaticText(
            self.progress_panel,
            wx.ID_ANY,
            _("Ready to check"),
        )
        self.progress_gauge = wx.Gauge(
            self.progress_panel,
            wx.ID_ANY,
            100,
            style=wx.GA_HORIZONTAL,
        )
        self.stop_check_button = wx.Button(
            self.progress_panel,
            wx.ID_ANY,
            _("Stop Check"),
            size=wx.Size(105, 30),
        )
        progress_sizer.Add(self.progress_status, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        progress_sizer.Add(self.progress_gauge, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        progress_sizer.Add(self.stop_check_button, 0, wx.ALIGN_CENTER_VERTICAL)
        self.progress_panel.SetSizer(progress_sizer)
        root_sizer = self.m_panel9.GetSizer()
        root_sizer.Insert(3, self.progress_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.progress_panel.Hide()

    def _build_dfm_hint_ui(self, language):
        self.dfm_hint_panel = wx.Panel(self.m_panel9)
        hint_sizer = wx.BoxSizer(wx.HORIZONTAL)
        hint_text = wx.StaticText(
            self.dfm_hint_panel,
            wx.ID_ANY,
            _("For more advanced DFM checks, use"),
        )
        hint_text.SetForegroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
        )
        self.dfm_hint_link = wx.adv.HyperlinkCtrl(
            self.dfm_hint_panel,
            wx.ID_ANY,
            _("Huaqiu DFM"),
            hq_dfm_url(language),
        )
        self.dfm_hint_link.SetToolTip(_("Open Huaqiu DFM in your browser"))
        hint_sizer.Add(hint_text, 0, wx.ALIGN_CENTER_VERTICAL)
        hint_sizer.Add(
            self.dfm_hint_link,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            4,
        )
        self.dfm_hint_panel.SetSizer(hint_sizer)
        self.m_panel9.GetSizer().Add(
            self.dfm_hint_panel,
            0,
            wx.ALIGN_CENTER_HORIZONTAL | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

    def begin_check_progress(self):
        self.progress_gauge.SetValue(0)
        self.progress_status.SetLabel(_("Preparing check..."))
        self.stop_check_button.Enable(True)
        self.progress_panel.Show()
        self.m_panel9.Layout()
        self.Layout()

    def update_check_progress(self, completed, total, message):
        total = max(1, int(total))
        value = min(100, max(0, int(round(float(completed) * 100.0 / total))))
        self.progress_gauge.SetValue(value)
        self.progress_status.SetLabel(message)
        self.progress_panel.Layout()
        self.m_panel9.Layout()
        wx.YieldIfNeeded()

    def show_stopping(self):
        self.stop_check_button.Enable(False)
        self.progress_status.SetLabel(_("Stopping after the current check..."))
        self.progress_panel.Layout()

    def end_check_progress(self):
        self.progress_panel.Hide()
        self.m_panel9.Layout()
        self.Layout()

    def init_data_view(self, json_analysis_map):
        self.json_analysis_map = json_analysis_map

        self.DfmMaindialogModel = DfmMaindialogModel(
            json_analysis_map, action_label=_("Check")
        )

        self.mainframe_data_view.AssociateModel(self.DfmMaindialogModel)

        wx.CallAfter(self.m_panel3.Layout)

    def refresh_dpi_layout(self):
        main_button_size = wx.Size(
            scaled_dip(self, 112),
            scaled_dip(self, 34),
        )
        for button in self.main_action_buttons:
            button.SetMinSize(main_button_size)

        if self._data_column_item:
            self._data_column_item.SetBorder(
                scaled_dip(self, self._data_column_border_dip)
            )

        self.mainframe_data_view.SetMinSize(
            wx.Size(scaled_dip(self, 495), scaled_dip(self, 735))
        )
        self.mainframe_data_view.InvalidateBestSize()
        model = getattr(self, "DfmMaindialogModel", None)
        if model is not None:
            model.Cleared()
        self.mainframe_data_view.Refresh()
        self.m_panel3.Layout()
        self.Layout()

    def current_dpi_scale(self):
        return dpi_scale(self)

    def summary_column_widths(self):
        return normalize_summary_column_widths(
            [unscaled_dip(self, column.GetWidth()) for column in self._summary_columns]
        )
