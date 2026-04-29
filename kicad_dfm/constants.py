"""Named constants for the kicad-hqdfm-plugin.

Centralises every magic number so there is a single source of truth.
Import from here instead of hardcoding literals.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import TypedDict

# ── KiCad internal-unit conversion ────────────────────────────────────
NM_PER_MM = 1_000_000
NM_PER_CM = 10_000_000
NM_PER_M = 1_000_000_000
NM_PER_INCH = 25_400_000
MM_PER_INCH = 25.4
MILS_PER_MM = 39.3701


# ── Pad / footprint attribute flags ───────────────────────────────────
class PadAttribute(IntEnum):
    THT = 0
    SMD = 1
    EXCLUDE_FROM_POS = 2
    EXCLUDE_FROM_BOM = 3
    NOT_IN_SCHEMATIC = 4
    NPTH = 3


# Legacy aliases for backward compatibility.
PAD_ATTR_THT = PadAttribute.THT
PAD_ATTR_SMD = PadAttribute.SMD
PAD_ATTR_EXCLUDE_FROM_POS = PadAttribute.EXCLUDE_FROM_POS
PAD_ATTR_EXCLUDE_FROM_BOM = PadAttribute.EXCLUDE_FROM_BOM
PAD_ATTR_NOT_IN_SCHEMATIC = PadAttribute.NOT_IN_SCHEMATIC
PAD_ATTR_NPTH = PadAttribute.NPTH


# ── Pad shape identifiers ────────────────────────────────────────────
class PadShape(IntEnum):
    CIRCLE = 0
    RECT = 1
    OVAL = 2


PAD_SHAPE_CIRCLE = PadShape.CIRCLE
PAD_SHAPE_RECT = PadShape.RECT
PAD_SHAPE_OVAL = PadShape.OVAL


# ── Drill shape identifiers ───────────────────────────────────────────
class DrillShape(IntEnum):
    CIRCLE = 0


DRILL_SHAPE_CIRCLE = DrillShape.CIRCLE


# ── PCB shape type identifiers ────────────────────────────────────────
class PcbShape(IntEnum):
    SEGMENT = 0
    ARC = 1
    RECT = 2


PCB_SHAPE_SEGMENT = PcbShape.SEGMENT
PCB_SHAPE_ARC = PcbShape.ARC
PCB_SHAPE_RECT = PcbShape.RECT


# ── Fill mode ─────────────────────────────────────────────────────────
class ZoneFillMode(IntEnum):
    HATCHED = 1


ZONE_FILL_MODE_HATCHED = ZoneFillMode.HATCHED


# ── Unit selection (combo-box indices in the UI) ──────────────────────
UNIT_MM = 0
UNIT_INCH = 5
UNIT_MILS = 5  # same value as inch in this plugin


# ── Analysis result colours ───────────────────────────────────────────
class Colour(str, Enum):
    RED = "red"
    GOLD = "gold"
    BLACK = "black"


COLOUR_RED = Colour.RED
COLOUR_GOLD = Colour.GOLD
COLOUR_BLACK = Colour.BLACK
VALID_COLOURS = frozenset({Colour.RED, Colour.GOLD, Colour.BLACK})


# ── Analysis item names ───────────────────────────────────────────────
# Used as keys in the DFM analysis-result dicts.  Members hold the
# English name; each also has a translated label via _() in the UI layer.
class AnalysisItem(str, Enum):
    SIGNAL_INTEGRITY = "Signal Integrity"
    SMALLEST_TRACE_WIDTH = "Smallest Trace Width"
    SMALLEST_TRACE_SPACING = "Smallest Trace Spacing"
    PAD_SIZE = "Pad size"
    PAD_SPACING = "Pad Spacing"
    HATCHED_COPPER_POUR = "Hatched Copper Pour"
    HOLE_DIAMETER = "Hole Diameter"
    RINGHOLE = "RingHole"
    DRILL_HOLE_SPACING = "Drill Hole Spacing"
    DRILL_TO_COPPER = "Drill to Copper"
    COPPER_TO_BOARD_EDGE = "Copper-to-Board Edge"
    SPECIAL_DRILL_HOLES = "Special Drill Holes"
    HOLES_ON_SMD_PADS = "Holes on SMD Pads"
    MISSING_SMASK_OPENINGS = "Missing SMask Openings"
    DRILL_HOLE_DENSITY = "Drill Hole Density"
    SURFACE_FINISH_AREA = "Surface Finish Area"
    TEST_POINT_COUNT = "Test Point Count"


# ── Analysis sub-item names ───────────────────────────────────────────
# Nested items returned inside each AnalysisItem's "check" list.
class _SubItem(str, Enum):
    VIA_ANNULAR_RING = "Via Annular Ring"
    PTH_ANNULAR_RING = "PTH Annular Ring"
    SHORT_PADS = "Short Pads"
    LONG_PADS = "Long Pads"
    SMALLEST_TRACE_WIDTH = "Smallest Trace Width"
    GRID_WIDTH = "Grid Width"
    GRID_SPACING = "Grid Spacing"
    PAD_SPACING = "Pad Spacing"
    ASPECT_RATIO = "Aspect Ratio"


# ── KiCad version boundaries (from GetBuildVersion) ───────────────────
KICAD_V8_MIN = 7.99
KICAD_V8_MAX = 8.99
KICAD_V9_MIN = 8.99
KICAD_V9_MAX = 9.99


# ── wxWidgets version boundary ────────────────────────────────────────
# wxWidgets 3.1.5 introduced some API changes (BitmapBundle etc.)
WX_VERSION_BOUNDARY = 315


# ── Sentinel / fallback values ────────────────────────────────────────
SENTINEL_UNSET = -1
SENTINEL_DISPLAY_NORMAL = "正常"
SENTINEL_DISTANCE_FALLBACK = 1_000_000  # returned when point is off segment
SENTINEL_UNKNOWN_VERSION = "unknown"


# ── Default geometry ──────────────────────────────────────────────────
WINDOW_DEFAULT_WIDTH = 490
WINDOW_DEFAULT_HEIGHT = 830


# ── Row heights per platform (CustomRenderer) ─────────────────────────
ROW_HEIGHT_WINDOWS = 35
ROW_HEIGHT_LINUX = 32
ROW_HEIGHT_MACOS = 35
ROW_HEIGHT_FALLBACK = 35


# ── HTTP / API constants ──────────────────────────────────────────────
HTTP_TIMEOUT_SEC = 20
HTTP_CHUNK_SIZE = 8192
HTTP_SLEEP_POLL_SEC = 1.5
HTTP_SLEEP_RETRY_SEC = 1
HTTP_MAX_RETRIES = 5

# Return / status codes from the DFM API
API_CODE_SUCCESS = 2000
API_CODE_SUCCESS_ALT_200 = 200
API_CODE_SUCCESS_ALT_50000 = 50000
API_CODE_PENDING = 22006


# ── Drawing / rendering constants ─────────────────────────────────────
MARKER_LINE_WIDTH_NM = 100_000  # 0.1 mm
MARKER_HALF_SIZE_NM = 250_000  # 0.25 mm half-side for square markers
ERROR_ACCURACY_NM = 30_000  # HitTest tolerance
LINE_WIDTH_EXTENT_NM = 80_000  # on-segment tolerance
EDGE_WIDTH_EXTENT_NM = 100_000  # board-edge proximity tolerance


# ── UI column indices ─────────────────────────────────────────────────
COL_INDEX_ITEM = 0
COL_INDEX_DISPLAY = 1
COL_WIDTH_ITEM = 170
COL_WIDTH_DISPLAY_AUTO = -1


# ── Decimal precision ─────────────────────────────────────────────────
PRECISION_STANDARD = 3
PRECISION_ASPECT_RATIO = 2


# ── UI defaults ───────────────────────────────────────────────────────
SPLITTER_SASH_DEFAULT = 432


# ── Progress-bar step values ──────────────────────────────────────────
PROGRESS_MAX = 100
PROGRESS_START = 5
PROGRESS_POLL_START = 30
PROGRESS_POLL_CAP = 90
PROGRESS_POLL_STEP = 2
PROGRESS_DOWNLOAD = 20
PROGRESS_DONE = 100


# ── Layer IDs (KiCad internal) ────────────────────────────────────────
# Mapping from logical names to layer IDs for the layer-conversion table.
LAYER_F_CU = 0
LAYER_F_MASK = 1
LAYER_B_CU = 2
LAYER_B_MASK = 3
LAYER_IN2_CU = 4
LAYER_F_SILK = 5
LAYER_IN3_CU = 6
LAYER_B_SILK = 7
LAYER_EDGE_CUTS = 25
LAYER_B_PASTE = 33
LAYER_F_PASTE = 35
LAYER_INNER_START = 8
LAYER_INNER_END = 66  # exclusive upper bound
LAYER_INNER_STEP = 2
LAYER_COUNT_MAX = 82

# Numéro de couche pour pcb_setting.py (Edge_Cuts drawing check)
EDGE_CUTS_LAYER_ID = 44


# ── Board layer count constants (create_file.py) ──────────────────
BOARD_LAYERS_SINGLE = 1
BOARD_LAYERS_DOUBLE = 2
BOARD_LAYERS_4 = 4
BOARD_LAYERS_6 = 6


# ── Gerber format ─────────────────────────────────────────────────
GERBER_FORMAT = 1


# ── Pad-size threshold (long pad vs short pad) ────────────────────
PAD_LONG_THRESHOLD_MM = 1.2


# ── Type aliases for common data structures ──────────────────────────


class _LineDict(TypedDict):
    """Start/end coordinates for a line segment (nm or IU)."""

    start_x: int
    start_y: int
    end_x: int
    end_y: int
