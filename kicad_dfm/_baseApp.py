import builtins
import multiprocessing
import os
import sys

import wx

from kicad_dfm import PLUGIN_ROOT
from kicad_dfm.language.lang_const import LANG_DOMAIN

from .dfm_mainframe import DfmMainframe

# add translation macro to builtin similar to what gettext does
builtins.__dict__["_"] = wx.GetTranslation


def _displayHook(obj):
    if obj is not None:
        pass


def create_shared_memory(size):
    # 创建一块大小为 `size` 的共享内存
    return multiprocessing.shared_memory.create("my_shm", size=size)


class BaseApp(wx.EvtHandler):
    def __init__(self):
        super().__init__()
        sys.displayhook = _displayHook

        wx.Locale.AddCatalogLookupPathPrefix(os.path.join(PLUGIN_ROOT, "language", "locale"))
        existing_locale = wx.GetLocale()
        if existing_locale is not None:
            existing_locale.AddCatalog(LANG_DOMAIN)

        self.startup()
        return

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
