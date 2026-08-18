import pathlib
import unittest

from kicad_dfm.core.rule_catalog import RULE_CATALOG
from kicad_dfm.core.rule_contract import assert_valid_rule_contract
from kicad_dfm.core.rule_contract import rule_key
from kicad_dfm.core.rule_contract import validate_rule_contract
from kicad_dfm.core.rule_profiles import default_profiles
from kicad_dfm.services.native_drc import NATIVE_DRC_CATEGORY_KEYS
from kicad_dfm.services.offline_analysis import COMPAT_CATEGORIES
from kicad_dfm.services.offline_analysis import IMPLEMENTED_LOCAL_CATEGORIES
from kicad_dfm.services.offline_analysis import LOCAL_CHECKS
from kicad_dfm.ui.main_frame import SUMMARY_ITEMS
from kicad_dfm.ui.rule_frame import default_categories
from kicad_dfm.settings.color_rule import ColorRule


class RuleContractTest(unittest.TestCase):
    def test_hole_size_rule_contract_matches_manufacturing_table(self):
        expected = {
            "Smallest Drill Size": ("0.190000,0.250000,0.300000", "mm", "hqpcb_public_capability"),
            "Smallest PTH": ("0.290000,0.450000,999.000000", "mm", "official_service_sample"),
            "Largest Drill Size": ("999.000000,6.300000,6.000000", "mm", "hqpcb_public_capability"),
            "Largest PTH Size": ("999.000000,6.300000,6.000000", "mm", "official_service_sample"),
            "Aspect Ratio": ("12.000000,10.000000,8.000000", "ratio", "official_service_sample"),
            "Smallest Via [mec]": ("0.190000,0.250000,999.000000", "mm", "official_service_sample"),
            "Smallest Blind_Laser": ("0.090000,0.130000,999.000000", "mm", "official_service_sample"),
            "Smallest Blind_mec": ("0.190000,0.250000,999.000000", "mm", "official_service_sample"),
            "Smallest Buried_Laser": ("0.090000,0.130000,999.000000", "mm", "official_service_sample"),
            "Smallest Buried_mec": ("0.190000,0.250000,999.000000", "mm", "official_service_sample"),
            "Smallest Slot Width": ("0.450088,0.599948,5.999988", "mm", "plugin_default"),
            "Largest Blind/Buried Via": ("0.500000,0.400000,0.300000", "mm", "official_service_sample"),
            "Largest Slot Length": ("15.000000,12.000000,10.000000", "mm", "official_service_sample"),
            "Largest Slot Width": ("8.000000,7.000000,6.000000", "mm", "official_service_sample"),
            "Slot Aspect Ratio": ("1.500000,2.000000,999.000000", "ratio", "official_service_sample"),
        }
        actual = {
            rule["item"]: (rule["rule"], rule["unit"], rule["source"])
            for rule in RULE_CATALOG["Hole Size"]
        }

        self.assertEqual(expected, actual)
        self.assertTrue(all(rule["offline_status"] == "implemented" for rule in RULE_CATALOG["Hole Size"]))

    def test_slot_width_contract_has_independent_minimum_and_maximum_checks(self):
        items = {rule["item"]: rule for rule in RULE_CATALOG["Hole Size"]}

        self.assertEqual("0.450088,0.599948,5.999988", items["Smallest Slot Width"]["rule"])
        self.assertEqual(
            [17.72, 23.62, 236.22],
            [round(float(value) / 0.0254, 2) for value in items["Smallest Slot Width"]["rule"].split(",")],
        )
        self.assertEqual("min", items["Smallest Slot Width"]["kind"])
        self.assertEqual("8.000000,7.000000,6.000000", items["Largest Slot Width"]["rule"])
        self.assertEqual("max", items["Largest Slot Width"]["kind"])
        self.assertIn("5.8 mm", items["Largest Slot Width"]["description"])
        self.assertNotIn("Square Hole Size", items)

    def test_requested_hole_size_guidance_is_description_only(self):
        items = {rule["item"]: rule for rule in RULE_CATALOG["Hole Size"]}

        expected_fragments = {
            "Smallest Drill Size": "0.3 mm",
            "Aspect Ratio": "thick PCB",
            "Smallest Slot Width": "0.6 mm",
            "Largest Slot Length": "10 mm",
            "Largest Slot Width": "5.8 mm",
            "Slot Aspect Ratio": "twice the width",
        }
        for item, fragment in expected_fragments.items():
            self.assertTrue(items[item].get("description_only"), item)
            self.assertIn(fragment, items[item]["description"])

    def test_slot_aspect_ratio_is_a_minimum_not_a_range(self):
        item = next(
            rule
            for rule in RULE_CATALOG["Hole Size"]
            if rule["item"] == "Slot Aspect Ratio"
        )
        colors = ColorRule()

        self.assertEqual("min", item["kind"])
        self.assertEqual("red", colors.color_for_rule(item["rule"], 1.49, item["kind"]))
        self.assertEqual("gold", colors.color_for_rule(item["rule"], 1.75, item["kind"]))
        self.assertEqual("black", colors.color_for_rule(item["rule"], 2.0, item["kind"]))
        self.assertEqual("black", colors.color_for_rule(item["rule"], 5.0, item["kind"]))

    def test_range_rules_use_lower_alarm_warning_and_upper_limit(self):
        colors = ColorRule()
        self.assertEqual("red", colors.color_for_rule("1,2,3", 0.9, "range"))
        self.assertEqual("gold", colors.color_for_rule("1,2,3", 1.5, "range"))
        self.assertEqual("black", colors.color_for_rule("1,2,3", 2.5, "range"))
        self.assertEqual("red", colors.color_for_rule("1,2,3", 3.1, "range"))

    def test_annular_ring_rule_contract_matches_exact_mil_thresholds(self):
        expected = {
            "Via Annular Ring": "0.101600,0.127000,0.152400",
            "PTH Annular Ring": "0.152400,0.177800,0.203200",
        }
        actual = {rule["item"]: rule for rule in RULE_CATALOG["RingHole"]}

        self.assertEqual(expected, {item: rule["rule"] for item, rule in actual.items()})
        self.assertTrue(all(rule.get("profile_scale") == "fixed" for rule in actual.values()))

    def test_different_net_pth_spacing_uses_exact_fixed_mil_thresholds(self):
        rule = next(
            rule
            for rule in RULE_CATALOG["Drill Hole Spacing"]
            if rule["item"] == "Different Net PTH Spacing"
        )

        self.assertEqual("0.400050,0.450088,0.500126", rule["rule"])
        self.assertEqual("fixed", rule["profile_scale"])
        self.assertTrue(rule["description_only"])

    def test_smd_spacing_is_an_independent_fixed_rule_category(self):
        self.assertNotIn(
            "SMD Pad Spacing",
            {rule["item"] for rule in RULE_CATALOG["Smallest Trace Spacing"]},
        )
        self.assertEqual(
            ("SMD Pad Spacing",),
            tuple(rule["item"] for rule in RULE_CATALOG["SMD Spacing"]),
        )
        rule = RULE_CATALOG["SMD Spacing"][0]
        self.assertEqual("0.152400,0.203200,0.254000", rule["rule"])
        self.assertEqual("fixed", rule["profile_scale"])
        spacing_index = COMPAT_CATEGORIES.index("Smallest Trace Spacing")
        self.assertEqual("SMD Spacing", COMPAT_CATEGORIES[spacing_index + 1])
        summary_index = SUMMARY_ITEMS.index("Smallest Trace Spacing")
        self.assertEqual("SMD Spacing", SUMMARY_ITEMS[summary_index + 1])

    def test_smd_summary_row_and_action_button_keep_the_same_order(self):
        dialog_dir = pathlib.Path(__file__).parents[1] / "kicad_dfm" / "dfm_maindialog"
        generated = (dialog_dir / "ui_dfm_maindialog.py").read_text(encoding="utf-8")
        view = (dialog_dir / "dfm_maindialog_view.py").read_text(encoding="utf-8")
        self.assertLess(
            generated.index("bSizer7.Add(self.pad_spacing_button"),
            generated.index("bSizer7.Add(self.pad_size_button"),
        )
        self.assertLess(
            view.index("self.smd_spacing_button,"),
            view.index("self.pad_size_button,"),
        )

    def test_holes_on_smd_rule_contract_matches_official_service_sample(self):
        expected = {
            "Via on BGA Pad": "0.010000,0.010000,0.000000",
            "Via on SMD Pad": "0.150000,0.050000,0.000000",
            "NPTH on SMD Pad": "0.100000,0.010000,0.000000",
            "PTH on SMD Pad": "0.100000,0.050000,0.000000",
        }
        actual = {rule["item"]: rule for rule in RULE_CATALOG["Holes on SMD Pads"]}

        self.assertEqual(expected, {item: rule["rule"] for item, rule in actual.items()})
        self.assertTrue(all(rule["unit"] == "mm" for rule in actual.values()))
        self.assertTrue(all(rule["source"] == "official_service_sample" for rule in actual.values()))
        self.assertTrue(all(rule.get("profile_scale") == "fixed" for rule in actual.values()))

    def test_special_drill_contract_contains_only_shape_and_castellated_holes(self):
        self.assertEqual(
            ("Square/Rectangular Drills", "Castellated Holes"),
            tuple(rule["item"] for rule in RULE_CATALOG["Special Drill Holes"]),
        )

    def test_default_rule_contract_is_consistent(self):
        assert_valid_rule_contract(
            implemented_categories=IMPLEMENTED_LOCAL_CATEGORIES,
            compat_categories=COMPAT_CATEGORIES,
            summary_items=SUMMARY_ITEMS,
            native_marker_categories=NATIVE_DRC_CATEGORY_KEYS,
        )

    def test_gerber_export_is_not_a_fixed_main_summary_row(self):
        self.assertNotIn("Gerber Export", SUMMARY_ITEMS)

    def test_rule_frame_categories_follow_offline_implementation(self):
        self.assertEqual(IMPLEMENTED_LOCAL_CATEGORIES, default_categories())

    def test_offline_categories_are_derived_from_local_check_table(self):
        self.assertEqual(
            tuple(category for category, _method_name in LOCAL_CHECKS),
            IMPLEMENTED_LOCAL_CATEGORIES,
        )
        self.assertEqual(len(LOCAL_CHECKS), len({category for category, _method_name in LOCAL_CHECKS}))

    def test_default_profiles_keep_catalog_categories_and_items(self):
        catalog_items = {
            category: tuple(rule["item"] for rule in entries)
            for category, entries in RULE_CATALOG.items()
        }
        for profile in default_profiles().values():
            rules = profile["rules"]
            self.assertEqual(set(catalog_items), set(rules))
            for category, items in catalog_items.items():
                self.assertEqual(items, tuple(rule["item"] for rule in rules[category]))

    def test_compat_categories_use_standard_board_edge_name(self):
        self.assertIn("Copper-to-Board Edge", COMPAT_CATEGORIES)
        self.assertIn("Hole-to-Board Edge", COMPAT_CATEGORIES)
        self.assertNotIn("Board Edge Clearance", COMPAT_CATEGORIES)

    def test_hole_to_board_edge_rule_contract_matches_reference(self):
        rules = {
            entry["item"]: entry
            for entry in RULE_CATALOG["Hole-to-Board Edge"]
        }
        self.assertEqual(
            "0.400050,0.500126,0.599948",
            rules["PTH-to-Board Edge"]["rule"],
        )
        self.assertEqual(
            "0.299974,0.400050,0.500126",
            rules["Via-to-Board Edge"]["rule"],
        )
        self.assertEqual(
            "0.400050,0.500126,0.599948",
            rules["Screw Hole-to-Board Edge"]["rule"],
        )
        self.assertEqual(
            "0.199898,0.299974,0.400050",
            rules["NPTH-to-Board Edge"]["rule"],
        )
        for rule in rules.values():
            self.assertEqual("fixed", rule["profile_scale"])
            self.assertEqual("implemented", rule["offline_status"])

    def test_hatched_copper_category_is_retired_everywhere(self):
        category = "Hatched Copper Pour"
        self.assertNotIn(category, RULE_CATALOG)
        self.assertNotIn(category, IMPLEMENTED_LOCAL_CATEGORIES)
        self.assertNotIn(category, COMPAT_CATEGORIES)
        self.assertNotIn(category, SUMMARY_ITEMS)
        self.assertNotIn(category, NATIVE_DRC_CATEGORY_KEYS)

    def test_rule_key_normalizes_category_and_item(self):
        self.assertEqual("tracemssing:viaannularring", rule_key("Trace Mssing", "Via Annular Ring"))

    def test_validate_rule_contract_reports_missing_category(self):
        issues = validate_rule_contract(
            rule_catalog={"Only Catalog": ({"item": "A", "rule": "1,2,3", "unit": "mm", "kind": "min", "source": "test", "offline_status": "implemented"},)},
            implemented_categories=("Missing",),
            compat_categories=("Missing",),
            summary_items=("Missing",),
        )

        self.assertTrue(any(issue.code == "implemented_missing_catalog" for issue in issues))
        self.assertTrue(any(issue.code == "catalog_missing_implemented" for issue in issues))


if __name__ == "__main__":
    unittest.main()
