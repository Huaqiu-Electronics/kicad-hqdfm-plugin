import math
import bisect
import time
from dataclasses import dataclass, replace

from kicad_dfm.core.models import DfmIssue, Location
from kicad_dfm.core.pad_size import pad_shorter_side_mm, pad_size_item
from kicad_dfm.core.rule_contract import rule_key
from kicad_dfm.kicad.swig import SwigBackend
from kicad_dfm.services.board_statistics import calculate_board_statistics
from kicad_dfm.services.board_statistics import statistic_result_map
from kicad_dfm.settings.color_rule import ColorRule


NM_PER_MM = 1000000.0
ACUTE_ANGLE_TOLERANCE_DEGREES = 1.0
ACUTE_ANGLE_MINIMUM_DEGREES = 1.0
ACUTE_ENDPOINT_TOLERANCE_NM = 1.0
ZONE_DISTANCE_SEARCH_NM = 2000000.0
ZONE_EDGE_BUCKET_NM = 2000000
NET_TIE_CONTACT_TOLERANCE_MM = 0.000001
HEARTBEAT_INTERVAL_SECONDS = 0.05


def net_tie_groups_by_pad_id(raw_groups):
    """Normalize declared NetTie groups without losing their local pad scope."""
    groups_by_pad_id = {}
    for raw_group in raw_groups or ():
        members = {}
        for raw_member in raw_group or ():
            if not isinstance(raw_member, (tuple, list)) or len(raw_member) < 2:
                continue
            pad_id = str(raw_member[0] or "")
            net_name = str(raw_member[1] or "")
            if pad_id and net_name:
                members[pad_id] = net_name
        net_names = frozenset(members.values())
        if len(net_names) < 2:
            continue
        group = (members, net_names)
        for pad_id in members:
            groups_by_pad_id.setdefault(pad_id, []).append(group)
    return {
        pad_id: tuple(groups)
        for pad_id, groups in groups_by_pad_id.items()
    }


def declared_net_tie_pad_pair(
    groups_by_pad_id,
    left_pad_id,
    left_net,
    right_pad_id,
    right_net,
):
    """Return whether two current pad identities share one declared group."""
    left_pad_id = str(left_pad_id or "")
    right_pad_id = str(right_pad_id or "")
    left_net = str(left_net or "")
    right_net = str(right_net or "")
    if (
        not left_pad_id
        or not right_pad_id
        or not left_net
        or not right_net
        or left_pad_id == right_pad_id
        or left_net == right_net
    ):
        return False
    return any(
        members.get(left_pad_id) == left_net
        and members.get(right_pad_id) == right_net
        for members, _net_names in groups_by_pad_id.get(left_pad_id, ())
    )


def local_net_tie_attachment_candidates(
    groups_by_pad_id,
    reported_member_id,
    reported_member_net,
    ordinary_pad_id,
    ordinary_pad_net,
):
    """Return same-net member pads that can anchor one local attachment.

    This helper performs identity and declared-group checks only.  The caller
    must still prove that the ordinary pad is within each returned member's
    explicit local-clearance override.  Treating geometry separately keeps
    this function reusable by both native and mapped-Gerber result paths.
    """
    reported_member_id = str(reported_member_id or "")
    reported_member_net = str(reported_member_net or "")
    ordinary_pad_id = str(ordinary_pad_id or "")
    ordinary_pad_net = str(ordinary_pad_net or "")
    if (
        not reported_member_id
        or not reported_member_net
        or not ordinary_pad_id
        or not ordinary_pad_net
        or reported_member_id == ordinary_pad_id
        or reported_member_net == ordinary_pad_net
    ):
        return ()
    # A member of another NetTie group is not an ordinary locally attached
    # pad.  Keeping that distinction prevents two neighbouring groups from
    # accidentally inheriting each other's clearance exemption.
    if ordinary_pad_id in groups_by_pad_id:
        return ()

    candidates = []
    seen = set()
    for members, net_names in groups_by_pad_id.get(reported_member_id, ()):
        if (
            members.get(reported_member_id) != reported_member_net
            or ordinary_pad_net not in net_names
        ):
            continue
        for member_id, member_net in members.items():
            if (
                member_id == reported_member_id
                or member_net != ordinary_pad_net
                or member_id in seen
            ):
                continue
            seen.add(member_id)
            candidates.append((member_id, member_net))
    return tuple(candidates)


@dataclass(frozen=True)
class IndexedItem:
    item: object
    item_id: str
    item_type: str
    layer_name: str
    layer_id: object
    net_name: str
    bbox_nm: tuple = None
    segment_nm: tuple = None
    track_path_nm: tuple = ()
    track_endpoint_vectors_nm: tuple = ()
    geometry_basis: str = "exact_kicad"
    center_nm: tuple = None
    width_nm: int = 0
    pad_size_mm: tuple = None
    pad_shape: object = None
    pad_drill_mm: tuple = None
    pad_drill_shape: object = None
    pad_attr: object = None
    pad_radius_nm: float = 0.0
    pad_is_smd: bool = False
    pad_is_bga: bool = False
    pad_has_solder_mask_opening: bool = True
    pad_solder_mask_sides: tuple = ()
    is_via: bool = False
    is_track: bool = False
    is_pad: bool = False
    is_zone: bool = False
    via_drill_mm: float = 0.0
    via_is_micro: bool = False
    via_is_blind_buried: bool = False
    via_layer_pair: tuple = ()
    copper_layer_names: tuple = ()
    pad_copper_layers_known: bool = False
    hole_drill_mm: float = 0.0
    hole_radius_nm: float = 0.0
    is_round_pth: bool = False
    is_round_drill: bool = True
    hole_bbox_nm: tuple = None
    footprint_names: tuple = ()
    zone_polygons_nm: tuple = ()
    zone_edges_nm: tuple = ()
    zone_edge_x_starts: tuple = ()
    zone_edge_max_width: float = 0.0
    zone_is_teardrop: bool = False
    zone_edge_buckets: dict = None


@dataclass(frozen=True)
class GeometryCandidate:
    indexed: IndexedItem
    bbox_nm: tuple


@dataclass
class BoardIndex:
    tracks_by_layer: dict
    pads_by_layer: dict
    copper_pads_by_layer: dict
    smd_pads_by_layer: dict
    vias_by_layer: dict
    vias_by_net: dict
    pads_by_net: dict
    zones_by_layer: dict
    acute_cover_items: tuple
    acute_cover_x_starts: tuple
    acute_cover_max_width: float
    drawings_by_layer: dict
    mask_openings_by_side: dict
    mask_opening_x_starts_by_side: dict
    mask_opening_max_width_by_side: dict
    items_by_net: dict
    item_x_starts_by_net: dict
    item_max_width_by_net: dict
    connectable_items_by_net: dict
    connectable_x_starts_by_net: dict
    connectable_max_width_by_net: dict
    all_connectable_items: tuple
    all_connectable_x_starts: tuple
    all_connectable_max_width: float
    board_outline: tuple
    board_outline_bbox: tuple
    board_outline_segment_bboxes: tuple
    board_outline_x_starts: tuple
    board_outline_max_width: float
    copper_layer_names: tuple
    tracks: tuple
    pads: tuple
    copper_pads: tuple
    smd_pads: tuple
    zones: tuple
    vias: tuple
    holes: tuple
    hole_drill_candidates: tuple
    pad_x_starts_by_layer: dict
    pad_max_width_by_layer: dict
    copper_pad_x_starts_by_layer: dict
    copper_pad_max_width_by_layer: dict
    smd_pad_x_starts_by_layer: dict
    smd_pad_max_width_by_layer: dict
    track_x_starts_by_layer: dict
    track_max_width_by_layer: dict
    zone_x_starts_by_layer: dict
    zone_max_width_by_layer: dict
    board_thickness_mm: float
    layer_ids_by_name: dict


