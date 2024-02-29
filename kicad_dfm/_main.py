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
        # windows = wx.GetTopLevelWindows()
        # pcb_window = [
        #     w
        #     for w in windows
        #     if "pcb editor" in w.GetTitle().lower() or "pcb 编辑器" in w.GetTitle().lower()
        # ]
        # # wx.MessageBox(f"pcb_window:{pcb_window}。")
        # if len(pcb_window) != 1:
        #     dialog_ad_footprint.DialogADFootprint(None).Show()
        # else:
        #     if (
        #         pcb_window[0].GetTitle().lower() == "pcb editor"
        #         or pcb_window[0].GetTitle().lower() == "pcb 编辑器"
        #     ):
        #         wx.MessageBox("文件为空", "Help", style=wx.ICON_INFORMATION)
        #     else:
        #         dialog_ad_footprint.DialogADFootprint(pcb_window[0]).Show()
