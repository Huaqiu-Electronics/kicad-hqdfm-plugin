import wx
import sys
from pcbnew import *
from wx.lib.mixins.inspection import InspectionMixin
from .dialog_ad_footprint import DialogADFootprint


def _main():
    app = BaseApp()
    app.MainLoop()


class BaseApp(wx.App, InspectionMixin):
    def __init__(self):
        super().__init__()
        self.Init()
        self.locale = None
        self.startup()
        return None

    def startup(self):
        DialogADFootprint(None).Show()
