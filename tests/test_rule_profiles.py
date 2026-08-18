import os
import tempfile
import unittest

from kicad_dfm.core import rule_profiles
from kicad_dfm.config import Language_chinese, Language_english
from kicad_dfm.core.settings import DEFAULT_SETTINGS
from kicad_dfm.settings.color_rule import ColorRule
from kicad_dfm.ui.rule_frame import build_rule_rows, rules_to_result_json


class RuleProfilesTest(unittest.TestCase):
    def test_rule_manager_labels_cover_every_catalog_rule_in_both_languages(self):
        for mapping in (Language_chinese, Language_english):
            for category, entries in rule_profiles.RULE_CATALOG.items():
                self.assertNotEqual(
                    "fallback",
                    rule_profiles.rule_label(category, mapping, lambda _value: "fallback"),
                    category,
                )
                for entry in entries:
                    item = entry["item"]
                    self.assertNotEqual(
                        "fallback",
                        rule_profiles.rule_label(item, mapping, lambda _value: "fallback"),
                        "{0} / {1}".format(category, item),
                    )

    def test_rule_labels_use_selected_language_without_changing_rule_keys(self):
        self.assertEqual("最小Via(过孔)", Language_chinese["smallest drill size"])
        self.assertEqual("最小插件孔", Language_chinese["smallest pth"])
        self.assertEqual("同网络过孔", Language_chinese["same net via spacing"])
        self.assertEqual(
            "网络断连",
            rule_profiles.rule_label("Trace Mssing", Language_chinese),
        )
        self.assertEqual(
            "Trace Missing",
            rule_profiles.rule_label("Trace Mssing", Language_english),
        )
        self.assertEqual(
            "孔厚径比",
            rule_profiles.rule_label("Aspect Ratio", Language_chinese),
        )
        self.assertEqual("孔到铜", Language_chinese["Drill to Copper"])
        self.assertEqual(
            "PTH孔到外层走线", Language_chinese["pth-to-trace [outer]"]
        )
        self.assertEqual(
            "PTH孔到内层走线", Language_chinese["pth-to-trace [inner]"]
        )
        self.assertEqual(
            "过孔到外层走线", Language_chinese["via-to-trace [outer]"]
        )
        self.assertEqual(
            "过孔到内层走线", Language_chinese["via-to-trace [inner]"]
        )
        self.assertEqual("NPTH孔到铜", Language_chinese["npth-to-copper"])

    def test_all_profiles_use_the_supported_drill_to_copper_rules(self):
        expected = {
            "PTH-to-Trace [Outer]": "0.200000,0.250000,999.000000",
            "PTH-to-Trace [Inner]": "0.250000,0.300000,999.000000",
            "Via-to-Trace [Outer]": "0.200000,0.250000,999.000000",
            "Via-to-Trace [Inner]": "0.250000,0.300000,999.000000",
            "NPTH-to-Copper": "0.200000,0.250000,999.000000",
        }

        for profile_id in ("economy", "standard", "precision"):
            actual = {
                rule["item"]: rule["rule"]
                for rule in rule_profiles.rules_for_profile(profile_id)["Drill to Copper"]
            }
            self.assertEqual(expected, actual, profile_id)

    def test_default_selected_profile_is_standard(self):
        self.assertEqual("standard", rule_profiles.selected_profile_id(DEFAULT_SETTINGS))

    def test_only_manufacturing_profiles_are_available(self):
        expected = ("economy", "standard", "precision")
        self.assertEqual(
            expected,
            tuple(rule_profiles.default_profiles()),
        )
        self.assertEqual(expected, tuple(rule_profiles.load_profiles()))
        self.assertEqual(
            expected,
            tuple(profile_id for profile_id, _label in rule_profiles.profile_choices()),
        )
        self.assertEqual(
            "standard",
            rule_profiles.selected_profile_id({"rule_profile": "unsupported"}),
        )

    def test_profile_labels_are_compact_for_the_main_window(self):
        self.assertEqual(
            ("Basic", "Standard", "Advanced"),
            tuple(label for _profile_id, label in rule_profiles.profile_choices()),
        )
        self.assertEqual(
            ("普通工艺", "标准工艺", "高阶工艺"),
            tuple(
                label
                for _profile_id, label in rule_profiles.profile_choices(
                    label_map=Language_chinese
                )
            ),
        )

    def test_profiles_scale_common_minimum_rules(self):
        profiles = rule_profiles.default_profiles()

        economy_width = self.rule_value(profiles, "economy", "Smallest Trace Width")
        standard_width = self.rule_value(profiles, "standard", "Smallest Trace Width")
        precision_width = self.rule_value(profiles, "precision", "Smallest Trace Width")

        self.assertGreater(economy_width, standard_width)
        self.assertLess(precision_width, standard_width)

    def test_profiles_keep_structural_and_defect_rules_fixed(self):
        profiles = rule_profiles.default_profiles()

        fixed_rules = (
            ("Signal Integrity", "Trace Mssing"),
            ("Hole Size", "Largest PTH Size"),
            ("Hole Size", "Aspect Ratio"),
            ("Hole Size", "Smallest Slot Width"),
            ("Hole Size", "Largest Blind/Buried Via"),
            ("Hole Size", "Largest Slot Length"),
            ("Hole Size", "Largest Slot Width"),
            ("Hole Size", "Slot Aspect Ratio"),
            ("Holes on SMD Pads", "Via on BGA Pad"),
            ("Holes on SMD Pads", "Via on SMD Pad"),
            ("Holes on SMD Pads", "NPTH on SMD Pad"),
            ("Holes on SMD Pads", "PTH on SMD Pad"),
            ("Pad size", "Short Pads"),
            ("Pad size", "Long Pads"),
            ("SMD Spacing", "SMD Pad Spacing"),
            ("Solder Mask Analysis", "Solder Mask Bridge"),
            ("Solder Mask Analysis", "Solder Mask Covers Trace"),
        )

        for category, item in fixed_rules:
            rules = {
                profile_id: self.rule_text(profiles, profile_id, category, item)
                for profile_id in ("economy", "standard", "precision")
            }
            self.assertEqual(
                rules["standard"],
                rules["economy"],
                "{0} / {1}".format(category, item),
            )
            self.assertEqual(
                rules["standard"],
                rules["precision"],
                "{0} / {1}".format(category, item),
            )

    def test_loaded_profiles_add_minimum_slot_width_and_remove_square_size(self):
        for profile_id in ("economy", "standard", "precision"):
            items = {
                rule["item"]: rule
                for rule in rule_profiles.rules_for_profile(profile_id)["Hole Size"]
            }
            self.assertEqual(
                "0.450088,0.599948,5.999988",
                items["Smallest Slot Width"]["rule"],
                profile_id,
            )
            self.assertNotIn("Square Hole Size", items, profile_id)
            self.assertEqual(
                "1.500000,2.000000,999.000000",
                items["Slot Aspect Ratio"]["rule"],
                profile_id,
            )

    def test_manufacturing_profiles_use_exact_holes_on_smd_rules(self):
        expected = {
            "Via on BGA Pad": "0.010000,0.010000,0.000000",
            "Via on SMD Pad": "0.150000,0.050000,0.000000",
            "NPTH on SMD Pad": "0.100000,0.010000,0.000000",
            "PTH on SMD Pad": "0.100000,0.050000,0.000000",
        }

        for profile_id in ("economy", "standard", "precision"):
            actual = {
                rule["item"]: rule["rule"]
                for rule in rule_profiles.rules_for_profile(profile_id)["Holes on SMD Pads"]
            }
            self.assertEqual(expected, actual, profile_id)

    def test_holes_on_smd_chinese_labels_name_the_smd_target_first(self):
        self.assertEqual(
            "SMD\u710a\u76d8\u4e0a\u8fc7\u5b54",
            Language_chinese["via on smd pad"],
        )
        self.assertEqual(
            "SMD\u710a\u76d8\u4e0aNPTH\u5b54",
            Language_chinese["npth on smd pad"],
        )
        self.assertEqual(
            "SMD\u710a\u76d8\u4e0aPTH\u5b54",
            Language_chinese["pth on smd pad"],
        )

    def test_solder_mask_rules_match_reference_mil_thresholds(self):
        profiles = rule_profiles.default_profiles()

        self.assertEqual(
            "0.127000,0.152400,0.254000",
            self.rule_text(
                profiles, "standard", "Solder Mask Analysis", "Solder Mask Bridge"
            ),
        )
        self.assertEqual(
            "0.038100,0.050800,0.063500",
            self.rule_text(
                profiles,
                "standard",
                "Solder Mask Analysis",
                "Solder Mask Covers Trace",
            ),
        )
        self.assertEqual(
            "-,-,-",
            self.rule_text(
                profiles,
                "standard",
                "Solder Mask Analysis",
                "Solder Mask Covers Multiple Nets",
            ),
        )

    def test_pad_size_rules_match_reference_mil_thresholds(self):
        profiles = rule_profiles.default_profiles()

        self.assertEqual(
            "0.203200,0.304800,0.508000",
            self.rule_text(profiles, "standard", "Pad size", "Short Pads"),
        )
        self.assertEqual(
            "0.152400,0.177800,0.254000",
            self.rule_text(profiles, "standard", "Pad size", "Long Pads"),
        )

    def test_all_profiles_use_exact_annular_ring_mil_thresholds(self):
        expected = {
            "Via Annular Ring": "0.101600,0.127000,0.152400",
            "PTH Annular Ring": "0.152400,0.177800,0.203200",
        }

        for profile_id in ("economy", "standard", "precision"):
            actual = {
                rule["item"]: rule["rule"]
                for rule in rule_profiles.rules_for_profile(profile_id)["RingHole"]
            }
            self.assertEqual(expected, actual, profile_id)

        rows = build_rule_rows(
            rules_to_result_json(rule_profiles.rules_for_profile("standard")),
            unit=5,
            transform=lambda value: str(round(float(value) / 0.0254, 3)),
        )
        displayed = {
            row[2]: row[3]
            for row in rows
            if row[1] == "RingHole"
        }
        self.assertEqual("4.0,5.0,6.0", displayed["Via Annular Ring"])
        self.assertEqual("6.0,7.0,8.0", displayed["PTH Annular Ring"])

    def test_profiles_scale_key_manufacturing_capabilities(self):
        profiles = rule_profiles.default_profiles()

        scaled_rules = (
            ("Smallest Trace Width", "Smallest Trace Width"),
            ("Smallest Trace Spacing", "Trace Spacing"),
            ("Smallest Trace Spacing", "Pad-to-Pad Spacing"),
            ("Hole Size", "Smallest PTH"),
            ("Copper-to-Board Edge", "Trace-to-Board Edge"),
        )

        for category, item in scaled_rules:
            economy = self.first_rule_value(profiles, "economy", category, item)
            standard = self.first_rule_value(profiles, "standard", category, item)
            precision = self.first_rule_value(profiles, "precision", category, item)
            self.assertGreater(economy, standard, "{0} / {1}".format(category, item))
            self.assertLess(precision, standard, "{0} / {1}".format(category, item))

    def test_hole_to_board_edge_rules_are_fixed_reference_thresholds(self):
        expected = {
            "PTH-to-Board Edge": "0.400050,0.500126,0.599948",
            "Via-to-Board Edge": "0.299974,0.400050,0.500126",
            "Screw Hole-to-Board Edge": "0.400050,0.500126,0.599948",
            "NPTH-to-Board Edge": "0.199898,0.299974,0.400050",
        }
        for profile_id in ("economy", "standard", "precision"):
            actual = {
                rule["item"]: rule["rule"]
                for rule in rule_profiles.rules_for_profile(profile_id)["Hole-to-Board Edge"]
            }
            self.assertEqual(expected, actual, profile_id)

        rows = build_rule_rows(
            rules_to_result_json(rule_profiles.rules_for_profile("standard")),
            unit=5,
            transform=lambda value: str(round(float(value) / 0.0254, 2)),
        )
        displayed = {
            row[2]: row[3]
            for row in rows
            if row[1] == "Hole-to-Board Edge"
        }
        self.assertEqual("15.75,19.69,23.62", displayed["PTH-to-Board Edge"])
        self.assertEqual("11.81,15.75,19.69", displayed["Via-to-Board Edge"])
        self.assertEqual("15.75,19.69,23.62", displayed["Screw Hole-to-Board Edge"])
        self.assertEqual("7.87,11.81,15.75", displayed["NPTH-to-Board Edge"])

    def test_manufacturing_profiles_use_exact_smd_spacing_mil_thresholds(self):
        profiles = rule_profiles.default_profiles()

        for profile_id in ("economy", "standard", "precision"):
            self.assertEqual(
                "0.152400,0.203200,0.254000",
                self.rule_text(
                    profiles,
                    profile_id,
                    "SMD Spacing",
                    "SMD Pad Spacing",
                ),
                profile_id,
            )

    def test_all_profiles_use_exact_different_net_pth_spacing_mil_thresholds(self):
        profiles = rule_profiles.default_profiles()

        for profile_id in ("economy", "standard", "precision"):
            self.assertEqual(
                "0.400050,0.450088,0.500126",
                self.rule_text(
                    profiles,
                    profile_id,
                    "Drill Hole Spacing",
                    "Different Net PTH Spacing",
                ),
                profile_id,
            )

        rows = build_rule_rows(
            rules_to_result_json(rule_profiles.rules_for_profile("standard")),
            unit=5,
            transform=lambda value: str(round(float(value) / 0.0254, 3)),
        )
        displayed = next(
            row[3]
            for row in rows
            if row[1] == "Drill Hole Spacing"
            and row[2] == "Different Net PTH Spacing"
        )
        self.assertEqual("15.75,17.72,19.69", displayed)

    def test_rule_manager_rows_include_new_trace_spacing_items(self):
        rules = rule_profiles.rules_for_profile("standard")
        rows = build_rule_rows(
            rules_to_result_json(rules),
            unit=1,
            transform=lambda value: value,
        )
        sub_items = {
            row[2] for row in rows if row[1] == "Smallest Trace Spacing"
        }

        self.assertIn("Pad-to-Pad Spacing", sub_items)
        self.assertNotIn("Track-to-Copper Spacing", sub_items)
        self.assertIn("BGA Pads", sub_items)
        self.assertNotIn("SMD Pad Spacing", sub_items)
        self.assertEqual(
            {"SMD Pad Spacing"},
            {row[2] for row in rows if row[1] == "SMD Spacing"},
        )
        self.assertNotIn("Pad Spacing", rules)

    def test_rule_manager_keeps_aspect_ratio_dimensionless(self):
        rules = rule_profiles.rules_for_profile("standard")
        rows = build_rule_rows(
            rules_to_result_json(rules),
            unit=5,
            transform=lambda value: str(round(float(value) / 0.0254, 3)),
        )
        aspect = next(
            row
            for row in rows
            if row[1] == "Hole Size" and row[2] == "Aspect Ratio"
        )
        trace = next(
            row
            for row in rows
            if row[1] == "Smallest Trace Width"
            and row[2] == "Smallest Trace Width"
        )

        self.assertEqual("12.000000,10.000000,8.000000", aspect[3])
        self.assertEqual("ratio", aspect[4])
        self.assertEqual("mil", trace[4])
        self.assertNotEqual("0.127000,0.150000,999.000000", trace[3])

    def test_saved_track_to_copper_rule_is_removed(self):
        migrated = rule_profiles.migrate_legacy_rules(
            {
                "Smallest Trace Spacing": (
                    {"item": "Trace Spacing", "rule": "0.111,0.222,999"},
                    {"item": "Track-to-Copper Spacing", "rule": "0.123,0.234,999"},
                )
            }
        )

        items = {
            rule["item"]
            for rule in migrated["Smallest Trace Spacing"]
        }
        self.assertEqual({"Trace Spacing"}, items)

    def test_saved_hatched_copper_category_is_removed(self):
        migrated = rule_profiles.migrate_legacy_rules(
            {
                "Hatched Copper Pour": (
                    {"item": "Grid Width", "rule": "0.111,0.222,999"},
                    {"item": "Grid Spacing", "rule": "0.123,0.234,999"},
                )
            }
        )

        self.assertNotIn("Hatched Copper Pour", migrated)

    def test_saved_via_in_pad_rules_are_removed(self):
        migrated = rule_profiles.migrate_legacy_rules(
            {
                "Special Drill Holes": (
                    {"item": "Square/Rectangular Drills", "rule": "-,-,-"},
                    {"item": "Castellated Holes", "rule": "-,-,-"},
                    {"item": "Via-in-Pad", "rule": "-,-,-"},
                    {"item": "盘中孔", "rule": "-,-,-"},
                )
            }
        )

        self.assertEqual(
            ("Square/Rectangular Drills", "Castellated Holes"),
            tuple(rule["item"] for rule in migrated["Special Drill Holes"]),
        )

    def test_saved_hole_rules_keep_slot_width_and_remove_square_size(self):
        migrated = rule_profiles.migrate_legacy_rules(
            {
                "Hole Size": (
                    {"item": "Smallest Slot Width", "rule": "0.45,0.6,6"},
                    {"item": "Largest Slot Width", "rule": "8,7,6"},
                    {"item": "Slot Aspect Ratio", "rule": "1.5,2,2"},
                    {"item": "Square Hole Size", "rule": "1,2,3"},
                )
            }
        )

        self.assertEqual(
            ("Smallest Slot Width", "Largest Slot Width", "Slot Aspect Ratio"),
            tuple(rule["item"] for rule in migrated["Hole Size"]),
        )
        self.assertEqual(
            "0.450088,0.599948,5.999988",
            migrated["Hole Size"][0]["rule"],
        )
        self.assertEqual(
            "1.500000,2.000000,999.000000",
            migrated["Hole Size"][2]["rule"],
        )

    def test_legacy_hole_diameter_rules_migrate_to_hole_size(self):
        migrated = rule_profiles.migrate_legacy_rules(
            {
                "Hole Diameter": (
                    {"item": "Smallest PTH", "rule": "0.300,0.400,999"},
                )
            }
        )

        self.assertNotIn("Hole Diameter", migrated)
        self.assertEqual("0.300,0.400,999", migrated["Hole Size"][0]["rule"])

    def test_legacy_pad_spacing_rules_migrate_to_canonical_categories(self):
        migrated = rule_profiles.migrate_legacy_rules(
            {
                "Pad Spacing": (
                    {"item": "Pad Spacing", "rule": "0.111,0.222,999"},
                    {"item": "SMD Pad Spacing", "rule": "0.123,0.234,999"},
                )
            }
        )

        self.assertNotIn("Pad Spacing", migrated)
        by_item = {rule["item"]: rule["rule"] for rule in migrated["Smallest Trace Spacing"]}
        self.assertEqual("0.111,0.222,999", by_item["Pad-to-Pad Spacing"])
        self.assertNotIn("SMD Pad Spacing", by_item)
        smd = {rule["item"]: rule["rule"] for rule in migrated["SMD Spacing"]}
        self.assertEqual("0.123,0.234,999", smd["SMD Pad Spacing"])

    def test_explicit_smd_category_overrides_legacy_nested_rule(self):
        migrated = rule_profiles.migrate_legacy_rules(
            {
                "Smallest Trace Spacing": (
                    {"item": "SMD Pad Spacing", "rule": "0.111,0.222,0.333"},
                ),
                "SMD Spacing": (
                    {"item": "SMD Pad Spacing", "rule": "0.1524,0.2032,0.254"},
                ),
            }
        )

        self.assertEqual((), migrated["Smallest Trace Spacing"])
        self.assertEqual(
            "0.1524,0.2032,0.254",
            migrated["SMD Spacing"][0]["rule"],
        )

    def test_update_profile_rules_persists_editable_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "rule_profiles.json")
            original_path = rule_profiles.profiles_path
            rule_profiles.profiles_path = lambda: path
            try:
                rule_profiles.update_profile_rules(
                    "standard",
                    {
                        "Smallest Trace Width": [
                            {"item": "Smallest Trace Width", "rule": "0.200000,0.250000,999.000000"}
                        ]
                    },
                )
                profiles = rule_profiles.load_profiles()
            finally:
                rule_profiles.profiles_path = original_path

        self.assertEqual(0.2, self.rule_value(profiles, "standard", "Smallest Trace Width"))

    def test_configured_rules_override_embedded_analysis_rules(self):
        embedded_rules = {
            "Smallest Trace Width": {
                "_rules": [{"Smallest Trace Width": "0.127000,0.150000,999.000000"}]
            }
        }
        selected_rules = {
            "Smallest Trace Width": (
                {"item": "Smallest Trace Width", "rule": "0.250000,0.300000,999.000000"},
            )
        }

        self.assertEqual(
            "red",
            ColorRule(selected_rules).get_rule(
                embedded_rules, "Smallest Trace Width", "Smallest Trace Width", 0.2
            ),
        )

    def rule_value(self, profiles, profile_id, category):
        rule = profiles[profile_id]["rules"][category][0]["rule"]
        return float(rule.split(",")[0])

    def rule_text(self, profiles, profile_id, category, item):
        for rule in profiles[profile_id]["rules"][category]:
            if rule["item"] == item:
                return rule["rule"]
        self.fail("missing rule: {0} / {1}".format(category, item))

    def first_rule_value(self, profiles, profile_id, category, item):
        return float(self.rule_text(profiles, profile_id, category, item).split(",")[0])


if __name__ == "__main__":
    unittest.main()
