import pytest

from kicad_dfm.constants import (
    API_CODE_PENDING,
    API_CODE_SUCCESS,
    DRILL_SHAPE_CIRCLE,
    EDGE_CUTS_LAYER_ID,
    EDGE_WIDTH_EXTENT_NM,
    ERROR_ACCURACY_NM,
    HTTP_CHUNK_SIZE,
    HTTP_MAX_RETRIES,
    HTTP_SLEEP_POLL_SEC,
    HTTP_TIMEOUT_SEC,
    KICAD_V8_MAX,
    KICAD_V8_MIN,
    KICAD_V9_MAX,
    KICAD_V9_MIN,
    LAYER_COUNT_MAX,
    LAYER_EDGE_CUTS,
    LAYER_F_CU,
    LAYER_INNER_END,
    LAYER_INNER_START,
    LAYER_INNER_STEP,
    LINE_WIDTH_EXTENT_NM,
    MARKER_HALF_SIZE_NM,
    MARKER_LINE_WIDTH_NM,
    MILS_PER_MM,
    MM_PER_INCH,
    NM_PER_CM,
    NM_PER_INCH,
    NM_PER_MM,
    PAD_ATTR_EXCLUDE_FROM_BOM,
    PAD_ATTR_EXCLUDE_FROM_POS,
    PAD_ATTR_NOT_IN_SCHEMATIC,
    PAD_ATTR_NPTH,
    PAD_ATTR_SMD,
    PAD_ATTR_THT,
    PAD_SHAPE_CIRCLE,
    PAD_SHAPE_OVAL,
    PAD_SHAPE_RECT,
    PCB_SHAPE_ARC,
    PCB_SHAPE_RECT,
    PCB_SHAPE_SEGMENT,
    PRECISION_ASPECT_RATIO,
    PRECISION_STANDARD,
    PROGRESS_MAX,
    PROGRESS_START,
    ROW_HEIGHT_FALLBACK,
    ROW_HEIGHT_LINUX,
    ROW_HEIGHT_MACOS,
    ROW_HEIGHT_WINDOWS,
    SENTINEL_DISPLAY_NORMAL,
    SENTINEL_DISTANCE_FALLBACK,
    SENTINEL_UNKNOWN_VERSION,
    SENTINEL_UNSET,
    UNIT_INCH,
    UNIT_MM,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WX_VERSION_BOUNDARY,
    ZONE_FILL_MODE_HATCHED,
    Colour,
    DrillShape,
)

pytestmark = pytest.mark.pure


class TestUnitConversion:
    def test_nm_per_mm(self):
        assert NM_PER_MM == 1_000_000

    def test_nm_per_cm(self):
        assert NM_PER_CM == 10_000_000

    def test_nm_per_inch(self):
        assert NM_PER_INCH == 25_400_000

    def test_mm_per_inch(self):
        assert MM_PER_INCH == 25.4

    def test_mils_per_mm(self):
        assert MILS_PER_MM > 39.37


class TestPadAttributes:
    def test_values_are_consecutive(self):
        vals = {
            PAD_ATTR_THT,
            PAD_ATTR_SMD,
            PAD_ATTR_EXCLUDE_FROM_POS,
            PAD_ATTR_EXCLUDE_FROM_BOM,
            PAD_ATTR_NOT_IN_SCHEMATIC,
        }
        assert vals == {0, 1, 2, 3, 4}

    def test_npth_is_three(self):
        assert PAD_ATTR_NPTH == 3


class TestPadShape:
    def test_circle_is_zero(self):
        assert PAD_SHAPE_CIRCLE == 0

    def test_rect_is_one(self):
        assert PAD_SHAPE_RECT == 1

    def test_oval_is_two(self):
        assert PAD_SHAPE_OVAL == 2


class TestDrillShape:
    def test_circle_is_zero(self):
        assert DRILL_SHAPE_CIRCLE == 0


class TestPcbShape:
    def test_segment_is_zero(self):
        assert PCB_SHAPE_SEGMENT == 0

    def test_arc_is_one(self):
        assert PCB_SHAPE_ARC == 1

    def test_rect_is_two(self):
        assert PCB_SHAPE_RECT == 2


class TestVersionBoundaries:
    def test_v8_range(self):
        assert KICAD_V8_MIN < KICAD_V8_MAX

    def test_v9_range(self):
        assert KICAD_V9_MIN < KICAD_V9_MAX

    def test_no_gap(self):
        assert KICAD_V9_MIN == KICAD_V8_MAX

    def test_wx_boundary(self):
        assert WX_VERSION_BOUNDARY == 315