class LocalChecks:
    def __init__(
        self,
        control,
        board,
        backend=None,
        rules=None,
        include_passed_details=False,
        heartbeat=None,
    ):
        self.language = control
        self.board = board
        self.backend = backend or SwigBackend(board)
        self.rules = rules
        self.color_rule = ColorRule(rules)
        self.include_passed_details = include_passed_details
        self.issues = []
        self._rule_cache = {}
        self._rule_item_cache = {}
        self._via_span_layer_cache = {}
        self._vias_by_copper_layer_cache = {}
        self._heartbeat = heartbeat
        self._heartbeat_count = 0
        self._heartbeat_last_at = None
        self._statistic_results = None
        self.index = self.build_index()
        self._pads_by_id = {
            pad.item_id: pad
            for pad in self.index.pads
            if pad.item_id
        }
        self._pad_local_clearance_mm_cache = {}
        self._net_tie_groups_by_pad_id = self._build_net_tie_pad_groups()
        self._net_tie_footprint_pad_ids = self._build_net_tie_footprint_pad_ids()

    def set_heartbeat(self, heartbeat):
        self._heartbeat = heartbeat
        self._heartbeat_count = 0
        self._heartbeat_last_at = None

    def _checkpoint(self):
        self._heartbeat_count += 1
        if self._heartbeat is not None and self._heartbeat_count % 32 == 0:
            now = time.monotonic()
            if (
                self._heartbeat_last_at is None
                or now - self._heartbeat_last_at >= HEARTBEAT_INTERVAL_SECONDS
            ):
                self._heartbeat_last_at = now
                self._heartbeat()

    def _checkpointed(self, items):
        for item in items:
            self._checkpoint()
            yield item

    def build_index(self):
        tracks_by_layer = {}
        vias_by_layer = {}
        vias_by_net = {}
        items_by_net = {}
        vias = []
        for item in self._checkpointed(self.backend.iter_tracks()):
            indexed = self._index_item(item, item_kind="track_or_via")
            if indexed.is_via:
                vias.append(indexed)
                vias_by_layer.setdefault(indexed.layer_name, []).append(indexed)
                vias_by_net.setdefault(indexed.net_name, []).append(indexed)
            elif indexed.is_track:
                tracks_by_layer.setdefault(indexed.layer_name, []).append(indexed)
            items_by_net.setdefault(indexed.net_name, []).append(indexed)

        pads_by_layer = {}
        pads_by_net = {}
        for footprint in self._checkpointed(self.backend.iter_footprints()):
            for pad in self._checkpointed(self.backend.iter_pads(footprint)):
                indexed = self._index_item(pad, footprint, item_kind="pad")
                pads_by_layer.setdefault(indexed.layer_name, []).append(indexed)
                pads_by_net.setdefault(indexed.net_name, []).append(indexed)
                items_by_net.setdefault(indexed.net_name, []).append(indexed)

        zones_by_layer = {}
        acute_cover_items = []
        mask_openings_by_side = {}
        for zone in self._checkpointed(self.backend.iter_zones()):
            teardrop_reader = getattr(self.backend, "is_teardrop_zone", None)
            zone_name_reader = getattr(self.backend, "zone_name", None)
            try:
                is_teardrop = bool(
                    teardrop_reader(zone)
                    if teardrop_reader is not None
                    else (
                        zone_name_reader is not None
                        and zone_name_reader(zone) == "$teardrop_padvia$"
                    )
                )
            except Exception:
                is_teardrop = False
            copper_layer_reader = getattr(
                self.backend,
                "item_copper_layer_ids",
                None,
            )
            try:
                zone_layer_ids = tuple(
                    copper_layer_reader(zone) if copper_layer_reader else ()
                )
            except Exception:
                zone_layer_ids = ()
            for layer_id in zone_layer_ids or (None,):
                indexed = self._index_item(
                    zone,
                    item_kind="zone",
                    layer_id_override=layer_id,
                )
                if is_teardrop:
                    # Teardrops are excluded from ordinary zone/spacing rules,
                    # but their filled polygons are real same-net copper for
                    # both junction coverage and connectivity.
                    acute_cover_items.append(indexed)
                    items_by_net.setdefault(indexed.net_name, []).append(indexed)
                    continue
                mask_side = mask_layer_side(indexed.layer_name)
                if mask_side:
                    mask_openings_by_side.setdefault(mask_side, []).append(indexed)
                else:
                    zones_by_layer.setdefault(indexed.layer_name, []).append(indexed)
                    items_by_net.setdefault(indexed.net_name, []).append(indexed)

        drawings_by_layer = {}
        for drawing in self._checkpointed(self.backend.iter_drawings()):
            indexed = self._index_item(drawing, item_kind="drawing")
            mask_side = mask_layer_side(indexed.layer_name)
            if mask_side:
                mask_openings_by_side.setdefault(mask_side, []).append(indexed)
            else:
                drawings_by_layer.setdefault(indexed.layer_name, []).append(indexed)

        sort_indexed_items(tracks_by_layer)
        sort_indexed_items(pads_by_layer)
        sort_indexed_items(vias_by_layer)
        sort_indexed_items(zones_by_layer)
        sort_indexed_items(drawings_by_layer)
        sort_indexed_items(mask_openings_by_side)
        sort_indexed_items(items_by_net)
        acute_cover_items = tuple(sorted(acute_cover_items, key=index_sort_key))
        connectable_items_by_net = {
            net_name: tuple(
                item
                for item in items
                if self._is_copper_connectable(item)
            )
            for net_name, items in items_by_net.items()
        }
        all_connectable_items = tuple(
            sorted(
                (
                    item
                    for items in connectable_items_by_net.values()
                    for item in items
                ),
                key=index_sort_key,
            )
        )

        outline_pairs = tuple(
            sorted(
                (
                    (segment, bbox_for_segments((segment,)))
                    for segment in self.backend.board_outline_segments()
                ),
                key=lambda pair: pair[1][0] if pair[1] is not None else 0,
            )
        )
        board_outline = tuple(segment for segment, _bbox in outline_pairs)
        board_outline_segment_bboxes = tuple(segment_bbox for _segment, segment_bbox in outline_pairs)
        tracks = tuple(item for items in tracks_by_layer.values() for item in items)
        pads = tuple(item for items in pads_by_layer.values() for item in items)
        layer_ids_by_name = self._layer_ids_by_name(
            tracks_by_layer,
            pads_by_layer,
            zones_by_layer,
            drawings_by_layer,
            mask_openings_by_side,
        )
        copper_pad_layer_names = tuple(
            dict.fromkeys(
                pad.layer_name
                for pad in pads
                if self._pad_has_copper(pad)
            )
        )
        known_copper_layers = tuple(
            dict.fromkeys(
                tuple(tracks_by_layer)
                + copper_pad_layer_names
                + tuple(zones_by_layer)
            )
        )
        copper_pads_by_layer = {}
        for pad in pads:
            if not self._pad_has_copper(pad):
                continue
            for layer in self._pad_copper_layers(pad, known_copper_layers):
                copper_pads_by_layer.setdefault(layer, []).append(self._pad_on_copper_layer(pad, layer, layer_ids_by_name))
        copper_pads_by_layer = {
            layer: tuple(sorted(items, key=index_sort_key))
            for layer, items in copper_pads_by_layer.items()
        }
        copper_layer_names = tuple(
            dict.fromkeys(
                tuple(tracks_by_layer)
                + tuple(copper_pads_by_layer)
                + tuple(zones_by_layer)
            )
        )
        copper_pads = tuple(pad for pad in pads if self._pad_has_copper(pad))
        smd_pads_by_layer = {
            layer: tuple(pad for pad in items if pad.pad_is_smd)
            for layer, items in pads_by_layer.items()
        }
        smd_pads = tuple(pad for pad in pads if pad.pad_is_smd)
        zones = tuple(item for items in zones_by_layer.values() for item in items)
        holes = tuple(
            list(vias)
            + [
                pad
                for pad in pads
                if pad.pad_drill_mm and (pad.pad_drill_mm[0] > 0 or pad.pad_drill_mm[1] > 0)
            ]
        )
        hole_drill_candidates = tuple(
            candidate
            for candidate in (
                self._drill_geometry_candidate(hole)
                for hole in holes
            )
            if candidate is not None
        )
        return BoardIndex(
            tracks_by_layer=tracks_by_layer,
            pads_by_layer=pads_by_layer,
            copper_pads_by_layer=copper_pads_by_layer,
            smd_pads_by_layer=smd_pads_by_layer,
            vias_by_layer=vias_by_layer,
            vias_by_net=vias_by_net,
            pads_by_net=pads_by_net,
            zones_by_layer=zones_by_layer,
            acute_cover_items=acute_cover_items,
            acute_cover_x_starts=tuple(
                index_sort_key(item) for item in acute_cover_items
            ),
            acute_cover_max_width=max_bbox_width_nm(acute_cover_items),
            drawings_by_layer=drawings_by_layer,
            mask_openings_by_side=mask_openings_by_side,
            mask_opening_x_starts_by_side={
                side: tuple(index_sort_key(item) for item in items)
                for side, items in mask_openings_by_side.items()
            },
            mask_opening_max_width_by_side={
                side: max_bbox_width_nm(items)
                for side, items in mask_openings_by_side.items()
            },
            items_by_net=items_by_net,
            item_x_starts_by_net={
                net_name: tuple(index_sort_key(item) for item in items)
                for net_name, items in items_by_net.items()
            },
            item_max_width_by_net={
                net_name: max_bbox_width_nm(items)
                for net_name, items in items_by_net.items()
            },
            connectable_items_by_net=connectable_items_by_net,
            connectable_x_starts_by_net={
                net_name: tuple(index_sort_key(item) for item in items)
                for net_name, items in connectable_items_by_net.items()
            },
            connectable_max_width_by_net={
                net_name: max_bbox_width_nm(items)
                for net_name, items in connectable_items_by_net.items()
            },
            all_connectable_items=all_connectable_items,
            all_connectable_x_starts=tuple(index_sort_key(item) for item in all_connectable_items),
            all_connectable_max_width=max_bbox_width_nm(all_connectable_items),
            board_outline=board_outline,
            board_outline_bbox=bbox_for_segments(board_outline),
            board_outline_segment_bboxes=board_outline_segment_bboxes,
            board_outline_x_starts=tuple(bbox[0] if bbox is not None else 0 for bbox in board_outline_segment_bboxes),
            board_outline_max_width=max_bbox_width_from_bboxes(board_outline_segment_bboxes),
            copper_layer_names=copper_layer_names,
            tracks=tracks,
            pads=pads,
            copper_pads=copper_pads,
            smd_pads=smd_pads,
            zones=zones,
            vias=tuple(vias),
            holes=holes,
            hole_drill_candidates=hole_drill_candidates,
            pad_x_starts_by_layer={
                layer: tuple(index_sort_key(item) for item in items)
                for layer, items in pads_by_layer.items()
            },
            pad_max_width_by_layer={
                layer: max_bbox_width_nm(items)
                for layer, items in pads_by_layer.items()
            },
            copper_pad_x_starts_by_layer={
                layer: tuple(index_sort_key(item) for item in items)
                for layer, items in copper_pads_by_layer.items()
            },
            copper_pad_max_width_by_layer={
                layer: max_bbox_width_nm(items)
                for layer, items in copper_pads_by_layer.items()
            },
            smd_pad_x_starts_by_layer={
                layer: tuple(index_sort_key(item) for item in items)
                for layer, items in smd_pads_by_layer.items()
            },
            smd_pad_max_width_by_layer={
                layer: max_bbox_width_nm(items)
                for layer, items in smd_pads_by_layer.items()
            },
            track_x_starts_by_layer={
                layer: tuple(index_sort_key(item) for item in items)
                for layer, items in tracks_by_layer.items()
            },
            track_max_width_by_layer={
                layer: max_bbox_width_nm(items)
                for layer, items in tracks_by_layer.items()
            },
            zone_x_starts_by_layer={
                layer: tuple(index_sort_key(item) for item in items)
                for layer, items in zones_by_layer.items()
            },
            zone_max_width_by_layer={
                layer: max_bbox_width_nm(items)
                for layer, items in zones_by_layer.items()
            },
            board_thickness_mm=None,
            layer_ids_by_name=layer_ids_by_name,
        )

    def get_pad(self, analysis_result):
        category = "Pad size"
        if analysis_result.get(category) == "":
            return ""
        if not self.include_passed_details:
            result = self._pad_summary(analysis_result)
        else:
            result = self._collect_minimum(
                category,
                self._iter_pad_size_results(analysis_result),
            )
        return self._remote_passing_display(category, result)

    def get_annular_ring(self, analysis_result):
        category = "RingHole"
        if analysis_result.get(category) == "":
            return ""
        if not self.include_passed_details:
            result = self._annular_ring_summary(analysis_result)
        else:
            result = self._collect_minimum(
                category,
                self._iter_annular_ring_results(analysis_result),
            )
        return self._remote_passing_display(category, result)

    def get_line_width(self, analysis_result):
        category = "Smallest Trace Width"
        if analysis_result.get(category) == "":
            return ""
        if not self.include_passed_details:
            return self._line_width_summary(analysis_result)
        return self._collect_minimum(category, self._iter_line_width_results(analysis_result))

    def get_trace_spacing(self, analysis_result):
        category = "Smallest Trace Spacing"
        if analysis_result.get(category) == "":
            return ""
        return self._collect_minimum(category, self._iter_trace_spacing_results(analysis_result))

    def get_smd_spacing(self, analysis_result):
        category = "SMD Spacing"
        if analysis_result.get(category) == "":
            return ""
        return self._collect_minimum(
            category,
            self._iter_smd_spacing_results(analysis_result),
        )

    def get_copper_to_board_edge(self, analysis_result):
        category = "Copper-to-Board Edge"
        if analysis_result.get(category) == "":
            return ""
        if not self.index.board_outline:
            return ""
        return self._collect_minimum(category, self._iter_copper_to_edge_results(analysis_result))

    def get_hole_to_board_edge(self, analysis_result):
        category = "Hole-to-Board Edge"
        if analysis_result.get(category) == "":
            return ""
        if not self.index.board_outline:
            return ""
        return self._collect_minimum(
            category,
            self._iter_hole_to_edge_results(analysis_result),
        )

    def get_drill_to_copper(self, analysis_result):
        category = "Drill to Copper"
        if analysis_result.get(category) == "":
            return ""
        return self._collect_minimum(category, self._iter_drill_to_copper_results(analysis_result))

    def get_hole_size(self, analysis_result):
        category = "Hole Size"
        if analysis_result.get(category) == "":
            return ""
        return self._collect_minimum(category, self._iter_hole_size_results(analysis_result))

    # Compatibility for third-party callers; analysis results use Hole Size.
    def get_hole_diameter(self, analysis_result):
        return self.get_hole_size(analysis_result)

    def get_drill_hole_spacing(self, analysis_result):
        category = "Drill Hole Spacing"
        if analysis_result.get(category) == "":
            return ""
        return self._collect_minimum(category, self._iter_drill_hole_spacing_results(analysis_result))

    def get_special_drill_holes(self, analysis_result):
        category = "Special Drill Holes"
        if analysis_result.get(category) == "":
            return ""
        return self._collect_minimum(category, self._iter_special_drill_results(analysis_result))

    def get_holes_on_smd_pads(self, analysis_result):
        category = "Holes on SMD Pads"
        if analysis_result.get(category) == "":
            return ""
        results = self._iter_holes_on_smd_results(analysis_result)
        if not self._uses_remote_holes_contract():
            return self._collect_minimum(category, results)
        result = self._collect_maximum(category, results)
        if isinstance(result.get("display"), (int, float)):
            result["display"] = "{0:.2f}%".format(result["display"] * 100.0)
        return result

    def get_missing_smask_openings(self, analysis_result):
        category = "Missing SMask Openings"
        if analysis_result.get(category) == "":
            return ""
        return self._summary_only(category, self._iter_missing_smask_results(analysis_result))

    def get_solder_mask_analysis(self, analysis_result):
        category = "Solder Mask Analysis"
        if analysis_result.get(category) == "":
            return ""
        return self._summary_only(
            category, self._iter_solder_mask_analysis_results(analysis_result)
        )

    def get_drill_hole_density(self, analysis_result):
        return self._statistic_result("Drill Hole Density")

    def get_surface_finish_area(self, analysis_result):
        return self._statistic_result("Surface Finish Area")

    def get_test_point_count(self, analysis_result):
        return self._statistic_result("Test Point Count")

    def _statistic_result(self, category):
        if self._statistic_results is None:
            statistics = calculate_board_statistics(
                self.backend,
                pads=(item.item for item in self.index.pads),
                vias=(item.item for item in self.index.vias),
            )
            self._statistic_results = statistic_result_map(
                statistics,
                chinese=self.tr("Drill Hole Density") != "Drill Hole Density",
            )
        return dict(self._statistic_results[category])

    def get_signal_integrity(self, analysis_result):
        category = "Signal Integrity"
        if analysis_result.get(category) == "":
            return ""
        return self._summary_only(
            category,
            self._iter_signal_integrity_results(analysis_result),
        )

    def _iter_signal_integrity_results(self, analysis_result):
        yield from self._iter_trace_missing_results(analysis_result)
        yield from self._iter_acute_angle_results(analysis_result)
        yield from self._iter_dangling_track_results(analysis_result)
        yield from self._iter_unconnected_via_results(analysis_result)

    def _iter_trace_missing_results(self, analysis_result):
        category = "Signal Integrity"
        item = self.tr("Trace Mssing")
        for net_name, connectable in self.index.connectable_items_by_net.items():
            if not net_name:
                continue
            if len(connectable) < 2:
                continue
            components = self._native_copper_components(connectable)
            if components is None:
                components = self._copper_components(
                    connectable,
                    sorted_items=connectable,
                    starts=self.index.connectable_x_starts_by_net.get(net_name, ()),
                )
            if len(components) < 2:
                continue
            largest = min(
                components,
                key=lambda component: (
                    -len(component),
                    stable_component_key(component),
                ),
            )
            for component in sorted(components, key=stable_component_key):
                if component is largest:
                    continue
                routed_items = tuple(
                    candidate for candidate in component if candidate.is_track
                )
                if not routed_items:
                    continue
                representative = min(routed_items, key=stable_indexed_item_key)
                data = self._boolean_result(
                    analysis_result,
                    category,
                    item,
                    representative,
                    force_violation=True,
                    message="Same-net copper is split into disconnected components.",
                )
                data["gap_mm"] = self._component_gap_mm(component, largest)
                yield data

    def _iter_acute_angle_results(self, analysis_result):
        category = "Signal Integrity"
        item = self.tr("Acute Angle Traces")
        for tracks in self.index.tracks_by_layer.values():
            for left, right in self._checkpointed(pairwise_candidates(tracks, 0)):
                if (
                    not left.net_name
                    or not right.net_name
                    or left.net_name != right.net_name
                ):
                    continue
                junction = self._connected_track_junction(left, right)
                if junction is None:
                    continue
                shared, angle = junction
                if (
                    angle <= ACUTE_ANGLE_MINIMUM_DEGREES
                    or angle >= 90.0 - ACUTE_ANGLE_TOLERANCE_DEGREES
                ):
                    continue
                if not self._acute_junction_is_exposed(left, right, shared):
                    continue
                yield self._boolean_result(
                    analysis_result,
                    category,
                    item,
                    left,
                    related=right,
                    message="Connected tracks form an acute angle.",
                )

    def _iter_remote_acute_angle_results(self, analysis_result):
        category = "Signal Integrity"
        item = self.tr("Acute Angle Traces")
        results_by_layer = {}
        for tracks in self.index.tracks_by_layer.values():
            for left, right in self._checkpointed(pairwise_candidates(tracks, 0)):
                if not self._is_outer_copper(left):
                    continue
                if (
                    not left.net_name
                    or not right.net_name
                    or left.net_name != right.net_name
                ):
                    continue
                junction = self._connected_track_junction(left, right)
                if junction is None:
                    continue
                shared, angle = junction
                if (
                    angle <= ACUTE_ANGLE_MINIMUM_DEGREES
                    or angle >= 90.0 - ACUTE_ANGLE_TOLERANCE_DEGREES
                ):
                    continue
                if not self._acute_junction_is_exposed(left, right, shared):
                    continue
                results_by_layer.setdefault(left.layer_name, []).append(
                    self._boolean_result(
                        analysis_result,
                        category,
                        item,
                        left,
                        related=right,
                        message="Copper geometry forms an acute angle.",
                    )
                )
        for drawing in self._copper_text_drawings():
            if not self._is_outer_copper(drawing):
                continue
            layer_results = results_by_layer.setdefault(drawing.layer_name, [])
            polygons = tuple(self.backend.text_stroke_polygons(drawing.item))
            strokes = tuple(self.backend.text_stroke_segments(drawing.item))
            for stroke_index in acute_stroke_indexes(strokes):
                bbox = (
                    filled_polygon_bbox(polygons[stroke_index])
                    if stroke_index < len(polygons)
                    else stroke_bbox(strokes[stroke_index])
                )
                layer_results.append(
                    self._remote_zone_geometry_result(
                        analysis_result,
                        category,
                        item,
                        drawing,
                        bbox,
                        stroke_index,
                        "Copper text strokes form an acute angle.",
                    )
                )
        for layer_results in results_by_layer.values():
            yield from layer_results

    def _iter_floating_copper_results(self, analysis_result):
        category = "Signal Integrity"
        item = self.tr("Floating Copper")
        if self._uses_remote_contract():
            components_by_layer = {}
            for drawing in self._copper_text_drawings():
                layer_components = components_by_layer.setdefault(
                    drawing.layer_name,
                    [],
                )
                polygons = tuple(self.backend.text_stroke_polygons(drawing.item))
                strokes = tuple(self.backend.text_stroke_segments(drawing.item))
                components = (
                    stroke_components(strokes)
                    if len(strokes) == len(polygons)
                    else filled_polygon_components(polygons)
                )
                for component in components:
                    full_component = tuple(
                        (polygon_index, polygons[polygon_index])
                        for polygon_index in component
                    )
                    if any(
                        self._filled_polygon_connected_to_copper(
                            drawing,
                            polygon,
                            filled_polygon_bbox(polygon),
                        )
                        for _polygon_index, polygon in full_component
                    ):
                        continue
                    layer_components.append((drawing, full_component))
            for layer_components in components_by_layer.values():
                for drawing, component in layer_components:
                    for polygon_index, polygon in component:
                        yield self._remote_zone_geometry_result(
                            analysis_result,
                            category,
                            item,
                            drawing,
                            filled_polygon_bbox(polygon),
                            polygon_index,
                            "Non-conductor copper text island is electrically floating.",
                        )
            return
        for zone in self._all_zones():
            self._checkpoint()
            if not zone.net_name or zone.bbox_nm is None:
                continue
            if self._zone_connected_to_copper(zone):
                continue
            yield self._boolean_result(
                analysis_result,
                category,
                item,
                zone,
                message="Copper zone is not connected to same-net copper.",
            )

    def _filled_polygon_connected_to_copper(self, zone, polygon, bbox):
        polygons = (polygon,)
        source = GeometryCandidate(indexed=zone, bbox_nm=bbox)
        if getattr(self.backend, "is_text", lambda _item: False)(zone.item):
            candidates = self._layer_copper_candidates(source)
        else:
            candidates = self._connection_candidates(source, max_gap_nm=0)
        for candidate in candidates:
            if self._same_indexed_item(candidate, zone):
                continue
            if getattr(self.backend, "is_text", lambda _item: False)(candidate.item):
                continue
            if not self._can_connect(zone, candidate):
                continue
            if not bbox_near(bbox, candidate.bbox_nm, self._item_radius_nm(candidate)):
                continue
            if candidate.zone_polygons_nm:
                outer, _holes = polygon
                sample_points = tuple(outer or ())
                if sample_points:
                    sample_points += (
                        (
                            (bbox[0] + bbox[2]) / 2.0,
                            (bbox[1] + bbox[3]) / 2.0,
                        ),
                    )
                if any(
                    self._zone_contains_point(candidate, point)
                    for point in sample_points
                ):
                    return True
            elif self._track_segments(candidate):
                if min(
                    segment_to_filled_polygons_distance(segment, polygons)
                    for segment in self._track_segments(candidate)
                ) <= candidate.width_nm / 2.0:
                    return True
            elif candidate.center_nm is not None:
                radius = self._item_radius_nm(candidate)
                if point_to_filled_polygons_distance(candidate.center_nm, polygons) <= radius:
                    return True
            elif candidate.bbox_nm:
                if bbox_to_filled_polygons_distance(candidate.bbox_nm, polygons) <= 0:
                    return True
        return False

    def _layer_copper_candidates(self, source):
        layer = source.indexed.layer_name
        groups = (
            (
                self.index.tracks_by_layer.get(layer, ()),
                self.index.track_x_starts_by_layer.get(layer, ()),
                self.index.track_max_width_by_layer.get(layer, 0),
            ),
            (
                self.index.copper_pads_by_layer.get(layer, ()),
                self.index.copper_pad_x_starts_by_layer.get(layer, ()),
                self.index.copper_pad_max_width_by_layer.get(layer, 0),
            ),
            (
                self.index.zones_by_layer.get(layer, ()),
                self.index.zone_x_starts_by_layer.get(layer, ()),
                self.index.zone_max_width_by_layer.get(layer, 0),
            ),
        )
        seen = set()
        for items, starts, max_width in groups:
            for candidate in nearby_items(source, items, starts, 0, max_width):
                key = id(candidate.item)
                if key not in seen:
                    seen.add(key)
                    yield candidate
        vias = self._vias_on_copper_layer(layer)
        via_starts = tuple(index_sort_key(via) for via in vias)
        for candidate in nearby_items(
            source,
            vias,
            via_starts,
            0,
            max_bbox_width_nm(vias),
        ):
            key = id(candidate.item)
            if key not in seen:
                seen.add(key)
                yield candidate

    def _vias_on_copper_layer(self, layer):
        if layer not in self._vias_by_copper_layer_cache:
            self._vias_by_copper_layer_cache[layer] = tuple(
                sorted(
                    (
                        via
                        for via in self.index.vias
                        if layer in self._hole_copper_layers(via)
                    ),
                    key=index_sort_key,
                )
            )
        return self._vias_by_copper_layer_cache[layer]

    def _copper_text_drawings(self):
        is_text = getattr(self.backend, "is_text", lambda _item: False)
        for drawings in self.index.drawings_by_layer.values():
            for drawing in drawings:
                if self._is_outer_copper(drawing) and is_text(drawing.item):
                    yield drawing

    def _remote_zone_geometry_result(
        self,
        analysis_result,
        category,
        item,
        zone,
        bbox,
        polygon_index,
        message,
    ):
        data = self._boolean_result(
            analysis_result,
            category,
            item,
            zone,
            message=message,
        )
        data["value"] = "0.0"
        data["bbox_nm"] = bbox
        data["polygon_index"] = polygon_index
        return data

    def _iter_dangling_track_results(self, analysis_result):
        category = "Signal Integrity"
        item = self.tr("Dangling Tracks")
        for track in self._all_tracks():
            self._checkpoint()
            endpoints = self._track_endpoints(track)
            if not endpoints:
                continue
            if (
                not self._point_connected_to_copper(
                    track, endpoints[0], track.width_nm / 2.0
                )
                or not self._point_connected_to_copper(
                    track, endpoints[1], track.width_nm / 2.0
                )
            ):
                yield self._boolean_result(
                    analysis_result,
                    category,
                    item,
                    track,
                    message="Track endpoint is not connected.",
                )

    def _iter_unconnected_via_results(self, analysis_result):
        category = "Signal Integrity"
        item = self.tr("Unconnected Vias")
        connected_layers_reader = getattr(
            self.backend,
            "connected_copper_layer_ids",
            None,
        )
        for via in self.index.vias:
            if via.center_nm is None:
                continue
            try:
                native_connected_layers = (
                    connected_layers_reader(via.item)
                    if connected_layers_reader is not None
                    else None
                )
            except Exception:
                native_connected_layers = None
            if native_connected_layers is not None:
                connected = bool(native_connected_layers)
            else:
                connected = self._point_connected_to_copper(
                    via,
                    via.center_nm,
                    via.width_nm / 2.0,
                )
            if connected:
                continue
            yield self._boolean_result(
                analysis_result,
                category,
                item,
                via,
                message="Via is not connected to copper.",
            )

    def _iter_pad_size_results(self, analysis_result):
        category = "Pad size"
        for pad in self._all_pads():
            self._checkpoint()
            if pad.pad_attr == 3:
                continue
            if self._uses_remote_contract() and self.backend.is_custom_pad(pad.item):
                continue
            size_x, size_y = pad.pad_size_mm
            value = round(pad_shorter_side_mm(size_x, size_y), 6)
            item = self.tr(self._pad_size_item(size_x, size_y))
            if not self._within_rule_limit(
                analysis_result, category, item, value
            ):
                continue
            yield self._result(
                analysis_result,
                category,
                item,
                value,
                pad,
            )

    def _pad_summary(self, analysis_result):
        category = "Pad size"
        minimum = -1
        have_red = False
        have_yellow = False
        result_list = []
        checked_count = 0
        violation_count = 0
        for pad in self._all_pads():
            self._checkpoint()
            if pad.pad_attr == 3:
                continue
            if self._uses_remote_contract() and self.backend.is_custom_pad(pad.item):
                continue
            checked_count += 1
            size_x, size_y = pad.pad_size_mm
            value = round(pad_shorter_side_mm(size_x, size_y), 6)
            if value < minimum or minimum == -1:
                minimum = value
            item = self.tr(self._pad_size_item(size_x, size_y))
            color = self.color_rule.get_rule(analysis_result, category, self._rule_item_name(category, item), value)
            if color in ("red", "gold"):
                violation_count += 1
            have_red, have_yellow = update_color_flags(color, have_red, have_yellow)
            if color != "black":
                data = self._result(analysis_result, category, item, value, pad)
                self._append_issue(category, data)
                result_list.append({"result": [data]})
        return self._summary_result(
            minimum,
            result_list,
            have_red,
            have_yellow,
            checked_count,
            violation_count,
        )

    def _pad_size_item(self, size_x, size_y):
        return pad_size_item(size_x, size_y)

    def _iter_annular_ring_results(self, analysis_result):
        category = "RingHole"
        for via in self.index.vias:
            width = round(float(via.width_nm) / NM_PER_MM, 6)
            drill = round(float(via.via_drill_mm), 6)
            value = round((width - drill) / 2.0, 6)
            item = self.tr("Via Annular Ring")
            if self._within_rule_limit(analysis_result, category, item, value):
                yield self._result(
                    analysis_result,
                    category,
                    item,
                    value,
                    via,
                    extra={"pad_diameter": width, "hole_diameter": drill},
                )
        for pad in self._all_pads():
            self._checkpoint()
            if not pad.is_round_pth:
                continue
            size_x, _ = pad.pad_size_mm
            drill_x, _ = pad.pad_drill_mm
            value = round((size_x - drill_x) / 2.0, 6)
            item = self.tr("PTH Annular Ring")
            if self._within_rule_limit(analysis_result, category, item, value):
                yield self._result(
                    analysis_result,
                    category,
                    item,
                    value,
                    pad,
                    extra={
                        "pad_diameter": round(size_x, 6),
                        "hole_diameter": round(drill_x, 6),
                    },
                )

    def _annular_ring_summary(self, analysis_result):
        category = "RingHole"
        minimum = -1
        have_red = False
        have_yellow = False
        result_list = []
        checked_count = 0
        violation_count = 0
        for via in self.index.vias:
            checked_count += 1
            width = round(float(via.width_nm) / NM_PER_MM, 6)
            drill = round(float(via.via_drill_mm), 6)
            value = round((width - drill) / 2.0, 6)
            if value < minimum or minimum == -1:
                minimum = value
            item = self.tr("Via Annular Ring")
            color = self.color_rule.get_rule(analysis_result, category, self._rule_item_name(category, item), value)
            if color in ("red", "gold"):
                violation_count += 1
            have_red, have_yellow = update_color_flags(color, have_red, have_yellow)
            if color != "black" and self._within_rule_limit(analysis_result, category, item, value):
                data = self._result(
                    analysis_result,
                    category,
                    item,
                    value,
                    via,
                    extra={"pad_diameter": width, "hole_diameter": drill},
                )
                self._append_issue(category, data)
                result_list.append({"result": [data]})
        for pad in self._all_pads():
            self._checkpoint()
            if not pad.is_round_pth:
                continue
            checked_count += 1
            size_x, _ = pad.pad_size_mm
            drill_x, _ = pad.pad_drill_mm
            value = round((size_x - drill_x) / 2.0, 6)
            if value < minimum or minimum == -1:
                minimum = value
            item = self.tr("PTH Annular Ring")
            color = self.color_rule.get_rule(analysis_result, category, self._rule_item_name(category, item), value)
            if color in ("red", "gold"):
                violation_count += 1
            have_red, have_yellow = update_color_flags(color, have_red, have_yellow)
            if color != "black" and self._within_rule_limit(analysis_result, category, item, value):
                data = self._result(
                    analysis_result,
                    category,
                    item,
                    value,
                    pad,
                    extra={"pad_diameter": round(size_x, 6), "hole_diameter": round(drill_x, 6)},
                )
                self._append_issue(category, data)
                result_list.append({"result": [data]})
        if (
            self._uses_remote_contract()
            and minimum > 0.254
            and not have_red
            and not have_yellow
        ):
            minimum = -1
        return self._summary_result(
            minimum,
            result_list,
            have_red,
            have_yellow,
            checked_count,
            violation_count,
        )

    def _iter_line_width_results(self, analysis_result):
        category = "Smallest Trace Width"
        for track in self._all_tracks():
            self._checkpoint()
            value = round(float(track.width_nm) / NM_PER_MM, 6)
            yield self._result(
                analysis_result,
                category,
                self.tr("Smallest Trace Width"),
                value,
                track,
                extra={"info": track.item_id},
            )

    def _line_width_summary(self, analysis_result):
        category = "Smallest Trace Width"
        item = self.tr("Smallest Trace Width")
        rule_item = self._rule_item_name(category, item)
        minimum = -1
        have_red = False
        have_yellow = False
        result_list = []
        checked_count = 0
        violation_count = 0
        for track in self._all_tracks():
            self._checkpoint()
            checked_count += 1
            value = round(float(track.width_nm) / NM_PER_MM, 6)
            if value < minimum or minimum == -1:
                minimum = value
            color = self.color_rule.get_rule(analysis_result, category, rule_item, value)
            if color in ("red", "gold"):
                violation_count += 1
            have_red, have_yellow = update_color_flags(color, have_red, have_yellow)
            if color != "black":
                data = self._result(
                    analysis_result,
                    category,
                    item,
                    value,
                    track,
                    extra={"info": track.item_id},
                )
                self._append_issue(category, data)
                result_list.append({"result": [data]})
        if (
            self._uses_remote_contract()
            and minimum > 0.254
            and not have_red
            and not have_yellow
        ):
            minimum = -1
        return self._summary_result(
            minimum,
            result_list,
            have_red,
            have_yellow,
            checked_count,
            violation_count,
        )

    def _iter_trace_spacing_results(self, analysis_result):
        category = "Smallest Trace Spacing"
        max_gap = max(
            self._candidate_gap_nm(category, "Trace Spacing"),
            self._candidate_gap_nm(category, "Trace-to-Pad Spacing"),
            self._candidate_gap_nm(category, "Pad-to-Pad Spacing"),
            self._candidate_gap_nm(category, "BGA Pads"),
        )
        if self._uses_remote_contract():
            max_gap = max(max_gap, 0.254 * NM_PER_MM)
        track_item = self.tr("Trace Spacing")
        track_pad_item = self.tr("Trace-to-Pad Spacing")
        yield from self._iter_trace_to_pad_spacing_results(
            analysis_result,
            category,
            track_pad_item,
            max_gap,
        )
        yield from self._iter_pad_to_pad_trace_spacing_results(
            analysis_result,
            category,
            max_gap,
        )
        for tracks in self.index.tracks_by_layer.values():
            for left, right in self._checkpointed(
                y_near_pairwise_candidates(tracks, max_gap)
            ):
                if self._same_named_net(left, right):
                    continue
                distance = self._track_to_track_gap_mm(left, right)
                if distance is None:
                    continue
                yield self._result(
                    analysis_result,
                    category,
                    track_item,
                    distance,
                    left,
                    related=right,
                )

    def _iter_pad_to_pad_trace_spacing_results(
        self, analysis_result, category, max_gap
    ):
        reported_pairs = set()
        for pads in self.index.copper_pads_by_layer.values():
            for left, right in self._checkpointed(pairwise_candidates(pads, max_gap)):
                pair_key = self._indexed_pair_key(left, right)
                if pair_key in reported_pairs:
                    continue
                spacing_item = self._pad_spacing_item(left, right)
                if spacing_item == "SMD Pad Spacing":
                    continue
                if self._same_named_net(left, right):
                    continue
                distance = self._pad_to_pad_gap_mm(left, right)
                if distance is None:
                    continue
                if self._is_local_net_tie_contact(left, right, distance):
                    continue
                item = self.tr(spacing_item)
                yield self._result(
                    analysis_result,
                    category,
                    item,
                    distance,
                    left,
                    related=right,
                )
                reported_pairs.add(pair_key)

    def _iter_smd_spacing_results(self, analysis_result):
        category = "SMD Spacing"
        item = self.tr("SMD Pad Spacing")
        max_gap = self._candidate_gap_nm(category, "SMD Pad Spacing")
        reported_pairs = set()
        for copper_pads in self.index.copper_pads_by_layer.values():
            pads = tuple(
                pad
                for pad in copper_pads
                if pad.pad_is_smd and not pad.pad_is_bga
            )
            for left, right in self._checkpointed(
                pairwise_candidates(pads, max_gap)
            ):
                pair_key = self._indexed_pair_key(left, right)
                if pair_key in reported_pairs:
                    continue
                if self._same_named_net(left, right):
                    continue
                if self._is_smd_net_tie_exempt(left, right):
                    continue
                distance = self._pad_to_pad_gap_mm(left, right)
                if distance is None:
                    continue
                yield self._result(
                    analysis_result,
                    category,
                    item,
                    distance,
                    left,
                    related=right,
                )
                reported_pairs.add(pair_key)

    def _iter_trace_to_pad_spacing_results(self, analysis_result, category, item, max_gap):
        for layer, tracks in self.index.tracks_by_layer.items():
            pads = self.index.copper_pads_by_layer.get(layer, ())
            for track in self._checkpointed(tracks):
                for pad in nearby_items(
                    track,
                    pads,
                    self.index.copper_pad_x_starts_by_layer.get(layer, ()),
                    max_gap,
                    self.index.copper_pad_max_width_by_layer.get(layer, 0),
                ):
                    if not within_bbox_gap(track, pad, max_gap):
                        continue
                    if self._same_named_net(track, pad):
                        continue
                    distance = self._track_to_pad_gap_mm(track, pad)
                    if distance is None:
                        continue
                    if self._is_local_net_tie_contact(track, pad, distance):
                        continue
                    yield self._result(
                        analysis_result,
                        category,
                        item,
                        distance,
                        track,
                        related=pad,
                    )

    def _iter_copper_to_edge_results(self, analysis_result):
        category = "Copper-to-Board Edge"
        trace_gap = self._candidate_gap_nm(category, "Trace-to-Board Edge")
        copper_gap = self._candidate_gap_nm(category, "Copper-to-Board Edge")
        max_gap = max(trace_gap, copper_gap)
        for track in self._all_tracks():
            self._checkpoint()
            outline_segments = self._near_outline_segments(track.bbox_nm, trace_gap)
            if not outline_segments:
                continue
            distance = self._track_to_outline_gap_mm(track, outline_segments)
            if distance is None:
                continue
            item = self.tr("Trace-to-Board Edge")
            if self._is_reportable(analysis_result, category, item, distance):
                yield self._result(analysis_result, category, item, distance, track)

        for zone in self._all_zones():
            self._checkpoint()
            outline_segments = self._near_outline_segments(zone.bbox_nm, max_gap)
            if not outline_segments:
                continue
            distance = self._bbox_to_outline_gap_mm(
                zone,
                outline_segments,
                max_gap,
            )
            if distance is None:
                continue
            item = self.tr("Copper-to-Board Edge")
            if self._is_reportable(analysis_result, category, item, distance):
                yield self._result(analysis_result, category, item, distance, zone)

        for via in self.index.vias:
            outline_segments = self._near_outline_segments(via.bbox_nm, copper_gap)
            if not outline_segments:
                continue
            distance = self._via_to_outline_gap_mm(via, outline_segments)
            if distance is None:
                continue
            item = self.tr("Copper-to-Board Edge")
            if self._is_reportable(analysis_result, category, item, distance):
                yield self._result(analysis_result, category, item, distance, via)

        smd_pad_gap = self._candidate_gap_nm(category, "SMD-to-Board Edge")
        pad_gap = max(smd_pad_gap, copper_gap)
        for pad in self._copper_pads():
            self._checkpoint()
            outline_segments = self._near_outline_segments(pad.bbox_nm, pad_gap)
            if not outline_segments:
                continue
            distance = self._pad_to_outline_gap_mm(
                pad,
                outline_segments,
                pad_gap,
            )
            if distance is None:
                continue
            item = self.tr("SMD-to-Board Edge" if pad.pad_is_smd else "Copper-to-Board Edge")
            if self._is_reportable(analysis_result, category, item, distance):
                yield self._result(analysis_result, category, item, distance, pad)

    def _iter_hole_to_edge_results(self, analysis_result):
        category = "Hole-to-Board Edge"
        max_gap = max(
            self._candidate_gap_nm(category, item)
            for item in (
                "PTH-to-Board Edge",
                "Via-to-Board Edge",
                "Screw Hole-to-Board Edge",
                "NPTH-to-Board Edge",
            )
        )
        for hole in self._hole_items():
            self._checkpoint()
            candidate = self._drill_geometry_candidate(hole)
            if candidate is None:
                continue
            outline_segments = self._near_outline_segments(
                candidate.bbox_nm,
                max_gap,
            )
            if not outline_segments:
                continue
            distance = self._hole_to_outline_gap_mm(
                hole,
                outline_segments,
                max_gap,
            )
            if distance is None:
                continue
            item = self.tr(self._hole_to_board_edge_item(hole))
            if self._is_reportable(analysis_result, category, item, distance):
                yield self._result(
                    analysis_result,
                    category,
                    item,
                    distance,
                    hole,
                )

    def _iter_drill_to_copper_results(self, analysis_result):
        category = "Drill to Copper"
        max_gap = max(
            self._candidate_gap_nm(category, "PTH-to-Trace [Outer]"),
            self._candidate_gap_nm(category, "PTH-to-Trace [Inner]"),
            self._candidate_gap_nm(category, "Via-to-Trace [Outer]"),
            self._candidate_gap_nm(category, "Via-to-Trace [Inner]"),
            self._candidate_gap_nm(category, "NPTH-to-Copper"),
        )
        if self._uses_remote_contract():
            max_gap = max(max_gap, 0.5 * NM_PER_MM)
        for hole in self._hole_items():
            self._checkpoint()
            center = hole.center_nm
            drill = self._hole_drill_mm(hole)
            if center is None or drill <= 0:
                continue
            hole_candidate = self._drill_geometry_candidate(hole)
            if hole_candidate is None:
                continue
            radius_nm = hole.hole_radius_nm
            reported_pairs = set()
            is_npth = not hole.is_via and hole.pad_attr == 3
            nearest_npth = None
            for layer in self._hole_copper_layers(hole):
                for copper in self._drill_to_copper_candidates(hole, hole_candidate, layer, max_gap):
                    pair_key = self._indexed_pair_key(hole, copper)
                    if pair_key in reported_pairs:
                        continue
                    distance = self._hole_to_copper_gap_mm(hole, hole_candidate, center, radius_nm, copper)
                    if distance is None:
                        continue
                    item = self.tr(self._drill_to_trace_item(hole, copper.layer_name))
                    if self._should_report_measurement(
                        analysis_result,
                        category,
                        item,
                        distance,
                        remote_limit=0.5,
                    ):
                        reported_pairs.add(pair_key)
                        if is_npth:
                            if nearest_npth is None or distance < nearest_npth[0]:
                                nearest_npth = (distance, item, copper)
                        else:
                            yield self._result(
                                analysis_result,
                                category,
                                item,
                                distance,
                                hole,
                                related=copper,
                            )
            if nearest_npth is not None:
                distance, item, copper = nearest_npth
                yield self._result(
                    analysis_result,
                    category,
                    item,
                    distance,
                    hole,
                    related=copper,
                    extra={"layer": ["Drl"]},
                )

    def _drill_to_copper_candidates(self, hole, hole_candidate, layer, max_gap):
        sources = [
            (
                self.index.tracks_by_layer.get(layer, ()),
                self.index.track_x_starts_by_layer.get(layer, ()),
                self.index.track_max_width_by_layer.get(layer, 0),
            )
        ]
        # PTH-to-Trace and Via-to-Trace are intentionally trace-only rules.
        # NPTH-to-Copper covers every copper object, including pads and pours.
        if not hole.is_via and hole.pad_attr == 3:
            sources.extend(
                (
                    (
                        self.index.copper_pads_by_layer.get(layer, ()),
                        self.index.copper_pad_x_starts_by_layer.get(layer, ()),
                        self.index.copper_pad_max_width_by_layer.get(layer, 0),
                    ),
                    (
                        self.index.zones_by_layer.get(layer, ()),
                        self.index.zone_x_starts_by_layer.get(layer, ()),
                        self.index.zone_max_width_by_layer.get(layer, 0),
                    ),
                )
            )
        for items, starts, max_width in sources:
            for copper in nearby_items(hole_candidate, items, starts, max_gap, max_width):
                if self._same_indexed_item(hole, copper):
                    continue
                if hole.net_name and hole.net_name == copper.net_name:
                    continue
                if not within_bbox_gap(hole_candidate, copper, max_gap):
                    continue
                yield copper

    def _iter_hole_size_results(self, analysis_result):
        category = "Hole Size"
        reported_aspect_drills = set()
        for hole in self._hole_items():
            self._checkpoint()
            drill = self._hole_drill_mm(hole)
            if drill <= 0:
                continue
            item = self.tr(self._hole_diameter_item(hole))
            if (
                item
                and (
                    self._is_reportable(analysis_result, category, item, drill)
                    or self._uses_remote_contract()
                )
            ):
                yield self._result(analysis_result, category, item, drill, hole)

            max_item = self.tr("Largest PTH Size")
            if (
                not hole.is_via
                and hole.pad_attr != 3
                and self._is_reportable(analysis_result, category, max_item, drill)
            ):
                yield self._result(analysis_result, category, max_item, drill, hole)
            blind_max_item = self.tr("Largest Blind/Buried Via")
            if (
                hole.via_is_blind_buried
                and self._is_reportable(analysis_result, category, blind_max_item, drill)
            ):
                yield self._result(analysis_result, category, blind_max_item, drill, hole)
            aspect = self._hole_aspect_ratio(hole, drill)
            aspect_item = self.tr("Aspect Ratio")
            aspect_is_reportable = aspect is not None and (
                self._is_reportable(
                    analysis_result, category, aspect_item, aspect
                )
                or self._within_rule_limit(
                    analysis_result, category, aspect_item, aspect
                )
            )
            aspect_drill_key = round(drill, 6)
            if aspect_is_reportable and aspect_drill_key not in reported_aspect_drills:
                reported_aspect_drills.add(aspect_drill_key)
                yield self._result(
                    analysis_result,
                    category,
                    aspect_item,
                    aspect,
                    hole,
                    extra={
                        "board_thickness_mm": self._board_thickness_mm(),
                        "diameter": drill,
                    },
                )
            yield from self._iter_slot_hole_results(analysis_result, category, hole)

    def _iter_drill_hole_spacing_results(self, analysis_result):
        category = "Drill Hole Spacing"
        holes = tuple(self._drill_spacing_candidates())
        max_gap = self._candidate_gap_for_items(
            category,
            (
                "Same Net Via Spacing",
                "Different Net Via Spacing",
                "Different Net PTH Spacing",
                "Blind/Buried Via Spacing",
            ),
        )
        if self._uses_remote_holes_contract():
            # The remote report exposes the closest passing drill pair as well
            # (the observed reporting window reaches 0.7 mm).
            max_gap = max(max_gap, 0.7 * NM_PER_MM)
        for left_candidate, right_candidate in self._checkpointed(
            pairwise_candidates(holes, max_gap)
        ):
            left = left_candidate.indexed
            right = right_candidate.indexed
            distance = self._drill_hole_spacing_mm(
                left,
                right,
                left_candidate,
                right_candidate,
            )
            same_net = bool(left.net_name and left.net_name == right.net_name)
            if left.is_via and right.is_via and left.via_is_blind_buried and right.via_is_blind_buried:
                item = self.tr("Blind/Buried Via Spacing")
            elif left.is_via and right.is_via:
                item = self.tr(
                    "Same Net Via Spacing" if same_net else "Different Net Via Spacing"
                )
            elif same_net:
                # There is no same-net PTH rule.  Never apply the
                # different-net PTH threshold to a same-net pair.
                continue
            else:
                item = self.tr("Different Net PTH Spacing")
            if (
                self._is_reportable(analysis_result, category, item, distance)
                or (self._uses_remote_holes_contract() and distance <= 0.7)
            ):
                yield self._result(
                    analysis_result,
                    category,
                    item,
                    distance,
                    left,
                    related=right,
                )

    def _drill_hole_spacing_mm(
        self,
        left,
        right,
        left_candidate,
        right_candidate,
    ):
        left_segment, left_radius = self._slot_drill_segment_nm(left)
        right_segment, right_radius = self._slot_drill_segment_nm(right)
        if left_segment is not None and right_segment is not None:
            distance = (
                segment_distance(left_segment, right_segment)
                - left_radius
                - right_radius
            )
        elif left_segment is not None and right.center_nm is not None:
            distance = (
                point_segment_distance(right.center_nm, left_segment)
                - left_radius
                - right.hole_radius_nm
            )
        elif right_segment is not None and left.center_nm is not None:
            distance = (
                point_segment_distance(left.center_nm, right_segment)
                - left.hole_radius_nm
                - right_radius
            )
        elif left.center_nm is not None and right.center_nm is not None:
            distance = (
                point_distance(left.center_nm, right.center_nm)
                - left.hole_radius_nm
                - right.hole_radius_nm
            )
        else:
            distance = bbox_gap(
                left_candidate.bbox_nm,
                right_candidate.bbox_nm,
            )
        return round(max(0.0, distance) / NM_PER_MM, 6)

    def _drill_spacing_candidates(self):
        return self.index.hole_drill_candidates

    def _drill_geometry_candidate(self, hole):
        bbox = self._hole_bbox_nm(hole)
        if bbox is None:
            return None
        return GeometryCandidate(
            indexed=hole,
            bbox_nm=bbox,
        )

    def _iter_special_drill_results(self, analysis_result):
        category = "Special Drill Holes"
        for pad in self._hole_items():
            self._checkpoint()
            if pad.is_via:
                continue
            if self._is_castellated_hole(pad):
                yield self._boolean_result(
                    analysis_result,
                    category,
                    self.tr("Castellated Holes"),
                    pad,
                    message="Drill hole intersects the board edge.",
                )
            if self._is_explicit_square_or_rectangular_drill(pad):
                yield self._boolean_result(
                    analysis_result,
                    category,
                    self.tr("Square/Rectangular Drills"),
                    pad,
                    message=(
                        "Explicit sharp-corner square or rectangular hole "
                        "shape detected."
                    ),
                )

    @staticmethod
    def _is_explicit_square_or_rectangular_drill(hole):
        """Require explicit sharp-corner shape evidence for this rule.

        KiCad's standard non-circular pad drill is an oblong/capsule: its two
        ends are semicircles.  A non-round drill enum or unequal drill axes
        therefore proves only that the hole is a slot, not that it has the
        unmachinable right-angle corners checked by this rule.

        Current KiCad pad drill enums are circular or oblong.  Keep support
        for a backend that can expose an explicit named rectangular/square
        drill shape, but never infer that shape from dimensions alone.
        """
        shape = hole.pad_drill_shape
        shape_name = getattr(shape, "name", "")
        shape_text = "{0} {1}".format(shape_name, shape).upper().replace("_", "")
        if "ROUNDRECT" in shape_text or "ROUNDEDRECT" in shape_text:
            return False
        return "RECTANG" in shape_text or "SQUARE" in shape_text

    def _iter_holes_on_smd_results(self, analysis_result):
        category = "Holes on SMD Pads"
        for via in self.index.vias:
            via_center = via.center_nm
            via_radius = via.hole_radius_nm
            if via_center is None or via_radius <= 0:
                continue
            via_candidate = self._drill_geometry_candidate(via)
            if via_candidate is None:
                continue
            reported_pads = set()
            for layer in self._hole_copper_layers(via):
                pads = self.index.smd_pads_by_layer.get(layer, ())
                starts = self.index.smd_pad_x_starts_by_layer.get(layer, ())
                for pad in nearby_items(
                    via_candidate,
                    pads,
                    starts,
                    0,
                    self.index.smd_pad_max_width_by_layer.get(layer, 0),
                ):
                    pad_key = pad.item_id or id(pad.item)
                    if pad_key in reported_pads:
                        continue
                    if not within_bbox_gap(via_candidate, pad, 0):
                        continue
                    if not self._hole_axis_on_pad(via, via_center, pad):
                        continue
                    overlap_mm = self._hole_pad_overlap_mm(
                        via,
                        via_candidate,
                        via_center,
                        via_radius,
                        pad,
                    )
                    overlap = (
                        self._hole_pad_overlap_ratio(
                            overlap_mm,
                            via_radius,
                            center=via_center,
                            pad=pad,
                        )
                        if self._uses_remote_holes_contract()
                        else overlap_mm
                    )
                    if overlap <= 0:
                        continue
                    item = self.tr("Via on BGA Pad" if pad.pad_is_bga else "Via on SMD Pad")
                    if self._is_reportable(analysis_result, category, item, overlap):
                        reported_pads.add(pad_key)
                        yield self._result(
                            analysis_result,
                            category,
                            item,
                            overlap,
                            via,
                            related=pad,
                            extra={
                                "overlap_mm": overlap_mm,
                                # A through via's primary layer is F.Cu even
                                # when the SMD pad hit is on the back.  Location
                                # and layer display must follow the target pad.
                                "layer": [str(pad.layer_name)],
                            },
                        )
        for hole in self._hole_items():
            self._checkpoint()
            if hole.is_via or hole.hole_radius_nm <= 0 or hole.pad_is_smd:
                continue
            is_npth = self.backend.is_npth_pad(hole.item)
            is_pth = self.backend.is_pth_pad(hole.item)
            if not is_npth and not is_pth:
                continue
            center = hole.center_nm
            radius = hole.hole_radius_nm
            if center is None or radius <= 0:
                continue
            hole_candidate = self._drill_geometry_candidate(hole)
            if hole_candidate is None:
                continue
            reported_pads = set()
            for layer in self._hole_copper_layers(hole):
                pads = self.index.smd_pads_by_layer.get(layer, ())
                starts = self.index.smd_pad_x_starts_by_layer.get(layer, ())
                for pad in nearby_items(
                    hole_candidate,
                    pads,
                    starts,
                    0,
                    self.index.smd_pad_max_width_by_layer.get(layer, 0),
                ):
                    pad_key = pad.item_id or id(pad.item)
                    if pad_key in reported_pads or self._same_indexed_item(pad, hole):
                        continue
                    overlap_mm = self._hole_pad_overlap_mm(hole, hole_candidate, center, radius, pad)
                    overlap = (
                        self._hole_pad_overlap_ratio(
                            overlap_mm,
                            radius,
                            center=center,
                            pad=pad,
                        )
                        if self._uses_remote_holes_contract()
                        else overlap_mm
                    )
                    if overlap <= 0:
                        continue
                    item = self.tr("NPTH on SMD Pad" if is_npth else "PTH on SMD Pad")
                    if self._is_reportable(analysis_result, category, item, overlap):
                        reported_pads.add(pad_key)
                        yield self._result(
                            analysis_result,
                            category,
                            item,
                            overlap,
                            hole,
                            related=pad,
                            extra={"overlap_mm": overlap_mm},
                        )

    def _iter_missing_smask_results(self, analysis_result):
        category = "Missing SMask Openings"
        item = self.tr("Missing SMask Opening")
        for pad in self._smd_pads():
            self._checkpoint()
            if pad.item_id in self._net_tie_footprint_pad_ids:
                continue
            for copper_layer in self._pad_copper_layers(
                pad, self._copper_layer_names()
            ):
                side = copper_layer_side(copper_layer)
                if not side or side in pad.pad_solder_mask_sides:
                    continue
                indexed = (
                    pad
                    if pad.layer_name == copper_layer
                    else replace(pad, layer_name=copper_layer)
                )
                yield self._boolean_result(
                    analysis_result,
                    category,
                    item,
                    indexed,
                    message="SMD pad has no solder mask opening on {0}.".format(
                        copper_layer
                    ),
                )

    def _iter_solder_mask_analysis_results(self, analysis_result):
        category = "Solder Mask Analysis"
        bridge_item = self.tr("Solder Mask Bridge")
        trace_item = self.tr("Solder Mask Covers Trace")
        multiple_item = self.tr("Solder Mask Covers Multiple Nets")
        for side in ("F", "B"):
            copper_layer = side + ".Cu"
            mask_layer = side + ".Mask"
            pad_openings = [
                self._solder_mask_opening_indexed(pad, mask_layer)
                for pad in self.index.copper_pads_by_layer.get(copper_layer, ())
                if side in pad.pad_solder_mask_sides and pad.bbox_nm is not None
            ]
            components = list(
                self._connected_solder_mask_pad_components(
                    pad_openings, mask_layer
                )
            )
            if not components:
                continue
            component_geometries = sorted(
                (
                    (bbox_for_indexed_items(component), component)
                    for component in components
                ),
                key=lambda entry: entry[0][0],
            )

            bridge_limit = self._candidate_gap_nm(category, "Solder Mask Bridge")
            for index, (left_bbox, left) in enumerate(component_geometries):
                for right_bbox, right in component_geometries[index + 1:]:
                    if right_bbox[0] > left_bbox[2] + bridge_limit:
                        break
                    if bbox_gap(left_bbox, right_bbox) > bridge_limit:
                        continue
                    gap_nm, left_opening, right_opening = self._solder_mask_component_gap_nm(
                        left, right, mask_layer, bridge_limit
                    )
                    if gap_nm <= 0 or gap_nm > bridge_limit:
                        continue
                    value = gap_nm / NM_PER_MM
                    if self._is_reportable(analysis_result, category, bridge_item, value):
                        yield self._result(
                            analysis_result,
                            category,
                            bridge_item,
                            value,
                            left_opening,
                            related=right_opening,
                            message="Solder-mask bridge is below the configured width.",
                        )

            trace_limit = self._candidate_gap_nm(category, "Solder Mask Covers Trace")
            tracks = self.index.tracks_by_layer.get(copper_layer, ())
            track_starts = self.index.track_x_starts_by_layer.get(copper_layer, ())
            track_max_width = self.index.track_max_width_by_layer.get(copper_layer, 0)
            for component_bbox, component in component_geometries:
                intended_nets = {
                    opening.net_name
                    for opening in component
                    if opening.is_pad and opening.net_name
                }
                pads_by_net = {}
                for opening in component:
                    if opening.net_name:
                        pads_by_net.setdefault(opening.net_name, opening)
                if len(pads_by_net) > 1:
                    first, second = list(pads_by_net.values())[:2]
                    primary = replace(first, layer_name=mask_layer)
                    yield self._boolean_result(
                        analysis_result,
                        category,
                        multiple_item,
                        primary,
                        related=second,
                        message="One solder-mask opening exposes multiple copper nets.",
                    )

                if len(intended_nets) != 1:
                    continue
                component_candidate = GeometryCandidate(
                    indexed=component[0], bbox_nm=component_bbox
                )
                for track in nearby_items(
                    component_candidate,
                    tracks,
                    track_starts,
                    trace_limit,
                    track_max_width,
                ):
                    if not track.net_name or track.net_name in intended_nets:
                        continue
                    if not any(
                        bbox_near(opening.bbox_nm, track.bbox_nm, trace_limit)
                        for opening in component
                    ):
                        continue
                    gap_nm, closest_opening = min(
                        (
                            (
                                self._solder_mask_opening_to_item_gap_nm(
                                    opening, track, mask_layer, trace_limit
                                ),
                                opening,
                            )
                            for opening in component
                        ),
                        key=lambda result: result[0],
                    )
                    if gap_nm > trace_limit:
                        continue
                    value = gap_nm / NM_PER_MM
                    if self._is_reportable(analysis_result, category, trace_item, value):
                        primary = replace(track, layer_name=mask_layer)
                        yield self._result(
                            analysis_result,
                            category,
                            trace_item,
                            value,
                            primary,
                            related=closest_opening,
                            extra={"opening_nets": tuple(sorted(intended_nets))},
                            message="Solder-mask opening is too close to another-net trace.",
                        )

            # A deliberately drawn mask opening can expose several pads, but
            # it is not itself a pad opening and must not participate in the
            # bridge/trace-clearance rules.  Keep the separate multi-net safety
            # check using exact KiCad geometry where available.
            for opening in self.index.mask_openings_by_side.get(side, ()):
                exposed_by_net = {}
                pads = self.index.copper_pads_by_layer.get(copper_layer, ())
                pad_starts = self.index.copper_pad_x_starts_by_layer.get(
                    copper_layer, ()
                )
                pad_max_width = self.index.copper_pad_max_width_by_layer.get(
                    copper_layer, 0
                )
                for pad in nearby_items(
                    opening, pads, pad_starts, 0, pad_max_width
                ):
                    if not pad.net_name or not bbox_near(
                        opening.bbox_nm, pad.bbox_nm, 0
                    ):
                        continue
                    if not self._mask_drawing_exposes_pad(opening, pad):
                        continue
                    exposed_by_net.setdefault(pad.net_name, pad)
                if len(exposed_by_net) > 1:
                    first, second = list(exposed_by_net.values())[:2]
                    yield self._boolean_result(
                        analysis_result,
                        category,
                        multiple_item,
                        replace(opening, layer_name=mask_layer),
                        related=second,
                        message="One solder-mask opening exposes multiple copper nets.",
                    )

    def _connected_solder_mask_pad_components(self, openings, mask_layer):
        """Group only genuinely touching pad openings, including EP shapes."""
        items = sorted(openings, key=index_sort_key)
        parents = list(range(len(items)))

        def find(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left, right):
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        for left_index, left in enumerate(items):
            for right_index in range(left_index + 1, len(items)):
                right = items[right_index]
                if right.bbox_nm[0] > left.bbox_nm[2]:
                    break
                if not bbox_near(left.bbox_nm, right.bbox_nm, 0):
                    continue
                if self._solder_mask_opening_gap_nm(
                    left, right, mask_layer, 1
                ) <= 0:
                    union(left_index, right_index)

        groups = {}
        for index, item in enumerate(items):
            groups.setdefault(find(index), []).append(item)
        yield from (tuple(component) for component in groups.values())

    def _solder_mask_opening_indexed(self, pad, mask_layer):
        bbox_nm = pad.bbox_nm
        reader = getattr(self.backend, "solder_mask_opening_bbox_nm", None)
        if reader is not None:
            exact_bbox = reader(pad.item, mask_layer)
            if exact_bbox is not None:
                bbox_nm = exact_bbox
        return replace(pad, layer_name=mask_layer, bbox_nm=bbox_nm)

    def _solder_mask_component_gap_nm(
        self, left, right, mask_layer, max_distance_nm
    ):
        return min(
            (
                (
                    self._solder_mask_opening_gap_nm(
                        left_item, right_item, mask_layer, max_distance_nm
                    ),
                    left_item,
                    right_item,
                )
                for left_item in left
                for right_item in right
            ),
            key=lambda result: result[0],
        )

    def _solder_mask_opening_gap_nm(
        self, left, right, mask_layer, max_distance_nm
    ):
        reader = getattr(self.backend, "solder_mask_opening_clearance_nm", None)
        if reader is not None:
            exact = reader(
                left.item, right.item, mask_layer, max_distance_nm
            )
            if exact is not None:
                return max(0.0, float(exact))
        fallback = self._pad_to_pad_gap_mm(left, right)
        return (fallback or 0.0) * NM_PER_MM

    def _solder_mask_opening_to_item_gap_nm(
        self, opening, indexed, mask_layer, max_distance_nm
    ):
        reader = getattr(
            self.backend,
            "solder_mask_opening_to_item_clearance_nm",
            None,
        )
        if reader is not None:
            exact = reader(
                opening.item, indexed.item, mask_layer, max_distance_nm
            )
            if exact is not None:
                return max(0.0, float(exact))
        segments = self._track_segments(indexed)
        if not segments:
            return float("inf")
        return max(
            0.0,
            min(
                bbox_to_segment_distance(opening.bbox_nm, segment)
                for segment in segments
            )
            - indexed.width_nm / 2.0,
        )

    def _mask_drawing_exposes_pad(self, opening, pad):
        reader = getattr(self.backend, "item_clearance_nm", None)
        if reader is not None:
            exact = reader(opening.item, pad.item, 1)
            if exact is not None:
                return exact <= 0
        return bbox_overlaps_area(opening.bbox_nm, pad.bbox_nm)

    def _collect_minimum(self, category, results):
        result_list = []
        minimum = -1
        have_red = False
        have_yellow = False
        checked_count = 0
        violation_count = 0
        item_summaries = self._seed_item_summaries(category)
        for data in results:
            checked_count += 1
            value = safe_float(data.get("value"), None)
            is_ratio = (
                category == "Hole Size"
                and self._item_summary_unit(category, data.get("item"))
                == "ratio"
            )
            if (
                value is not None
                and not is_ratio
                and (value < minimum or minimum == -1)
            ):
                minimum = value
            color = data.get("color")
            if color in ("red", "gold"):
                violation_count += 1
            have_red, have_yellow = update_color_flags(
                color, have_red, have_yellow
            )
            item_summary = self._update_item_summary(
                item_summaries, category, data, value
            )
            keep_normal_aspect_ratio = (
                category == "Hole Size"
                and self._rule_item_name(category, data.get("item", ""))
                == "Aspect Ratio"
            )
            keep_normal_slot_result = (
                category == "Hole Size"
                and self._rule_item_name(category, data.get("item", ""))
                in (
                    "Smallest Slot Width",
                    "Largest Slot Width",
                    "Largest Slot Length",
                    "Slot Aspect Ratio",
                )
            )
            if (
                not self.include_passed_details
                and data.get("color") == "black"
                and not keep_normal_aspect_ratio
                and not keep_normal_slot_result
            ):
                continue
            result_list.append({"result": [data]})
            if item_summary is not None:
                item_summary["displayed_count"] += 1
            self._append_issue(category, data)
        result_list = self._ordered_aspect_ratio_groups(category, result_list)
        result = {
            "display": "正常" if minimum == -1 else round(minimum, 6),
            "check": result_list,
            "color": aggregate_color(have_red, have_yellow),
            "checked_count": checked_count,
            "violation_count": violation_count,
            "displayed_count": len(result_list),
            "execution_status": "completed",
        }
        if item_summaries is not None:
            result["item_summaries"] = self._finalize_item_summaries(
                item_summaries
            )
            result["display_unit"] = "mm"
            result["display_semantics"] = "minimum_dimensional_measurement"
        return result

    def _ordered_aspect_ratio_groups(self, category, groups):
        if category != "Hole Size":
            return groups

        def is_aspect(group):
            rows = group.get("result") or ()
            return bool(rows) and self._rule_item_name(
                category, rows[0].get("item", "")
            ) == "Aspect Ratio"

        aspect_groups = sorted(
            (group for group in groups if is_aspect(group)),
            key=lambda group: safe_float(group["result"][0].get("value"), float("-inf")),
            reverse=True,
        )
        if len(aspect_groups) < 2:
            return groups
        ordered_aspects = iter(aspect_groups)
        return [next(ordered_aspects) if is_aspect(group) else group for group in groups]

    def _collect_maximum(self, category, results):
        result_list = []
        maximum = -1
        have_red = False
        have_yellow = False
        checked_count = 0
        violation_count = 0
        for data in results:
            checked_count += 1
            value = safe_float(data.get("value"), None)
            if value is not None and value > maximum:
                maximum = value
            color = data.get("color")
            if color in ("red", "gold"):
                violation_count += 1
            have_red, have_yellow = update_color_flags(
                color, have_red, have_yellow
            )
            if not self.include_passed_details and color == "black":
                continue
            result_list.append({"result": [data]})
            self._append_issue(category, data)
        return {
            "display": "正常" if maximum == -1 else round(maximum, 6),
            "check": result_list,
            "color": aggregate_color(have_red, have_yellow),
            "checked_count": checked_count,
            "violation_count": violation_count,
            "displayed_count": len(result_list),
            "execution_status": "completed",
        }

    def _summary_result(
        self,
        minimum,
        result_list,
        have_red,
        have_yellow,
        checked_count=None,
        violation_count=None,
    ):
        if checked_count is None:
            checked_count = len(result_list)
        if violation_count is None:
            violation_count = sum(
                1
                for group in result_list
                for data in group.get("result") or ()
                if data.get("color") in ("red", "gold")
            )
        return {
            "display": "正常" if minimum == -1 else round(minimum, 6),
            "check": result_list,
            "color": aggregate_color(have_red, have_yellow),
            "checked_count": checked_count,
            "violation_count": violation_count,
            "displayed_count": len(result_list),
            "execution_status": "completed",
        }

    def _remote_passing_display(self, category, result):
        if (
            self._uses_remote_contract()
            and category in ("Pad size", "RingHole")
            and isinstance(result, dict)
            and result.get("color") == "black"
        ):
            result = dict(result)
            result["display"] = "正常"
        return result

    def _summary_only(self, category, results):
        minimum = -1
        have_red = False
        have_yellow = False
        result_list = []
        checked_count = 0
        violation_count = 0
        for data in results:
            checked_count += 1
            value = safe_float(data.get("value"), None)
            if value is not None and (value < minimum or minimum == -1):
                minimum = value
            color = data.get("color")
            if color in ("red", "gold"):
                violation_count += 1
            have_red, have_yellow = update_color_flags(
                color, have_red, have_yellow
            )
            if color != "black":
                self._append_issue(category, data)
                result_list.append({"result": [data]})
        return {
            "display": "正常" if minimum == -1 else round(minimum, 6),
            "check": result_list,
            "color": aggregate_color(have_red, have_yellow),
            "checked_count": checked_count,
            "violation_count": violation_count,
            "displayed_count": len(result_list),
            "execution_status": "completed",
        }

    def _update_item_summary(self, summaries, category, data, value):
        if summaries is None:
            return None
        item_rule_key = str(
            data.get("rule_key")
            or self._rule_key(category, data.get("item", ""))
        )
        key = item_rule_key or str(data.get("item") or "")
        summary = summaries.setdefault(
            key,
            self._empty_item_summary(
                category,
                data.get("item"),
                item_rule_key,
            ),
        )
        summary["checked_count"] += 1
        if data.get("color") in ("red", "gold"):
            summary["violation_count"] += 1
        if value is not None:
            kind = self.color_rule.rule_kind(
                category,
                self._rule_item_name(category, data.get("item", "")),
            )
            if kind == "max":
                if summary["extreme"] == -1 or value > summary["extreme"]:
                    summary["extreme"] = value
            elif summary["extreme"] == -1 or value < summary["extreme"]:
                summary["extreme"] = value
        summary["have_red"], summary["have_yellow"] = update_color_flags(
            data.get("color"), summary["have_red"], summary["have_yellow"]
        )
        return summary

    def _seed_item_summaries(self, category):
        if category == "Hole Size":
            return {}
        if category not in ("Smallest Trace Spacing", "SMD Spacing"):
            return None
        summaries = {}
        for rule in (self.rules or {}).get(category, ()):
            if not isinstance(rule, dict) or not rule.get("item"):
                continue
            item = self.tr(rule["item"])
            item_rule_key = self._rule_key(category, item)
            summaries[item_rule_key] = self._empty_item_summary(
                category,
                item,
                item_rule_key,
            )
        return summaries

    def _empty_item_summary(self, category, item, item_rule_key):
        return {
            "rule_key": str(item_rule_key or ""),
            "item": str(item or ""),
            "unit": self._item_summary_unit(category, item),
            "checked_count": 0,
            "violation_count": 0,
            "displayed_count": 0,
            "extreme": -1,
            "have_red": False,
            "have_yellow": False,
        }

    def _finalize_item_summaries(self, summaries):
        finalized = {}
        for key, summary in summaries.items():
            extreme = summary.pop("extreme")
            have_red = summary.pop("have_red")
            have_yellow = summary.pop("have_yellow")
            summary["display"] = (
                "正常" if extreme == -1 else round(extreme, 6)
            )
            summary["color"] = aggregate_color(have_red, have_yellow)
            summary["execution_status"] = "completed"
            finalized[key] = summary
        return finalized

    def _item_summary_unit(self, category, item):
        item_name = self._rule_item_name(category, item or "")
        return "ratio" if "Aspect Ratio" in item_name else "mm"

    def _result(self, analysis_result, category, item, value, indexed, related=None, extra=None, message=""):
        item_name = self._rule_item_name(category, item)
        color = self.color_rule.get_rule(analysis_result, category, item_name, value)
        data = {
            "id": indexed.item_id,
            "rule_key": self._rule_key(category, item),
            "source": "kicad",
            "confidence": 1.0,
            "geometry_basis": self._result_geometry_basis(indexed, related),
            "layer": [str(indexed.layer_name)],
            "value": str(round(value, 6)),
            "item": item,
            "color": color,
            "type": 10,
            "rule": self._rule_for(category, item),
            "item_type": indexed.item_type,
            "bbox_nm": indexed.bbox_nm,
        }
        if message:
            data["message"] = message
        if related is not None:
            data["related_id"] = related.item_id
            data["related_type"] = related.item_type
            data["related_layer"] = related.layer_name
            data["related_bbox_nm"] = related.bbox_nm
        if extra:
            data.update(extra)
        return data

    def _boolean_result(
        self,
        analysis_result,
        category,
        item,
        indexed,
        related=None,
        message="",
        force_violation=False,
    ):
        rule = self._rule_for(category, item)
        data = {
            "id": indexed.item_id,
            "rule_key": self._rule_key(category, item),
            "source": "kicad",
            "confidence": 1.0,
            "geometry_basis": self._result_geometry_basis(indexed, related),
            "layer": [str(indexed.layer_name)],
            "value": "1",
            "value_kind": "boolean",
            "item": item,
            "color": "red",
            "type": 10,
            "rule": rule,
            "item_type": indexed.item_type,
            "bbox_nm": indexed.bbox_nm,
            "message": message,
        }
        if rule and rule != "-,-,-" and not force_violation:
            data["color"] = self.color_rule.get_rule(analysis_result, category, item, 1)
        if related is not None:
            data["related_id"] = related.item_id
            data["related_bbox_nm"] = related.bbox_nm
            data["related_layer"] = related.layer_name
            data["related_type"] = related.item_type
        return data

    def _result_geometry_basis(self, *items):
        bases = tuple(
            dict.fromkeys(
                str(item.geometry_basis or "exact_kicad")
                for item in items
                if item is not None
            )
        )
        non_exact = tuple(basis for basis in bases if basis != "exact_kicad")
        if not non_exact:
            return "exact_kicad"
        if len(non_exact) == 1:
            return non_exact[0]
        return "mixed:" + ",".join(non_exact)

    def _same_indexed_item(self, left, right):
        if left.item is right.item:
            return True
        return bool(left.item_id and left.item_id == right.item_id)

    def _unique_indexed_items(self, items):
        result = []
        seen = set()
        for item in items:
            key = item.item_id or id(item.item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return tuple(result)

    def _indexed_pair_key(self, left, right):
        left_key = ("uuid", left.item_id) if left.item_id else ("identity", id(left.item))
        right_key = ("uuid", right.item_id) if right.item_id else ("identity", id(right.item))
        return tuple(sorted((left_key, right_key)))

    def _item_id(self, item):
        try:
            return self.backend.item_id(item)
        except Exception:
            return ""

    def _is_reportable(self, analysis_result, category, item, value):
        return self.color_rule.get_rule(analysis_result, category, self._rule_item_name(category, item), value) != "black"

    def _should_report_measurement(
        self,
        analysis_result,
        category,
        item,
        value,
        remote_limit,
    ):
        return (
            self._is_reportable(analysis_result, category, item, value)
            or (
                self._uses_remote_contract()
                and value > 0
                and value <= remote_limit
            )
        )

    def _within_rule_limit(self, analysis_result, category, item, value):
        rule = self._rule_for(category, item)
        if not rule:
            return self._is_reportable(analysis_result, category, item, value)
        limit = self.color_rule.third_rule_value(rule)
        if limit >= 900:
            return True
        return value <= limit

    def _candidate_gap_nm(self, category, item):
        rule = self._rule_for(category, item)
        values = []
        for part in str(rule or "").split(","):
            try:
                value = float(part)
            except ValueError:
                continue
            if value < 900:
                values.append(value)
        return (max(values) if values else 1.0) * NM_PER_MM

    def _candidate_gap_for_items(self, category, items):
        return max((self._candidate_gap_nm(category, item) for item in items), default=NM_PER_MM)

    def _rule_key(self, category, item):
        return rule_key(category, self._rule_item_name(category, item))

    def _append_issue(self, category, data):
        self._add_local_fields(category, data)
        self.issues.append(
            DfmIssue(
                category=category,
                item=data.get("item", ""),
                severity=color_to_severity(data.get("color", "black")),
                layer=data.get("layer"),
                value=data.get("value", ""),
                rule=data.get("rule", ""),
                message=data.get("message", ""),
                raw=data,
                location=Location(
                    item_id=data.get("id"),
                    item_type=data.get("item_type", ""),
                    layer=data.get("layer"),
                    bbox_nm=data.get("bbox_nm"),
                ),
            )
        )

    def _add_local_fields(self, category, data):
        data.setdefault("type", 10)
        data.setdefault("rule", self._rule_for(category, data.get("item", "")))

    def _rule_for(self, category, item):
        key = (category, item)
        if key in self._rule_cache:
            return self._rule_cache[key]
        for candidate in self._rule_item_candidates(item):
            rule = self._default_rule_for(category, candidate)
            if rule:
                self._rule_cache[key] = rule
                return rule
        self._rule_cache[key] = ""
        return ""

    def _rule_item_name(self, category, item):
        key = (category, item)
        if key in self._rule_item_cache:
            return self._rule_item_cache[key]
        for candidate in self._rule_item_candidates(item):
            if self._default_rule_for(category, candidate):
                self._rule_item_cache[key] = candidate
                return candidate
        self._rule_item_cache[key] = item
        return item

    def _default_rule_for(self, category, item):
        return self.color_rule.default_rule_for(category, item)

    def _rule_item_candidates(self, item):
        yield item
        for key, value in self.language.items():
            if value == item:
                yield key

    def _canonical_layer_name_for_id(self, layer_id):
        for owner, name in (
            (self.backend, "canonical_layer_name"),
            (self.backend, "layer_name"),
            (self.board, "GetStandardLayerName"),
            (self.board, "GetLayerName"),
        ):
            if owner is None or not hasattr(owner, name):
                continue
            try:
                value = getattr(owner, name)(layer_id)
            except Exception:
                continue
            if value:
                return str(value)
        return str(layer_id)

    def _index_item(
        self,
        item,
        footprint=None,
        item_kind=None,
        layer_id_override=None,
    ):
        layer_id = (
            layer_id_override
            if layer_id_override is not None
            else self.backend.item_layer_id(item)
        )
        is_zone = item_kind == "zone"
        pad_size = None
        pad_shape = None
        pad_drill = None
        pad_drill_shape = None
        pad_attr = None
        pad_radius = 0.0
        pad_is_smd = False
        pad_is_bga = False
        pad_has_solder_mask_opening = True
        pad_solder_mask_sides = ()
        via_drill = 0.0
        via_is_micro = False
        via_is_blind_buried = False
        via_layer_pair = ()
        copper_layer_names = ()
        pad_copper_layers_known = False
        hole_drill = 0.0
        is_round_pth = False
        is_round_drill = True
        hole_bbox = None
        footprint_names = ()
        zone_polygons = ()
        zone_edges = ()
        zone_edge_x_starts = ()
        zone_edge_max_width = 0.0
        zone_is_teardrop = False
        zone_edge_buckets = None
        segment = None
        track_path = ()
        track_endpoint_vectors = ()
        geometry_basis = "exact_kicad"
        if item_kind == "pad":
            is_via = False
            is_track = False
            is_pad = True
        elif item_kind in ("zone", "drawing"):
            is_via = False
            is_track = False
            is_pad = False
            if item_kind == "zone":
                teardrop_reader = getattr(
                    self.backend,
                    "is_teardrop_zone",
                    None,
                )
                zone_name_reader = getattr(self.backend, "zone_name", None)
                try:
                    zone_is_teardrop = bool(
                        teardrop_reader(item)
                        if teardrop_reader is not None
                        else (
                            zone_name_reader is not None
                            and zone_name_reader(item) == "$teardrop_padvia$"
                        )
                    )
                except Exception:
                    zone_is_teardrop = False
                zone_polygon_reader = getattr(
                    self.backend,
                    "zone_polygons",
                    None,
                )
                if zone_polygon_reader is not None:
                    zone_polygons = zone_polygon_reader(
                        item,
                        layer_id,
                    )
                    zone_edges = tuple(
                        sorted(
                            filled_polygon_edges(zone_polygons),
                            key=lambda edge: min(edge[0][0], edge[1][0]),
                        )
                    )
                    zone_edge_x_starts = tuple(
                        min(edge[0][0], edge[1][0])
                        for edge in zone_edges
                    )
                    zone_edge_max_width = max(
                        (
                            abs(edge[1][0] - edge[0][0])
                            for edge in zone_edges
                        ),
                        default=0.0,
                    )
                    zone_edge_buckets = {}
                    for edge in zone_edges:
                        edge_bbox = segment_bbox_nm(edge)
                        first_bucket = math.floor(
                            edge_bbox[0] / ZONE_EDGE_BUCKET_NM
                        )
                        last_bucket = math.floor(
                            edge_bbox[2] / ZONE_EDGE_BUCKET_NM
                        )
                        for bucket in range(first_bucket, last_bucket + 1):
                            zone_edge_buckets.setdefault(bucket, []).append(edge)
        else:
            is_via = self.backend.is_via(item)
            is_pad = False
            is_track = (not is_via) and self.backend.is_track(item)
        if is_via:
            via_drill = self.backend.via_drill_mm(item)
            via_is_micro = self.backend.is_micro_via(item)
            via_is_blind_buried = self.backend.is_blind_buried_via(item)
            via_layer_pair = self.backend.via_layer_pair_names(item)
            copper_layer_reader = getattr(
                self.backend,
                "item_copper_layer_ids",
                None,
            )
            try:
                copper_layer_ids = tuple(
                    copper_layer_reader(item) if copper_layer_reader else ()
                )
            except Exception:
                copper_layer_ids = ()
            copper_layer_names = tuple(
                self._canonical_layer_name_for_id(copper_layer_id)
                for copper_layer_id in copper_layer_ids
            )
            hole_drill = via_drill
        elif is_pad:
            pad_size = self.backend.pad_size_mm(item)
            pad_shape = self.backend.pad_shape(item)
            pad_drill = self.backend.pad_drill_mm(item)
            pad_drill_shape = self.backend.pad_drill_shape(item)
            pad_attr = self.backend.pad_attribute(item)
            pad_radius = min(abs(pad_size[0]), abs(pad_size[1])) * NM_PER_MM / 2.0
            pad_is_smd = self.backend.is_smd_pad(item)
            pad_is_bga = self.backend.is_bga_pad(item, footprint)
            pad_has_solder_mask_opening = self.backend.pad_has_solder_mask_opening(item)
            side_reader = getattr(
                self.backend, "pad_has_solder_mask_opening_on_layer", None
            )
            pad_solder_mask_sides = tuple(
                side
                for side in ("F", "B")
                if (
                    side_reader(item, side + ".Cu")
                    if side_reader is not None
                    else pad_has_solder_mask_opening
                )
            )
            pad_has_solder_mask_opening = bool(pad_solder_mask_sides)
            copper_layer_reader = getattr(
                self.backend,
                "pad_copper_layer_ids",
                None,
            )
            try:
                copper_layer_ids = (
                    copper_layer_reader(item)
                    if copper_layer_reader is not None
                    else None
                )
            except Exception:
                copper_layer_ids = None
            if copper_layer_ids is not None:
                pad_copper_layers_known = True
                copper_layer_names = tuple(
                    dict.fromkeys(
                        self._canonical_layer_name_for_id(copper_layer_id)
                        for copper_layer_id in copper_layer_ids
                    )
                )
            hole_drill = min((abs(value) for value in pad_drill if value > 0), default=0.0)
            is_round_pth = self.backend.is_round_pth_pad(item)
            is_round_drill = self.backend.is_round_drill_pad(item)
            footprint_name_reader = getattr(self.backend, "footprint_names", None)
            if footprint_name_reader is not None and footprint is not None:
                try:
                    footprint_names = tuple(footprint_name_reader(footprint) or ())
                except Exception:
                    footprint_names = ()
        if hole_drill > 0:
            hole_bbox_reader = getattr(self.backend, "hole_bbox", None)
            if hole_bbox_reader is not None:
                try:
                    hole_bbox = hole_bbox_reader(item)
                except Exception:
                    hole_bbox = None
        width = self.backend.item_width(item) if is_track or is_via else 0
        segment = self.backend.track_segment(item)
        if is_track:
            geometry_reader = getattr(self.backend, "track_geometry", None)
            try:
                geometry = (
                    geometry_reader(item)
                    if geometry_reader is not None
                    else {}
                )
            except Exception:
                geometry = {}
                if "ARC" in str(self.backend.item_type(item)).upper():
                    geometry_basis = "kicad_arc_geometry_unavailable"
            if geometry:
                segment = geometry.get("segment") or segment
                track_path = tuple(geometry.get("path") or ())
                track_endpoint_vectors = tuple(
                    geometry.get("endpoint_vectors") or ()
                )
                geometry_basis = str(
                    geometry.get("geometry_basis") or geometry_basis
                )
            if not track_path and segment and not geometry_basis.startswith(
                "kicad_arc_"
            ):
                track_path = tuple(segment)
            if not track_endpoint_vectors and len(track_path) >= 2:
                start, end = track_path[0], track_path[-1]
                track_endpoint_vectors = (
                    (end[0] - start[0], end[1] - start[1]),
                    (start[0] - end[0], start[1] - end[1]),
                )
        layer_name = (
            self._canonical_layer_name_for_id(layer_id)
            if layer_id_override is not None
            else self.backend.item_layer_name(item)
        )
        canonical_layer_reader = getattr(
            self.backend, "canonical_layer_name", None
        )
        if canonical_layer_reader is not None and layer_id is not None:
            try:
                canonical_layer = canonical_layer_reader(layer_id)
            except Exception:
                canonical_layer = ""
            if canonical_layer:
                layer_name = canonical_layer
        return IndexedItem(
            item=item,
            item_id=self._item_id(item),
            item_type=self.backend.item_type(item),
            layer_name=layer_name,
            layer_id=layer_id,
            net_name=self.backend.item_net_name(item),
            bbox_nm=self.backend.item_bbox(item),
            segment_nm=segment,
            track_path_nm=track_path,
            track_endpoint_vectors_nm=track_endpoint_vectors,
            geometry_basis=geometry_basis,
            center_nm=self.backend.item_position(item),
            width_nm=width,
            pad_size_mm=pad_size,
            pad_shape=pad_shape,
            pad_drill_mm=pad_drill,
            pad_drill_shape=pad_drill_shape,
            pad_attr=pad_attr,
            pad_radius_nm=pad_radius,
            pad_is_smd=pad_is_smd,
            pad_is_bga=pad_is_bga,
            pad_has_solder_mask_opening=pad_has_solder_mask_opening,
            pad_solder_mask_sides=pad_solder_mask_sides,
            is_via=is_via,
            is_track=is_track,
            is_pad=is_pad,
            is_zone=is_zone,
            via_drill_mm=via_drill,
            via_is_micro=via_is_micro,
            via_is_blind_buried=via_is_blind_buried,
            via_layer_pair=via_layer_pair,
            copper_layer_names=copper_layer_names,
            pad_copper_layers_known=pad_copper_layers_known,
            hole_drill_mm=hole_drill,
            hole_radius_nm=hole_drill * NM_PER_MM / 2.0,
            is_round_pth=is_round_pth,
            is_round_drill=is_round_drill,
            hole_bbox_nm=hole_bbox,
            footprint_names=footprint_names,
            zone_polygons_nm=zone_polygons,
            zone_edges_nm=zone_edges,
            zone_edge_x_starts=zone_edge_x_starts,
            zone_edge_max_width=zone_edge_max_width,
            zone_is_teardrop=zone_is_teardrop,
            zone_edge_buckets=zone_edge_buckets,
        )

    def _all_tracks(self):
        return self.index.tracks

    def _all_pads(self):
        return self.index.pads

    def _copper_pads(self):
        return self.index.copper_pads

    def _smd_pads(self):
        return self.index.smd_pads

    def _all_zones(self):
        return self.index.zones

    def _hole_items(self):
        return self.index.holes

    def _hole_drill_mm(self, indexed):
        return round(float(indexed.hole_drill_mm), 6)

    def _hole_bbox_nm(self, hole):
        if hole.hole_bbox_nm is not None:
            return hole.hole_bbox_nm
        center = hole.center_nm
        if center is None:
            return None
        if hole.pad_drill_mm:
            drill_x, drill_y = hole.pad_drill_mm
            half_x = abs(drill_x) * NM_PER_MM / 2.0
            half_y = abs(drill_y) * NM_PER_MM / 2.0
        else:
            half_x = half_y = hole.hole_radius_nm
        if half_x <= 0 or half_y <= 0:
            return None
        return (
            center[0] - half_x,
            center[1] - half_y,
            center[0] + half_x,
            center[1] + half_y,
        )

    def _hole_to_board_edge_item(self, hole):
        if hole.is_via:
            return "Via-to-Board Edge"
        if self._is_screw_hole(hole):
            return "Screw Hole-to-Board Edge"
        if hole.pad_attr == 3:
            return "NPTH-to-Board Edge"
        return "PTH-to-Board Edge"

    @staticmethod
    def _is_screw_hole(hole):
        text = "".join(
            character
            for value in hole.footprint_names
            for character in str(value or "").lower()
            if character.isalnum()
        )
        return any(
            marker in text
            for marker in (
                "mountinghole",
                "screwhole",
                "mountingdrill",
                "screwdrill",
            )
        )

    def _pad_spacing_item(self, left, right):
        if left.pad_is_bga or right.pad_is_bga:
            return "BGA Pads"
        if left.pad_is_smd and right.pad_is_smd:
            return "SMD Pad Spacing"
        return "Pad-to-Pad Spacing"

    def _pad_has_copper(self, pad):
        if pad.pad_copper_layers_known:
            return bool(pad.copper_layer_names)
        return pad.pad_attr != 3

    def _pad_copper_layers(self, pad, copper_layer_names):
        if pad.pad_copper_layers_known:
            return tuple(pad.copper_layer_names)
        if pad.pad_attr == 0:
            return tuple(copper_layer_names) or (pad.layer_name,)
        return (pad.layer_name,)

    def _build_net_tie_pad_groups(self):
        group_reader = getattr(self.backend, "net_tie_pad_groups", None)
        if group_reader is None:
            return {}
        try:
            raw_groups = tuple(group_reader() or ())
        except Exception:
            return {}
        return net_tie_groups_by_pad_id(raw_groups)

    def _build_net_tie_footprint_pad_ids(self):
        reader = getattr(self.backend, "net_tie_footprint_pad_ids", None)
        if reader is None:
            return frozenset()
        try:
            return frozenset(str(pad_id) for pad_id in reader() or () if pad_id)
        except Exception:
            return frozenset()

    def _same_named_net(self, left, right):
        left_net = str(left.net_name or "")
        right_net = str(right.net_name or "")
        return bool(left_net and right_net and left_net == right_net)

    def _is_declared_net_tie_pad_pair(self, left, right):
        """Return whether two pads are members of the same declared group.

        The backend reports groups per NetTie footprint, keyed by member pad
        UUID.  Matching both UUID and the pad's current net prevents a stale
        or ambiguous group from granting an exemption.  This is deliberately
        local: other pads using the same two net names remain unrelated.
        """
        if not left.is_pad or not right.is_pad:
            return False
        return declared_net_tie_pad_pair(
            self._net_tie_groups_by_pad_id,
            left.item_id,
            left.net_name,
            right.item_id,
            right.net_name,
        )

    def _is_smd_net_tie_exempt(self, left, right):
        """Scope SMD spacing exemptions to one physical NetTie structure.

        Declared member pads are always one intentional structure, even when
        their shapes have a positive gap.  KiCad NetTie footprints can also
        place an ordinary same-net pad immediately beside one member; that
        pad is local only when its exact shape clearance to the same-net
        member fits that member's explicit local-clearance override.
        """
        if not left.is_pad or not right.is_pad:
            return False
        if self._is_declared_net_tie_pad_pair(left, right):
            return True
        return (
            self._is_pad_locally_attached_across_net_tie(left, right)
            or self._is_pad_locally_attached_across_net_tie(right, left)
        )

    def _is_pad_locally_attached_across_net_tie(
        self,
        reported_member,
        ordinary_pad,
    ):
        candidates = local_net_tie_attachment_candidates(
            self._net_tie_groups_by_pad_id,
            reported_member.item_id,
            reported_member.net_name,
            ordinary_pad.item_id,
            ordinary_pad.net_name,
        )
        for member_id, member_net in candidates:
            same_net_member = self._pads_by_id.get(member_id)
            if (
                same_net_member is None
                or not same_net_member.is_pad
                or str(same_net_member.net_name or "") != member_net
                or not self._pads_share_copper_layer(
                    ordinary_pad,
                    same_net_member,
                )
            ):
                continue
            attachment_limit_mm = max(
                NET_TIE_CONTACT_TOLERANCE_MM,
                self._pad_local_clearance_mm(same_net_member),
            )
            attachment_gap_mm = self._pad_to_pad_gap_mm(
                ordinary_pad,
                same_net_member,
            )
            if (
                attachment_gap_mm is not None
                and attachment_gap_mm <= attachment_limit_mm
            ):
                return True
        return False

    def _pads_share_copper_layer(self, left, right):
        left_layers = self._indexed_pad_copper_layers(left)
        right_layers = self._indexed_pad_copper_layers(right)
        return bool(left_layers.intersection(right_layers))

    def _indexed_pad_copper_layers(self, pad):
        if pad.pad_copper_layers_known:
            return frozenset(pad.copper_layer_names)
        if pad.copper_layer_names:
            return frozenset(pad.copper_layer_names)

        reader = getattr(self.backend, "pad_copper_layer_ids", None)
        if reader is not None:
            try:
                layer_ids = reader(pad.item)
            except Exception:
                layer_ids = None
            if layer_ids is not None:
                return frozenset(
                    self._canonical_layer_name_for_id(layer_id)
                    for layer_id in layer_ids
                )
        return frozenset((pad.layer_name,)) if pad.layer_name else frozenset()

    def _pad_local_clearance_mm(self, pad):
        cache_key = pad.item_id or id(pad.item)
        if cache_key in self._pad_local_clearance_mm_cache:
            return self._pad_local_clearance_mm_cache[cache_key]
        value = None
        reader = getattr(self.backend, "item_local_clearance_nm", None)
        if reader is not None:
            try:
                value = reader(pad.item)
            except Exception:
                value = None
        if value is None:
            reader = getattr(pad.item, "GetLocalClearance", None)
            if reader is not None:
                try:
                    value = reader()
                except Exception:
                    value = None
        try:
            clearance_mm = max(0.0, float(value) / NM_PER_MM)
        except (TypeError, ValueError):
            clearance_mm = 0.0
        self._pad_local_clearance_mm_cache[cache_key] = clearance_mm
        return clearance_mm

    def _is_local_net_tie_contact(self, left, right, distance_mm):
        """Return whether a zero-gap pair is part of one declared net tie.

        A net tie does not make its nets globally equivalent.  Only physical
        contact at the declared member pads is exempt: member-pad to
        member-pad, or a track on another group net touching a member pad.
        Positive clearance remains a real DFM measurement even inside the
        footprint, and unrelated objects elsewhere on the same nets are never
        hidden.
        """
        if (
            distance_mm is None
            or distance_mm > NET_TIE_CONTACT_TOLERANCE_MM
        ):
            return False
        left_net = str(left.net_name or "")
        right_net = str(right.net_name or "")
        if not left_net or not right_net or left_net == right_net:
            return False

        if left.is_pad and right.is_pad:
            return self._is_declared_net_tie_pad_pair(left, right)

        if left.is_pad and right.is_track:
            pad, track = left, right
        elif right.is_pad and left.is_track:
            pad, track = right, left
        else:
            return False
        for members, net_names in self._net_tie_groups_by_pad_id.get(
            pad.item_id, ()
        ):
            if (
                members.get(pad.item_id) == str(pad.net_name or "")
                and str(track.net_name or "") in net_names
            ):
                return True
        return False

    def _pad_on_copper_layer(self, pad, layer_name, layer_ids_by_name):
        if layer_name == pad.layer_name:
            return pad
        return replace(
            pad,
            layer_name=layer_name,
            layer_id=layer_ids_by_name.get(layer_name),
        )

    def _hole_copper_layers(self, hole):
        if hole.is_via and hole.via_layer_pair:
            return tuple(self._via_span_layers(hole))
        if hole.pad_attr in (0, 3):
            return self._copper_layer_names()
        return (hole.layer_name,)

    def _via_span_layers(self, via):
        cache_key = id(via.item)
        if cache_key in self._via_span_layer_cache:
            return self._via_span_layer_cache[cache_key]
        if via.copper_layer_names:
            result = tuple(via.copper_layer_names)
            self._via_span_layer_cache[cache_key] = result
            return result
        layer_pair = tuple(str(layer) for layer in via.via_layer_pair[:2])
        if len(layer_pair) < 2:
            result = (via.layer_name,)
            self._via_span_layer_cache[cache_key] = result
            return result
        start, end = layer_pair
        start_id = self._layer_id_for_name(start)
        end_id = self._layer_id_for_name(end)
        if start_id is None or end_id is None:
            result = (via.layer_name,)
            self._via_span_layer_cache[cache_key] = result
            return result
        low, high = sorted((start_id, end_id))
        layers = []
        for layer in self._copper_layer_names():
            layer_id = self._layer_id_for_name(layer)
            if layer_id is not None and low <= layer_id <= high:
                layers.append(layer)
        result = tuple(layers) or (via.layer_name,)
        self._via_span_layer_cache[cache_key] = result
        return result

    def _copper_layer_names(self):
        return self.index.copper_layer_names

    def _layer_ids_by_name(self, *layer_maps):
        result = {}
        for layer_map in layer_maps:
            for items in layer_map.values():
                for indexed in items:
                    if indexed.layer_name and indexed.layer_id is not None:
                        result.setdefault(indexed.layer_name, int(indexed.layer_id))
                    break
        return result

    def _near_outline_segments(self, bbox_nm, max_gap_nm):
        if bbox_nm is None:
            return self.index.board_outline
        start_index = bisect.bisect_left(
            self.index.board_outline_x_starts,
            bbox_nm[0] - max_gap_nm - self.index.board_outline_max_width,
        )
        max_x = bbox_nm[2] + max_gap_nm
        return tuple(
            segment
            for segment, segment_bbox in zip(
                self.index.board_outline[start_index:],
                self.index.board_outline_segment_bboxes[start_index:],
            )
            if segment_bbox is not None
            and segment_bbox[0] <= max_x
            and bbox_near(bbox_nm, segment_bbox, max_gap_nm)
        )

    def _layer_id_for_name(self, layer_name):
        if layer_name in self.index.layer_ids_by_name:
            return self.index.layer_ids_by_name[layer_name]
        if hasattr(self.board, "GetLayerID"):
            layer_id = self.board.GetLayerID(layer_name)
            if layer_id is not None and int(layer_id) >= 0:
                return int(layer_id)
        for layer, tracks in self.index.tracks_by_layer.items():
            if layer == layer_name and tracks:
                return int(tracks[0].layer_id)
        return None

    def _drill_to_trace_item(self, hole, copper_layer=None):
        suffix = "[Inner]" if is_inner_copper_layer(copper_layer or hole.layer_name) else "[Outer]"
        if hole.is_via:
            return "Via-to-Trace {0}".format(suffix)
        attr = hole.pad_attr
        return "NPTH-to-Copper" if attr == 3 else "PTH-to-Trace {0}".format(suffix)

    def _hole_diameter_item(self, hole):
        if not hole.is_via:
            return "" if hole.pad_attr == 3 else "Smallest PTH"
        if not hole.via_is_blind_buried:
            return "Smallest Drill Size"
        layer_pair = tuple(str(layer) for layer in hole.via_layer_pair)
        is_blind = any(layer in ("F.Cu", "B.Cu") for layer in layer_pair)
        if hole.via_is_micro:
            return "Smallest Blind_Laser" if is_blind else "Smallest Buried_Laser"
        return "Smallest Blind_mec" if is_blind else "Smallest Buried_mec"

    def _hole_aspect_ratio(self, hole, drill):
        if hole.is_via:
            return None
        if drill <= 0:
            return None
        thickness = self._board_thickness_mm()
        if thickness <= 0:
            return None
        return round(thickness / drill, 6)

    def _board_thickness_mm(self):
        if self.index.board_thickness_mm is None:
            self.index.board_thickness_mm = self.backend.board_thickness_mm()
        return self.index.board_thickness_mm

    def _iter_slot_hole_results(self, analysis_result, category, hole):
        slot = self._slot_dimensions_mm(hole)
        if slot is None:
            return
        width, length = slot
        for item_name, value in (
            ("Smallest Slot Width", width),
            ("Largest Slot Width", width),
            ("Largest Slot Length", length),
            ("Slot Aspect Ratio", round(length / width, 6) if width > 0 else 0),
        ):
            item = self.tr(item_name)
            if (
                self._is_reportable(analysis_result, category, item, value)
                or self._within_rule_limit(
                    analysis_result, category, item, value
                )
            ):
                yield self._result(analysis_result, category, item, value, hole)

    def _slot_dimensions_mm(self, hole):
        if hole.is_via or hole.is_round_drill:
            return None
        drill_x, drill_y = hole.pad_drill_mm
        width = round(min(abs(drill_x), abs(drill_y)), 6)
        length = round(max(abs(drill_x), abs(drill_y)), 6)
        if width <= 0 or length <= width:
            return None
        return width, length

    def _slot_drill_segment_nm(self, hole):
        slot = self._slot_dimensions_mm(hole)
        if slot is None or hole.center_nm is None:
            return None, 0.0
        drill_x, drill_y = hole.pad_drill_mm
        width_nm = min(abs(drill_x), abs(drill_y)) * NM_PER_MM
        length_nm = max(abs(drill_x), abs(drill_y)) * NM_PER_MM
        axis_half = max(0.0, (length_nm - width_nm) / 2.0)
        center_x, center_y = hole.center_nm
        if abs(drill_x) >= abs(drill_y):
            segment = ((center_x - axis_half, center_y), (center_x + axis_half, center_y))
        else:
            segment = ((center_x, center_y - axis_half), (center_x, center_y + axis_half))
        return segment, width_nm / 2.0

    def _is_castellated_hole(self, hole):
        if not self.index.board_outline or hole.center_nm is None:
            return False
        candidate = self._drill_geometry_candidate(hole)
        if candidate is None:
            return False
        outline_segments = self._near_outline_segments(candidate.bbox_nm, 0)
        if not outline_segments:
            return False
        slot_segment, slot_radius = self._slot_drill_segment_nm(hole)
        if slot_segment is not None:
            return min(segment_distance(slot_segment, edge) for edge in outline_segments) <= slot_radius
        if hole.is_round_drill:
            return min(point_segment_distance(hole.center_nm, edge) for edge in outline_segments) <= hole.hole_radius_nm
        return min(bbox_to_segment_distance(candidate.bbox_nm, edge) for edge in outline_segments) <= 0

    def _has_mask_opening(self, indexed, side):
        openings = self.index.mask_openings_by_side.get(side, ())
        starts = self.index.mask_opening_x_starts_by_side.get(side, ())
        for opening in nearby_items(indexed, openings, starts, 0, self.index.mask_opening_max_width_by_side.get(side, 0)):
            if not bbox_near(indexed.bbox_nm, opening.bbox_nm, 0):
                continue
            if indexed.center_nm is not None and point_in_bbox(indexed.center_nm, opening.bbox_nm):
                return True
            if opening.center_nm is not None and point_in_bbox(opening.center_nm, indexed.bbox_nm):
                return True
            if bbox_overlaps_area(indexed.bbox_nm, opening.bbox_nm):
                return True
        return False

    def _point_connected_to_copper(self, source, point, radius_nm):
        source_candidate = self._point_geometry_candidate(source, point, radius_nm)
        for candidate in self._connection_candidates(source_candidate, max_gap_nm=radius_nm):
            if self._same_indexed_item(candidate, source):
                continue
            if not self._can_connect(source, candidate):
                continue
            if not point_near_bbox(point, candidate.bbox_nm, radius_nm):
                continue
            if self._point_touches_item(point, radius_nm, candidate):
                return True
        return False

    def _point_geometry_candidate(self, indexed, point, radius_nm):
        if point is None:
            return indexed
        return GeometryCandidate(
            indexed=indexed,
            bbox_nm=(
                point[0],
                point[1],
                point[0],
                point[1],
            ),
        )

    def _connection_candidates(self, source, max_gap_nm=None):
        indexed = getattr(source, "indexed", source)
        if indexed.net_name:
            items = self.index.connectable_items_by_net.get(indexed.net_name, ())
            starts = self.index.connectable_x_starts_by_net.get(indexed.net_name, ())
            max_width = self.index.connectable_max_width_by_net.get(indexed.net_name, 0)
        else:
            items = self.index.all_connectable_items
            starts = self.index.all_connectable_x_starts
            max_width = self.index.all_connectable_max_width
        if max_gap_nm is None:
            return items
        return tuple(nearby_items(source, items, starts, max_gap_nm, max_width))

    def _can_connect(self, source, candidate):
        if source.net_name and candidate.net_name and source.net_name != candidate.net_name:
            return False
        if source.layer_name == candidate.layer_name:
            return True
        source_layers = self._connected_copper_layers(source)
        candidate_layers = self._connected_copper_layers(candidate)
        return bool(set(source_layers).intersection(candidate_layers))

    def _connected_copper_layers(self, indexed):
        if indexed.is_via:
            if indexed.via_layer_pair:
                return self._via_span_layers(indexed)
            return self._copper_layer_names()
        if indexed.pad_attr == 0:
            return self._copper_layer_names()
        return (indexed.layer_name,)

    def _is_copper_connectable(self, indexed):
        if indexed.pad_attr == 3:
            return False
        if indexed.is_zone:
            return bool(indexed.zone_polygons_nm)
        return bool(indexed.segment_nm or indexed.center_nm or indexed.bbox_nm)

    def _copper_components(self, items, sorted_items=None, starts=None):
        items = tuple(items)
        if sorted_items is None:
            sorted_items = tuple(sorted(items, key=index_sort_key))
        if starts is None:
            starts = tuple(index_sort_key(item) for item in sorted_items)
        index_by_identity = {id(item): index for index, item in enumerate(items)}
        max_radius_nm = max((self._item_radius_nm(item) for item in items), default=0.0)
        max_item_width_nm = max_bbox_width_nm(sorted_items)
        remaining = set(range(len(items)))
        components = []
        while remaining:
            self._checkpoint()
            start = remaining.pop()
            stack = [start]
            component_indexes = [start]
            while stack:
                self._checkpoint()
                current = stack.pop()
                for candidate in tuple(
                    self._component_candidate_indexes(
                        items[current],
                        remaining,
                        sorted_items,
                        starts,
                        index_by_identity,
                        max_radius_nm,
                        max_item_width_nm,
                    )
                ):
                    if not self._items_connected(items[current], items[candidate]):
                        continue
                    remaining.remove(candidate)
                    stack.append(candidate)
                    component_indexes.append(candidate)
            components.append([items[index] for index in component_indexes])
        return components

    def _native_copper_components(self, items):
        connected_ids_reader = getattr(
            self.backend,
            "connected_item_ids",
            None,
        )
        if connected_ids_reader is None:
            return None
        # KiCad's connectivity graph already accounts for filled zones, their
        # per-layer islands, thermals, and teardrops.  Keep only concrete
        # track/pad/via nodes here: a single multi-layer ZONE object is exposed
        # with one UUID even though its layer islands are separate graph nodes.
        # Mapping that UUID back to every indexed clone would short layers (and
        # disconnected islands) together.  The connected non-zone UUIDs
        # returned for each concrete item retain KiCad's exact component split.
        items = tuple(item for item in items if not item.is_zone)
        if not items or any(not item.item_id for item in items):
            return None
        items_by_id = {}
        for item in items:
            items_by_id.setdefault(item.item_id, []).append(item)
        if any(len(indexed_items) != 1 for indexed_items in items_by_id.values()):
            # Duplicate UUIDs among concrete items are unexpected and cannot
            # be mapped safely back to graph nodes.
            return None
        remaining = set(items_by_id)
        components = []
        while remaining:
            seed_id = min(
                remaining,
                key=lambda item_id: stable_indexed_item_key(
                    min(items_by_id[item_id], key=stable_indexed_item_key)
                ),
            )
            if getattr(
                self.backend,
                "connected_item_ids_are_components",
                False,
            ):
                try:
                    connected_ids = connected_ids_reader(
                        items_by_id[seed_id][0].item
                    )
                except Exception:
                    return None
                if connected_ids is None:
                    return None
                component_ids = {seed_id}
                component_ids.update(
                    connected_id
                    for connected_id in map(str, connected_ids)
                    if connected_id in items_by_id
                )
                components.append(
                    [items_by_id[component_id][0] for component_id in component_ids]
                )
                remaining.difference_update(component_ids)
                continue

            component_ids = set()
            pending = [seed_id]
            while pending:
                current_id = pending.pop()
                if current_id in component_ids:
                    continue
                current = items_by_id[current_id][0]
                try:
                    connected_ids = connected_ids_reader(current.item)
                except Exception:
                    return None
                if connected_ids is None:
                    return None
                component_ids.add(current_id)
                for connected_id in connected_ids:
                    connected_id = str(connected_id)
                    if (
                        connected_id in items_by_id
                        and connected_id not in component_ids
                    ):
                        pending.append(connected_id)
            components.append(
                [items_by_id[component_id][0] for component_id in component_ids]
            )
            remaining.difference_update(component_ids)
        return components

    def _component_candidate_indexes(
        self,
        source,
        remaining,
        sorted_items,
        starts,
        index_by_identity,
        max_radius_nm,
        max_item_width_nm=None,
    ):
        max_gap_nm = self._item_radius_nm(source) + max_radius_nm
        for candidate in nearby_items(source, sorted_items, starts, max_gap_nm, max_item_width_nm):
            candidate_index = index_by_identity.get(id(candidate))
            if candidate_index in remaining:
                yield candidate_index

    def _items_connected(self, left, right):
        if not self._can_connect(left, right):
            return False
        if not bbox_near(
            left.bbox_nm,
            right.bbox_nm,
            self._item_radius_nm(left) + self._item_radius_nm(right),
        ):
            return False
        if left.zone_polygons_nm:
            return self._item_touches_filled_zone(right, left)
        if right.zone_polygons_nm:
            return self._item_touches_filled_zone(left, right)
        left_segments = self._track_segments(left)
        right_segments = self._track_segments(right)
        if left_segments and right_segments:
            return min(
                segment_distance(left_segment, right_segment)
                for left_segment in left_segments
                for right_segment in right_segments
            ) <= (left.width_nm + right.width_nm) / 2.0
        if left_segments and self._is_non_round_pad(right):
            return min(
                bbox_to_segment_distance(right.bbox_nm, segment)
                for segment in left_segments
            ) <= left.width_nm / 2.0
        if right_segments and self._is_non_round_pad(left):
            return min(
                bbox_to_segment_distance(left.bbox_nm, segment)
                for segment in right_segments
            ) <= right.width_nm / 2.0
        if left_segments and right.center_nm is not None:
            return self._point_touches_item(right.center_nm, self._item_radius_nm(right), left)
        if right_segments and left.center_nm is not None:
            return self._point_touches_item(left.center_nm, self._item_radius_nm(left), right)
        if left.bbox_nm and right_segments:
            return any(
                segment_intersects_bbox(segment, left.bbox_nm)
                for segment in right_segments
            )
        if right.bbox_nm and left_segments:
            return any(
                segment_intersects_bbox(segment, right.bbox_nm)
                for segment in left_segments
            )
        if left.bbox_nm and right.bbox_nm and (self._is_non_round_pad(left) or self._is_non_round_pad(right)):
            return bbox_near(left.bbox_nm, right.bbox_nm, 0)
        if left.center_nm is not None and right.center_nm is not None:
            return point_distance(left.center_nm, right.center_nm) <= self._item_radius_nm(left) + self._item_radius_nm(right)
        if left.bbox_nm and right.center_nm is not None:
            return point_in_bbox(right.center_nm, left.bbox_nm)
        if right.bbox_nm and left.center_nm is not None:
            return point_in_bbox(left.center_nm, right.bbox_nm)
        return bbox_near(left.bbox_nm, right.bbox_nm, 0)

    def _item_touches_filled_zone(self, item, zone):
        polygons = zone.zone_polygons_nm
        if not polygons:
            return False
        # The raw KiCad zone may span several copper layers.  Its effective
        # shape is not a reliable substitute for this clone's actual filled
        # polygon, even when a layer argument is supplied (pads, tracks, and
        # zone-to-zone joins all have observed false results).  Keep the
        # per-layer fill geometry authoritative here.
        if item.zone_polygons_nm:
            return filled_polygons_distance(item.zone_polygons_nm, polygons) <= 0
        track_segments = self._track_segments(item)
        if track_segments:
            return min(
                segment_to_filled_polygons_distance(segment, polygons)
                for segment in track_segments
            ) <= item.width_nm / 2.0
        if item.center_nm is not None and not self._is_non_round_pad(item):
            return (
                self._point_to_zone_distance_nm(item.center_nm, zone)
                <= self._item_radius_nm(item)
            )
        if item.bbox_nm:
            return bbox_to_filled_polygons_distance(item.bbox_nm, polygons) <= 0
        return False

    def _item_radius_nm(self, indexed):
        if indexed.pad_radius_nm:
            return indexed.pad_radius_nm
        if indexed.width_nm:
            return indexed.width_nm / 2.0
        if indexed.hole_radius_nm:
            return indexed.hole_radius_nm
        return 0.0

    def _component_gap_mm(self, left_component, right_component):
        minimum = None
        for left in left_component:
            for right in right_component:
                gap = bbox_gap(left.bbox_nm, right.bbox_nm)
                if minimum is None or gap < minimum:
                    minimum = gap
        return round((minimum or 0.0) / NM_PER_MM, 6)

    def _zone_connected_to_copper(self, zone):
        for candidate in self._connection_candidates(zone, max_gap_nm=0):
            if self._same_indexed_item(candidate, zone):
                continue
            if not self._can_connect(zone, candidate):
                continue
            if not bbox_near(zone.bbox_nm, candidate.bbox_nm, 0):
                continue
            if self._items_connected(zone, candidate):
                return True
        return False

    def _track_segments(self, indexed):
        path = tuple(indexed.track_path_nm or ())
        if len(path) >= 2:
            return tuple(zip(path, path[1:]))
        if indexed.segment_nm and not str(indexed.geometry_basis).startswith(
            "kicad_arc_"
        ):
            return (indexed.segment_nm,)
        return ()

    def _track_endpoints(self, indexed):
        if indexed.segment_nm:
            return indexed.segment_nm[0], indexed.segment_nm[1]
        path = tuple(indexed.track_path_nm or ())
        if len(path) >= 2:
            return path[0], path[-1]
        return ()

    def _track_vector_from_endpoint(self, indexed, point, tolerance_nm):
        endpoints = self._track_endpoints(indexed)
        if not endpoints:
            return None
        distances = tuple(point_distance(endpoint, point) for endpoint in endpoints)
        endpoint_index = 0 if distances[0] <= distances[1] else 1
        if distances[endpoint_index] > tolerance_nm:
            return None
        vectors = tuple(indexed.track_endpoint_vectors_nm or ())
        if len(vectors) == 2:
            return vectors[endpoint_index]
        segments = self._track_segments(indexed)
        if not segments:
            return None
        segment = segments[0] if endpoint_index == 0 else segments[-1]
        return segment_vector_from_point(segment, point)

    def _point_touches_item(self, point, radius_nm, indexed):
        if indexed.is_zone:
            if not indexed.zone_polygons_nm:
                return False
            return self._point_to_zone_distance_nm(point, indexed) <= radius_nm
        track_segments = self._track_segments(indexed)
        if track_segments:
            return min(
                point_segment_distance(point, segment)
                for segment in track_segments
            ) <= radius_nm + indexed.width_nm / 2.0
        if indexed.center_nm is not None and indexed.pad_radius_nm:
            if not self._is_round_pad(indexed):
                return point_to_bbox_distance(point, indexed.bbox_nm) <= radius_nm
            return point_distance(point, indexed.center_nm) <= radius_nm + indexed.pad_radius_nm
        if indexed.center_nm is not None and indexed.width_nm:
            return point_distance(point, indexed.center_nm) <= radius_nm + indexed.width_nm / 2.0
        return point_in_bbox(point, indexed.bbox_nm)

    def _connected_track_junction(self, left, right):
        left_endpoints = self._track_endpoints(left)
        right_endpoints = self._track_endpoints(right)
        if not left_endpoints or not right_endpoints:
            return None
        shared = shared_segment_endpoint(
            left_endpoints,
            right_endpoints,
            ACUTE_ENDPOINT_TOLERANCE_NM,
        )
        if shared is None:
            return None
        left_vector = self._track_vector_from_endpoint(
            left,
            shared,
            ACUTE_ENDPOINT_TOLERANCE_NM,
        )
        right_vector = self._track_vector_from_endpoint(
            right,
            shared,
            ACUTE_ENDPOINT_TOLERANCE_NM,
        )
        if left_vector is None or right_vector is None:
            return None
        angle = vector_angle_degrees(left_vector, right_vector)
        if angle is None:
            return None
        return shared, angle

    def _connected_track_angle_degrees(self, left, right):
        junction = self._connected_track_junction(left, right)
        return junction[1] if junction is not None else None

    def _acute_junction_is_exposed(self, left, right, shared):
        source = GeometryCandidate(
            indexed=left,
            bbox_nm=(shared[0], shared[1], shared[0], shared[1]),
        )
        candidates = self._connection_candidates(source, max_gap_nm=0)
        teardrop_candidates = nearby_items(
            source,
            self.index.acute_cover_items,
            self.index.acute_cover_x_starts,
            0,
            self.index.acute_cover_max_width,
        )
        for candidate in tuple(candidates) + tuple(teardrop_candidates):
            if self._same_indexed_item(candidate, left) or self._same_indexed_item(
                candidate,
                right,
            ):
                continue
            if (
                not candidate.net_name
                or candidate.net_name != left.net_name
            ):
                continue
            if not self._can_connect(left, candidate):
                continue
            if not point_near_bbox(shared, candidate.bbox_nm, 0):
                continue
            if self._point_touches_item(shared, 0, candidate):
                return False
        return True

    def _track_to_track_gap_mm(self, left, right):
        left_segments = self._track_segments(left)
        right_segments = self._track_segments(right)
        if not left_segments or not right_segments:
            return None
        width = (left.width_nm + right.width_nm) / 2.0
        distance = min(
            segment_distance(left_segment, right_segment)
            for left_segment in left_segments
            for right_segment in right_segments
        )
        return round(max(0.0, distance - width) / NM_PER_MM, 6)

    def _track_to_pad_gap_mm(self, track, pad):
        segments = self._track_segments(track)
        center = pad.center_nm
        if not segments or center is None:
            return None
        exact = self._native_item_clearance_nm(track, pad)
        if exact is not None:
            return round(exact / NM_PER_MM, 6)
        track_radius = track.width_nm / 2.0
        if self._is_round_pad(pad):
            distance = min(
                point_segment_distance(center, segment) for segment in segments
            ) - pad.pad_radius_nm - track_radius
        else:
            distance = min(
                bbox_to_segment_distance(pad.bbox_nm, segment)
                for segment in segments
            ) - track_radius
        return round(max(0.0, distance) / NM_PER_MM, 6)

    def _pad_to_pad_gap_mm(self, left, right):
        left_center = left.center_nm
        right_center = right.center_nm
        if left_center is None or right_center is None:
            return None
        exact = self._native_item_clearance_nm(left, right)
        if exact is not None:
            return round(exact / NM_PER_MM, 6)
        if self._is_round_pad(left) and self._is_round_pad(right):
            distance = point_distance(left_center, right_center) - left.pad_radius_nm - right.pad_radius_nm
        elif self._is_round_pad(left):
            distance = point_to_bbox_distance(left_center, right.bbox_nm) - left.pad_radius_nm
        elif self._is_round_pad(right):
            distance = point_to_bbox_distance(right_center, left.bbox_nm) - right.pad_radius_nm
        else:
            distance = bbox_gap(left.bbox_nm, right.bbox_nm)
        return round(max(0.0, distance) / NM_PER_MM, 6)

    def _native_item_clearance_nm(self, left, right):
        clearance = getattr(self.backend, "item_clearance_nm", None)
        if clearance is None:
            return None
        return clearance(
            left.item,
            right.item,
            ZONE_DISTANCE_SEARCH_NM,
        )

    def _is_round_pad(self, pad):
        if pad.pad_shape is None:
            return True
        shape = int(pad.pad_shape)
        if shape == 0:
            return True
        # KiCad represents many circular THT pads as OVAL.  When both axes
        # are equal the effective copper is still a circle; treating it as
        # its bounding square underestimates plane clearance at corners.
        if shape == 2 and pad.pad_size_mm:
            return abs(abs(pad.pad_size_mm[0]) - abs(pad.pad_size_mm[1])) <= 1e-9
        return False

    def _is_non_round_pad(self, indexed):
        return bool(indexed.pad_radius_nm and not self._is_round_pad(indexed))

    def _track_to_outline_gap_mm(self, track, outline_segments):
        segments = self._track_segments(track)
        if not segments or not outline_segments:
            return None
        width = track.width_nm / 2.0
        distance = min(
            segment_distance(segment, edge)
            for segment in segments
            for edge in outline_segments
        )
        return round(max(0.0, distance - width) / NM_PER_MM, 6)

    def _pad_to_outline_gap_mm(
        self,
        pad,
        outline_segments,
        max_gap_nm=ZONE_DISTANCE_SEARCH_NM,
    ):
        center = pad.center_nm
        if center is None or not outline_segments:
            return None
        if self._is_round_pad(pad):
            radius = pad.pad_radius_nm
            distance = min(point_segment_distance(center, edge) for edge in outline_segments) - radius
        else:
            exact_clearance = getattr(
                self.backend,
                "item_to_segment_clearance_nm",
                None,
            )
            if exact_clearance is not None:
                distances = []
                for edge in outline_segments:
                    try:
                        clearance = exact_clearance(
                            pad.item,
                            edge,
                            pad.layer_id,
                            max_gap_nm,
                        )
                    except Exception:
                        clearance = None
                    if clearance is not None:
                        distances.append(clearance)
                if distances:
                    return round(
                        max(0.0, min(distances)) / NM_PER_MM,
                        6,
                    )
            distance = min(bbox_to_segment_distance(pad.bbox_nm, edge) for edge in outline_segments)
        return round(max(0.0, distance) / NM_PER_MM, 6)

    def _via_to_outline_gap_mm(self, via, outline_segments):
        center = via.center_nm
        if center is None or not outline_segments:
            return None
        radius = via.width_nm / 2.0
        distance = min(point_segment_distance(center, edge) for edge in outline_segments) - radius
        return round(max(0.0, distance) / NM_PER_MM, 6)

    def _hole_to_outline_gap_mm(
        self,
        hole,
        outline_segments,
        max_gap_nm=ZONE_DISTANCE_SEARCH_NM,
    ):
        if hole.center_nm is None or not outline_segments:
            return None
        exact_clearance = getattr(
            self.backend,
            "hole_to_segment_clearance_nm",
            None,
        )
        if exact_clearance is not None:
            distances = []
            for edge in outline_segments:
                try:
                    clearance = exact_clearance(
                        hole.item,
                        edge,
                        max_gap_nm,
                    )
                except Exception:
                    clearance = None
                if clearance is not None:
                    distances.append(clearance)
            if distances:
                return round(max(0.0, min(distances)) / NM_PER_MM, 6)

        slot_segment, slot_radius = self._slot_drill_segment_nm(hole)
        if slot_segment is not None:
            distance = min(
                segment_distance(slot_segment, edge)
                for edge in outline_segments
            ) - slot_radius
        elif hole.is_round_drill:
            distance = min(
                point_segment_distance(hole.center_nm, edge)
                for edge in outline_segments
            ) - hole.hole_radius_nm
        else:
            bbox = self._hole_bbox_nm(hole)
            if bbox is None:
                return None
            distance = min(
                bbox_to_segment_distance(bbox, edge)
                for edge in outline_segments
            )
        return round(max(0.0, distance) / NM_PER_MM, 6)

    def _bbox_to_outline_gap_mm(
        self,
        indexed,
        outline_segments,
        max_gap_nm=ZONE_DISTANCE_SEARCH_NM,
    ):
        bbox = indexed.bbox_nm
        if bbox is None or not outline_segments:
            return None
        if indexed.zone_polygons_nm and indexed.zone_edges_nm:
            minimum = None
            for outline_segment in outline_segments:
                zone_edges = self._near_zone_edges(
                    indexed,
                    segment_bbox_nm(outline_segment),
                    max_gap_nm,
                )
                for zone_edge in zone_edges:
                    distance = segment_distance(
                        outline_segment,
                        zone_edge,
                    )
                    if minimum is None or distance < minimum:
                        minimum = distance
            if minimum is not None:
                return round(max(0.0, minimum) / NM_PER_MM, 6)
            # A very large filled zone can contain an entire outline contour
            # without putting its own boundary inside the reporting window.
            # Check containment only for that uncommon no-near-edge case;
            # doing a polygon test for every tessellated outline point makes
            # normal curved boards needlessly expensive.
            for outline_segment in outline_segments:
                for point in outline_segment:
                    if point_in_bbox(point, bbox) and self._zone_contains_point(
                        indexed,
                        point,
                    ):
                        return 0.0
            # No filled-zone boundary lies within the reporting window.  The
            # zone bounding box may still be close to the outline while its
            # actual copper is not, so a bbox fallback would be a false hit.
            return None
        distance = min(bbox_to_segment_distance(bbox, edge) for edge in outline_segments)
        return round(max(0.0, distance) / NM_PER_MM, 6)

    def _point_to_track_edge_mm(self, point, radius_nm, track):
        segments = self._track_segments(track)
        if not segments:
            return None
        distance = min(
            point_segment_distance(point, segment) for segment in segments
        )
        return round(max(0.0, distance - radius_nm - track.width_nm / 2.0) / NM_PER_MM, 6)

    def _point_to_copper_gap_mm(self, point, radius_nm, copper):
        if self._track_segments(copper):
            return self._point_to_track_edge_mm(point, radius_nm, copper)
        if copper.pad_radius_nm:
            if self._is_round_pad(copper):
                distance = point_distance(point, copper.center_nm) - radius_nm - copper.pad_radius_nm
            else:
                distance = point_to_bbox_distance(point, copper.bbox_nm) - radius_nm
            return round(max(0.0, distance) / NM_PER_MM, 6)
        if copper.bbox_nm:
            if copper.zone_polygons_nm:
                distance = (
                    self._point_to_zone_distance_nm(point, copper)
                    - radius_nm
                )
                return round(max(0.0, distance) / NM_PER_MM, 6)
            distance = point_to_bbox_distance(point, copper.bbox_nm) - radius_nm
            return round(max(0.0, distance) / NM_PER_MM, 6)
        return None

    def _zone_contains_point(self, zone, point):
        contains = getattr(self.backend, "zone_contains_point", None)
        if contains is not None:
            result = contains(zone.item, point, zone.layer_id)
            if result is not None:
                return bool(result)
        return point_in_filled_polygons(point, zone.zone_polygons_nm)

    def _near_zone_edges(
        self,
        zone,
        bbox,
        max_gap_nm=ZONE_DISTANCE_SEARCH_NM,
    ):
        edges = zone.zone_edges_nm
        starts = zone.zone_edge_x_starts
        if not edges or bbox is None:
            return edges
        if zone.zone_edge_buckets:
            first_bucket = math.floor(
                (bbox[0] - max_gap_nm) / ZONE_EDGE_BUCKET_NM
            )
            last_bucket = math.floor(
                (bbox[2] + max_gap_nm) / ZONE_EDGE_BUCKET_NM
            )
            candidates = {
                edge
                for bucket in range(first_bucket, last_bucket + 1)
                for edge in zone.zone_edge_buckets.get(bucket, ())
            }
            return tuple(
                edge
                for edge in candidates
                if bbox_near(
                    bbox,
                    segment_bbox_nm(edge),
                    max_gap_nm,
                )
            )
        start_index = bisect.bisect_left(
            starts,
            bbox[0] - max_gap_nm - zone.zone_edge_max_width,
        )
        max_x = bbox[2] + max_gap_nm
        result = []
        for edge in edges[start_index:]:
            edge_bbox = segment_bbox_nm(edge)
            if edge_bbox[0] > max_x:
                break
            if bbox_near(bbox, edge_bbox, max_gap_nm):
                result.append(edge)
        return tuple(result)

    def _point_to_zone_distance_nm(self, point, zone):
        native_distance = self._native_zone_point_distance_nm(zone, point)
        if native_distance is not None:
            return native_distance
        if self._zone_contains_point(zone, point):
            return 0.0
        bbox = (point[0], point[1], point[0], point[1])
        edges = self._near_zone_edges(zone, bbox)
        if not edges:
            return ZONE_DISTANCE_SEARCH_NM
        return min(point_segment_distance(point, edge) for edge in edges)

    def _native_zone_point_distance_nm(self, zone, point):
        distance = getattr(self.backend, "zone_point_distance_nm", None)
        if distance is None:
            return None
        return distance(zone.item, point, zone.layer_id)

    def _hole_to_copper_gap_mm(self, hole, hole_candidate, center, radius_nm, copper):
        if hole.is_round_drill or hole_candidate.bbox_nm is None:
            return self._point_to_copper_gap_mm(center, radius_nm, copper)
        copper_segments = self._track_segments(copper)
        if copper_segments:
            slot_segment, slot_radius = self._slot_drill_segment_nm(hole)
            if slot_segment is not None:
                distance = min(
                    segment_distance(slot_segment, copper_segment)
                    for copper_segment in copper_segments
                ) - slot_radius - copper.width_nm / 2.0
            else:
                distance = min(
                    bbox_to_segment_distance(
                        hole_candidate.bbox_nm, copper_segment
                    )
                    for copper_segment in copper_segments
                ) - copper.width_nm / 2.0
        elif copper.pad_radius_nm and self._is_round_pad(copper):
            slot_segment, slot_radius = self._slot_drill_segment_nm(hole)
            if slot_segment is not None:
                distance = point_segment_distance(copper.center_nm, slot_segment) - slot_radius - copper.pad_radius_nm
            else:
                distance = point_to_bbox_distance(copper.center_nm, hole_candidate.bbox_nm) - copper.pad_radius_nm
        elif copper.bbox_nm:
            distance = bbox_gap(hole_candidate.bbox_nm, copper.bbox_nm)
        else:
            return self._point_to_copper_gap_mm(center, radius_nm, copper)
        return round(max(0.0, distance) / NM_PER_MM, 6)

    def _hole_pad_overlap_mm(self, hole, hole_candidate, center, radius_nm, pad):
        native_overlap = self._native_hole_pad_overlap_nm(hole, pad)
        if native_overlap is not None:
            return round(max(0.0, native_overlap) / NM_PER_MM, 6)
        if hole.is_round_drill or hole_candidate.bbox_nm is None:
            return self._circle_pad_overlap_mm(center, radius_nm, pad)
        if self._is_round_pad(pad):
            slot_segment, slot_radius = self._slot_drill_segment_nm(hole)
            if slot_segment is not None:
                overlap = slot_radius + pad.pad_radius_nm - point_segment_distance(pad.center_nm, slot_segment)
            else:
                overlap = pad.pad_radius_nm - point_to_bbox_distance(pad.center_nm, hole_candidate.bbox_nm)
        else:
            overlap = bbox_overlap_depth(hole_candidate.bbox_nm, pad.bbox_nm)
        return round(max(0.0, overlap) / NM_PER_MM, 6)

    def _native_hole_pad_overlap_nm(self, hole, pad):
        overlap = getattr(self.backend, "hole_pad_overlap_nm", None)
        if overlap is None:
            return None
        return overlap(hole.item, pad.item, pad.layer_id)

    def _hole_axis_on_pad(self, hole, center, pad):
        native_check = getattr(self.backend, "hole_axis_on_pad", None)
        if native_check is not None:
            result = native_check(hole.item, pad.item, pad.layer_id)
            if result is not None:
                return bool(result)
        slot_segment, _slot_radius = self._slot_drill_segment_nm(hole)
        if slot_segment is not None:
            if self._is_round_pad(pad):
                return (
                    point_segment_distance(pad.center_nm, slot_segment)
                    <= pad.pad_radius_nm
                )
            return bool(
                pad.bbox_nm
                and segment_intersects_bbox(slot_segment, pad.bbox_nm)
            )
        if self._is_round_pad(pad):
            return point_distance(center, pad.center_nm) <= pad.pad_radius_nm
        return bool(pad.bbox_nm and point_in_bbox(center, pad.bbox_nm))

    def _hole_pad_overlap_ratio(self, overlap_mm, radius_nm, center=None, pad=None):
        diameter_mm = 2.0 * float(radius_nm or 0.0) / NM_PER_MM
        if diameter_mm <= 0:
            return 0.0
        penetration_mm = float(overlap_mm)
        if (
            center is not None
            and pad is not None
            and pad.bbox_nm is not None
            and not self._is_round_pad(pad)
            and point_in_bbox(center, pad.bbox_nm)
        ):
            left, top, right, bottom = pad.bbox_nm
            interior_depth_nm = min(
                center[0] - left,
                right - center[0],
                center[1] - top,
                bottom - center[1],
            )
            penetration_mm = (float(radius_nm) + max(0.0, interior_depth_nm)) / NM_PER_MM
        return round(min(1.0, max(0.0, penetration_mm / diameter_mm)), 6)

    def _uses_remote_holes_contract(self):
        return self._uses_remote_contract()

    def _uses_remote_contract(self):
        rule = self._rule_for("Holes on SMD Pads", "Via on SMD Pad")
        return str(rule) == "0.004000,0.001000,0.000000"

    def _is_outer_copper(self, indexed):
        layer_id = indexed.layer_id
        outer_ids = {
            self.backend.layer_id(layer_name)
            for layer_name in ("F.Cu", "B.Cu")
            if hasattr(self.backend, "layer_id")
        }
        outer_ids = {
            int(value)
            for value in outer_ids
            if value is not None and int(value) >= 0
        }
        if not outer_ids:
            return indexed.layer_name in ("F.Cu", "B.Cu")
        try:
            return int(layer_id) in outer_ids
        except (TypeError, ValueError):
            return indexed.layer_name in ("F.Cu", "B.Cu")

    def _circle_pad_overlap_mm(self, center, radius_nm, pad):
        pad_center = pad.center_nm
        if pad_center is None:
            return 0
        if self._is_round_pad(pad):
            overlap = radius_nm + pad.pad_radius_nm - point_distance(center, pad_center)
        else:
            overlap = radius_nm - point_to_bbox_distance(center, pad.bbox_nm)
        return round(max(0.0, overlap) / NM_PER_MM, 6)

    def tr(self, value):
        return self.language.get(value) or self.language.get(str(value).lower(), value)


def aggregate_color(have_red, have_yellow):
    if have_red:
        return "red"
    if have_yellow:
        return "gold"
    return "black"


def update_color_flags(color, have_red, have_yellow):
    if color == "red":
        have_red = True
    elif color == "gold":
        have_yellow = True
    return have_red, have_yellow


def sort_indexed_items(groups):
    for key, items in list(groups.items()):
        groups[key] = tuple(sorted(items, key=index_sort_key))


def index_sort_key(item):
    if item.bbox_nm is None:
        return 0
    return item.bbox_nm[0]


def stable_indexed_item_key(item):
    bbox = (
        tuple(item.bbox_nm)
        if item.bbox_nm is not None
        else (float("inf"),) * 4
    )
    return (
        bbox,
        str(item.layer_name or ""),
        str(item.item_id or ""),
        str(item.item_type or ""),
    )


def stable_component_key(component):
    return min(stable_indexed_item_key(item) for item in component)


def color_to_severity(color):
    if color == "red":
        return "error"
    if color == "gold":
        return "warning"
    return "ok"


def is_inner_copper_layer(layer_name):
    return str(layer_name or "").startswith("In") and str(layer_name or "").endswith(".Cu")


def copper_layer_side(layer_name):
    value = str(layer_name or "")
    if value == "F.Cu":
        return "F"
    if value == "B.Cu":
        return "B"
    return ""


def mask_layer_side(layer_name):
    value = str(layer_name or "")
    if value in ("F.Mask", "F_Mask"):
        return "F"
    if value in ("B.Mask", "B_Mask"):
        return "B"
    return ""


def pairwise_candidates(items, max_gap_nm=None):
    items = tuple(items)
    if max_gap_nm is not None and all(item.bbox_nm is not None for item in items):
        items = tuple(sorted(items, key=lambda item: item.bbox_nm[0]))
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            if (
                max_gap_nm is not None
                and left.bbox_nm is not None
                and right.bbox_nm is not None
                and right.bbox_nm[0] - left.bbox_nm[2] > max_gap_nm
            ):
                break
            if max_gap_nm is not None and not bbox_near(left.bbox_nm, right.bbox_nm, max_gap_nm):
                continue
            yield left, right


def y_near_pairwise_candidates(items, max_gap_nm):
    items = tuple(sorted(items, key=lambda item: item.bbox_nm[1] if item.bbox_nm else 0))
    for index, left in enumerate(items):
        if left.bbox_nm is None:
            for right in items[index + 1:]:
                yield left, right
            continue
        max_y = left.bbox_nm[3] + max_gap_nm
        for right in items[index + 1:]:
            if right.bbox_nm is not None and right.bbox_nm[1] > max_y:
                break
            if bbox_near(left.bbox_nm, right.bbox_nm, max_gap_nm):
                yield left, right


def nearby_items(target, items, starts, max_gap_nm, max_item_width_nm=None):
    if target.bbox_nm is None or not starts:
        for item in items:
            yield item
        return
    if max_item_width_nm is None:
        max_item_width_nm = max_bbox_width_nm(items)
    start_index = bisect.bisect_left(starts, target.bbox_nm[0] - max_gap_nm - max_item_width_nm)
    max_x = target.bbox_nm[2] + max_gap_nm
    for item in items[start_index:]:
        if item.bbox_nm is not None and item.bbox_nm[0] > max_x:
            break
        yield item


def within_bbox_gap(left, right, max_gap_nm):
    if left.bbox_nm is None or right.bbox_nm is None:
        return True
    return bbox_near(left.bbox_nm, right.bbox_nm, max_gap_nm)


def bbox_near(left, right, max_gap_nm):
    if left is None or right is None:
        return True
    return (
        left[0] - right[2] <= max_gap_nm
        and right[0] - left[2] <= max_gap_nm
        and left[1] - right[3] <= max_gap_nm
        and right[1] - left[3] <= max_gap_nm
    )


def bbox_gap(left, right):
    left_x = max(0, max(left[0] - right[2], right[0] - left[2]))
    left_y = max(0, max(left[1] - right[3], right[1] - left[3]))
    return math.hypot(left_x, left_y)


def connected_bbox_components(items):
    remaining = [item for item in items if item.bbox_nm is not None]
    while remaining:
        component = [remaining.pop()]
        index = 0
        while index < len(component):
            current = component[index]
            connected = [
                candidate
                for candidate in remaining
                if bbox_near(current.bbox_nm, candidate.bbox_nm, 0)
            ]
            for candidate in connected:
                remaining.remove(candidate)
                component.append(candidate)
            index += 1
        yield tuple(component)


def bbox_component_gap(left, right):
    return min(
        (
            (bbox_gap(left_item.bbox_nm, right_item.bbox_nm), left_item, right_item)
            for left_item in left
            for right_item in right
        ),
        key=lambda result: result[0],
    )


def bbox_for_indexed_items(items):
    boxes = [item.bbox_nm for item in items if item.bbox_nm is not None]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def bbox_overlap_depth(left, right):
    if left is None or right is None:
        return 0.0
    overlap_x = min(left[2], right[2]) - max(left[0], right[0])
    overlap_y = min(left[3], right[3]) - max(left[1], right[1])
    if overlap_x <= 0 or overlap_y <= 0:
        return 0.0
    return min(overlap_x, overlap_y)


def max_bbox_width_nm(items):
    return max((item.bbox_nm[2] - item.bbox_nm[0] for item in items if item.bbox_nm is not None), default=0)


def max_bbox_width_from_bboxes(bboxes):
    return max((bbox[2] - bbox[0] for bbox in bboxes if bbox is not None), default=0)


def bbox_overlaps_area(left, right):
    if left is None or right is None:
        return False
    return min(left[2], right[2]) > max(left[0], right[0]) and min(left[3], right[3]) > max(left[1], right[1])


def point_to_bbox_distance(point, bbox):
    if point is None or bbox is None:
        return 0.0
    gap_x = max(0, bbox[0] - point[0], point[0] - bbox[2])
    gap_y = max(0, bbox[1] - point[1], point[1] - bbox[3])
    return math.hypot(gap_x, gap_y)


def bbox_to_segment_distance(bbox, segment):
    if bbox is None or segment is None:
        return 0.0
    if segment_intersects_bbox(segment, bbox):
        return 0.0
    left, top, right, bottom = bbox
    edges = (
        ((left, top), (right, top)),
        ((right, top), (right, bottom)),
        ((right, bottom), (left, bottom)),
        ((left, bottom), (left, top)),
    )
    return min(segment_distance(segment, edge) for edge in edges)


def bbox_for_segments(segments):
    points = [point for segment in segments for point in segment if point is not None]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def segment_bbox_nm(segment):
    return (
        min(segment[0][0], segment[1][0]),
        min(segment[0][1], segment[1][1]),
        max(segment[0][0], segment[1][0]),
        max(segment[0][1], segment[1][1]),
    )


def near_bbox_edge(item_bbox, outline_bbox, max_gap_nm):
    if item_bbox is None or outline_bbox is None:
        return True
    left, top, right, bottom = item_bbox
    board_left, board_top, board_right, board_bottom = outline_bbox
    return (
        left - board_left <= max_gap_nm
        or board_right - right <= max_gap_nm
        or top - board_top <= max_gap_nm
        or board_bottom - bottom <= max_gap_nm
    )


def point_in_bbox(point, bbox):
    if point is None or bbox is None:
        return False
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def polygon_edges(points):
    points = tuple(points or ())
    if len(points) < 2:
        return ()
    return tuple(zip(points, points[1:] + points[:1]))


def filled_polygon_edges(polygons):
    return tuple(
        edge
        for outer, holes in polygons or ()
        for contour in (outer,) + tuple(holes or ())
        for edge in polygon_edges(contour)
    )


def filled_polygon_bbox(polygon):
    outer, _holes = polygon
    points = tuple(outer or ())
    if not points:
        return None
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def filled_polygon_components(polygons):
    polygons = tuple(polygons or ())
    if not polygons:
        return ()
    bboxes = tuple(filled_polygon_bbox(polygon) for polygon in polygons)
    parents = list(range(len(polygons)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def join(left, right):
        left_root = root(left)
        right_root = root(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left_index, left in enumerate(polygons):
        left_bbox = bboxes[left_index]
        if left_bbox is None:
            continue
        for right_index in range(left_index + 1, len(polygons)):
            right_bbox = bboxes[right_index]
            if right_bbox is None or not bbox_near(left_bbox, right_bbox, 0):
                continue
            if filled_polygons_distance((left,), (polygons[right_index],)) <= 0:
                join(left_index, right_index)
    components = {}
    for index in range(len(polygons)):
        components.setdefault(root(index), []).append(index)
    return tuple(tuple(component) for component in components.values())


def stroke_bbox(stroke):
    start, end, width = stroke
    radius = float(width or 0.0) / 2.0
    return (
        min(start[0], end[0]) - radius,
        min(start[1], end[1]) - radius,
        max(start[0], end[0]) + radius,
        max(start[1], end[1]) + radius,
    )


def stroke_components(strokes):
    strokes = tuple(strokes or ())
    if not strokes:
        return ()
    parents = list(range(len(strokes)))
    bboxes = tuple(stroke_bbox(stroke) for stroke in strokes)

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def join(left, right):
        left_root = root(left)
        right_root = root(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left_index, left in enumerate(strokes):
        for right_index in range(left_index + 1, len(strokes)):
            if not bbox_near(bboxes[left_index], bboxes[right_index], 0):
                continue
            right = strokes[right_index]
            if (
                segment_distance(
                    (left[0], left[1]),
                    (right[0], right[1]),
                )
                <= (left[2] + right[2]) / 2.0
            ):
                join(left_index, right_index)
    components = {}
    for index in range(len(strokes)):
        components.setdefault(root(index), []).append(index)
    return tuple(tuple(component) for component in components.values())


def acute_stroke_indexes(strokes):
    strokes = tuple(strokes or ())
    endpoints = {}
    for index, (start, end, _width) in enumerate(strokes):
        endpoints.setdefault(start, []).append(index)
        endpoints.setdefault(end, []).append(index)
    selected = []
    seen = set()
    for shared, indexes in endpoints.items():
        for offset, left_index in enumerate(indexes):
            left = strokes[left_index]
            left_vector = segment_vector_from_point(
                (left[0], left[1]),
                shared,
            )
            for right_index in indexes[offset + 1:]:
                right = strokes[right_index]
                right_vector = segment_vector_from_point(
                    (right[0], right[1]),
                    shared,
                )
                if vector_angle_degrees(left_vector, right_vector) >= 89.0:
                    continue
                for index in (left_index, right_index):
                    if index not in seen:
                        seen.add(index)
                        selected.append(index)
    return tuple(selected)


def point_bbox(point):
    return (point[0], point[1], point[0], point[1])


def acute_polygon_vertices(points):
    points = tuple(points or ())
    if len(points) < 3:
        return ()
    results = []
    for index, current in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % len(points)]
        left = (previous[0] - current[0], previous[1] - current[1])
        right = (following[0] - current[0], following[1] - current[1])
        left_length = math.hypot(*left)
        right_length = math.hypot(*right)
        if left_length <= 0 or right_length <= 0:
            continue
        cosine = max(
            -1.0,
            min(
                1.0,
                (left[0] * right[0] + left[1] * right[1])
                / (left_length * right_length),
            ),
        )
        angle = math.degrees(math.acos(cosine))
        if angle < 90.0 - ACUTE_ANGLE_TOLERANCE_DEGREES:
            results.append(current)
    return tuple(results)


def point_on_segment(point, segment, tolerance=1e-6):
    start, end = segment
    if point_segment_distance(point, segment) > tolerance:
        return False
    return (
        min(start[0], end[0]) - tolerance
        <= point[0]
        <= max(start[0], end[0]) + tolerance
        and min(start[1], end[1]) - tolerance
        <= point[1]
        <= max(start[1], end[1]) + tolerance
    )


def point_in_polygon(point, polygon):
    polygon = tuple(polygon or ())
    if len(polygon) < 3:
        return False
    if any(point_on_segment(point, edge) for edge in polygon_edges(polygon)):
        return True
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) * (x2 - x1) / float(y2 - y1)
            if crossing_x > x:
                inside = not inside
        previous = current
    return inside


def point_in_filled_polygons(point, polygons):
    return any(
        point_in_polygon(point, outer)
        and not any(point_in_polygon(point, hole) for hole in holes or ())
        for outer, holes in polygons or ()
    )


def point_to_filled_polygons_distance(point, polygons):
    if point_in_filled_polygons(point, polygons):
        return 0.0
    edges = filled_polygon_edges(polygons)
    if not edges:
        return math.inf
    return min(point_segment_distance(point, edge) for edge in edges)


def segment_to_filled_polygons_distance(segment, polygons):
    if (
        point_in_filled_polygons(segment[0], polygons)
        or point_in_filled_polygons(segment[1], polygons)
    ):
        return 0.0
    edges = filled_polygon_edges(polygons)
    if not edges:
        return math.inf
    return min(segment_distance(segment, edge) for edge in edges)


def bbox_to_filled_polygons_distance(bbox, polygons):
    if bbox is None:
        return math.inf
    left, top, right, bottom = bbox
    bbox_edges = (
        ((left, top), (right, top)),
        ((right, top), (right, bottom)),
        ((right, bottom), (left, bottom)),
        ((left, bottom), (left, top)),
    )
    if any(
        point_in_filled_polygons(point, polygons)
        for point in ((left, top), (right, top), (right, bottom), (left, bottom))
    ):
        return 0.0
    zone_edges = filled_polygon_edges(polygons)
    if any(point_in_bbox(point, bbox) for edge in zone_edges for point in edge):
        return 0.0
    return min(
        segment_distance(bbox_edge, zone_edge)
        for bbox_edge in bbox_edges
        for zone_edge in zone_edges
    ) if zone_edges else math.inf


def filled_polygons_distance(left, right):
    left_edges = filled_polygon_edges(left)
    right_edges = filled_polygon_edges(right)
    if not left_edges or not right_edges:
        return math.inf
    if any(
        point_in_filled_polygons(point, right)
        for outer, _holes in left or ()
        for point in outer
    ):
        return 0.0
    if any(
        point_in_filled_polygons(point, left)
        for outer, _holes in right or ()
        for point in outer
    ):
        return 0.0
    return min(
        segment_distance(left_edge, right_edge)
        for left_edge in left_edges
        for right_edge in right_edges
    )


def point_near_bbox(point, bbox, max_gap_nm):
    if point is None or bbox is None:
        return True
    return (
        bbox[0] - max_gap_nm <= point[0] <= bbox[2] + max_gap_nm
        and bbox[1] - max_gap_nm <= point[1] <= bbox[3] + max_gap_nm
    )


def segment_intersects_bbox(segment, bbox):
    if segment is None or bbox is None:
        return False
    if point_in_bbox(segment[0], bbox) or point_in_bbox(segment[1], bbox):
        return True
    left, top, right, bottom = bbox
    edges = (
        ((left, top), (right, top)),
        ((right, top), (right, bottom)),
        ((right, bottom), (left, bottom)),
        ((left, bottom), (left, top)),
    )
    return any(segments_intersect(segment, edge) for edge in edges)


def point_distance(left, right):
    return math.hypot(left[0] - right[0], left[1] - right[1])


def shared_segment_endpoint(left, right, tolerance_nm):
    for left_point in left:
        for right_point in right:
            if point_distance(left_point, right_point) <= tolerance_nm:
                return (
                    (left_point[0] + right_point[0]) / 2.0,
                    (left_point[1] + right_point[1]) / 2.0,
                )
    return None


def segment_vector_from_point(segment, point):
    start, end = segment
    start_distance = point_distance(start, point)
    end_distance = point_distance(end, point)
    target = end if start_distance <= end_distance else start
    return target[0] - point[0], target[1] - point[1]


def vector_angle_degrees(left, right):
    left_len = math.hypot(left[0], left[1])
    right_len = math.hypot(right[0], right[1])
    if left_len == 0 or right_len == 0:
        return None
    cosine = max(-1.0, min(1.0, (left[0] * right[0] + left[1] * right[1]) / (left_len * right_len)))
    return math.degrees(math.acos(cosine))


def point_segment_distance(point, segment):
    start, end = segment
    sx, sy = start
    ex, ey = end
    px, py = point
    dx = ex - sx
    dy = ey - sy
    if dx == 0 and dy == 0:
        return point_distance(point, start)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / float(dx * dx + dy * dy)))
    projection = (sx + t * dx, sy + t * dy)
    return point_distance(point, projection)


def segment_distance(left, right):
    fast = axis_aligned_segment_distance(left, right)
    if fast is not None:
        return fast
    if segments_intersect(left, right):
        return 0.0
    return min(
        point_segment_distance(left[0], right),
        point_segment_distance(left[1], right),
        point_segment_distance(right[0], left),
        point_segment_distance(right[1], left),
    )


def axis_aligned_segment_distance(left, right):
    a, b = left
    c, d = right
    left_horizontal = a[1] == b[1]
    right_horizontal = c[1] == d[1]
    left_vertical = a[0] == b[0]
    right_vertical = c[0] == d[0]
    if left_horizontal and right_horizontal:
        y_gap = abs(a[1] - c[1])
        x_gap = interval_gap(a[0], b[0], c[0], d[0])
        return math.hypot(x_gap, y_gap)
    if left_vertical and right_vertical:
        x_gap = abs(a[0] - c[0])
        y_gap = interval_gap(a[1], b[1], c[1], d[1])
        return math.hypot(x_gap, y_gap)
    if left_horizontal and right_vertical:
        if interval_contains(a[0], b[0], c[0]) and interval_contains(c[1], d[1], a[1]):
            return 0.0
    elif left_vertical and right_horizontal:
        if interval_contains(c[0], d[0], a[0]) and interval_contains(a[1], b[1], c[1]):
            return 0.0
    else:
        return None
    return min(
        point_segment_distance(a, right),
        point_segment_distance(b, right),
        point_segment_distance(c, left),
        point_segment_distance(d, left),
    )


def interval_gap(a1, a2, b1, b2):
    left_a, right_a = sorted((a1, a2))
    left_b, right_b = sorted((b1, b2))
    if right_a < left_b:
        return left_b - right_a
    if right_b < left_a:
        return left_a - right_b
    return 0


def interval_contains(a1, a2, value):
    low, high = sorted((a1, a2))
    return low <= value <= high


def segments_intersect(left, right):
    a, b = left
    c, d = right
    return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)


def ccw(a, b, c):
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


def safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
