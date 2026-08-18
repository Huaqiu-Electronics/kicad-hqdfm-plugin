import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
import zipfile


VERSIONS = ("6.0", "7.0", "8.0", "9.0", "10.0")
DEFAULT_VIDEO_DIR = r"D:\KiCad\6.0\share\kicad\demos\video"
DEFAULT_BOARD = os.path.join(DEFAULT_VIDEO_DIR, "video.kicad_pcb")
DEFAULT_BACKUP_DIR = os.path.join(DEFAULT_VIDEO_DIR, "video-backups")
MAX_ROWS_PER_CATEGORY = 4
MAX_ROWS_TOTAL = 48


CHECK_SCRIPT = r"""
import json
import os
import sys
import time
import builtins

sys.path.insert(0, os.environ["HQDFM_REPO"])

if not hasattr(builtins, "_"):
    builtins._ = lambda value: value

import pcbnew
import wx

from kicad_dfm import config
from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame
from kicad_dfm.core.rule_profiles import rules_for_profile
from kicad_dfm.kicad.board_loader import load_board_noninteractive
from kicad_dfm.kicad.swig import SwigBackend
from kicad_dfm.services.locate import LocateService, ZOOM_MIN_SPAN_NM
from kicad_dfm.services.offline_analysis import OfflineDfmAnalysis
from kicad_dfm.ui.main_frame import select_language_control


MAX_ROWS_PER_CATEGORY = int(os.environ.get("HQDFM_MAX_ROWS_PER_CATEGORY", "4"))
MAX_ROWS_TOTAL = int(os.environ.get("HQDFM_MAX_ROWS_TOTAL", "48"))
MAX_AVG_LOCATE_MS = float(os.environ.get("HQDFM_MAX_AVG_LOCATE_MS", "250"))
MAX_SINGLE_LOCATE_MS = float(os.environ.get("HQDFM_MAX_SINGLE_LOCATE_MS", "1500"))
MAX_CHILD_FRAME_ROWS_PER_CATEGORY = int(os.environ.get("HQDFM_CHILD_FRAME_ROWS_PER_CATEGORY", "3"))


class DummyEvent:
    def Skip(self):
        pass


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def marker_span(backend, marker):
    bounds = backend.item_bbox(marker)
    assert_true(bounds, "marker has no bounding box")
    left, top, right, bottom = bounds
    return abs(right - left), abs(bottom - top)


def is_selected(item):
    if hasattr(item, "IsSelected"):
        return bool(item.IsSelected())
    return True


def is_brightened(item):
    if hasattr(item, "IsBrightened"):
        return bool(item.IsBrightened())
    return True


def all_rows(result):
    for category, data in sorted(result.kicad_result.items()):
        if not isinstance(data, dict):
            continue
        for check in data.get("check") or ():
            for row in check.get("result") or ():
                yield category, check.get("title", ""), row


def row_items(backend, row):
    items = []
    for key in ("id", "related_id"):
        item_id = row.get(key)
        item = backend.resolve_item(item_id) if item_id else None
        if item is not None:
            items.append(item)
    return items


def row_bbox(row):
    bbox = row.get("bbox_nm")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        return tuple(int(value) for value in bbox)
    return None


def row_point_bbox(row):
    for keys in (("sx", "sy", "ex", "ey"), ("start_x", "start_y", "end_x", "end_y")):
        if all(key in row for key in keys):
            try:
                sx, sy, ex, ey = (int(float(row[key])) for key in keys)
            except (TypeError, ValueError):
                continue
            return (min(sx, ex), min(sy, ey), max(sx, ex), max(sy, ey))
    return None


def usable_row(backend, row):
    if row_items(backend, row):
        return True
    return row_bbox(row) is not None or row_point_bbox(row) is not None


def select_rows(backend, result):
    selected = []
    per_category = {}
    for category, title, row in all_rows(result):
        if len(selected) >= MAX_ROWS_TOTAL:
            break
        if per_category.get(category, 0) >= MAX_ROWS_PER_CATEGORY:
            continue
        if not usable_row(backend, row):
            continue
        selected.append((category, title, row))
        per_category[category] = per_category.get(category, 0) + 1
    return selected


def locate_single_row(board, backend, category, title, row):
    service = LocateService(board, [], [], backend)
    service.begin(defer_focus=True)

    items = row_items(backend, row)
    if items:
        for index, item in enumerate(items):
            service.show_item(item, focus=index == len(items) - 1)
        assert_true(service.item_list, "no selected item tracked for {0}".format(category))
        assert_true(
            len(service.line_list) >= len(items) and len(service.line_list) <= len(items) * 2,
            "target marker count mismatch for {0}".format(category),
        )
        for item in items:
            assert_true(is_selected(item), "item was not selected for {0}".format(category))
            assert_true(is_brightened(item), "item was not brightened for {0}".format(category))
    else:
        bbox = row_bbox(row) or row_point_bbox(row)
        service.show_bbox(bbox)
        assert_true(len(service.line_list) == 1, "bbox marker count mismatch for {0}".format(category))

    assert_true(service._last_focus_bounds is not None, "focus bounds were not remembered for {0}".format(category))
    assert_true(service.flush_focus(), "deferred focus did not flush for {0}".format(category))
    assert_true(not service.defer_focus, "deferred mode was not cleared for {0}".format(category))
    assert_true(service._last_focus_bounds is not None, "focus bounds lost after flush for {0}".format(category))

    focus_marker = service._focus_marker(service._last_focus_bounds)
    assert_true(focus_marker is not None, "focus marker could not be built for {0}".format(category))
    span_x, span_y = marker_span(backend, focus_marker)
    assert_true(
        span_x >= ZOOM_MIN_SPAN_NM and span_y >= ZOOM_MIN_SPAN_NM,
        "focus marker too small for {0}: {1}x{2}".format(category, span_x, span_y),
    )
    assert_true(len(service.line_list) <= max(len(items) * 2, 1), "zoom marker leaked for {0}".format(category))

    assert_true(service.refocus_last(), "refocus replay failed for {0}".format(category))
    assert_true(len(service.line_list) <= max(len(items) * 2, 1), "refocus leaked markers for {0}".format(category))

    service.clear()
    assert_true(not service.item_list, "selected items were not cleared for {0}".format(category))
    assert_true(not service.line_list, "temporary markers were not cleared for {0}".format(category))


def verify_child_frame_rows(board, result, categories):
    app = wx.App.Get() or wx.App(False)
    verified = {}
    for category in sorted(categories):
        data = result.kicad_result.get(category)
        if not isinstance(data, dict) or not data.get("check"):
            continue
        line_list = []
        frame = DfmChildFrame(None, category, result.kicad_result, category, line_list, 1, board, True)
        try:
            count = min(len(frame.result_row_keys), MAX_CHILD_FRAME_ROWS_PER_CATEGORY)
            if count <= 0:
                continue
            for row in range(count):
                key = frame.result_row_keys[row]
                frame.analysis_process(key, DummyEvent())
                assert_true(
                    frame.locate_service._last_focus_bounds is not None,
                    "child frame did not remember focus bounds for {0} row {1}".format(category, row),
                )
                assert_true(
                    frame.locate_service.item_list or frame.locate_service.line_list,
                    "child frame left no selected item or target marker for {0} row {1}".format(category, row),
                )
                assert_true(
                    len(frame.locate_service.focus_markers) <= 1,
                    "child frame leaked focus markers for {0} row {1}".format(category, row),
                )
                frame.locate_service.clear()
                assert_true(not frame.locate_service.item_list, "child frame item clear failed for {0}".format(category))
                assert_true(not frame.locate_service.line_list, "child frame marker clear failed for {0}".format(category))
            verified[category] = count
        finally:
            frame.Destroy()
    assert_true(verified, "no child frame rows were verified")
    app.Yield()
    return verified


board_path = os.environ["HQDFM_BOARD"]
board = load_board_noninteractive(board_path)
assert_true(board is not None, "LoadBoard returned None")

backend = SwigBackend(board)
control = select_language_control("English", config)
result = OfflineDfmAnalysis(
    board,
    control,
    backend=backend,
    rules=rules_for_profile(os.environ.get("HQDFM_RULE_PROFILE", "standard")),
    include_passed_details=False,
).analyze()
rows = select_rows(backend, result)
if len(rows) < 8:
    result = OfflineDfmAnalysis(
        board,
        control,
        backend=backend,
        rules=rules_for_profile(os.environ.get("HQDFM_RULE_PROFILE", "standard")),
        include_passed_details=True,
    ).analyze()
    rows = select_rows(backend, result)

assert_true(rows, "no DFM rows with usable locations were found")

durations = []
categories = {}
for category, title, row in rows:
    started = time.perf_counter()
    locate_single_row(board, backend, category, title, row)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    durations.append(elapsed_ms)
    categories[category] = categories.get(category, 0) + 1
    assert_true(
        elapsed_ms <= MAX_SINGLE_LOCATE_MS,
        "single locate too slow for {0}: {1:.1f}ms".format(category, elapsed_ms),
    )

avg_ms = sum(durations) / len(durations)
assert_true(
    avg_ms <= MAX_AVG_LOCATE_MS,
    "average locate too slow: {0:.1f}ms over {1} rows".format(avg_ms, len(durations)),
)

child_rows = verify_child_frame_rows(board, result, categories)

print(
    json.dumps(
        {
            "version": str(pcbnew.GetBuildVersion()),
            "board": os.path.basename(board_path),
            "rows": len(rows),
            "categories": categories,
            "child_frame_rows": child_rows,
            "avg_ms": round(avg_ms, 2),
            "max_ms": round(max(durations), 2),
        },
        sort_keys=True,
    )
)
"""


