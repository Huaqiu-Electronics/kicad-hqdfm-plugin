import os
import wx
import re
import shutil
from decimal import Decimal
import json
import pcbnew
import tempfile
from pathlib import Path
from . import config

from .create_file import CreateFile
from .dfm_child_frame import DfmChildFrame
from .picture import GetImagePath
from .analysis import MinimumLineWidth
from .dfm_analysis import DfmAnalysis
from kicad_dfm import GetFilePath
from kicad_dfm.dfm_maindialog.dfm_maindialog_view import DfmMaindailogView
from kicad_dfm.settings.pcb_setting import PcbSetting
from kicad_dfm.manager.rule_manager_view import RuleManagerView
from kicad_dfm.settings.frame_setting import FRAME_SETTING
from kicad_dfm.settings.single_plugin import SINGLE_PLUGIN
from kicad_dfm.hole_childframe.hole_childframe_view import HoleChildFrameView


class DfmMainframe(wx.Frame):
    def __init__(self, parent):
        super(wx.Frame, self).__init__(
            parent,
            title=_("HQ DFM"),
            style=wx.DEFAULT_FRAME_STYLE & ~(wx.MAXIMIZE_BOX) | wx.TAB_TRAVERSAL,
        )
        SINGLE_PLUGIN.register_main_wind(self)
        self.control = {}
        if pcbnew.GetLanguage() == "简体中文":
            self.control = config.Language_chinese
        elif pcbnew.GetLanguage() == "English":
            self.control = config.Language_english
        elif pcbnew.GetLanguage() == "Default":
            self.control = config.Language_english
        elif pcbnew.GetLanguage() == "":
            self.control = config.Language_english
        else:
            wx.MessageBox(
                _("The language you selected is currently not supported"),
                _("Help"),
                style=wx.ICON_INFORMATION,
            )
            return

        self.line_list = []
        self.have_progress = False
        try:
            pcbnew.GetBoard().GetFileName()
            self.board = pcbnew.GetBoard()
        except Exception as e:
            for fp in (
                "C:\\Program Files\\KiCad\\8.0\\share\\kicad\\demos\\flat_hierarchy\\flat_hierarchy.kicad_pcb",
                "C:\\Program Files\\KiCad\\8.0\\share\\kicad\\demos\\video\\video.kicad_pcb",
            ):
                if os.path.exists(fp):
                    self.board = pcbnew.LoadBoard(fp)

        self.path, self.filename = os.path.split(self.board.GetFileName())
        self.board_name = os.path.split(self.board.GetFileName())[1]
        self.name = self.board_name.split(".")[0]
        self.analysis_result = {}
        self.unit = pcbnew.GetUserUnits()
        self.unit = 1
        self.kicad_result = {}
        self.rule_message_list = []
        self.dfm_analysis = DfmAnalysis()
        self.hole_childframe = None
        self.pcb_setting = PcbSetting(self.board)

        self.item_result = _("no errors detected")
        self.SetIcon(wx.Icon(GetImagePath("icon.png"), wx.BITMAP_TYPE_PNG))  # 设置窗口图标
        # 将 DfmMaindailogView 对象添加到 BoxSizer 中
        self.dfm_maindialog = DfmMaindailogView(self, self.control)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.dfm_maindialog, 1, wx.EXPAND)
        self.SetSizer(self.sizer)

        self.SetSize(wx.Size(480, 830))
        self.Layout()
        self.Centre(wx.BOTH)
        self.add_temp_json()

        self.dfm_maindialog.dfm_run_button.Bind(
            wx.EVT_BUTTON, self.on_select_export_gerber
        )
        self.dfm_maindialog.rule_manager_button.Bind(
            wx.EVT_BUTTON, self.show_rule_manager
        )
        self.dfm_maindialog.signal_integrity_button.Bind(
            wx.EVT_BUTTON, self.show_signal_integrity_button
        )
        self.dfm_maindialog.smallest_trace_width_button.Bind(
            wx.EVT_BUTTON, self.show_smallest_trace_width_button
        )
        self.dfm_maindialog.smallest_trace_spacing_button.Bind(
            wx.EVT_BUTTON, self.show_smallest_trace_spacing_button
        )
        self.dfm_maindialog.pad_size_button.Bind(
            wx.EVT_BUTTON, self.show_pad_size_button
        )
        self.dfm_maindialog.pad_spacing_button.Bind(
            wx.EVT_BUTTON, self.show_pad_spacing_button
        )
        self.dfm_maindialog.hatched_copper_pour_button.Bind(
            wx.EVT_BUTTON, self.show_hatched_copper_pour_button
        )
        self.dfm_maindialog.hole_diameter_button.Bind(
            wx.EVT_BUTTON, self.show_hole_diameter_button
        )
        self.dfm_maindialog.ringHole_button.Bind(
            wx.EVT_BUTTON, self.show_ringHole_button
        )
        self.dfm_maindialog.drill_hole_spacing_button.Bind(
            wx.EVT_BUTTON, self.show_drill_hole_spacing_button
        )
        self.dfm_maindialog.drill_to_copper_button.Bind(
            wx.EVT_BUTTON, self.show_drill_to_copper_button
        )
        self.dfm_maindialog.board_edge_clearance_button.Bind(
            wx.EVT_BUTTON, self.show_board_edge_clearance_button
        )
        self.dfm_maindialog.special_drill_holes_button.Bind(
            wx.EVT_BUTTON, self.show_special_drill_holes_button
        )
        self.dfm_maindialog.holes_on_smd_pads_button.Bind(
            wx.EVT_BUTTON, self.show_holes_on_smd_pads_button
        )
        self.dfm_maindialog.missing_mask_openings_button.Bind(
            wx.EVT_BUTTON, self.show_missing_mask_openings_button
        )
        self.dfm_maindialog.drill_hole_density_button.Bind(
            wx.EVT_BUTTON, self.show_drill_hole_density_button
        )
        self.dfm_maindialog.surface_finish_area_button.Bind(
            wx.EVT_BUTTON, self.show_surface_finish_area_button
        )
        self.dfm_maindialog.test_point_count_button.Bind(
            wx.EVT_BUTTON, self.show_test_point_count_button
        )
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def on_close(self, event):
        for line in self.line_list:
            self.board.Delete(line)
        SINGLE_PLUGIN.register_main_wind(None)
        self.Destroy()

    def add_temp_json(self):
        json_name = GetFilePath("temp.json")
        temp_filename = GetFilePath("name.json")
        if os.path.exists(temp_filename) and os.path.exists(json_name):
            with open(temp_filename, "r") as f:
                content = f.read().encode(encoding="utf-8")
                data = json.loads(content)
                if data["name"] == self.name or "*" + data["name"] == self.name:
                    if pcbnew.GetLanguage() == "简体中文":
                        self.analysis_result = self.dfm_analysis.analysis_json(
                            json_name, True
                        )
                    else:
                        self.analysis_result = self.dfm_analysis.analysis_json(
                            json_name
                        )
                    if self.analysis_result == "":
                        wx.MessageBox(
                            _("File parsing failed. Please click dfm analysis"),
                            _("Help"),
                            style=wx.ICON_INFORMATION,
                        )
                        return
                    self.add_all_item()

    def get_file_name(self):
        title_name = self.title_name
        name = title_name.partition("— PCB")
        return name[0]

    # 只出现一个查看窗口
    def have_same_class_window(self):
        for line in self.line_list:
            self.board.Delete(line)
        pcbnew.Refresh()
        title_name = [
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
            _("Surface Finish Area"),
            _("Test Point Count"),
            _("Drill Hole Density"),
        ]
        # WINDOWS = wx.GetTopLevelWindows()
        for win in wx.GetTopLevelWindows():
            if win.GetTitle() in title_name:
                win.Destroy()

    def create_child_frame(
        self, title, analysis_result, jsonfile_string, is_kicad_result=False
    ):
        try:
            wx.BeginBusyCursor()
            self.have_same_class_window()
            child_frame = DfmChildFrame(
                self,
                title,
                analysis_result,
                jsonfile_string,
                self.line_list,
                self.unit,
                self.board,
                is_kicad_result,
            )

            child_frame.Show()
        finally:
            wx.EndBusyCursor()

    # 每个查看按钮
    def show_signal_integrity_button(self, event):
        self.create_child_frame(
            _("Signal Integrity"), self.analysis_result, "Signal Integrity"
        )

    def show_smallest_trace_width_button(self, event):
        self.create_child_frame(
            _("Smallest Trace Width"), self.kicad_result, "Smallest Trace Width", True
        )

    def show_smallest_trace_spacing_button(self, event):
        self.create_child_frame(
            _("Smallest Trace Spacing"), self.analysis_result, "Smallest Trace Spacing"
        )

    def show_pad_size_button(self, event):
        self.create_child_frame(_("Pad size"), self.kicad_result, "Pad size", True)

    def show_pad_spacing_button(self, event):
        self.create_child_frame(_("Pad Spacing"), self.analysis_result, "Pad Spacing")

    def show_hatched_copper_pour_button(self, event):
        self.create_child_frame(
            _("Hatched Copper Pour"), self.kicad_result, "Hatched Copper Pour", True
        )

    def show_hole_diameter_button(self, event):
        self.create_child_frame(
            _("Hole Diameter"), self.analysis_result, "Hole Diameter"
        )

    def show_ringHole_button(self, event):
        self.create_child_frame(_("RingHole"), self.kicad_result, "RingHole")

    def show_drill_hole_spacing_button(self, event):
        self.create_child_frame(
            _("Drill Hole Spacing"), self.analysis_result, "Drill Hole Spacing"
        )

    def show_drill_to_copper_button(self, event):
        self.create_child_frame(
            _("Drill to Copper"), self.analysis_result, "Drill to Copper"
        )

    def show_board_edge_clearance_button(self, event):
        self.create_child_frame(
            _("Board Edge Clearance"), self.analysis_result, "Board Edge Clearance"
        )

    def show_special_drill_holes_button(self, event):
        self.create_child_frame(
            _("Special Drill Holes"), self.analysis_result, "Special Drill Holes"
        )

    def show_holes_on_smd_pads_button(self, event):
        self.create_child_frame(
            _("Holes on SMD Pads"), self.analysis_result, "Holes on SMD Pads"
        )

    def show_missing_mask_openings_button(self, event):
        self.create_child_frame(
            _("Missing SMask Openings"), self.analysis_result, "Missing SMask Openings"
        )

    def show_drill_hole_density_button(self, event):
        self.have_same_class_window()
        HoleChildFrameView(
            self,
            self.analysis_result["Drill Hole Density"]["display"],
        ).Show()

    def show_surface_finish_area_button(self, event):
        pass

    def show_test_point_count_button(self, event):
        pass

    def on_select_export_gerber(self, event):
        try:
            gerber_dir = os.path.join(self.path, "dfm", "gerber")
            Path(gerber_dir).mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            gerber_dir = os.path.join(tempfile.gettempdir(), "dfm", "gerber")
            Path(gerber_dir).mkdir(parents=True, exist_ok=True)

        creat_file = CreateFile(self.board)
        creat_file.export_gerber(gerber_dir)
        creat_file.export_drl(gerber_dir)
        filename = GetFilePath("temp.json")
        if os.path.exists(filename):
            os.remove(filename)
        archived = shutil.make_archive(Path(gerber_dir), "zip", Path(gerber_dir))
        if self.have_progress is False:
            self.have_progress = True
            # 下载json文件
            json_path = self.dfm_analysis.download_file(archived, self.name)
            # 解析json文件，保存到结果中
            if pcbnew.GetLanguage() == "简体中文":
                self.analysis_result = self.dfm_analysis.analysis_json(json_path, True)
            else:
                self.analysis_result = self.dfm_analysis.analysis_json(json_path)
            if self.analysis_result == "":
                wx.MessageBox(
                    _("File analysis failure"), _("Help"), style=wx.ICON_INFORMATION
                )
        self.have_progress = False
        self.add_all_item()

    # 添加分析项
    def add_all_item(self):
        if self.analysis_result == {}:
            return
        # kicad项 分析
        minmum_line_width = MinimumLineWidth(self.control, self.board)
        self.kicad_result["Smallest Trace Width"] = minmum_line_width.get_line_width(
            self.analysis_result
        )
        self.kicad_result["RingHole"] = minmum_line_width.get_annular_ring(
            self.analysis_result
        )
        self.kicad_result["Hatched Copper Pour"] = minmum_line_width.get_zone_attribute(
            self.analysis_result
        )
        self.kicad_result["Pad size"] = minmum_line_width.get_pad(self.analysis_result)

        # 板子层数
        self.dfm_maindialog.grid.SetCellValue(
            0, 1, str(self.board.GetCopperLayerCount())
        )

        # 板子尺寸
        self.dfm_maindialog.grid.SetCellValue(
            1, 1, str(self.pcb_setting.get_layer_size())
        )

        # 电气信号
        if self.analysis_result["Signal Integrity"] == "":
            self.dfm_maindialog.grid.SetCellValue(2, 1, self.item_result)

            self.dfm_maindialog.signal_integrity_button.SetBackgroundColour(wx.GREEN)
        else:
            data = self.analysis_result["Signal Integrity"]["display"]
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(2, 1, _("Error(s) detected"))
                self.dfm_maindialog.grid.SetCellTextColour(
                    2, 1, self.analysis_result["Signal Integrity"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(2, 1, self.item_result)
                self.dfm_maindialog.signal_integrity_button.SetBackgroundColour(
                    wx.GREEN
                )

        # 最小间距
        if self.analysis_result["Smallest Trace Spacing"] == "":
            self.dfm_maindialog.grid.SetCellValue(4, 1, self.item_result)
        else:
            data = self.get_data(
                self.analysis_result["Smallest Trace Spacing"]["display"]
            )
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(4, 1, self.unit_conversion(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    4, 1, self.analysis_result["Smallest Trace Spacing"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(4, 1, self.item_result)

        # smd间距
        if self.analysis_result["Pad Spacing"] == "":
            self.dfm_maindialog.grid.SetCellValue(6, 1, self.item_result)
        else:
            data = self.get_data(self.analysis_result["Pad Spacing"]["display"])
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(6, 1, self.unit_conversion(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    6, 1, self.analysis_result["Pad Spacing"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(6, 1, self.item_result)

        # 孔大小
        if self.analysis_result["Hole Diameter"] == "":
            self.dfm_maindialog.grid.SetCellValue(8, 1, self.item_result)
        else:
            data = self.get_data(self.analysis_result["Hole Diameter"]["display"])
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(8, 1, self.unit_conversion(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    8, 1, self.analysis_result["Hole Diameter"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(8, 1, self.item_result)

        # 孔到孔
        if self.analysis_result["Drill Hole Spacing"] == "":
            self.dfm_maindialog.grid.SetCellValue(10, 1, self.item_result)
        else:
            data = self.get_data(self.analysis_result["Drill Hole Spacing"]["display"])
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(10, 1, self.unit_conversion(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    10, 1, self.analysis_result["Drill Hole Spacing"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(10, 1, self.item_result)

        # 孔到线
        if self.analysis_result["Drill to Copper"] == "":
            self.dfm_maindialog.grid.SetCellValue(11, 1, self.item_result)
        else:
            data = self.get_data(self.analysis_result["Drill to Copper"]["display"])
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(11, 1, self.unit_conversion(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    11, 1, self.analysis_result["Drill to Copper"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(11, 1, self.item_result)
        # 板边距离
        if self.analysis_result["Board Edge Clearance"] == "":
            self.dfm_maindialog.grid.SetCellValue(12, 1, self.item_result)
        else:
            data = self.get_data(
                self.analysis_result["Board Edge Clearance"]["display"]
            )
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(12, 1, self.unit_conversion(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    12, 1, self.analysis_result["Board Edge Clearance"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(12, 1, self.item_result)

        # 特殊孔
        if self.analysis_result["Special Drill Holes"] == "":
            self.dfm_maindialog.grid.SetCellValue(13, 1, self.item_result)
        else:
            data = self.get_data(self.analysis_result["Special Drill Holes"]["display"])
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(13, 1, self.unit_conversion(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    13, 1, self.analysis_result["Special Drill Holes"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(13, 1, self.item_result)

        # 孔环
        if self.kicad_result["RingHole"] == "":
            self.dfm_maindialog.grid.SetCellValue(9, 1, self.item_result)
        else:
            minimum_value = self.kicad_result["RingHole"]["display"]
            self.dfm_maindialog.grid.SetCellValue(
                9, 1, self.unit_conversion(minimum_value)
            )
            self.dfm_maindialog.grid.SetCellTextColour(
                9, 1, self.kicad_result["RingHole"]["color"]
            )

        # 最小焊盘
        if self.kicad_result["Pad size"] == "":
            self.dfm_maindialog.grid.SetCellValue(5, 1, self.item_result)
        else:
            minimum_value = self.kicad_result["Pad size"]["display"]
            self.dfm_maindialog.grid.SetCellValue(
                5, 1, self.unit_conversion(minimum_value)
            )
            self.dfm_maindialog.grid.SetCellTextColour(
                5, 1, self.kicad_result["Pad size"]["color"]
            )

        # 最小线宽
        if self.kicad_result["Smallest Trace Width"] == "":
            self.dfm_maindialog.grid.SetCellValue(3, 1, self.item_result)
        else:
            minimum_value = self.kicad_result["Smallest Trace Width"]["display"]
            self.dfm_maindialog.grid.SetCellValue(
                3, 1, self.unit_conversion(minimum_value)
            )
            self.dfm_maindialog.grid.SetCellTextColour(
                3, 1, self.kicad_result["Smallest Trace Width"]["color"]
            )

        # 网格铺铜
        if self.kicad_result["Hatched Copper Pour"] == "":
            self.dfm_maindialog.grid.SetCellValue(7, 1, self.item_result)
        else:
            minimum_value = self.kicad_result["Hatched Copper Pour"]["display"]
            self.dfm_maindialog.grid.SetCellValue(
                7, 1, self.unit_conversion(minimum_value)
            )
            self.dfm_maindialog.grid.SetCellTextColour(
                7, 1, self.kicad_result["Hatched Copper Pour"]["color"]
            )

            # 孔上焊盘
        if self.analysis_result["Holes on SMD Pads"] == "":
            self.dfm_maindialog.grid.SetCellValue(14, 1, self.item_result)
        else:
            data = self.analysis_result["Holes on SMD Pads"]["display"]
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(14, 1, str(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    14, 1, self.analysis_result["Holes on SMD Pads"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(14, 1, self.item_result)

            # 阻焊开窗
        if self.analysis_result["Missing SMask Openings"] == "":
            self.dfm_maindialog.grid.SetCellValue(15, 1, self.item_result)
        else:
            data = self.get_data(
                self.analysis_result["Missing SMask Openings"]["display"]
            )
            if data is not None:
                self.dfm_maindialog.grid.SetCellValue(15, 1, str(data))
                self.dfm_maindialog.grid.SetCellTextColour(
                    15, 1, self.analysis_result["Missing SMask Openings"]["color"]
                )
            else:
                self.dfm_maindialog.grid.SetCellValue(15, 1, self.item_result)

            # 孔密度
        if self.analysis_result["Drill Hole Density"] == "":
            self.dfm_maindialog.grid.SetCellValue(16, 1, self.item_result)
        else:
            self.dfm_maindialog.grid.SetCellValue(
                16, 1, str(self.analysis_result["Drill Hole Density"]["display"])
            )

            # 沉金面积
        if self.analysis_result["Surface Finish Area"] == "":
            self.dfm_maindialog.grid.SetCellValue(17, 1, self.item_result)
        else:
            self.dfm_maindialog.grid.SetCellValue(
                17, 1, str(self.analysis_result["Surface Finish Area"]["display"])
            )

            # 飞针点数
        if self.analysis_result["Test Point Count"] == "":
            self.dfm_maindialog.grid.SetCellValue(18, 1, self.item_result)
        else:
            self.dfm_maindialog.grid.SetCellValue(
                18, 1, str(self.analysis_result["Test Point Count"]["display"])
            )

    # 只获取数据
    def get_data(self, data_string):
        pattern = re.compile(r"(\d+(\.\d+)?)")
        ret = pattern.search(data_string)
        if ret is not None:
            result = ret.group()
            return float(result)

    # 单位转换
    def unit_conversion(self, str_value):
        if self.unit == 0:
            iu_value = float(str_value) / 25.4
            return str(round(iu_value, 3)) + "inch"
        elif self.unit == 5:
            mils_value = float(str_value) * 39.37
            return str(round(mils_value, 3)) + "mils"
        else:
            return str(round(float(str_value), 3)) + "mm"

    def show_rule_manager(self, event):
        rule_item = {}
        item_size = 0
        for item in self.analysis_result:
            if (
                self.analysis_result[item] != ""
                and "check" in self.analysis_result[item]
            ):
                rule_item[item] = []
                for check in self.analysis_result[item]["check"]:
                    rule_result = {}
                    for result in check["result"]:
                        rule_result[result["item"]] = result["rule"]
                        if rule_result not in rule_item[item]:
                            rule_item[item].append(rule_result)
                            item_size += 1
        for window in wx.GetTopLevelWindows():
            if window.GetTitle() in _("Rule View"):
                window.Destroy()
        RuleManagerView(self, rule_item, item_size, self.unit).Show()
