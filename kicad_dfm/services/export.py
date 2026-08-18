import os
import shutil
import tempfile

from kicad_dfm.core.files import export_files, validate_export_file, zip_directory
from kicad_dfm.core.models import ExportResult, OutputDirResult
from kicad_dfm.kicad.swig import SwigBackend


def export_gerber(backend, output_dir, layer_count=None):
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    for filename in os.listdir(output_dir):
        path = os.path.join(output_dir, filename)
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
    layer_count = layer_count or backend.copper_layer_count()
    plot_plan = gerber_plot_plan(backend, layer_count)
    plot_controller = backend.create_plot_controller(output_dir)
    try:
        for layer_info in plot_plan:
            backend.plot_gerber_layer(plot_controller, layer_info)
    finally:
        plot_controller.ClosePlot()
    return plot_plan


def export_drill(backend, output_dir):
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    backend.export_drill(output_dir)


def export_fabrication_package(board, output_dir, layer_count=None, zip_path=None):
    output_info = output_dir if isinstance(output_dir, OutputDirResult) else None
    root_dir = os.fspath(output_dir)
    output_dir = gerber_package_dir(root_dir, board)
    backend = SwigBackend(board)
    layer_count = layer_count or backend.copper_layer_count()
    plot_plan = export_gerber(backend, output_dir, layer_count)
    export_drill(backend, output_dir)
    zip_path = zip_path or os.path.join(root_dir, os.path.basename(output_dir) + ".zip")
    files = export_files(output_dir)
    zip_directory(output_dir, zip_path, files=files)
    validate_export_file(zip_path)
    return ExportResult(
        output_dir=output_dir,
        zip_path=zip_path,
        files=files,
        plot_plan=tuple(plot_plan),
        layer_count=int(layer_count or 0),
        fallback_used=bool(output_info and output_info.fallback_used),
        warnings=tuple(output_info.warnings) if output_info else (),
    )


def gerber_output_dir(pcb_dir, include_metadata=False):
    output_dir = os.path.join(pcb_dir, "HQDMF")
    try:
        os.makedirs(output_dir, exist_ok=True)
        result = OutputDirResult(output_dir=output_dir)
    except (PermissionError, OSError) as exc:
        fallback = os.path.join(tempfile.gettempdir(), "HQDMF")
        os.makedirs(fallback, exist_ok=True)
        result = OutputDirResult(
            output_dir=fallback,
            fallback_used=True,
            warnings=("Falling back to temporary Gerber output directory: {0}".format(exc),),
        )
    if include_metadata:
        return result
    return result.output_dir


def gerber_package_dir(root_dir, board):
    board_name = board_file_stem(board)
    return os.path.join(os.fspath(root_dir), "Gerber_{0}".format(board_name))


def board_file_stem(board):
    filename = ""
    if hasattr(board, "GetFileName"):
        filename = board.GetFileName() or ""
    stem = os.path.splitext(os.path.basename(filename))[0]
    return safe_path_component(stem or "board")


def safe_path_component(value):
    text = str(value or "board")
    sanitized = "".join(ch if ch not in '<>:"/\\|?*' and ord(ch) >= 32 else "_" for ch in text)
    sanitized = sanitized.strip(" .")
    return sanitized or "board"


def gerber_plot_plan(backend, layer_count):
    plan = [
        ("CuTop", backend.layer_constant("F_Cu"), "Top layer"),
        ("SilkTop", backend.layer_constant("F_SilkS"), "Silk top"),
        ("MaskTop", backend.layer_constant("F_Mask"), "Mask top"),
        ("PasteTop", backend.layer_constant("F_Paste"), "Paste top"),
    ]
    inner_layers = max(0, int(layer_count or 0) - 2)
    for index in range(inner_layers):
        const_name = "In{0}_Cu".format(index + 1)
        if hasattr(_PcbnewConstants(backend), const_name):
            plan.append(("CuIn{0}".format(index + 1), backend.layer_constant(const_name), "Inner layer {0}".format(index + 1)))
    if int(layer_count or 0) >= 2:
        plan.extend(
            [
                ("CuBottom", backend.layer_constant("B_Cu"), "Bottom layer"),
                ("SilkBottom", backend.layer_constant("B_SilkS"), "Silk bottom"),
                ("MaskBottom", backend.layer_constant("B_Mask"), "Mask bottom"),
                ("PasteBottom", backend.layer_constant("B_Paste"), "Paste bottom"),
            ]
        )
    plan.extend(
        [
            ("EdgeCuts", backend.layer_constant("Edge_Cuts"), "Edges"),
            ("VScore", backend.layer_constant("Cmts_User"), "V score cut"),
        ]
    )
    return plan


class _PcbnewConstants:
    def __init__(self, backend):
        self.backend = backend

    def __getattr__(self, name):
        try:
            return self.backend.layer_constant(name)
        except AttributeError:
            raise AttributeError(name)
