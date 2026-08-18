import wx
import re
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
from kicad_dfm.child_frame.diagram_hint import diagram_bitmap_for
from kicad_dfm.child_frame.rule_guidance import current_rule_guidance
from kicad_dfm.child_frame.rule_guidance import current_rule_text
from kicad_dfm.settings.kicad_setting import KiCadSetting
from .dfm_child_frame_model import DfmChildFrameModel
import logging
from kicad_dfm.services.locate import LocateService
from kicad_dfm.services.locate import LocatePlan
from kicad_dfm.services.locate import ResultLocationPlanner
from kicad_dfm.core.i18n import _
from kicad_dfm.core.rule_catalog import RULE_CATALOG
from kicad_dfm.core.rule_catalog import normalize_name
from kicad_dfm.core.rule_contract import rule_key as build_rule_key

MAX_LOCATE_ITEMS = 200
MAX_LOCATE_MARKERS = 20
RULE_DIAGRAM_MAX_SIZE = (360, 190)
LOGGER = logging.getLogger(__name__)


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
        if KiCadSetting.read_lang_setting() == "English":
            self.message_type = config.Language_english
        else:
            self.message_type = config.Language_chinese
        self.kicad = kicad
        self.combo = 1
        self.graphics_setting = GraphicsSetting(self.board)
        self.child_frame_setting = ChildFrameSetting(self.board)

        self.SetTitle(title)
        self._locate_status = ""
        self.CreateStatusBar()
        self.set_locate_status("")
        self.result = {}
        self.result_row_keys = []
        self.layer_name = []
        self.item_list = []
        self.locate_service = LocateService(self.board, self.line_list, self.item_list)
        self.delete_value = {}
        self.select_number = -1
        # self.combo_box.SetSelection(0)

        self.analysis_result_data = self.get_result()
        self.lst_analysis_result1.AppendTextColumn(
            _("#"),
            width=48,
            mode=dv.DATAVIEW_CELL_INERT,
            align=wx.ALIGN_LEFT,
        )
        self.lst_analysis_result1.AppendTextColumn(
            _("Severity"),
            width=90,
            mode=dv.DATAVIEW_CELL_INERT,
            align=wx.ALIGN_LEFT,
        )
        self.lst_analysis_result1.AppendTextColumn(
            _("Value"),
            width=180,
            mode=dv.DATAVIEW_CELL_INERT,
            align=wx.ALIGN_LEFT,
        )
        self.lst_analysis_result1.AppendTextColumn(
            _("Layer"),
            width=140,
            mode=dv.DATAVIEW_CELL_INERT,
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
        if self.should_show_all_by_default():
            self.combo_box.SetSelection(0)
        self.dispose_result()
        self.set_layer()
        self.set_color_rule()

        self.Update()
        self.Centre()
        self.Show(True)

    def remove_added_line(self, event):
        self.locate_service.clear()
        # pcbnew.UpdateUserInterface
        event.Skip()

    def should_show_all_by_default(self):
        result = self.result_json.get(self.json_string) if isinstance(self.result_json, dict) else None
        if not isinstance(result, dict):
            return False
        display = str(result.get("display") or "").lower()
        if display in ("", "normal", "正常"):
            return False
        checks = result.get("check") or []
        for check in checks:
            for item in check.get("result") or []:
                if item.get("color") in ("red", "gold"):
                    return False
        return True

    # 关闭窗口时清空在kicad上的处理
    def on_close(self, event):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        try:
            self.locate_service.clear()
        except Exception:
            # The owner may already have removed temporary board shapes while
            # shutting down.  Cleanup failure must never leave an orphaned,
            # uncloseable top-level window behind.
            LOGGER.debug("detail window cleanup failed during close", exc_info=True)
        finally:
            self.Destroy()

    def select_first(self, event):
        if len(self.get_layer) == 0:
            return
        self.lst_analysis_result1.SelectRow(0)
        self.select_number = 0
        string_data = self.lst_analysis_result1.GetTextValue(
            self.lst_analysis_result1.GetSelectedRow(), 0
        )
        self.analysis_process(self.result_key_for_row(0, string_data), event)
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
        self.analysis_process(self.result_key_for_row(self.select_number, string_data), event)
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
        self.analysis_process(self.result_key_for_row(self.select_number, string_data), event)
        event.Skip()

    def select_last(self, event):
        if len(self.get_layer) == 0:
            return
        self.select_number = self.lst_analysis_result1.GetItemCount() - 1
        self.lst_analysis_result1.SelectRow(self.select_number)
        string_data = self.lst_analysis_result1.GetTextValue(self.select_number, 0)
        self.analysis_process(self.result_key_for_row(self.select_number, string_data), event)
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
                    if result_list.get("result") and result_list["result"][0]["color"] == "black":
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
        counts = self.analysis_type_counts(selected_layers)
        self.lst_analysis_type.Set(
            [self.analysis_type_label(item, counts[item]) for item in sorted(counts)]
        )

    def set_color_rule(self):
        if self.result_json[self.json_string] == "":
            return
        results_list = []
        self.result_row_keys = []
        self.result = {}  # 展示的结果集
        if self.lst_analysis_type.GetSelections() != wx.NOT_FOUND:
            list_data = self.lst_analysis_type.GetSelections()
        num = 0
        list_string = []
        for data in list_data:
            list_string.append(
                self.analysis_type_key(self.lst_analysis_type.GetString(data))
            )
        if len(list_string) == 0 and self.lst_analysis_type.GetCount() != 0:
            list_string.append(
                self.analysis_type_key(self.lst_analysis_type.GetString(0))
            )
            self.lst_analysis_type.SetSelection(0)

        # Refresh all rule context for automatic and explicit selections.
        if list_string:
            self.update_rule_diagram(list_string[0])
            self.update_rule_content(list_string[0])

        for result_list in self.result_json[self.json_string]["check"]:
            for result in result_list["result"]:
                result_layer = self.child_frame_setting.layer_conversion(
                    self.json_string, result["layer"]
                )
                if (
                    any(
                        self.result_matches_rule_item(result, item)
                        for item in list_string
                    )
                    and result_layer[0] in self.layer_name
                ):
                    num += 1
                    self.result[str(num)] = {"result": [result]}
                    self.append_result_row(results_list, num, result)

        self.dfm_child_frame_model.Update(results_list)

    def update_rule_diagram(self, item):
        bitmap = diagram_bitmap_for(item, max_size=RULE_DIAGRAM_MAX_SIZE)
        if bitmap is None:
            bitmap = wx.Bitmap(GetImagePath("none.png"))
        self.bmp.SetBitmap(bitmap)
        self.Layout()

    def update_rule_content(self, item):
        result = self.rule_result_for_item(item)
        label = current_rule_text(self.json_string, result, self.unit)
        guidance = current_rule_guidance(self.json_string, result, self.unit)
        rule_label = getattr(self, "rule_value_label", None)
        if rule_label is not None:
            rule_label.SetLabel(label)
            rule_label.SetToolTip(label)
            rule_label.Wrap(max(rule_label.GetParent().GetClientSize().width - 10, 120))
        description = getattr(self, "rule_description_text", None)
        if description is not None:
            description.SetValue(guidance)
            description.SetInsertionPoint(0)
        self.Layout()

    def rule_result_for_item(self, item):
        result_data = self.result_json.get(self.json_string, {})
        if not isinstance(result_data, dict):
            return {"item": item}
        for result_list in result_data.get("check") or ():
            for result in result_list.get("result") or ():
                if self.result_matches_rule_item(result, item):
                    return result
        for summary_item, summary in self.executed_item_summaries():
            if summary_item == item:
                return summary
        return {"item": item}

    def append_result_row(self, rows, key, result):
        rows.append(
            [
                str(key),
                self.result_severity(result),
                self.format_result_value(result),
                self.format_result_layer(result),
                result.get("color", "black"),
            ]
        )
        self.result_row_keys.append(str(key))

    def format_result_value(self, result):
        value = result.get("value", "")
        if result.get("value_kind") == "boolean":
            return "—"
        if self.result_matches_rule_item(result, "Aspect Ratio"):
            try:
                ratio = float(value)
                raw = result.get("raw") or {}
                thickness = float(
                    result.get("board_thickness_mm")
                    or raw.get("board_thickness_mm")
                    or self.board.GetDesignSettings().GetBoardThickness() / 1000000
                )
                diameter = float(
                    result.get("diameter")
                    or raw.get("diameter")
                    or thickness / ratio
                )
                return f"{ratio:.2f} ({thickness:.2f}/{diameter:.2f})"
            except (TypeError, ValueError, ZeroDivisionError):
                return str(value)
        if self.result_matches_rule_item(result, "Slot Aspect Ratio"):
            try:
                return str(round(float(value), 3))
            except (TypeError, ValueError):
                return str(value)
        try:
            millimeter_value = float(value)
        except (TypeError, ValueError):
            return str(value)
        if self.unit == 0:
            return str(CHILDFRAME_UNIT_CONVERSION.Millimeter2iu(millimeter_value)) + "inch"
        if self.unit == 5:
            return str(CHILDFRAME_UNIT_CONVERSION.Millimeter2mils(millimeter_value)) + "mil"
        return str(round(millimeter_value, 3)) + "mm"

    def result_matches_rule_item(self, result, item):
        """Match a result item by its stable rule identity, independent of UI language."""
        actual_key = str(result.get("rule_key") or "")
        if actual_key:
            return actual_key == build_rule_key(self.json_string, item)
        actual_item = str(result.get("item") or "")
        candidates = {str(item), str(_(item))}
        for mapping in (config.Language_chinese, config.Language_english):
            candidates.add(str(mapping.get(item, "")))
            candidates.add(str(mapping.get(str(item).lower(), "")))
        candidates.discard("")
        return actual_item in candidates

    def format_result_layer(self, result):
        layer = result.get("layer") or ()
        if isinstance(layer, str):
            return layer
        return ", ".join(str(item) for item in layer)

    def data_view_binding(self):
        self.dfm_child_frame_model = DfmChildFrameModel(self.analysis_result_data)
        self.lst_analysis_result1.AssociateModel(self.dfm_child_frame_model)
        wx.CallAfter(self.lst_analysis_result1.Refresh)

    def on_analysis_result(self, event):
        selection = self.lst_analysis_result1.GetSelectedRow()
        if selection < 0:
            event.Skip()
            return
        item_data = self.lst_analysis_result1.GetTextValue(selection, 0)
        # Assuming item_data is the data associated with the selected row
        # Start the analysis process synchronously
        self.analysis_process(self.result_key_for_row(selection, item_data), event)
        event.Skip()

    def result_key_for_row(self, row, fallback_text):
        parsed_key = self.result_key_from_text(fallback_text)
        if parsed_key is not None:
            return parsed_key
        try:
            return self.result_row_keys[row]
        except (IndexError, TypeError):
            return fallback_text

    def result_key_from_text(self, text):
        try:
            match = re.search(r"^(\d+)$|(\d+(?=(\、)))", text)
        except TypeError:
            return None
        if match:
            return match.group(1) or match.group(2)
        return None

    # 通过选中行的string去查找到对应的item
    def analysis_process(self, string_data, event):
        self.set_locate_status(_("Locating..."))
        settings = self.board.GetDesignSettings()
        x = settings.GetAuxOrigin().x
        y = settings.GetAuxOrigin().y
        locate_started = False
        try:
            search = self.result_key_from_text(string_data)
            if search is None:
                return
            if search not in self.result:
                self.set_locate_status(_("No selected result."))
                return
            result_group = self.result[search]
            selected_results = result_group.get("result", []) if isinstance(result_group, dict) else result_group
            if self.is_file_based_result_group(selected_results) and not self.has_drawable_location_result(selected_results):
                self.locate_service.clear()
                self.set_locate_status(_("Gerber/Drill file result has no PCB object location."))
                return
            if self.has_no_location_result(selected_results):
                self.locate_service.clear()
                wx.MessageBox(
                    _("This issue has no location data from the DFM service."),
                    _("Info"),
                    style=wx.ICON_INFORMATION,
                )
                return
            layer_num = []
            self.locate_service.begin(defer_focus=True)
            locate_started = True
            # 结果表每一行对应一条结果，选择时只定位当前行。
            if self.is_file_based_result_group(selected_results):
                if self.draw_file_based_results(selected_results, x, y, layer_num):
                    pass
                else:
                    self.set_locate_status(_("Gerber/Drill file result has no PCB object location."))
                    return
            elif self.json_string in [
                "Pad size",
                "Smallest Trace Width",
                "RingHole",
            ]:
                result = selected_results[0]
                for layer in result["layer"]:
                    layer_num.append(self.board.GetLayerID(layer))
                plan = ResultLocationPlanner(self.locate_service.backend).plan_native_items(result)
                self.locate_service.apply_plan(plan)
                if not plan.items and not plan.bboxes_nm:
                    self.draw_result_location(result, x, y, layer_num)

            elif self.json_string in ["Signal Integrity", "Hole Size"]:
                items = []
                for result in selected_results:
                    item = self.signal_result_item(result, x, y)
                    if item is not None:
                        items.append(item)
                for layer in result["layer"]:
                    layer_num.append(self.board.GetLayerID(layer))
                if items:
                    self.locate_service.apply_plan(LocatePlan(items=items))
                else:
                    for result in selected_results:
                        self.draw_result_location(result, x, y, layer_num)

            elif self.json_string in [
                "Holes on SMD Pads",
                "Special Drill Holes",
            ]:
                planner = ResultLocationPlanner(self.locate_service.backend)
                plan = planner.plan_item_or_drawable_results(
                    selected_results,
                    resolve_items=lambda result: self.smd_pad_location_items(result, x, y),
                    create_shape=self.locate_service.create_warning_shape,
                    draw_shape=lambda line, result: self.draw_result_shape(line, result, x, y),
                    result_layer=self.first_result_layer,
                )
                layer_num.extend(plan.layers)
                self.locate_service.apply_plan(plan)
                if plan.items:
                    self.set_bulk_locate_status(len(plan.items))

            elif self.json_string in [
                "Drill to Copper",
                "Smallest Trace Spacing",
                "SMD Spacing",
            ]:
                planner = ResultLocationPlanner(self.locate_service.backend)
                plan = planner.plan_item_or_drawable_results(
                    selected_results,
                    resolve_items=self.location_items_for_result,
                    create_shape=self.locate_service.create_warning_shape,
                    draw_shape=lambda line, result: self.spacing_result_shape(line, result, x, y),
                    result_layer=self.first_result_layer,
                )
                layer_num.extend(plan.layers)
                self.locate_service.apply_plan(plan)
                if plan.items:
                    self.set_bulk_locate_status(len(plan.items))

            elif self.json_string in (
                "Copper-to-Board Edge",
                "Hole-to-Board Edge",
            ):
                planner = ResultLocationPlanner(self.locate_service.backend)
                plan = planner.plan_item_or_drawable_results(
                    selected_results,
                    resolve_items=self.location_items_for_result,
                    create_shape=self.locate_service.create_warning_shape,
                    draw_shape=lambda line, result: self.board_edge_result_shape(line, result, x, y),
                    result_layer=self.first_result_layer,
                )
                layer_num.extend(plan.layers)
                self.locate_service.apply_plan(plan)

            elif self.json_string in [
                "Smallest Trace Spacing",
                "Drill Hole Spacing",
                "Solder Mask Analysis",
            ]:
                planner = ResultLocationPlanner(self.locate_service.backend)
                plan = planner.plan_item_or_drawable_results(
                    selected_results,
                    resolve_items=self.location_items_for_result,
                    create_shape=self.locate_service.create_warning_shape,
                    draw_shape=lambda line, result: self.spacing_result_shape(line, result, x, y),
                    result_layer=self.first_result_layer,
                )
                layer_num.extend(plan.layers)
                self.locate_service.apply_plan(plan)
                if plan.items:
                    self.set_bulk_locate_status(len(plan.items))

            # dfm analysis item
            else:
                for result in selected_results:
                    self.draw_result_location(result, x, y, layer_num)
                    # show layers
                    for layer in result["layer"]:
                        if self.board.GetLayerID(layer) > -1:
                            layer_num.append(self.board.GetLayerID(layer))
                        else:
                            layer_num.append(pcbnew.B_Adhes)

            # close needn't layers
            if self.check_box.GetValue() is False and self.should_hide_unrelated_layers(layer_num, selected_results):
                self.locate_service.hide_unrelated_layers(layer_num)
        finally:
            if locate_started:
                self.locate_service.flush_focus()
                if LOGGER.isEnabledFor(logging.DEBUG):
                    LOGGER.debug("locate_result key=%s profile=%s", self.json_string, self.locate_service.profile)
                wx.CallAfter(pcbnew.Refresh)
                if self._locate_status == _("Locating..."):
                    self.set_locate_status(_("Location updated."))
            if event is not None and hasattr(event, "Skip"):
                event.Skip()

    def draw_result_location(self, result, x, y, layer_num):
        planner = ResultLocationPlanner(self.locate_service.backend)
        plan = planner.plan_drawable_result(
            result,
            create_shape=self.locate_service.create_warning_shape,
            draw_shape=lambda line, item: self.draw_result_shape(line, item, x, y),
            result_layer=self.first_result_layer,
        )
        layer_num.extend(plan.layers)
        self.locate_service.apply_plan(plan)
        return bool(plan.temporary_shapes or plan.bboxes_nm)

    def draw_result_shape(self, line, result, x, y):
        if result.get("type") == 0:
            if result.get("et") == 0:
                return self.graphics_setting.set_segment(line, result, x, y)
            if result.get("et") == 1:
                return self.graphics_setting.set_arc(line, result, x, y)
            return self.graphics_setting.set_rect(line, result, x, y)
        if result.get("type") == 2:
            return self.graphics_setting.set_segment(line, result, x, y)
        if "result" in result:
            return self.graphics_setting.set_rect_list(line, result, x, y)
        return None

    def spacing_result_shape(self, line, result, x, y):
        if result.get("item") in {
            _("Pad-to-Pad Spacing"),
            _("BGA Pads"),
            _("SMD Pad Spacing"),
            _("Pad Spacing"),  # legacy cached/remote result
        }:
            items = self.graphics_setting.get_pad_spacing_judge_segment(result, x, y)
        else:
            items = self.graphics_setting.get_spacing_judge_segment(result, x, y)
        return items[0] if items else None

    def board_edge_result_shape(self, line, result, x, y):
        return self.graphics_setting.set_segment(line, result, x, y)

    def signal_result_item(self, result, x, y):
        if result["type"] != 0:
            return None
        if result["et"] == 0:
            if self.json_string == "Signal Integrity":
                return self.graphics_setting.get_signal_integrity_segment(result, x, y)
            return self.graphics_setting.get_hole_diameter_segment(result, x, y)
        if result["et"] == 1:
            return self.graphics_setting.get_signal_integrity_arc(result, x, y)
        if result["et"] == 3:
            return self.graphics_setting.get_signal_integrity_floating_copper(result, x, y)
        return self.graphics_setting.get_signal_integrity_rect(result, x, y)

    def smd_pad_location_items(self, result, x, y):
        items = self.location_items_for_result(result)
        if items or not result.get("result"):
            return items
        item = self.graphics_setting.get_SMD_pads_rect_list(result, x, y)
        return [item] if item is not None else []

    def first_result_layer(self, result):
        for layer in result.get("layer") or ():
            layer_id = self.board.GetLayerID(layer)
            if layer_id > -1:
                return layer_id
        return pcbnew.Dwgs_User

    def has_no_location_result(self, results):
        return bool(results) and all(result.get("type") == 9 for result in results)

    def should_hide_unrelated_layers(self, layer_nums, results):
        if not layer_nums:
            return False
        return any(isinstance(layer, int) and layer >= 0 for layer in layer_nums)

    def is_file_based_result_group(self, results):
        return bool(results) and all(result.get("item_type") in ("gerber", "drill") for result in results)

    def has_drawable_location_result(self, results):
        return any(self.is_drawable_location_result(result) for result in results or ())

    def is_drawable_location_result(self, result):
        return result.get("type") in (0, 2) and all(key in result for key in ("sx", "sy", "ex", "ey"))

    def draw_file_based_results(self, results, x, y, layer_num):
        planner = ResultLocationPlanner(self.locate_service.backend)
        drawables = []
        resolved_items = []
        seen_items = set()
        for result in results or ():
            primary_item = self.resolve_location_item(result.get("id"))
            related_item = self.resolve_location_item(result.get("related_id"))
            items = [item for item in (primary_item, related_item) if item is not None]
            drawables.extend(
                self.file_result_drawables(
                    result,
                    primary_resolved=primary_item is not None,
                    related_resolved=related_item is not None,
                )
            )
            for item in items:
                identity = id(item)
                if identity not in seen_items:
                    seen_items.add(identity)
                    resolved_items.append(item)
        plan = planner.plan_file_results(
            drawables,
            create_shape=self.locate_service.create_warning_shape,
            set_segment=lambda line, result: self.graphics_setting.set_segment(line, result, x, y),
            result_width=self.file_result_width_nm,
            result_layer=self.file_result_layer,
            is_drawable=self.is_drawable_location_result,
        )
        plan.items.extend(resolved_items)
        layer_num.extend(plan.layers)
        for result in results or ():
            for layer in self.file_result_layers(result):
                layer_id = self.board.GetLayerID(layer)
                if layer_id > -1 and layer_id not in layer_num:
                    layer_num.append(layer_id)
        self.locate_service.apply_plan(plan)
        if plan.status:
            self.set_locate_status(_(plan.status))
        return bool(plan.items or plan.temporary_shapes)

    def resolve_location_item(self, item_id):
        resolver = getattr(self.locate_service.backend, "resolve_item", None)
        return resolver(item_id) if resolver is not None and item_id else None

    def file_result_drawables(self, result, primary_resolved=False, related_resolved=False):
        """Draw only unresolved physical segments; never draw a zone centreline."""
        drawables = []
        raw = result.get("raw") or {}
        primary = raw.get("primary")
        related = raw.get("related") or raw.get("related_raw")
        for mapping, resolved in ((primary, primary_resolved), (related, related_resolved)):
            if resolved or not isinstance(mapping, dict):
                continue
            if mapping.get("kind") == "region" and "pad" not in str(mapping.get("aperture_function") or "").lower():
                continue
            segment = mapping.get("segment")
            if not segment or len(segment) != 2:
                continue
            drawable = dict(result)
            drawable["raw"] = mapping
            drawable["layer"] = mapping.get("layer") or result.get("layer")
            drawable.update(self.segment_location_fields(segment))
            drawables.append(drawable)
        # Flashed pads/regions have no centreline in their nested mapping.  If
        # neither side maps to a native object, draw the top-level measured-gap
        # segment so every Gerber spacing result still has a visible location.
        if not drawables and not primary_resolved and not related_resolved:
            drawables.append(result)
        return drawables

    @staticmethod
    def segment_location_fields(segment):
        start, end = segment
        return {
            "type": 0,
            "et": 0,
            "sx": "{0:.6f}".format(start[0]),
            "sy": "{0:.6f}".format(start[1]),
            "ex": "{0:.6f}".format(end[0]),
            "ey": "{0:.6f}".format(end[1]),
        }

    def file_result_layers(self, result):
        """Return PCB layers referenced by a Gerber/Excellon result and its pair."""
        layers = []

        def append(value):
            if isinstance(value, str):
                value = (value,)
            for layer in value or ():
                if layer and layer not in layers:
                    layers.append(layer)

        append(result.get("layer"))
        raw = result.get("raw") or {}
        for key in ("primary", "related", "related_raw"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                append(nested.get("layer"))
        append(raw.get("related_layer"))
        append(result.get("related_layer"))
        return layers

    def file_result_width_nm(self, result):
        raw = result.get("raw") or {}
        width = raw.get("width") or raw.get("diameter")
        try:
            return max(int(float(width) * 1000000), 150000) if width else 300000
        except (TypeError, ValueError):
            return 300000

    def file_result_layer(self, result):
        for layer in result.get("layer") or ():
            layer_id = self.board.GetLayerID(layer)
            if layer_id > -1:
                return layer_id
        return pcbnew.Dwgs_User

    def location_items_for_result(self, result):
        items = []
        resolver = getattr(self.locate_service.backend, "resolve_item", None)
        if resolver is None:
            return items
        for key in ("id", "related_id"):
            item_id = result.get(key)
            item = resolver(item_id) if item_id else None
            if item is not None:
                items.append(item)
        return items

    def set_items_Brightened(self, items):
        self.set_bulk_locate_status(len(items))
        limited_items = items[:MAX_LOCATE_ITEMS]
        if any(not item for item in limited_items):
            return
        self.locate_service.apply_plan(
            LocatePlan(
                items=limited_items,
                marker_limit=MAX_LOCATE_MARKERS,
            )
        )

    def set_bulk_locate_status(self, total):
        shown = min(total, MAX_LOCATE_ITEMS)
        markers = min(shown, MAX_LOCATE_MARKERS)
        if total <= MAX_LOCATE_ITEMS:
            self.set_locate_status(
                _("Selected {shown} item(s), marked {markers}.").format(
                    shown=shown,
                    markers=markers,
                )
            )
            return
        self.set_locate_status(
            _("This group has {total} items. Showing first {shown}, marking first {markers} to keep KiCad responsive.").format(
                total=total,
                shown=shown,
                markers=markers,
            )
        )

    def set_locate_status(self, message):
        self._locate_status = message
        if self.GetStatusBar() is not None:
            self.SetStatusText(message)

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
        counts = self.analysis_type_counts()
        return [
            self.analysis_type_label(item, counts[item])
            for item in sorted(counts)
        ]

    def analysis_type_counts(self, selected_layers=None):
        counts = {}
        result_data = self.result_json.get(self.json_string, "")
        if not isinstance(result_data, dict):
            return counts
        for result_list in result_data.get("check") or ():
            for result in result_list.get("result") or ():
                if selected_layers is not None:
                    layers = self.child_frame_setting.layer_conversion(
                        self.json_string, result.get("layer") or []
                    )
                    if not layers or layers[0] not in selected_layers:
                        continue
                # Native rows may already contain a localized item while
                # Gerber rows keep the canonical English item.  Both engines
                # attach the same stable rule key, so resolve that identity
                # before counting to avoid duplicate visual groups.
                item = self.canonical_analysis_item(result)
                counts[item] = counts.get(item, 0) + 1
        # The alarm-only filter intentionally removes passing detail rows from
        # ``check``.  Do not let that make an executed rule disappear from the
        # analysis structure: an item summary is the engine's explicit proof
        # that the rule ran, while the zero count makes it clear that there are
        # no rows in the current view.
        for item, _summary in self.executed_item_summaries():
            counts.setdefault(item, 0)
        return counts

    def executed_item_summaries(self):
        """Return catalog identities for item summaries proven to have run."""
        result_data = self.result_json.get(self.json_string, "")
        if not isinstance(result_data, dict):
            return ()
        if str(result_data.get("execution_status") or "") != "completed":
            return ()
        summaries = result_data.get("item_summaries")
        if not isinstance(summaries, dict):
            return ()

        executed = []
        seen = set()
        catalog_keys = {
            build_rule_key(self.json_string, metadata.get("item")): metadata.get("item")
            for metadata in RULE_CATALOG.get(self.json_string, ())
        }
        for summary_key, summary in summaries.items():
            if not isinstance(summary, dict):
                continue
            summary_status = str(summary.get("execution_status") or "completed")
            if summary_status != "completed":
                continue
            stable_key = str(summary.get("rule_key") or "")
            if not stable_key and str(summary_key) in catalog_keys:
                stable_key = str(summary_key)
            raw_item = str(summary.get("item") or "")
            if not raw_item and not stable_key:
                raw_item = str(summary_key)
            item = self.canonical_analysis_item(
                {"rule_key": stable_key, "item": raw_item}
            )
            # Only catalog-backed identities are safe to present as an
            # executed rule.  This prevents partial/remote payload metadata
            # from inventing checks that the engine did not run.
            if item not in catalog_keys.values() or item in seen:
                continue
            normalized = dict(summary)
            normalized.setdefault("item", item)
            normalized.setdefault("rule_key", build_rule_key(self.json_string, item))
            executed.append((item, normalized))
            seen.add(item)
        return tuple(executed)

    def canonical_analysis_item(self, result):
        """Return the catalog item identified by a result's stable rule key."""
        result = result if isinstance(result, dict) else {}
        stable_key = str(result.get("rule_key") or "")
        catalog = RULE_CATALOG.get(self.json_string, ())
        if stable_key:
            for metadata in catalog:
                item = str(metadata.get("item") or "")
                if stable_key == build_rule_key(self.json_string, item):
                    return item

        raw_item = str(result.get("item") or "")
        normalized_item = normalize_name(raw_item)
        if not normalized_item:
            return raw_item
        for metadata in catalog:
            item = str(metadata.get("item") or "")
            aliases = {
                normalize_name(item),
                normalize_name(_(item)),
            }
            item_key = item.strip().lower()
            for mapping in (config.Language_chinese, config.Language_english):
                aliases.add(normalize_name(mapping.get(item, "")))
                aliases.add(normalize_name(mapping.get(item_key, "")))
            aliases.discard("")
            if normalized_item in aliases:
                return item
        return raw_item

    def analysis_type_text(self, item):
        """Translate a rule item for display while retaining its stable key."""
        translated = _(str(item))
        if translated != item:
            return translated
        return self.message_type.get(str(item).strip().lower(), str(item))

    def analysis_type_label(self, item, count=None):
        text = self.analysis_type_text(item)
        if count is None:
            return text
        return "{0}({1}{2})".format(
            text,
            count,
            self.message_type.get("pcs", _("pcs")),
        )

    def analysis_type_key(self, label):
        for item in self.analysis_type_counts():
            text = self.analysis_type_text(item)
            if label == item or label == text or str(label).startswith(text + "("):
                return item
        return label

    def get_result(self):
        analysis_result = []
        result_data = self.result_json.get(self.json_string, {})
        if result_data == "" or not result_data.get("check"):
            return analysis_result
        num = 0
        for result_list in result_data["check"]:
            for result in result_list["result"]:
                num += 1
                analysis_result.append(
                    [
                        str(num),
                        self.result_severity(result),
                        self.format_result_value(result),
                        self.format_result_layer(result),
                        result.get("color", "black"),
                    ]
                )
        return analysis_result

    def result_severity(self, result):
        color = result.get("color")
        if color == "red":
            return _("Error")
        if color == "gold":
            return _("Warning")
        return _("OK")

    def GetImagePath(self, bitmap_path):
        return GetImagePath(bitmap_path)
