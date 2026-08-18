import os
import time

from kicad_dfm.core.logging import get_logger
from kicad_dfm.core.files import is_safe_zip_name, zip_entries
from kicad_dfm.core.models import DfmIssue, DfmSummary
from kicad_dfm.core.pad_size import pad_shorter_side_mm, pad_size_item
from kicad_dfm.core.progress import report_progress
from kicad_dfm.core.rule_contract import rule_key
from kicad_dfm.services.export_geometry import scan_gerber as scan_gerber
from kicad_dfm.services.export_parsers import gerber_file_function
from kicad_dfm.services.export_parsers import parse_excellon_scan
from kicad_dfm.services.export_parsers import parse_gerber_scan
from kicad_dfm.services.export_result_helpers import aggregate_color
from kicad_dfm.services.export_result_helpers import aggregate_physical_native_results
from kicad_dfm.services.export_result_helpers import grouped_native_results
from kicad_dfm.services.export_result_helpers import is_copper_layer_name
from kicad_dfm.services.export_result_helpers import is_mask_layer_name
from kicad_dfm.services.export_result_helpers import layer_name_from_file
from kicad_dfm.services.export_result_helpers import layer_name_from_file_function
from kicad_dfm.services.export_result_helpers import location_fields
from kicad_dfm.services.export_result_helpers import native_finding_key
from kicad_dfm.services.export_result_helpers import safe_float
from kicad_dfm.services.result_object_mapper import GerberResultObjectMapper
from kicad_dfm.services.board_statistics import calculate_board_statistics
from kicad_dfm.services.board_statistics import statistic_result_map
from kicad_dfm.services.export_scanners import scan_copper_spacing
from kicad_dfm.services.export_scanners import scan_castellated_holes
from kicad_dfm.services.export_scanners import scan_hole_to_board_edge
from kicad_dfm.services.export_scanners import scan_copper_to_board_edge
from kicad_dfm.services.export_scanners import scan_drill_to_copper
from kicad_dfm.services.export_scanners import scan_drill_spacing
from kicad_dfm.services.export_scanners import scan_pad_drill_features
from kicad_dfm.services.export_scanners import scan_smd_pad_size
from kicad_dfm.services.export_scanners import scan_signal_integrity
from kicad_dfm.services.export_scanners import scan_missing_smask_openings
from kicad_dfm.services.export_scanners import scan_solder_mask_analysis
from kicad_dfm.settings.color_rule import ColorRule


CATEGORY = "Gerber Export"
COPPER_SPACING_TIE_TOLERANCE_MM = 0.00005
LOGGER = get_logger(__name__)
BLOCKING_EXPORT_ITEMS = {
    "Empty Export Directory",
    "Missing Layer File",
    "Empty Layer File",
    "Missing Board Outline",
    "Missing Drill File",
    "Copper Layer Count Mismatch",
    "Zip Package Error",
    "Geometry Parse Error",
    "Empty Board Outline",
}

# Categories whose fabrication-file scanners are executed by
# ``_scan_outputs``.  Keep statistics out of this list: Gerber/Excellon data
# alone does not currently implement those calculations, so their absence
# must continue to mean ``not_computed`` in the shared contract.
STRICT_SCANNER_CATEGORIES = (
    "Signal Integrity",
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
    "Missing SMask Openings",
    "Solder Mask Analysis",
)


def analyze_export(
    export_result,
    rules=None,
    expected_output_name="HQDMF",
    progress_callback=None,
    is_cancelled=None,
    board_thickness_mm=None,
    board=None,
    backend=None,
    chinese=False,
):
    checks = ExportChecks(
        export_result,
        rules=rules,
        expected_output_name=expected_output_name,
        board_thickness_mm=board_thickness_mm,
        board=board,
        backend=backend,
        chinese=chinese,
    )
    return checks.analyze(progress_callback, is_cancelled)


def analyze_export_with_results(
    export_result,
    rules=None,
    expected_output_name="HQDMF",
    include_profile=False,
    progress_callback=None,
    is_cancelled=None,
    board_thickness_mm=None,
    board=None,
    backend=None,
    chinese=False,
):
    checks = ExportChecks(
        export_result,
        rules=rules,
        expected_output_name=expected_output_name,
        board_thickness_mm=board_thickness_mm,
        board=board,
        backend=backend,
        chinese=chinese,
    )
    issues, summary = checks.analyze(progress_callback, is_cancelled)
    if include_profile:
        return issues, summary, checks.native_result_map(), checks.profile
    return issues, summary, checks.native_result_map()


def is_blocking_export_issue(issue):
    return issue.severity == "error" and issue.item in BLOCKING_EXPORT_ITEMS


