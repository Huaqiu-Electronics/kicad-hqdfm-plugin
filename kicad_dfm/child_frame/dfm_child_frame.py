import os
import wx
import re
from decimal import Decimal
import pcbnew
from .. import config
from ..picture import GetImagePath
from kicad_dfm.child_frame.ui_child_frame import UiChildFrame
from kicad_dfm.settings.graphics_setting import GraphicsSetting
from kicad_dfm.child_frame.child_frame_setting import (
    ChildFrameSetting,
    CHILDFRAME_UNIT_CONVERSION
)
import wx.dataview as dv
from kicad_dfm.child_frame.picture_match_path import PICTURE_MATCH_PATH
from kicad_dfm.settings.timestamp import TimeStamp
from .dfm_child_frame_model import DfmChildFrameModel
import sys


class MyShapeItem(pcbnew.PCB_SHAPE):
    def __init__(self, *args):
        super().__init__(*args)

    def GetLayerSet(self):
        r"""GetLayerSet(BOARD_ITEM self) -> LSET"""
        wx.MessageBox("GetLayerSet")
        return pcbnew.LSET()


class DfmChildFrame(UiChildFrame):
    def __init__(
        self,
        parent,
        title,
        analysis_result,
        json_string,
        line_list,
        _unit,
        _board,
        kicad=False,
    ):
        super().__init__(parent)
        self.temp_layer = {""}
        self.line_list = line_list
        self.board = _board
        self.unit = _unit
        self.result_json = analysis_result
        self.json_string = json_string
        self.message_type = {}
        if pcbnew.GetLanguage() == "English":
            self.message_type = config.Language_english
        else:
            self.message_type = config.Language_chinese
        self.kicad = kicad
        self.combo = 1
        self.graphics_setting = GraphicsSetting(self.board)
        self.child_frame_setting = ChildFrameSetting(self.board)

        self.SetTitle(title)
        self.result = {}
        self.layer_name = []
        self.item_list = []
        self.delete_value = {}
        self.select_number = -1
        # self.combo_box.SetSelection(0)

        self.analysis_result_data = self.get_result()
        self.lst_analysis_result1.AppendTextColumn(
            _("Item"),
            width=-1,
            mode=dv.DATAVIEW_CELL_ACTIVATABLE,
            align=wx.ALIGN_LEFT,
        )

        self.lst_layer.Set(self.get_layer)
        self.lst_analysis_type.Set(self.get_type_data)

        self.lst_layer.Bind(wx.EVT_LISTBOX, self.set_result)
        self.lst_analysis_type.Bind(wx.EVT_LISTBOX, self.analysis_type)
        self.lst_analysis_result1.Bind(
            dv.EVT_DATAVIEW_SELECTION_CHANGED, self.on_analysis_result
        )
        self.lst_analysis_result1.Bind(
            dv.EVT_DATAVIEW_ITEM_ACTIVATED, self.on_analysis_result
        )

        self.combo_box.Bind(wx.EVT_COMBOBOX, self.read_json)
        self.Bind(wx.EVT_CLOSE, self.on_close, self)

        self.first_button.Bind(wx.EVT_BUTTON, self.select_first)
        self.back_button.Bind(wx.EVT_BUTTON, self.select_back)
        self.next_button.Bind(wx.EVT_BUTTON, self.select_next)
        self.last_button.Bind(wx.EVT_BUTTON, self.select_last)
        # 设置事件处理程序

        self.data_view_binding()
        self.dispose_result()
        self.set_layer()
        self.set_color_rule()

        self.Update()
        self.Centre()
        self.Show(True)

    def remove_added_line(self, event):
        if len(self.item_list) != 0:
            for item in self.item_list:
                if item:
                    item.ClearBrightened()
                # item.ClearSelected()
        if len(self.line_list) != 0:
            for line in self.line_list:
                self.board.Delete(line)
            self.line_list.clear()
        pcbnew.Refresh
        # pcbnew.UpdateUserInterface
        event.Skip()

    # 关闭窗口时清空在kicad上的处理
    def on_close(self, event):
        self.remove_added_line(event)
        self.Destroy()

    def select_first(self, event):
        if len(self.get_layer) == 0:
            return
        self.lst_analysis_result1.SelectRow(0)
        self.select_number = 0
        string_data = self.lst_analysis_result1.GetTextValue(
            self.lst_analysis_result1.GetSelectedRow(), 0
        )
        self.analysis_process(string_data, event)
        event.Skip()

    def select_back(self, event):
        if len(self.get_layer) == 0:
            return
        self.select_number = self.lst_analysis_result1.GetSelectedRow()
        self.select_number -= 1
        if self.select_number < 0:
            self.select_number = 0
        self.lst_analysis_result1.SelectRow(self.select_number)
        string_data = self.lst_analysis_result1.GetTextValue(self.select_number, 0)
        self.analysis_process(string_data, event)
        event.Skip()

    def select_next(self, event):
        if len(self.get_layer) == 0:
            return
        self.select_number = self.lst_analysis_result1.GetSelectedRow()
        self.select_number += 1
        if self.select_number > self.lst_analysis_result1.GetItemCount() - 1:
            self.select_number = self.lst_analysis_result1.GetItemCount() - 1
        self.lst_analysis_result1.SelectRow(self.select_number)
        string_data = self.lst_analysis_result1.GetTextValue(self.select_number, 0)
        self.analysis_process(string_data, event)
        event.Skip()

    def select_last(self, event):
        if len(self.get_layer) == 0:
            return
        self.select_number = self.lst_analysis_result1.GetItemCount() - 1
        self.lst_analysis_result1.SelectRow(self.select_number)
        string_data = self.lst_analysis_result1.GetTextValue(self.select_number, 0)
        self.analysis_process(string_data, event)
        event.Skip()

    def read_json(self, event):
        self.combo = self.combo_box.GetSelection()
        self.dispose_result()
        self.get_result()
        self.set_layer()
        self.set_color_rule()
        event.Skip()

    def set_result(self, event):
        self.set_layer()
        self.set_color_rule()
        event.Skip()

    def analysis_type(self, event):
        self.set_color_rule()
        event.Skip()

    def dispose_result(self):
        if self.combo_box.GetSelection() == 1:
            if self.json_string not in self.delete_value.keys():
                if not self.result_json[self.json_string]:
                    return
                for result_list in self.result_json[self.json_string]["check"]:
                    # for result in result_list["result"]:
                    #     if result["color"] == "black":
                    if result_list["result"][0]["color"] == "black":
                        if self.json_string not in self.delete_value:
                            self.delete_value[self.json_string] = []
                        self.delete_value[self.json_string].append(result_list)
            if self.json_string in self.delete_value.keys():
                for result in self.delete_value[self.json_string]:
                    if result in self.result_json[self.json_string]["check"]:
                        self.result_json[self.json_string]["check"].remove(result)

        else:
            if self.json_string in self.delete_value.keys():
                self.result_json[self.json_string]["check"] += self.delete_value[
                    self.json_string
                ]

        self.lst_layer.Set(self.get_layer)
        self.lst_analysis_type.Set(self.get_type_data)

    def set_layer(self):
        if len(self.get_layer) == 0:
            self.layer_name.append("")
            return
        self.layer_name = []
        if self.lst_layer.GetSelections() != wx.NOT_FOUND:
            list_data = self.lst_layer.GetSelections()
        for data in list_data:
            self.layer_name.append(self.lst_layer.GetString(data))
        if len(list_data) == 0:
            for i in range(self.lst_layer.GetCount()):
                self.lst_layer.SetSelection(i)
                self.layer_name.append(self.lst_layer.GetString(i))

        selected_layers = set(self.layer_name)
        selected_item_types = set(self.get_type_data)
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                result_layer = self.child_frame_setting.layer_conversion(
                    self.json_string, result["layer"]
                )
                if (
                    result["item"] not in selected_item_types
                    and result_layer[0] in selected_layers
                ):
                    selected_item_types.add(result["item"])

        self.lst_analysis_type.Set(list(selected_item_types))

    def set_color_rule(self):
        if self.result_json[self.json_string] == "":
            return
        results_list = []
        self.result = {}  # 展示的结果集
        if self.lst_analysis_type.GetSelections() != wx.NOT_FOUND:
            list_data = self.lst_analysis_type.GetSelections()
        num = 0
        list_string = []
        for data in list_data:
            list_string.append(self.lst_analysis_type.GetString(data))
        if len(list_string) == 0 and len(self.get_layer) != 0:
            list_string.append(self.lst_analysis_type.GetString(0))
            self.lst_analysis_type.SetSelection(0)
            bitmap_path =  PICTURE_MATCH_PATH.picture_path(
                    self, list_string[0], self.message_type["picture_path"]
                )
            if bitmap_path is None:
                self.bmp.SetBitmap(wx.Bitmap(GetImagePath("none.png")))
                print(" PICTURE_MATCH_PATH.picture_path() 返回了 None")
            else:
                self.bmp.SetBitmap(bitmap_path)
            self.Layout()

        # 孔环和最小线宽的特殊展示方式
        if self.json_string == "Smallest Trace Width" or self.json_string == "RingHole":
            check_lists =self.result_json[self.json_string]["check"]
            for check_list in self.result_json[self.json_string]["check"]:
                for result in check_list["result"]:
                    result_layer = self.child_frame_setting.layer_conversion(
                        self.json_string, result["layer"]
                    )
                    if (
                        result["item"] in list_string
                        and result_layer[0] in self.layer_name
                    ):
                        is_join = False
                        for number in self.result.keys():
                            # 最小线宽的线宽相同就放一起展示
                            if (
                                result["value"] == self.result[number][0]["value"]
                                and result["layer"] == self.result[number][0]["layer"]
                                and self.json_string == "Smallest Trace Width"
                            ):
                                self.result[number].append(result)
                                is_join = True
                            # 孔环的盘直径和孔径相同才放一起展示
                            elif self.json_string == "RingHole":
                                if (
                                    result["pad_diameter"]
                                    == self.result[number][0]["pad_diameter"]
                                    and result["hole_diameter"]
                                    == self.result[number][0]["hole_diameter"]
                                    and result["layer"]
                                    == self.result[number][0]["layer"]
                                ):
                                    self.result[number].append(result)
                                    is_join = True
                        if is_join is False:
                            num += 1
                            result_list = []
                            result_list.append(result)
                            self.result[str(num)] = result_list
            for result in self.result:
                millimeter_value = round(float(self.result[result][0]["value"]), 3)
                iu_value = CHILDFRAME_UNIT_CONVERSION.Millimeter2iu(millimeter_value)
                mils_value = CHILDFRAME_UNIT_CONVERSION.Millimeter2mils(
                    millimeter_value
                )
                if self.unit == 0:
                    string = CHILDFRAME_UNIT_CONVERSION.multi_string_conversion(
                        result, str(iu_value) + "inch", len(self.result[result])
                    )
                elif self.unit == 5:
                    string = CHILDFRAME_UNIT_CONVERSION.multi_string_conversion(
                        result, str(mils_value) + "mils", len(self.result[result])
                    )
                else:
                    string = CHILDFRAME_UNIT_CONVERSION.multi_string_conversion(
                        result, str(millimeter_value) + "mm", len(self.result[result])
                    )

                value = self.result[result][0]["value"]
                color = self.result[result][0]["color"]
                results_list.append([string, color])

        else:
            for result_list in self.result_json[self.json_string]["check"]:
                for result in result_list["result"]:
                    result_layer = self.child_frame_setting.layer_conversion(
                        self.json_string, result["layer"]
                    )
                    if (
                        result["item"] in list_string
                        and result_layer[0] in self.layer_name
                    ):
                        num += 1
                        if self.json_string == "Holes on SMD Pads":
                            results_list.append(
                                [
                                    CHILDFRAME_UNIT_CONVERSION.string_conversion(
                                        str(num), result["value"]
                                    ),
                                    result["color"],
                                ]
                            )
                        elif result["item"] == _("Aspect Ratio"):
                            millimeter_value = round(float(result["value"]), 2)
                            board_thickness = round(
                                (
                                    self.board.GetDesignSettings().GetBoardThickness()
                                    / 1000000
                                ),
                                2,
                            )
                            hole_diameter = round(board_thickness / millimeter_value, 2)
                            values = (
                                str(millimeter_value)
                                + "("
                                + str(board_thickness)
                                + "/"
                                + str(hole_diameter)
                                + ")"
                                + ", "
                                + str(len(result_list["result"]))
                                + _("pcs")
                            )
                            results_list.append(
                                [
                                    CHILDFRAME_UNIT_CONVERSION.string_conversion(
                                        str(num), values
                                    ),
                                    result["color"],
                                ]
                            )
                        elif self.json_string == "Hole Diameter":
                            # elif result["item"] == _("Largest Drill Size") or result[
                            #     "item"
                            # ] == _("Smallest Drill Size"):
                            millimeter_value = round(float(result["value"]), 3)
                            iu_value = CHILDFRAME_UNIT_CONVERSION.Millimeter2iu(
                                millimeter_value
                            )
                            mils_value = CHILDFRAME_UNIT_CONVERSION.Millimeter2mils(
                                millimeter_value
                            )
                            if self.unit == 0:
                                results_list.append(
                                    [
                                        CHILDFRAME_UNIT_CONVERSION.multi_string_conversion(
                                            str(num),
                                            str(iu_value) + "inch",
                                            len(result_list["result"]),
                                        ),
                                        result["color"],
                                    ]
                                )
                            elif self.unit == 5:
                                results_list.append(
                                    [
                                        CHILDFRAME_UNIT_CONVERSION.multi_string_conversion(
                                            str(num),
                                            str(mils_value) + "mil",
                                            len(result_list["result"]),
                                        ),
                                        result["color"],
                                    ]
                                )
                            else:
                                results_list.append(
                                    [
                                        CHILDFRAME_UNIT_CONVERSION.multi_string_conversion(
                                            str(num),
                                            result["value"] + "mm",
                                            len(result_list["result"]),
                                        ),
                                        result["color"],
                                    ]
                                )
                        else:
                            millimeter_value = round(float(result["value"]), 3)
                            iu_value = CHILDFRAME_UNIT_CONVERSION.Millimeter2iu(
                                millimeter_value
                            )
                            mils_value = CHILDFRAME_UNIT_CONVERSION.Millimeter2mils(
                                millimeter_value
                            )
                            if self.unit == 0:
                                results_list.append(
                                    [
                                        CHILDFRAME_UNIT_CONVERSION.string_conversion(
                                            str(num), str(iu_value) + "inch"
                                        ),
                                        result["color"],
                                    ]
                                )
                            elif self.unit == 5:
                                results_list.append(
                                    [
                                        CHILDFRAME_UNIT_CONVERSION.string_conversion(
                                            str(num), str(mils_value) + "mil"
                                        ),
                                        result["color"],
                                    ]
                                )
                            else:
                                results_list.append(
                                    [
                                        CHILDFRAME_UNIT_CONVERSION.string_conversion(
                                            str(num), result["value"] + "mm"
                                        ),
                                        result["color"],
                                    ]
                                )
                        self.result[str(num)] = result_list
                        break

        self.dfm_child_frame_model.Update(results_list)

    def data_view_binding(self):
        self.dfm_child_frame_model = DfmChildFrameModel(self.analysis_result_data)
        self.lst_analysis_result1.AssociateModel(self.dfm_child_frame_model)
        wx.CallAfter(self.lst_analysis_result1.Refresh)

    def on_analysis_result(self, event):
        selection = self.lst_analysis_result1.GetSelectedRow()
        item_data = self.lst_analysis_result1.GetValue(selection, 0)
        # Assuming item_data is the data associated with the selected row
        # Start the analysis process synchronously
        self.analysis_process(item_data, event)
        event.Skip()

    # 通过选中行的string去查找到对应的item
    def analysis_process(self, string_data, event):
        settings = self.board.GetDesignSettings()
        x = settings.GetAuxOrigin().x
        y = settings.GetAuxOrigin().y
        self.remove_added_line(event)

        self.item_list = []
        pattern = re.compile(r"(\d+(?=(\、)))")
        try:
            search_res = pattern.search(string_data)
        except TypeError as e:
            return
        layer_num = []
        self.board.ClearSelected()
        self.board.SetVisibleAlls()
        if search_res:
            search = search_res.group()
        else:
            return
        # 高亮多个结果的kicad分析项
        if self.json_string == "Smallest Trace Width" or self.json_string == "RingHole":
            self.board.ClearBrightened()
            for result_list in self.result:
                if search == str(result_list):
                    for result in self.result[result_list]:
                        item = self.board.GetItem(result["id"])
                        item.SetBrightened()
                        # item.SetSelected()
                        self.item_list.append(item)
                        for layer in result["layer"]:
                            layer_num.append(self.board.GetLayerID(layer))
                    if len(self.item_list) == 1:
                        pcbnew.FocusOnItem(
                            item, self.board.GetLayerID(self.item_list[0].GetLayer())
                        )
                    else:
                        pcbnew.FocusOnItem(
                            self.item_list[int(len(self.item_list) / 2)],
                            self.board.GetLayerID(
                                self.item_list[int(len(self.item_list) / 2)].GetLayer()
                            ),
                        )
        # 其他项只需要高亮一个结果
        else:
            for result_list in self.result:
                if search == str(result_list):

                    self.remove_added_line(event)
                    if self.json_string in ["Hatched Copper Pour", "Pad size"]:
                        item = self.board.GetItem(self.result[result_list][0]["id"])
                        pcbnew.FocusOnItem(item, self.board.GetLayerID(item.GetLayer()))
                        for layer in self.result[result_list][0]["layer"]:
                            layer_num.append(self.board.GetLayerID(layer))
                        item.SetBrightened()
                        self.item_list.append(item)

                    elif self.json_string in ["Signal Integrity", "Hole Diameter"]:
                        items = []
                        for result in self.result[result_list]["result"]:
                            if result["type"] == 0:
                                if result["et"] == 0:
                                    if self.json_string == "Signal Integrity":
                                        item = self.graphics_setting.get_signal_integrity_segment(
                                            result, x, y
                                        )
                                    else:
                                        item = self.graphics_setting.get_hole_diameter_segment(
                                            result, x, y
                                        )
                                elif result["et"] == 1:
                                    item = (
                                        self.graphics_setting.get_signal_integrity_arc(
                                            result, x, y
                                        )
                                    )
                                elif result["et"] == 3:
                                        item = self.graphics_setting.get_signal_integrity_floating_copper(
                                            result, x, y
                                        )
                                else:
                                    item = (
                                        self.graphics_setting.get_signal_integrity_rect(
                                            result, x, y
                                        )
                                    )
                                items.append(item)
                                self.item_list.append(item)
                            for layer in result["layer"]:
                                layer_num.append(self.board.GetLayerID(layer))
                        if items:
                            for item in items:
                                if not item:
                                    return
                                item.SetBrightened()
                                if type(item) is pcbnew.PCB_TEXT:
                                    pcbnew.FocusOnItem(
                                        item, self.board.GetLayerID(item.GetLayer())
                                    )
                                if len(items) - items.index(item) == 1:
                                    pcbnew.FocusOnItem(
                                        item, self.board.GetLayerID(item.GetLayer())
                                    )

                    elif self.json_string in [
                        "Holes on SMD Pads",
                        "Special Drill Holes",
                    ]:
                        items = []
                        for result in self.result[result_list]["result"]:
                            item = self.graphics_setting.get_SMD_pads_rect_list(
                                result, x, y
                            )
                            items.append(item)
                            self.item_list.append(item)
                            for layer in result["layer"]:
                                layer_num.append(self.board.GetLayerID(layer))
                        if items:
                            self.set_items_Brightened(items)

                    elif self.json_string in [
                        "Drill to Copper",
                        "Smallest Trace Spacing",
                    ]:
                        items = []
                        for result in self.result[result_list]["result"]:
                            if result["item"] == _("Pad Spacing"):
                                items = (
                                    self.graphics_setting.get_pad_spacing_judge_segment(
                                        result, x, y
                                    )
                                )
                            else:
                                items = self.graphics_setting.get_spacing_judge_segment(
                                    result, x, y
                                )
                            for layer in result["layer"]:
                                layer_num.append(self.board.GetLayerID(layer))
                        if items:
                            self.set_items_Brightened(items)

                    elif self.json_string == "Copper-to-Board Edge":
                        self.process_items(
                            self.result[result_list]["result"],
                            self.graphics_setting.get_board_edge_judge_segment,
                            x,
                            y,
                            layer_num,
                        )

                    elif self.json_string in ["Pad Spacing", "Drill Hole Spacing"]:
                        self.process_items(
                            self.result[result_list]["result"],
                            self.graphics_setting.get_pad_spacing_judge_segment,
                            x,
                            y,
                            layer_num,
                        )

                    # dfm analysis item
                    else:
                        for result in self.result[result_list]["result"]:
                            line = pcbnew.PCB_SHAPE()
                            line.GetLayerSet()
                            line.SetLayer(pcbnew.LAYER_DRC_WARNING)
                            line.SetWidth(100000)
                            if result["type"] == 0:
                                if result["et"] == 0:
                                    line = self.graphics_setting.set_segment(
                                        line, result, x, y
                                    )
                                elif result["et"] == 1:
                                    line = self.graphics_setting.set_arc(
                                        line, result, x, y
                                    )
                                else:
                                    line = self.graphics_setting.set_rect(
                                        line, result, x, y
                                    )
                            elif result["type"] == 2:
                                line = self.graphics_setting.set_segment(
                                    line, result, x, y
                                )
                            else:
                                line = self.graphics_setting.set_rect_list(
                                    line, result, x, y
                                )
                            self.line_list.append(line)
                            layer_num.append(pcbnew.Dwgs_User)

                            # show layers
                            for layer in result["layer"]:
                                if self.board.GetLayerID(layer) > -1:
                                    layer_num.append(self.board.GetLayerID(layer))
                                else:
                                    layer_num.append(pcbnew.B_Adhes)
                        count = 0
                        # orientation
                        for line in self.line_list:
                            count += 1
                            self.board.Add(line)
                            line.SetBrightened()
                            if count == len(self.line_list):
                                pcbnew.FocusOnItem(line, layer_num[0])

        # close needn't layers
        if self.check_box.GetValue() is False:
            gal_set = self.board.GetVisibleLayers()
            for num in [x for x in gal_set.Seq()]:
                if num in layer_num:
                    continue
                gal_set.removeLayer(num)
            self.board.SetVisibleLayers(gal_set)
            pcbnew.UpdateUserInterface()
        wx.CallAfter(pcbnew.Refresh)
        event.Skip()

    def process_items(self, results, get_item_func, x, y, layer_num):
        items = []
        for result in results:
            items = get_item_func(result, x, y)
            for layer in result["layer"]:
                layer_num.append(self.board.GetLayerID(layer))
        if items:
            self.set_items_Brightened(items)

    def set_items_Brightened(self, items):
        for item in items:
            if not item:
                return
            self.item_list.append(item)
            item.SetBrightened()
        if len(items) - items.index(item) == 1:
            pcbnew.FocusOnItem(item, self.board.GetLayerID(item.GetLayer()))

    @property
    def get_layer(self):
        layer = []
        if self.result_json[self.json_string] == "":
            return layer
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                if self.kicad is False:
                    result["layer"] = self.child_frame_setting.layer_conversion(
                        self.json_string, result["layer"]
                    )
                if result["layer"][0] not in layer:
                    layer.append(result["layer"][0])
        return layer

    @property
    def get_type_data(self):
        if not hasattr(self, "_cached_analysis_type"):
            # Compute and cache the analysis types
            analysis_type = set()
            if self.result_json[self.json_string] != "":
                for result_list in self.result_json[self.json_string]["check"]:
                    for result in result_list["result"]:
                        analysis_type.add(result["item"])

            # # 遍历列表
            # _cached_analysis_type = []
            # analysis_type_list = list(analysis_type)
            # for item in analysis_type_list:
            #     item = item.strip()  # 去掉首尾空格
            #     _language_item = self.message_type.get(item)  # 使用 get 方法避免 KeyError
            #     if _language_item is None:
            #         print(f"Warning: '{item}' not found in Language_chinese.")
            #         _language_item = item  # 如果找不到，保留原字符串
            #     _cached_analysis_type.append(_language_item)

            _cached_analysis_type = list(analysis_type)
        return _cached_analysis_type

    def get_result(self):
        analysis_result = []
        if self.result_json[self.json_string] == "":
            return analysis_result
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                if result["value"] not in analysis_result:
                    analysis_result.append([result["value"], result["color"]])
        return analysis_result

    def GetImagePath(self, bitmap_path):
        return GetImagePath(bitmap_path)
