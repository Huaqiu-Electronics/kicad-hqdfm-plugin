import argparse
import os
import subprocess
import sys
import textwrap


VERSIONS = ("6.0", "7.0", "8.0", "9.0", "10.0")


CHECK_SCRIPT = r"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.environ["HQDFM_REPO"])

import pcbnew

from kicad_dfm.kicad.board_loader import load_board_noninteractive
from kicad_dfm.kicad.swig import SwigBackend
from kicad_dfm.services.locate import LocatePlan
from kicad_dfm.services.native_drc import NativeDrcMarkerExporter
from kicad_dfm.services.native_drc import NATIVE_DRC_CATEGORY_KEYS


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def first_board_item(backend):
    for track in backend.iter_tracks():
        return track
    for footprint in backend.iter_footprints():
        for pad in backend.iter_pads(footprint):
            return pad
        return footprint
    for drawing in backend.iter_drawings():
        return drawing
    return None


def marker_factory():
    if hasattr(pcbnew.PCB_MARKER, "DeserializeFromString"):
        return "DeserializeFromString", pcbnew.PCB_MARKER.DeserializeFromString
    if hasattr(pcbnew.PCB_MARKER, "Deserialize"):
        return "Deserialize", pcbnew.PCB_MARKER.Deserialize
    if hasattr(pcbnew, "PCB_MARKER_Deserialize"):
        return "PCB_MARKER_Deserialize", pcbnew.PCB_MARKER_Deserialize
    return None, None


def marker_count(board):
    if hasattr(board, "Markers"):
        return len(list(board.Markers()))
    count = 0
    for drawing in board.GetDrawings():
        if hasattr(pcbnew, "PCB_MARKER_ClassOf") and pcbnew.PCB_MARKER_ClassOf(drawing):
            count += 1
    return count


def write_drc_report(board, path):
    units = getattr(pcbnew, "EDA_UNITS_MILLIMETRES", None)
    if units is None:
        units = getattr(pcbnew, "MILLIMETRES", None)
    if units is None:
        units = 0
    return pcbnew.WriteDRCReport(board, path, units, True)


board_path = os.environ["HQDFM_BOARD"]
board = load_board_noninteractive(board_path)
assert_true(board is not None, "LoadBoard returned None")

backend = SwigBackend(board)
item = first_board_item(backend)
assert_true(item is not None, "No board item found for marker POC")

item_id = backend.item_id(item)
assert_true(item_id, "Could not read item UUID")

factory_name, factory = marker_factory()
assert_true(factory is not None, "No PCB_MARKER deserialize factory is available")

before = marker_count(board)
categories = {}
first_marker = None
rc_text = ""
severity = None
report_path = ""

for category in sorted(NATIVE_DRC_CATEGORY_KEYS):
    payloads = []

    def tracked_factory(payload):
        marker = factory(payload)
        if marker is not None:
            payloads.append(payload)
        return marker

    exporter = NativeDrcMarkerExporter(board, backend=backend, marker_factory=tracked_factory)
    before_category = marker_count(board)
    result = exporter.export(LocatePlan(items=[item]), category=category)
    assert_true(
        result.markers,
        "NativeDrcMarkerExporter did not create a marker for {0}; skipped={1}".format(category, len(result.skipped)),
    )
    after_add_category = marker_count(board)
    assert_true(
        after_add_category >= before_category + 1,
        "Marker count did not increase after board.Add for {0}".format(category),
    )
    payload = payloads[-1] if payloads else ""
    marker_key = payload.split("|", 1)[0] if payload else ""
    categories[category] = {
        "marker_key": marker_key,
        "payload": payload,
    }
    if first_marker is None:
        first_marker = result.markers[0]
        if hasattr(first_marker, "GetRCItem"):
            rc_item = first_marker.GetRCItem()
            if rc_item is not None and hasattr(rc_item, "GetErrorMessage"):
                rc_text = str(rc_item.GetErrorMessage(True))
        if hasattr(first_marker, "GetSeverity"):
            try:
                severity = int(first_marker.GetSeverity())
            except (TypeError, ValueError):
                severity = str(first_marker.GetSeverity())
        if os.environ.get("HQDFM_WRITE_DRC_REPORT") == "1":
            report_path = os.path.join(tempfile.gettempdir(), "hqdfm-native-drc-marker-{0}.rpt".format(os.getpid()))
            ok = write_drc_report(board, report_path)
            assert_true(ok, "WriteDRCReport returned False")
            with open(report_path, "r", encoding="utf-8", errors="replace") as handle:
                report_text = handle.read()
            assert_true("DRC violations" in report_text, "DRC report does not look valid")
            assert_true(
                "Warning" in report_text
                or "warning" in report_text
                or "Track width" in report_text
                or "Clearance" in report_text,
                "DRC report did not include marker text",
            )
    exporter.clear()
    after_clear_category = marker_count(board)
    assert_true(
        after_clear_category <= before_category,
        "Marker count did not return to baseline after clear for {0}".format(category),
    )

after_delete = marker_count(board)
assert_true(after_delete <= before, "Marker count did not return to baseline after board.Delete")

print(json.dumps({
    "version": str(pcbnew.GetBuildVersion()) if hasattr(pcbnew, "GetBuildVersion") else backend.version(),
    "factory": factory_name,
    "categories": categories,
    "item_id": item_id,
    "marker_count_before": before,
    "marker_count_after_delete": after_delete,
    "rc_text": rc_text,
    "severity": severity,
    "report_path": report_path,
}, sort_keys=True))
"""


def _board_is_usable(path):
    return bool(path and os.path.exists(path))


def main():
    parser = argparse.ArgumentParser(
        description="Verify whether Python can inject native KiCad DRC markers across KiCad versions."
    )
    parser.add_argument("--kicad-root", default=r"D:\KiCad")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument(
        "--board",
        default=r"D:\KiCad\6.0\share\kicad\demos\video\video.kicad_pcb",
    )
    parser.add_argument("--versions", nargs="*", default=VERSIONS)
    parser.add_argument(
        "--write-drc-report",
        action="store_true",
        help="Also call pcbnew.WriteDRCReport after adding the marker. This can be slow.",
    )
    args = parser.parse_args()

    compile(textwrap.dedent(CHECK_SCRIPT), "<verify_native_drc_marker CHECK_SCRIPT>", "exec")

    board = os.path.abspath(args.board)
    if not _board_is_usable(board):
        print("missing board: {0}".format(board), file=sys.stderr)
        return 1

    failures = []
    for version in args.versions:
        python_exe = os.path.join(args.kicad_root, version, "bin", "python.exe")
        if not os.path.exists(python_exe):
            failures.append("{0}: missing {1}".format(version, python_exe))
            continue
        env = os.environ.copy()
        env["HQDFM_REPO"] = os.path.abspath(args.repo)
        env["HQDFM_BOARD"] = board
        if args.write_drc_report:
            env["HQDFM_WRITE_DRC_REPORT"] = "1"
        result = subprocess.run(
            [python_exe, "-c", textwrap.dedent(CHECK_SCRIPT)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        sys.stdout.write("{0}: ".format(version))
        sys.stdout.write(result.stdout)
        if result.returncode != 0:
            failures.append("{0}: failed with exit code {1}".format(version, result.returncode))

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