def _read_board_header(path, lines=6):
    header = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for _ in range(lines):
            line = handle.readline()
            if not line:
                break
            header.append(line.strip())
    return " ".join(header)


def _extract_video_backup(backup_dir, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    for name in sorted(os.listdir(backup_dir)):
        if not name.lower().endswith(".zip"):
            continue
        zip_path = os.path.join(backup_dir, name)
        with zipfile.ZipFile(zip_path) as archive:
            members = [item for item in archive.namelist() if item.endswith("video.kicad_pcb")]
            if not members:
                continue
            member = members[0]
            target_dir = os.path.join(cache_dir, os.path.splitext(name)[0])
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, "video.kicad_pcb")
            if not os.path.exists(target):
                with archive.open(member) as source, open(target, "wb") as dest:
                    dest.write(source.read())
            return target, zip_path
    return None, None


def _board_is_legacy_compatible(path):
    try:
        header = _read_board_header(path)
    except OSError:
        return False
    return "generator_version" not in header and "version 20211014" in header


def choose_board(args):
    board = os.path.abspath(args.board)
    if args.use_current_board or _board_is_legacy_compatible(board):
        return board, "current"
    backup_dir = os.path.abspath(args.backup_dir)
    extracted, source = _extract_video_backup(backup_dir, os.path.abspath(args.cache_dir))
    if extracted:
        return extracted, source
    return board, "current-incompatible"


