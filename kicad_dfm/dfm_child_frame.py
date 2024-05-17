import os
import wx
import re
from decimal import Decimal
import pcbnew
import threading
from . import config
from .picture import GetImagePath
from kicad_dfm.child_frame.ui_child_frame import UiChildFrame
from kicad_dfm.settings.graphics_setting import GRAPHICS_SETTING
from kicad_dfm.child_frame.child_frame_model import ChildFrameModel
import wx.dataview as dv
from kicad_dfm.child_frame.picture_match_path import PICTURE_MATCH_PATH
from kicad_dfm.settings.timestamp import TimeStamp


class DfmChildFrame(UiChildFrame):
    def __init__(
        self,
        parent,
        title,
        result_json,
        json_string,
        line_list,
        _unit,
        _board,
        kicad=False,
    ):
        self.temp_layer = {""}
        self.line_list = line_list
        self.board = _board
        self.unit = _unit
        self.result_json = result_json
        self.json_string = json_string
        self.message_type = {}
        if pcbnew.GetLanguage() == "简体中文":
            self.message_type = config.Language_chinese
        else:
            self.message_type = config.Language_english
        self.kicad = kicad
        self.combo = 1
        super().__init__(parent)
        self.SetTitle(title)
        self.result = {}
        self.layer_name = []
        self.item_list = []
        self.delete_value = {}
        self.select_number = -1
        self.process_lock = threading.Lock()

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
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.first_button.Bind(wx.EVT_BUTTON, self.select_first)
        self.back_button.Bind(wx.EVT_BUTTON, self.select_back)
        self.next_button.Bind(wx.EVT_BUTTON, self.select_next)
        self.last_button.Bind(wx.EVT_BUTTON, self.select_last)

        self.dispose_result()
        self.set_layer()
        self.set_color_rule()

        self.Update()
        self.Centre()
        self.Show(True)

    # 关闭窗口时清空在kicad上的处理
    def on_close(self, event):
        if len(self.line_list) != 0:
            for line in self.line_list:
                self.board.Delete(line)
        self.line_list.clear()
        for item in self.item_list:
            item.ClearBrightened()
        # pcbnew.Refresh()
        self.Destroy()

    def select_first(self, event):
        if len(self.get_layer) == 0:
            return
        self.lst_analysis_result1.SelectRow(0)
        self.select_number = 0
        string_data = self.lst_analysis_result1.GetTextValue(
            self.lst_analysis_result1.GetSelectedRow(), 0
        )
        self.analysis_process(string_data)

    def select_back(self, event):
        if len(self.get_layer) == 0:
            return
        self.select_number = self.lst_analysis_result1.GetSelectedRow()
        self.select_number -= 1
        if self.select_number < 0:
            self.select_number = 0
        self.lst_analysis_result1.SelectRow(self.select_number)
        string_data = self.lst_analysis_result1.GetTextValue(self.select_number, 0)
        self.analysis_process(string_data)

    def select_next(self, event):
        if len(self.get_layer) == 0:
            return
        self.select_number = self.lst_analysis_result1.GetSelectedRow()
        self.select_number += 1
        if self.select_number > self.lst_analysis_result1.GetItemCount() - 1:
            self.select_number = self.lst_analysis_result1.GetItemCount() - 1
        self.lst_analysis_result1.SelectRow(self.select_number)
        string_data = self.lst_analysis_result1.GetTextValue(self.select_number, 0)
        self.analysis_process(string_data)

    def select_last(self, event):
        if len(self.get_layer) == 0:
            return
        self.select_number = self.lst_analysis_result1.GetItemCount() - 1
        self.lst_analysis_result1.SelectRow(self.select_number)
        string_data = self.lst_analysis_result1.GetTextValue(self.select_number, 0)
        self.analysis_process(string_data)

    def dispose_result(self):
        if self.combo_box.GetSelection() == 1:
            if self.json_string not in self.delete_value.keys():
                for result_list in self.result_json[self.json_string]["check"]:
                    for result in result_list["result"]:
                        if result["color"] == "black":
                            if self.json_string not in self.delete_value.keys():
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

    def read_json(self, event):
        self.combo = self.combo_box.GetSelection()
        self.dispose_result()
        self.get_result()
        self.set_layer()
        self.set_color_rule()

    def set_result(self, event):
        self.set_layer()
        self.set_color_rule()

    def set_layer(self):
        if len(self.get_layer) == 0:
            self.layer_name.append("")
            return
        self.layer_name = []
        # self.analysis_type_data = []
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
                result_layer = self.layer_conversion(result["layer"])
                if (
                    result["item"] not in selected_item_types
                    and result_layer[0] in selected_layers
                ):
                    selected_item_types.add(result["item"])

        self.lst_analysis_type.Set(list(selected_item_types))

    def analysis_type(self, event):
        self.set_color_rule()

    def set_color_rule(self):
        if self.result_json[self.json_string] == "":
            return
        self.analysis_result_data = []
        result_flag_list = {}
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
            self.bmp.SetBitmap(
                PICTURE_MATCH_PATH.picture_path(
                    self, list_string[0], self.message_type["picture_path"]
                )
            )

        # 孔环和最小线宽的特殊展示方式
        if self.json_string == "Smallest Trace Width" or self.json_string == "RingHole":
            for check_list in self.result_json[self.json_string]["check"]:
                for result in check_list["result"]:
                    result_layer = self.layer_conversion(result["layer"])
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
                iu_value = self.Millimeter2iu(millimeter_value)
                mils_value = self.Millimeter2mils(millimeter_value)
                if self.unit == 0:
                    string = (
                        result
                        + "、"
                        + str(iu_value)
                        + "inch"
                        + ","
                        + str(len(self.result[result]))
                        + _("pcs")
                    )
                elif self.unit == 5:
                    string = (
                        result
                        + "、"
                        + str(mils_value)
                        + "mils"
                        + ","
                        + str(len(self.result[result]))
                        + _("pcs")
                    )
                else:
                    string = (
                        result
                        + "、"
                        + str(millimeter_value)
                        + "mm"
                        + ","
                        + str(len(self.result[result]))
                        + _("pcs")
                    )
                self.analysis_result_data.append(string)
            temp_num = 0
            for result_flag in result_flag_list:
                if self.result[result_flag]["color"] == "red":
                    self.lst_analysis_result1.AssociateModel()
                elif self.result[result_flag]["color"] == "gold":
                    self.lst_analysis_result1.SetItemForegroundColour(
                        temp_num, wx.YELLOW
                    )
                elif self.result[result_flag]["color"] == "black":
                    self.lst_analysis_result1.SetItemForegroundColour(
                        temp_num, wx.BLACK
                    )
                temp_num += 1
        else:
            for result_list in self.result_json[self.json_string]["check"]:
                for result in result_list["result"]:
                    result_layer = self.layer_conversion(result["layer"])
                    if (
                        result["item"] in list_string
                        and result_layer[0] in self.layer_name
                    ):
                        num += 1
                        if self.json_string == "Holes on SMD Pads":
                            result_flag_list[str(num)] = result["value"]
                        elif result["item"] == "Aspect Ratio":
                            millimeter_value = round(float(result["value"]), 2)
                            result_flag_list[str(num)] = result["value"]
                            board_thickness = round(
                                (
                                    self.board.GetDesignSettings().GetBoardThickness()
                                    / 1000000
                                ),
                                2,
                            )
                            hole_diameter = round(board_thickness / millimeter_value, 2)
                            result_flag_list[str(num)] = (
                                str(millimeter_value)
                                + "("
                                + str(board_thickness)
                                + "/"
                                + str(hole_diameter)
                                + ")"
                            )
                        else:
                            millimeter_value = round(float(result["value"]), 3)
                            iu_value = self.Millimeter2iu(millimeter_value)
                            mils_value = self.Millimeter2mils(millimeter_value)
                            if self.unit == 0:
                                result_flag_list[str(num)] = str(iu_value) + "inch"
                            elif self.unit == 5:
                                result_flag_list[str(num)] = str(mils_value) + "mil"
                            else:
                                result_flag_list[str(num)] = result["value"] + "mm"
                        self.result[str(num)] = result_list
                        break
            for flag in result_flag_list:
                string = flag + "、 " + result_flag_list.get(flag)
                self.analysis_result_data.append(string)

        self.lst_analysis_result1.DeleteAllItems()
        for value in self.analysis_result_data:
            self.lst_analysis_result1.AppendItem([value])

    def Millimeter2iu(self, millimeter_value):
        return round(millimeter_value / 25.4, 3)

    def Millimeter2mils(self, millimeter_value):
        return round((millimeter_value * 39.37), 3)

    def on_analysis_result(self, event):
        selection = self.lst_analysis_result1.GetSelectedRow()
        item_data = self.lst_analysis_result1.GetValue(selection, 0)
        # Assuming item_data is the data associated with the selected row
        # Start the analysis process synchronously
        self.analysis_process(item_data)
        event.Skip()

    # 通过选中行的string去查找到对应的item
    def analysis_process(self, string_data):
        settings = self.board.GetDesignSettings()
        x = settings.GetAuxOrigin().x
        y = settings.GetAuxOrigin().y
        for clear_item in self.item_list:
            clear_item.ClearBrightened()
        self.item_list = []
        pattern = re.compile(r"(\d+(?=(\、)))")
        search_res = pattern.search(string_data)
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
                    # kicad分析项
                    if (
                        self.json_string == "Hatched Copper Pour"
                        and self.json_string == "Pad size"
                    ):
                        item = self.board.GetItem(self.result[result_list][0]["id"])
                        pcbnew.FocusOnItem(item, self.board.GetLayerID(item.GetLayer()))
                        for layer in self.result[result_list][0]["layer"]:
                            layer_num.append(self.board.GetLayerID(layer))
                        item.SetBrightened()
                        self.item_list.append(item)
                    # dfm分析项
                    else:
                        if len(self.line_list) != 0:
                            for line in self.line_list:
                                self.board.Delete(line)
                            self.line_list.clear()
                        for result in self.result[result_list]["result"]:
                            # 多种的数据格式
                            line = pcbnew.PCB_SHAPE()
                            line.SetLayer(pcbnew.LAYER_DRC_WARNING)
                            line.SetWidth(250000)
                            if result["type"] == 0:
                                if result["et"] == 0:
                                    line = GRAPHICS_SETTING.set_segment(
                                        self, line, result, x, y
                                    )
                                elif result["et"] == 1:
                                    line = GRAPHICS_SETTING.set_arc(
                                        self, line, result, x, y
                                    )
                                else:
                                    line = GRAPHICS_SETTING.set_rect(
                                        self, line, result, x, y
                                    )
                            elif result["type"] == 2:
                                line = GRAPHICS_SETTING.set_segment(
                                    self, line, result, x, y
                                )
                            else:
                                line = GRAPHICS_SETTING.set_rect_list(
                                    self, line, result, x, y
                                )
                            self.line_list.append(line)
                            layer_num.append(pcbnew.Dwgs_User)
                        # 显示的层
                        for result in self.result[result_list]["result"]:
                            for layer in result["layer"]:
                                layer_num.append(self.board.GetLayerID(layer))
                        count = 0
                        # 定位
                        for line in self.line_list:
                            count += 1
                            self.board.Add(line)
                            # line.SetSelected()
                            line.SetBrightened()
                            if count == len(self.line_list):
                                pcbnew.FocusOnItem(line, pcbnew.Dwgs_User)
        # 关闭不需要显示的层
        if self.check_box.GetValue() is False:
            gal_set = self.board.GetVisibleLayers()
            for num in [x for x in gal_set.Seq()]:
                if num in layer_num:
                    continue
                gal_set.removeLayer(num)
            self.board.SetVisibleLayers(gal_set)
            wx.CallAfter(pcbnew.UpdateUserInterface)
        wx.CallAfter(pcbnew.Refresh)

    @property
    def get_layer(self):
        layer = []
        if self.result_json[self.json_string] == "":
            return layer
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                if self.kicad is False:
                    result["layer"] = self.layer_conversion(result["layer"])
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
            _cached_analysis_type = list(analysis_type)
        return _cached_analysis_type

    def get_result(self):
        analysis_result = []
        if self.result_json[self.json_string] == "":
            return analysis_result
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                if result["value"] not in analysis_result:
                    analysis_result.append(result["value"])
        return analysis_result

    def layer_conversion(self, layer_result):
        if (
            self.json_string == "Hatched Copper Pour"
            or self.json_string == "Pad size"
            or self.json_string == "Smallest Trace Width"
            or self.json_string == "RingHole"
        ):
            return layer_result
        kicad_layer = {}
        kicad_layer["Top Silk"] = self.board.GetLayerName(37)
        kicad_layer["Top Solder"] = self.board.GetLayerName(39)
        kicad_layer["Top Layer"] = self.board.GetLayerName(0)
        kicad_layer["Bot Silk"] = self.board.GetLayerName(36)
        kicad_layer["Bot Solder"] = self.board.GetLayerName(38)
        kicad_layer["Bot Layer"] = self.board.GetLayerName(31)
        kicad_layer["Outline"] = self.board.GetLayerName(44)
        kicad_layer["Top Paste"] = self.board.GetLayerName(35)
        kicad_layer["Bot Paste"] = self.board.GetLayerName(34)
        for i in range(2, 32):
            kicad_layer[f"Inner{i}"] = self.board.GetLayerName(i - 1)

        if isinstance(layer_result, str):  # 如果 layer_result 是字符串
            if layer_result in kicad_layer.keys():
                layer_result = kicad_layer[layer_result]
        elif isinstance(layer_result, list):  # 如果 layer_result 是列表
            for i, layer in enumerate(layer_result):
                if layer in kicad_layer.keys():
                    layer_result[i] = kicad_layer[layer]
        return layer_result

    def GetImagePath(self, bitmap_path):
        return GetImagePath(bitmap_path)
