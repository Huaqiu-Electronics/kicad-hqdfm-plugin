import os
import re

import wx
import wx.dataview

from kicad_dfm.constants import (
    PAD_ATTR_EXCLUDE_FROM_BOM as EXCLUDE_FROM_BOM,
)
from kicad_dfm.constants import (
    PAD_ATTR_EXCLUDE_FROM_POS as EXCLUDE_FROM_POS,
)
from kicad_dfm.constants import (
    PAD_ATTR_NOT_IN_SCHEMATIC as NOT_IN_SCHEMATIC,
)
from kicad_dfm.constants import (
    PAD_ATTR_SMD as SMD,
)
from kicad_dfm.constants import (
    PAD_ATTR_THT as THT,
)
from kicad_dfm.constants import (
    WX_VERSION_BOUNDARY,
)
from kicad_dfm.utils.pure import clear_bit, get_bit, set_bit, toggle_bit

PLUGIN_PATH = os.path.split(os.path.abspath(__file__))[0]
PLUGIN_ROOT = os.path.dirname(PLUGIN_PATH)


def getWxWidgetsVersion():
    v = re.search(r"wxWidgets\s([\d\.]+)", wx.version())
    return int(v.group(1).replace(".", ""))


def getVersion():
    """READ Version from file (repo-root VERSION)."""
    version_path = os.path.join(PLUGIN_ROOT, "VERSION")
    if not os.path.isfile(version_path):
        return "unknown"
    with open(version_path) as f:
        return f.read().strip()


def GetScaleFactor(window):
    """Workaround if wxWidgets Version does not support GetDPIScaleFactor"""
    if hasattr(window, "GetDPIScaleFactor"):
        return window.GetDPIScaleFactor()
    return 1.0


def HighResWxSize(window, size):
    """Workaround if wxWidgets Version does not support FromDIP"""
    if hasattr(window, "FromDIP"):
        return window.FromDIP(size)
    return size


def loadBitmapScaled(filename, scale=1.0, static=False):
    """Load a scaled bitmap, handle differences between Kicad versions"""
    if filename:
        path = os.path.join(PLUGIN_PATH, "icons", filename)
        bmp = wx.Bitmap(path)
        w, h = bmp.GetSize()
        img = bmp.ConvertToImage()
        bmp = wx.Bitmap(img.Scale(int(w * scale), int(h * scale)))
    else:
        bmp = wx.Bitmap()
    if getWxWidgetsVersion() > WX_VERSION_BOUNDARY and not static:
        return wx.BitmapBundle(bmp)
    return bmp


def loadIconScaled(filename, scale=1.0):
    """Load a scaled icon, handle differences between Kicad versions"""
    bmp = loadBitmapScaled(filename, scale=scale, static=False)
    if getWxWidgetsVersion() > WX_VERSION_BOUNDARY:
        return bmp
    return wx.Icon(bmp)


def GetListIcon(value, scale_factor):
    if value == 0:
        return wx.dataview.DataViewIconText(
            "",
            loadIconScaled(
                "mdi-check-color.png",
                scale_factor,
            ),
        )
    return wx.dataview.DataViewIconText(
        "",
        loadIconScaled(
            "mdi-close-color.png",
            scale_factor,
        ),
    )


def get_lcsc_value(fp):
    """Get the first lcsc number (C123456 for example) from the properties of the footprint."""
    # Kicad 7.99
    try:
        for field in fp.GetFields():
            if re.match(r"^C\d+$", field.GetText()):
                return field.GetText()
    # KiCad < V7
    except AttributeError:
        for value in fp.GetProperties().values():
            if re.match(r"^C\d+$", value):
                return value
    return ""


def get_valid_footprints(board):
    """Get all footprints that have a valid reference (drop all REF**)"""
    return [fp for fp in board.GetFootprints() if re.match(r"\w+\d+", fp.GetReference())]


def get_footprint_keys(fp):
    """get keys from footprint for sorting."""
    try:
        package = str(fp.GetFPID().GetLibItemName())
    except Exception:
        package = ""
    try:
        reference = int(re.search(r"\d+", fp.GetReference())[0])
    except Exception:
        reference = 0
    return (package, reference)


def get_footprint_by_ref(board, ref):
    """get a footprint from the list of footprints by its Reference."""
    return [fp for fp in get_valid_footprints(board) if str(fp.GetReference()) == ref]


def get_tht(footprint):
    """Get the THT property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    return bool(get_bit(val, THT))


def get_smd(footprint):
    """Get the SMD property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    return bool(get_bit(val, SMD))


def get_exclude_from_pos(footprint):
    """Get the 'exclude from POS' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    return bool(get_bit(val, EXCLUDE_FROM_POS))


def get_exclude_from_bom(footprint):
    """Get the 'exclude from BOM' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    return bool(get_bit(val, EXCLUDE_FROM_BOM))


def get_not_in_schematic(footprint):
    """Get the 'not in schematic' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    return bool(get_bit(val, NOT_IN_SCHEMATIC))


def set_tht(footprint):
    """Set the THT property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = set_bit(val, THT)
    footprint.SetAttributes(val)
    return bool(get_bit(val, THT))


def set_smd(footprint):
    """Set the SMD property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = set_bit(val, SMD)
    footprint.SetAttributes(val)
    return bool(get_bit(val, SMD))


def set_exclude_from_pos(footprint, v):
    """Set the 'exclude from POS' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = set_bit(val, EXCLUDE_FROM_POS) if v else clear_bit(val, EXCLUDE_FROM_POS)
    footprint.SetAttributes(val)
    return bool(get_bit(val, EXCLUDE_FROM_POS))


def set_exclude_from_bom(footprint, v):
    """Set the 'exclude from BOM' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = set_bit(val, EXCLUDE_FROM_BOM) if v else clear_bit(val, EXCLUDE_FROM_BOM)
    footprint.SetAttributes(val)
    return bool(get_bit(val, EXCLUDE_FROM_BOM))


def set_not_in_schematic(footprint, v):
    """Set the 'not in schematic' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = set_bit(val, NOT_IN_SCHEMATIC) if v else clear_bit(val, NOT_IN_SCHEMATIC)
    footprint.SetAttributes(val)
    return bool(get_bit(val, NOT_IN_SCHEMATIC))


def toggle_tht(footprint):
    """Toggle the THT property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = toggle_bit(val, THT)
    footprint.SetAttributes(val)
    return bool(get_bit(val, THT))


def toggle_smd(footprint):
    """Toggle the SMD property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = toggle_bit(val, SMD)
    footprint.SetAttributes(val)
    return bool(get_bit(val, SMD))


def toggle_exclude_from_pos(footprint):
    """Toggle the 'exclude from POS' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = toggle_bit(val, EXCLUDE_FROM_POS)
    footprint.SetAttributes(val)
    return bool(get_bit(val, EXCLUDE_FROM_POS))


def toggle_exclude_from_bom(footprint):
    """Toggle the 'exclude from BOM' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = toggle_bit(val, EXCLUDE_FROM_BOM)
    footprint.SetAttributes(val)
    return bool(get_bit(val, EXCLUDE_FROM_BOM))


def toggle_not_in_schematic(footprint):
    """Toggle the 'not in schematic' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = toggle_bit(val, NOT_IN_SCHEMATIC)
    footprint.SetAttributes(val)
    return bool(get_bit(val, NOT_IN_SCHEMATIC))
