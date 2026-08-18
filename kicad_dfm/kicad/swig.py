import math
import os

from kicad_dfm.core.errors import ExportError
from kicad_dfm.kicad.backend import BackendCapabilities, BoardBackend


def _pcbnew():
    import pcbnew

    return pcbnew


class SwigBackend(BoardBackend):
    """SWIG pcbnew adapter for KiCad 6-10.

    KiCad APIs differ by version, so feature checks use hasattr before calling
    optional methods. IPC can be added later without changing service callers.
    """

    kind = "swig"
    # CONNECTIVITY_DATA.GetConnectedItems() searches KiCad connectivity
    # clusters, so one call already returns the complete component containing
    # the source item.  LocalChecks uses this capability marker to avoid
    # repeating the same native cluster search for every item in that cluster.
    connected_item_ids_are_components = True

    def __init__(self, board=None):
        if board is None:
            board = _pcbnew().GetBoard()
        super().__init__(board)
        self._item_cache = None
        self._solder_mask_shape_cache = {}
        self._connectivity_initialized = False
        self._connectivity_data = None
        self._connected_item_ids_cache = {}
        self._connected_layer_ids_cache = {}

    def invalidate_item_cache(self):
        self._item_cache = None
        self._solder_mask_shape_cache.clear()
        self._connectivity_initialized = False
        self._connectivity_data = None
        self._connected_item_ids_cache.clear()
        self._connected_layer_ids_cache.clear()

    def begin_analysis(self):
        # The interactive editor can mutate the shared BOARD between runs.
        # Connectivity and UUID/shape caches must describe this exact pass,
        # otherwise a removed bridge can remain falsely connected (and vice
        # versa) until the plugin is restarted.
        self.invalidate_item_cache()

    def version(self):
        pcbnew = _pcbnew()
        if hasattr(pcbnew, "GetBuildVersion"):
            return pcbnew.GetBuildVersion()
        if hasattr(pcbnew, "Version"):
            return pcbnew.Version()
        return ""

    def capabilities(self):
        pcbnew = _pcbnew()
        return BackendCapabilities(
            can_plot=hasattr(pcbnew, "PLOT_CONTROLLER"),
            can_drill=hasattr(pcbnew, "EXCELLON_WRITER"),
            can_mark=hasattr(pcbnew, "PCB_MARKER") or hasattr(pcbnew, "PCB_MARKER_Deserialize"),
            can_highlight=hasattr(self.board, "SetVisibleLayers"),
            can_focus_native=hasattr(pcbnew, "FocusOnItem"),
            can_native_drc_marker=self._major_version() in (6, 7),
            can_resolve_item=hasattr(self.board, "ResolveItem"),
            can_iter_zones=hasattr(self.board, "Zones") or hasattr(self.board, "GetArea"),
        )

    def board_name(self):
        filename = self.file_name()
        return os.path.splitext(os.path.basename(filename))[0]

    def board_area_mm2(self):
        pcbnew = _pcbnew()
        if self.board is not None and hasattr(self.board, "GetBoardPolygonOutlines"):
            try:
                outlines = pcbnew.SHAPE_POLY_SET()
                if self.board.GetBoardPolygonOutlines(outlines, True):
                    return abs(float(outlines.Area())) / 1000000000000.0
            except Exception:
                pass
        return super().board_area_mm2()

    def board_outline_segments(self):
        """Return KiCad's polygonized outer outline and every internal cut-out.

        Reading Edge.Cuts drawing start/end points is insufficient for arcs,
        circles, rectangles, polygons, and Beziers.  BOARD owns the canonical
        outline builder and already normalizes those primitives into closed
        polygon chains, including holes.
        """
        pcbnew = _pcbnew()
        if self.board is not None and hasattr(
            self.board,
            "GetBoardPolygonOutlines",
        ) and hasattr(pcbnew, "SHAPE_POLY_SET"):
            outlines = pcbnew.SHAPE_POLY_SET()
            built = False
            for args in (
                (outlines, False, None, False, False),
                (outlines, False),
            ):
                try:
                    built = bool(self.board.GetBoardPolygonOutlines(*args))
                    break
                except TypeError:
                    continue
                except Exception:
                    break
            if built:
                segments = []
                try:
                    outline_count = int(outlines.OutlineCount())
                except Exception:
                    outline_count = 0
                for outline_index in range(outline_count):
                    chain = self._poly_set_chain(
                        outlines,
                        "COutline",
                        "Outline",
                        outline_index,
                    )
                    segments.extend(self._closed_chain_segments(chain))
                    try:
                        hole_count = int(outlines.HoleCount(outline_index))
                    except Exception:
                        hole_count = 0
                    for hole_index in range(hole_count):
                        hole = self._poly_set_chain(
                            outlines,
                            "CHole",
                            "Hole",
                            outline_index,
                            hole_index,
                        )
                        segments.extend(self._closed_chain_segments(hole))
                if segments:
                    return tuple(segments)
        return super().board_outline_segments()

    def _poly_set_chain(self, polyset, const_name, mutable_name, *indexes):
        for name in (const_name, mutable_name):
            if not hasattr(polyset, name):
                continue
            try:
                return getattr(polyset, name)(*indexes)
            except Exception:
                continue
        return None

    def _closed_chain_segments(self, chain):
        points = self._poly_chain_points(chain)
        if len(points) < 2:
            return ()
        return tuple(
            (points[index], points[(index + 1) % len(points)])
            for index in range(len(points))
            if points[index] != points[(index + 1) % len(points)]
        )

    def pad_copper_area_mm2(self, pad, layer_name=None):
        pcbnew = _pcbnew()
        if layer_name and hasattr(pad, "TransformShapeToPolygon"):
            try:
                polygons = pcbnew.SHAPE_POLY_SET()
                error_loc = getattr(pcbnew, "ERROR_INSIDE", 0)
                pad.TransformShapeToPolygon(
                    polygons,
                    self.layer_id(layer_name),
                    0,
                    10000,
                    error_loc,
                )
                return abs(float(polygons.Area())) / 1000000000000.0
            except Exception:
                pass
        return super().pad_copper_area_mm2(pad, layer_name)

    def via_has_solder_mask_opening_on_layer(self, via, layer_name):
        # KiCad 6 does not expose via tenting through SWIG.  Treat an unknown
        # state as covered instead of inflating finish area/test-point counts.
        if not hasattr(via, "IsTented"):
            return False
        return super().via_has_solder_mask_opening_on_layer(via, layer_name)

    def file_name(self):
        return self.board.GetFileName() if self.board is not None else ""

    def save(self, path=None):
        pcbnew = _pcbnew()
        return pcbnew.SaveBoard(path or self.file_name(), self.board)

    def copper_layer_count(self):
        return self.board.GetCopperLayerCount()

    def layer_id(self, layer_name):
        if hasattr(self.board, "GetLayerID"):
            return self.board.GetLayerID(layer_name)
        for layer_id in range(64):
            try:
                if self.board.GetLayerName(layer_id) == layer_name:
                    return layer_id
            except Exception:
                continue
        return None

    def layer_name(self, layer_id):
        return self.board.GetLayerName(layer_id)

    def canonical_layer_name(self, layer_id):
        # BOARD.GetLayerName returns the user-assigned stackup name in KiCad
        # 10 (for example "L1 (Sig, PWR)").  Rule indexing must use stable
        # names such as F.Cu/B.Cu/F.Mask regardless of those aliases.
        if hasattr(self.board, "GetStandardLayerName"):
            try:
                return str(self.board.GetStandardLayerName(layer_id))
            except Exception:
                pass
        pcbnew = _pcbnew()
        if hasattr(pcbnew, "LayerName"):
            try:
                return str(pcbnew.LayerName(layer_id))
            except Exception:
                pass
        return self.layer_name(layer_id)

    def item_layer_id(self, item):
        # PAD.GetLayer() is not authoritative for multilayer-capable pads in
        # recent KiCad versions.  In particular, a bottom-side SMD pad can
        # still report F_Cu here even though its layer set contains B_Cu only.
        # Grouping such pads on F_Cu creates false cross-layer spacing errors.
        if self.is_pad(item) and hasattr(item, "IsOnLayer"):
            active_copper_layers = []
            pcbnew = _pcbnew()
            names = ["F_Cu"]
            names.extend("In{0}_Cu".format(index) for index in range(1, 31))
            names.append("B_Cu")
            for name in names:
                if not hasattr(pcbnew, name):
                    continue
                layer_id = getattr(pcbnew, name)
                try:
                    if item.IsOnLayer(layer_id):
                        active_copper_layers.append(layer_id)
                except Exception:
                    continue
            if len(active_copper_layers) == 1:
                return active_copper_layers[0]
        return super().item_layer_id(item)

    def item_layer_name(self, item):
        # Resolve through the board's layer table.  KiCad 10 can return the
        # front-layer name from PAD/ZONE.GetLayerName() even when GetLayer()
        # points at B_Cu or an inner copper layer.
        layer_id = self.item_layer_id(item)
        if layer_id is not None:
            try:
                return self.layer_name(layer_id)
            except Exception:
                pass
        return super().item_layer_name(item)

    def vector(self, x, y):
        pcbnew = _pcbnew()
        if hasattr(pcbnew, "VECTOR2I"):
            return pcbnew.VECTOR2I(int(x), int(y))
        return pcbnew.wxPoint(int(x), int(y))

    def iter_footprints(self):
        if hasattr(self.board, "GetFootprints"):
            return iter(self.board.GetFootprints())
        if hasattr(self.board, "Modules"):
            return iter(self.board.Modules())
        return iter(())

    def iter_pads(self, footprint):
        if hasattr(footprint, "Pads"):
            return iter(footprint.Pads())
        return iter(())

    def iter_tracks(self):
        return iter(self.board.GetTracks()) if hasattr(self.board, "GetTracks") else iter(())

    def iter_vias(self):
        return (item for item in self.iter_tracks() if self.is_via(item))

    def iter_zones(self):
        if hasattr(self.board, "Zones"):
            return iter(self.board.Zones())
        if hasattr(self.board, "GetAreaCount") and hasattr(self.board, "GetArea"):
            return (self.board.GetArea(index) for index in range(self.board.GetAreaCount()))
        return iter(())

    def iter_drawings(self):
        if hasattr(self.board, "GetDrawings"):
            return iter(self.board.GetDrawings())
        if hasattr(self.board, "Drawings"):
            return iter(self.board.Drawings())
        return iter(())

    def _copper_stack_layer_ids(self):
        """Return copper layer IDs in physical stack order.

        KiCad's numeric layer IDs are not stack ordered (B.Cu is ID 2 while
        inner layers use IDs 4, 6, ...), so numeric range comparisons are not
        valid for blind/buried-via spans.
        """
        if self.board is None:
            return ()
        if hasattr(self.board, "GetEnabledLayers"):
            try:
                enabled = self.board.GetEnabledLayers()
                if hasattr(enabled, "CuStack"):
                    stack = tuple(int(layer_id) for layer_id in enabled.CuStack())
                    if stack:
                        return stack
            except Exception:
                pass

        try:
            copper_count = int(self.board.GetCopperLayerCount())
        except Exception:
            copper_count = 0
        if copper_count < 2:
            return ()
        try:
            pcbnew = _pcbnew()
        except ImportError:
            return ()
        names = ["F_Cu"]
        names.extend(
            "In{0}_Cu".format(index)
            for index in range(1, max(1, copper_count - 1))
        )
        names.append("B_Cu")
        return tuple(
            int(getattr(pcbnew, name))
            for name in names
            if hasattr(pcbnew, name)
        )

    def item_copper_layer_ids(self, item):
        stack = self._copper_stack_layer_ids()
        if item is None or not stack:
            return ()

        # Vias expose their span endpoints consistently across KiCad 6-10.
        # Expand that span by physical stack position before consulting
        # IsOnLayer(), whose older implementations can report only endpoints.
        endpoints = []
        for names in (
            ("TopLayer", "GetTopLayer"),
            ("BottomLayer", "GetBottomLayer"),
        ):
            for name in names:
                if not hasattr(item, name):
                    continue
                try:
                    endpoints.append(int(getattr(item, name)()))
                    break
                except Exception:
                    continue
        if len(endpoints) == 2 and all(layer in stack for layer in endpoints):
            first = stack.index(endpoints[0])
            last = stack.index(endpoints[1])
            low, high = sorted((first, last))
            return stack[low : high + 1]

        if hasattr(item, "GetLayerSet"):
            try:
                layer_set = item.GetLayerSet()
                if hasattr(layer_set, "Seq"):
                    item_layers = {int(layer_id) for layer_id in layer_set.Seq()}
                    layers = tuple(
                        layer_id for layer_id in stack if layer_id in item_layers
                    )
                    if layers:
                        return layers
            except Exception:
                pass

        if hasattr(item, "IsOnLayer"):
            layers = []
            attempted = False
            for layer_id in stack:
                try:
                    on_layer = bool(item.IsOnLayer(layer_id))
                    attempted = True
                except Exception:
                    continue
                if on_layer:
                    layers.append(layer_id)
            if attempted:
                return tuple(layers)

        try:
            layer_id = int(item.GetLayer())
        except Exception:
            return ()
        return (layer_id,) if layer_id in stack else ()

    def pad_copper_layer_ids(self, pad):
        """Return an authoritative pad copper-layer set when the stack is known.

        KiCad footprint authors commonly use pad-shaped objects on F.Paste or
        B.Paste to tune stencil apertures.  Those objects may still report a
        fallback F.Cu layer through ``GetLayer()``, so callers must use the
        complete layer set rather than the single-layer fallback.
        """
        if pad is None:
            return ()
        stack = self._copper_stack_layer_ids()
        if not stack:
            return None
        if hasattr(pad, "GetLayerSet"):
            try:
                layer_set = pad.GetLayerSet()
                if hasattr(layer_set, "Seq"):
                    item_layers = {int(layer_id) for layer_id in layer_set.Seq()}
                    # A successful empty intersection is authoritative: this
                    # is exactly how paste-only pad-shaped apertures appear.
                    return tuple(
                        layer_id for layer_id in stack if layer_id in item_layers
                    )
            except Exception:
                pass
        if hasattr(pad, "IsOnLayer"):
            layers = []
            attempted = False
            for layer_id in stack:
                try:
                    on_layer = bool(pad.IsOnLayer(layer_id))
                    attempted = True
                except Exception:
                    continue
                if on_layer:
                    layers.append(layer_id)
            if attempted:
                return tuple(layers)
        try:
            layer_id = int(pad.GetLayer())
        except Exception:
            return None
        return (layer_id,) if layer_id in stack else ()

    def net_tie_pad_groups(self):
        """Return the distinct pad groups declared by KiCad net ties.

        Each member retains both its UUID and net name so spacing checks can
        scope KiCad's exemption to the physical net-tie construction instead
        of treating the two nets as globally interchangeable.
        """
        groups = []
        seen = set()
        for footprint in self.iter_footprints():
            is_net_tie = getattr(footprint, "IsNetTie", None)
            try:
                if is_net_tie is None or not bool(is_net_tie()):
                    continue
            except Exception:
                continue

            pads = tuple(self.iter_pads(footprint))
            get_tied_pads = getattr(footprint, "GetNetTiePads", None)
            if get_tied_pads is None:
                # KiCad 6 exposes IsNetTie() but not the group reader.  Its
                # common two-pin net tie can still be recognized safely.  Do
                # not merge a footprint with more pad numbers: it may contain
                # multiple independent tie groups.
                pad_numbers = set()
                for pad in pads:
                    if not hasattr(pad, "GetNumber"):
                        continue
                    try:
                        pad_number = str(pad.GetNumber() or "")
                    except Exception:
                        continue
                    if pad_number:
                        pad_numbers.add(pad_number)
                candidate_groups = (pads,) if len(pad_numbers) == 2 else ()
            else:
                candidate_groups = []
                for pad in pads:
                    try:
                        candidate_groups.append(tuple(get_tied_pads(pad) or ()))
                    except Exception:
                        continue

            for tied_pads in candidate_groups:
                members = []
                for pad in tied_pads:
                    pad_id = self.item_id(pad)
                    net_name = self.item_net_name(pad)
                    if pad_id and net_name:
                        members.append((pad_id, net_name))
                members = tuple(sorted(set(members)))
                net_names = {net_name for _pad_id, net_name in members}
                if len(net_names) < 2 or members in seen:
                    continue
                seen.add(members)
                groups.append(members)
        return tuple(groups)

    def net_tie_footprint_pad_ids(self):
        """Return all pads belonging to footprints KiCad marks as net ties."""
        pad_ids = set()
        for footprint in self.iter_footprints():
            is_net_tie = getattr(footprint, "IsNetTie", None)
            try:
                if is_net_tie is None or not bool(is_net_tie()):
                    continue
            except Exception:
                continue
            for pad in self.iter_pads(footprint):
                pad_id = self.item_id(pad)
                if pad_id:
                    pad_ids.add(pad_id)
        return frozenset(pad_ids)

    def net_tie_net_groups(self):
        """Project local net-tie pad groups to names for compatibility."""
        return tuple(
            tuple(sorted({net_name for _pad_id, net_name in group}))
            for group in self.net_tie_pad_groups()
        )

    def _get_connectivity(self):
        if self._connectivity_initialized:
            return self._connectivity_data
        self._connectivity_initialized = True
        if self.board is None or not hasattr(self.board, "GetConnectivity"):
            return None
        try:
            if hasattr(self.board, "BuildConnectivity"):
                self.board.BuildConnectivity()
            self._connectivity_data = self.board.GetConnectivity()
        except Exception:
            self._connectivity_data = None
        return self._connectivity_data

    def connected_item_ids(self, item):
        connectivity = self._get_connectivity()
        if connectivity is None or not hasattr(connectivity, "GetConnectedItems"):
            return None
        cache_key = self.item_id(item) or id(item)
        if cache_key in self._connected_item_ids_cache:
            return self._connected_item_ids_cache[cache_key]
        try:
            connected = connectivity.GetConnectedItems(item)
        except TypeError:
            # KiCad 6/7 expose a different second parameter here: a
            # KICAD_T container, not the integer flags used by KiCad 8+.
            # Those old SWIG bindings do not provide a constructible Python
            # container for the parameter, so let the caller use its exact
            # per-layer geometry graph instead of passing a misleading 0.
            return None
        except Exception:
            return None
        item_ids = {
            item_id
            for item_id in (self.item_id(candidate) for candidate in connected)
            if item_id
        }
        own_id = self.item_id(item)
        if own_id:
            item_ids.add(own_id)
        result = frozenset(item_ids)
        self._connected_item_ids_cache[cache_key] = result
        return result

    def connected_copper_layer_ids(self, item):
        connectivity = self._get_connectivity()
        if connectivity is None or not hasattr(connectivity, "IsConnectedOnLayer"):
            return None
        cache_key = self.item_id(item) or id(item)
        if cache_key in self._connected_layer_ids_cache:
            return self._connected_layer_ids_cache[cache_key]
        layers = self.item_copper_layer_ids(item)
        if not layers:
            return None
        connected_layers = []
        for layer_id in layers:
            try:
                connected = bool(connectivity.IsConnectedOnLayer(item, layer_id))
            except Exception:
                # A partial layer result is not authoritative for a via: an
                # exception on one spanned layer could otherwise turn an
                # unknown connection into a false isolated/connected verdict.
                return None
            if connected:
                connected_layers.append(layer_id)
        result = tuple(connected_layers)
        self._connected_layer_ids_cache[cache_key] = result
        return result

    def zone_polygons(self, zone, layer_id=None):
        if zone is None or not hasattr(zone, "GetFilledPolysList"):
            return ()
        if layer_id is None:
            try:
                layer_id = zone.GetLayer()
            except Exception:
                return ()
        try:
            if (
                hasattr(zone, "HasFilledPolysForLayer")
                and not zone.HasFilledPolysForLayer(layer_id)
            ):
                return ()
            polyset = zone.GetFilledPolysList(layer_id)
            outline_count = int(polyset.OutlineCount())
        except Exception:
            return ()
        polygons = []
        for outline_index in range(outline_count):
            outer = self._poly_chain_points(polyset.Outline(outline_index))
            if len(outer) < 3:
                continue
            holes = []
            try:
                hole_count = int(polyset.HoleCount(outline_index))
            except Exception:
                hole_count = 0
            for hole_index in range(hole_count):
                hole = self._poly_chain_points(
                    polyset.Hole(outline_index, hole_index)
                )
                if len(hole) >= 3:
                    holes.append(hole)
            polygons.append((outer, tuple(holes)))
        return tuple(polygons)

    def zone_contains_point(self, zone, point, layer_id=None):
        if (
            zone is None
            or point is None
            or not hasattr(zone, "GetFilledPolysList")
        ):
            return None
        if layer_id is None:
            try:
                layer_id = zone.GetLayer()
            except Exception:
                return None
        try:
            polyset = zone.GetFilledPolysList(layer_id)
            return bool(
                polyset.Contains(
                    _pcbnew().VECTOR2I(int(point[0]), int(point[1]))
                )
            )
        except Exception:
            return None

    def zone_point_distance_nm(self, zone, point, layer_id=None):
        if (
            zone is None
            or point is None
            or not hasattr(zone, "GetFilledPolysList")
        ):
            return None
        if layer_id is None:
            try:
                layer_id = zone.GetLayer()
            except Exception:
                return None
        try:
            polyset = zone.GetFilledPolysList(layer_id)
            return int(
                polyset.Distance(
                    _pcbnew().VECTOR2I(int(point[0]), int(point[1]))
                )
            )
        except Exception:
            return None

    def item_clearance_nm(self, left, right, max_distance_nm):
        left_shape = self._effective_shape(left)
        right_shape = self._effective_shape(right)
        return self._shape_clearance_nm(left_shape, right_shape, max_distance_nm)

    def item_local_clearance_nm(self, item):
        reader = getattr(item, "GetLocalClearance", None)
        if reader is None:
            return None
        try:
            value = reader()
        except Exception:
            return None
        if value is None:
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None

    def item_to_segment_clearance_nm(
        self,
        item,
        segment,
        layer_id=None,
        max_distance_nm=0,
    ):
        if item is None or not segment or len(segment) != 2:
            return None
        pcbnew = _pcbnew()
        if not (
            hasattr(pcbnew, "SHAPE_SEGMENT")
            and hasattr(pcbnew, "VECTOR2I")
        ):
            return None
        try:
            start, end = segment
            edge_shape = pcbnew.SHAPE_SEGMENT(
                pcbnew.VECTOR2I(int(start[0]), int(start[1])),
                pcbnew.VECTOR2I(int(end[0]), int(end[1])),
                0,
            )
        except Exception:
            return None
        return self._shape_clearance_nm(
            self._effective_shape(item, layer_id),
            edge_shape,
            max_distance_nm,
        )

    def _shape_clearance_nm(self, left_shape, right_shape, max_distance_nm):
        if left_shape is None or right_shape is None:
            return None
        try:
            if left_shape.Collide(right_shape, 0):
                return 0
            upper = max(0, int(max_distance_nm))
            if upper <= 0:
                return 1
            if not left_shape.Collide(right_shape, upper):
                # Callers use ``> max_distance`` to prune non-candidates.  Do
                # not return the limit itself for an object known to be farther
                # away, otherwise it is reported as an exact boundary hit.
                return upper + 1
            get_clearance = getattr(left_shape, "GetClearance", None)
            if callable(get_clearance):
                try:
                    # KiCad 8+ exposes the exact shape-to-shape distance.  A
                    # final Collide check preserves the integer threshold
                    # semantics used by older versions (GetClearance can be
                    # one nanometre below that threshold for some shapes).
                    candidate = max(1, int(get_clearance(right_shape)))
                    if candidate <= upper and not left_shape.Collide(
                        right_shape,
                        candidate,
                    ):
                        candidate += 1
                    if candidate <= upper and left_shape.Collide(
                        right_shape,
                        candidate,
                    ):
                        return candidate
                except Exception:
                    # Some older bindings expose the name for only a subset of
                    # shape pairs, and SWIG commonly reports those failures as
                    # RuntimeError.  Preserve the Collide binary-search fallback.
                    pass
            lower = 1
            while lower < upper:
                middle = (lower + upper) // 2
                if left_shape.Collide(right_shape, middle):
                    upper = middle
                else:
                    lower = middle + 1
            return lower
        except Exception:
            return None

    def solder_mask_opening_clearance_nm(
        self, left_pad, right_pad, mask_layer_name, max_distance_nm
    ):
        return self._shape_clearance_nm(
            self._solder_mask_opening_shape(left_pad, mask_layer_name),
            self._solder_mask_opening_shape(right_pad, mask_layer_name),
            max_distance_nm,
        )

    def solder_mask_opening_bbox_nm(self, pad, mask_layer_name):
        shape = self._solder_mask_opening_shape(pad, mask_layer_name)
        if shape is None or not hasattr(shape, "BBox"):
            return None
        try:
            return self.bbox_bounds(shape.BBox())
        except Exception:
            return None

    def solder_mask_opening_to_item_clearance_nm(
        self, pad, item, mask_layer_name, max_distance_nm
    ):
        return self._shape_clearance_nm(
            self._solder_mask_opening_shape(pad, mask_layer_name),
            self._effective_shape(item),
            max_distance_nm,
        )

    def _solder_mask_opening_shape(self, pad, mask_layer_name):
        """Build the real expanded mask polygon for rotated/custom pads."""
        try:
            pad_key = self.item_id(pad) or id(pad)
        except Exception:
            pad_key = id(pad)
        cache_key = (pad_key, str(mask_layer_name))
        if cache_key in self._solder_mask_shape_cache:
            return self._solder_mask_shape_cache[cache_key]
        if pad is None or not self.pad_has_solder_mask_opening_on_layer(
            pad, "F.Cu" if mask_layer_name == "F.Mask" else "B.Cu"
        ):
            self._solder_mask_shape_cache[cache_key] = None
            return None
        pcbnew = _pcbnew()
        try:
            mask_layer_id = self.layer_id(mask_layer_name)
            copper_layer_id = self.layer_id(
                "F.Cu" if mask_layer_name == "F.Mask" else "B.Cu"
            )
            expansion = int(pad.GetSolderMaskExpansion(mask_layer_id))
            polygon = pcbnew.SHAPE_POLY_SET()
            error_loc = getattr(pcbnew, "ERROR_INSIDE", 0)
            pad.TransformShapeToPolygon(
                polygon,
                copper_layer_id,
                expansion,
                10000,
                error_loc,
            )
            self._solder_mask_shape_cache[cache_key] = polygon
            return polygon
        except Exception:
            # Older KiCad builds may not expose TransformShapeToPolygon with
            # the same signature.  The effective mask-layer shape is still a
            # better fallback than an axis-aligned pad bounding box.
            try:
                shape = self._effective_shape(pad, self.layer_id(mask_layer_name))
                self._solder_mask_shape_cache[cache_key] = shape
                return shape
            except Exception:
                self._solder_mask_shape_cache[cache_key] = None
                return None

    def hole_pad_overlap_nm(self, hole, pad, pad_layer_id=None):
        """Return drill penetration into a pad's effective copper shape.

        KiCad custom and rotated pads can have a bounding box that contains a
        drill even when their real copper does not.  Shrinking a cloned drill
        shape until it stops colliding gives the radial penetration depth while
        preserving round and slotted drill geometry.
        """
        if hole is None or pad is None or not hasattr(hole, "GetEffectiveHoleShape"):
            return None
        try:
            hole_shape = hole.GetEffectiveHoleShape()
            pad_shape = self._effective_shape(pad, pad_layer_id)
            if hole_shape is None or pad_shape is None:
                return None
            if not hole_shape.Collide(pad_shape, 0):
                return 0
            width = int(hole_shape.GetWidth())
            if width <= 0 or not hasattr(hole_shape, "Clone"):
                return None
            probe = hole_shape.Clone()
            if not hasattr(probe, "SetWidth"):
                return None
            probe.SetWidth(0)
            if probe.Collide(pad_shape, 0):
                return width // 2
            lower = 0
            upper = width
            while lower + 1 < upper:
                middle = (lower + upper) // 2
                probe.SetWidth(middle)
                if probe.Collide(pad_shape, 0):
                    upper = middle
                else:
                    lower = middle
            return max(0, (width - upper) // 2)
        except Exception:
            return None

    def hole_bbox(self, hole):
        if hole is None or not hasattr(hole, "GetEffectiveHoleShape"):
            return None
        try:
            shape = hole.GetEffectiveHoleShape()
            return self.bbox_bounds(shape.BBox()) if shape is not None else None
        except Exception:
            return None

    def hole_to_segment_clearance_nm(
        self,
        hole,
        segment,
        max_distance_nm,
    ):
        """Return exact drill-edge clearance to one board-outline segment."""
        if hole is None or not hasattr(hole, "GetEffectiveHoleShape"):
            return None
        try:
            pcbnew = _pcbnew()
            hole_shape = hole.GetEffectiveHoleShape()
            if hole_shape is None or not hasattr(pcbnew, "SHAPE_SEGMENT"):
                return None
            edge_shape = pcbnew.SHAPE_SEGMENT(
                self.vector(segment[0][0], segment[0][1]),
                self.vector(segment[1][0], segment[1][1]),
                0,
            )
            if hole_shape.Collide(edge_shape, 0):
                return 0
            upper = max(1, int(math.ceil(float(max_distance_nm or 0))))
            if not hole_shape.Collide(edge_shape, upper):
                return None
            lower = 0
            while lower + 1 < upper:
                middle = (lower + upper) // 2
                if hole_shape.Collide(edge_shape, middle):
                    upper = middle
                else:
                    lower = middle
            return upper
        except Exception:
            return None

    def hole_axis_on_pad(self, hole, pad, pad_layer_id=None):
        """Return whether a drill centre/slot centreline is on real pad copper."""
        if hole is None or pad is None or not hasattr(hole, "GetEffectiveHoleShape"):
            return None
        try:
            hole_shape = hole.GetEffectiveHoleShape()
            pad_shape = self._effective_shape(pad, pad_layer_id)
            if hole_shape is None or pad_shape is None:
                return None
            if not hole_shape.Collide(pad_shape, 0):
                return False
            width = int(hole_shape.GetWidth())
            if width <= 0 or not hasattr(hole_shape, "Clone"):
                return None

            # A circular via is represented by KiCad as a zero-length
            # SHAPE_SEGMENT.  Do not shrink it to width zero and call Collide:
            # KiCad 10 can report that degenerate shape as colliding when its
            # point is just outside a pad.  PointInside tests the drill axis
            # against the pad's real (including rotated/custom) copper shape.
            start_reader = getattr(hole_shape, "GetStart", None)
            end_reader = getattr(hole_shape, "GetEnd", None)
            point_inside = getattr(pad_shape, "PointInside", None)
            if (
                callable(start_reader)
                and callable(end_reader)
                and callable(point_inside)
            ):
                start = start_reader()
                end = end_reader()
                if start == end:
                    try:
                        return bool(point_inside(start, 0))
                    except TypeError:
                        return bool(point_inside(start))

            probe = hole_shape.Clone()
            if not hasattr(probe, "SetWidth"):
                return None
            probe.SetWidth(0)
            return bool(probe.Collide(pad_shape, 0))
        except Exception:
            return None

    def _effective_shape(self, item, layer_id=None):
        if item is None or not hasattr(item, "GetEffectiveShape"):
            return None
        if layer_id is None:
            layer_id = self.item_layer_id(item)
        if layer_id is not None:
            try:
                return item.GetEffectiveShape(layer_id)
            except TypeError:
                pass
            except Exception:
                pass
        try:
            return item.GetEffectiveShape()
        except Exception:
            return None

    def _poly_chain_points(self, chain):
        if chain is None:
            return ()
        try:
            count = int(chain.PointCount())
        except Exception:
            try:
                count = int(chain.GetPointCount())
            except Exception:
                return ()
        points = []
        for index in range(count):
            try:
                point = chain.CPoint(index)
            except Exception:
                try:
                    point = chain.GetPoint(index)
                except Exception:
                    return ()
            xy = self.point_xy(point)
            if xy is not None and (not points or xy != points[-1]):
                points.append(xy)
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        return tuple(points)

    def is_via(self, item):
        pcbnew = _pcbnew()
        return hasattr(pcbnew, "PCB_VIA") and isinstance(item, pcbnew.PCB_VIA)

    def is_track(self, item):
        pcbnew = _pcbnew()
        return hasattr(pcbnew, "PCB_TRACK") and isinstance(item, pcbnew.PCB_TRACK)

    def is_pad(self, item):
        pcbnew = _pcbnew()
        if hasattr(pcbnew, "PAD") and isinstance(item, pcbnew.PAD):
            return True
        # KiCad 9+ may rename PAD class or reorganize the type hierarchy so
        # isinstance(item, pcbnew.PAD) returns False.  Detect pads by their
        # unique API signature: GetSizeX / GetSizeY / GetAttribute / GetShape.
        if (
            hasattr(item, "GetSizeX")
            and hasattr(item, "GetSizeY")
            and hasattr(item, "GetAttribute")
            and not hasattr(item, "GetStart")
        ):
            return True
        return False

    def is_shape(self, item):
        pcbnew = _pcbnew()
        return hasattr(pcbnew, "PCB_SHAPE") and isinstance(item, pcbnew.PCB_SHAPE)

    def is_text(self, item):
        pcbnew = _pcbnew()
        return hasattr(pcbnew, "PCB_TEXT") and isinstance(item, pcbnew.PCB_TEXT)

    def is_custom_pad(self, item):
        if not self.is_pad(item) or not hasattr(item, "GetShape"):
            return False
        pcbnew = _pcbnew()
        try:
            return item.GetShape() == pcbnew.PAD_SHAPE_CUSTOM
        except Exception:
            return False

    def text_stroke_polygons(self, item):
        if not self.is_text(item) or not hasattr(item, "GetEffectiveTextShape"):
            return ()
        pcbnew = _pcbnew()
        if not hasattr(pcbnew, "SHAPE_POLY_SET"):
            return ()
        try:
            shape = item.GetEffectiveTextShape()
            polyset = pcbnew.SHAPE_POLY_SET()
            error_loc = getattr(pcbnew, "ERROR_INSIDE", 0)
            shape.TransformToPolygon(polyset, 10000, error_loc)
            outline_count = int(polyset.OutlineCount())
        except Exception:
            return ()
        polygons = []
        for outline_index in range(outline_count):
            try:
                outer = self._poly_chain_points(polyset.Outline(outline_index))
            except Exception:
                continue
            if len(outer) >= 3:
                polygons.append((outer, ()))
        return tuple(polygons)

    def text_stroke_segments(self, item):
        if not self.is_text(item) or not hasattr(item, "GetEffectiveTextShape"):
            return ()
        try:
            # Keep the compound alive while reading its borrowed subshape
            # pointers; otherwise SWIG may attempt to cast dangling shapes.
            effective_shape = item.GetEffectiveTextShape()
            subshapes = effective_shape.GetSubshapes()
        except Exception:
            return ()
        segments = []
        for index in range(len(subshapes)):
            try:
                shape = subshapes[index]
                start = self.point_xy(shape.GetStart())
                end = self.point_xy(shape.GetEnd())
                width = float(shape.GetWidth())
            except Exception:
                continue
            if start is not None and end is not None:
                segments.append((start, end, width))
        return tuple(segments)

    def item_width(self, item):
        if self.is_via(item):
            return self.via_width(item)
        if self.is_pad(item):
            size_x, size_y = self.pad_size_mm(item)
            width = min(abs(size_x or 0.0), abs(size_y or 0.0))
            if width > 0:
                return int(width * 1000000.0)
            return 0
        # Items that are not recognised as pads but carry pad-like geometry
        # (e.g. renamed PAD class in newer KiCad) should still use pad_size_mm
        # rather than blindly calling GetWidth which may not exist or may
        # require a different signature on those objects.
        if hasattr(item, "GetSizeX") and hasattr(item, "GetSizeY"):
            size_x, size_y = self.pad_size_mm(item)
            width = min(abs(size_x or 0.0), abs(size_y or 0.0))
            if width > 0:
                return int(width * 1000000.0)
            return 0
        if not hasattr(item, "GetWidth"):
            size_x, size_y = self.pad_size_mm(item)
            width = min(abs(size_x or 0.0), abs(size_y or 0.0))
            if width > 0:
                return int(width * 1000000.0)
            return 0
        if hasattr(item, "GetWidth"):
            try:
                return item.GetWidth()
            except Exception:
                return 0
        return 0

    def pad_size_mm(self, pad):
        size = super().pad_size_mm(pad)
        pcbnew = _pcbnew()
        try:
            is_custom = pad.GetShape() == pcbnew.PAD_SHAPE_CUSTOM
        except Exception:
            is_custom = False
        if not is_custom:
            return size
        bbox = self.item_bbox(pad)
        if bbox is None:
            return size
        width = max(0, bbox[2] - bbox[0]) / 1000000.0
        height = max(0, bbox[3] - bbox[1]) / 1000000.0
        if width > 0 and height > 0:
            return width, height
        return size

    def via_width_mm(self, item):
        return self.via_width(item) / 1000000.0

    def via_width(self, item):
        layer_id = None
        for name in ("GetLayer", "TopLayer"):
            if hasattr(item, name):
                try:
                    layer_id = getattr(item, name)()
                    break
                except Exception:
                    pass
        if layer_id is not None:
            try:
                return item.GetWidth(layer_id)
            except Exception:
                pass
        if not hasattr(item, "GetWidth"):
            return 0
        try:
            return item.GetWidth()
        except Exception:
            return 0

    def via_type(self, via):
        if hasattr(via, "GetViaType"):
            try:
                return via.GetViaType()
            except Exception:
                pass
        return super().via_type(via)

    def via_layer_pair_names(self, via):
        layers = []
        for name in ("TopLayer", "GetTopLayer", "GetLayer"):
            if hasattr(via, name):
                try:
                    layers.append(
                        self.canonical_layer_name(getattr(via, name)())
                    )
                    break
                except Exception:
                    pass
        for name in ("BottomLayer", "GetBottomLayer"):
            if hasattr(via, name):
                try:
                    layers.append(
                        self.canonical_layer_name(getattr(via, name)())
                    )
                    break
                except Exception:
                    pass
        return tuple(layer for layer in layers if layer)

    def is_micro_via(self, via):
        pcbnew = _pcbnew()
        via_type = self.via_type(via)
        for name in ("VIATYPE_MICROVIA", "PCB_VIA_T_MICROVIA"):
            if hasattr(pcbnew, name) and via_type == getattr(pcbnew, name):
                return True
        return "micro" in str(via_type or "").lower()

    def is_blind_buried_via(self, via):
        pcbnew = _pcbnew()
        via_type = self.via_type(via)
        for name in ("VIATYPE_THROUGH", "PCB_VIA_T_THROUGH"):
            if hasattr(pcbnew, name) and via_type == getattr(pcbnew, name):
                return False
        for name in ("VIATYPE_BLIND_BURIED", "PCB_VIA_T_BLIND_BURIED"):
            if hasattr(pcbnew, name) and via_type == getattr(pcbnew, name):
                return True
        if self.is_micro_via(via):
            return True
        try:
            layer_pair = {via.TopLayer(), via.BottomLayer()}
            if layer_pair == {pcbnew.F_Cu, pcbnew.B_Cu}:
                return False
        except Exception:
            pass
        return super().is_blind_buried_via(via)

    def is_round_pth_pad(self, pad):
        pcbnew = _pcbnew()
        # Drill shape numeric values changed in KiCad 9, so use version constants.
        pth = getattr(pcbnew, "PAD_ATTRIB_PTH", 0)
        circle = getattr(pcbnew, "PAD_SHAPE_CIRCLE", 0)
        drill_circle = getattr(pcbnew, "PAD_DRILL_SHAPE_CIRCLE", 0)
        return (
            pad.GetAttribute() == pth
            and pad.GetShape() == circle
            and pad.GetDrillShape() == drill_circle
        )

    def is_smd_pad(self, pad):
        return self.pad_attribute(pad) == getattr(_pcbnew(), "PAD_ATTRIB_SMD", 1)

    def is_pth_pad(self, pad):
        return self.pad_attribute(pad) == getattr(_pcbnew(), "PAD_ATTRIB_PTH", 0)

    def is_npth_pad(self, pad):
        return self.pad_attribute(pad) == getattr(_pcbnew(), "PAD_ATTRIB_NPTH", 3)

    def pad_has_solder_mask_opening(self, pad):
        checked_layer_membership = False
        for name in ("IsOnLayer", "HasLayer"):
            if hasattr(pad, name):
                for layer in ("F_Mask", "B_Mask"):
                    try:
                        checked_layer_membership = True
                        if getattr(pad, name)(self.layer_constant(layer)):
                            return True
                    except Exception:
                        pass
        if checked_layer_membership:
            return False
        for name in ("GetLocalSolderMaskMargin", "GetSolderMaskMargin"):
            if hasattr(pad, name):
                try:
                    margin = getattr(pad, name)()
                    return margin is None or int(margin) > -min(self.pad_size_mm(pad)) * 1000000.0 / 2.0
                except Exception:
                    pass
        return True

    def is_round_drill_pad(self, pad):
        drill_circle = getattr(_pcbnew(), "PAD_DRILL_SHAPE_CIRCLE", 0)
        return self.pad_drill_shape(pad) == drill_circle

    def clear_selected(self):
        if hasattr(self.board, "ClearSelected"):
            self.board.ClearSelected()

    def clear_brightened(self):
        if hasattr(self.board, "ClearBrightened"):
            self.board.ClearBrightened()

    def set_visible_alls(self):
        if hasattr(self.board, "SetVisibleAlls"):
            self.board.SetVisibleAlls()
        if hasattr(self.board, "SetVisibleLayers"):
            layers = self.all_layers_mask()
            if layers is not None:
                self.board.SetVisibleLayers(layers)
        if hasattr(self.board, "SetVisibleElements") and hasattr(self.board, "GetVisibleElements"):
            elements = self.all_visible_elements()
            if elements is not None:
                self.board.SetVisibleElements(elements)

    def all_layers_mask(self):
        pcbnew = _pcbnew()
        if hasattr(pcbnew, "LSET") and hasattr(pcbnew.LSET, "AllLayersMask"):
            return pcbnew.LSET.AllLayersMask()
        try:
            layers = self.board.GetVisibleLayers()
            for layer_id in range(64):
                try:
                    if not hasattr(self.board, "IsLayerEnabled") or self.board.IsLayerEnabled(layer_id):
                        layers.AddLayer(layer_id)
                except Exception:
                    continue
            return layers
        except Exception:
            return None

    def all_visible_elements(self):
        try:
            elements = self.board.GetVisibleElements()
        except Exception:
            return None
        if isinstance(elements, int):
            return (1 << 32) - 1
        return elements

    def focus_on_item(self, item, layer_id=None):
        pcbnew = _pcbnew()
        if item is None:
            return False
        focus_on_item = getattr(pcbnew, "FocusOnItem", None)
        if focus_on_item is None:
            return False
        if layer_id is not None:
            try:
                focus_on_item(item, layer_id)
                return True
            except TypeError:
                pass
            except Exception:
                pass
        try:
            focus_on_item(item)
            return True
        except Exception:
            return False

    def refresh(self):
        _pcbnew().Refresh()

    def update_user_interface(self):
        _pcbnew().UpdateUserInterface()

    def item_id(self, item):
        if hasattr(item, "GetUuid"):
            try:
                return self._uuid_text(item.GetUuid())
            except Exception:
                pass
        if hasattr(item, "m_Uuid"):
            try:
                return self._uuid_text(item.m_Uuid)
            except Exception:
                pass
        return ""

    def resolve_item(self, item_id):
        if not item_id:
            return None
        item_id = str(item_id)
        if hasattr(self.board, "ResolveItem"):
            try:
                item = self.board.ResolveItem(item_id)
                if item is not None:
                    return item
            except TypeError:
                pass
        item = self._items_by_id().get(item_id)
        if item is not None:
            return item
        return None

    def _resolve_child_item(self, item, item_id):
        if hasattr(item, "Pads"):
            for pad in item.Pads():
                if self.item_id(pad) == item_id:
                    return pad
        return None

    def _items_by_id(self):
        if self._item_cache is None:
            self._item_cache = {}
            for items in (
                self.iter_tracks(),
                self.iter_footprints(),
                self.iter_zones(),
                self.iter_drawings(),
            ):
                for item in items:
                    self._cache_item(item)
                    if hasattr(item, "Pads"):
                        for pad in item.Pads():
                            self._cache_item(pad)
        return self._item_cache

    def _cache_item(self, item):
        item_id = self.item_id(item)
        if item_id:
            self._item_cache[item_id] = item

    def _uuid_text(self, uuid):
        if uuid is None:
            return ""
        for name in ("AsString", "asString", "ToString", "GetString"):
            if hasattr(uuid, name):
                value = getattr(uuid, name)()
                if value:
                    return str(value)
        return str(uuid)

    def plot_gerber_layer(self, plot_controller, layer_info):
        pcbnew = _pcbnew()
        name, layer_id, description = layer_info
        plot_options = plot_controller.GetPlotOptions()
        plot_options.SetSkipPlotNPTH_Pads(layer_id <= pcbnew.B_Cu)
        plot_controller.SetLayer(layer_id)
        if not plot_controller.OpenPlotfile(name, pcbnew.PLOT_FORMAT_GERBER, description):
            raise ExportError("Failed to open plot file for {0}".format(description))
        if not plot_controller.PlotLayer():
            raise ExportError("Failed to plot layer {0}".format(description))

    def create_plot_controller(self, output_dir):
        pcbnew = _pcbnew()
        plot_controller = pcbnew.PLOT_CONTROLLER(self.board)
        plot_options = plot_controller.GetPlotOptions()
        plot_options.SetOutputDirectory(output_dir)
        plot_options.SetFormat(1)
        plot_options.SetPlotValue(True)
        plot_options.SetPlotReference(True)
        plot_options.SetSketchPadsOnFabLayers(False)
        plot_options.SetUseGerberProtelExtensions(False)
        plot_options.SetCreateGerberJobFile(False)
        plot_options.SetSubtractMaskFromSilk(True)
        plot_options.SetUseAuxOrigin(True)
        plot_options.SetUseGerberX2format(True)
        plot_options.SetIncludeGerberNetlistInfo(True)
        plot_options.SetDisableGerberMacros(False)
        if hasattr(pcbnew, "DRILL_MARKS_NO_DRILL_SHAPE"):
            plot_options.SetDrillMarksType(pcbnew.DRILL_MARKS_NO_DRILL_SHAPE)
        plot_options.SetPlotFrameRef(False)
        return plot_controller

    def export_drill(self, output_dir):
        pcbnew = _pcbnew()
        writer = pcbnew.EXCELLON_WRITER(self.board)
        offset = self.board.GetDesignSettings().GetAuxOrigin()
        writer.SetOptions(False, False, offset, False)
        writer.SetFormat(False)
        writer.CreateDrillandMapFilesSet(output_dir, True, True)

    def layer_constant(self, name):
        pcbnew = _pcbnew()
        return getattr(pcbnew, name)

    def _major_version(self):
        version = str(self.version() or "")
        try:
            return int(version.split(".", 1)[0])
        except (TypeError, ValueError):
            return 0
