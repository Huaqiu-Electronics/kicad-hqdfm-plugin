#!/usr/bin/env python3
"""Report the ZIP download size and extracted install size.

Usage:
    py zip_sizes.py path\to\package.zip
    py zip_sizes.py path\to\package.zip --json
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path


def format_bytes(size: int) -> str:
    """Format bytes in both bytes and binary units."""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:,.2f} {unit} ({size:,} bytes)"
        value /= 1024
    return f"{size:,} bytes"


def get_sizes(zip_path: Path) -> dict:
    if not zip_path.is_file():
        raise FileNotFoundError(f"ZIP file not found: {zip_path}")

    download_size = zip_path.stat().st_size
    install_size = 0
    file_count = 0
    directory_count = 0

    with zipfile.ZipFile(zip_path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise zipfile.BadZipFile(f"CRC check failed for member: {bad_member}")

        # Sum uncompressed file sizes, excluding directory entries.
        # This mirrors the KiCad PCM validator's install_size calculation.
        for entry in archive.infolist():
            if entry.is_dir():
                directory_count += 1
                continue
            install_size += entry.file_size
            file_count += 1

    return {
        "path": str(zip_path.resolve()),
        "download_size_bytes": download_size,
        "install_size_bytes": install_size,
        "file_count": file_count,
        "directory_count": directory_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print ZIP download size and extracted install size."
    )
    parser.add_argument("zip_path", help="Path to the ZIP file")
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Print results as JSON"
    )
    args = parser.parse_args()

    try:
        result = get_sizes(Path(args.zip_path).expanduser())
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"ZIP:          {result['path']}")
        print(
            f"Download size: {format_bytes(result['download_size_bytes'])}"
        )
        print(
            f"Install size:  {format_bytes(result['install_size_bytes'])}"
        )
        print(f"Files:         {result['file_count']:,}")
        print(f"Directories:   {result['directory_count']:,}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
