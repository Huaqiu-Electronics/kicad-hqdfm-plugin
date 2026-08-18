import shutil
import subprocess

from kicad_dfm.core.errors import ExportError


def kicad_cli_path():
    return shutil.which("kicad-cli")


def available():
    return kicad_cli_path() is not None


def unavailable_reason():
    if available():
        return ""
    return "kicad-cli was not found on PATH"


def export_gerbers(board_path, output_dir):
    return _run(["pcb", "export", "gerbers", "-o", output_dir, board_path])


def export_drill(board_path, output_dir):
    return _run(["pcb", "export", "drill", "-o", output_dir, board_path])


def _run(args):
    exe = kicad_cli_path()
    if exe is None:
        raise ExportError(unavailable_reason())
    result = subprocess.run(
        [exe] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ExportError(result.stderr.strip() or result.stdout.strip())
    return result.stdout
