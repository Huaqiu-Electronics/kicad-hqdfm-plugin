from __future__ import annotations

import pcbnew

from kicad_dfm.constants import KICAD_V8_MAX, KICAD_V8_MIN, KICAD_V9_MAX, KICAD_V9_MIN


def get_version():
    ki_version = pcbnew.GetBuildVersion().split(".")[0:2]
    return float(".".join(ki_version))


def is_v9(version=None):
    if version is None:
        version = get_version()
    return KICAD_V9_MIN <= version < KICAD_V9_MAX


def is_v8(version=None):
    if version is None:
        version = get_version()
    return KICAD_V8_MIN <= version < KICAD_V8_MAX


def plot_text(popt):
    version = get_version()

    if is_v9(version):
        return None
    return popt.SetPlotInvisibleText(False)


def footprint_get_field(footprint, field_name):
    version = get_version()

    if is_v8(version) or is_v9(version):
        return footprint.GetFieldByName(field_name).GetText()
    return footprint.GetProperty(field_name)
