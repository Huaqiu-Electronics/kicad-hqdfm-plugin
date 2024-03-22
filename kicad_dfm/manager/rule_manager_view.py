import wx
import pcbnew
from kicad_dfm.picture import GetImagePath
from kicad_dfm.manager.ui_rule_manager import UiRuleManager
import wx.dataview as dv


class RuleManagerView(UiRuleManager):
    def __init__(self, parent, result_json, item_size, unit):
        super().__init__(parent)
        self.temp_layer = {""}
        self.unit = unit
        self.result_json = result_json
        self.item_size = item_size

        self.init_ui()
        self.fill_list_data()

    def init_ui(self):
        self.rule_manager_list.AppendTextColumn(
            _("ID"),
            0,
            width=50,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        self.rule_manager_list.AppendTextColumn(
            _("AnalyseItem"),
            1,
            width=170,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        self.rule_manager_list.AppendTextColumn(
            _("AnalyseSubItem"),
            2,
            width=170,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        self.rule_manager_list.AppendTextColumn(
            _("ReportSet"),
            3,
            width=200,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )
        self.rule_manager_list.AppendTextColumn(
            _("Unit"),
            4,
            width=50,
            align=wx.ALIGN_CENTER,
            flags=dv.DATAVIEW_COL_RESIZABLE,
        )

    def fill_list_data(self):
        data = []
        number = 0
        if self.unit == 0:
            unit = "inch"
        elif self.unit == 5:
            unit = "mil"
        # elif self.unit == 1:
        else:
            unit = "mm"
        for item in self.result_json:
            for result in self.result_json[item]:
                number += 1
                data = [
                    str(number),
                    _(item),
                    _(list(result.keys())[0]),
                    self.dispose_json_rule(result[list(result.keys())[0]]),
                    unit,
                ]
                self.rule_manager_list.AppendItem(data)

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
            iu_value = float(rule_string) / 25.4
            return str(round(iu_value, 3))
        elif self.unit == 5:
            mils_value = float(rule_string) * 39.37
            return str(round(mils_value, 3))
        else:
            return rule_string
