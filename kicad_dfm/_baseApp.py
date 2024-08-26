import wx
import os
import sys
from pcbnew import *
from wx.lib.mixins.inspection import InspectionMixin
from .dfm_mainframe import DfmMainframe
import builtins
from kicad_dfm import PLUGIN_ROOT
from kicad_dfm.language.lang_const import LANG_DOMAIN
import socket
import multiprocessing

# add translation macro to builtin similar to what gettext does
builtins.__dict__["_"] = wx.GetTranslation


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

        wx.Locale.AddCatalogLookupPathPrefix(
            os.path.join(PLUGIN_ROOT, "language", "locale")
        )
        existing_locale = wx.GetLocale()
        if existing_locale is not None:
            existing_locale.AddCatalog(LANG_DOMAIN)

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
