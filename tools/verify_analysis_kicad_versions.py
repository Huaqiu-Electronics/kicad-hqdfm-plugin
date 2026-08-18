import argparse
import json
import os
import subprocess
import sys
import textwrap
import zipfile


VERSIONS = ("6.0", "7.0", "8.0", "9.0", "10.0")
DEFAULT_VIDEO_DIR = r"D:\KiCad\6.0\share\kicad\demos\video"
DEFAULT_BOARD = os.path.join(DEFAULT_VIDEO_DIR, "video.kicad_pcb")
DEFAULT_BACKUP_DIR = os.path.join(DEFAULT_VIDEO_DIR, "video-backups")
LOCAL_CATEGORIES = (
    "Smallest Trace Width",
    "Smallest Trace Spacing",
    "SMD Spacing",
    "Pad size",
    "Hole Size",
    "RingHole",
    "Drill Hole Spacing",
    "Drill to Copper",
    "Copper-to-Board Edge",
    "Hole-to-Board Edge",
    "Special Drill Holes",
    "Holes on SMD Pads",
)


def comparable_summary(summary):
    return {
        category: {
            "display": data.get("display", ""),
            "count": data.get("count", 0),
            "color": data.get("color", ""),
        }
        for category, data in summary.items()
    }


def parse_check_output(output):
    """Extract the JSON result from noisy KiCad/SWIG standard output."""
    decoder = json.JSONDecoder()
    text = str(output or "")
    for offset, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[offset:])
        except ValueError:
            continue
        if isinstance(payload, dict) and "summary" in payload:
            return payload
    raise ValueError("KiCad verification produced no JSON summary")


CHECK_SCRIPT = r"""
import json
import os
import sys

sys.path.insert(0, os.environ["HQDFM_REPO"])

import pcbnew

from kicad_dfm.core.rule_profiles import rules_for_profile
from kicad_dfm.kicad.board_loader import load_board_noninteractive
from kicad_dfm.services.offline_analysis import OfflineDfmAnalysis
from kicad_dfm.ui.main_frame import select_language_control
from kicad_dfm import config


LOCAL_CATEGORIES = (
    "Smallest Trace Width",
    "Smallest Trace Spacing",
    "SMD Spacing",
    "Pad size",
    "Hole Size",
    "RingHole",
    "Drill Hole Spacing",
    "Drill to Copper",
    "Copper-to-Board Edge",
    "Hole-to-Board Edge",
    "Special Drill Holes",
    "Holes on SMD Pads",
)


def summarize(result):
    summary = {}
    for category in LOCAL_CATEGORIES:
        data = result.kicad_result.get(category)
        if not isinstance(data, dict):
            summary[category] = {"display": "", "count": 0, "color": ""}
            continue
        checks = data.get("check") or []
        active_rule = ""
        for check in checks:
            results = check.get("result") or []
            if results:
                active_rule = results[0].get("rule", "")
                break
        summary[category] = {
            "display": str(data.get("display", "")),
            "count": sum(len(check.get("result") or []) for check in checks),
            "color": data.get("color", ""),
            "rule": active_rule,
        }
    return summary


board = load_board_noninteractive(os.environ["HQDFM_BOARD"])
if board is None:
    raise AssertionError("LoadBoard returned None")
control = select_language_control("English", config)
profile_id = os.environ.get("HQDFM_RULE_PROFILE", "standard")
result = OfflineDfmAnalysis(
    board,
    control,
    rules=rules_for_profile(profile_id),
    include_passed_details=True,
).analyze()
print(
    json.dumps(
        {"version": str(pcbnew.GetBuildVersion()), "summary": summarize(result)},
        sort_keys=True,
    ),
    flush=True,
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
    extracted, source = _extract_video_backup(
        os.path.abspath(args.backup_dir),
        os.path.abspath(args.cache_dir),
    )
    if extracted:
        return extracted, source
    return board, "current-incompatible"


def main():
    parser = argparse.ArgumentParser(
        description="Verify offline DFM analysis consistency on installed KiCad versions."
    )
    parser.add_argument("--kicad-root", default=r"D:\KiCad")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument(
        "--board",
        default=DEFAULT_BOARD,
    )
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--cache-dir", default=os.path.join(os.getcwd(), ".hqdfm-test", "video"))
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--versions", nargs="*", default=VERSIONS)
    parser.add_argument(
        "--use-current-board",
        action="store_true",
        help="Use --board exactly as passed, even if it appears newer than KiCad 6.",
    )
    parser.add_argument(
        "--check-profiles",
        action="store_true",
        help="Also verify economy/standard/precision use different active rule thresholds.",
    )
    args = parser.parse_args()

    board, source = choose_board(args)
    print("board: {0}".format(board))
    print("source: {0}".format(source))

    results = {}
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
        result = subprocess.run(
            [python_exe, "-c", textwrap.dedent(CHECK_SCRIPT)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.stderr:
            sys.stderr.write(result.stderr)
        if result.returncode != 0:
            sys.stdout.write(result.stdout)
            failures.append("{0}: failed with exit code {1}".format(version, result.returncode))
            continue
        try:
            data = parse_check_output(result.stdout)
        except ValueError as exc:
            failures.append("{0}: {1}".format(version, exc))
            continue
        results[version] = data["summary"]
        print("{0}: {1}".format(version, json.dumps(data["summary"], sort_keys=True)))

    if results:
        baseline_version = next(iter(results))
        baseline = comparable_summary(results[baseline_version])
        for version, summary in results.items():
            if comparable_summary(summary) != baseline:
                failures.append(
                    "{0}: summary differs from {1}".format(version, baseline_version)
                )

    if args.check_profiles and not failures:
        profile_rules = {}
        version = next(iter(results))
        python_exe = os.path.join(args.kicad_root, version, "bin", "python.exe")
        for profile in ("economy", "standard", "precision"):
            env = os.environ.copy()
            env["KICAD_ROOT"] = os.path.join(args.kicad_root, version)
            env["HQDFM_REPO"] = os.path.abspath(args.repo)
            env["HQDFM_BOARD"] = board
            env["HQDFM_RULE_PROFILE"] = profile
            result = subprocess.run(
                [python_exe, "-c", textwrap.dedent(CHECK_SCRIPT)],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.stderr:
                sys.stderr.write(result.stderr)
            if result.returncode != 0:
                sys.stdout.write(result.stdout)
                failures.append("{0}: profile {1} failed".format(version, profile))
                continue
            try:
                data = parse_check_output(result.stdout)
            except ValueError as exc:
                failures.append("{0}: profile {1}: {2}".format(version, profile, exc))
                continue
            profile_rules[profile] = data["summary"]["Smallest Trace Width"]["rule"]
        if len(set(profile_rules.values())) != 3:
            failures.append("rule profiles did not produce distinct active rules: {0}".format(profile_rules))
        elif profile_rules:
            print("profiles: {0}".format(json.dumps(profile_rules, sort_keys=True)))

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
