from dataclasses import dataclass

from kicad_dfm.services.local_checks import (
    NM_PER_MM,
    bbox_gap,
    bbox_near,
    point_distance,
    point_in_bbox,
    point_segment_distance,
    segment_distance,
    segment_intersects_bbox,
)


DEFAULT_MATCH_TOLERANCE_NM = 250000
ZONE_FILLED_BBOX_TOLERANCE_NM = 10000
X2_PAD_GEOMETRY_TOLERANCE_NM = 10000
DRILL_LAYER_NAMES = {"drl", "drill", "drills", "excellon"}


@dataclass
class MappingResult:
    status: str
    confidence: float = 0.0
    reason: str = ""
    item_id: str = ""
    item: object = None


@dataclass(frozen=True)
class CandidateItem:
    item: object
    item_id: str
    layer_name: str
    bbox_nm: tuple = None
    width_nm: float = 0.0


class GerberResultObjectMapper:
    def __init__(self, board, backend, tolerance_nm=DEFAULT_MATCH_TOLERANCE_NM):
        self.board = board
        self.backend = backend
        self.tolerance_nm = int(tolerance_nm)
        self._candidate_cache = {}
        self._candidate_layer_cache = {}
        self._zone_filled_bbox_cache = {}
        self._x2_pad_index = None
        self._transform_plot_coordinates = self._has_aux_origin()
        self._aux_origin_nm = self._read_aux_origin_nm()

    def map_row(self, row):
        if not isinstance(row, dict):
            return MappingResult("skipped", reason="invalid_row")
        mapping_row = self._mapping_row(row, "primary")
        if self._has_uuid(mapping_row.get("id")):
            return MappingResult("already_mapped", confidence=1.0, reason="uuid_present", item_id=mapping_row.get("id"))
        x2_match = self._map_x2_identity(mapping_row)
        if x2_match is not None:
            return x2_match
        geometry = self._row_geometry(mapping_row)
        if geometry is None:
            return MappingResult("skipped", reason="missing_geometry")
        candidates = self._candidates(mapping_row, geometry)
        if not candidates:
            return MappingResult("skipped", reason="no_candidate")
        candidates.sort(key=lambda candidate: (-candidate.confidence, candidate.reason))
        best = candidates[0]
        tied = [
            candidate
            for candidate in candidates[1:]
            if abs(candidate.confidence - best.confidence) < 0.02
        ]
        if tied:
            return MappingResult("ambiguous", confidence=best.confidence, reason="multiple_candidates")
        if best.confidence < 0.9:
            return MappingResult("low_confidence", confidence=best.confidence, reason=best.reason)
        return best

    def _map_x2_identity(self, row):
        raw = row.get("raw") or {}
        function = str(raw.get("aperture_function") or "").lower()
        component = str(raw.get("component") or "")
        object_id = str(raw.get("object_id") or "")
        if "pad" in function and component:
            fields = object_id.split(",")
            pad_number = fields[1] if len(fields) > 1 and fields[0] == component else ""
            matches = self._x2_pad_matches(component, pad_number)
            if matches:
                constrained = tuple(
                    pad
                    for pad in matches
                    if self._matches_row_net(row, pad)
                    and self._x2_pad_matches_row_layers(row, pad)
                )
                if not constrained:
                    return MappingResult(
                        "skipped", reason="x2_component_pad_constraints_mismatch"
                    )
                if len(matches) == 1:
                    return self._identity_result(constrained[0], "x2_component_pad")
                return self._map_duplicate_x2_pad_geometry(row, constrained)
        return None

    def _map_duplicate_x2_pad_geometry(self, row, matches):
        """Resolve duplicate native pads carrying one X2 component/pad id.

        KiCad permits a footprint to contain several pad shapes with the same
        number (NetTie footprints commonly use this).  X2 identifies all of
        those shapes with the same component and pad number, so the identity
        fields alone are insufficient.  Only a strict exported bbox/point
        match is authoritative; close peers remain ambiguous instead of
        falling through to the generic region-to-zone mapper.
        """
        geometry = self._row_geometry(row)
        if geometry is None:
            return MappingResult(
                "skipped", reason="x2_component_pad_geometry_missing"
            )
        ranked = []
        for pad in matches:
            error = self._x2_pad_geometry_error(row, geometry, pad)
            if error is None or error > X2_PAD_GEOMETRY_TOLERANCE_NM:
                continue
            ranked.append((float(error), pad))
        if not ranked:
            return MappingResult(
                "skipped", reason="x2_component_pad_geometry_mismatch"
            )
        ranked.sort(key=lambda entry: entry[0])
        best_error = ranked[0][0]
        if len(ranked) > 1:
            return MappingResult(
                "ambiguous",
                self._confidence(best_error, X2_PAD_GEOMETRY_TOLERANCE_NM),
                "x2_component_pad_geometry_ambiguous",
            )
        result = self._identity_result(ranked[0][1], "x2_component_pad_geometry")
        if result is not None:
            result.confidence = self._confidence(
                best_error, X2_PAD_GEOMETRY_TOLERANCE_NM
            )
        return result

    def _x2_pad_geometry_error(self, row, geometry, pad):
        raw = row.get("raw") or {}
        raw_bbox = raw.get("bbox")
        if raw_bbox and len(raw_bbox) == 4:
            try:
                exported_bbox = self._mm_bbox_to_nm(raw_bbox)
                native_bbox = self.backend.item_bbox(pad)
                return max(
                    abs(float(exported) - float(native))
                    for exported, native in zip(exported_bbox, native_bbox)
                )
            except (TypeError, ValueError, IndexError):
                return None
        if geometry.get("kind") == "point":
            try:
                native_point = self.backend.item_position(pad)
            except Exception:
                return None
            if native_point is not None:
                return point_distance(geometry["point"], native_point)
        return None

    def _x2_pad_matches_row_layers(self, row, pad):
        wanted_layers = set(
            self._candidate_layer_names("gerber", self._row_layers(row))
        )
        if not wanted_layers:
            return True
        try:
            fallback_layer = str(self.backend.item_layer_name(pad) or "")
        except Exception:
            fallback_layer = ""
        candidate = CandidateItem(
            item=pad,
            item_id="",
            layer_name=fallback_layer,
        )
        pad_layers = set(self._candidate_item_layer_names(candidate))
        if fallback_layer:
            pad_layers.add(fallback_layer)
        # Missing backend layer metadata is not evidence of a mismatch.
        return not pad_layers or bool(wanted_layers.intersection(pad_layers))

    def _x2_pad_matches(self, component, pad_number):
        if self._x2_pad_index is None:
            index = {}
            for footprint in self.backend.iter_footprints():
                try:
                    reference = str(footprint.GetReference())
                except Exception:
                    continue
                for pad in self.backend.iter_pads(footprint):
                    try:
                        number = str(pad.GetNumber())
                    except Exception:
                        number = ""
                    index.setdefault((reference, ""), []).append(pad)
                    if number:
                        index.setdefault((reference, number), []).append(pad)
            self._x2_pad_index = {
                key: tuple(items) for key, items in index.items()
            }
        return self._x2_pad_index.get((component, pad_number), ())

    def _identity_result(self, item, reason):
        item_id = self.backend.item_id(item)
        if not item_id:
            return None
        return MappingResult("matched", 1.0, reason, item_id, item)

    def apply_mapping(self, row):
        result = self.map_row(row)
        raw = row.setdefault("raw", {})
        raw["uuid_mapping"] = {
            "status": result.status,
            "confidence": result.confidence,
            "reason": result.reason,
        }
        if result.status == "matched":
            row["id"] = result.item_id
            row["confidence"] = max(float(row.get("confidence") or 0.0), result.confidence)
            row["geometry_basis"] = "hit_test"
            raw["uuid_mapping"]["id"] = result.item_id
        related = self.map_related(row)
        if related is not None:
            related_info = {
                "status": related.status,
                "confidence": related.confidence,
                "reason": related.reason,
            }
            if related.status in ("matched", "already_mapped"):
                row["related_id"] = related.item_id
                related_info["id"] = related.item_id
            if related.status == "matched":
                row["related_bbox_nm"] = self.backend.item_bbox(related.item)
                row["related_layer"] = self.backend.item_layer_name(related.item)
                item_type = self._backend_item_type(related.item)
                if item_type:
                    row["related_type"] = item_type
            raw["uuid_mapping"]["related"] = related_info
        return result

    def map_pair(self, row):
        """Return PCB matches for both sides of a two-object result."""
        return self.map_row(row), self.map_related(row)

    def map_pair_candidates(self, row):
        """Return all equally plausible high-confidence matches for a pair.

        Arc tessellation can place one short Gerber segment across the junction
        of two native KiCad tracks.  ``map_row`` intentionally reports that as
        ambiguous, but distance checks need both pieces because together they
        represent the exported copper shape.
        """
        return self._map_candidates(row, "primary"), self._map_candidates(
            self._related_row(row), "primary"
        )

    def map_related(self, row):
        related_row = self._related_row(row)
        if related_row is None:
            return None
        return self.map_row(related_row)

    def _related_row(self, row):
        related_raw = self._related_raw(row)
        if related_raw is None:
            return None
        related_row = dict(row)
        related_row["raw"] = related_raw
        related_row["id"] = row.get("related_id") or related_raw.get("file")
        if related_raw.get("item_type"):
            related_row["item_type"] = related_raw["item_type"]
        if "layer" in related_raw:
            related_row["layer"] = related_raw["layer"]
        return related_row

    def _map_candidates(self, row, raw_key="primary"):
        if not isinstance(row, dict):
            return ()
        mapping_row = self._mapping_row(row, raw_key)
        identity = self._map_x2_identity(mapping_row)
        if identity is not None:
            return (identity,) if identity.status == "matched" else ()
        geometry = self._row_geometry(mapping_row)
        if geometry is None:
            return ()
        candidates = self._candidates(mapping_row, geometry)
        candidates.sort(key=lambda candidate: (-candidate.confidence, candidate.reason))
        if not candidates or candidates[0].confidence < 0.9:
            return ()
        best_confidence = candidates[0].confidence
        return tuple(
            candidate
            for candidate in candidates
            if candidate.confidence >= 0.9
            and best_confidence - candidate.confidence < 0.02
        )

    def _mapping_row(self, row, raw_key):
        raw = row.get("raw") or {}
        mapping_raw = raw.get(raw_key)
        if not isinstance(mapping_raw, dict):
            return row
        mapping_row = dict(row)
        mapping_row["raw"] = mapping_raw
        if mapping_raw.get("file") and not self._has_uuid(row.get("id")):
            mapping_row["id"] = mapping_raw["file"]
        if mapping_raw.get("item_type"):
            mapping_row["item_type"] = mapping_raw["item_type"]
        if "layer" in mapping_raw:
            mapping_row["layer"] = mapping_raw["layer"]
        return mapping_row

    def _related_raw(self, row):
        raw = row.get("raw") or {}
        for key in ("related", "related_raw"):
            value = raw.get(key)
            if isinstance(value, dict):
                return value
        related = {}
        for raw_key, mapped_key in (
            ("related_segment", "segment"),
            ("related_point", "point"),
            ("related_bbox", "bbox"),
            ("related_width", "width"),
            ("related_diameter", "diameter"),
            ("related_file", "file"),
            ("related_layer", "layer"),
            ("related_item_type", "item_type"),
        ):
            if raw_key in raw:
                related[mapped_key] = raw[raw_key]
        return related or None

    def _candidates(self, row, geometry):
        layer_names = self._row_layers(row)
        wanted_type = str(row.get("item_type") or "").lower()
        candidates = []
        for candidate in self._candidate_items_for_layers(wanted_type, layer_names):
            if not self._matches_row_net(row, candidate.item):
                continue
            if not self._geometry_near_candidate(geometry, candidate):
                continue
            confidence, reason = self._score(candidate.item, geometry, candidate.bbox_nm, candidate.width_nm)
            if confidence > 0:
                candidates.append(MappingResult("matched", confidence, reason, candidate.item_id, candidate.item))
        return candidates

    def _matches_row_net(self, row, item):
        wanted_net = str((row.get("raw") or {}).get("net") or "")
        reader = getattr(self.backend, "item_net_name", None)
        if not wanted_net or reader is None:
            return True
        try:
            item_net = str(reader(item) or "")
        except Exception:
            return True
        return item_net == wanted_net

    def _candidate_items_for_layers(self, wanted_type, layer_names):
        layer_names = self._candidate_layer_names(wanted_type, layer_names)
        if not layer_names:
            return self._candidate_items(wanted_type)
        cache_key = self._candidate_cache_key(wanted_type)
        by_layer = self._candidate_items_by_layer(cache_key)
        result = []
        seen = set()
        for layer_name in layer_names:
            for candidate in by_layer.get(layer_name, ()):
                identity = id(candidate.item)
                if identity in seen:
                    continue
                seen.add(identity)
                result.append(candidate)
        for candidate in by_layer.get("", ()):
            identity = id(candidate.item)
            if identity in seen:
                continue
            seen.add(identity)
            result.append(candidate)
        return tuple(result)

    def _candidate_layer_names(self, wanted_type, layer_names):
        if wanted_type == "drill":
            layer_names = tuple(
            layer_name
            for layer_name in layer_names
            if str(layer_name or "").lower() not in DRILL_LAYER_NAMES
            )
        aliases = []
        for layer_name in layer_names:
            if layer_name not in aliases:
                aliases.append(layer_name)
            layer_id = None
            if layer_name == "F.Cu":
                layer_id = self._layer_constant("F_Cu", 0)
            elif layer_name == "B.Cu":
                layer_id = self._layer_constant("B_Cu", 31)
            elif str(layer_name).startswith("In") and str(layer_name).endswith(".Cu"):
                try:
                    inner_index = int(str(layer_name)[2:-3])
                except (TypeError, ValueError):
                    inner_index = 0
                if 1 <= inner_index <= 30:
                    layer_id = self._layer_constant(
                        "In%s_Cu" % inner_index, inner_index
                    )
            if layer_id is not None:
                try:
                    board_name = self.backend.layer_name(layer_id)
                except Exception:
                    board_name = ""
                if board_name and board_name not in aliases:
                    aliases.append(board_name)
        return tuple(aliases)

    def _candidate_items(self, wanted_type):
        cache_key = self._candidate_cache_key(wanted_type)
        if cache_key not in self._candidate_cache:
            self._candidate_cache[cache_key] = tuple(
                candidate
                for candidate in self._build_candidate_items(cache_key)
                if candidate.item_id
            )
        return self._candidate_cache[cache_key]

    def _unique_items(self, items):
        result = []
        seen = set()
        for item in items:
            item_id = self.backend.item_id(item)
            key = ("uuid", item_id) if item_id else ("identity", id(item))
            if key in seen:
                continue
            seen.add(key)
            result.append((item, item_id))
        return tuple(result)

    def _candidate_items_by_layer(self, cache_key):
        if cache_key not in self._candidate_layer_cache:
            by_layer = {}
            for candidate in self._candidate_items(cache_key):
                layer_names = self._candidate_item_layer_names(candidate)
                if not layer_names:
                    layer_names = (candidate.layer_name or "",)
                for layer_name in layer_names:
                    by_layer.setdefault(layer_name, []).append(candidate)
            self._candidate_layer_cache[cache_key] = {
                layer_name: tuple(candidates)
                for layer_name, candidates in by_layer.items()
            }
        return self._candidate_layer_cache[cache_key]

    def _candidate_item_layer_names(self, candidate):
        """Return every copper layer occupied by a native candidate.

        A through-hole pad, via, or multi-layer zone often reports only one
        fallback layer through ``GetLayer()``/``item_layer_name``.  Gerber
        emits the same physical object on every occupied copper layer, so
        indexing only that fallback layer prevents inner-layer evidence from
        receiving its native UUID and later being physically deduplicated.
        """
        reader = getattr(self.backend, "item_copper_layer_ids", None)
        if reader is None:
            return ()
        try:
            layer_ids = tuple(reader(candidate.item) or ())
        except Exception:
            return ()
        names = []
        for layer_id in layer_ids:
            try:
                layer_name = str(self.backend.layer_name(layer_id) or "")
            except Exception:
                layer_name = ""
            if layer_name and layer_name not in names:
                names.append(layer_name)
            canonical_reader = getattr(self.backend, "canonical_layer_name", None)
            if canonical_reader is not None:
                try:
                    canonical = str(canonical_reader(layer_id) or "")
                except Exception:
                    canonical = ""
                if canonical and canonical not in names:
                    names.append(canonical)
        return tuple(names)

    def _candidate_cache_key(self, wanted_type):
        return wanted_type if wanted_type in ("drill", "gerber") else "all"

    def _build_candidate_items(self, cache_key):
        for item, item_id in self._unique_items(self._iter_items(cache_key)):
            if cache_key == "drill" and not self._has_drill_geometry(item):
                continue
            if cache_key == "gerber" and not self._has_gerber_copper(item):
                continue
            yield CandidateItem(
                item=item,
                item_id=item_id,
                layer_name=self.backend.item_layer_name(item),
                bbox_nm=self.backend.item_bbox(item),
                width_nm=float(self.backend.item_width(item) or 0),
            )

    def _has_drill_geometry(self, item):
        is_pad = getattr(self.backend, "is_pad", None)
        if is_pad:
            try:
                if not is_pad(item):
                    return True
            except Exception:
                return True
        if hasattr(self.backend, "pad_drill_mm"):
            try:
                drill = self.backend.pad_drill_mm(item)
                if drill and any(float(value or 0) > 0 for value in drill):
                    return True
                if drill == (0.0, 0.0) or drill == (0, 0):
                    return False
            except Exception:
                pass
        return True

    def _has_gerber_copper(self, item):
        is_pad = getattr(self.backend, "is_pad", None)
        if is_pad:
            try:
                if not is_pad(item):
                    return True
            except Exception:
                return True
        is_npth_pad = getattr(self.backend, "is_npth_pad", None)
        if is_npth_pad:
            try:
                return not is_npth_pad(item)
            except Exception:
                return True
        return True

    def _geometry_near_candidate(self, geometry, candidate):
        if candidate.bbox_nm is None:
            return True
        return bbox_near(geometry["bbox"], candidate.bbox_nm, self.tolerance_nm)

    def _score(self, item, geometry, item_bbox=None, item_width=None):
        if geometry["kind"] == "region":
            return self._score_conductor_region(item, geometry, item_bbox)
        item_segment = self.backend.track_segment(item)
        if item_bbox is None:
            item_bbox = self.backend.item_bbox(item)
        if item_width is None:
            item_width = self.backend.item_width(item) or 0
        item_radius = max(float(item_width) / 2.0, self.tolerance_nm)
        if geometry["kind"] == "segment":
            segment = geometry["segment"]
            if item_segment:
                endpoint_distance = min(
                    max(
                        point_distance(segment[0], item_segment[0]),
                        point_distance(segment[1], item_segment[1]),
                    ),
                    max(
                        point_distance(segment[0], item_segment[1]),
                        point_distance(segment[1], item_segment[0]),
                    ),
                )
                if endpoint_distance <= self.tolerance_nm:
                    confidence = self._confidence(endpoint_distance, self.tolerance_nm)
                    geometry_width = float(geometry.get("width_nm") or 0)
                    if geometry_width > 0 and float(item_width or 0) > 0:
                        width_error = abs(geometry_width - float(item_width))
                        exact_width_tolerance = max(1000.0, geometry_width * 0.001)
                        if width_error > exact_width_tolerance:
                            confidence = min(confidence, 0.96)
                    return confidence, "segment_endpoints"
                distance = segment_distance(segment, item_segment)
                tolerance = self.tolerance_nm + item_radius
                if distance <= tolerance:
                    return min(0.94, self._confidence(distance, tolerance)), "segment_overlap"
            if item_bbox and (
                segment_intersects_bbox(segment, self._expand_bbox(item_bbox, self.tolerance_nm))
                or bbox_near(geometry["bbox"], item_bbox, self.tolerance_nm)
            ):
                return 0.9, "segment_hits_bbox"
        if geometry["kind"] == "point":
            point = geometry["point"]
            if item_segment:
                distance = point_segment_distance(point, item_segment)
                tolerance = self.tolerance_nm + item_radius
                if distance <= tolerance:
                    return self._confidence(distance, tolerance), "point_to_segment"
            item_point = self.backend.item_position(item)
            if item_point:
                distance = point_distance(point, item_point)
                if distance <= self.tolerance_nm + item_radius:
                    return self._confidence(distance, self.tolerance_nm + item_radius), "point_to_center"
            if item_bbox and point_in_bbox(point, self._expand_bbox(item_bbox, self.tolerance_nm)):
                return 0.92, "point_in_bbox"
        if geometry["kind"] == "bbox" and item_bbox:
            gap = bbox_gap(geometry["bbox"], item_bbox)
            if gap <= self.tolerance_nm:
                return self._confidence(gap, self.tolerance_nm), "bbox_near"
        return 0.0, "no_match"

    def _score_conductor_region(self, item, geometry, item_bbox=None):
        """Match an exported conductor region to one filled KiCad zone.

        A zone's editable outline bbox can be much larger than its clipped
        copper fill, and many unrelated items can overlap that bbox.  Gerber
        regions, however, are emitted from the filled outer contours.  Only a
        close four-edge match to a filled contour is authoritative here.

        The guard fields deliberately exclude custom-pad macro regions and
        layer-ambiguous evidence; those must keep their existing X2/geometry
        mapping path rather than being mislabeled as zones.
        """
        if not geometry.get("is_conductor") or not geometry.get("net"):
            return 0.0, "region_not_zone_conductor"
        layer_ids = tuple(geometry.get("layer_ids") or ())
        if len(layer_ids) != 1 or not self._is_zone_item(item):
            return 0.0, "region_not_single_layer_zone"

        filled_bboxes = self._zone_filled_bboxes(item, layer_ids[0])
        if not filled_bboxes:
            # The editable zone bbox is only a pruning hint, never sufficient
            # evidence for a UUID assignment.
            return 0.0, "zone_fill_unavailable"
        error = min(
            max(abs(float(left) - float(right)) for left, right in zip(geometry["bbox"], bbox))
            for bbox in filled_bboxes
        )
        if error > ZONE_FILLED_BBOX_TOLERANCE_NM:
            return 0.0, "zone_filled_bbox_mismatch"
        return (
            self._confidence(error, ZONE_FILLED_BBOX_TOLERANCE_NM),
            "zone_filled_bbox",
        )

    def _is_zone_item(self, item):
        return "zone" in str(self._backend_item_type(item) or "").lower()

    def _zone_filled_bboxes(self, item, layer_id):
        key = (self.backend.item_id(item) or id(item), int(layer_id))
        if key not in self._zone_filled_bbox_cache:
            reader = getattr(self.backend, "zone_polygons", None)
            bboxes = []
            if reader is not None:
                try:
                    polygons = tuple(reader(item, layer_id) or ())
                except Exception:
                    polygons = ()
                for polygon in polygons:
                    outer = polygon[0] if isinstance(polygon, (tuple, list)) and polygon else ()
                    if len(outer) < 3:
                        continue
                    try:
                        bboxes.append(self._bbox_for_points(outer))
                    except (TypeError, ValueError, IndexError):
                        continue
            self._zone_filled_bbox_cache[key] = tuple(bboxes)
        return self._zone_filled_bbox_cache[key]

    def _iter_items(self, wanted_type):
        if wanted_type == "drill":
            yield from self.backend.iter_vias()
            for footprint in self.backend.iter_footprints():
                yield from self.backend.iter_pads(footprint)
            return
        if wanted_type == "gerber":
            yield from self.backend.iter_tracks()
            for footprint in self.backend.iter_footprints():
                yield from self.backend.iter_pads(footprint)
            yield from self.backend.iter_vias()
            iter_zones = getattr(self.backend, "iter_zones", None)
            if iter_zones is not None:
                yield from iter_zones()
            yield from self.backend.iter_drawings()
            return
        yield from self.backend.iter_tracks()
        yield from self.backend.iter_vias()
        iter_zones = getattr(self.backend, "iter_zones", None)
        if iter_zones is not None:
            yield from iter_zones()
        for footprint in self.backend.iter_footprints():
            yield from self.backend.iter_pads(footprint)
        yield from self.backend.iter_drawings()

    def _row_geometry(self, row):
        raw = row.get("raw") or {}
        if raw.get("kind") == "region":
            bbox = raw.get("bbox")
            if bbox and len(bbox) == 4:
                layer_ids = self._row_copper_layer_ids(row)
                return {
                    "kind": "region",
                    "bbox": self._mm_bbox_to_nm(bbox),
                    "is_conductor": str(raw.get("aperture_function") or "").lower()
                    == "conductor",
                    "net": str(raw.get("net") or ""),
                    "layer_ids": layer_ids,
                }
        point = raw.get("point")
        if raw.get("is_flash") and point:
            point = self._mm_point_to_nm(point)
            if point is not None:
                return {
                    "kind": "point",
                    "point": point,
                    "bbox": self._mm_bbox_to_nm(raw.get("bbox"))
                    if raw.get("bbox") and len(raw.get("bbox")) == 4
                    else (point[0], point[1], point[0], point[1]),
                    "width_nm": self._mm_length_to_nm(raw.get("width")),
                }
        segment = raw.get("segment")
        if segment and len(segment) == 2:
            start = self._mm_point_to_nm(segment[0])
            end = self._mm_point_to_nm(segment[1])
            if start is not None and end is not None:
                return {
                    "kind": "segment",
                    "segment": (start, end),
                    "bbox": self._bbox_for_points((start, end)),
                    "width_nm": self._mm_length_to_nm(raw.get("width")),
                }
        point = raw.get("point")
        if point:
            point = self._mm_point_to_nm(point)
            if point is not None:
                return {"kind": "point", "point": point, "bbox": (point[0], point[1], point[0], point[1])}
        bbox = raw.get("bbox")
        if bbox and len(bbox) == 4:
            return {"kind": "bbox", "bbox": self._mm_bbox_to_nm(bbox)}
        return None

    def _row_copper_layer_ids(self, row):
        result = []
        for layer_name in self._row_layers(row):
            layer_id = None
            if layer_name == "F.Cu":
                layer_id = self._layer_constant("F_Cu", 0)
            elif layer_name == "B.Cu":
                layer_id = self._layer_constant("B_Cu", 31)
            elif str(layer_name).startswith("In") and str(layer_name).endswith(".Cu"):
                try:
                    inner_index = int(str(layer_name)[2:-3])
                except (TypeError, ValueError):
                    inner_index = 0
                if 1 <= inner_index <= 30:
                    layer_id = self._layer_constant(
                        "In%s_Cu" % inner_index, inner_index
                    )
            if layer_id is not None and layer_id not in result:
                result.append(layer_id)
        return tuple(result)

    def _row_layers(self, row):
        result = []
        layers = row.get("layer") or ()
        if isinstance(layers, str):
            layers = (layers,)
        for layer in layers:
            text = str(layer or "")
            if text and text not in result:
                result.append(text)
        return tuple(result)

    def _backend_item_type(self, item):
        item_type = getattr(self.backend, "item_type", None)
        if not item_type:
            return ""
        try:
            return item_type(item)
        except Exception:
            return ""

    def _mm_point_to_nm(self, point):
        if point is None or len(point) < 2:
            return None
        return (
            int(float(point[0]) * NM_PER_MM) + self._aux_origin_nm[0],
            (
                self._aux_origin_nm[1] - int(float(point[1]) * NM_PER_MM)
                if self._transform_plot_coordinates
                else int(float(point[1]) * NM_PER_MM)
            ),
        )

    def _mm_length_to_nm(self, value):
        try:
            return abs(float(value) * NM_PER_MM)
        except (TypeError, ValueError):
            return 0.0

    def _has_aux_origin(self):
        try:
            self.board.GetDesignSettings().GetAuxOrigin()
            return True
        except Exception:
            return False

    def _read_aux_origin_nm(self):
        try:
            origin = self.board.GetDesignSettings().GetAuxOrigin()
            return int(origin.x), int(origin.y)
        except Exception:
            return 0, 0

    def _mm_bbox_to_nm(self, bbox):
        left = int(float(bbox[0]) * NM_PER_MM) + self._aux_origin_nm[0]
        top = (
            self._aux_origin_nm[1] - int(float(bbox[1]) * NM_PER_MM)
            if self._transform_plot_coordinates
            else int(float(bbox[1]) * NM_PER_MM)
        )
        right = int(float(bbox[2]) * NM_PER_MM) + self._aux_origin_nm[0]
        bottom = (
            self._aux_origin_nm[1] - int(float(bbox[3]) * NM_PER_MM)
            if self._transform_plot_coordinates
            else int(float(bbox[3]) * NM_PER_MM)
        )
        return min(left, right), min(top, bottom), max(left, right), max(top, bottom)

    def _layer_constant(self, name, fallback):
        reader = getattr(self.backend, "layer_constant", None)
        if reader is not None:
            try:
                return reader(name)
            except Exception:
                pass
        return fallback

    def _bbox_for_points(self, points):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    def _expand_bbox(self, bbox, margin):
        return bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin

    def _confidence(self, distance, tolerance):
        if tolerance <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - float(distance) / float(tolerance) * 0.2))

    def _has_uuid(self, value):
        text = str(value or "")
        return bool(text and not (text.lower().endswith((".gbr", ".ger", ".drl", ".xln")) or "/" in text or "\\" in text))
