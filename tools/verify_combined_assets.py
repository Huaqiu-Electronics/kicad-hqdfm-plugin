"""Read-only regression runner for the bundled KiCad/Gerber assets.

The parent process never imports pcbnew.  Each load, native-analysis, and
strict-Gerber phase is run in a bounded KiCad-Python subprocess so one damaged
or pathological board cannot stall the remaining assets.  Existing Gerbers
are read in place; missing/forced exports are written below a temporary HQDMF
directory and removed at the end of the run.
"""

import argparse
import collections
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback


SCHEMA_VERSION = 1
WORKER_PREFIX = "HQDFM_ASSET_WORKER="
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent

KICAD_NATIVE = "kicad_native"
GERBER_STRICT = "gerber_strict"
COMBINED = "combined"
LOAD_BOARD = "load_board"

ASSETS = {
    "pic": "pic_programmer.kicad_pcb",
    "flat": "flat_hierarchy.kicad_pcb",
    "video": "video.kicad_pcb",
    "amulet": "amulet_controller_9.kicad_pcb",
}

SLOW_PHASES = {
    ("amulet", KICAD_NATIVE),
    ("amulet", GERBER_STRICT),
}

PIC_MISSING_MASK_UUID = "ad7eb14f-6c5c-4996-a54a-7ce82fc42954"
AMULET_COPPER_LAYERS = (
    "F.Cu",
    "In1.Cu",
    "In2.Cu",
    "In3.Cu",
    "In4.Cu",
    "B.Cu",
)


def elapsed_ms(started_at):
    return round((time.perf_counter() - started_at) * 1000.0, 3)


def flatten_rows(result_map, category):
    category_result = (result_map or {}).get(category)
    if not isinstance(category_result, dict):
        return []
    return [
        row
        for group in category_result.get("check") or ()
        if isinstance(group, dict)
        for row in group.get("result") or ()
        if isinstance(row, dict)
    ]


def _counter_dict(values):
    return dict(sorted(collections.Counter(values).items(), key=lambda pair: str(pair[0])))


def _layer_key(layers):
    return ",".join(str(layer) for layer in (layers or ()))


def category_observation(result_map, category):
    data = (result_map or {}).get(category)
    data = data if isinstance(data, dict) else {}
    rows = flatten_rows(result_map, category)
    return {
        "rows": len(rows),
        "items": _counter_dict(str(row.get("item") or "") for row in rows),
        "layers": _counter_dict(_layer_key(row.get("layer")) for row in rows),
        "display": data.get("display"),
        "color": data.get("color", ""),
        "checked_count": int(data.get("checked_count") or 0),
        "violation_count": int(data.get("violation_count") or 0),
        "displayed_count": int(data.get("displayed_count") or len(rows)),
        "execution_status": data.get("execution_status", ""),
    }


def summarize_result_map(result_map):
    return {
        category: category_observation(result_map, category)
        for category in result_map or {}
        if isinstance((result_map or {}).get(category), dict)
    }


def native_observation(result):
    categories = summarize_result_map(result.kicad_result)
    missing_rows = flatten_rows(result.kicad_result, "Missing SMask Openings")
    return {
        "categories": categories,
        "missing_smask": [
            {
                "id": str(row.get("id") or ""),
                "layer": list(row.get("layer") or ()),
            }
            for row in missing_rows
        ],
        "profile_total_ms": (result.profile or {}).get("total_ms"),
        "contract": contract_observation(result.contract),
    }


