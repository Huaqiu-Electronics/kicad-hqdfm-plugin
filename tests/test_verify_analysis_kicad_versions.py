import importlib.util
import pathlib
import unittest


SCRIPT_PATH = (
    pathlib.Path(__file__).parents[1]
    / "tools"
    / "verify_analysis_kicad_versions.py"
)
SPEC = importlib.util.spec_from_file_location("verify_analysis_kicad_versions", SCRIPT_PATH)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class VerifyAnalysisOutputTest(unittest.TestCase):
    def test_extracts_json_summary_amid_swig_warnings(self):
        output = "\n".join(
            (
                "swig/python detected a memory leak",
                '{"summary": {"Hole Size": {"count": 2}}, "version": "6.0"}',
                "swig/python detected another memory leak",
            )
        )

        payload = VERIFY.parse_check_output(output)

        self.assertEqual("6.0", payload["version"])
        self.assertEqual(2, payload["summary"]["Hole Size"]["count"])

    def test_extracts_json_when_swig_warning_shares_the_same_line(self):
        payload = VERIFY.parse_check_output(
            'swig warning: {"summary": {}, "version": "6.0"} trailing warning'
        )

        self.assertEqual("6.0", payload["version"])

    def test_rejects_output_without_summary_payload(self):
        with self.assertRaisesRegex(ValueError, "no JSON summary"):
            VERIFY.parse_check_output('warning\n{"version": "6.0"}')


if __name__ == "__main__":
    unittest.main()
