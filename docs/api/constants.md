# `kicad_dfm.constants`

Single source of truth for all magic numbers, enums, and configuration constants.

## Unit conversion

| Constant | Value | Description |
|---|---|---|
| `NM_PER_MM` | `1_000_000` | Nanometres per millimetre |
| `NM_PER_CM` | `10_000_000` | Nanometres per centimetre |
| `NM_PER_INCH` | `25_400_000` | Nanometres per inch |
| `MM_PER_INCH` | `25.4` | Millimetres per inch |
| `MILS_PER_MM` | `39.3701` | Mils per millimetre |

## Enums

### `PadAttribute(IntEnum)`

KiCad pad/footprint attribute flags.

| Member | Value | Description |
|---|---|---|
| `THT` | `0` | Through-hole |
| `SMD` | `1` | Surface-mount |
| `EXCLUDE_FROM_POS` | `2` | Exclude from position file |
| `EXCLUDE_FROM_BOM` | `3` | Exclude from BOM |
| `NOT_IN_SCHEMATIC` | `4` | Not in schematic |
| `NPTH` | `3` | Non-plated through-hole (alias for `EXCLUDE_FROM_BOM`) |

### `PadShape(IntEnum)`

KiCad pad shape identifiers.

| Member | Value |
|---|---|
| `CIRCLE` | `0` |
| `RECT` | `1` |
| `OVAL` | `2` |

### `DrillShape(IntEnum)`

| Member | Value |
|---|---|
| `CIRCLE` | `0` |

### `PcbShape(IntEnum)`

KiCad PCB shape type identifiers.

| Member | Value |
|---|---|
| `SEGMENT` | `0` |
| `ARC` | `1` |
| `RECT` | `2` |

### `ZoneFillMode(IntEnum)`

| Member | Value |
|---|---|
| `HATCHED` | `1` |

### `Colour(str, Enum)`

Analysis result colour indicators.

| Member | Value |
|---|---|
| `RED` | `"red"` |
| `GOLD` | `"gold"` |
| `BLACK` | `"black"` |

## Version boundaries

| Constant | Value | Description |
|---|---|---|
| `KICAD_V8_MIN` | `7.99` | Minimum version for KiCad 8 |
| `KICAD_V8_MAX` | `8.99` | Maximum version for KiCad 8 |
| `KICAD_V9_MIN` | `8.99` | Minimum version for KiCad 9 |
| `KICAD_V9_MAX` | `9.99` | Maximum version for KiCad 9 |
| `WX_VERSION_BOUNDARY` | `315` | wxWidgets 3.1.5 API boundary |

## Sentinel values

| Constant | Value | Description |
|---|---|---|
| `SENTINEL_UNSET` | `-1` | Unset/initial value |
| `SENTINEL_DISPLAY_NORMAL` | `"正常"` | Normal display string |
| `SENTINEL_DISTANCE_FALLBACK` | `1_000_000` | Off-segment distance |
| `SENTINEL_UNKNOWN_VERSION` | `"unknown"` | Version string fallback |

## HTTP/API

| Constant | Value |
|---|---|
| `HTTP_TIMEOUT_SEC` | `20` |
| `HTTP_CHUNK_SIZE` | `8192` |
| `HTTP_SLEEP_POLL_SEC` | `1.5` |
| `HTTP_MAX_RETRIES` | `5` |
| `API_CODE_SUCCESS` | `2000` |
| `API_CODE_PENDING` | `22006` |
