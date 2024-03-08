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
                return "orange"
            else:
                return "black"
        else:
            if different > float(rule_string1[0]):
                return "red"
            elif float(rule_string2[0]) < different < float(rule_string1[0]):
                return "orange"
            else:
                return "black"
