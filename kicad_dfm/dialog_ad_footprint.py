import os
import wx
import wx.grid as gridlib
import re
import shutil
from decimal import Decimal
import json
import logging
import pcbnew

from . import config

import gettext
from .helpers import is_nightly
from .create_file import CreateFile
from .rule_manager import RuleManagerFrame
from .hole_child_frame import HoleChildFrame
from .child_frame import ChildFrame
from .picture import GetImagePath
from .analysis import MinimumLineWidth
from .dfm_analysis import DfmAnalysis
from kicad_dfm import GetFilePath

from pathlib import Path

_ = gettext.gettext


class DialogADFootprint(wx.Frame):
    def __init__(self, parent):
        super(wx.Frame, self).__init__(
            parent,
            title=_("HQ DFM"),
            style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP,
        )
        self.control = {}
        self.control = config.Language_english
        # for window in wx.GetTopLevelWindows():
        #     if window.GetTitle().lower() == "dfm analysis":
        #         window.Destroy()
        # wx.MessageBox(f"pcbnew.GetLanguage():{pcbnew.GetLanguage()}")

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
                "The language you selected is currently not supported",
                "Help",
                style=wx.ICON_INFORMATION,
            )
            return

        self.line_list = []
        self.have_progress = False
        self.logger = logging.getLogger(__name__)
        try:
            pcbnew.GetBoard().GetFileName()
            self.board = pcbnew.GetBoard()
        except Exception as e:
            for fp in (
                "C:\\Program Files\\demos\\flat_hierarchy\\flat_hierarchy.kicad_pcb",
                "C:\\Program Files\\demos\\flat_hierarchy\\flat_hierarchy.kicad_pcb",
            ):
                if os.path.exists(fp):
                    self.board = pcbnew.LoadBoard(fp)

        self.path, self.filename = os.path.split(self.board.GetFileName())
        self.board_name = os.path.split(self.board.GetFileName())[1]
        self.name = self.board_name.split(".")[0]
        self.analysis_result = {}
        self.unit = pcbnew.GetUserUnits()
        self.kicad_result = {}
        self.check = False
        self.list = 1
        self.rule_message_list = []
        self.dfm_analysis = DfmAnalysis()

        filename = GetImagePath("icon.png")
        icon = wx.Icon(filename, wx.BITMAP_TYPE_PNG)
        self.SetIcon(icon)  # 设置窗口图标
        panel = wx.Panel(self)
        show_box = wx.GridBagSizer(11, 3)
        ui_box = wx.BoxSizer(wx.VERTICAL)
        box = wx.BoxSizer(wx.HORIZONTAL)
        grid_box = wx.BoxSizer(wx.VERTICAL)
        button_box = wx.BoxSizer(wx.VERTICAL)
        grid_panel = wx.Panel(panel)
        box_panel = wx.Panel(grid_panel)
        ui_panel = wx.Panel(grid_panel)
        button_panel = wx.Panel(panel)
        self.dfm_run_button = wx.Button(
            box_panel,
            wx.ID_ANY,
            self.control["analysis_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.rule_manager_button = wx.Button(
            box_panel,
            wx.ID_ANY,
            self.control["rule_manager"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.grid = wx.grid.Grid(ui_panel, size=(320, 666))
        self.grid.CreateGrid(19, 2)
        self.grid.HideColLabels()
        self.grid.HideRowLabels()
        self.grid.SetColSize(0, 170)
        self.grid.SetColSize(1, 150)
        self.grid.Center()

        self.layer_count = wx.Button(
            button_panel, wx.ID_ANY, "", wx.DefaultPosition, size=(100, 30)
        )
        self.layer_size = wx.Button(
            button_panel, wx.ID_ANY, "", wx.DefaultPosition, size=(100, 30)
        )
        self.signal_integrity_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.smallest_trace_width_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.smallest_trace_spacing_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.pad_size_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.pad_spacing_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.hatched_copper_pour_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.hole_diameter_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.ringHole_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.drill_hole_spacing_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.drill_to_copper_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.board_edge_clearance_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.special_drill_holes_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.holes_on_smd_pads_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.missing_mask_openings_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.drill_hole_density_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.surface_finish_area_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )
        self.test_point_count_button = wx.Button(
            button_panel,
            wx.ID_ANY,
            self.control["check_button"],
            wx.DefaultPosition,
            size=(100, 30),
        )

        for index, value in enumerate(self.control["json_name"]):
            self.grid.SetRowSize(index, 35)
            self.grid.SetCellValue(index, 0, self.control["json_name"][index])
            self.grid.SetCellAlignment(index, 0, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        self.dfm_run_button.Bind(wx.EVT_BUTTON, self.on_select_export_gerber)
        self.rule_manager_button.Bind(wx.EVT_BUTTON, self.show_rule_manager)
        self.signal_integrity_button.Bind(
            wx.EVT_BUTTON, self.show_signal_integrity_button
        )
        self.smallest_trace_width_button.Bind(
            wx.EVT_BUTTON, self.show_smallest_trace_width_button
        )
        self.smallest_trace_spacing_button.Bind(
            wx.EVT_BUTTON, self.show_smallest_trace_spacing_button
        )
        self.pad_size_button.Bind(wx.EVT_BUTTON, self.show_pad_size_button)
        self.pad_spacing_button.Bind(wx.EVT_BUTTON, self.show_pad_spacing_button)
        self.hatched_copper_pour_button.Bind(
            wx.EVT_BUTTON, self.show_hatched_copper_pour_button
        )
        self.hole_diameter_button.Bind(wx.EVT_BUTTON, self.show_hole_diameter_button)
        self.ringHole_button.Bind(wx.EVT_BUTTON, self.show_ringHole_button)
        self.drill_hole_spacing_button.Bind(
            wx.EVT_BUTTON, self.show_drill_hole_spacing_button
        )
        self.drill_to_copper_button.Bind(
            wx.EVT_BUTTON, self.show_drill_to_copper_button
        )
        self.board_edge_clearance_button.Bind(
            wx.EVT_BUTTON, self.show_board_edge_clearance_button
        )
        self.special_drill_holes_button.Bind(
            wx.EVT_BUTTON, self.show_special_drill_holes_button
        )
        self.holes_on_smd_pads_button.Bind(
            wx.EVT_BUTTON, self.show_holes_on_smd_pads_button
        )
        self.missing_mask_openings_button.Bind(
            wx.EVT_BUTTON, self.show_missing_mask_openings_button
        )
        self.drill_hole_density_button.Bind(
            wx.EVT_BUTTON, self.show_drill_hole_density_button
        )
        self.surface_finish_area_button.Bind(
            wx.EVT_BUTTON, self.show_surface_finish_area_button
        )
        self.test_point_count_button.Bind(
            wx.EVT_BUTTON, self.show_test_point_count_button
        )
        self.Bind(wx.EVT_CLOSE, self.on_close)

        ui_box.Add(self.grid, 0, wx.LEFT | wx.TOP, 10)
        ui_panel.SetSizer(ui_box)
        box.Add(self.dfm_run_button, 0, wx.LEFT, 10)
        box.Add(self.rule_manager_button, 0, wx.LEFT, 10)
        box_panel.SetSizer(box)

        button_box.Add(self.layer_count, 0, wx.TOP, 45)
        button_box.Add(self.layer_size, 0, wx.TOP, 5)
        button_box.Add(self.signal_integrity_button, 0, wx.TOP, 5)
        button_box.Add(self.smallest_trace_width_button, 0, wx.TOP, 5)
        button_box.Add(self.smallest_trace_spacing_button, 0, wx.TOP, 5)
        button_box.Add(self.pad_size_button, 0, wx.TOP, 5)
        button_box.Add(self.pad_spacing_button, 0, wx.TOP, 5)
        button_box.Add(self.hatched_copper_pour_button, 0, wx.TOP, 5)
        button_box.Add(self.hole_diameter_button, 0, wx.TOP, 5)
        button_box.Add(self.ringHole_button, 0, wx.TOP, 5)
        button_box.Add(self.drill_hole_spacing_button, 0, wx.TOP, 5)
        button_box.Add(self.drill_to_copper_button, 0, wx.TOP, 5)
        button_box.Add(self.board_edge_clearance_button, 0, wx.TOP, 5)
        button_box.Add(self.special_drill_holes_button, 0, wx.TOP, 5)
        button_box.Add(self.holes_on_smd_pads_button, 0, wx.TOP, 5)
        button_box.Add(self.missing_mask_openings_button, 0, wx.TOP, 5)
        button_box.Add(self.drill_hole_density_button, 0, wx.TOP, 5)
        button_box.Add(self.surface_finish_area_button, 0, wx.TOP, 5)
        button_box.Add(self.test_point_count_button, 0, wx.TOP, 5)
        button_panel.SetSizer(button_box)
        grid_box.Add(box_panel, 0, wx.TOP, 0)
        grid_box.Add(ui_panel, 0, wx.TOP, 5)
        grid_panel.SetSizer(grid_box)
        show_box.Add(
            grid_panel, pos=(1, 0), span=(0, 0), flag=wx.ALL | wx.EXPAND, border=5
        )
        show_box.Add(
            button_panel, pos=(1, 1), span=(0, 0), flag=wx.ALL | wx.EXPAND, border=5
        )
        panel.SetSizer(show_box)
        panel.Fit()

        self.SetSize(wx.Size(480, 820))
        self.Layout()
        self.Centre(wx.BOTH)
        self.add_temp_json()

    def on_close(self, event):
        for line in self.line_list:
            self.board.Delete(line)
        self.Destroy()

    def add_temp_json(self):
        # current_file = os.path.abspath(os.path.dirname(__file__))
        json_name = GetFilePath("temp.json")
        # json_name = current_file + "\\temp.json"
        temp_filename = GetFilePath("name.json")
        # current_file + "\\name.json"
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
                            "文件解析失败，请点击dfm分析", "Help", style=wx.ICON_INFORMATION
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
            "Signal Integrity",
            "Smallest Trace Width",
            "Smallest Trace Spacing",
            "Pad size",
            "Pad Spacing",
            "Hatched Copper Pour",
            "Hole Diameter",
            "RingHole",
            "Drill Hole Spacing",
            "Drill to Copper",
            "Board Edge Clearance",
            "Special Drill Holes",
            "Holes on SMD Pads",
            "Missing SMask Openings",
            "Drill Hole Density",
            "Surface Finish Area",
            "Test Point Count",
        ]
        windows = wx.GetTopLevelWindows()
        dfm_analysis_window = [w for w in windows if w.GetTitle() in title_name]

        if len(dfm_analysis_window) != 0:
            for window in dfm_analysis_window:
                window.Destroy()

    def create_child_frame(
        self, title, analysis_result, line_list, is_kicad_result=False
    ):
        self.have_same_class_window()
        child_frame = ChildFrame(
            self,
            title,
            analysis_result,
            title,
            self.check,
            self.list,
            line_list,
            os.path.abspath(os.path.dirname(__file__)),
            self.board,
            is_kicad_result,
        )
        child_frame.Show()

    # 每个查看按钮
    def show_signal_integrity_button(self, event):
        self.create_child_frame(
            "Signal Integrity", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Signal Integrity",
        #     self.analysis_result,
        #     "Signal Integrity",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_smallest_trace_width_button(self, event):
        self.create_child_frame(
            "Smallest Trace Width", self.kicad_result, self.line_list, True
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Smallest Trace Width",
        #     self.kicad_result,
        #     "Smallest Trace Width",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        #     True,
        # )
        # child_frame.Show()

    def show_smallest_trace_spacing_button(self, event):
        self.create_child_frame(
            "Smallest Trace Spacing", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Smallest Trace Spacing",
        #     self.analysis_result,
        #     "Smallest Trace Spacing",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_pad_size_button(self, event):
        self.create_child_frame("Pad size", self.kicad_result, self.line_list, True)
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Pad size",
        #     self.kicad_result,
        #     "Pad size",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        #     True,
        # )
        # child_frame.Show()

    def show_pad_spacing_button(self, event):
        self.create_child_frame("Pad Spacing", self.analysis_result, self.line_list)
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Pad Spacing",
        #     self.analysis_result,
        #     "Pad Spacing",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_hatched_copper_pour_button(self, event):
        self.create_child_frame(
            "Hatched Copper Pour", self.kicad_result, self.line_list, True
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Hatched Copper Pour",
        #     self.kicad_result,
        #     "Hatched Copper Pour",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        #     True,
        # )
        # child_frame.Show()

    def show_hole_diameter_button(self, event):
        self.create_child_frame("Hole Diameter", self.analysis_result, self.line_list)
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Hole Diameter",
        #     self.analysis_result,
        #     "Hole Diameter",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_ringHole_button(self, event):
        self.create_child_frame("RingHole", self.kicad_result, self.line_list, True)
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "RingHole",
        #     self.kicad_result,
        #     "RingHole",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        #     True,
        # )
        # child_frame.Show()

    def show_drill_hole_spacing_button(self, event):
        self.create_child_frame(
            "Drill Hole Spacing", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Drill Hole Spacing",
        #     self.analysis_result,
        #     "Drill Hole Spacing",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_drill_to_copper_button(self, event):
        self.create_child_frame("Drill to Copper", self.analysis_result, self.line_list)
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Drill to Copper",
        #     self.analysis_result,
        #     "Drill to Copper",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_board_edge_clearance_button(self, event):
        self.create_child_frame(
            "Board Edge Clearance", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Board Edge Clearance",
        #     self.analysis_result,
        #     "Board Edge Clearance",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_special_drill_holes_button(self, event):
        self.create_child_frame(
            "Special Drill Holes", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Special Drill Holes",
        #     self.analysis_result,
        #     "Special Drill Holes",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_holes_on_smd_pads_button(self, event):
        self.create_child_frame(
            "Holes on SMD Pads", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Holes on SMD Pads",
        #     self.analysis_result,
        #     "Holes on SMD Pads",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_missing_mask_openings_button(self, event):
        self.create_child_frame(
            "Missing SMask Openings", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Missing SMask Openings",
        #     self.analysis_result,
        #     "Missing SMask Openings",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_drill_hole_density_button(self, event):
        grid_frame = HoleChildFrame(
            self,
            self.analysis_result["Drill Hole Density"]["display"],
            os.path.abspath(os.path.dirname(__file__)),
        )
        grid_frame.Show()

    def show_surface_finish_area_button(self, event):
        self.create_child_frame(
            "Surface Finish Area", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Surface Finish Area",
        #     self.analysis_result,
        #     "Surface Finish Area",
        #     self.check,
        #     self.list,
        #     self.line_list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    def show_test_point_count_button(self, event):
        self.create_child_frame(
            "Test Point Count", self.analysis_result, self.line_list
        )
        # self.have_same_class_window()
        # child_frame = ChildFrame(
        #     self,
        #     "Test Point Count",
        #     self.analysis_result,
        #     "Test Point Count",
        #     self.check,
        #     self.list,
        #     os.path.abspath(os.path.dirname(__file__)),
        # )
        # child_frame.Show()

    # 处理 kicad 获取的层尺寸信息
    def get_layer_size(self):
        drawings = self.board.GetDrawings()
        for drawing in drawings:
            if drawing.GetLayer() == 44:
                width = drawing.GetWidth() / 1000000

        box = self.board.GetBoardEdgesBoundingBox()
        box_x = box.GetWidth() / 1000000
        box_y = box.GetHeight() / 1000000
        return str(round(box_x - width, 2)) + "*" + str(round(box_y - width, 2))

    def on_select_export_gerber(self, event):
        gerber_dir = os.path.join(self.path, "pcb", "gerber")
        Path(gerber_dir).mkdir(parents=True, exist_ok=True)
        creat_file = CreateFile(self.board)
        creat_file.export_gerber(gerber_dir)
        creat_file.export_drl(gerber_dir)
        current_file = os.path.abspath(os.path.dirname(__file__))
        filename = current_file + "\\temp.json"
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
                wx.MessageBox("文件分析失败", "Help", style=wx.ICON_INFORMATION)
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
        self.grid.SetRowSize(0, 35)
        self.grid.SetCellValue(0, 1, str(self.board.GetCopperLayerCount()))
        self.grid.SetCellAlignment(0, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # 板子尺寸
        self.grid.SetRowSize(1, 35)
        self.grid.SetCellValue(1, 1, str(self.get_layer_size()))
        self.grid.SetCellAlignment(1, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # 电气信号
        if self.analysis_result["Signal Integrity"] == "":
            self.grid.SetRowSize(2, 35)
            self.grid.SetCellValue(2, 1, self.control["item_result"])
            self.signal_integrity_button.SetBackgroundColour(wx.GREEN)
            self.grid.SetCellAlignment(2, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.analysis_result["Signal Integrity"]["display"]
            if data is not None:
                self.grid.SetRowSize(2, 35)
                self.grid.SetCellValue(2, 1, data)
                self.grid.SetCellAlignment(2, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    2, 1, self.analysis_result["Signal Integrity"]["color"]
                )
            else:
                self.grid.SetRowSize(2, 35)
                self.grid.SetCellValue(2, 1, self.control["item_result"])
                self.signal_integrity_button.SetBackgroundColour(wx.GREEN)
                self.grid.SetCellAlignment(2, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # 最小间距
        if self.analysis_result["Smallest Trace Spacing"] == "":
            self.grid.SetRowSize(4, 35)
            self.grid.SetCellValue(4, 1, self.control["item_result"])
            self.grid.SetCellAlignment(4, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.get_data(
                self.analysis_result["Smallest Trace Spacing"]["display"]
            )
            if data is not None:
                self.grid.SetRowSize(4, 35)
                self.grid.SetCellValue(4, 1, self.unit_conversion(data))
                self.grid.SetCellAlignment(4, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    4, 1, self.analysis_result["Smallest Trace Spacing"]["color"]
                )
            else:
                self.grid.SetRowSize(4, 35)
                self.grid.SetCellValue(4, 1, self.control["item_result"])
                self.grid.SetCellAlignment(4, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # smd间距
        if self.analysis_result["Pad Spacing"] == "":
            self.grid.SetRowSize(6, 35)
            self.grid.SetCellValue(6, 1, self.control["item_result"])
            self.grid.SetCellAlignment(6, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.get_data(self.analysis_result["Pad Spacing"]["display"])
            if data is not None:
                self.grid.SetRowSize(6, 35)
                self.grid.SetCellValue(6, 1, self.unit_conversion(data))
                self.grid.SetCellAlignment(6, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    6, 1, self.analysis_result["Pad Spacing"]["color"]
                )
            else:
                self.grid.SetRowSize(6, 35)
                self.grid.SetCellValue(6, 1, self.control["item_result"])
                self.grid.SetCellAlignment(6, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # 孔大小
        if self.analysis_result["Hole Diameter"] == "":
            self.grid.SetRowSize(8, 35)
            self.grid.SetCellValue(8, 1, self.control["item_result"])
            self.grid.SetCellAlignment(8, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.get_data(self.analysis_result["Hole Diameter"]["display"])
            if data is not None:
                self.grid.SetRowSize(8, 35)
                self.grid.SetCellValue(8, 1, self.unit_conversion(data))
                self.grid.SetCellAlignment(8, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    8, 1, self.analysis_result["Hole Diameter"]["color"]
                )
            else:
                self.grid.SetRowSize(8, 35)
                self.grid.SetCellValue(8, 1, self.control["item_result"])
                self.grid.SetCellAlignment(8, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # 孔到孔
        if self.analysis_result["Drill Hole Spacing"] == "":
            self.grid.SetRowSize(10, 35)
            self.grid.SetCellValue(10, 1, self.control["item_result"])
            self.grid.SetCellAlignment(10, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.get_data(self.analysis_result["Drill Hole Spacing"]["display"])
            if data is not None:
                self.grid.SetRowSize(10, 35)
                self.grid.SetCellValue(10, 1, self.unit_conversion(data))
                self.grid.SetCellAlignment(10, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    10, 1, self.analysis_result["Drill Hole Spacing"]["color"]
                )
            else:
                self.grid.SetRowSize(10, 35)
                self.grid.SetCellValue(10, 1, self.control["item_result"])
                self.grid.SetCellAlignment(10, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # 孔到线
        if self.analysis_result["Drill to Copper"] == "":
            self.grid.SetRowSize(11, 35)
            self.grid.SetCellValue(11, 1, self.control["item_result"])
            self.grid.SetCellAlignment(11, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.get_data(self.analysis_result["Drill to Copper"]["display"])
            if data is not None:
                self.grid.SetRowSize(11, 35)
                self.grid.SetCellValue(11, 1, self.unit_conversion(data))
                self.grid.SetCellAlignment(11, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    11, 1, self.analysis_result["Drill to Copper"]["color"]
                )
            else:
                self.grid.SetRowSize(11, 35)
                self.grid.SetCellValue(11, 1, self.control["item_result"])
                self.grid.SetCellAlignment(11, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        # 板边距离
        if self.analysis_result["Board Edge Clearance"] == "":
            self.grid.SetRowSize(12, 35)
            self.grid.SetCellValue(12, 1, self.control["item_result"])
            self.grid.SetCellAlignment(12, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.get_data(
                self.analysis_result["Board Edge Clearance"]["display"]
            )
            if data is not None:
                self.grid.SetRowSize(12, 35)
                self.grid.SetCellValue(12, 1, self.unit_conversion(data))
                self.grid.SetCellAlignment(12, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    12, 1, self.analysis_result["Board Edge Clearance"]["color"]
                )
            else:
                self.grid.SetRowSize(12, 35)
                self.grid.SetCellValue(12, 1, self.control["item_result"])
                self.grid.SetCellAlignment(12, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # 特殊孔
        if self.analysis_result["Special Drill Holes"] == "":
            self.grid.SetRowSize(13, 35)
            self.grid.SetCellValue(13, 1, self.control["item_result"])
            self.grid.SetCellAlignment(13, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.get_data(self.analysis_result["Special Drill Holes"]["display"])
            if data is not None:
                self.grid.SetRowSize(13, 35)
                self.grid.SetCellValue(13, 1, self.unit_conversion(data))
                self.grid.SetCellAlignment(13, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    13, 1, self.analysis_result["Special Drill Holes"]["color"]
                )
            else:
                self.grid.SetRowSize(13, 35)
                self.grid.SetCellValue(13, 1, self.control["item_result"])
                self.grid.SetCellAlignment(13, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

        # 孔环
        if self.kicad_result["RingHole"] == "":
            self.grid.SetRowSize(9, 35)
            self.grid.SetCellValue(9, 1, self.control["item_result"])
            self.grid.SetCellAlignment(9, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            minimum_value = self.kicad_result["RingHole"]["display"]
            self.grid.SetRowSize(9, 35)
            self.grid.SetCellValue(9, 1, self.unit_conversion(minimum_value))
            self.grid.SetCellAlignment(9, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
            self.grid.SetCellTextColour(9, 1, self.kicad_result["RingHole"]["color"])

        # 最小焊盘
        if self.kicad_result["Pad size"] == "":
            self.grid.SetRowSize(5, 35)
            self.grid.SetCellValue(5, 1, self.control["item_result"])
            self.grid.SetCellAlignment(5, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            minimum_value = self.kicad_result["Pad size"]["display"]
            self.grid.SetRowSize(5, 35)
            self.grid.SetCellValue(5, 1, self.unit_conversion(minimum_value))
            self.grid.SetCellAlignment(5, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
            self.grid.SetCellTextColour(5, 1, self.kicad_result["Pad size"]["color"])

        # 最小线宽
        if self.kicad_result["Smallest Trace Width"] == "":
            self.grid.SetRowSize(3, 35)
            self.grid.SetCellValue(3, 1, self.control["item_result"])
            self.grid.SetCellAlignment(3, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            minimum_value = self.kicad_result["Smallest Trace Width"]["display"]
            self.grid.SetRowSize(3, 35)
            self.grid.SetCellValue(3, 1, self.unit_conversion(minimum_value))
            self.grid.SetCellAlignment(3, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
            self.grid.SetCellTextColour(
                3, 1, self.kicad_result["Smallest Trace Width"]["color"]
            )

        # 网格铺铜
        if self.kicad_result["Hatched Copper Pour"] == "":
            self.grid.SetRowSize(7, 35)
            self.grid.SetCellValue(7, 1, self.control["item_result"])
            self.grid.SetCellAlignment(7, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            minimum_value = self.kicad_result["Hatched Copper Pour"]["display"]
            self.grid.SetRowSize(7, 35)
            self.grid.SetCellValue(7, 1, self.unit_conversion(minimum_value))
            self.grid.SetCellAlignment(7, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
            self.grid.SetCellTextColour(
                7, 1, self.kicad_result["Hatched Copper Pour"]["color"]
            )

            # 孔上焊盘
        if self.analysis_result["Holes on SMD Pads"] == "":
            self.grid.SetRowSize(14, 35)
            self.grid.SetCellValue(14, 1, self.control["item_result"])
            self.grid.SetCellAlignment(14, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.analysis_result["Holes on SMD Pads"]["display"]
            if data is not None:
                self.grid.SetRowSize(14, 35)
                self.grid.SetCellValue(14, 1, str(data))
                self.grid.SetCellAlignment(14, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellTextColour(
                    14, 1, self.analysis_result["Holes on SMD Pads"]["color"]
                )
            else:
                self.grid.SetRowSize(14, 35)
                self.grid.SetCellValue(14, 1, self.control["item_result"])
                self.grid.SetCellAlignment(14, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

            # 阻焊开窗
        if self.analysis_result["Missing SMask Openings"] == "":
            self.grid.SetRowSize(15, 35)
            self.grid.SetCellValue(15, 1, self.control["item_result"])
            self.grid.SetCellAlignment(15, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            data = self.get_data(
                self.analysis_result["Missing SMask Openings"]["display"]
            )
            if data is not None:
                self.grid.SetRowSize(15, 35)
                self.grid.SetCellValue(15, 1, str(data))
                self.grid.SetCellTextColour(
                    15, 1, self.analysis_result["Missing SMask Openings"]["color"]
                )
                self.grid.SetCellAlignment(15, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
            else:
                self.grid.SetRowSize(15, 35)
                self.grid.SetCellValue(15, 1, self.control["item_result"])
                self.grid.SetCellAlignment(15, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

            # 孔密度
        if self.analysis_result["Drill Hole Density"] == "":
            self.grid.SetRowSize(16, 35)
            self.grid.SetCellValue(16, 1, self.control["item_result"])
            self.grid.SetCellAlignment(16, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            self.grid.SetRowSize(16, 35)
            self.grid.SetCellValue(
                16, 1, str(self.analysis_result["Drill Hole Density"]["display"])
            )
            self.grid.SetCellAlignment(16, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

            # 沉金面积
        if self.analysis_result["Surface Finish Area"] == "":
            self.grid.SetRowSize(17, 35)
            self.grid.SetCellValue(17, 1, self.control["item_result"])
            self.grid.SetCellAlignment(17, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            self.grid.SetRowSize(17, 35)
            self.grid.SetCellValue(
                17, 1, str(self.analysis_result["Surface Finish Area"]["display"])
            )
            self.grid.SetCellAlignment(17, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

            # 飞针点数
        if self.analysis_result["Test Point Count"] == "":
            self.grid.SetRowSize(18, 35)
            self.grid.SetCellValue(18, 1, self.control["item_result"])
            self.grid.SetCellAlignment(18, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        else:
            self.grid.SetRowSize(18, 35)
            self.grid.SetCellValue(
                18, 1, str(self.analysis_result["Test Point Count"]["display"])
            )
            self.grid.SetCellAlignment(18, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)

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
            return str(round(iu_value), 3) + "inch"
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
        RuleManagerFrame(self, rule_item, item_size, self.unit, pcbnew.GetLanguage())