class ExportChecks:
    def __init__(
        self,
        export_result,
        rules=None,
        expected_output_name="HQDMF",
        board_thickness_mm=None,
        board=None,
        backend=None,
        chinese=False,
    ):
        self.export_result = export_result
        self.rules = rules
        self.expected_output_name = expected_output_name
        self.board_thickness_mm = board_thickness_mm
        self.board = board
        self.backend = backend
        self.chinese = chinese
        self.result_mapper = (
            GerberResultObjectMapper(board, backend)
            if board is not None and backend is not None
            else None
        )
        self.color_rule = ColorRule(rules)
        self.issues = []
        self.native_results = {}
        self._completed_scanner_categories = set()
        self._native_net_tie_pad_groups_cache = None
        self._native_net_tie_member_ids_cache = None
        self._native_net_tie_footprint_pad_ids_cache = None
        self._native_net_tie_items_cache = {}
        self.profile = {}
        self._progress_callback = None
        self._is_cancelled = None

    def analyze(self, progress_callback=None, is_cancelled=None):
        started_at = time.perf_counter()
        self._progress_callback = progress_callback
        self._is_cancelled = is_cancelled
        phases = (
            ("Checking output directory", self._check_output_dir),
            ("Checking exported files", self._check_files),
            ("Checking ZIP package", self._check_zip),
            ("Scanning exported geometry", self._scan_outputs),
        )
        for index, (label, operation) in enumerate(phases):
            report_progress(
                progress_callback,
                is_cancelled,
                index,
                len(phases),
                label,
            )
            operation()
        report_progress(
            progress_callback,
            is_cancelled,
            len(phases),
            len(phases),
            "Finalizing results",
        )
        issues = tuple(self.issues)
        self.profile["total_ms"] = elapsed_ms(started_at)
        self.profile["issue_count"] = len(issues)
        self.profile["native_result_count"] = sum(len(rows) for rows in self.native_results.values())
        LOGGER.debug("export_dfm_analysis profile=%s", self.profile)
        return issues, {CATEGORY: self._summary(issues)}

    def _check_output_dir(self):
        output_dir = self.export_result.output_dir
        if not self._is_expected_output_dir(output_dir):
            self._add_issue(
                "Wrong Output Directory",
                "warning",
                "Gerber files were written outside {0}/Gerber_<board>: {1}".format(
                    self.expected_output_name, output_dir
                ),
                raw={"output_dir": output_dir},
            )
        if self.export_result.fallback_used:
            message = "Gerber export used fallback output directory: {0}".format(output_dir)
            self._add_issue(
                "Wrong Output Directory",
                "warning",
                message,
                raw={"output_dir": output_dir, "fallback_used": True},
            )
        for warning in self.export_result.warnings:
            self._add_issue(
                "Wrong Output Directory",
                "warning",
                str(warning),
                raw={"output_dir": output_dir, "warning": str(warning)},
            )

    def _is_expected_output_dir(self, output_dir):
        path = os.path.normpath(output_dir)
        name = os.path.basename(path)
        parent = os.path.basename(os.path.dirname(path))
        if name.startswith("Gerber_") and parent == self.expected_output_name:
            return True
        return name == self.expected_output_name

    def _check_files(self):
        files = tuple(self.export_result.files or ())
        output_dir = self.export_result.output_dir
        if not os.path.isdir(output_dir) or not files:
            self._add_issue(
                "Empty Export Directory",
                "error",
                "{0} has no exported files.".format(output_dir),
                raw={"output_dir": output_dir},
            )
            return

        planned = self._planned_files()
        for layer_name, path in planned.items():
            if not self._is_required_layer(layer_name):
                continue
            path = self._existing_layer_file(layer_name, path)
            if not os.path.exists(path):
                self._add_issue(
                    "Missing Layer File",
                    "error",
                    "{0} is missing.".format(path),
                    layer=[self._display_layer(layer_name)],
                    raw={"file": path, "layer": layer_name},
                )
            elif os.path.getsize(path) <= 0:
                self._add_issue(
                    "Empty Layer File",
                    "error",
                    "{0} is empty.".format(path),
                    layer=[self._display_layer(layer_name)],
                    raw={"file": path, "layer": layer_name},
                )

        edge_path = self._existing_layer_file(
            "EdgeCuts",
            planned.get("EdgeCuts") or self._find_by_stem("EdgeCuts", ".gbr"),
        )
        if not edge_path or not os.path.exists(edge_path) or os.path.getsize(edge_path) <= 0:
            self._add_issue(
                "Missing Board Outline",
                "error",
                "EdgeCuts.gbr is missing or empty.",
                layer=["Edge.Cuts"],
                raw={"file": edge_path},
            )

        drill_files = self._drill_files()
        if not drill_files:
            self._add_issue(
                "Missing Drill File",
                "error",
                "No Excellon drill file was exported.",
                layer=["Drl"],
                raw={"output_dir": output_dir},
            )
        elif not any(os.path.getsize(path) > 0 for path in drill_files):
            self._add_issue(
                "Missing Drill File",
                "error",
                "All exported drill files are empty.",
                layer=["Drl"],
                raw={"files": drill_files},
            )

        if not self._drill_map_files():
            self._add_issue(
                "Missing Drill Map",
                "warning",
                "No drill map file was exported.",
                layer=["Drl"],
                raw={"output_dir": output_dir},
            )

        expected_copper = int(self.export_result.layer_count or 0)
        actual_copper = 0
        for layer_name, path in planned.items():
            if not is_copper_layer_name(layer_name):
                continue
            path = self._existing_layer_file(layer_name, path)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                actual_copper += 1
        if expected_copper and actual_copper != expected_copper:
            self._add_issue(
                "Copper Layer Count Mismatch",
                "error",
                "Expected {0} copper Gerber files, found {1}.".format(
                    expected_copper, actual_copper
                ),
                raw={"expected": expected_copper, "actual": actual_copper},
            )

    def _check_zip(self):
        zip_path = self.export_result.zip_path
        if not zip_path or not os.path.isfile(zip_path) or os.path.getsize(zip_path) <= 0:
            self._add_issue(
                "Zip Package Error",
                "error",
                "ZIP package is missing or empty: {0}".format(zip_path),
                raw={"zip_path": zip_path},
            )
            return

        entries = zip_entries(zip_path)
        if not entries:
            self._add_issue(
                "Zip Package Error",
                "error",
                "ZIP package cannot be read or has no entries: {0}".format(zip_path),
                raw={"zip_path": zip_path},
            )
            return

        names = {entry.filename.replace("\\", "/") for entry in entries}
        for entry in entries:
            if not is_safe_zip_name(entry.filename):
                self._add_issue(
                    "Zip Package Error",
                    "error",
                    "ZIP contains unsafe path: {0}".format(entry.filename),
                    raw={"zip_path": zip_path, "entry": entry.filename},
                )
            if (
                not entry.is_dir()
                and entry.file_size <= 0
                and not self._is_optional_empty_zip_entry(entry.filename)
            ):
                self._add_issue(
                    "Zip Package Error",
                    "error",
                    "ZIP contains empty file: {0}".format(entry.filename),
                    raw={"zip_path": zip_path, "entry": entry.filename},
                )

        for path in self.export_result.files or ():
            if not os.path.isfile(path):
                continue
            relpath = os.path.relpath(path, self.export_result.output_dir).replace("\\", "/")
            if relpath not in names:
                self._add_issue(
                    "Zip Package Error",
                    "error",
                    "ZIP package is missing exported file: {0}".format(relpath),
                    raw={"zip_path": zip_path, "file": path, "entry": relpath},
                )

    def _scan_outputs(self):
        started_at = time.perf_counter()
        result_count = 0
        gerber_scans = []
        drill_scans = []
        files_seen = 0
        files_parsed = 0
        skipped_empty = 0
        skipped_geometry = 0
        parse_errors = 0
        for path in self.export_result.files or ():
            self._scan_checkpoint()
            if not os.path.isfile(path):
                continue
            files_seen += 1
            if os.path.getsize(path) <= 0:
                skipped_empty += 1
                continue
            lower = path.lower()
            if lower.endswith((".gbr", ".ger")):
                if not self._should_scan_gerber_geometry(path):
                    skipped_geometry += 1
                    continue
                try:
                    scan = parse_gerber_scan(path)
                except Exception as exc:
                    parse_errors += 1
                    self._add_parse_error(path, "Gerber", exc)
                    continue
                files_parsed += 1
                gerber_scans.append(scan)
                for finding in scan.findings:
                    result_count += self._add_scan_finding(finding)
            elif lower.endswith((".drl", ".xln")):
                try:
                    scan = parse_excellon_scan(
                        path,
                        None,
                        self.board_thickness_mm,
                    )
                except Exception as exc:
                    parse_errors += 1
                    self._add_parse_error(path, "Excellon", exc)
                    continue
                files_parsed += 1
                drill_scans.append(scan)
                for finding in scan.findings:
                    result_count += self._add_scan_finding(finding)
        scan_profile = {
            "elapsed_ms": 0.0,
            "files_seen": files_seen,
            "files_parsed": files_parsed,
            "skipped_empty": skipped_empty,
            "skipped_non_geometry": skipped_geometry,
            "parse_errors": parse_errors,
            "gerber_files": len(gerber_scans),
            "drill_files": len(drill_scans),
            "issue_findings": result_count,
            "native_results": sum(len(rows) for rows in self.native_results.values()),
            "capped": False,
        }
        self._scan_checkpoint()
        drill_spacing_limit = self._drill_spacing_reporting_limit()
        if self._uses_remote_pad_contract():
            # The remote report includes near-limit black drill gaps.
            drill_spacing_limit = max(float(drill_spacing_limit or 0.0), 0.7)
        for finding in scan_drill_spacing(
            drill_scans,
            drill_spacing_limit,
            checkpoint=lambda: self._scan_checkpoint("Checking drill spacing"),
        ):
            result_count += self._add_scan_finding(finding)
        self._scan_checkpoint()
        for finding in scan_copper_spacing(
            gerber_scans,
            self._copper_spacing_reporting_limits(),
            checkpoint=lambda: self._scan_checkpoint("Checking copper spacing"),
        ):
            result_count += self._add_scan_finding(finding)
        self._scan_checkpoint()
        for finding in scan_smd_pad_size(gerber_scans):
            result_count += self._add_scan_finding(finding)
        self._scan_checkpoint()
        for finding in scan_pad_drill_features(
            drill_scans,
            gerber_scans,
            include_drilled_pad_size=not self._uses_remote_pad_contract(),
            holes_overlap_ratio=self._uses_remote_pad_contract(),
        ):
            result_count += self._add_scan_finding(finding)
        self._scan_checkpoint()
        for finding in scan_drill_to_copper(
            drill_scans,
            gerber_scans,
            self._drill_to_copper_reporting_limits(),
            checkpoint=lambda: self._scan_checkpoint("Checking drill-to-copper clearance"),
        ):
            result_count += self._add_scan_finding(finding)
        self._scan_checkpoint()
        for finding in scan_copper_to_board_edge(
            gerber_scans,
            drill_scans,
            self._board_edge_reporting_limits(),
        ):
            result_count += self._add_scan_finding(finding)
        self._scan_checkpoint()
        for finding in scan_hole_to_board_edge(
            drill_scans,
            gerber_scans,
            self._hole_to_board_edge_reporting_limits(),
            checkpoint=lambda: self._scan_checkpoint(
                "Checking hole-to-board-edge clearance"
            ),
        ):
            result_count += self._add_scan_finding(finding)
        supplemental_scans = (
            scan_castellated_holes(drill_scans, gerber_scans),
            scan_signal_integrity(
                gerber_scans,
                checkpoint=lambda: self._scan_checkpoint("Checking signal integrity"),
            ),
            scan_missing_smask_openings(
                drill_scans,
                gerber_scans,
                checkpoint=lambda: self._scan_checkpoint(
                    "Checking solder-mask openings"
                ),
            ),
            scan_solder_mask_analysis(
                gerber_scans,
                self._solder_mask_reporting_limits(),
                checkpoint=lambda: self._scan_checkpoint("Checking solder mask"),
            ),
        )
        for findings in supplemental_scans:
            self._scan_checkpoint()
            for finding in findings:
                result_count += self._add_scan_finding(finding)
        scan_profile["elapsed_ms"] = elapsed_ms(started_at)
        scan_profile["issue_findings"] = result_count
        scan_profile["native_results"] = sum(len(rows) for rows in self.native_results.values())
        scan_profile["capped"] = False
        self.profile["scan_outputs"] = scan_profile
        self._completed_scanner_categories.update(STRICT_SCANNER_CATEGORIES)

    def _scan_checkpoint(self, label="Scanning exported geometry"):
        report_progress(
            self._progress_callback,
            self._is_cancelled,
            3,
            4,
            label,
        )

    def _should_scan_gerber_geometry(self, path):
        layer_name = layer_name_from_file_function(
            gerber_file_function(path)
        ) or layer_name_from_file(path)
        return (
            is_copper_layer_name(layer_name)
            or is_mask_layer_name(layer_name)
            or layer_name == "Edge.Cuts"
            or "edge" in os.path.basename(path).lower()
            or "mask" in os.path.basename(path).lower()
        )

    def _add_scan_finding(self, finding):
        if finding.category and finding.item:
            rule = finding.rule or self.color_rule.default_rule_for(
                self._rule_category(finding.category),
                finding.item,
            )
            color = finding.color or self._finding_color(finding, rule)
            data = self._native_result(finding, rule, color)
            if (
                finding.category == "Missing SMask Openings"
                and self.result_mapper is not None
            ):
                data = self._mapped_missing_smask_result(data)
                if data is None:
                    return 0
            if (
                finding.category == "Hole-to-Board Edge"
                and self.result_mapper is not None
            ):
                data = self._mapped_hole_to_board_edge_result(data)
                rule = data.get("rule") or rule
            self._apply_measurement_uncertainty(finding.category, data, rule)
            if (
                finding.category in (
                    "Smallest Trace Spacing",
                    "SMD Spacing",
                )
                and self.result_mapper is not None
            ):
                data = self._mapped_copper_spacing_result(finding, data)
                if data is None:
                    return 0
            if finding.category == "Pad size" and self.result_mapper is not None:
                data = self._mapped_pad_size_result(finding, data)
            if (
                finding.category == "Holes on SMD Pads"
                and self.result_mapper is not None
            ):
                # Holes-on-pad findings carry a drill as the primary object and
                # the X2 SMD pad as the related object.  Map both so locating a
                # result selects the actual via/hole and exact native pad rather
                # than drawing a Gerber bounding-box fallback over a nearby
                # custom pad.
                self._apply_mapping_preserving_measurement(data)
            if (
                finding.category == "Solder Mask Analysis"
                and self.result_mapper is not None
            ):
                # The mask Gerber itself normally has no X2 component/pad
                # attributes.  The scanner supplies the copper pad/trace
                # anchors for both sides, allowing these findings to resolve
                # to native KiCad objects while retaining the exact Gerber gap
                # segment as a drawing fallback.
                self._apply_mapping_preserving_measurement(data)
            if (
                finding.category == "Drill Hole Spacing"
                and finding.item == "Different Net PTH Spacing"
                and self.result_mapper is not None
            ):
                self._mapped_drill_spacing_item(data)
            self._record_native_result(finding.category, data)
            return 0
        self._add_issue(
            finding.item,
            finding.severity,
            finding.message,
            layer=finding.layer,
            raw=finding.raw,
        )
        return 1

    def _mapped_missing_smask_result(self, data):
        """Suppress a Gerber missing-opening result proven to be a NetTie pad."""
        mapping = self._apply_mapping_preserving_measurement(data)
        if mapping.status not in ("matched", "already_mapped"):
            return data
        mapped_id = str(
            data.get("id") or getattr(mapping, "item_id", "") or ""
        )
        if mapped_id not in self._native_net_tie_footprint_pad_ids():
            return data
        data.setdefault("raw", {})["suppressed_reason"] = "net_tie_footprint"
        return None

    def _mapped_pad_size_result(self, finding, data):
        mapping = self._apply_mapping_preserving_measurement(data)
        if mapping.status != "matched" or not self.backend.is_pad(mapping.item):
            return data
        size_reader = getattr(self.backend, "pad_size_mm", None)
        if size_reader is None:
            return data
        try:
            size_x, size_y = (abs(float(value)) for value in size_reader(mapping.item))
        except (TypeError, ValueError):
            return data
        short = pad_shorter_side_mm(size_x, size_y)
        if short <= 0:
            return data
        item = pad_size_item(size_x, size_y)
        raw = data.setdefault("raw", {})
        raw.setdefault("gerber_value", data.get("value"))
        raw.setdefault("gerber_pad_size", raw.get("pad_size"))
        raw["native_value"] = "{0:.6f}".format(short)
        raw["native_pad_size"] = (size_x, size_y)
        raw["native_item"] = item
        raw["native_measurement_basis"] = "kicad_pad_size"
        raw["native_rule"] = self.color_rule.default_rule_for(
            finding.category, item
        )
        raw["native_color"] = self.color_rule.get_rule(
            {}, finding.category, item, short
        )
        return data

    def _mapped_copper_spacing_result(self, finding, data):
        primary, related = self.result_mapper.map_pair(data)
        self._record_pair_mapping(data, primary, related)
        candidate_pairs = ()
        if primary.status == "matched" and related is not None and related.status == "matched":
            candidate_pairs = ((primary.item, related.item),)
        elif (
            related is not None
            and primary.status in ("matched", "ambiguous")
            and related.status in ("matched", "ambiguous")
            and hasattr(self.result_mapper, "map_pair_candidates")
        ):
            left_candidates, right_candidates = self.result_mapper.map_pair_candidates(data)
            candidate_pairs = tuple(
                (left.item, right.item)
                for left in left_candidates
                for right in right_candidates
            )
        if not candidate_pairs:
            return data

        clearance_reader = getattr(self.backend, "item_clearance_nm", None)
        gerber_value = safe_float(data.get("value"), None)
        gerber_clearance_nm = (
            float(gerber_value) * 1000000.0
            if gerber_value is not None
            else 0.0
        )
        measured = []
        have_unmeasured_candidate = False
        for left, right in candidate_pairs:
            relation = self._native_electrical_relation(left, right)
            if len(candidate_pairs) == 1 and relation:
                raw = data.setdefault("raw", {})
                raw["suppressed_reason"] = relation
                raw["native_pair_count"] = 1
                return None
            if self.backend.is_via(left) or self.backend.is_via(right):
                continue
            item = self._mapped_copper_spacing_item(finding.item, left, right)
            if item is None:
                continue
            clearance_nm = (
                clearance_reader(left, right, 5000000)
                if clearance_reader is not None
                else None
            )
            if clearance_nm is None:
                have_unmeasured_candidate = True
                continue
            clearance_nm = float(clearance_nm)
            if not relation and self._native_net_tie_contact(left, right):
                # The declared member pads form one intentional NetTie
                # structure even when their exported copper has a positive
                # gap.  Pad-to-track exemptions remain contact-local.
                pad_pair = bool(
                    self.backend.is_pad(left)
                    and self.backend.is_pad(right)
                )
                if pad_pair or abs(clearance_nm) <= 1.0:
                    relation = "net_tie"
            measured.append(
                (
                    abs(clearance_nm - gerber_clearance_nm),
                    clearance_nm,
                    item,
                    left,
                    right,
                    relation,
                )
            )
        if not measured:
            return data
        if have_unmeasured_candidate and len(candidate_pairs) > 1:
            # An unmeasured ambiguous candidate cannot be ranked against the
            # Gerber observation.  Keep the strict evidence conservatively.
            return data
        closest_difference = min(result[0] for result in measured)
        closest = [
            result
            for result in measured
            if result[0] <= closest_difference + 1.0
        ]
        reportable = [result for result in closest if not result[5]]
        if not reportable:
            relations = {result[5] for result in closest}
            raw = data.setdefault("raw", {})
            raw["suppressed_reason"] = (
                "same_object"
                if "same_object" in relations
                else "same_net"
                if "same_net" in relations
                else "net_tie"
            )
            raw["native_pair_count"] = len(candidate_pairs)
            raw["closest_native_pair_count"] = len(closest)
            raw["native_mapping_delta_nm"] = closest_difference
            return None
        (
            mapping_difference,
            clearance_nm,
            item,
            left,
            right,
            _relation,
        ) = min(reportable, key=lambda result: (result[0], result[1]))

        original_value = data.get("value")
        native_value = max(0.0, float(clearance_nm) / 1000000.0)
        data.setdefault("raw", {}).setdefault("gerber_value", original_value)
        data["raw"]["native_value"] = "{0:.6f}".format(native_value)
        data["raw"]["native_measurement_basis"] = "kicad_effective_shape"
        data["raw"]["candidate_pair_count"] = len(candidate_pairs)
        data["raw"]["closest_native_pair_count"] = len(closest)
        data["raw"]["native_mapping_delta_nm"] = mapping_difference
        item_id_reader = getattr(self.backend, "item_id", None)
        if item_id_reader is not None:
            data["id"] = item_id_reader(left)
            data["related_id"] = item_id_reader(right)
        data["raw"]["native_item"] = item
        rule_category = self._rule_category(finding.category)
        data["raw"]["native_rule"] = self.color_rule.default_rule_for(
            rule_category, item
        )
        data["raw"]["native_color"] = self.color_rule.get_rule(
            {}, rule_category, item, native_value
        )
        return data

    def _native_electrical_relation(self, left, right):
        """Classify authoritative KiCad equivalence for a mapped copper pair."""
        if left is right:
            return "same_object"
        item_id_reader = getattr(self.backend, "item_id", None)
        if item_id_reader is not None:
            try:
                left_id = str(item_id_reader(left) or "")
                right_id = str(item_id_reader(right) or "")
            except Exception:
                left_id = right_id = ""
            if left_id and left_id == right_id:
                return "same_object"

        net_reader = getattr(self.backend, "item_net_name", None)
        if net_reader is None:
            return ""
        try:
            left_net = str(net_reader(left) or "")
            right_net = str(net_reader(right) or "")
        except Exception:
            return ""
        if not left_net or not right_net:
            return ""
        if left_net == right_net:
            return "same_net"
        return ""

    def _native_net_tie_contact(self, left, right):
        """Confirm a pair belongs to one declared, local net-tie structure.

        Net names joined by a net tie are not globally exempt from clearance.
        A pair of declared member pads is one exempt logical structure.  An
        ordinary pad is also local to that structure when it is on one member
        net and is no farther from that member pad than the member's explicit
        KiCad local-clearance override.  This second case covers copper that
        is intentionally attached immediately beside a NetTie member without
        extending the exemption to the rest of either net.  A pad/track
        relation is only a candidate here; the caller additionally requires
        actual zero-clearance contact for that case.
        """
        groups = self._native_net_tie_pad_groups()
        if not groups:
            return False
        item_id_reader = getattr(self.backend, "item_id", None)
        net_reader = getattr(self.backend, "item_net_name", None)
        if item_id_reader is None or net_reader is None:
            return False
        try:
            left_id = str(item_id_reader(left) or "")
            right_id = str(item_id_reader(right) or "")
            left_net = str(net_reader(left) or "")
            right_net = str(net_reader(right) or "")
        except Exception:
            return False
        left_pad = bool(self.backend.is_pad(left))
        right_pad = bool(self.backend.is_pad(right))
        left_track = bool(self.backend.is_track(left))
        right_track = bool(self.backend.is_track(right))
        for group in groups:
            members = {
                pad_id: net_name
                for pad_id, net_name in group
                if pad_id and net_name
            }
            net_names = set(members.values())
            left_is_member = bool(left_id and members.get(left_id) == left_net)
            right_is_member = bool(right_id and members.get(right_id) == right_net)
            if left_pad and right_pad and left_is_member and right_is_member:
                return True
            if (
                left_pad
                and right_pad
                and left_is_member
                and not right_is_member
                and self._native_pad_attached_to_net_tie_member(
                    right,
                    right_id,
                    right_net,
                    members,
                    left_id,
                )
            ):
                return True
            if (
                left_pad
                and right_pad
                and right_is_member
                and not left_is_member
                and self._native_pad_attached_to_net_tie_member(
                    left,
                    left_id,
                    left_net,
                    members,
                    right_id,
                )
            ):
                return True
            if (
                left_pad
                and right_track
                and left_is_member
                and right_net in net_names
            ):
                return True
            if (
                right_pad
                and left_track
                and right_is_member
                and left_net in net_names
            ):
                return True
        return False

    def _native_pad_attached_to_net_tie_member(
        self,
        pad,
        pad_id,
        pad_net,
        members,
        reported_member_id,
    ):
        """Return whether ``pad`` is geometrically local to its group member.

        The test deliberately uses direct shape clearance, not KiCad's
        transitive connectivity component.  Connectivity would make every
        object on the same routed net inherit the NetTie exemption.
        """
        if not pad_net or pad_net not in set(members.values()):
            return False
        if pad_id and pad_id in self._native_net_tie_member_ids():
            # A pad declared by this or any other NetTie group is not an
            # ordinary attachment.  In particular, two adjacent groups that
            # share a net name must never inherit each other's exemption.
            return False
        clearance_reader = getattr(self.backend, "item_clearance_nm", None)
        if clearance_reader is None:
            return False
        for member_id, member_net in members.items():
            if member_id == reported_member_id or member_net != pad_net:
                continue
            member = self._resolve_native_net_tie_item(member_id, member_net)
            if member is None:
                continue
            if not self._native_pads_share_copper_layer(pad, member):
                continue
            local_clearance_nm = self._native_item_local_clearance_nm(member)
            attachment_limit_nm = max(
                1.0,
                float(local_clearance_nm)
                if local_clearance_nm is not None
                else 0.0,
            )
            try:
                clearance_nm = clearance_reader(
                    pad,
                    member,
                    int(attachment_limit_nm) + 1,
                )
            except Exception:
                continue
            if (
                clearance_nm is not None
                and float(clearance_nm) <= attachment_limit_nm
            ):
                return True
        return False

    def _native_net_tie_member_ids(self):
        cached = self._native_net_tie_member_ids_cache
        if cached is not None:
            return cached
        cached = frozenset(
            member_id
            for group in self._native_net_tie_pad_groups()
            for member_id, _net_name in group
            if member_id
        )
        self._native_net_tie_member_ids_cache = cached
        return cached

    def _native_net_tie_footprint_pad_ids(self):
        cached = self._native_net_tie_footprint_pad_ids_cache
        if cached is not None:
            return cached
        reader = getattr(self.backend, "net_tie_footprint_pad_ids", None)
        if reader is None:
            cached = frozenset()
        else:
            try:
                cached = frozenset(
                    str(pad_id) for pad_id in reader() or () if pad_id
                )
            except Exception:
                cached = frozenset()
        self._native_net_tie_footprint_pad_ids_cache = cached
        return cached

    def _native_pads_share_copper_layer(self, left, right):
        reader = getattr(self.backend, "pad_copper_layer_ids", None)
        if reader is None:
            return True
        try:
            left_layers = reader(left)
            right_layers = reader(right)
        except Exception:
            return True
        if left_layers is None or right_layers is None:
            return True
        return bool(set(left_layers).intersection(right_layers))

    def _resolve_native_net_tie_item(self, item_id, expected_net):
        if item_id in self._native_net_tie_items_cache:
            return self._native_net_tie_items_cache[item_id]
        resolver = getattr(self.backend, "resolve_item", None)
        if resolver is None:
            self._native_net_tie_items_cache[item_id] = None
            return None
        try:
            item = resolver(item_id)
        except Exception:
            item = None
        if item is not None:
            item_id_reader = getattr(self.backend, "item_id", None)
            net_reader = getattr(self.backend, "item_net_name", None)
            try:
                valid = bool(
                    self.backend.is_pad(item)
                    and item_id_reader is not None
                    and str(item_id_reader(item) or "") == item_id
                    and net_reader is not None
                    and str(net_reader(item) or "") == expected_net
                )
            except Exception:
                valid = False
            if not valid:
                item = None
        self._native_net_tie_items_cache[item_id] = item
        return item

    def _native_item_local_clearance_nm(self, item):
        reader = getattr(self.backend, "item_local_clearance_nm", None)
        if reader is not None:
            try:
                value = reader(item)
            except Exception:
                value = None
            if value is not None:
                try:
                    return max(0.0, float(value))
                except (TypeError, ValueError):
                    pass
        method = getattr(item, "GetLocalClearance", None)
        if method is None:
            return None
        try:
            return max(0.0, float(method()))
        except Exception:
            return None

    def _native_net_tie_pad_groups(self):
        cached = self._native_net_tie_pad_groups_cache
        if cached is not None:
            return cached
        group_reader = getattr(self.backend, "net_tie_pad_groups", None)
        if group_reader is None:
            self._native_net_tie_pad_groups_cache = ()
            return self._native_net_tie_pad_groups_cache
        try:
            groups = tuple(group_reader() or ())
        except Exception:
            groups = ()
        normalized = []
        for group in groups:
            members = []
            for member in group or ():
                if not isinstance(member, (tuple, list)) or len(member) < 2:
                    continue
                pad_id = str(member[0] or "")
                net_name = str(member[1] or "")
                if pad_id or net_name:
                    members.append((pad_id, net_name))
            if len(members) >= 2:
                normalized.append(tuple(members))
        self._native_net_tie_pad_groups_cache = tuple(normalized)
        return self._native_net_tie_pad_groups_cache

    def _apply_mapping_preserving_measurement(self, data):
        """Apply UUID enrichment without changing Gerber measurement provenance."""
        geometry_basis = data.get("geometry_basis")
        value = data.get("value")
        message = data.get("message")
        mapping = self.result_mapper.apply_mapping(data)
        data["value"] = value
        data["message"] = message
        if geometry_basis is not None:
            data["geometry_basis"] = geometry_basis
        raw = data.setdefault("raw", {})
        raw.setdefault("measurement_basis", data.get("source") or "gerber")
        if data.get("source") == "gerber":
            raw.setdefault("gerber_value", value)
        return mapping

    @staticmethod
    def _record_pair_mapping(data, primary, related):
        raw = data.setdefault("raw", {})
        mapping_raw = raw.setdefault("uuid_mapping", {})
        if primary is not None:
            primary_id = getattr(primary, "item_id", "")
            primary_status = getattr(primary, "status", "skipped")
            mapping_raw.update(
                {
                    "status": primary_status,
                    "confidence": getattr(primary, "confidence", 0.0),
                    "reason": getattr(primary, "reason", ""),
                }
            )
            if primary_id and primary_status in ("matched", "already_mapped"):
                data["id"] = primary_id
                mapping_raw["id"] = primary_id
        if related is not None:
            related_id = getattr(related, "item_id", "")
            related_status = getattr(related, "status", "skipped")
            related_raw = {
                "status": related_status,
                "confidence": getattr(related, "confidence", 0.0),
                "reason": getattr(related, "reason", ""),
            }
            if related_id and related_status in ("matched", "already_mapped"):
                data["related_id"] = related_id
                related_raw["id"] = related_id
            mapping_raw["related"] = related_raw

    def _mapped_copper_spacing_item(self, requested_item, left, right):
        left_track = bool(self.backend.is_track(left))
        right_track = bool(self.backend.is_track(right))
        left_pad = bool(self.backend.is_pad(left))
        right_pad = bool(self.backend.is_pad(right))
        if left_track and right_track:
            return "Trace Spacing"
        elif (left_track and right_pad) or (left_pad and right_track):
            return "Trace-to-Pad Spacing"
        elif left_pad and right_pad:
            if requested_item == "Pad-to-Pad Spacing":
                return "Pad-to-Pad Spacing"
            if self._mapped_bga_pad(left) or self._mapped_bga_pad(right):
                return "BGA Pads"
            elif self.backend.is_smd_pad(left) and self.backend.is_smd_pad(right):
                return "SMD Pad Spacing"
            else:
                return "Pad-to-Pad Spacing"
        return None

    def _mapped_bga_pad(self, pad):
        detector = getattr(self.backend, "is_bga_pad", None)
        if detector is None:
            return False
        footprint = None
        for name in ("GetParentFootprint", "GetParent"):
            if hasattr(pad, name):
                try:
                    footprint = getattr(pad, name)()
                    break
                except Exception:
                    pass
        try:
            return bool(detector(pad, footprint))
        except TypeError:
            return bool(detector(pad))

    def _mapped_hole_to_board_edge_result(self, data):
        mapping = self._apply_mapping_preserving_measurement(data)
        raw = data.setdefault("raw", {})
        if mapping.status not in ("matched", "already_mapped"):
            raw["classification_status"] = "unmapped"
            return data
        item = mapping.item
        native_item = self._native_hole_to_board_edge_item(item)
        if not native_item:
            raw["classification_status"] = "unmapped"
            return data
        rule = self.color_rule.default_rule_for(
            "Hole-to-Board Edge",
            native_item,
        )
        value = safe_float(data.get("value"), 0.0)
        color = self.color_rule.get_rule(
            {},
            "Hole-to-Board Edge",
            native_item,
            value,
        )
        raw.update(
            {
                "classification_status": "mapped",
                "native_item": native_item,
                "native_rule": rule,
                "native_color": color,
            }
        )
        data["item"] = native_item
        data["rule_key"] = rule_key("Hole-to-Board Edge", native_item)
        data["rule"] = rule
        data["color"] = color
        data["finding_key"] = native_finding_key(
            "Hole-to-Board Edge",
            native_item,
            raw,
            data.get("layer"),
        )
        return data

    def _native_hole_to_board_edge_item(self, item):
        if self.backend.is_via(item):
            return "Via-to-Board Edge"
        if not self.backend.is_pad(item):
            return ""
        footprint = None
        for name in ("GetParentFootprint", "GetParent"):
            if hasattr(item, name):
                try:
                    footprint = getattr(item, name)()
                    if footprint is not None:
                        break
                except Exception:
                    pass
        names = ()
        name_reader = getattr(self.backend, "footprint_names", None)
        if name_reader is not None and footprint is not None:
            try:
                names = tuple(name_reader(footprint) or ())
            except Exception:
                names = ()
        text = "".join(
            character
            for value in names
            for character in str(value or "").lower()
            if character.isalnum()
        )
        if any(
            marker in text
            for marker in (
                "mountinghole",
                "screwhole",
                "mountingdrill",
                "screwdrill",
            )
        ):
            return "Screw Hole-to-Board Edge"
        if self.backend.is_npth_pad(item):
            return "NPTH-to-Board Edge"
        return "PTH-to-Board Edge"

    def _mapped_drill_spacing_item(self, data):
        primary, related = self.result_mapper.map_pair(data)
        self._record_pair_mapping(data, primary, related)
        if primary.status != "matched" or related is None or related.status != "matched":
            data.setdefault("raw", {})["classification_status"] = "unmapped"
            return data.get("item") or "Different Net PTH Spacing"
        left = primary.item
        right = related.item
        left_net = str(self.backend.item_net_name(left) or "")
        right_net = str(self.backend.item_net_name(right) or "")
        same_net = bool(left_net and left_net == right_net)
        left_is_via = bool(self.backend.is_via(left))
        right_is_via = bool(self.backend.is_via(right))
        if (
            left_is_via
            and right_is_via
            and self.backend.is_blind_buried_via(left)
            and self.backend.is_blind_buried_via(right)
        ):
            native_item = "Blind/Buried Via Spacing"
        elif left_is_via and right_is_via:
            native_item = (
                "Same Net Via Spacing" if same_net else "Different Net Via Spacing"
            )
        else:
            native_item = "Different Net PTH Spacing"
        raw = data.setdefault("raw", {})
        raw["classification_status"] = "mapped"
        raw["native_item"] = native_item
        raw["native_rule"] = self.color_rule.default_rule_for(
            "Drill Hole Spacing", native_item
        )
        value = safe_float(data.get("value"), 0.0)
        raw["native_color"] = self.color_rule.get_rule(
            {}, "Drill Hole Spacing", native_item, value
        )
        if same_net:
            raw["suppressed_reason"] = "same_net"
        return data.get("item") or "Different Net PTH Spacing"

    def _add_parse_error(self, path, file_type, exc):
        message = "{0} geometry parser failed for {1}: {2}".format(
            file_type,
            path,
            exc.__class__.__name__,
        )
        self._add_issue(
            "Geometry Parse Error",
            "error",
            message,
            layer=[self._display_layer(layer_name_from_file(path))],
            raw={
                "file": path,
                "file_type": file_type,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        )

    def _planned_files(self):
        result = {}
        for layer_info in self.export_result.plot_plan or ():
            if not layer_info:
                continue
            name = layer_info[0]
            result[name] = os.path.join(self.export_result.output_dir, "{0}.gbr".format(name))
        return result

    def _find_by_stem(self, stem, extension):
        stem = stem.lower()
        extension = extension.lower()
        for path in self.export_result.files or ():
            root, ext = os.path.splitext(os.path.basename(path))
            if root.lower() == stem and ext.lower() == extension:
                return path
        return ""

    def _existing_layer_file(self, layer_name, expected_path):
        if expected_path and os.path.exists(expected_path):
            return expected_path
        matched = self._find_layer_file(layer_name, (".gbr", ".ger"))
        return matched or expected_path

    def _find_layer_file(self, layer_name, extensions):
        layer = str(layer_name).lower()
        extensions = tuple(extension.lower() for extension in extensions)
        for path in self.export_result.files or ():
            root, ext = os.path.splitext(os.path.basename(path))
            if ext.lower() not in extensions:
                continue
            root = root.lower()
            if root == layer or root.endswith("-{0}".format(layer)) or root.endswith("_{0}".format(layer)):
                return path
        return ""

    def _drill_files(self):
        return tuple(
            path
            for path in self.export_result.files or ()
            if os.path.isfile(path) and os.path.splitext(path)[1].lower() in (".drl", ".xln")
        )

    def _drill_map_files(self):
        return tuple(
            path
            for path in self.export_result.files or ()
            if os.path.isfile(path)
            and (
                "map" in os.path.basename(path).lower()
                or os.path.splitext(path)[1].lower() in (".rpt", ".map")
            )
        )

    def _display_layer(self, layer_name):
        if layer_name == "EdgeCuts":
            return "Edge.Cuts"
        if layer_name == "CuTop":
            return "F.Cu"
        if layer_name == "CuBottom":
            return "B.Cu"
        return layer_name

    def _is_required_layer(self, layer_name):
        return layer_name == "EdgeCuts" or is_copper_layer_name(layer_name)

    def _is_optional_empty_zip_entry(self, name):
        stem, extension = os.path.splitext(os.path.basename(str(name)))
        if extension.lower() not in (".gbr", ".ger"):
            return False
        planned = self._planned_files()
        return stem in planned and not self._is_required_layer(stem)

    def _native_result(self, finding, rule, color):
        raw = dict(finding.raw or {})
        path = raw.get("file", "")
        value = finding.value
        if value is None:
            value = 1.0
        formatted_value = "{0:.6f}".format(value)
        source = "gerber" if str(path).lower().endswith((".gbr", ".ger")) else "drill"
        raw.setdefault(
            "measurement_basis",
            "gerber" if source == "gerber" else "excellon",
        )
        raw.setdefault(
            "gerber_value" if source == "gerber" else "excellon_value",
            formatted_value,
        )
        return {
            "id": path,
            "finding_key": native_finding_key(
                finding.category,
                finding.item,
                raw,
                finding.layer,
            ),
            "rule_key": rule_key(finding.category, finding.item),
            "source": source,
            "confidence": safe_float(raw.get("confidence"), 0.65),
            "geometry_basis": "gerber_derived" if source == "gerber" else "excellon_derived",
            "layer": finding.layer,
            "value": formatted_value,
            "item": finding.item,
            "color": color,
            "type": 10,
            "rule": rule,
            "item_type": "gerber" if str(path).lower().endswith((".gbr", ".ger")) else "drill",
            "message": finding.message,
            "raw": raw,
            **location_fields(raw),
        }

    def _finding_color(self, finding, rule):
        if finding.value is None:
            return "red" if finding.severity == "error" else "gold"
        return self.color_rule.get_rule(
            {},
            self._rule_category(finding.category),
            finding.item,
            finding.value,
        )

    def _apply_measurement_uncertainty(self, category, data, rule):
        if self._native_value_unit(category, data.get("item", "")) != "mm":
            return
        raw = data.setdefault("raw", {})
        uncertainty = self._measurement_uncertainty_mm(raw)
        if uncertainty <= 0:
            return
        value = safe_float(data.get("value"), None)
        if value is None:
            return
        lower = max(0.0, value - uncertainty)
        upper = value + uncertainty
        raw["uncertainty_mm"] = uncertainty
        raw["measurement_interval_mm"] = (lower, upper)
        data["uncertainty_mm"] = uncertainty
        data["measurement_interval_mm"] = (lower, upper)
        try:
            kind = self.color_rule.rule_kind(
                self._rule_category(category),
                data.get("item", ""),
            )
            lower_color = self.color_rule.color_for_rule(rule, lower, kind)
            upper_color = self.color_rule.color_for_rule(rule, upper, kind)
        except (TypeError, ValueError):
            return
        raw["decision_interval_colors"] = (lower_color, upper_color)
        if lower_color != upper_color:
            # A quantized measurement whose admissible interval crosses a
            # threshold needs native validation.  Preserve the nominal
            # classification as evidence, but do not expose an arbitrary
            # pass/fail color to the UI.
            raw["nominal_color"] = data.get("color", "black")
            data["color"] = "gold"
            raw["threshold_status"] = "borderline"
            data["threshold_status"] = "borderline"
            data["execution_status"] = "completed"
        else:
            raw["threshold_status"] = "clear"
            data["threshold_status"] = "clear"

    @staticmethod
    def _measurement_uncertainty_mm(raw):
        explicit = safe_float(raw.get("uncertainty_mm"), None)
        if explicit is not None:
            return max(0.0, explicit)
        endpoint_tolerances = []
        for name in ("primary", "related"):
            endpoint = raw.get(name)
            if not isinstance(endpoint, dict):
                continue
            tolerance = safe_float(endpoint.get("quantization_tolerance_mm"), None)
            if tolerance is None:
                resolution = safe_float(
                    endpoint.get("coordinate_resolution_mm"), None
                )
                tolerance = resolution / 2.0 if resolution is not None else None
            if tolerance is not None:
                endpoint_tolerances.append(max(0.0, tolerance))
        if endpoint_tolerances:
            return sum(endpoint_tolerances)
        tolerance = safe_float(raw.get("quantization_tolerance_mm"), None)
        if tolerance is not None:
            return max(0.0, tolerance)
        resolution = safe_float(raw.get("coordinate_resolution_mm"), 0.0)
        return max(0.0, resolution / 2.0)

    def _record_native_result(self, category, data):
        if category in ("Pad size", "RingHole") and not self._within_rule_reporting_limit(
            category, data
        ):
            return
        if (
            self._uses_remote_pad_contract()
            and data.get("color") == "black"
            and not self._within_remote_reporting_window(category, data)
        ):
            return
        results = self.native_results.setdefault(category, [])
        if self._is_hole_aspect_ratio(data):
            if (
                data.get("color") == "black"
                and not self._within_rule_reporting_limit(category, data)
            ):
                return
            value = safe_float(data.get("value"), None)
            if value is None:
                return
            if not any(
                self._is_hole_aspect_ratio(existing)
                and abs(safe_float(existing.get("value"), float("inf")) - value) <= 1e-9
                for existing in results
            ):
                results.append(data)
            return
        if data.get("color") != "black" or data.get("item_type") == "drill":
            results.append(data)
            return
        if category in ("Pad size", "RingHole"):
            # Pad-size and annular-ring findings carry physical-object
            # locations.  Keeping only one passing minimum loses every other
            # pad/via with the same measurement.  Grouping later folds equal
            # values into one row while retaining all locatable objects.
            results.append(data)
            return
        if category in ("Smallest Trace Spacing", "SMD Spacing"):
            self._record_tied_copper_spacing_minimum(results, data)
            return
        for index, existing in enumerate(results):
            if existing.get("color") == "black" and existing.get("item") == data.get("item"):
                if self._more_reportable_value(category, data, existing):
                    results[index] = data
                return
        results.append(data)

    def _within_rule_reporting_limit(self, category, data):
        """Limit passing details to the third value in their rule."""
        value = safe_float(data.get("value"), None)
        if value is None:
            return True
        rule = data.get("rule") or self.color_rule.default_rule_for(
            self._rule_category(category), data.get("item", "")
        )
        try:
            limit = self.color_rule.third_rule_value(rule)
        except (TypeError, ValueError):
            return True
        uncertainty = self._measurement_uncertainty_mm(data.get("raw") or {})
        return limit <= 0 or limit >= 900 or value - uncertainty <= limit

    @staticmethod
    def _is_hole_aspect_ratio(data):
        return (
            data.get("rule_key") == rule_key("Hole Size", "Aspect Ratio")
            or data.get("item") == "Aspect Ratio"
        )

    def _record_tied_copper_spacing_minimum(self, results, data):
        item = data.get("item")
        matching = [
            existing
            for existing in results
            if existing.get("color") == "black" and existing.get("item") == item
        ]
        if not matching:
            results.append(data)
            return
        value = safe_float(data.get("value"), None)
        minimum = min(
            safe_float(existing.get("value"), float("inf"))
            for existing in matching
        )
        if value is None:
            return
        if value < minimum - COPPER_SPACING_TIE_TOLERANCE_MM:
            results[:] = [
                existing
                for existing in results
                if not (
                    existing.get("color") == "black"
                    and existing.get("item") == item
                )
            ]
            results.append(data)
            return
        if abs(value - minimum) <= COPPER_SPACING_TIE_TOLERANCE_MM:
            pair_key = self._native_pair_key(data)
            if not any(self._native_pair_key(existing) == pair_key for existing in matching):
                results.append(data)

    @staticmethod
    def _native_pair_key(data):
        item_ids = tuple(
            sorted(
                str(value)
                for value in (data.get("id"), data.get("related_id"))
                if value
            )
        )
        if len(item_ids) == 2:
            return "uuid", item_ids
        raw = data.get("raw") or {}
        endpoints = []
        for name in ("primary", "related"):
            endpoint = raw.get(name) or {}
            endpoints.append(
                (
                    endpoint.get("file"),
                    endpoint.get("flash_id"),
                    endpoint.get("object_id"),
                    endpoint.get("bbox"),
                )
            )
        return "gerber", tuple(sorted(endpoints, key=repr))

    def _within_remote_reporting_window(self, category, data):
        value = safe_float(data.get("value"), None)
        if value is None:
            return True
        if category in ("Smallest Trace Width", "RingHole"):
            return value <= 0.254
        if category in ("Smallest Trace Spacing", "SMD Spacing"):
            return value < 0.254
        return True

    def _more_reportable_value(self, category, data, existing):
        value = safe_float(data.get("value"), None)
        current = safe_float(existing.get("value"), None)
        if value is None:
            return False
        if current is None:
            return True
        kind = self.color_rule.rule_kind(
            self._rule_category(category),
            data.get("item", ""),
        )
        if kind == "max":
            return value > current
        return value < current

    def native_result_map(self):
        result = self._board_statistic_result_map()
        for category in STRICT_SCANNER_CATEGORIES:
            if category not in self._completed_scanner_categories:
                continue
            result[category] = {
                "display": "正常",
                "check": [],
                "color": "black",
                "checked_count": 0,
                "available_count": 0,
                "violation_count": 0,
                "suppressed_count": 0,
                "borderline_count": 0,
                "displayed_count": 0,
                "visible_count": 0,
                "execution_status": "completed",
                "coverage": "partial",
                "checked_count_basis": "available_results",
                "item_summaries": self._completed_item_summaries(category),
            }
        for category, available_rows in self.native_results.items():
            if not available_rows:
                continue
            available_rows = list(available_rows)
            rows = aggregate_physical_native_results(category, available_rows)
            rows = self._ordered_native_results(category, rows)
            groups = grouped_native_results(rows)
            headline_groups = groups
            if category == "Hole Size":
                units = {
                    self._native_value_unit(category, row.get("item", ""))
                    for row in groups
                }
                if len(units) > 1:
                    headline_groups = [
                        row
                        for row in groups
                        if self._native_value_unit(category, row.get("item", ""))
                        != "ratio"
                    ]
            values = [safe_float(row.get("value"), None) for row in headline_groups]
            values = [value for value in values if value is not None]
            if not values:
                display = "正常"
            elif category == "Holes on SMD Pads" and self._uses_remote_pad_contract():
                display = "{0:.2f}%".format(max(values) * 100.0)
            elif (
                category in ("Pad size", "RingHole", "Copper-to-Board Edge")
                and self._uses_remote_pad_contract()
                and aggregate_color(row.get("color") for row in rows) == "black"
            ):
                display = "\u6b63\u5e38"
            else:
                display = round(min(values), 6)
            result[category] = {
                "display": display,
                "check": [{"result": row["result"]} for row in groups],
                "color": aggregate_color(row.get("color") for row in rows),
                "checked_count": len(available_rows),
                "available_count": len(available_rows),
                "violation_count": sum(
                    row.get("color") != "black" for row in rows
                ),
                "suppressed_count": sum(
                    bool((row.get("raw") or {}).get("suppressed_reason"))
                    for row in rows
                ),
                "borderline_count": sum(
                    row.get("threshold_status") == "borderline" for row in rows
                ),
                "displayed_count": len(rows),
                "visible_count": len(rows),
                "execution_status": "completed",
                "coverage": "partial",
                "checked_count_basis": "available_results",
                "item_summaries": self._native_item_summaries(
                    category, available_rows, rows
                ),
            }
        self._add_default_result_metrics(result)
        return result

    def _native_item_summaries(self, category, available_rows, visible_rows):
        items = []
        for row in available_rows:
            item = row.get("item", "")
            if item not in items:
                items.append(item)
        summaries = self._completed_item_summaries(category)
        for item in items:
            available = [row for row in available_rows if row.get("item", "") == item]
            visible = [row for row in visible_rows if row.get("item", "") == item]
            values = [safe_float(row.get("value"), None) for row in visible]
            values = [value for value in values if value is not None]
            if values:
                kind = self.color_rule.rule_kind(
                    self._rule_category(category), item
                )
                display = max(values) if kind == "max" else min(values)
            else:
                display = None
            summaries[item] = {
                "item": item,
                "rule_key": rule_key(category, item),
                "rule": self.color_rule.default_rule_for(
                    self._rule_category(category), item
                ),
                "display": display,
                "unit": self._native_value_unit(category, item),
                "checked_count": len(available),
                "available_count": len(available),
                "violation_count": sum(
                    row.get("color") != "black" for row in visible
                ),
                "suppressed_count": sum(
                    bool((row.get("raw") or {}).get("suppressed_reason"))
                    for row in visible
                ),
                "borderline_count": sum(
                    row.get("threshold_status") == "borderline"
                    for row in visible
                ),
                "displayed_count": len(visible),
                "visible_count": len(visible),
                "execution_status": "completed",
                "coverage": "partial",
                "checked_count_basis": "available_results",
                "color": aggregate_color(row.get("color") for row in visible),
            }
        return summaries

    def _completed_item_summaries(self, category):
        if category not in ("Smallest Trace Spacing", "SMD Spacing"):
            return {}
        items = (
            ("SMD Pad Spacing",)
            if category == "SMD Spacing"
            else (
                "Trace Spacing",
                "Trace-to-Pad Spacing",
                "Pad-to-Pad Spacing",
                "BGA Pads",
            )
        )
        return {
            item: {
                "item": item,
                "rule_key": rule_key(category, item),
                "rule": self.color_rule.default_rule_for(
                    self._rule_category(category), item
                ),
                "display": None,
                "unit": self._native_value_unit(category, item),
                "checked_count": 0,
                "available_count": 0,
                "violation_count": 0,
                "suppressed_count": 0,
                "borderline_count": 0,
                "displayed_count": 0,
                "visible_count": 0,
                "execution_status": "completed",
                "coverage": "partial",
                "checked_count_basis": "available_results",
                "color": "black",
            }
            for item in items
        }

    @staticmethod
    def _native_value_unit(category, item):
        if "ratio" in str(item or "").lower():
            return "ratio"
        if category in (
            "Hole Size",
            "Drill Hole Spacing",
            "Smallest Trace Width",
            "Smallest Trace Spacing",
            "SMD Spacing",
            "Pad size",
            "RingHole",
            "Drill to Copper",
            "Copper-to-Board Edge",
            "Hole-to-Board Edge",
            "Solder Mask Analysis",
        ):
            return "mm"
        return "count"

    @staticmethod
    def _add_default_result_metrics(result):
        for entry in result.values():
            if not isinstance(entry, dict):
                continue
            displayed = sum(
                len(group.get("result") or ())
                for group in entry.get("check") or ()
            )
            entry.setdefault("checked_count", displayed)
            entry.setdefault("available_count", displayed)
            entry.setdefault("violation_count", 0 if entry.get("color") == "black" else displayed)
            entry.setdefault("suppressed_count", 0)
            entry.setdefault("borderline_count", 0)
            entry.setdefault("displayed_count", displayed)
            entry.setdefault("visible_count", displayed)
            entry.setdefault("execution_status", "completed")
            entry.setdefault("coverage", "complete")
            entry.setdefault("checked_count_basis", "reported_results")
            entry.setdefault("item_summaries", {})

    def _ordered_native_results(self, category, rows):
        if category != "Hole Size":
            return rows
        aspect_rows = sorted(
            (row for row in rows if self._is_hole_aspect_ratio(row)),
            key=lambda row: safe_float(row.get("value"), float("-inf")),
            reverse=True,
        )
        if len(aspect_rows) < 2:
            return rows
        ordered_aspects = iter(aspect_rows)
        return [
            next(ordered_aspects) if self._is_hole_aspect_ratio(row) else row
            for row in rows
        ]

    def _board_statistic_result_map(self):
        if self.board is None or self.backend is None:
            return {}
        statistics = calculate_board_statistics(self.backend)
        return statistic_result_map(statistics, chinese=self.chinese)

    def _warning_limit(self, category, item):
        rule = self.color_rule.default_rule_for(
            self._rule_category(category), item
        )
        try:
            parts = [float(part) for part in str(rule).split(",")[:2]]
        except ValueError:
            return None
        if len(parts) < 2:
            return None
        return max(parts)

    def _copper_spacing_reporting_limits(self):
        items = (
            "Trace Spacing",
            "Trace-to-Pad Spacing",
            "Pad-to-Pad Spacing",
            "BGA Pads",
            "SMD Pad Spacing",
        )
        limits = {
            item: limit
            for item in items
            for category in (
                "SMD Spacing" if item == "SMD Pad Spacing" else "Smallest Trace Spacing",
            )
            for limit in (self._warning_limit(category, item),)
            if limit is not None
        }
        return limits

    @staticmethod
    def _rule_category(category):
        """Return the configured category used by strict-result rules."""
        return category

    def _drill_spacing_reporting_limit(self):
        items = (
            "Same Net Via Spacing",
            "Different Net Via Spacing",
            "Different Net PTH Spacing",
            "Blind/Buried Via Spacing",
        )
        limits = [
            self._warning_limit("Drill Hole Spacing", item)
            for item in items
        ]
        return max((limit for limit in limits if limit is not None), default=None)

    def _drill_to_copper_reporting_limits(self):
        items = (
            "PTH-to-Trace [Outer]",
            "PTH-to-Trace [Inner]",
            "Via-to-Trace [Outer]",
            "Via-to-Trace [Inner]",
            "NPTH-to-Copper",
        )
        return {
            item: limit
            for item in items
            for limit in (self._warning_limit("Drill to Copper", item),)
            if limit is not None
        }

    def _board_edge_reporting_limits(self):
        items = (
            "SMD-to-Board Edge",
            "Trace-to-Board Edge",
            "Copper-to-Board Edge",
        )
        limits = {}
        for item in items:
            rule = self.color_rule.default_rule_for("Copper-to-Board Edge", item)
            try:
                values = [float(value) for value in str(rule).split(",")[:3]]
            except ValueError:
                continue
            finite = [value for value in values if 0 < value < 900]
            if finite:
                limits[item] = max(finite)
        return limits

    def _hole_to_board_edge_reporting_limits(self):
        items = (
            "PTH-to-Board Edge",
            "Via-to-Board Edge",
            "Screw Hole-to-Board Edge",
            "NPTH-to-Board Edge",
        )
        limits = {}
        for item in items:
            rule = self.color_rule.default_rule_for(
                "Hole-to-Board Edge",
                item,
            )
            try:
                values = [float(value) for value in str(rule).split(",")[:3]]
            except ValueError:
                continue
            finite = [value for value in values if 0 < value < 900]
            if finite:
                limits[item] = max(finite)
        return limits

    def _solder_mask_reporting_limits(self):
        items = ("Solder Mask Bridge", "Solder Mask Covers Trace")
        return {
            item: limit
            for item in items
            for limit in (self._warning_limit("Solder Mask Analysis", item),)
            if limit is not None
        }

    def _uses_remote_pad_contract(self):
        rule = self.color_rule.default_rule_for("Holes on SMD Pads", "Via on SMD Pad")
        return str(rule) == "0.004000,0.001000,0.000000"

    def _add_issue(self, item, severity, message, layer=None, value="", rule="", raw=None):
        self.issues.append(
            DfmIssue(
                category=CATEGORY,
                item=item,
                severity=severity,
                layer=layer,
                value=value,
                rule=rule,
                message=message,
                raw=raw or {},
            )
        )

    def _summary(self, issues):
        color = "black"
        if any(issue.severity == "error" for issue in issues):
            color = "red"
        elif any(issue.severity == "warning" for issue in issues):
            color = "gold"
        error_count = sum(1 for issue in issues if issue.severity == "error")
        warning_count = sum(1 for issue in issues if issue.severity == "warning")
        if error_count or warning_count:
            display = "{0} error(s), {1} warning(s)".format(error_count, warning_count)
        else:
            display = "OK"
        return DfmSummary(category=CATEGORY, display=display, color=color, issues=issues)


def elapsed_ms(started_at):
    return round((time.perf_counter() - started_at) * 1000.0, 3)
