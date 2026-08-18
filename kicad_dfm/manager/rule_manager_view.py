import wx
from kicad_dfm.manager.ui_rule_manager import UiRuleManager
import wx.dataview as dv
from kicad_dfm.child_frame.diagram_hint import diagram_bitmap_for
from kicad_dfm.core.i18n import _
from kicad_dfm.core.rule_profiles import (
    PROFILE_LABELS,
    profile_label,
    rule_label,
    update_profile_rules,
)
from kicad_dfm.core.units import mm_to_inches, mm_to_mils, mils_to_mm
from kicad_dfm.ui.rule_frame import (
    dispose_rule,
    merged_rule_map,
    rule_unit_for,
    rules_to_result_json,
    transform_rule_value,
    unit_name_for,
)


class RuleManagerView(UiRuleManager):
    def __init__(self, parent, profile_id, rules, unit, translations=None):
        super().__init__(parent)
        self.temp_layer = {""}
        self.unit = unit
        self.profile_id = profile_id
        self.rules = rules
        self.result_json = rules_to_result_json(rules)
        self.row_keys = []
        self.selected_row = -1
        self.translations = translations or {}

        self.init_ui()
        self.fill_list_data()
        self.rule_profile_name.SetLabel(_(profile_label(PROFILE_LABELS.get(profile_id, profile_id), self.translations)))
        self.rule_manager_list.Bind(dv.EVT_DATAVIEW_SELECTION_CHANGED, self.on_rule_selected)
        self.rule_manager_list.Bind(wx.EVT_LEFT_UP, self.on_rule_click)
        self.rule_manager_list.Bind(wx.EVT_LEFT_DCLICK, self.on_rule_double_click)
        self.rule_value_text.Bind(wx.EVT_TEXT, self.on_rule_value_changed)
        self.rule_value_text.Bind(wx.EVT_TEXT_ENTER, self.on_apply_rule_value)
        self.save_button.Bind(wx.EVT_BUTTON, self.on_save)
        self.close_button.Bind(wx.EVT_BUTTON, self.on_close)
        self.rule_manager_list.SetFocus()

    def init_ui(self):
        self.rule_manager_list.AppendTextColumn(
            _("ID"),
            width=45,
            mode=dv.DATAVIEW_CELL_INERT,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        self.rule_manager_list.AppendTextColumn(
            _("AnalyseItem"),
            width=145,
            mode=dv.DATAVIEW_CELL_INERT,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        self.rule_manager_list.AppendTextColumn(
            _("AnalyseSubItem"),
            width=155,
            mode=dv.DATAVIEW_CELL_INERT,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        self.rule_manager_list.AppendTextColumn(
            _("ReportSet"),
            width=170,
            mode=dv.DATAVIEW_CELL_INERT,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        self.rule_manager_list.AppendTextColumn(
            _("Unit"),
            width=45,
            mode=dv.DATAVIEW_CELL_INERT,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )

    def fill_list_data(self):
        number = 0
        unit_name = unit_name_for(self.unit)
        for category, rules in merged_rule_map(self.result_json).items():
            for result in rules:
                number += 1
                sub_item = list(result.keys())[0]
                rule_unit = rule_unit_for(category, sub_item)
                self.row_keys.append((category, sub_item))
                self.rule_manager_list.AppendItem(
                    [
                        str(number),
                        rule_label(category, self.translations, _),
                        rule_label(sub_item, self.translations, _),
                        dispose_rule(
                            result[sub_item],
                            lambda value, source_unit=rule_unit: transform_rule_value(
                                value, source_unit, self.transform_unit
                            ),
                        ),
                        unit_name if rule_unit == "mm" else rule_unit,
                    ]
                )
        if self.rule_manager_list.GetItemCount():
            self.select_row(0)

    def dispose_json_rule(self, json_string):
        rule_string1 = json_string.partition(",")
        rule_string2 = rule_string1[2].partition(",")
        rule_string3 = rule_string2[2].partition(",")
        return (
            self.transform_unit(rule_string1[0])
            + ","
            + self.transform_unit(rule_string2[0])
            + ","
            + self.transform_unit(rule_string3[0])
        )

    def transform_unit(self, rule_string):
        if rule_string == "-":
            return "-"

        if self.unit == 0:
            iu_value = mm_to_inches(rule_string)
            return str(round(iu_value, 3))
        elif self.unit == 5:
            mils_value = mm_to_mils(rule_string)
            return str(round(mils_value, 3))
        else:
            return rule_string

    def restore_unit(self, rule_string):
        if rule_string == "-":
            return "-"
        try:
            value = float(rule_string)
        except ValueError:
            raise ValueError(_("Rule values must be numbers or '-' placeholders."))
        if self.unit == 0:
            return "{0:.6f}".format(value * 25.4)
        if self.unit == 5:
            return "{0:.6f}".format(mils_to_mm(value))
        return "{0:.6f}".format(value)

    def select_row(self, row):
        item = self.rule_manager_list.RowToItem(row)
        if item.IsOk():
            self.rule_manager_list.Select(item)
            self.load_row_into_editor(row)

    def on_rule_selected(self, event):
        row = self.rule_manager_list.ItemToRow(event.GetItem())
        if row >= 0:
            self.load_row_into_editor(row)
        event.Skip()

    def on_rule_click(self, event):
        wx.CallAfter(self.focus_selected_rule)
        event.Skip()

    def on_rule_double_click(self, event):
        self.focus_rule_editor()
        event.Skip()

    def focus_selected_rule(self):
        item = self.rule_manager_list.GetSelection()
        if item.IsOk():
            row = self.rule_manager_list.ItemToRow(item)
            if row >= 0 and row != self.selected_row:
                self.load_row_into_editor(row)
            else:
                self.focus_rule_editor()

    def on_apply_rule_value(self, event):
        self.apply_rule_editor()
        event.Skip()

    def on_rule_value_changed(self, event):
        self.sync_rule_editor()
        event.Skip()

    def load_row_into_editor(self, row):
        self.selected_row = row
        name = "{} / {}".format(
            self.rule_manager_list.GetTextValue(row, 1),
            self.rule_manager_list.GetTextValue(row, 2),
        )
        self.selected_rule_name.SetLabel(name)
        self.selected_rule_name.Wrap(320)
        self.rule_value_text.ChangeValue(self.rule_manager_list.GetTextValue(row, 3))
        self.update_rule_picture(row)

    def update_rule_picture(self, row):
        source_category, source_item = self.row_keys[row]
        bitmap = diagram_bitmap_for(source_item, max_size=(260, 110), fallback=False)
        if bitmap is None or not bitmap.IsOk():
            bitmap = diagram_bitmap_for(source_category, max_size=(260, 110))
        self.rule_picture.SetBitmap(bitmap)
        self.rule_picture.Refresh()

    def scaled_bitmap(self, bitmap, max_width, max_height):
        if not bitmap.IsOk():
            return bitmap
        width = bitmap.GetWidth()
        height = bitmap.GetHeight()
        if width <= max_width and height <= max_height:
            return bitmap
        scale = min(float(max_width) / width, float(max_height) / height)
        image = bitmap.ConvertToImage()
        return wx.Bitmap(image.Scale(max(1, int(width * scale)), max(1, int(height * scale))))

    def focus_rule_editor(self):
        self.rule_value_text.SetFocus()
        self.rule_value_text.SetSelection(0, -1)

    def apply_rule_editor(self, show_error=True):
        if self.selected_row < 0:
            return False
        value = self.rule_value_text.GetValue().strip()
        try:
            category, item = self.row_keys[self.selected_row]
            self.restore_rule(value, category, item)
        except ValueError as exc:
            if show_error:
                wx.MessageBox(str(exc), _("Error"), style=wx.ICON_ERROR)
                self.focus_rule_editor()
            return False
        self.rule_manager_list.SetTextValue(value, self.selected_row, 3)
        return True

    def sync_rule_editor(self):
        if self.selected_row >= 0:
            self.rule_manager_list.SetTextValue(
                self.rule_value_text.GetValue(), self.selected_row, 3
            )

    def on_save(self, event):
        if not self.apply_rule_editor():
            return
        try:
            rules = self.rules_from_rows()
        except ValueError as exc:
            wx.MessageBox(str(exc), _("Error"), style=wx.ICON_ERROR)
            return
        update_profile_rules(self.profile_id, rules)
        wx.MessageBox(_("Rules saved."), _("Info"), style=wx.ICON_INFORMATION)
        event.Skip()

    def on_close(self, event):
        self.Destroy()
        event.Skip()

    def rules_from_rows(self):
        rules = {}
        for row in range(self.rule_manager_list.GetItemCount()):
            rule = self.rule_manager_list.GetTextValue(row, 3)
            source_category, source_item = self.row_keys[row]
            rules.setdefault(source_category, []).append(
                {
                    "item": source_item,
                    "rule": self.restore_rule(rule, source_category, source_item),
                }
            )
        return rules

    def restore_rule(self, rule, category="", item=""):
        rule_unit = rule_unit_for(category, item)
        parts = str(rule or "").split(",")
        restored = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part == "-":
                restored.append(part)
                continue
            restored.append(
                self.restore_unit(part) if rule_unit == "mm" else "{0:.6f}".format(float(part))
            )
        if len(restored) < 3:
            raise ValueError(_("Rule values must contain three comma-separated fields."))
        return ",".join(restored)
