from kicad_dfm.core.rule_catalog import RULE_CATALOG, default_rule_for, normalize_name


class ColorRule:
    def __init__(self, rules=None):
        self.rules = rules

    def get_rule(self, analysis_result, name, item_name, different):
        temp_rule = self.configured_rule_for(name, item_name)
        if temp_rule == "":
            temp_rule = self.find_rule(analysis_result, name, item_name)
        if temp_rule == "":
            temp_rule = self.default_rule_for(name, item_name)
        if temp_rule == "":
            return "black"
        return self.color_for_rule(temp_rule, different, self.rule_kind(name, item_name))

    def find_rule(self, analysis_result, name, item_name):
        category_result = analysis_result.get(name) if isinstance(analysis_result, dict) else None
        checks = category_result.get("check") if isinstance(category_result, dict) else None
        if not checks:
            return ""
        for item_check in checks:
            for detail_result in item_check.get("result") or ():
                item = detail_result.get("item")
                if item == item_name:
                    return detail_result.get("rule", "")
        for rule_result in category_result.get("_rules", ()):
            item = list(rule_result.keys())[0]
            if item == item_name:
                return rule_result[item]
        return ""

    def color_for_rule(self, temp_rule, different, kind=""):
        try:
            different = float(different)
        except (TypeError, ValueError):
            return "black"
        rule_string1 = temp_rule.partition(",")
        rule_string2 = rule_string1[2].partition(",")
        first = float(rule_string1[0])
        second = float(rule_string2[0])
        if kind == "range":
            rule_string3 = rule_string2[2].partition(",")
            upper = float(rule_string3[0]) if rule_string3[0] else second
            lower = min(first, second)
            warning = max(first, second)
            if different < lower or different > upper:
                return "red"
            if different < warning:
                return "gold"
            return "black"
        if kind == "min" or first < second:
            if different < first:
                return "red"
            elif first <= different < second:
                return "gold"
            else:
                return "black"
        else:
            if different > first:
                return "red"
            elif second < different < first:
                return "gold"
            else:
                return "black"

    def filter_rule_vlaue(self, analysis_result, name, item_name):
        temp_rule = self.configured_rule_for(name, item_name)
        if not temp_rule:
            temp_rule = self.find_rule(analysis_result, name, item_name)
        if not temp_rule:
            temp_rule = self.default_rule_for(name, item_name)
        if temp_rule:
            return self.third_rule_value(temp_rule)
        result = analysis_result.get(name) if isinstance(analysis_result, dict) else None
        checks = result.get("check") if isinstance(result, dict) else None
        if not checks:
            return None
        for item_check in checks:
            for result in item_check.get("result") or ():
                item = result.get("item")
                if item == item_name:
                    temp_rule = result.get("rule")
                    if not temp_rule:
                        return None
                    return self.third_rule_value(temp_rule)
        return None

    def third_rule_value(self, temp_rule):
        rule_string1 = temp_rule.partition(",")
        rule_string2 = rule_string1[2].partition(",")
        rule_string3 = rule_string2[2].partition(",")
        if rule_string3[0]:
            return float(rule_string3[0])
        return 0

    def default_rule_for(self, category, item):
        configured = self.configured_rule_for(category, item)
        if configured:
            return configured
        return default_rule_for(category, item)

    def configured_rule_for(self, category, item):
        if self.rules:
            normalized_item = normalize_name(item)
            for rule in self.rules.get(category, ()):
                if normalize_name(rule.get("item")) == normalized_item:
                    return rule.get("rule", "")
        return ""

    def rule_kind(self, category, item):
        normalized_item = normalize_name(item)
        for source in (self.rules, RULE_CATALOG):
            if not source:
                continue
            for rule in source.get(category, ()):
                if normalize_name(rule.get("item")) == normalized_item:
                    return rule.get("kind", "")
        return ""
