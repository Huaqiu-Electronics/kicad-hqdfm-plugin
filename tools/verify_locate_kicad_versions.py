import argparse
import os
import subprocess
import sys
import textwrap


VERSIONS = ("6.0", "7.0", "8.0", "9.0", "10.0")


CHECK_SCRIPT = r"""
import os
import sys

sys.path.insert(0, os.environ["HQDFM_REPO"])

import pcbnew

from kicad_dfm.kicad.board_loader import load_board_noninteractive
from kicad_dfm.kicad.swig import SwigBackend
from kicad_dfm.services.locate import LocateService, ZOOM_MIN_SPAN_NM


def first_existing(root, paths):
    for relpath in paths:
        path = os.path.join(root, *relpath.split("/"))
        if os.path.exists(path):
            return path
    raise AssertionError("No usable KiCad demo board found")


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def is_true(item, method_name):
    if not hasattr(item, method_name):
        return True
    return bool(getattr(item, method_name)())


def marker_span(backend, marker):
    bounds = backend.item_bbox(marker)
    if not bounds:
        return 0, 0
    left, top, right, bottom = bounds
    return abs(right - left), abs(bottom - top)


root = os.environ["KICAD_ROOT"]
board_path = os.environ.get("HQDFM_BOARD")
if not board_path:
    board_path = first_existing(
        root,
        (
            "share/kicad/demos/flat_hierarchy/flat_hierarchy.kicad_pcb",
            "share/kicad/template/Arduino_Uno/Arduino_Uno.kicad_pcb",
        ),
    )
board = load_board_noninteractive(board_path)
assert_true(board is not None, "LoadBoard returned None")

backend = SwigBackend(board)
version = backend.version()
items = []

for track in backend.iter_tracks():
    items.append(track)
    break

for footprint in backend.iter_footprints():
    for pad in backend.iter_pads(footprint):
        items.append(pad)
        break
    if items:
        break

assert_true(items, "No selectable board items found")

for item in items[:2]:
    item_id = backend.item_id(item)
    assert_true(item_id and "Swig Object" not in item_id, "Invalid UUID text: {0}".format(item_id))

    resolved = backend.resolve_item(item_id)
    assert_true(resolved is not None, "Could not resolve item id {0}".format(item_id))
    assert_true(backend.item_id(resolved) == item_id, "Resolved item id mismatch")

    service = LocateService(board, [], [], backend)
    shown = service.show_item(item, focus=False)
    assert_true(shown is not None, "show_item returned None")
    assert_true(len(service.item_list) == 1, "Selected item was not tracked")
    assert_true(1 <= len(service.line_list) <= 2, "Only editable target markers should remain")
    target_x, target_y = marker_span(backend, service.line_list[0])
    assert_true(target_x > 0 and target_y > 0, "Temporary target marker is empty")
    focus_marker = service._focus_marker(backend.item_bbox(service.line_list[0]))
    assert_true(focus_marker is not None, "Temporary zoom marker could not be built")
    span_x, span_y = marker_span(backend, focus_marker)
    assert_true(
        span_x >= ZOOM_MIN_SPAN_NM and span_y >= ZOOM_MIN_SPAN_NM,
        "Temporary marker is too small for clear zoom: {0}x{1}".format(span_x, span_y),
    )
    assert_true(is_true(item, "IsSelected"), "Item was not selected")
    assert_true(is_true(item, "IsBrightened"), "Item was not brightened")
    assert_true(service.focus_marker_for_item(item), "First refocus did not use a marker")
    assert_true(service.focus_marker_for_item(item), "Second refocus did not use a fresh marker")
    assert_true(service.refocus_last(), "Final refocus did not replay the last zoom request")
    assert_true(1 <= len(service.line_list) <= 2, "Refocus should not leave zoom markers behind")

    service.clear()
    assert_true(len(service.item_list) == 0, "Selected item list was not cleared")
    assert_true(len(service.line_list) == 0, "Temporary marker list was not cleared")

service = LocateService(board, [], [], backend)
bbox_marker = service.show_bbox((0, 0, 100000, 100000))
assert_true(bbox_marker is not None, "show_bbox returned None")
assert_true(len(service.line_list) == 1, "Only the editable bbox target marker should remain")
target_x, target_y = marker_span(backend, bbox_marker)
assert_true(target_x > 0 and target_y > 0, "BBox target marker is empty")
focus_marker = service._focus_marker((0, 0, 100000, 100000))
assert_true(focus_marker is not None, "BBox zoom marker could not be built")
span_x, span_y = marker_span(backend, focus_marker)
assert_true(
    span_x >= ZOOM_MIN_SPAN_NM and span_y >= ZOOM_MIN_SPAN_NM,
    "BBox marker is too small for clear zoom: {0}x{1}".format(span_x, span_y),
)
service.clear()

service = LocateService(board, [], [], backend)
service.begin(defer_focus=True)
deferred = service.show_item(items[0])
assert_true(deferred is not None, "Deferred show_item returned None")
assert_true(service._last_focus_bounds is not None, "Deferred locate did not remember focus bounds")
assert_true(1 <= len(service.line_list) <= 2, "Deferred locate should keep only editable target markers")
assert_true(service.flush_focus(), "Deferred locate did not flush a final zoom")
assert_true(not service.defer_focus, "flush_focus did not leave deferred mode")
assert_true(1 <= len(service.line_list) <= 2, "flush_focus should not leave zoom markers behind")
service.clear()

print("{0}: ok ({1})".format(version, os.path.basename(board_path)))
"""


def main():
    parser = argparse.ArgumentParser(
        description="Verify DFM locate selection/highlight behavior on installed KiCad versions."
    )
    parser.add_argument("--kicad-root", default=r"D:\KiCad")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--board", default="")
    parser.add_argument("--versions", nargs="*", default=VERSIONS)
    args = parser.parse_args()

    failures = []
    for version in args.versions:
        python_exe = os.path.join(args.kicad_root, version, "bin", "python.exe")
        if not os.path.exists(python_exe):
            failures.append("{0}: missing {1}".format(version, python_exe))
            continue
        env = os.environ.copy()
        env["KICAD_ROOT"] = os.path.join(args.kicad_root, version)
        env["HQDFM_REPO"] = os.path.abspath(args.repo)
        if args.board:
            env["HQDFM_BOARD"] = os.path.abspath(args.board)
        result = subprocess.run(
            [python_exe, "-c", textwrap.dedent(CHECK_SCRIPT)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
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
