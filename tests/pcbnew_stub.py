"""Stub module for KiCad's ``pcbnew``, used when testing outside KiCad.

This provides empty/trivial implementations of all pcbnew classes,
functions, and constants used by the plugin, so tests can import
and exercise logic without KiCad installed.

The ``test_pcbnew_stub.py`` test verifies that every symbol imported
from ``pcbnew`` in the actual codebase has a matching stub here.
"""

# ── Layer / shape constants ──────────────────────────────────────────
F_Cu = 0
In1_Cu = 1
In2_Cu = 2
In3_Cu = 3
In4_Cu = 4
F_Mask = 5
F_Paste = 6
F_SilkS = 7
B_Cu = 8
B_Mask = 9
B_Paste = 10
B_SilkS = 11
Cmts_User = 12
Edge_Cuts = 13
Dwgs_User = 14
B_Adhes = 15
LAYER_DRC_WARNING = 16

S_SEGMENT = 0
S_ARC = 1
S_RECT = 2

DRILL_MARKS_NO_DRILL_SHAPE = 0
PLOT_FORMAT_GERBER = 0


# ── Types used in isinstance() checks ────────────────────────────────
class ActionPlugin:
    name = ""
    category = ""
    description = ""
    show_toolbar_button = False
    icon_file_name = ""
    dark_icon_file_name = ""

    def Run(self):
        pass

    def register(self):
        pass


class PCB_TRACK:
    pass


class PCB_VIA:
    pass


class PCB_SHAPE:
    pass


class PCB_TEXT:
    pass


class VECTOR2I:
    def __init__(self, x=0, y=0):
        self.x = x
        self.y = y


class LSET:
    pass


class SETTINGS_MANAGER:
    @staticmethod
    def GetUserSettingsPath():
        import tempfile

        return tempfile.gettempdir()


class PLOT_CONTROLLER:
    def __init__(self, _board=None):
        self._options = PCB_PLOT_PARAMS()

    def GetPlotOptions(self):
        return self._options

    def SetLayer(self, layer):
        pass

    def OpenPlotfile(self, _name, _fmt, _desc):
        return True

    def PlotLayer(self):
        return True

    def ClosePlot(self):
        pass


class PCB_PLOT_PARAMS:
    def SetOutputDirectory(self, path):
        pass

    def SetFormat(self, val):
        pass

    def SetPlotValue(self, val):
        pass

    def SetPlotReference(self, val):
        pass

    def SetSketchPadsOnFabLayers(self, val):
        pass

    def SetUseGerberProtelExtensions(self, val):
        pass

    def SetCreateGerberJobFile(self, val):
        pass

    def SetSubtractMaskFromSilk(self, val):
        pass

    def SetUseAuxOrigin(self, val):
        pass

    def SetUseGerberX2format(self, val):
        pass

    def SetIncludeGerberNetlistInfo(self, val):
        pass

    def SetDisableGerberMacros(self, val):
        pass

    def SetDrillMarksType(self, val):
        pass

    def SetPlotFrameRef(self, val):
        pass

    def SetSkipPlotNPTH_Pads(self, val):
        pass

    def SetPlotInvisibleText(self, val):
        pass


class EXCELLON_WRITER:
    def __init__(self, _board=None):
        pass

    def SetOptions(self, mirror, minimal_header, offset, merge_NPTH):
        pass

    def SetFormat(self, val):
        pass

    def CreateDrillandMapFilesSet(self, path, gen_drl, gen_map):
        pass


class ZONE_FILLER:
    def __init__(self, _board=None):
        pass

    def Fill(self, board):
        pass


# ── Functions ────────────────────────────────────────────────────────
def GetLanguage():
    return "en"


def GetBoard():
    return None


def LoadBoard(_path):
    return None


def GetUserUnits():
    return 0


def UpdateUserInterface():
    pass


def Refresh():
    pass


def SaveBoard(path, board):
    pass


def GetBuildVersion():
    return "8.0.0"


def FocusOnItem(item, layer=None, item_type=None):
    pass


def ToMM(val):
    return val / 1000000.0
