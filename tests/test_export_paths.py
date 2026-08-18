import os
import tempfile
import unittest
import zipfile
from unittest import mock

from kicad_dfm.core.models import OutputDirResult
from kicad_dfm.services import export
from kicad_dfm.services.export import export_gerber, gerber_output_dir


class ExportPathTest(unittest.TestCase):
    def test_gerber_output_dir_is_hqdmf_under_pcb_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = gerber_output_dir(tmpdir)

        self.assertEqual(os.path.join(tmpdir, "HQDMF"), output_dir)

    def test_export_gerber_cleans_nested_old_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "HQDMF")
            os.makedirs(os.path.join(output_dir, "old"))
            old_path = os.path.join(output_dir, "old", "stale.gbr")
            with open(old_path, "w", encoding="utf-8") as fp:
                fp.write("stale")

            export_gerber(FakeExportBackend(), output_dir, layer_count=2)

            self.assertFalse(os.path.exists(old_path))
            self.assertFalse(os.path.exists(os.path.join(output_dir, "old")))

    def test_fabrication_package_uses_board_named_gerber_subdir_and_zip_in_hqdmf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hqdmf_dir = OutputDirResult(os.path.join(tmpdir, "HQDMF"))
            board = FakeBoard(os.path.join(tmpdir, "demo board.kicad_pcb"))
            with mock.patch.object(export, "SwigBackend", return_value=FakeExportBackend()):
                result = export.export_fabrication_package(board, hqdmf_dir)

            expected_dir = os.path.join(tmpdir, "HQDMF", "Gerber_demo board")
            expected_zip = os.path.join(tmpdir, "HQDMF", "Gerber_demo board.zip")

            self.assertEqual(expected_dir, result.output_dir)
            self.assertEqual(expected_zip, result.zip_path)
            self.assertTrue(os.path.isfile(expected_zip))
            self.assertTrue(all(path.startswith(expected_dir) for path in result.files))
            with zipfile.ZipFile(expected_zip, "r") as archive:
                names = archive.namelist()
            self.assertTrue(names)
            self.assertFalse(any("\\" in name for name in names))


class FakePlotController:
    def __init__(self, output_dir):
        self.output_dir = output_dir

    def ClosePlot(self):
        pass


class FakeExportBackend:
    def copper_layer_count(self):
        return 2

    def layer_constant(self, name):
        return name

    def create_plot_controller(self, output_dir):
        return FakePlotController(output_dir)

    def plot_gerber_layer(self, plot_controller, layer_info):
        path = os.path.join(plot_controller.output_dir, "{0}.gbr".format(layer_info[0]))
        with open(path, "w", encoding="utf-8") as fp:
            fp.write("new")

    def export_drill(self, output_dir):
        with open(os.path.join(output_dir, "board.drl"), "w", encoding="utf-8") as fp:
            fp.write("M48\nMETRIC,TZ\nT01C0.800\n%\nT01\nX000000Y000000\nM30\n")
        with open(os.path.join(output_dir, "drill-map.map"), "w", encoding="utf-8") as fp:
            fp.write("map\n")


class FakeBoard:
    def __init__(self, filename):
        self.filename = filename

    def GetFileName(self):
        return self.filename


if __name__ == "__main__":
    unittest.main()
