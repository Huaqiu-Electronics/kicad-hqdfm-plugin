import wx
from . import config


class RuleManagerFrame(wx.Frame):
    def __init__(self, parent, result_json, item_size, unit, language):
        self.temp_layer = {""}
        self.language_string = {}
        if language == "简体中文":
            self.language_string = config.Language_chinese
        else:
            self.language_string = config.Language_english
        super(wx.Frame, self).__init__(
            parent, title=self.language_string["title"], size=(650, 800)
        )
        self.grid = wx.grid.Grid(self, size=(650, 800))
        self.unit = unit
        self.grid.CreateGrid(item_size + 1, 5)
        self.grid.HideColLabels()
        self.grid.HideRowLabels()
        self.grid.SetColSize(0, 50)
        self.grid.SetColSize(1, 200)
        self.grid.SetColSize(2, 130)
        self.grid.SetColSize(3, 200)
        self.grid.SetColSize(4, 50)
        self.grid.Center()
        self.grid.SetRowSize(0, 50)
        self.grid.SetCellValue(0, 0, "id")
        self.grid.EnableEditing(False)
        self.grid.SetCellAlignment(0, 0, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        self.grid.SetCellBackgroundColour(0, 0, wx.Colour(192, 192, 192))
        self.grid.SetCellValue(0, 1, self.language_string["Analyse_Item"])
        self.grid.SetCellAlignment(0, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        self.grid.SetCellBackgroundColour(0, 1, wx.Colour(192, 192, 192))
        self.grid.SetCellValue(0, 2, self.language_string["Analyse_SubItem"])
        self.grid.SetCellAlignment(0, 2, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        self.grid.SetCellBackgroundColour(0, 2, wx.Colour(192, 192, 192))
        self.grid.SetCellValue(0, 3, self.language_string["Report_Set"])
        self.grid.SetCellAlignment(0, 3, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        self.grid.SetCellBackgroundColour(0, 3, wx.Colour(192, 192, 192))
        self.grid.SetCellValue(0, 4, self.language_string["unit"])
        self.grid.SetCellAlignment(0, 4, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        self.grid.SetCellBackgroundColour(0, 4, wx.Colour(192, 192, 192))
        number = 1
        for item in result_json:
            for result in result_json[item]:
                self.grid.SetRowSize(number, 35)
                self.grid.SetCellValue(number, 0, str(number))
                self.grid.SetCellAlignment(number, 0, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                if language == "简体中文":
                    self.grid.SetCellValue(number, 1, self.language_string[item])
                else:
                    self.grid.SetCellValue(number, 1, item)
                self.grid.SetCellAlignment(number, 1, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellValue(number, 2, list(result.keys())[0])
                self.grid.SetCellAlignment(number, 2, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                self.grid.SetCellValue(
                    number, 3, self.dispose_json_rule(result[list(result.keys())[0]])
                )
                self.grid.SetCellAlignment(number, 3, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                if unit == 0:
                    self.grid.SetCellValue(number, 4, "inch")
                elif unit == 5:
                    self.grid.SetCellValue(number, 4, "mil")
                elif unit == 1:
                    self.grid.SetCellValue(number, 4, "mm")
                self.grid.SetCellAlignment(number, 4, wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
                number += 1
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.grid, 0, wx.ALL, 0)
        self.SetSizer(sizer)
        self.Centre()
        self.Show(True)

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
            return str(round(iu_value), 3)
        elif self.unit == 5:
            mils_value = float(rule_string) * 39.37
            return str(round(mils_value, 3))
        else:
            return rule_string
