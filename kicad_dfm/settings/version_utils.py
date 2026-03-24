import pcbnew  # type: ignore
import os
import json
import wx

def get_version():
    # ki_version = pcbnew.GetBuildVersion().split(".")
    # major = ki_version[0]
    # minor = ki_version[1]
    # patch = ki_version[2]
    # # 组合成浮点数
    # version_float = float(major + "." + minor + patch)
    ki_version = pcbnew.GetBuildVersion().split(".")[0:2]
    version_float = float('.'.join( ki_version )) 
    # print(f"{ float('.'.join( ki_version ))  }")
    return version_float  # e.g GetBuildVersion(): e.g. '7.99.0-3969-gc5ac2337e4'


def is_v9(version = get_version()):
    return version >= 8.99 and version < 9.99

def is_v8(version = get_version()):
    return version >= 7.99 and version < 8.99

def plot_text(popt):
    version = get_version()
    
    if  is_v9(version):
        return
    else:
        return popt.SetPlotInvisibleText(False)

def footprint_get_field(footprint, field_name):
    version = get_version()
    
    if is_v8(version) or is_v9(version):
        return footprint.GetFieldByName(field_name).GetText()
    else:
        return footprint.GetProperty(field_name)
