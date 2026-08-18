import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap


VERSIONS = ("6.0", "7.0", "8.0", "9.0", "10.0")


CHECK_SCRIPT = r"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.environ["HQDFM_REPO"])

import pcbnew

from kicad_dfm.core.rule_profiles import rules_for_profile
from kicad_dfm.kicad.board_loader import load_board_noninteractive
from kicad_dfm.services.export import export_fabrication_package, gerber_output_dir
from kicad_dfm.services.export_checks import analyze_export


def copy_project(board_path, target_dir):
    # Copy the entire project directory, not just files sharing the board's
    # name prefix. KiCad 7+ opens a modal dialog (and hangs in a GUI-less
    # python session) when project library tables such as fp-lib-table /
    # sym-lib-table reference local .pretty libraries that are missing.
    source_dir = os.path.dirname(board_path)
    for name in os.listdir(source_dir):
        source = os.path.join(source_dir, name)
        dest = os.path.join(target_dir, name)
        if os.path.isdir(source):
            shutil.copytree(source, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(source, dest)
    target_board = os.path.join(target_dir, os.path.basename(board_path))
    if not os.path.exists(target_board):
        shutil.copy2(board_path, target_board)
    return target_board


temp_root = tempfile.mkdtemp(prefix="hqdfm_export_")
board_path = copy_project(os.environ["HQDFM_BOARD"], temp_root)
board = load_board_noninteractive(board_path)
if board is None:
    raise AssertionError("LoadBoard returned None")

output_dir = gerber_output_dir(temp_root, include_metadata=True)
result = export_fabrication_package(board, output_dir)
issues, summary = analyze_export(result, rules_for_profile(os.environ.get("HQDFM_RULE_PROFILE", "standard")))
data = {
    "version": str(pcbnew.GetBuildVersion()),
    "temp_dir": temp_root,
    "output_dir": result.output_dir,
    "file_count": len(result.files),
    "zip_path": result.zip_path,
    "zip_size": os.path.getsize(result.zip_path) if os.path.exists(result.zip_path) else 0,
    "summary": summary["Gerber Export"].display,
    "color": summary["Gerber Export"].color,
    "issues": [
        {"item": issue.item, "severity": issue.severity, "message": issue.message}
        for issue in issues
    ],
}
print(json.dumps(data, sort_keys=True))
"""


def main():
    parser = argparse.ArgumentParser(
        description="Verify Gerber/Drill/ZIP export stability on installed KiCad versions."
    )
    parser.add_argument("--kicad-root", default=r"D:\KiCad")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument(
        "--board",
        default=r"D:\KiCad\6.0\share\kicad\demos\video\video.kicad_pcb",
    )
    parser.add_argument("--profile", default="standard")
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
        env["HQDFM_BOARD"] = os.path.abspath(args.board)
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
            data = json.loads(result.stdout)
        except ValueError:
            sys.stdout.write(result.stdout)
            failures.append("{0}: invalid JSON output".format(version))
            continue
        print(
            "{0}: {1} files, {2} bytes, {3}, {4}".format(
                version,
                data["file_count"],
                data["zip_size"],
                data["summary"],
                data["output_dir"],
            )
        )
        blocking = [issue for issue in data["issues"] if issue["severity"] == "error"]
        if blocking:
            failures.append("{0}: Gerber Check errors in {1}".format(version, data["temp_dir"]))

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
