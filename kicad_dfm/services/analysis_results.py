"""Shared result contract and orchestration for the local DFM pipelines.

The legacy UI result maps are deliberately kept as an adapter at the edge of
this module.  The contract below records which pipeline actually ran, keeps
counts explicit, and gives findings stable keys so results from two pipelines
can be compared and merged without relying on translated display strings.
"""

import copy
import dataclasses
import hashlib
import json
import os
from dataclasses import dataclass, field

from kicad_dfm.core.models import DfmIssue, DfmSummary, Location
from kicad_dfm.core.rule_contract import rule_key


CONTRACT_VERSION = 1
SOURCE_VIEWS_SCHEMA = "hqdfm.analysis-source-views"
SOURCE_VIEWS_SCHEMA_VERSION = 1

KICAD_NATIVE = "kicad_native"
GERBER_STRICT = "gerber_strict"
GERBER_ENRICHED = "gerber_enriched"
COMBINED = "combined"
ANALYSIS_MODES = (KICAD_NATIVE, GERBER_STRICT, GERBER_ENRICHED, COMBINED)

_MODE_ALIASES = {
    "offline": KICAD_NATIVE,
    "kicad": KICAD_NATIVE,
    "native": KICAD_NATIVE,
    "online": GERBER_ENRICHED,
    "gerber": GERBER_ENRICHED,
    "enriched": GERBER_ENRICHED,
    "strict": GERBER_STRICT,
    "combined": COMBINED,
}

_VIOLATION_COLORS = {"red", "gold"}
_VIOLATION_SEVERITIES = {"error", "warning", "fatal"}
_SMD_SPACING_CATEGORY = "SMD Spacing"
_LEGACY_SPACING_CATEGORY = "Smallest Trace Spacing"
_SMD_SPACING_ITEM = "SMD Pad Spacing"
_SMD_SPACING_RULE_KEY = rule_key(_SMD_SPACING_CATEGORY, _SMD_SPACING_ITEM)


def normalize_smd_spacing_results(results):
    """Move legacy nested SMD-pad results into the independent category.

    Modern native and Gerber engines already emit ``SMD Spacing``.  This
    adapter keeps saved caches and older remote responses compatible without
    exposing the retired nested placement to the UI or combined contract.
    """
    normalized = copy.deepcopy(results) if isinstance(results, dict) else {}
    legacy = normalized.get(_LEGACY_SPACING_CATEGORY)
    if not isinstance(legacy, dict):
        return normalized

    retained_checks = []
    moved_checks = []
    for check in legacy.get("check") or ():
        if not isinstance(check, dict):
            continue
        retained_rows = []
        moved_rows = []
        for row in check.get("result") or ():
            if not isinstance(row, dict):
                continue
            if _is_smd_spacing_record(row):
                moved = dict(row)
                moved["item"] = _SMD_SPACING_ITEM
                moved["rule_key"] = _SMD_SPACING_RULE_KEY
                moved_rows.append(moved)
            else:
                retained_rows.append(row)
        if retained_rows:
            retained_check = dict(check)
            retained_check["result"] = retained_rows
            retained_checks.append(retained_check)
        if moved_rows:
            moved_check = dict(check)
            moved_check["result"] = moved_rows
            moved_checks.append(moved_check)

    retained_summaries = {}
    moved_summaries = {}
    for summary_key, item_summary in (legacy.get("item_summaries") or {}).items():
        if _is_smd_spacing_record(item_summary, fallback=summary_key):
            moved = dict(item_summary) if isinstance(item_summary, dict) else {}
            moved["item"] = _SMD_SPACING_ITEM
            moved["rule_key"] = _SMD_SPACING_RULE_KEY
            moved_summaries[_SMD_SPACING_RULE_KEY] = moved
        else:
            retained_summaries[summary_key] = item_summary

    if not moved_checks and not moved_summaries:
        return normalized

    normalized[_LEGACY_SPACING_CATEGORY] = _rebuild_split_result(
        legacy,
        retained_checks,
        retained_summaries,
    )
    explicit = normalized.get(_SMD_SPACING_CATEGORY)
    if not _result_has_smd_spacing_contract(explicit):
        normalized[_SMD_SPACING_CATEGORY] = _rebuild_split_result(
            legacy,
            moved_checks,
            moved_summaries,
        )
    return normalized


def _is_smd_spacing_record(record, fallback=""):
    record = record if isinstance(record, dict) else {}
    identity = "".join(
        character
        for character in str(record.get("item") or fallback or "").lower()
        if character.isalnum()
    )
    rule_identity = str(record.get("rule_key") or fallback or "").lower()
    return identity in ("smdpadspacing", "smdspacing") or rule_identity.endswith(
        ":smdpadspacing"
    )


def _result_has_smd_spacing_contract(result):
    if not isinstance(result, dict):
        return False
    if any(
        _is_smd_spacing_record(row)
        for check in result.get("check") or ()
        if isinstance(check, dict)
        for row in check.get("result") or ()
    ):
        return True
    return any(
        _is_smd_spacing_record(summary, fallback=key)
        for key, summary in (result.get("item_summaries") or {}).items()
    )


def _rebuild_split_result(template, checks, item_summaries):
    result = copy.deepcopy(template)
    result["check"] = list(checks)
    result["item_summaries"] = copy.deepcopy(item_summaries)
    rows = [
        row
        for check in checks
        for row in check.get("result") or ()
        if isinstance(row, dict)
    ]
    summaries = [
        summary
        for summary in item_summaries.values()
        if isinstance(summary, dict)
    ]
    metric_names = (
        "checked_count",
        "available_count",
        "violation_count",
        "suppressed_count",
        "borderline_count",
        "displayed_count",
        "visible_count",
    )
    for metric in metric_names:
        values = [summary.get(metric) for summary in summaries if summary.get(metric) is not None]
        if values:
            result[metric] = sum(_safe_int(value) for value in values)
        elif metric in ("displayed_count", "visible_count", "violation_count"):
            result[metric] = (
                sum(_legacy_row_is_violation(row) for row in rows)
                if metric == "violation_count"
                else len(rows)
            )
        else:
            result[metric] = len(rows)

    display_values = [
        value
        for value in (
            _safe_float(row.get("value")) for row in rows
        )
        if value is not None
    ]
    if not display_values:
        display_values = [
            value
            for value in (
                _safe_float(summary.get("display")) for summary in summaries
            )
            if value is not None
        ]
    result["display"] = min(display_values) if display_values else ""
    result["color"] = _aggregate_legacy_color(rows)
    return result


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def canonical_mode(mode):
    value = str(mode or KICAD_NATIVE).strip().lower()
    value = _MODE_ALIASES.get(value, value)
    if value not in ANALYSIS_MODES:
        raise ValueError("Unsupported DFM analysis mode: {0}".format(mode))
    return value


