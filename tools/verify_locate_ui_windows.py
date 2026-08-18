import argparse
import os
import subprocess
import sys
import textwrap
import zipfile


VERSIONS = ("6.0", "7.0", "8.0", "9.0", "10.0")
DEFAULT_VIDEO_DIR = r"D:\KiCad\6.0\share\kicad\demos\video"
DEFAULT_BOARD = os.path.join(DEFAULT_VIDEO_DIR, "video.kicad_pcb")
DEFAULT_BACKUP_DIR = os.path.join(DEFAULT_VIDEO_DIR, "video-backups")
MAX_CATEGORIES = 5
MAX_ROWS_PER_CATEGORY = 3


CHECK_SCRIPT = r"""
import builtins
import json
import os
import sys
import time

sys.path.insert(0, os.environ["HQDFM_REPO"])

if not hasattr(builtins, "_"):
    builtins._ = lambda value: value

import pcbnew
import wx

from kicad_dfm import config
from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame
from kicad_dfm.core.rule_profiles import rules_for_profile
import kicad_dfm.dfm_mainframe as mainframe_module
from kicad_dfm.dfm_mainframe import DfmMainframe
from kicad_dfm.kicad.board_loader import load_board_noninteractive
from kicad_dfm.kicad.swig import SwigBackend
from kicad_dfm.services.offline_analysis import OfflineDfmAnalysis
from kicad_dfm.ui.main_frame import select_language_control
from kicad_dfm.core.settings import DEFAULT_SETTINGS


MAX_CATEGORIES = int(os.environ.get("HQDFM_MAX_CATEGORIES", "5"))
MAX_ROWS_PER_CATEGORY = int(os.environ.get("HQDFM_MAX_ROWS_PER_CATEGORY", "3"))


class DummyEvent:
    def __init__(self):
        self.skipped = False

    def Skip(self):
        self.skipped = True


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def row_has_location(row, backend):
    for key in ("id", "related_id"):
        item_id = row.get(key)
        if item_id and backend.resolve_item(item_id) is not None:
            return True
    if row.get("bbox_nm"):
        return True
    for keys in (("sx", "sy", "ex", "ey"), ("start_x", "start_y", "end_x", "end_y")):
        if all(key in row for key in keys):
            return True
    return False


def categories_with_locations(result, backend):
    selected = []
    for category, data in sorted(result.kicad_result.items()):
        if len(selected) >= MAX_CATEGORIES:
            break
        if not isinstance(data, dict):
            continue
        for check in data.get("check") or ():
            rows = [row for row in check.get("result") or () if row_has_location(row, backend)]
            if rows:
                selected.append(category)
                break
    return selected


def assert_cleared(frame, category):
    service = frame.locate_service
    assert_true(not service.item_list, "item_list was not cleared for {0}".format(category))
    assert_true(not service.line_list, "line_list was not cleared for {0}".format(category))
    assert_true(not service.focus_markers, "focus_markers were not cleared for {0}".format(category))


def first_board_item_id(board):
    candidates = []
    if hasattr(board, "GetTracks"):
        candidates.extend(list(board.GetTracks()))
    if hasattr(board, "GetFootprints"):
        for footprint in board.GetFootprints():
            if hasattr(footprint, "Pads"):
                candidates.extend(list(footprint.Pads()))
    for item in candidates:
        for attr in ("m_Uuid",):
            uuid = getattr(item, attr, None)
            if uuid is not None and hasattr(uuid, "AsString"):
                value = uuid.AsString()
                if value:
                    return value
        if hasattr(item, "GetUuid"):
            uuid = item.GetUuid()
            if hasattr(uuid, "AsString"):
                value = uuid.AsString()
                if value:
                    return value
    return ""


def synthetic_marker_result(item_id):
    return {
        "Smallest Trace Width": {
            "check": [
                {
                    "result": [
                        {
                            "item": "Trace Width",
                            "id": item_id,
                            "source": "kicad",
                            "geometry_basis": "exact_kicad",
                        }
                    ]
                }
            ]
        }
    }


def verify_native_marker_auto_sync(main_window, board, backend):
    can_native_marker = bool(getattr(backend.capabilities(), "can_native_drc_marker", False))
    assert_true(
        main_window.supports_native_drc_marker_auto_sync() == can_native_marker,
        "main window native marker support does not match backend capabilities",
    )
    item_id = first_board_item_id(board)
    assert_true(item_id, "no board item UUID available for native DRC marker verification")
    main_window.analysis_result = {}
    main_window.kicad_result = synthetic_marker_result(item_id)
    exported, skipped = main_window.sync_native_drc_markers()
    if can_native_marker:
        assert_true(exported > 0, "native DRC marker auto sync exported no markers; skipped={0}".format(skipped))
    else:
        assert_true(exported == 0, "native DRC marker auto sync should be disabled on this KiCad version")
        assert_true(skipped == 0, "disabled native DRC marker auto sync should not skip rows")
    cleared = main_window.clear_native_drc_markers()
    assert_true(cleared == exported, "native DRC marker clear count mismatch: {0} != {1}".format(cleared, exported))


def locate_frame_rows(board, result, categories):
    verified = {}
    durations = []
    for category in categories:
        line_list = []
        frame = DfmChildFrame(None, category, result.kicad_result, category, line_list, 1, board, True)
        try:
            count = min(len(frame.result_row_keys), MAX_ROWS_PER_CATEGORY)
            if count <= 0:
                continue
            verified_rows = 0
            for row_index in range(count):
                key = frame.result_row_keys[row_index]
                event = DummyEvent()
                started = time.perf_counter()
                frame.analysis_process(key, event)
                wx.Yield()
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                service = frame.locate_service
                assert_true(event.skipped, "analysis_process did not skip event for {0}".format(category))
                assert_true(
                    service.item_list or service.line_list,
                    "row left no located items or markers for {0} row {1}".format(category, row_index),
                )
                assert_true(service._last_focus_bounds is not None, "missing focus bounds for {0}".format(category))
                assert_true(
                    len(service.item_list) <= 40,
                    "item_list grew unexpectedly for {0}".format(category),
                )
                assert_true(
                    len(service.line_list) <= 40,
                    "line_list grew unexpectedly for {0}".format(category),
                )
                durations.append(elapsed_ms)
                verified_rows += 1
                service.clear()
                assert_cleared(frame, category)
            verified[category] = verified_rows
        finally:
            frame.Destroy()
    return verified, durations


board_path = os.environ["HQDFM_BOARD"]
board = load_board_noninteractive(board_path)
assert_true(board is not None, "LoadBoard returned None")
pcbnew.GetBoard = lambda: board

app = wx.App.Get() or wx.App(False)
backend = SwigBackend(board)
result = OfflineDfmAnalysis(
    board,
    select_language_control("English", config),
    backend=backend,
    rules=rules_for_profile(os.environ.get("HQDFM_RULE_PROFILE", "standard")),
    include_passed_details=True,
).analyze()

mainframe_module.load_ui_settings = lambda: DEFAULT_SETTINGS.copy()
main_window = DfmMainframe(None)
try:
    main_window.analysis_result = result.analysis_result
    main_window.kicad_result = result.kicad_result
    assert_true(
        not hasattr(main_window.dfm_maindialog, "inject_native_drc_markers_button"),
        "main window still exposes native DRC marker inject button",
    )
    assert_true(
        not hasattr(main_window.dfm_maindialog, "clear_native_drc_markers_button"),
        "main window still exposes native DRC marker clear button",
    )
    verify_native_marker_auto_sync(main_window, board, backend)
finally:
    main_window.Destroy()

categories = categories_with_locations(result, backend)
assert_true(categories, "no categories with locatable rows found")
verified, durations = locate_frame_rows(board, result, categories)
assert_true(verified, "no UI rows were verified")

print(
    json.dumps(
        {
            "version": str(pcbnew.GetBuildVersion()) if hasattr(pcbnew, "GetBuildVersion") else backend.version(),
            "board": os.path.basename(board_path),
            "categories": verified,
            "rows": sum(verified.values()),
            "avg_ms": round(sum(durations) / len(durations), 2) if durations else 0,
            "max_ms": round(max(durations), 2) if durations else 0,
        },
        sort_keys=True,
    )
)
app.Destroy()
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
            target_dir = os.path.join(cache_dir, os.path.splitext(name)[0])
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, "video.kicad_pcb")
            if not os.path.exists(target):
                with archive.open(members[0]) as source, open(target, "wb") as dest:
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
        description="Verify DfmChildFrame locate UI interactions on installed KiCad versions."
    )
    parser.add_argument("--kicad-root", default=r"D:\KiCad")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--board", default=DEFAULT_BOARD)
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--cache-dir", default=os.path.join(os.getcwd(), ".hqdfm-test", "video"))
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--versions", nargs="*", default=VERSIONS)
    parser.add_argument("--max-categories", type=int, default=MAX_CATEGORIES)
    parser.add_argument("--max-rows-per-category", type=int, default=MAX_ROWS_PER_CATEGORY)
    parser.add_argument(
        "--use-current-board",
        action="store_true",
        help="Use --board exactly as passed, even if it appears newer than KiCad 6.",
    )
    args = parser.parse_args()

    compile(textwrap.dedent(CHECK_SCRIPT), "<verify_locate_ui_windows CHECK_SCRIPT>", "exec")

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
        env["HQDFM_MAX_CATEGORIES"] = str(args.max_categories)
        env["HQDFM_MAX_ROWS_PER_CATEGORY"] = str(args.max_rows_per_category)
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
