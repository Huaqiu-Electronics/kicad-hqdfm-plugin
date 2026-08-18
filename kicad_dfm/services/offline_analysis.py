import time
from dataclasses import dataclass, field

from kicad_dfm.core.logging import get_logger
from kicad_dfm.core.models import DfmSummary
from kicad_dfm.core.progress import report_progress
from kicad_dfm.core.rule_catalog import RULE_CATALOG
from kicad_dfm.services.analysis_results import build_analysis_contract
from kicad_dfm.services.analysis_results import KICAD_NATIVE
from kicad_dfm.services.local_checks import LocalChecks


LOGGER = get_logger(__name__)

LOCAL_CHECKS = (
    ("Signal Integrity", "get_signal_integrity"),
    ("Smallest Trace Width", "get_line_width"),
    ("Smallest Trace Spacing", "get_trace_spacing"),
    ("SMD Spacing", "get_smd_spacing"),
    ("Pad size", "get_pad"),
    ("Hole Size", "get_hole_size"),
    ("RingHole", "get_annular_ring"),
    ("Drill Hole Spacing", "get_drill_hole_spacing"),
    ("Drill to Copper", "get_drill_to_copper"),
    ("Copper-to-Board Edge", "get_copper_to_board_edge"),
    ("Hole-to-Board Edge", "get_hole_to_board_edge"),
    ("Special Drill Holes", "get_special_drill_holes"),
    ("Holes on SMD Pads", "get_holes_on_smd_pads"),
    ("Missing SMask Openings", "get_missing_smask_openings"),
    ("Solder Mask Analysis", "get_solder_mask_analysis"),
)

STATISTIC_CHECKS = (
    ("Drill Hole Density", "get_drill_hole_density"),
    ("Surface Finish Area", "get_surface_finish_area"),
    ("Test Point Count", "get_test_point_count"),
)

ANALYSIS_CHECKS = LOCAL_CHECKS + STATISTIC_CHECKS

IMPLEMENTED_LOCAL_CATEGORIES = tuple(category for category, _method_name in LOCAL_CHECKS)

COMPAT_CATEGORIES = (
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
    "Drill Hole Density",
    "Surface Finish Area",
    "Test Point Count",
)


@dataclass
class OfflineDfmResult:
    analysis_result: dict
    kicad_result: dict
    issues: tuple
    summary: dict
    profile: dict
    contract: dict = field(default_factory=dict)


class OfflineDfmAnalysis:
    def __init__(self, board, control, backend=None, rules=None, include_passed_details=False):
        self.board = board
        self.control = control
        self.backend = backend
        self.rules = rules or RULE_CATALOG
        self.include_passed_details = include_passed_details

    def analyze(self, progress_callback=None, is_cancelled=None):
        started_at = time.perf_counter()
        analysis_result = self._base_analysis_result()
        index_started_at = time.perf_counter()
        total_steps = len(ANALYSIS_CHECKS) + 1
        report_progress(
            progress_callback,
            is_cancelled,
            0,
            total_steps,
            "Preparing board data",
        )
        begin_analysis = getattr(self.backend, "begin_analysis", None)
        if begin_analysis is not None:
            begin_analysis()
        checks = LocalChecks(
            self.control,
            self.board,
            self.backend,
            self.rules,
            include_passed_details=self.include_passed_details,
            heartbeat=lambda: report_progress(
                progress_callback,
                is_cancelled,
                0,
                total_steps,
                "Preparing board data",
            ),
        )
        profile = {
            "index_build_ms": elapsed_ms(index_started_at),
            "categories": {},
        }
        kicad_result = {}
        for index, (category, method_name) in enumerate(ANALYSIS_CHECKS, start=1):
            checks.set_heartbeat(
                lambda current=index, item=category: report_progress(
                    progress_callback,
                    is_cancelled,
                    current,
                    total_steps,
                    item,
                )
            )
            report_progress(
                progress_callback,
                is_cancelled,
                index,
                total_steps,
                category,
            )
            category_started_at = time.perf_counter()
            result = getattr(checks, method_name)(analysis_result)
            kicad_result[category] = result
            analysis_result[category] = result
            profile["categories"][category] = {
                "elapsed_ms": elapsed_ms(category_started_at),
                "rows": result_row_count(result),
                "color": result.get("color") if isinstance(result, dict) else "",
            }
        report_progress(
            progress_callback,
            is_cancelled,
            total_steps,
            total_steps,
            "Finalizing results",
        )
        profile["total_ms"] = elapsed_ms(started_at)
        profile["issue_count"] = len(checks.issues)
        LOGGER.debug("offline_dfm_analysis profile=%s", profile)
        summary = self._summary(kicad_result, checks.issues)
        return OfflineDfmResult(
            analysis_result=analysis_result,
            kicad_result=kicad_result,
            issues=tuple(checks.issues),
            summary=summary,
            profile=profile,
            contract=build_analysis_contract(
                KICAD_NATIVE,
                analysis_result,
                checks.issues,
                summary,
                categories=COMPAT_CATEGORIES,
                profile=profile,
            ),
        )

    def _base_analysis_result(self):
        result = {}
        for category in COMPAT_CATEGORIES:
            rules = self.rules.get(category, ())
            if category in IMPLEMENTED_LOCAL_CATEGORIES:
                result[category] = {
                    "display": None,
                    "display_inch": "",
                    "color": "black",
                    "check": [],
                    "_rules": [{rule["item"]: rule["rule"]} for rule in rules],
                }
            else:
                result[category] = ""
        return result

    def _summary(self, kicad_result, issues):
        summary = {}
        for category, result in kicad_result.items():
            if isinstance(result, dict):
                category_issues = tuple(issue for issue in issues if issue.category == category)
                summary[category] = DfmSummary(
                    category=category,
                    display=str(result.get("display", "")),
                    display_inch=str(result.get("display_inch", "")),
                    color=result.get("color", ""),
                    issues=category_issues,
                )
        return summary


def elapsed_ms(started_at):
    return round((time.perf_counter() - started_at) * 1000.0, 3)


def result_row_count(result):
    if not isinstance(result, dict):
        return 0
    return sum(
        len(check.get("result") or ())
        for check in result.get("check") or ()
        if isinstance(check, dict)
    )
