import wx
import sys
from pcbnew import *
from wx.lib.mixins.inspection import InspectionMixin
from .dialog_ad_footprint import DialogADFootprint


def _displayHook(obj):
    if obj is not None:
        print(repr(obj))


def _main():
    app = BaseApp()


class BaseApp(wx.EvtHandler):
    def __init__(self):
        super().__init__()
        sys.displayhook = _displayHook
        self.locale = None
        self.startup()
        return None

    def startup(self):
        DialogADFootprint(None).Show()