def normalize_source_views(source_views):
    """Return the one runtime/cache schema used for full pipeline source views.

    Source views are deliberately JSON-native even while an analysis is live.
    Keeping dataclasses and tuples out of this diagnostic snapshot makes its
    in-memory shape identical to the shape restored from cache.
    """
    if not isinstance(source_views, dict):
        return {}
    normalized = {}
    for source_mode, source_view in source_views.items():
        if not isinstance(source_view, dict):
            continue
        try:
            mode = canonical_mode(source_view.get("mode") or source_mode)
        except ValueError:
            continue
        normalized[mode] = {
            "source_view_schema_version": SOURCE_VIEWS_SCHEMA_VERSION,
            "mode": mode,
            "analysis_result": _json_value(source_view.get("analysis_result") or {}),
            "kicad_result": _json_value(source_view.get("kicad_result") or {}),
            "issues": _json_value(source_view.get("issues") or ()),
            "summary": _json_value(source_view.get("summary") or {}),
            "profile": _json_value(source_view.get("profile") or {}),
            "contract": _json_value(source_view.get("contract") or {}),
            "input_paths": [str(path) for path in source_view.get("input_paths") or ()],
            "export_summary": _json_value(source_view.get("export_summary") or {}),
        }
    return normalized


def source_views_payload(source_views):
    """Encode full source views as a uniquely identified JSON payload."""
    return {
        "schema": SOURCE_VIEWS_SCHEMA,
        "schema_version": SOURCE_VIEWS_SCHEMA_VERSION,
        "views": normalize_source_views(source_views),
    }


def source_views_from_payload(payload):
    """Decode a full source-view payload, rejecting ambiguous structures."""
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema") != SOURCE_VIEWS_SCHEMA:
        return {}
    if payload.get("schema_version") != SOURCE_VIEWS_SCHEMA_VERSION:
        return {}
    return normalize_source_views(payload.get("views") or {})