def _function_values(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in ("function", "aperture_function"):
                yield str(nested or "")
            elif isinstance(nested, (dict, list, tuple)):
                yield from _function_values(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _function_values(nested)


def is_nonconductor_related(row):
    raw = row.get("raw") if isinstance(row, dict) else {}
    related = raw.get("related") if isinstance(raw, dict) else {}
    return any(
        "".join(character for character in value.lower() if character.isalnum())
        == "nonconductor"
        for value in _function_values(related)
    )


def ring_evidence_observation(rows):
    measurement_layers = collections.Counter()
    measurement_total = 0
    rows_with_measurements = 0
    rows_with_matching_declared_count = 0
    row_layer_sets = []
    for row in rows:
        raw = row.get("raw") or {}
        measurements = raw.get("per_layer_measurements") or ()
        if measurements:
            rows_with_measurements += 1
        if int(raw.get("physical_measurement_count") or 0) == len(measurements):
            rows_with_matching_declared_count += 1
        row_layers = set()
        for measurement in measurements:
            layers = measurement.get("layer") if isinstance(measurement, dict) else ()
            for layer in layers or ():
                layer = str(layer)
                measurement_layers[layer] += 1
                row_layers.add(layer)
            measurement_total += 1
        row_layer_sets.append(sorted(row_layers))
    expected_layers = set(AMULET_COPPER_LAYERS)
    return {
        "physical_rows": len(rows),
        "rows_with_per_layer_measurements": rows_with_measurements,
        "rows_with_matching_physical_measurement_count": (
            rows_with_matching_declared_count
        ),
        "per_layer_measurement_total": measurement_total,
        "measurement_layers": dict(sorted(measurement_layers.items())),
        "rows_covering_all_amulet_copper_layers": sum(
            set(layers) == expected_layers for layers in row_layer_sets
        ),
    }


def gerber_observation(result_map, issues, profile, source):
    categories = summarize_result_map(result_map)
    holes = flatten_rows(result_map, "Holes on SMD Pads")
    rings = flatten_rows(result_map, "RingHole")
    try:
        from kicad_dfm.services.export_checks import is_blocking_export_issue

        blocking_count = sum(is_blocking_export_issue(issue) for issue in issues)
    except Exception:
        blocking_count = 0
    return {
        "source": source,
        "categories": categories,
        "holes_on_smd": {
            "physical_rows": len(holes),
            "nonconductor_related_rows": sum(
                is_nonconductor_related(row) for row in holes
            ),
        },
        "ring_evidence": ring_evidence_observation(rings),
        "export_issue_count": len(tuple(issues or ())),
        "blocking_export_issue_count": blocking_count,
        "profile_total_ms": (profile or {}).get("total_ms"),
    }


def contract_observation(contract):
    contract = contract if isinstance(contract, dict) else {}
    categories = {}
    for category, data in (contract.get("categories") or {}).items():
        categories[category] = {
            "execution_status": data.get("execution_status", ""),
            "checked_count": int(data.get("checked_count") or 0),
            "violation_count": int(data.get("violation_count") or 0),
            "displayed_count": int(data.get("displayed_count") or 0),
            "finding_count": len(data.get("findings") or ()),
            "source_counts": data.get("source_counts") or {},
        }
    return {
        "mode": contract.get("mode", ""),
        "execution_status": contract.get("execution_status", ""),
        "counts": contract.get("counts") or {},
        "source_modes": sorted((contract.get("source_views") or {}).keys()),
        "categories": categories,
    }


def write_contract(path, contract):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(contract, handle, ensure_ascii=True, sort_keys=True)


def worker_load_board(args):
    import pcbnew

    from kicad_dfm.kicad.board_loader import load_board_noninteractive
    from kicad_dfm.kicad.swig import SwigBackend

    started_at = time.perf_counter()
    board = load_board_noninteractive(args.board)
    load_ms = elapsed_ms(started_at)
    if board is None:
        raise RuntimeError("pcbnew.LoadBoard returned None")
    backend = SwigBackend(board)
    return {
        "status": "completed",
        "phase": LOAD_BOARD,
        "summary": {
            "build_version": str(pcbnew.GetBuildVersion()),
            "board_file": str(board.GetFileName() or args.board),
            "board_thickness_mm": backend.board_thickness_mm(),
            "copper_layer_count": backend.copper_layer_count(),
        },
        "timings_ms": {LOAD_BOARD: load_ms},
    }


def worker_native(args):
    import pcbnew

    from kicad_dfm.core.rule_profiles import rules_for_profile
    from kicad_dfm.kicad.board_loader import load_board_noninteractive
    from kicad_dfm.services.offline_analysis import OfflineDfmAnalysis

    load_started = time.perf_counter()
    board = load_board_noninteractive(args.board)
    load_ms = elapsed_ms(load_started)
    if board is None:
        raise RuntimeError("pcbnew.LoadBoard returned None")
    analysis_started = time.perf_counter()
    result = OfflineDfmAnalysis(
        board,
        {},
        rules=rules_for_profile(args.profile),
    ).analyze()
    analysis_ms = elapsed_ms(analysis_started)
    write_contract(args.artifact, result.contract)
    return {
        "status": "completed",
        "phase": KICAD_NATIVE,
        "summary": native_observation(result),
        "artifact": str(Path(args.artifact).resolve()),
        "timings_ms": {
            LOAD_BOARD: load_ms,
            KICAD_NATIVE: analysis_ms,
        },
    }


def _known_plot_plan(files):
    known_names = (
        "CuTop",
        "CuBottom",
        "SilkTop",
        "SilkBottom",
        "MaskTop",
        "MaskBottom",
        "PasteTop",
        "PasteBottom",
        "EdgeCuts",
        "VScore",
    )
    plan = []
    seen = set()
    for path in files:
        stem = Path(path).stem
        candidates = list(known_names)
        if "CuIn" in stem:
            suffix = stem[stem.rfind("CuIn") :]
            if suffix[4:].isdigit():
                candidates.append(suffix)
        for name in candidates:
            if stem == name or stem.endswith("-" + name) or stem.endswith("_" + name):
                if name not in seen:
                    seen.add(name)
                    plan.append((name, None, name))
                break
    return tuple(plan)


def existing_export_result(output_dir, copper_layer_count):
    from kicad_dfm.core.files import export_files
    from kicad_dfm.core.models import ExportResult

    output_dir = str(Path(output_dir).resolve())
    files = export_files(output_dir)
    zip_path = os.path.join(
        os.path.dirname(output_dir), os.path.basename(output_dir) + ".zip"
    )
    return ExportResult(
        output_dir=output_dir,
        zip_path=zip_path,
        files=files,
        plot_plan=_known_plot_plan(files),
        layer_count=int(copper_layer_count or 0),
    )


def strict_summary_map(export_summary, result_map, issues):
    from kicad_dfm.core.models import DfmSummary

    summary = dict(export_summary or {})
    for category, result in (result_map or {}).items():
        if not isinstance(result, dict):
            continue
        summary[category] = DfmSummary(
            category=category,
            display=str(result.get("display", "")),
            display_inch=str(result.get("display_inch", "")),
            color=result.get("color", ""),
            issues=tuple(issue for issue in issues if issue.category == category),
        )
    return summary


def worker_gerber(args):
    from kicad_dfm.core.rule_profiles import rules_for_profile
    from kicad_dfm.services.analysis_results import build_analysis_contract
    from kicad_dfm.services.analysis_results import GERBER_STRICT as STRICT_MODE
    from kicad_dfm.services.export import export_fabrication_package
    from kicad_dfm.services.export_checks import analyze_export_with_results
    from kicad_dfm.services.offline_analysis import COMPAT_CATEGORIES

    timings = {}
    source = args.gerber_source
    if source == "existing":
        export_result = existing_export_result(
            args.gerber_dir, args.copper_layer_count
        )
    else:
        import pcbnew

        from kicad_dfm.kicad.board_loader import load_board_noninteractive

        load_started = time.perf_counter()
        board = load_board_noninteractive(args.board)
        timings[LOAD_BOARD] = elapsed_ms(load_started)
        if board is None:
            raise RuntimeError("pcbnew.LoadBoard returned None")
        export_root = Path(args.temp_root).resolve() / "HQDMF"
        export_root.mkdir(parents=True, exist_ok=True)
        export_started = time.perf_counter()
        export_result = export_fabrication_package(board, str(export_root))
        timings["gerber_export"] = elapsed_ms(export_started)

    analysis_started = time.perf_counter()
    issues, export_summary, strict_results, profile = analyze_export_with_results(
        export_result,
        rules=rules_for_profile(args.profile),
        expected_output_name="HQDMF",
        include_profile=True,
        board_thickness_mm=args.board_thickness_mm,
        chinese=False,
    )
    timings[GERBER_STRICT] = elapsed_ms(analysis_started)
    summary = strict_summary_map(export_summary, strict_results, issues)
    contract = build_analysis_contract(
        STRICT_MODE,
        strict_results,
        issues,
        summary,
        categories=COMPAT_CATEGORIES,
        profile=profile,
        metadata={
            "input_kind": "gerber_excellon",
            "asset_regression_source": source,
        },
    )
    write_contract(args.artifact, contract)
    observation = gerber_observation(strict_results, issues, profile, source)
    observation["contract"] = contract_observation(contract)
    observation["export"] = {
        "output_dir": str(export_result.output_dir),
        "file_count": len(tuple(export_result.files or ())),
        "layer_count": int(export_result.layer_count or 0),
        "temporary": source == "export",
    }
    return {
        "status": "completed",
        "phase": GERBER_STRICT,
        "summary": observation,
        "artifact": str(Path(args.artifact).resolve()),
        "timings_ms": timings,
    }


def worker_parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker-phase", choices=(LOAD_BOARD, KICAD_NATIVE, GERBER_STRICT))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--board", required=True)
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--artifact")
    parser.add_argument("--gerber-source", choices=("existing", "export"))
    parser.add_argument("--gerber-dir")
    parser.add_argument("--temp-root")
    parser.add_argument("--board-thickness-mm", type=float)
    parser.add_argument("--copper-layer-count", type=int, default=0)
    return parser


def worker_main(argv):
    args = worker_parser().parse_args(argv)
    sys.path.insert(0, str(Path(args.repo).resolve()))
    try:
        if args.worker_phase == LOAD_BOARD:
            response = worker_load_board(args)
        elif args.worker_phase == KICAD_NATIVE:
            if not args.artifact:
                raise ValueError("--artifact is required for kicad_native")
            response = worker_native(args)
        else:
            if not args.artifact:
                raise ValueError("--artifact is required for gerber_strict")
            if args.gerber_source == "existing" and not args.gerber_dir:
                raise ValueError("--gerber-dir is required for existing Gerbers")
            if args.gerber_source == "export" and not args.temp_root:
                raise ValueError("--temp-root is required for temporary export")
            response = worker_gerber(args)
        exit_code = 0
    except Exception as exc:
        response = {
            "status": "failed",
            "phase": args.worker_phase,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    print(WORKER_PREFIX + json.dumps(response, ensure_ascii=True, sort_keys=True))
    return exit_code


def parse_worker_output(stdout):
    for line in reversed(str(stdout or "").splitlines()):
        if line.startswith(WORKER_PREFIX):
            return json.loads(line[len(WORKER_PREFIX) :])
    raise ValueError("worker did not emit a {0} record".format(WORKER_PREFIX))


def run_worker_phase(
    python_exe,
    phase,
    worker_args,
    timeout_seconds,
    repo=REPO_ROOT,
    runner=subprocess.run,
):
    command = [
        str(python_exe),
        str(SCRIPT_PATH),
        "--worker-phase",
        phase,
        "--repo",
        str(Path(repo).resolve()),
    ] + [str(value) for value in worker_args]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    started_at = time.perf_counter()
    try:
        completed = runner(
            command,
            cwd=str(Path(repo).resolve()),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=float(timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "phase": phase,
            "timeout_seconds": float(timeout_seconds),
            "wall_ms": elapsed_ms(started_at),
            "stdout_tail": str(exc.stdout or "")[-1000:],
            "stderr_tail": str(exc.stderr or "")[-1000:],
        }
    except Exception as exc:
        return {
            "status": "failed",
            "phase": phase,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "wall_ms": elapsed_ms(started_at),
        }

    try:
        response = parse_worker_output(completed.stdout)
    except Exception as exc:
        response = {
            "status": "failed",
            "phase": phase,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "stdout_tail": str(completed.stdout or "")[-2000:],
        }
    response["wall_ms"] = elapsed_ms(started_at)
    response["returncode"] = int(completed.returncode)
    stderr = str(completed.stderr or "")
    if stderr:
        response["stderr_line_count"] = len(stderr.splitlines())
        if completed.returncode != 0:
            response["stderr_tail"] = stderr[-2000:]
    if completed.returncode != 0 and response.get("status") == "completed":
        response["status"] = "failed"
        response["error"] = "worker exited with {0}".format(completed.returncode)
    return response


def _gate(name, expected, actual, passed, detail=""):
    result = {
        "name": name,
        "expected": expected,
        "actual": actual,
        "status": "passed" if passed else "failed",
    }
    if detail:
        result["detail"] = detail
    return result


def _skipped_gate(name, expected, reason):
    return {
        "name": name,
        "expected": expected,
        "actual": None,
        "status": "skipped",
        "detail": reason,
    }


def evaluate_gates(asset, native_summary=None, gerber_summary=None, combined=None):
    gates = []
    native_categories = (native_summary or {}).get("categories") or {}
    gerber_categories = (gerber_summary or {}).get("categories") or {}

    if asset == "pic":
        if native_summary is None:
            gates.extend(
                (
                    _skipped_gate("pic_signal_rows", 3, "kicad_native unavailable"),
                    _skipped_gate(
                        "pic_missing_smask_uuid",
                        PIC_MISSING_MASK_UUID,
                        "kicad_native unavailable",
                    ),
                )
            )
        else:
            signal_rows = (native_categories.get("Signal Integrity") or {}).get("rows")
            missing = native_summary.get("missing_smask") or []
            missing_ids = sorted(item.get("id") for item in missing)
            missing_layers = sorted(
                layer for item in missing for layer in item.get("layer") or ()
            )
            gates.append(_gate("pic_signal_rows", 3, signal_rows, signal_rows == 3))
            gates.append(
                _gate(
                    "pic_missing_smask_uuid",
                    [PIC_MISSING_MASK_UUID],
                    missing_ids,
                    missing_ids == [PIC_MISSING_MASK_UUID]
                    and missing_layers == ["B.Cu"],
                    detail="Expected the single missing opening on B.Cu.",
                )
            )

    if asset == "flat":
        if native_summary is None:
            gates.extend(
                (
                    _skipped_gate("flat_signal_rows", 0, "kicad_native unavailable"),
                    _skipped_gate(
                        "flat_missing_smask_rows", 0, "kicad_native unavailable"
                    ),
                )
            )
        else:
            signal_rows = (native_categories.get("Signal Integrity") or {}).get("rows")
            missing_rows = (
                native_categories.get("Missing SMask Openings") or {}
            ).get("rows")
            gates.append(_gate("flat_signal_rows", 0, signal_rows, signal_rows == 0))
            gates.append(
                _gate(
                    "flat_missing_smask_rows",
                    0,
                    missing_rows,
                    missing_rows == 0,
                )
            )

    if asset == "video":
        expected_items = {
            "Acute Angle Traces": 3,
        }
        if native_summary is None:
            gates.extend(
                (
                    _skipped_gate("video_signal_rows", 3, "kicad_native unavailable"),
                    _skipped_gate(
                        "video_signal_items", expected_items, "kicad_native unavailable"
                    ),
                )
            )
        else:
            signal = native_categories.get("Signal Integrity") or {}
            gates.append(
                _gate("video_signal_rows", 3, signal.get("rows"), signal.get("rows") == 3)
            )
            gates.append(
                _gate(
                    "video_signal_items",
                    expected_items,
                    signal.get("items") or {},
                    (signal.get("items") or {}) == expected_items,
                )
            )
        if gerber_summary is None:
            gates.extend(
                (
                    _skipped_gate(
                        "video_gerber_holes_on_smd_rows",
                        13,
                        "gerber_strict unavailable",
                    ),
                    _skipped_gate(
                        "video_gerber_nonconductor_related_rows",
                        0,
                        "gerber_strict unavailable",
                    ),
                )
            )
        else:
            holes = gerber_summary.get("holes_on_smd") or {}
            gates.append(
                _gate(
                    "video_gerber_holes_on_smd_rows",
                    13,
                    holes.get("physical_rows"),
                    holes.get("physical_rows") == 13,
                )
            )
            gates.append(
                _gate(
                    "video_gerber_nonconductor_related_rows",
                    0,
                    holes.get("nonconductor_related_rows"),
                    holes.get("nonconductor_related_rows") == 0,
                )
            )

    if asset == "amulet":
        if native_summary is None:
            gates.append(
                _skipped_gate(
                    "amulet_native_signal_rows",
                    0,
                    "kicad_native unavailable",
                )
            )
        else:
            signal = native_categories.get("Signal Integrity") or {}
            gates.append(
                _gate(
                    "amulet_native_signal_rows",
                    0,
                    signal.get("rows"),
                    signal.get("rows") == 0 and not (signal.get("items") or {}),
                    detail=(
                        "KiCad native connectivity and exposed-junction checks "
                        "must not recreate the former 145/1/158 false positives."
                    ),
                )
            )
        if gerber_summary is None:
            gates.extend(
                (
                    _skipped_gate(
                        "amulet_gerber_ring_physical_rows",
                        1253,
                        "gerber_strict unavailable",
                    ),
                    _skipped_gate(
                        "amulet_gerber_ring_per_layer_evidence",
                        7518,
                        "gerber_strict unavailable",
                    ),
                )
            )
        else:
            evidence = gerber_summary.get("ring_evidence") or {}
            physical_rows = evidence.get("physical_rows")
            measurement_total = evidence.get("per_layer_measurement_total")
            expected_layer_counts = {layer: 1253 for layer in AMULET_COPPER_LAYERS}
            evidence_passed = (
                measurement_total == 7518
                and evidence.get("rows_with_per_layer_measurements") == 1253
                and evidence.get("rows_with_matching_physical_measurement_count") == 1253
                and evidence.get("rows_covering_all_amulet_copper_layers") == 1253
                and evidence.get("measurement_layers") == expected_layer_counts
            )
            gates.append(
                _gate(
                    "amulet_gerber_ring_physical_rows",
                    1253,
                    physical_rows,
                    physical_rows == 1253,
                )
            )
            gates.append(
                _gate(
                    "amulet_gerber_ring_per_layer_evidence",
                    {
                        "measurement_total": 7518,
                        "layers": expected_layer_counts,
                        "rows_with_six_layers": 1253,
                    },
                    evidence,
                    evidence_passed,
                )
            )

    if gerber_summary is not None:
        blocking = gerber_summary.get("blocking_export_issue_count")
        gates.append(
            _gate(
                "gerber_blocking_export_issues",
                0,
                blocking,
                blocking == 0,
            )
        )

    if combined is not None:
        modes = combined.get("source_modes") or []
        gates.append(
            _gate(
                "combined_source_modes",
                [GERBER_STRICT, KICAD_NATIVE],
                modes,
                set(modes) == {KICAD_NATIVE, GERBER_STRICT},
            )
        )
    return gates


def default_kicad_python():
    configured = os.environ.get("KICAD_PYTHON")
    if configured and Path(configured).is_file():
        return configured
    current = Path(sys.executable)
    if "kicad" in str(current).lower() and current.is_file():
        return str(current)
    if os.name == "nt":
        roots = tuple(
            dict.fromkeys(
                value
                for value in (
                    os.environ.get("ProgramW6432"),
                    os.environ.get("ProgramFiles"),
                    r"C:\Program Files",
                )
                if value
            )
        )
        for root in roots:
            candidate = Path(root) / "KiCad" / "10.0" / "bin" / "python.exe"
            if candidate.is_file():
                return str(candidate)
    return str(current)


def existing_gerber_dir(assets_dir, board_path):
    return Path(assets_dir) / "HQDMF" / ("Gerber_" + Path(board_path).stem)


def _skipped_phase(phase, reason):
    return {"status": "skipped", "phase": phase, "reason": reason, "wall_ms": 0.0}


def _blocked_phase(phase, reason):
    return {"status": "blocked", "phase": phase, "reason": reason, "wall_ms": 0.0}


def load_contract(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def verify_asset(args, asset, work_root):
    board_path = Path(args.assets_dir).resolve() / ASSETS[asset]
    result = {
        "asset": asset,
        "board": str(board_path),
        "phases": {},
        "gates": [],
    }
    if not board_path.is_file():
        result["phases"][LOAD_BOARD] = {
            "status": "failed",
            "phase": LOAD_BOARD,
            "error": "board file does not exist",
        }
        result["status"] = "failed"
        return result

    native_requested = not args.skip_native and not (
        args.skip_slow and (asset, KICAD_NATIVE) in SLOW_PHASES
    )
    gerber_requested = not args.skip_gerber and not (
        args.skip_slow and (asset, GERBER_STRICT) in SLOW_PHASES
    )
    gerber_dir = existing_gerber_dir(args.assets_dir, board_path)
    if args.gerber_source == "existing":
        gerber_source = "existing"
    elif args.gerber_source == "export":
        gerber_source = "export"
    else:
        gerber_source = "existing" if gerber_dir.is_dir() else "export"
    if gerber_source == "export" and args.skip_temp_export:
        gerber_requested = False

    load_required = native_requested or (
        gerber_requested and gerber_source == "export"
    )
    if not load_required:
        reason = "all selected analysis phases were skipped"
        if gerber_requested and gerber_source == "existing":
            reason = "existing Gerber analysis does not require load_board"
        result["phases"][LOAD_BOARD] = _skipped_phase(
            LOAD_BOARD, reason
        )
        load_result = result["phases"][LOAD_BOARD]
    else:
        load_result = run_worker_phase(
            args.kicad_python,
            LOAD_BOARD,
            ("--board", board_path, "--profile", args.profile),
            args.load_timeout,
            repo=args.repo,
        )
        result["phases"][LOAD_BOARD] = load_result

    load_summary = load_result.get("summary") or {}
    contract_root = Path(args.contract_dir).resolve() if args.contract_dir else Path(work_root)
    asset_contract_root = contract_root / asset
    native_artifact = asset_contract_root / (KICAD_NATIVE + ".json")
    gerber_artifact = asset_contract_root / (GERBER_STRICT + ".json")
    combined_artifact = asset_contract_root / (COMBINED + ".json")

    if not native_requested:
        reason = "--skip-native"
        if args.skip_slow and (asset, KICAD_NATIVE) in SLOW_PHASES:
            reason = "--skip-slow"
        result["phases"][KICAD_NATIVE] = _skipped_phase(KICAD_NATIVE, reason)
    elif load_result.get("status") != "completed":
        result["phases"][KICAD_NATIVE] = _blocked_phase(
            KICAD_NATIVE, "load_board did not complete"
        )
    else:
        result["phases"][KICAD_NATIVE] = run_worker_phase(
            args.kicad_python,
            KICAD_NATIVE,
            (
                "--board",
                board_path,
                "--profile",
                args.profile,
                "--artifact",
                native_artifact,
            ),
            args.native_timeout,
            repo=args.repo,
        )

    if not gerber_requested:
        reason = "--skip-gerber"
        if args.skip_slow and (asset, GERBER_STRICT) in SLOW_PHASES:
            reason = "--skip-slow"
        elif gerber_source == "export" and args.skip_temp_export:
            reason = "--skip-temp-export and no existing Gerber package"
        result["phases"][GERBER_STRICT] = _skipped_phase(GERBER_STRICT, reason)
    elif gerber_source == "existing" and not gerber_dir.is_dir():
        result["phases"][GERBER_STRICT] = {
            "status": "failed",
            "phase": GERBER_STRICT,
            "error": "existing Gerber directory does not exist: {0}".format(gerber_dir),
        }
    elif gerber_source == "export" and load_result.get("status") != "completed":
        result["phases"][GERBER_STRICT] = _blocked_phase(
            GERBER_STRICT, "temporary export requires a loadable board"
        )
    else:
        worker_args = [
            "--board",
            board_path,
            "--profile",
            args.profile,
            "--artifact",
            gerber_artifact,
            "--gerber-source",
            gerber_source,
            "--copper-layer-count",
            int(load_summary.get("copper_layer_count") or 0),
        ]
        if load_summary.get("board_thickness_mm") is not None:
            worker_args.extend(
                ("--board-thickness-mm", load_summary["board_thickness_mm"])
            )
        if gerber_source == "existing":
            worker_args.extend(("--gerber-dir", gerber_dir))
        else:
            worker_args.extend(("--temp-root", Path(work_root) / asset / "export"))
        result["phases"][GERBER_STRICT] = run_worker_phase(
            args.kicad_python,
            GERBER_STRICT,
            worker_args,
            args.gerber_timeout,
            repo=args.repo,
        )

    native_phase = result["phases"][KICAD_NATIVE]
    gerber_phase = result["phases"][GERBER_STRICT]
    native_summary = (
        native_phase.get("summary")
        if native_phase.get("status") == "completed"
        else None
    )
    gerber_summary = (
        gerber_phase.get("summary")
        if gerber_phase.get("status") == "completed"
        else None
    )

    if args.skip_combined:
        result["phases"][COMBINED] = _skipped_phase(COMBINED, "--skip-combined")
        combined_summary = None
    elif (
        native_phase.get("status") != "completed"
        or gerber_phase.get("status") != "completed"
    ):
        result["phases"][COMBINED] = _blocked_phase(
            COMBINED, "combined contract requires native and strict contracts"
        )
        combined_summary = None
    else:
        from kicad_dfm.services.analysis_results import merge_analysis_contracts

        combined_started = time.perf_counter()
        combined_contract = merge_analysis_contracts(
            load_contract(native_artifact), load_contract(gerber_artifact)
        )
        write_contract(combined_artifact, combined_contract)
        combined_summary = contract_observation(combined_contract)
        result["phases"][COMBINED] = {
            "status": "completed",
            "phase": COMBINED,
            "wall_ms": elapsed_ms(combined_started),
            "summary": combined_summary,
            "artifact": str(combined_artifact),
        }

    result["gates"] = evaluate_gates(
        asset,
        native_summary=native_summary,
        gerber_summary=gerber_summary,
        combined=combined_summary,
    )
    failing_phase = any(
        phase.get("status") in ("failed", "timeout")
        for phase in result["phases"].values()
    )
    failed_gate = any(gate.get("status") == "failed" for gate in result["gates"])
    completed_count = sum(
        phase.get("status") == "completed" for phase in result["phases"].values()
    )
    if failing_phase or failed_gate:
        result["status"] = "failed"
    elif not completed_count:
        result["status"] = "skipped"
    else:
        result["status"] = "passed"
    for phase in result["phases"].values():
        if phase.get("artifact"):
            phase["artifact_retained"] = bool(args.contract_dir)
            if not args.contract_dir:
                phase.pop("artifact", None)
    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Verify bundled assets through isolated kicad_native and "
            "gerber_strict workers, then build a combined contract."
        )
    )
    parser.add_argument("--repo", default=str(REPO_ROOT))
    parser.add_argument("--assets-dir", default=str(REPO_ROOT / "assets"))
    parser.add_argument(
        "--assets",
        nargs="+",
        choices=tuple(ASSETS),
        default=tuple(ASSETS),
        metavar="ASSET",
        help="Assets to verify (default: pic flat video amulet).",
    )
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--kicad-python", default=default_kicad_python())
    parser.add_argument(
        "--gerber-source",
        choices=("auto", "existing", "export"),
        default="auto",
        help="Prefer existing assets/HQDMF packages or export into a temporary directory.",
    )
    parser.add_argument("--skip-native", action="store_true")
    parser.add_argument("--skip-gerber", action="store_true")
    parser.add_argument("--skip-combined", action="store_true")
    parser.add_argument(
        "--skip-slow",
        action="store_true",
        help="Skip the amulet native and strict-Gerber phases.",
    )
    parser.add_argument(
        "--skip-temp-export",
        action="store_true",
        help="In auto mode, skip Gerber when no existing package is available.",
    )
    parser.add_argument("--load-timeout", type=float, default=90.0)
    parser.add_argument("--native-timeout", type=float, default=300.0)
    parser.add_argument("--gerber-timeout", type=float, default=900.0)
    parser.add_argument(
        "--contract-dir",
        help="Optionally retain full stage/combined contracts; defaults to temporary files.",
    )
    parser.add_argument("--output", help="Write the JSON summary to this file.")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    return parser


def parent_main(argv):
    args = build_parser().parse_args(argv)
    args.repo = str(Path(args.repo).resolve())
    args.assets_dir = str(Path(args.assets_dir).resolve())
    args.kicad_python = str(Path(args.kicad_python).resolve())
    if not Path(args.kicad_python).is_file():
        raise SystemExit("KiCad Python not found: {0}".format(args.kicad_python))
    sys.path.insert(0, args.repo)

    started_at = time.perf_counter()
    started_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report = {
        "schema_version": SCHEMA_VERSION,
        "tool": "verify_combined_assets",
        "started_at": started_iso,
        "repo": args.repo,
        "assets_dir": args.assets_dir,
        "kicad_python": args.kicad_python,
        "profile": args.profile,
        "settings": {
            "assets": list(args.assets),
            "gerber_source": args.gerber_source,
            "skip_native": args.skip_native,
            "skip_gerber": args.skip_gerber,
            "skip_combined": args.skip_combined,
            "skip_slow": args.skip_slow,
            "skip_temp_export": args.skip_temp_export,
            "timeouts_seconds": {
                LOAD_BOARD: args.load_timeout,
                KICAD_NATIVE: args.native_timeout,
                GERBER_STRICT: args.gerber_timeout,
            },
            "modifies_assets": False,
        },
        "assets": {},
    }

    with tempfile.TemporaryDirectory(prefix="hqdfm-combined-assets-") as work_root:
        for asset in args.assets:
            report["assets"][asset] = verify_asset(args, asset, work_root)
            if args.fail_fast and report["assets"][asset]["status"] == "failed":
                break

    statuses = collections.Counter(
        result.get("status", "failed") for result in report["assets"].values()
    )
    report["totals"] = {
        "assets": len(report["assets"]),
        "passed": statuses.get("passed", 0),
        "failed": statuses.get("failed", 0),
        "skipped": statuses.get("skipped", 0),
    }
    report["duration_ms"] = elapsed_ms(started_at)
    indent = None if args.compact else 2
    rendered = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        indent=indent,
    )
    output_error = None
    if args.output:
        output = Path(args.output).resolve()
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            output_error = exc
    print(rendered)
    if output_error is not None:
        print(
            "Unable to write --output {0}: {1}".format(args.output, output_error),
            file=sys.stderr,
        )
        return 1
    return 1 if report["totals"]["failed"] else 0


def main(argv=None):
    # Windows may expose a legacy GBK console even though the report contains
    # valid Unicode such as square-metre symbols.  Keep stdout/stderr aligned
    # with the UTF-8 JSON files emitted by this tool instead of failing after
    # an expensive asset scan has already completed.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, OSError, ValueError):
                pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--worker-phase" in argv:
        return worker_main(argv)
    return parent_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
