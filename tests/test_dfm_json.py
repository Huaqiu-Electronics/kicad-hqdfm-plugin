import unittest

from kicad_dfm.core.dfm_json import parse_data
from kicad_dfm.core.dfm_json import severity_color


class DfmJsonTest(unittest.TestCase):
    def test_severity_color_treats_missing_measurement_as_not_reportable(self):
        self.assertEqual("black", severity_color("0.2,0.25,999", None))
        self.assertEqual("black", severity_color("0.2,0.25,999", ""))
        self.assertEqual("black", severity_color("bad,0.25,999", "0.1"))

    def test_drill_diameter_remote_alias_maps_to_hole_diameter(self):
        parsed = parse_data(
            {
                "Drill Diameter": {
                    "display": "0.399 mm",
                    "display_inch": "15.7 mil",
                    "check": [
                        {
                            "info": [
                                {
                                    "item": "Smallest Via [mec]",
                                    "rule": "0.190,0.250,999",
                                    "info": [
                                        {
                                            "layer": ["Drl"],
                                            "val": "0.399",
                                            "result": {
                                                "coord": {
                                                    "cx": "1.0",
                                                    "cy": "2.0",
                                                }
                                            },
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }
            }
        )

        self.assertEqual("0.399 mm", parsed.compat["Hole Size"]["display"])
        self.assertEqual("Smallest Via [mec]", parsed.compat["Hole Size"]["check"][0]["result"][0]["item"])

    def test_legacy_remote_pad_spacing_is_merged_and_renamed(self):
        parsed = parse_data(
            {
                "Pad Spacing": {
                    "display": "0.14 mm",
                    "check": [{"info": [{
                        "item": "Pad Spacing",
                        "rule": "0.127,0.150,999",
                        "info": [{"val": "0.14"}],
                    }]}],
                }
            }
        )

        rows = parsed.compat["Smallest Trace Spacing"]["check"][0]["result"]
        self.assertEqual("Pad-to-Pad Spacing", rows[0]["item"])
        self.assertNotIn("Pad Spacing", parsed.compat)

    def test_legacy_nested_smd_rows_move_to_independent_category(self):
        parsed = parse_data(
            {
                "Smallest Trace Spacing": {
                    "display": "0.10 mm",
                    "check": [
                        {
                            "layer": "F.Cu",
                            "info": [
                                {
                                    "item": "Trace Spacing",
                                    "rule": "0.127,0.150,0.254",
                                    "info": [{"val": "0.12"}],
                                },
                                {
                                    "item": "SMD Pad Spacing",
                                    "rule": "0.1524,0.2032,0.254",
                                    "info": [{"val": "0.10"}],
                                },
                            ],
                        }
                    ],
                }
            }
        )

        spacing_rows = parsed.compat["Smallest Trace Spacing"]["check"][0]["result"]
        smd_rows = parsed.compat["SMD Spacing"]["check"][0]["result"]
        self.assertEqual(["Trace Spacing"], [row["item"] for row in spacing_rows])
        self.assertEqual(["SMD Pad Spacing"], [row["item"] for row in smd_rows])
        self.assertEqual(
            {"Smallest Trace Spacing", "SMD Spacing"},
            {
                issue.category
                for issue in parsed.issues
                if issue.item in ("Trace Spacing", "SMD Pad Spacing")
            },
        )

    def test_top_level_smd_pad_spacing_alias_maps_only_to_smd_category(self):
        parsed = parse_data(
            {
                "SMD Pad Spacing": {
                    "display": "0.18 mm",
                    "check": [{"info": [{
                        "item": "SMD Pad Spacing",
                        "rule": "0.1524,0.2032,0.254",
                        "info": [{"val": "0.18"}],
                    }]}],
                }
            }
        )

        self.assertEqual("", parsed.compat["Smallest Trace Spacing"])
        rows = parsed.compat["SMD Spacing"]["check"][0]["result"]
        self.assertEqual("SMD Pad Spacing", rows[0]["item"])

    def test_retired_via_in_pad_is_removed_from_remote_special_drills(self):
        parsed = parse_data(
            {
                "Special Drill Holes": {
                    "display": "2",
                    "check": [
                        {
                            "info": [
                                {
                                    "item": "Via-in-Pad",
                                    "rule": "-,-,-",
                                    "info": [{"val": "1"}],
                                },
                                {
                                    "item": "Castellated Holes",
                                    "rule": "-,-,-",
                                    "info": [{"val": "1"}],
                                },
                            ]
                        }
                    ],
                }
            }
        )

        rows = [
            row
            for group in parsed.compat["Special Drill Holes"]["check"]
            for row in group["result"]
        ]
        self.assertEqual(["Castellated Holes"], [row["item"] for row in rows])
        self.assertEqual(
            ["Castellated Holes"],
            [issue.item for issue in parsed.summary["Special Drill Holes"].issues],
        )


if __name__ == "__main__":
    unittest.main()
