from dataclasses import dataclass, field

from kicad_dfm.kicad.swig import SwigBackend


NATIVE_DRC_MARKER_KEYS = (
    "generic_warning",
    "track_width",
    "clearance",
    "annular_width",
    "drill_out_of_range",
    "copper_edge_clearance",
    "hole_clearance",
)

NATIVE_DRC_CATEGORY_KEYS = {
    "Smallest Trace Width": ("track_width",),
    "Smallest Trace Spacing": ("clearance",),
    "SMD Spacing": ("clearance",),
    "Drill Hole Spacing": ("hole_clearance", "clearance"),
    "Copper-to-Board Edge": ("copper_edge_clearance", "edge_clearance"),
    "Drill to Copper": ("hole_clearance", "clearance"),
    "RingHole": ("annular_width",),
    "Hole Size": ("drill_out_of_range",),
    "Pad size": ("generic_warning", "clearance"),
}


@dataclass
class NativeDrcMarkerExportResult:
    markers: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


class NativeDrcMarkerExporter:
    def __init__(self, board, backend=None, marker_factory=None, marker_keys=None):
        self.board = board
        self.backend = backend or SwigBackend(board)
        self.marker_factory = marker_factory
        self.marker_keys = tuple(marker_keys or NATIVE_DRC_MARKER_KEYS)
        self.markers = []

    def export(self, plan, category=None):
        result = NativeDrcMarkerExportResult()
        factory = self.marker_factory or self._default_marker_factory()
        if factory is None:
            result.skipped.extend(plan.items)
            return result

        marker_keys = self._marker_keys_for(category)
        for item in plan.items:
            marker = self._create_item_marker(factory, item, marker_keys)
            if marker is None:
                result.skipped.append(item)
                continue
            self.backend.add_board_item(marker)
            self.markers.append(marker)
            result.markers.append(marker)
        return result

    def clear(self):
        for marker in list(self.markers):
            self.backend.delete_board_item(marker)
        self.markers.clear()

    def _marker_keys_for(self, category):
        keys = list(NATIVE_DRC_CATEGORY_KEYS.get(category, ()))
        keys.extend(key for key in self.marker_keys if key not in keys)
        return tuple(keys)

    def _create_item_marker(self, factory, item, marker_keys):
        item_id = self.backend.item_id(item)
        if not item_id:
            return None
        position = self._item_position(item)
        if position is None:
            return None
        layer_name = self.backend.item_layer_name(item) or "F.Cu"
        x, y = position
        for key in marker_keys:
            for payload in self._payloads(key, x, y, item_id, layer_name):
                marker = self._try_factory(factory, payload)
                if marker is not None:
                    return marker
        return None

    def _item_position(self, item):
        position = self.backend.item_position(item)
        if position is not None:
            return position
        bounds = self.backend.item_bbox(item)
        if not bounds:
            return None
        left, top, right, bottom = bounds
        return int((left + right) / 2), int((top + bottom) / 2)

    def _payloads(self, key, x, y, item_id, layer_name):
        empty_uuid = "00000000-0000-0000-0000-000000000000"
        return (
            "{0}|{1}|{2}|{3}|{4}".format(key, x, y, item_id, layer_name),
            "{0}|{1}|{2}|{3}|{3}".format(key, x, y, item_id),
            "{0}|{1}|{2}|{3}|{4}".format(key, x, y, item_id, empty_uuid),
        )

    def _try_factory(self, factory, payload):
        try:
            return factory(payload)
        except Exception:
            return None

    def _default_marker_factory(self):
        try:
            import pcbnew
        except Exception:
            return None
        marker_class = getattr(pcbnew, "PCB_MARKER", None)
        if marker_class is not None:
            for name in ("DeserializeFromString", "Deserialize"):
                factory = getattr(marker_class, name, None)
                if factory is not None:
                    return factory
        return getattr(pcbnew, "PCB_MARKER_Deserialize", None)
