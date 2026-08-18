import gettext
import os
import unittest
from unittest import mock

from kicad_dfm.child_frame import rule_guidance
from kicad_dfm.core.rule_catalog import RULE_CATALOG
from kicad_dfm.core.rule_contract import rule_key


class RuleGuidanceTest(unittest.TestCase):
    def translated_as_english(self):
        return mock.patch.object(rule_guidance, "_", side_effect=lambda message: message)

    def test_current_rule_is_converted_to_active_display_unit(self):
        result = {
            "item": "Smallest Trace Width",
            "rule_key": rule_key("Smallest Trace Width", "Smallest Trace Width"),
            "rule": "0.127000,0.150000,999.000000",
        }

        with self.translated_as_english():
            label = rule_guidance.current_rule_text(
                "Smallest Trace Width", result, unit_mode=5
            )
            guidance = rule_guidance.current_rule_guidance(
                "Smallest Trace Width", result, unit_mode=5
            )

        self.assertEqual("Rule: 5, 5.906, ∞ mil", label)
        self.assertIn("Values below 5 mil are high risk", guidance)
        self.assertIn("5.906 mil or greater", guidance)

    def test_rule_display_uses_the_result_rule_not_catalog_default(self):
        result = {
            "item": "Trace Spacing",
            "rule_key": rule_key("Smallest Trace Spacing", "Trace Spacing"),
            "rule": "0.200000,0.300000,0.400000",
        }

        with self.translated_as_english():
            label = rule_guidance.current_rule_text(
                "Smallest Trace Spacing", result, unit_mode=1
            )

        self.assertEqual("Rule: 0.2, 0.3, 0.4 mm", label)

    def test_maximum_sentinel_does_not_create_an_infinite_alarm_sentence(self):
        result = {
            "item": "Largest Drill Size",
            "rule_key": rule_key("Hole Size", "Largest Drill Size"),
            "rule": "999.000000,6.300000,6.000000",
        }

        with self.translated_as_english():
            guidance = rule_guidance.current_rule_guidance(
                "Hole Size", result, unit_mode=1
            )

        self.assertNotIn("above ∞", guidance)
        self.assertIn("6.3 mm or less", guidance)

    def test_description_only_and_boolean_rules_have_specific_recommendations(self):
        ratio_result = {
            "item": "Slot Aspect Ratio",
            "rule_key": rule_key("Hole Size", "Slot Aspect Ratio"),
            "rule": "1.500000,2.000000,2.000000",
        }
        boolean_result = {
            "item": "Castellated Holes",
            "rule_key": rule_key("Special Drill Holes", "Castellated Holes"),
            "rule": "-,-,-",
        }

        with self.translated_as_english():
            ratio_guidance = rule_guidance.current_rule_guidance(
                "Hole Size", ratio_result, unit_mode=1
            )
            boolean_label = rule_guidance.current_rule_text(
                "Special Drill Holes", boolean_result, unit_mode=1
            )
            boolean_guidance = rule_guidance.current_rule_guidance(
                "Special Drill Holes", boolean_result, unit_mode=1
            )

        self.assertIn("at least twice the width", ratio_guidance)
        self.assertEqual("Rule: qualitative check", boolean_label)
        self.assertIn("qualitative check", boolean_guidance)

    def test_stable_rule_key_finds_metadata_when_item_text_is_localized(self):
        result = {
            "item": "鏈€灏忕嚎瀹?",
            "rule_key": rule_key("Smallest Trace Width", "Smallest Trace Width"),
        }

        metadata = rule_guidance.rule_metadata("Smallest Trace Width", result)

        self.assertEqual("Smallest Trace Width", metadata["item"])

    def test_every_catalog_description_has_a_chinese_gettext_translation(self):
        locale_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "kicad_dfm",
            "language",
            "locale",
        )
        translation = gettext.translation(
            "kicad_hqdfm_plugin",
            locale_dir,
            languages=["zh_CN"],
        )

        missing = [
            metadata["description"]
            for entries in RULE_CATALOG.values()
            for metadata in entries
            if translation.gettext(metadata["description"]) == metadata["description"]
        ]

        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
