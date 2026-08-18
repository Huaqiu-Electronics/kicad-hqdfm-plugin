from dataclasses import dataclass
from enum import Enum

from kicad_dfm.core import http
from kicad_dfm.core.settings import load_settings


class WorkflowState(Enum):
    IDLE = "idle"
    EXPORTING = "exporting"
    UPLOADING = "uploading"
    PARSING = "parsing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Workflow:
    state: WorkflowState = WorkflowState.IDLE
    can_cancel: bool = False
    error: str = ""

    @property
    def running(self):
        return self.state in (
            WorkflowState.EXPORTING,
            WorkflowState.UPLOADING,
            WorkflowState.PARSING,
        )

    def start_export(self):
        return self.start_analysis()

    def start_analysis(self):
        if self.running:
            return False
        self.state = WorkflowState.EXPORTING
        self.can_cancel = True
        self.error = ""
        return True

    def uploading(self):
        self.state = WorkflowState.UPLOADING

    def parsing(self):
        self.state = WorkflowState.PARSING

    def done(self):
        self.state = WorkflowState.DONE
        self.can_cancel = False

    def fail(self, error):
        self.state = WorkflowState.FAILED
        self.error = str(error)
        self.can_cancel = False

    def cancel(self):
        if self.can_cancel:
            self.state = WorkflowState.CANCELLED
            self.can_cancel = False


def load_ui_settings():
    return load_settings()


HQ_DFM_CN_URL = "https://dfm.hqpcb.com"
HQ_DFM_EN_URL = "https://www.nextpcb.com/dfm"
# Backward-compatible alias for integrations that imported the original
# single-language constant.
HQ_DFM_URL = HQ_DFM_CN_URL


def hq_dfm_url(language):
    """Return the regional DFM site for the active UI language."""
    value = str(language or "").strip()
    normalized = value.lower().replace("-", "_")
    if (
        not value
        or normalized in ("default", "zh", "zh_cn", "zh_hans")
        or normalized.startswith("zh_")
        or "中文" in value
        or "chinese" in normalized
    ):
        return HQ_DFM_CN_URL
    return HQ_DFM_EN_URL


SUMMARY_ITEMS = (
    "Layer Count",
    "Dimensions",
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


def default_summary_map(translate=None):
    translate = translate or (lambda value: value)
    return {translate(item): {"display": "", "color": ""} for item in SUMMARY_ITEMS}


def select_language_control(language, config_module):
    if language in ("简体中文", "Default", ""):
        return config_module.Language_chinese
    if language == "English":
        return config_module.Language_english
    return None


def format_board_dimensions(value):
    """Format a millimetre ``width*height`` value with a fixed mm unit."""
    parts = str(value or "").split("*")
    if len(parts) != 2:
        return "0 mm" if str(value or "") == "0" else str(value or "")
    try:
        width_mm, height_mm = (float(part) for part in parts)
    except (TypeError, ValueError):
        return str(value or "")

    formatted = [str(round(number, 3)) for number in (width_mm, height_mm)]
    return "{0}*{1} mm".format(formatted[0], formatted[1])


def fetch_country():
    try:
        data = http.get_json("https://ipinfo.io/json")
        return (data or {}).get("country")
    except Exception:
        return None
