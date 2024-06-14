import wx


class ColorRule:
    def __init__(self):
        pass

    def get_rule(self, analysis_result, name, item_name, different):
        temp_rule = ""
        if analysis_result[name]["check"] is None:
            return "black"
        for item_check in analysis_result[name]["check"]:
            for result in item_check["result"]:
                item = result["item"]
                if item == item_name:
                    temp_rule = result["rule"]
        if temp_rule == "":
            return "red"
        rule_string1 = temp_rule.partition(",")
        rule_string2 = rule_string1[2].partition(",")
        if float(rule_string1[0]) < float(rule_string2[0]):
            if different < float(rule_string1[0]):
                return "red"
            elif float(rule_string2[0]) > different > float(rule_string1[0]):
                return "gold"
            else:
                return "black"
        else:
            if different > float(rule_string1[0]):
                return "red"
            elif float(rule_string2[0]) < different < float(rule_string1[0]):
                return "gold"
            else:
                return "black"

    def filter_rule_vlaue(self, analysis_result, name, item_name):
        temp_rule = ""
        for item_check in analysis_result[name]["check"]:
            for result in item_check["result"]:
                # wx.MessageBox(f"{item_name}")
                # wx.MessageBox(f"{result}")
                item = result["item"]
                if item == item_name:
                    temp_rule = result["rule"]
                if temp_rule == "" or temp_rule is None:
                    break
                rule_string1 = temp_rule.partition(",")
                rule_string2 = rule_string1[2].partition(",")
                rule_string3 = rule_string2[2].partition(",")
                if rule_string3[0]:
                    return float(rule_string3[0])
                else:
                    return 0
