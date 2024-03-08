import os
import wx
import re
from decimal import Decimal
import pcbnew
from . import config
from .picture import GetImagePath
from kicad_dfm.child_frame.ui_child_frame import UiChildFrame
from kicad_dfm.settings.graphics_setting import GRAPHICS_SETTING
from kicad_dfm.child_frame.child_frame_model import ChildFrameModel


class DfmChildFrame(UiChildFrame):
    def __init__(
        self,
        parent,
        title,
        result_json,
        json_string,
        check,
        line_list,
        _board,
        kicad=False,
    ):
        self.temp_layer = {""}
        self.line_list = line_list
        self.board = _board
        self.unit = pcbnew.GetUserUnits()
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

        self.languages = self.get_layer()
        self.analysis_type_data = self.get_type()
        self.analysis_result_data = self.get_result()
        self.lst_analysis_type.Set(self.analysis_type_data)
        self.lst_analysis_result.Set(self.analysis_result_data)
        self.lst.Set(self.languages)

        self.lst.Bind(wx.EVT_LISTBOX, self.set_result)
        self.lst_analysis_type.Bind(wx.EVT_LISTBOX, self.analysis_type)
        self.lst_analysis_result.Bind(wx.EVT_LISTBOX, self.analysis_result)
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
        if len(self.languages) == 0:
            return
        self.lst_analysis_result.Select(0)
        self.select_number = 0
        string_data = self.lst_analysis_result.GetString(
            self.lst_analysis_result.GetSelection()
        )
        self.analysis_process(string_data)

    def select_back(self, event):
        if len(self.languages) == 0:
            return
        self.select_number -= 1
        if self.select_number < 0:
            self.select_number = 0
        self.lst_analysis_result.SetSelection(self.select_number)
        self.analysis_result
        string_data = self.lst_analysis_result.GetString(
            self.lst_analysis_result.GetSelection()
        )
        self.analysis_process(string_data)

    def select_next(self, event):
        if len(self.languages) == 0:
            return
        self.select_number += 1
        if self.select_number > self.lst_analysis_result.GetCount() - 1:
            self.select_number = self.lst_analysis_result.GetCount() - 1
        self.lst_analysis_result.SetSelection(self.select_number)
        string_data = self.lst_analysis_result.GetString(
            self.lst_analysis_result.GetSelection()
        )
        self.analysis_process(string_data)

    def select_last(self, event):
        if len(self.languages) == 0:
            return
        self.select_number = self.lst_analysis_result.GetCount() - 1
        self.lst_analysis_result.SetSelection(self.select_number)
        string_data = self.lst_analysis_result.GetString(
            self.lst_analysis_result.GetSelection()
        )
        self.analysis_process(string_data)

    def picture_path(self, string, language_string):
        json_string = string.lower()
        if json_string == "acute angle traces" or json_string == "锐角":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("acute_angle" + language_string))
            )
        elif json_string == "unconnected traces" or json_string == "断头线":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("breakage_line" + language_string))
            )
        elif json_string == "floating copper" or json_string == "孤立铜":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("isolated_copper" + language_string))
            )
        elif json_string == "unconnected vias" or json_string == "无效过孔":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("invalid_via" + language_string))
            )
        elif json_string == "smallest trace width" or json_string == "最小线宽":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("line_width" + language_string))
            )
        elif json_string == "trace spacing" or json_string == "线到线":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("line2line" + language_string))
            )
        elif json_string == "trace-to-pad spacing" or json_string == "焊盘到线":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("pad2line" + language_string))
            )
        elif json_string == "pad spacing" or json_string == "焊盘间距":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("pad2pad" + language_string))
            )
        elif (
            json_string == "bga pads"
            or json_string == "short pads"
            or json_string == "long pads"
            or json_string == "bga焊盘"
            or json_string == "长条焊盘"
            or json_string == "常规焊盘"
        ):
            self.bmp.SetBitmap(wx.Bitmap(self.GetImagePath("bga" + language_string)))
        elif (
            json_string == "smd pad spacing"
            or json_string == "pad spacing"
            or json_string == "smd焊盘间距"
            or json_string == "焊盘间距"
        ):
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("pad_spacing_base" + language_string))
            )
        elif json_string == "grid width" or json_string == "网格线宽":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("grid_width" + language_string))
            )
        elif json_string == "grid spacing" or json_string == "网格间距":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("grid_spacing" + language_string))
            )
        elif json_string == "smallest drill size" or json_string == "最小孔径":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("min_diameter" + language_string))
            )
        elif json_string == "aspect ratio" or json_string == "孔后径比":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("min_thick_diameter" + language_string))
            )
        elif json_string == "smallest slot width" or json_string == "最小槽宽":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("min_slot" + language_string))
            )
        elif json_string == "largest drill size" or json_string == "最大孔径":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("max_diameter" + language_string))
            )
        elif json_string == "largest slot width" or json_string == "最大槽宽":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("max_slot" + language_string))
            )
        elif json_string == "largest slot length" or json_string == "最大槽长":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("max_slot_length" + language_string))
            )
        elif json_string == "slot aspect ratio" or json_string == "槽长宽比":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("slot_length_width" + language_string))
            )
        elif json_string == "largest blind/buried via" or json_string == "最大盲埋孔":
            self.bmp.SetBitmap(
                wx.Bitmap(
                    self.GetImagePath("max_diameter_blind_buried" + language_string)
                )
            )
        elif (
            json_string == "via annular ring"
            or json_string == "pth annular ring"
            or json_string == "via孔环"
            or json_string == "pth孔环"
        ):
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("via_ring" + language_string))
            )
        elif (
            json_string == "pth-to-trace (outer)"
            or json_string == "pth-to-trace (inner)"
            or json_string == "via-to-trace (outer)"
            or json_string == "via-to-trace (inner)"
            or json_string == "插件孔到表层"
            or json_string == "插件孔到内层"
            or json_string == "过孔到表层"
            or json_string == "过孔到内层"
        ):
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("line2pth_outer" + language_string))
            )
        elif json_string == "npth-to-copper" or json_string == "npth铜":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("npth2copper" + language_string))
            )
        elif json_string == "smd-to-board edge" or json_string == "smd到板边":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("smd2edge" + language_string))
            )
        elif json_string == "copper-to-board edge" or json_string == "铜到板边":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("copper2edge" + language_string))
            )
        elif json_string == "square/rectangular drills" or json_string == "正长方形孔":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("hole_spuared" + language_string))
            )
        elif json_string == "castellated holes" or json_string == "半孔":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("hole_half" + language_string))
            )
        elif json_string == "via-in-pad" or json_string == "盘中孔":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("resin_hole_plugging" + language_string))
            )
        elif json_string == "pth on smd pad" or json_string == "插件孔上焊盘":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("pth_insmd" + language_string))
            )
        elif json_string.lower() == "via on smd pad".lower() or json_string == "过孔上焊盘":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("via_insmd" + language_string))
            )
        elif json_string == "npth on smd pad" or json_string == "npth孔上焊盘":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("npth_insmd" + language_string))
            )
        elif json_string == "missing smask opening" or json_string == "阻焊少开窗":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("soldmask_lack" + language_string))
            )
        elif json_string == "same net via spacing" or json_string == "通网络过孔":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("via_same net" + language_string))
            )
        elif json_string == "different net via spacing" or json_string == "不同网络过孔":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("via_difference_net" + language_string))
            )
        elif json_string == "different net pth spacing" or json_string == "不同网络插件孔":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("pth_difference_net" + language_string))
            )
        elif json_string == "blind/buried via spacing" or json_string == "盲埋孔距离":
            self.bmp.SetBitmap(
                wx.Bitmap(self.GetImagePath("blind2blind" + language_string))
            )

    def dispose_result(self):
        if self.combo_box.GetStringSelection() == "!!":
            if self.json_string not in self.delete_value.keys():
                for result_list in self.result_json[self.json_string]["check"]:
                    for result in result_list["result"]:
                        if result["color"] == "red":
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

    def read_json(self, event):
        self.combo = self.combo_box.GetSelection()
        self.lst.Set(self.languages)
        self.dispose_result()
        self.get_layer()
        self.get_type()
        self.get_result()
        self.set_layer()
        self.set_color_rule()

    def set_result(self, event):
        self.set_layer()
        self.set_color_rule()
        self.lst.Refresh()
        self.lst.Update()

    def set_layer(self):
        if len(self.languages) == 0:
            self.layer_name.append("")
            return
        self.layer_name = []
        self.analysis_type_data = []
        if self.lst.GetSelections() != wx.NOT_FOUND:
            list_data = self.lst.GetSelections()
        for data in list_data:
            self.layer_name.append(self.lst.GetString(data))
        if len(list_data) == 0:
            for i in range(self.lst.GetCount()):
                self.lst.SetSelection(i)
                self.layer_name.append(self.lst.GetString(i))

        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                result_layer = self.layer_conversion(result["layer"])
                if (
                    result["item"] not in self.analysis_type_data
                    and result_layer[0] in self.layer_name
                ):
                    self.analysis_type_data.append(result["item"])
        self.lst_analysis_type.Set(self.analysis_type_data)

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
        if len(list_string) == 0 and len(self.languages) != 0:
            if self.lst_analysis_type.GetCount() > 0:
                list_string.append(self.lst_analysis_type.GetString(0))
            else:
                return
            self.lst_analysis_type.SetSelection(0)
            self.picture_path(list_string[0], self.message_type["picture_path"])

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
                # elif self.unit == 1:
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
                    self.lst_analysis_result.SetItemForegroundColour(temp_num, wx.RED)
                elif self.result[result_flag]["color"] == "orange":
                    self.lst_analysis_result.SetItemForegroundColour(
                        temp_num, wx.YELLOW
                    )
                elif self.result[result_flag]["color"] == "black":
                    self.lst_analysis_result.SetItemForegroundColour(temp_num, wx.BLACK)
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
                            elif self.unit == 1:
                                result_flag_list[str(num)] = result["value"] + "mm"
                        self.result[str(num)] = result_list
                        break
            for flag in result_flag_list:
                string = flag + "、 " + result_flag_list.get(flag)
                self.analysis_result_data.append(string)
        self.lst_analysis_result.Set(self.analysis_result_data)

    def Millimeter2iu(self, millimeter_value):
        return round(millimeter_value / 25.4, 3)

    def Millimeter2mils(self, millimeter_value):
        return round((millimeter_value * 39.37), 3)

    def analysis_result(self):
        if self.lst_analysis_result.GetSelection() != wx.NOT_FOUND:
            string_data = self.lst_analysis_result.GetString(
                self.lst_analysis_result.GetSelection()
            )
        self.select_number = self.lst_analysis_result.GetSelection()
        self.analysis_process(string_data)

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
                            line.SetLayer(pcbnew.Dwgs_User)
                            line.SetWidth(250000)
                            if result["type"] == 0:
                                if result["et"] == 0:
                                    # GRAPHICS_SETTING
                                    line = self.set_segment(line, result, x, y)
                                elif result["et"] == 1:
                                    line = self.set_arc(line, result, x, y)
                                else:
                                    line = self.set_rect(line, result, x, y)
                            elif result["type"] == 2:
                                line = self.set_segment(line, result, x, y)
                            else:
                                line = self.set_rect_list(line, result, x, y)
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
                            line.SetBrightened()
                            if count == len(self.line_list):
                                pcbnew.FocusOnItem(line, pcbnew.Dwgs_User)
        self.close_unshow_layer(layer_num)

        # 关闭不需要显示的层

    def close_unshow_layer(self, layer_num):
        if self.check_box.GetValue() is False:
            gal_set = self.board.GetVisibleLayers()
            for num in [x for x in gal_set.Seq()]:
                if num in layer_num:
                    continue
                gal_set.removeLayer(num)
            self.board.SetVisibleLayers(gal_set)
            pcbnew.UpdateUserInterface()
        pcbnew.Refresh()

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

    def get_type(self):
        analysis_type = []
        if self.result_json[self.json_string] == "":
            return analysis_type
        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                if result["item"] not in analysis_type:
                    analysis_type.append(result["item"])
        return analysis_type

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

        for k, v in enumerate(layer_result):
            layer = v
            if layer in kicad_layer.keys():
                layer = layer.replace(layer, kicad_layer[layer])
            layer_result[k] = layer

        return layer_result

    def GetImagePath(self, bitmap_path):
        return GetImagePath(bitmap_path)

    def set_segment(self, line, result, x, y):
        line.SetShape(pcbnew.S_SEGMENT)
        line.SetEndX(int(Decimal(result["ex"]) * 1000000) + x)
        line.SetEndY(y - int(Decimal(result["ey"]) * 1000000))
        line.SetStartX(int(Decimal(result["sx"]) * 1000000) + x)
        line.SetStartY(y - int(Decimal(result["sy"]) * 1000000))
        return line

    def set_arc(self, line, result, x, y):
        line.SetShape(pcbnew.S_ARC)
        line.SetEndX(int(Decimal(result["ex"]) * 1000000) + x)
        line.SetEndY(y - int(Decimal(result["ey"]) * 1000000))
        line.SetStartX(int(Decimal(result["sx"]) * 1000000) + x)
        line.SetStartY(y - int(Decimal(result["sy"]) * 1000000))
        line.SetCenter(
            int(Decimal(result["cx"]) * 1000000) + x,
            y - int(Decimal(result["cy"]) * 1000000),
        )
        return line

    def set_rect(self, line, result, x, y):
        line.SetShape(pcbnew.S_RECT)
        line.SetStartX(int(Decimal(result["cx"]) * 1000000) - 250000 + x)
        line.SetStartY(y - int(Decimal(result["cy"]) * 1000000) - 250000)
        line.SetEndX(int(Decimal(result["cx"]) * 1000000) + 250000 + x)
        line.SetEndY(y - int(Decimal(result["cy"]) * 1000000) + 250000)
        return line

    def set_rect_list(self, line, result, x, y):
        line.SetShape(pcbnew.S_RECT)
        line.SetStartX(int(Decimal(result["result"][0]) * 1000000) + x)
        line.SetStartY(y - int(Decimal(result["result"][3]) * 1000000))
        line.SetEndX(int(Decimal(result["result"][1]) * 1000000) + x)
        line.SetEndY(y - int(Decimal(result["result"][2]) * 1000000))
        return line
