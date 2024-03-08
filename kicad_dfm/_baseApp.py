import wx
import os
import sys
from pcbnew import *
from wx.lib.mixins.inspection import InspectionMixin
from .dfm_mainframe import DfmMainframe
import builtins
from kicad_dfm import PLUGIN_ROOT
from kicad_dfm.language.lang_const import LANG_DOMAIN

# add translation macro to builtin similar to what gettext does
builtins.__dict__["_"] = wx.GetTranslation


def _displayHook(obj):
    if obj is not None:
        print(repr(obj))


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

        self.startup()
        return None

    def startup(self):
        DfmMainframe(None).Show()