def main():
    parser = argparse.ArgumentParser(
        description="Verify real DFM-result row locate/highlight/zoom behavior on installed KiCad versions."
    )
    parser.add_argument("--kicad-root", default=r"D:\KiCad")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--board", default=DEFAULT_BOARD)
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--cache-dir", default=os.path.join(os.getcwd(), ".hqdfm-test", "video"))
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--versions", nargs="*", default=VERSIONS)
    parser.add_argument("--max-rows-per-category", type=int, default=MAX_ROWS_PER_CATEGORY)
    parser.add_argument("--max-rows-total", type=int, default=MAX_ROWS_TOTAL)
    parser.add_argument(
        "--use-current-board",
        action="store_true",
        help="Use --board exactly as passed, even if it appears newer than KiCad 6.",
    )
    args = parser.parse_args()

    compile(textwrap.dedent(CHECK_SCRIPT), "<verify_detail_locate_kicad_versions CHECK_SCRIPT>", "exec")

    board, source = choose_board(args)
    print("board: {0}".format(board))
    print("source: {0}".format(source))

    failures = []
    for version in args.versions:
        python_exe = os.path.join(args.kicad_root, version, "bin", "python.exe")
        if not os.path.exists(python_exe):
            failures.append("{0}: missing {1}".format(version, python_exe))
            continue
        env = os.environ.copy()
        env["KICAD_ROOT"] = os.path.join(args.kicad_root, version)
        env["HQDFM_REPO"] = os.path.abspath(args.repo)
        env["HQDFM_BOARD"] = board
        env["HQDFM_RULE_PROFILE"] = args.profile
        env["HQDFM_MAX_ROWS_PER_CATEGORY"] = str(args.max_rows_per_category)
        env["HQDFM_MAX_ROWS_TOTAL"] = str(args.max_rows_total)
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
