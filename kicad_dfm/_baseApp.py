import wx
import sys
from wx.lib.mixins.inspection import InspectionMixin
from .dfm_mainframe import DfmMainframe
from kicad_dfm.core.i18n import init_i18n
from kicad_dfm.settings.kicad_setting import KiCadSetting
import socket
import multiprocessing
import pcbnew

init_i18n(KiCadSetting.read_lang_setting(), wx_module=wx)


def _displayHook(obj):
    if obj is not None:
        print(repr(obj))


def create_shared_memory(size):
    # 创建一块大小为 `size` 的共享内存
    shm = multiprocessing.shared_memory.create("my_shm", size=size)
    print(f"Shared memory created with size: {size} bytes")
    return shm


class BaseApp(wx.EvtHandler):
    def __init__(self):
        super().__init__()
        sys.displayhook = _displayHook

        init_i18n(KiCadSetting.read_lang_setting(), wx_module=wx)

        print(wx.__version__)
        self.startup()
        return None

    def __del__(self):
        # destructor
        from kicad_dfm.settings.single_plugin import SINGLE_PLUGIN

        SINGLE_PLUGIN.register_main_wind(None)

    def startup(self):

        for win in wx.GetTopLevelWindows():
            if win.GetTitle() == _("HQ DFM"):
                win.Destroy()


        windows = wx.GetTopLevelWindows()
        pcb_window = [w for w in windows if _("pcb editor") in w.GetTitle().lower()]

        # if len(pcb_window) != 1:
        #     DfmMainframe(None).Show()
        # else:
        #     if pcb_window[0].GetTitle().lower() == _("pcb editor"):
        #         wx.MessageBox(_("File is empty"), _("Help"), style=wx.ICON_INFORMATION)
        #     else:
        #         DfmMainframe(pcb_window[0]).Show()
        if pcb_window:
            DfmMainframe(pcb_window[0]).Show()
        else:
            DfmMainframe(None).Show()