class TestSentinels:
    def test_unset_is_negative(self):
        assert SENTINEL_UNSET == -1

    def test_display_normal_is_chinese(self):
        assert SENTINEL_DISPLAY_NORMAL == "正常"

    def test_distance_fallback_large(self):
        assert SENTINEL_DISTANCE_FALLBACK == 1_000_000

    def test_unknown_version(self):
        assert SENTINEL_UNKNOWN_VERSION == "unknown"


class TestGeometry:
    def test_window_defaults(self):
        assert WINDOW_DEFAULT_WIDTH == 490
        assert WINDOW_DEFAULT_HEIGHT == 830

    def test_row_heights(self):
        assert ROW_HEIGHT_WINDOWS == 35
        assert ROW_HEIGHT_LINUX == 32
        assert ROW_HEIGHT_MACOS == 35
        assert ROW_HEIGHT_FALLBACK == 35


class TestHTTP:
    def test_timeout(self):
        assert HTTP_TIMEOUT_SEC == 20

    def test_chunk_size(self):
        assert HTTP_CHUNK_SIZE == 8192

    def test_poll_interval(self):
        assert HTTP_SLEEP_POLL_SEC == 1.5

    def test_max_retries(self):
        assert HTTP_MAX_RETRIES == 5

    def test_api_codes(self):
        assert API_CODE_SUCCESS == 2000
        assert API_CODE_PENDING == 22006


class TestDrawing:
    def test_marker_width(self):
        assert MARKER_LINE_WIDTH_NM == 100_000

    def test_marker_half_size(self):
        assert MARKER_HALF_SIZE_NM == 250_000

    def test_error_accuracy(self):
        assert ERROR_ACCURACY_NM == 30_000

    def test_line_width_extent(self):
        assert LINE_WIDTH_EXTENT_NM == 80_000

    def test_edge_width_extent(self):
        assert EDGE_WIDTH_EXTENT_NM == 100_000


class TestLayerConstants:
    def test_f_cu(self):
        assert LAYER_F_CU == 0

    def test_edge_cuts(self):
        assert LAYER_EDGE_CUTS == 25

    def test_layer_count_max(self):
        assert LAYER_COUNT_MAX == 82

    def test_inner_start(self):
        assert LAYER_INNER_START == 8

    def test_inner_end(self):
        assert LAYER_INNER_END == 66

    def test_inner_step(self):
        assert LAYER_INNER_STEP == 2

    def test_edge_cuts_layer_id(self):
        assert EDGE_CUTS_LAYER_ID == 44


class TestPrecision:
    def test_standard(self):
        assert PRECISION_STANDARD == 3

    def test_aspect_ratio(self):
        assert PRECISION_ASPECT_RATIO == 2


class TestProgress:
    def test_max(self):
        assert PROGRESS_MAX == 100

    def test_start(self):
        assert PROGRESS_START == 5


class TestFillMode:
    def test_hatched(self):
        assert ZONE_FILL_MODE_HATCHED == 1


class TestUnits:
    def test_mm(self):
        assert UNIT_MM == 0

    def test_inch(self):
        assert UNIT_INCH == 5


class TestColourEnum:
    def test_members(self):
        assert Colour.RED == "red"
        assert Colour.GOLD == "gold"
        assert Colour.BLACK == "black"

    def test_is_str(self):
        assert isinstance(Colour.RED, str)

    def test_unique_values(self):
        values = {m.value for m in Colour}
        assert values == {"red", "gold", "black"}


class TestPadAttributeEnum:
    def test_member_values(self):
        from kicad_dfm.constants import PadAttribute

        assert PadAttribute.THT == 0
        assert PadAttribute.SMD == 1
        assert PadAttribute.EXCLUDE_FROM_POS == 2
        assert PadAttribute.EXCLUDE_FROM_BOM == 3
        assert PadAttribute.NOT_IN_SCHEMATIC == 4

    def test_npth_same_as_bom(self):
        from kicad_dfm.constants import PadAttribute

        assert PadAttribute.NPTH == PadAttribute.EXCLUDE_FROM_BOM


class TestPadShapeEnum:
    def test_member_values(self):
        from kicad_dfm.constants import PadShape

        assert PadShape.CIRCLE == 0
        assert PadShape.RECT == 1
        assert PadShape.OVAL == 2


class TestDrillShapeEnum:
    def test_member_values(self):

        assert DrillShape.CIRCLE == 0


class TestPcbShapeEnum:
    def test_member_values(self):
        from kicad_dfm.constants import PcbShape

        assert PcbShape.SEGMENT == 0
        assert PcbShape.ARC == 1
        assert PcbShape.RECT == 2


class TestZoneFillModeEnum:
    def test_member_values(self):
        from kicad_dfm.constants import ZoneFillMode

        assert ZoneFillMode.HATCHED == 1
