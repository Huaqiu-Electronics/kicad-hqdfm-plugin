class ScanFinding:
    __slots__ = (
        "item",
        "message",
        "severity",
        "category",
        "value",
        "layer",
        "raw",
        "rule",
        "color",
    )

    def __init__(
        self,
        item,
        message,
        severity="warning",
        category="",
        value=None,
        layer=None,
        raw=None,
        rule="",
        color="",
    ):
        self.item = item
        self.message = message
        self.severity = severity
        self.category = category
        self.value = value
        self.layer = layer
        self.raw = raw or {}
        self.rule = rule
        self.color = color


class GerberScan:
    __slots__ = (
        "path",
        "layer",
        "is_copper",
        "is_edge",
        "segments",
        "primitives",
        "clear_masks",
        "clear_mask_starts",
        "clear_mask_max_width",
        "sorted_clear_masks",
        "findings",
        "widths",
        "visible_primitives",
        "file_function",
        "coordinate_resolution_mm",
        "units",
    )

    def __init__(self, path, layer, is_copper=False, is_edge=False):
        self.path = path
        self.layer = layer
        self.is_copper = is_copper
        self.is_edge = is_edge
        self.segments = []
        self.primitives = []
        self.clear_masks = []
        self.clear_mask_starts = None
        self.clear_mask_max_width = None
        self.sorted_clear_masks = None
        self.findings = []
        self.widths = set()
        self.visible_primitives = None
        self.file_function = ""
        self.coordinate_resolution_mm = None
        self.units = "mm"


class ExcellonScan:
    __slots__ = (
        "path",
        "layer",
        "primitives",
        "findings",
        "plated",
        "file_function",
        "coordinate_resolution_mm",
        "units",
        "layer_span",
    )

    def __init__(self, path):
        self.path = path
        self.layer = ["Drl"]
        self.primitives = []
        self.findings = []
        self.plated = None
        self.file_function = ""
        self.coordinate_resolution_mm = None
        self.units = "inch"
        self.layer_span = None