def stable_finding_key(category, row):
    """Return a pipeline-independent key for a legacy result row.

    UUID-backed identities are preferred.  Gerber-only findings fall back to
    normalized physical provenance.  Values and colors are observations, not
    identity, and are therefore intentionally excluded.
    """
    row = row if isinstance(row, dict) else {}
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    rule_identity = row.get("rule_key") or rule_key(category, row.get("item", ""))
    primary = _stable_object_identity(row.get("id"), raw, "primary")
    related_raw = raw.get("related") or raw.get("related_raw")
    related = _stable_object_identity(
        row.get("related_id"),
        related_raw if isinstance(related_raw, dict) else raw,
        "related",
    )
    if str(category or "") in (
        "Copper-to-Board Edge",
        "Hole-to-Board Edge",
    ):
        # The edge segment is a location witness, not a second violating PCB
        # object.  Enrichment may map that witness to an Edge.Cuts UUID while
        # native analysis leaves it implicit; including it would prevent the
        # same copper object/layer from merging across engines.
        related = ""
    if primary and related and _is_symmetric_finding(row):
        primary, related = sorted((primary, related))
    physical_across_layers = _has_physical_aggregation(raw) or (
        _is_intrinsically_cross_layer_physical(category, row, raw)
    )
    related_layers = (
        ()
        if str(category or "") in (
            "Copper-to-Board Edge",
            "Hole-to-Board Edge",
        )
        else _normalized_layers(row.get("related_layer"))
    )
    layer_identity = None if physical_across_layers else {
        "primary": _normalized_layers(row.get("layer")),
        "related": related_layers,
    }
    identity = {
        "rule": str(rule_identity),
        "primary": primary,
        "related": related,
        # UUID alone is not a physical finding identity: one object may have
        # distinct measurements on several copper layers.  Only an explicitly
        # aggregated row is allowed to use a layer-independent identity.
        "layer": layer_identity,
        "geometry": _geometry_identity(row, raw) if not primary else None,
    }
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "finding:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_finding_key(category, row):
    """Return the immutable fabrication-evidence alias, when one is present."""
    row = row if isinstance(row, dict) else {}
    source_key = row.get("finding_key")
    if not source_key:
        return ""
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    identity = {
        "rule": row.get("rule_key") or rule_key(category, row.get("item", "")),
        "source_key": str(source_key),
        "layer": None
        if _has_physical_aggregation(raw)
        or _is_intrinsically_cross_layer_physical(category, row, raw)
        else {
            "primary": _normalized_layers(row.get("layer")),
            "related": ()
            if str(category or "") in (
                "Copper-to-Board Edge",
                "Hole-to-Board Edge",
            )
            else _normalized_layers(row.get("related_layer")),
        },
    }
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "source:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_analysis_contract(
    mode,
    analysis_result,
    issues=(),
    summary=None,
    categories=(),
    profile=None,
    execution_status="completed",
    metadata=None,
):
    """Adapt a legacy result map to the shared, cacheable result contract."""
    mode = canonical_mode(mode)
    analysis_result = analysis_result if isinstance(analysis_result, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    ordered_categories = []
    for category in tuple(categories or ()) + tuple(analysis_result) + tuple(summary):
        if category not in ordered_categories:
            ordered_categories.append(category)

    contract_categories = {}
    total_checked = 0
    total_violations = 0
    total_displayed = 0
    for category in ordered_categories:
        legacy = analysis_result.get(category)
        category_issues = tuple(
            issue for issue in (issues or ()) if getattr(issue, "category", None) == category
        )
        result = _category_contract(mode, category, legacy, category_issues, summary.get(category))
        contract_categories[category] = result
        if result["execution_status"] == "completed":
            total_checked += result["checked_count"]
            total_violations += result["violation_count"]
            total_displayed += result["displayed_count"]

    return {
        "contract_version": CONTRACT_VERSION,
        "mode": mode,
        "execution_status": str(execution_status or "completed"),
        "counts": {
            "checked": total_checked,
            "violations": total_violations,
            "displayed": total_displayed,
        },
        "checked_count": total_checked,
        "violation_count": total_violations,
        "displayed_count": total_displayed,
        "categories": contract_categories,
        "profile": _json_value(profile or {}),
        "metadata": _json_value(metadata or {}),
    }


def merge_analysis_contracts(*contracts):
    contracts = tuple(contract for contract in contracts if isinstance(contract, dict))
    if not contracts:
        return build_analysis_contract(KICAD_NATIVE, {})

    merged_categories = {}
    source_views = {}
    for contract in contracts:
        mode = canonical_mode(contract.get("mode"))
        source_views[mode] = copy.deepcopy(contract)
        for category, source_category in (contract.get("categories") or {}).items():
            target = merged_categories.setdefault(
                category,
                {
                    "execution_status": "not_computed",
                    "result_status": "not_computed",
                    "counts": {"checked": 0, "violations": 0, "displayed": 0},
                    "checked_count": 0,
                    "violation_count": 0,
                    "displayed_count": 0,
                    "count_basis": {},
                    "findings": [],
                    "source_counts": {},
                    "source_execution_status": {},
                    "summary": {},
                },
            )
            target["source_counts"][mode] = copy.deepcopy(source_category.get("counts") or {})
            target["source_execution_status"][mode] = str(
                source_category.get("execution_status") or "not_computed"
            )
            if source_category.get("execution_status") == "completed":
                target["execution_status"] = "completed"
            elif target["execution_status"] == "not_computed":
                target["execution_status"] = source_category.get("execution_status", "not_computed")
            target["checked_count"] += int(source_category.get("checked_count") or 0)
            target["counts"]["checked"] = target["checked_count"]
            target["summary"][mode] = copy.deepcopy(source_category.get("summary") or {})

            alias_map = {}
            for existing in target["findings"]:
                if existing.get("_merged_into") is not None:
                    continue
                for alias in _finding_aliases(existing):
                    alias_map[alias] = existing
            for finding in source_category.get("findings") or ():
                key = finding.get("key")
                if not key:
                    continue
                finding_aliases = _finding_aliases(finding)
                matches = []
                match_ids = set()
                for alias in finding_aliases:
                    existing = alias_map.get(alias)
                    if existing is not None and id(existing) not in match_ids:
                        match_ids.add(id(existing))
                        matches.append(existing)
                if not matches:
                    merged = copy.deepcopy(finding)
                    observation = merged.pop("observation", {})
                    merged["source_views"] = {mode: observation}
                    merged["source_modes"] = [mode]
                    merged["aliases"] = sorted(finding_aliases)
                    target["findings"].append(merged)
                    for alias in finding_aliases:
                        alias_map[alias] = merged
                else:
                    existing = matches[0]
                    for duplicate in matches[1:]:
                        _merge_existing_contract_finding(existing, duplicate)
                        duplicate["_merged_into"] = True
                    _merge_contract_observation(existing, finding, mode)
                    existing_aliases = set(_finding_aliases(existing))
                    existing_aliases.update(finding_aliases)
                    existing["aliases"] = sorted(existing_aliases)
                    if _key_basis_rank(finding.get("key_basis")) > _key_basis_rank(
                        existing.get("key_basis")
                    ):
                        existing["key"] = finding["key"]
                        existing["key_basis"] = finding.get("key_basis")
                    for alias in existing_aliases:
                        alias_map[alias] = existing

    for category in merged_categories.values():
        category["findings"] = [
            finding
            for finding in category["findings"]
            if finding.pop("_merged_into", None) is None
        ]
        mode_order = {mode: index for index, mode in enumerate(ANALYSIS_MODES)}
        for finding in category["findings"]:
            finding["source_modes"] = sorted(
                set(finding.get("source_modes") or ()),
                key=lambda mode: (mode_order.get(mode, len(mode_order)), str(mode)),
            )
        enriched_is_authoritative = (
            category.get("source_execution_status", {}).get(GERBER_ENRICHED)
            == "completed"
        )
        if enriched_is_authoritative:
            # Enriched Gerber is a derived, UUID-mapped view of strict Gerber.
            # A finding retained by enrichment either merges through its
            # immutable source alias or appears as its own enriched finding.
            # Therefore a strict-only finding means enrichment deliberately
            # suppressed it (for example, a proven local NetTie contact).  Keep
            # it in the strict source view, not in the combined verdict.
            category["findings"] = [
                finding
                for finding in category["findings"]
                if not (
                    GERBER_STRICT in (finding.get("source_modes") or ())
                    and GERBER_ENRICHED not in (finding.get("source_modes") or ())
                    and KICAD_NATIVE not in (finding.get("source_modes") or ())
                )
            ]
        counted_source_modes = []
        if KICAD_NATIVE in category["source_counts"]:
            counted_source_modes.append(KICAD_NATIVE)
        if enriched_is_authoritative:
            counted_source_modes.append(GERBER_ENRICHED)
        elif GERBER_STRICT in category["source_counts"]:
            counted_source_modes.append(GERBER_STRICT)
        if not counted_source_modes and COMBINED in category["source_counts"]:
            counted_source_modes.append(COMBINED)
        category["counted_source_modes"] = counted_source_modes
        category["checked_count"] = sum(
            int(category["source_counts"][mode].get("checked") or 0)
            for mode in counted_source_modes
        )
        category["counts"]["checked"] = category["checked_count"]
        source_displayed = max(
            (
                int(category["source_counts"][mode].get("displayed") or 0)
                for mode in counted_source_modes
            ),
            default=0,
        )
        source_violations = max(
            (
                int(category["source_counts"][mode].get("violations") or 0)
                for mode in counted_source_modes
            ),
            default=0,
        )
        category["displayed_count"] = max(len(category["findings"]), source_displayed)
        finding_violations = sum(
            1 for finding in category["findings"] if finding.get("is_violation")
        )
        category["violation_count"] = max(finding_violations, source_violations)
        category["counts"].update(
            displayed=category["displayed_count"],
            violations=category["violation_count"],
        )
        category["count_basis"] = {
            "checked": "executed_source_sum_excluding_redundant_strict",
            "violations": "stable_key_union_with_source_lower_bound",
            "displayed": "stable_key_union_with_source_lower_bound",
        }
        if category["execution_status"] == "completed":
            category["result_status"] = (
                "violations_found" if category["violation_count"] else "passed"
            )

    checked = sum(item["checked_count"] for item in merged_categories.values())
    violations = sum(item["violation_count"] for item in merged_categories.values())
    displayed = sum(item["displayed_count"] for item in merged_categories.values())
    return {
        "contract_version": CONTRACT_VERSION,
        "mode": COMBINED,
        "execution_status": (
            "completed"
            if all(item.get("execution_status") == "completed" for item in contracts)
            else "partial"
        ),
        "counts": {"checked": checked, "violations": violations, "displayed": displayed},
        "checked_count": checked,
        "violation_count": violations,
        "displayed_count": displayed,
        "categories": merged_categories,
        "source_views": source_views,
        "metadata": {"merge_strategy": "canonical_and_source_alias_union"},
    }


@dataclass
class AnalysisStageResult:
    mode: str
    analysis_result: dict
    kicad_result: dict = field(default_factory=dict)
    issues: tuple = ()
    summary: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    contract: dict = field(default_factory=dict)
    input_paths: tuple = ()
    export_summary: dict = field(default_factory=dict)
    source_views: dict = field(default_factory=dict)

    def __post_init__(self):
        self.mode = canonical_mode(self.mode)
        if not self.contract:
            self.contract = build_analysis_contract(
                self.mode,
                self.analysis_result,
                self.issues,
                self.summary,
                profile=self.profile,
            )
        self.source_views = normalize_source_views(self.source_views)


@dataclass
class CombinedAnalysisResult:
    native: AnalysisStageResult
    gerber: AnalysisStageResult
    analysis_result: dict
    kicad_result: dict
    issues: tuple
    summary: dict
    contract: dict
    source_views: dict


class CombinedAnalysisService:
    """Run the native and Gerber pipelines in a deterministic order."""

    def __init__(self, native_runner, gerber_runner, gerber_mode=GERBER_ENRICHED):
        self.native_runner = native_runner
        self.gerber_runner = gerber_runner
        self.gerber_mode = canonical_mode(gerber_mode)

    def run(self):
        native = _coerce_stage(self.native_runner(), KICAD_NATIVE)
        gerber = _coerce_stage(self.gerber_runner(), self.gerber_mode)
        analysis_result = merge_legacy_analysis_views(
            native.analysis_result,
            gerber.analysis_result,
            native.mode,
            gerber.mode,
        )
        source_issues = _merge_issues(native.issues, gerber.issues)
        issues = _merge_issues(
            source_issues,
            _gerber_finding_issues(analysis_result, source_issues),
        )
        summary = _merge_summary(native.summary, gerber.summary, analysis_result, issues)
        source_contracts = [native.contract]
        for source_view in gerber.source_views.values():
            if isinstance(source_view, dict) and isinstance(source_view.get("contract"), dict):
                source_contracts.append(source_view["contract"])
        source_contracts.append(gerber.contract)
        contract = merge_analysis_contracts(*source_contracts)
        source_views = {
            native.mode: _stage_source_view(native),
            gerber.mode: _stage_source_view(gerber),
        }
        # Each stage view above is normalized into an independent snapshot.
        # Gerber's strict source view was normalized when its stage was built;
        # copy it once for ownership by the combined result.  Avoiding another
        # normalize pass here removes a full traversal of the complete result
        # tree without weakening snapshot isolation.
        source_views.update(copy.deepcopy(gerber.source_views))
        return CombinedAnalysisResult(
            native=native,
            gerber=gerber,
            analysis_result=analysis_result,
            kicad_result=copy.deepcopy(analysis_result),
            issues=issues,
            summary=summary,
            contract=contract,
            source_views=source_views,
        )


def merge_legacy_analysis_views(left, right, left_mode=KICAD_NATIVE, right_mode=GERBER_ENRICHED):
    """Union legacy rows while keeping enough provenance for old UI consumers."""
    left_mode = canonical_mode(left_mode)
    right_mode = canonical_mode(right_mode)
    left = left if isinstance(left, dict) else {}
    right = right if isinstance(right, dict) else {}
    categories = list(left)
    categories.extend(category for category in right if category not in categories)
    result = {}
    for category in categories:
        source_results = (
            (left_mode, left.get(category)),
            (right_mode, right.get(category)),
        )
        mappings = [item for _mode, item in source_results if isinstance(item, dict)]
        if not mappings:
            result[category] = ""
            continue
        preferred = max(mappings, key=lambda item: _color_rank(item.get("color")))
        merged = copy.deepcopy(preferred)
        merged["check"] = []
        merged["source_views"] = {
            mode: _legacy_headline(item)
            for mode, item in source_results
            if isinstance(item, dict)
        }
        rows_by_key = {}
        for mode, source_result in source_results:
            if not isinstance(source_result, dict):
                continue
            for check in source_result.get("check") or ():
                if not isinstance(check, dict):
                    continue
                rows = check.get("result") or ()
                if not rows:
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    key = stable_finding_key(category, row)
                    if key in rows_by_key:
                        existing = rows_by_key[key]
                        source_modes = existing.setdefault("_source_modes", [])
                        if mode not in source_modes:
                            source_modes.append(mode)
                        existing.setdefault("_source_views", {})[mode] = copy.deepcopy(row)
                        if _observation_rank(row) > _observation_rank(existing):
                            _promote_legacy_observation(existing, row)
                        continue
                    merged_row = copy.deepcopy(row)
                    merged_row["_finding_key"] = key
                    merged_row["_source_modes"] = [mode]
                    merged_row["_source_views"] = {mode: copy.deepcopy(row)}
                    merged_check = {key: copy.deepcopy(value) for key, value in check.items() if key != "result"}
                    merged_check["result"] = [merged_row]
                    merged["check"].append(merged_check)
                    rows_by_key[key] = merged_row
        _recompute_legacy_metrics(merged, category, source_results)
        result[category] = merged
    return result


def _recompute_legacy_metrics(merged, category, source_results):
    """Backfill legacy headline metrics from the union, never one source."""
    rows = list(_iter_rows(merged))
    sources = {
        mode: source_result
        for mode, source_result in source_results
        if isinstance(source_result, dict)
    }
    counted_modes = _counted_legacy_modes(sources)
    checked_count = sum(
        _legacy_metric(source, "checked_count", len(list(_iter_rows(source))))
        for mode, source in sources.items()
        if mode in counted_modes
    )
    available_count = sum(
        _legacy_metric(
            source,
            "available_count",
            _legacy_metric(source, "checked_count", len(list(_iter_rows(source)))),
        )
        for mode, source in sources.items()
        if mode in counted_modes
    )
    suppressed_count = sum(
        _legacy_metric(source, "suppressed_count", 0)
        for mode, source in sources.items()
        if mode in counted_modes
    )
    merged.update(
        checked_count=checked_count,
        available_count=available_count,
        violation_count=sum(_legacy_row_is_violation(row) for row in rows),
        suppressed_count=suppressed_count,
        borderline_count=sum(
            str(row.get("threshold_status") or "").lower() == "borderline"
            for row in rows
        ),
        displayed_count=len(rows),
        visible_count=len(rows),
        checked_count_basis="executed_source_sum_excluding_redundant_strict",
        item_summaries=_merged_legacy_item_summaries(rows, sources, counted_modes),
    )
    if rows:
        merged["color"] = _aggregate_legacy_color(rows)
    if sources:
        merged["execution_status"] = (
            "completed"
            if any(
                str(source.get("execution_status") or "completed") == "completed"
                for source in sources.values()
            )
            else next(iter(sources.values())).get("execution_status", "not_computed")
        )


def _counted_legacy_modes(sources):
    modes = []
    if KICAD_NATIVE in sources:
        modes.append(KICAD_NATIVE)
    if GERBER_ENRICHED in sources:
        modes.append(GERBER_ENRICHED)
    elif GERBER_STRICT in sources:
        modes.append(GERBER_STRICT)
    if not modes and COMBINED in sources:
        modes.append(COMBINED)
    return tuple(modes)


def _legacy_metric(mapping, name, fallback=0):
    try:
        return int(mapping.get(name))
    except (AttributeError, TypeError, ValueError):
        return int(fallback or 0)


def _legacy_item_identity(row):
    return str(row.get("rule_key") or row.get("item") or "")


def _source_item_identity(source_result, source_key, source_summary):
    explicit = source_summary.get("rule_key") if isinstance(source_summary, dict) else None
    if explicit:
        return str(explicit)
    item_name = source_summary.get("item") if isinstance(source_summary, dict) else None
    aliases = {str(source_key), str(item_name or "")}
    for row in _iter_rows(source_result):
        if str(row.get("item") or "") in aliases:
            return _legacy_item_identity(row)
    return str(source_key)


def _source_item_summary(source_result, identity):
    for source_key, source_summary in (source_result.get("item_summaries") or {}).items():
        if not isinstance(source_summary, dict):
            continue
        if _source_item_identity(source_result, source_key, source_summary) == identity:
            return source_summary
    return None


def _merged_legacy_item_summaries(rows, sources, counted_modes):
    ordered_identities = []
    for row in rows:
        identity = _legacy_item_identity(row)
        if identity and identity not in ordered_identities:
            ordered_identities.append(identity)
    for source in sources.values():
        for source_key, source_summary in (source.get("item_summaries") or {}).items():
            if not isinstance(source_summary, dict):
                continue
            identity = _source_item_identity(source, source_key, source_summary)
            if identity and identity not in ordered_identities:
                ordered_identities.append(identity)

    merged_summaries = {}
    for identity in ordered_identities:
        item_rows = [row for row in rows if _legacy_item_identity(row) == identity]
        source_summaries = [
            summary
            for source in sources.values()
            for summary in (_source_item_summary(source, identity),)
            if isinstance(summary, dict)
        ]
        preferred = max(
            source_summaries,
            key=lambda summary: _color_rank(summary.get("color")),
            default={},
        )
        item_summary = {
            key: copy.deepcopy(value)
            for key, value in preferred.items()
            if key
            not in {
                "checked_count",
                "available_count",
                "violation_count",
                "suppressed_count",
                "borderline_count",
                "displayed_count",
                "visible_count",
                "display",
                "color",
            }
        }
        first_row = item_rows[0] if item_rows else {}
        item_summary.setdefault("rule_key", first_row.get("rule_key") or identity)
        item_summary.setdefault("item", first_row.get("item") or preferred.get("item", ""))
        checked_count = 0
        available_count = 0
        suppressed_count = 0
        for mode in counted_modes:
            source = sources.get(mode) or {}
            summary = _source_item_summary(source, identity)
            source_rows = [
                row for row in _iter_rows(source) if _legacy_item_identity(row) == identity
            ]
            source_checked = _legacy_metric(summary or {}, "checked_count", len(source_rows))
            checked_count += source_checked
            available_count += _legacy_metric(
                summary or {}, "available_count", source_checked
            )
            suppressed_count += _legacy_metric(summary or {}, "suppressed_count", 0)
        item_summary.update(
            checked_count=checked_count,
            available_count=available_count,
            violation_count=sum(_legacy_row_is_violation(row) for row in item_rows),
            suppressed_count=suppressed_count,
            borderline_count=sum(
                str(row.get("threshold_status") or "").lower() == "borderline"
                for row in item_rows
            ),
            displayed_count=len(item_rows),
            visible_count=len(item_rows),
            execution_status="completed",
            checked_count_basis="executed_source_sum_excluding_redundant_strict",
            display=_merged_item_display(item_rows, preferred.get("display", "")),
            color=_aggregate_legacy_color(item_rows),
        )
        merged_summaries[identity] = item_summary
    return merged_summaries


def _merged_item_display(rows, fallback):
    values = []
    for row in rows:
        for observation in _legacy_row_observations(row):
            try:
                values.append(float(observation.get("value")))
            except (TypeError, ValueError):
                continue
    if not values:
        return copy.deepcopy(fallback)
    item = str(rows[0].get("item") or "").lower()
    identity = "".join(
        character
        for character in "{0}:{1}".format(
            rows[0].get("rule_key") or "",
            item,
        ).lower()
        if character.isalnum()
    )
    if "slotaspectratio" in identity:
        return min(values)
    if "largest" in item or "maximum" in item or "aspectratio" in identity:
        return max(values)
    return min(values)


def _legacy_row_is_violation(row):
    return any(
        str(observation.get("color") or "").lower() in _VIOLATION_COLORS
        or str(observation.get("severity") or "").lower() in _VIOLATION_SEVERITIES
        for observation in _legacy_row_observations(row)
    )


def _aggregate_legacy_color(rows):
    observations = [
        observation
        for row in rows
        for observation in _legacy_row_observations(row)
    ]
    colors = [str(row.get("color") or "").lower() for row in observations]
    if any(
        str(row.get("severity") or "").lower() in {"error", "fatal"}
        for row in observations
    ):
        colors.append("red")
    elif any(
        str(row.get("severity") or "").lower() == "warning"
        for row in observations
    ):
        colors.append("gold")
    return max(colors, key=_color_rank, default="black") or "black"


def _legacy_row_observations(row):
    yield row
    for observation in (row.get("_source_views") or {}).values():
        if isinstance(observation, dict):
            yield observation


def _category_contract(mode, category, legacy, issues, summary):
    if not isinstance(legacy, dict):
        if summary is not None:
            summary_value = _summary_value(summary)
            summary_issues = (
                getattr(summary, "issues", ())
                if dataclasses.is_dataclass(summary)
                else summary.get("issues", ()) if isinstance(summary, dict) else ()
            )
            violation_count = max(
                _issue_violation_count(issues),
                _issue_violation_count(summary_issues),
            )
            return {
                "execution_status": "completed",
                "result_status": "violations_found" if violation_count else "passed",
                "counts": {"checked": 0, "violations": violation_count, "displayed": 0},
                "checked_count": 0,
                "violation_count": violation_count,
                "displayed_count": 0,
                "count_basis": {
                    "checked": "summary_only",
                    "violations": "summary_issues",
                    "displayed": "summary_only",
                },
                "findings": [],
                "summary": summary_value,
            }
        return {
            "execution_status": "not_computed",
            "result_status": "not_computed",
            "counts": {"checked": 0, "violations": 0, "displayed": 0},
            "checked_count": 0,
            "violation_count": 0,
            "displayed_count": 0,
            "count_basis": {
                "checked": "not_available",
                "violations": "not_available",
                "displayed": "not_available",
            },
            "findings": [],
            "summary": _summary_value(summary),
        }
    rows = list(_iter_rows(legacy))
    findings = [_finding_contract(mode, category, row) for row in rows]
    issue_violation_count = sum(
        1 for issue in issues if str(getattr(issue, "severity", "")).lower() in _VIOLATION_SEVERITIES
    )
    row_violation_count = sum(1 for finding in findings if finding["is_violation"])
    provided_violation = legacy.get("violation_count")
    try:
        violation_count = int(provided_violation)
        violation_basis = "provided"
    except (TypeError, ValueError):
        violation_count = max(issue_violation_count, row_violation_count)
        violation_basis = "reported_rows_and_issues"
    provided_checked = legacy.get("checked_count", legacy.get("_checked_count"))
    try:
        checked_count = int(provided_checked)
        checked_basis = legacy.get("checked_count_basis") or "provided"
    except (TypeError, ValueError):
        checked_count = len(rows)
        checked_basis = "displayed_lower_bound"
    try:
        displayed_count = int(legacy.get("displayed_count"))
        displayed_basis = "provided"
    except (TypeError, ValueError):
        displayed_count = len(rows)
        displayed_basis = "legacy_result_rows"
    category_execution = str(legacy.get("execution_status") or "completed")
    return {
        "execution_status": category_execution,
        "result_status": (
            "violations_found" if violation_count else "passed"
        )
        if category_execution == "completed"
        else category_execution,
        "counts": {
            "checked": checked_count,
            "violations": violation_count,
            "displayed": displayed_count,
        },
        "checked_count": checked_count,
        "violation_count": violation_count,
        "displayed_count": displayed_count,
        "count_basis": {
            "checked": checked_basis,
            "violations": violation_basis,
            "displayed": displayed_basis,
        },
        "coverage": legacy.get("coverage", "unknown"),
        "available_count": legacy.get("available_count"),
        "suppressed_count": legacy.get("suppressed_count"),
        "visible_count": legacy.get("visible_count"),
        "item_summaries": _json_value(legacy.get("item_summaries") or {}),
        "findings": findings,
        "summary": _summary_value(summary, legacy),
    }


def _finding_contract(mode, category, row):
    color = str(row.get("color") or "").lower()
    severity = str(row.get("severity") or "").lower()
    geometry_basis = row.get("geometry_basis") or _default_geometry_basis(mode, row)
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    measurement_basis = raw.get("measurement_basis") or _default_measurement_basis(mode, row)
    return {
        "key": stable_finding_key(category, row),
        "source_key": source_finding_key(category, row),
        "key_basis": _finding_key_basis(row),
        "category": category,
        "rule_key": row.get("rule_key") or rule_key(category, row.get("item", "")),
        "item": row.get("item", ""),
        "is_violation": color in _VIOLATION_COLORS or severity in _VIOLATION_SEVERITIES,
        "geometry_basis": geometry_basis,
        "measurement_basis": measurement_basis,
        "observation": _json_value(row),
    }


def _finding_aliases(finding):
    aliases = set(finding.get("aliases") or ())
    for name in ("key", "source_key"):
        value = finding.get(name)
        if value:
            aliases.add(value)
    return aliases


def _merge_contract_observation(existing, finding, mode):
    existing.setdefault("source_views", {})[mode] = copy.deepcopy(
        finding.get("observation") or finding.get("source_views", {}).get(mode) or {}
    )
    source_modes = existing.setdefault("source_modes", [])
    if mode not in source_modes:
        source_modes.append(mode)
    existing["is_violation"] = bool(
        existing.get("is_violation") or finding.get("is_violation")
    )


def _merge_existing_contract_finding(existing, duplicate):
    existing.setdefault("source_views", {}).update(
        copy.deepcopy(duplicate.get("source_views") or {})
    )
    source_modes = existing.setdefault("source_modes", [])
    for mode in duplicate.get("source_modes") or ():
        if mode not in source_modes:
            source_modes.append(mode)
    aliases = _finding_aliases(existing)
    aliases.update(_finding_aliases(duplicate))
    existing["aliases"] = sorted(aliases)
    existing["is_violation"] = bool(
        existing.get("is_violation") or duplicate.get("is_violation")
    )
    if _key_basis_rank(duplicate.get("key_basis")) > _key_basis_rank(
        existing.get("key_basis")
    ):
        existing["key"] = duplicate.get("key")
        existing["key_basis"] = duplicate.get("key_basis")


def _finding_key_basis(row):
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    primary = _stable_object_identity(row.get("id"), raw, "primary")
    if primary:
        return "object_id"
    if row.get("finding_key"):
        return "fabrication_geometry"
    return "geometry"


def _key_basis_rank(value):
    return {
        "geometry": 1,
        "fabrication_geometry": 2,
        "object_id": 3,
    }.get(str(value or ""), 0)


def _coerce_stage(value, mode):
    if isinstance(value, AnalysisStageResult):
        return value
    return AnalysisStageResult(
        mode=mode,
        analysis_result=getattr(value, "analysis_result", {}) or {},
        kicad_result=getattr(value, "kicad_result", {}) or {},
        issues=tuple(getattr(value, "issues", ()) or ()),
        summary=getattr(value, "summary", {}) or {},
        profile=getattr(value, "profile", {}) or {},
        contract=getattr(value, "contract", {}) or {},
    )


def _stage_source_view(stage):
    return normalize_source_views(
        {
            stage.mode: {
                "analysis_result": stage.analysis_result,
                "kicad_result": stage.kicad_result,
                "issues": stage.issues,
                "summary": stage.summary,
                "profile": stage.profile,
                "contract": stage.contract,
                "input_paths": stage.input_paths,
                "export_summary": stage.export_summary,
            }
        }
    )[stage.mode]


def _iter_rows(result):
    for check in result.get("check") or ():
        if not isinstance(check, dict):
            continue
        for row in check.get("result") or ():
            if isinstance(row, dict):
                yield row


def _stable_object_identity(value, raw, side):
    text = str(value or "")
    if text and not _looks_like_export_file(text):
        return "id:" + text.lower()
    mapping = raw.get("uuid_mapping") if isinstance(raw, dict) else None
    if isinstance(mapping, dict):
        if side == "related":
            related_mapping = mapping.get("related")
            mapped = (
                related_mapping.get("id")
                if isinstance(related_mapping, dict)
                else None
            )
        else:
            mapped = mapping.get("id")
        if mapped:
            return "id:" + str(mapped).lower()
    object_id = raw.get("object_id") if isinstance(raw, dict) else None
    component = raw.get("component") if isinstance(raw, dict) else None
    if object_id or component:
        return "x2:{0}:{1}".format(str(component or "").lower(), str(object_id or "").lower())
    return ""


def _geometry_identity(row, raw):
    geometry = {}
    for key in ("point", "segment", "bbox", "diameter", "width", "pad_size"):
        if key in raw:
            geometry[key] = _rounded_geometry(raw.get(key))
    if not geometry:
        for key in ("x_nm", "y_nm", "bbox_nm"):
            if key in row:
                geometry[key] = row.get(key)
    file_name = raw.get("file") or row.get("id")
    if file_name and _looks_like_export_file(file_name):
        geometry["file"] = os.path.basename(str(file_name)).lower()
    return geometry


def _rounded_geometry(value):
    if isinstance(value, (list, tuple)):
        return [_rounded_geometry(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def _normalized_layers(value):
    if isinstance(value, str):
        value = (value,)
    return tuple(sorted(str(item).lower() for item in (value or ()) if item is not None))


def _has_physical_aggregation(raw):
    if not isinstance(raw, dict):
        return False
    try:
        measurement_count = int(raw.get("physical_measurement_count") or 0)
    except (TypeError, ValueError):
        measurement_count = 0
    measurements = raw.get("per_layer_measurements")
    if measurement_count <= 1 or not isinstance(measurements, (tuple, list)):
        return False
    layers = set()
    for measurement in measurements:
        if not isinstance(measurement, dict):
            continue
        value = measurement.get("layer") or ()
        if isinstance(value, str):
            value = (value,)
        layers.update(str(layer).lower() for layer in value if layer is not None)
    # Multiple contours on one layer are still distinct layer-scoped evidence.
    # Only a proven cross-layer physical fold (for example one PTH) may omit
    # the layer from the stable finding identity.
    return len(layers) > 1


def _is_intrinsically_cross_layer_physical(category, row, raw):
    if str(category or "") not in (
        "Copper-to-Board Edge",
        "Hole-to-Board Edge",
    ):
        return False
    primary = raw.get("primary") if isinstance(raw, dict) else None
    if isinstance(primary, dict) and primary.get("through_hole"):
        return True
    # Native copper-edge rows contain the PCB object type but do not carry a
    # per-layer raw envelope.  A non-SMD PAD or VIA row is one physical drilled
    # feature even though its locatable representative layer is normally F.Cu.
    item_type = str(row.get("item_type") or "").upper()
    rule_identity = str(row.get("rule_key") or "").lower()
    if str(category or "") == "Hole-to-Board Edge":
        return "PAD" in item_type or "VIA" in item_type
    return (
        ("PAD" in item_type or "VIA" in item_type)
        and not rule_identity.endswith(":smdtoboardedge")
    )


def _is_symmetric_finding(row):
    return bool(row.get("related_id") or (row.get("raw") or {}).get("related"))


def _looks_like_export_file(value):
    text = str(value or "").lower()
    return text.endswith((".gbr", ".ger", ".drl", ".xln")) or "/" in text or "\\" in text


def _default_geometry_basis(mode, row):
    if mode == KICAD_NATIVE:
        return "exact_kicad"
    return "excellon_derived" if row.get("source") == "drill" else "gerber_derived"


def _default_measurement_basis(mode, row):
    if mode == KICAD_NATIVE:
        return "kicad"
    return "excellon" if row.get("source") == "drill" else "gerber"


def _summary_value(summary, legacy=None):
    if dataclasses.is_dataclass(summary):
        value = _json_value(summary)
    elif isinstance(summary, dict):
        value = _json_value(summary)
    else:
        value = {}
    if legacy:
        value.setdefault("display", legacy.get("display", ""))
        value.setdefault("display_inch", legacy.get("display_inch", ""))
        value.setdefault("color", legacy.get("color", ""))
    return value


def _legacy_headline(result):
    return {
        key: copy.deepcopy(result.get(key))
        for key in ("display", "display_inch", "color")
        if key in result
    }


def _merge_issues(*issue_groups):
    result = []
    seen = set()
    for issue in (issue for group in issue_groups for issue in (group or ())):
        location = getattr(issue, "location", None)
        identity = (
            getattr(issue, "category", ""),
            getattr(issue, "item", ""),
            getattr(location, "item_id", None),
            getattr(location, "x_nm", None),
            getattr(location, "y_nm", None),
            str(getattr(issue, "value", "")),
            str(getattr(issue, "message", "")),
            json.dumps(
                _json_value(getattr(issue, "raw", None)),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        if identity not in seen:
            seen.add(identity)
            result.append(issue)
    return tuple(result)


def _gerber_finding_issues(analysis_result, existing_issues=()):
    """Create one locatable issue for each otherwise-unrepresented Gerber violation.

    A native and an enriched Gerber observation can share one stable finding
    even when quantization or engine semantics make only the Gerber observation
    violate its threshold.  In that case the Gerber discrepancy must remain in
    the combined issue/summary view.  If the native observation already
    violates, its native issue remains authoritative and no duplicate is made.
    """
    issues = []
    existing_keys = {
        key for key in (_issue_stable_finding_key(issue) for issue in existing_issues) if key
    }
    for category, legacy in (analysis_result or {}).items():
        if category == "Gerber Export" or not isinstance(legacy, dict):
            continue
        for row in _iter_rows(legacy):
            observations = _row_source_observations(row)
            native_observation = observations.get(KICAD_NATIVE)
            if native_observation is not None and _legacy_row_is_violation(
                native_observation
            ):
                continue
            violating_gerber = [
                (mode, observation)
                for mode, observation in observations.items()
                if mode in (GERBER_STRICT, GERBER_ENRICHED)
                and _legacy_row_is_violation(observation)
            ]
            if not violating_gerber:
                continue
            finding_key = row.get("_finding_key") or stable_finding_key(category, row)
            if finding_key in existing_keys:
                continue
            mode, observation = max(
                violating_gerber,
                key=lambda item: (
                    _observation_rank(item[1]),
                    1 if item[0] == GERBER_ENRICHED else 0,
                ),
            )
            violating_modes = sorted(
                {item[0] for item in violating_gerber},
                key=lambda value: ANALYSIS_MODES.index(value),
            )
            raw = copy.deepcopy(observation.get("raw") or {})
            raw.update(
                issue_kind="dfm_finding",
                source_mode=mode,
                source_modes=violating_modes,
                stable_finding_key=finding_key,
                engine_discrepancy=native_observation is not None,
            )
            color = _aggregate_legacy_color((observation,))
            severity = str(observation.get("severity") or "").lower()
            if severity not in _VIOLATION_SEVERITIES:
                severity = "error" if color == "red" else "warning"
            issues.append(
                DfmIssue(
                    category=category,
                    item=str(observation.get("item") or ""),
                    severity=severity,
                    layer=copy.deepcopy(observation.get("layer")),
                    value=str(observation.get("value") or ""),
                    rule=str(observation.get("rule") or ""),
                    message=str(observation.get("message") or ""),
                    location=_legacy_row_location(observation),
                    raw=raw,
                )
            )
            existing_keys.add(finding_key)
    return tuple(issues)


def _row_source_observations(row):
    observations = {}
    for mode, observation in (row.get("_source_views") or {}).items():
        if not isinstance(observation, dict):
            continue
        try:
            observations[canonical_mode(mode)] = observation
        except ValueError:
            continue
    if observations:
        return observations
    for mode in row.get("_source_modes") or ():
        try:
            observations[canonical_mode(mode)] = row
        except ValueError:
            continue
    return observations


def _issue_stable_finding_key(issue):
    raw = getattr(issue, "raw", None)
    raw = raw if isinstance(raw, dict) else {}
    explicit = raw.get("stable_finding_key")
    if explicit:
        return str(explicit)
    location = getattr(issue, "location", None)
    row = copy.deepcopy(raw)
    row.setdefault("item", getattr(issue, "item", ""))
    if location is not None:
        row.setdefault("id", getattr(location, "item_id", None))
        row.setdefault("layer", getattr(location, "layer", None))
        row.setdefault("x_nm", getattr(location, "x_nm", None))
        row.setdefault("y_nm", getattr(location, "y_nm", None))
        row.setdefault("bbox_nm", getattr(location, "bbox_nm", None))
    geometry = row.get("raw") if isinstance(row.get("raw"), dict) else row
    has_identity = bool(
        row.get("id")
        or row.get("related_id")
        or any(
            geometry.get(key) is not None
            for key in ("point", "segment", "bbox", "object_id", "component")
        )
        or row.get("x_nm") is not None
        or row.get("bbox_nm") is not None
    )
    if not has_identity:
        return ""
    return stable_finding_key(getattr(issue, "category", ""), row)


def _observation_rank(row):
    severity = str(row.get("severity") or "").lower()
    if severity in ("fatal", "error"):
        return 3
    if severity == "warning":
        return 2
    return _color_rank(row.get("color"))


def _promote_legacy_observation(existing, observation):
    """Promote the worst observation without replacing merged identity data."""
    identity_keys = (
        "id",
        "related_id",
        "item",
        "rule_key",
        "layer",
        "related_layer",
        "_finding_key",
        "_source_modes",
        "_source_views",
    )
    identity = {
        key: copy.deepcopy(existing[key]) for key in identity_keys if key in existing
    }
    existing.clear()
    existing.update(copy.deepcopy(observation))
    existing.update(identity)


def _legacy_row_location(row):
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    x_nm = row.get("x_nm")
    y_nm = row.get("y_nm")
    bbox_nm = row.get("bbox_nm")
    point = raw.get("point")
    if (x_nm is None or y_nm is None) and isinstance(point, (list, tuple)) and len(point) >= 2:
        try:
            x_nm = int(round(float(point[0]) * 1000000.0))
            y_nm = int(round(float(point[1]) * 1000000.0))
        except (TypeError, ValueError):
            x_nm = y_nm = None
    if bbox_nm is None:
        bbox = raw.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                bbox_nm = tuple(int(round(float(value) * 1000000.0)) for value in bbox)
            except (TypeError, ValueError):
                bbox_nm = None
    return Location(
        item_id=row.get("id"),
        item_type=str(row.get("item_type") or ""),
        layer=copy.deepcopy(row.get("layer")),
        x_nm=x_nm,
        y_nm=y_nm,
        bbox_nm=bbox_nm,
    )


def _merge_summary(native, gerber, analysis_result, issues):
    result = dict(native or {})
    result.update(gerber or {})
    for category, legacy in analysis_result.items():
        if not isinstance(legacy, dict):
            continue
        result[category] = DfmSummary(
            category=category,
            display=str(legacy.get("display", "")),
            display_inch=str(legacy.get("display_inch", "")),
            color=legacy.get("color", ""),
            issues=tuple(issue for issue in issues if getattr(issue, "category", None) == category),
        )
    return result


def _color_rank(color):
    return {"": 0, "black": 1, "gold": 2, "red": 3}.get(str(color or "").lower(), 0)


def _json_value(value):
    if dataclasses.is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _issue_violation_count(issues):
    return sum(
        1
        for issue in issues or ()
        if str(
            getattr(
                issue,
                "severity",
                issue.get("severity", "") if isinstance(issue, dict) else "",
            )
        ).lower()
        in _VIOLATION_SEVERITIES
    )
