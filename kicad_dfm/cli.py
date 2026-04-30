"""Command-line interface for headless DFM analysis.

Usage::

    python -m kicad_hqdfm check board.kicad_pcb [--output report.json]

The module can also be invoked directly::

    python kicad_dfm/cli.py check board.kicad_pcb
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kicad-hqdfm",
        description="Headless DFM analysis for KiCad PCB files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check_parser = sub.add_parser("check", help="Run local DFM checks on a board file")
    check_parser.add_argument("board", type=str, help="Path to .kicad_pcb file")
    check_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Write JSON report to file (default: stdout)",
    )
    check_parser.add_argument(
        "--fail-on",
        choices=["error", "warn", "never"],
        default="warn",
        help="Exit non-zero on: error (red only), warn (gold+red), never (always exit 0, default: warn)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.command == "check":
        return _cmd_check(args)

    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    board_path = args.board
    if not Path(board_path).is_file():
        print(f"Error: board file not found: {board_path}", file=sys.stderr)
        return 2

    from kicad_dfm.headless import analyze_board

    report = analyze_board(board_path)
    report_dict = report.to_dict()

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report_dict, indent=2, ensure_ascii=False))
        print(f"Report written to {output_path}", file=sys.stderr)
    else:
        json.dump(report_dict, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")

    if args.fail_on == "never":
        return 0
    if args.fail_on == "error" and report.status == "fail":
        return 2
    if args.fail_on == "warn" and report.status in ("warn", "fail"):
        return report.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
