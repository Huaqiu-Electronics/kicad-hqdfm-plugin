import wx
import os
from kicad_dfm.hole_childframe.ui_hole_childframe import UiHoleChildframe
from kicad_dfm.manager.rule_manager_view import RuleManagerView
import builtins
from kicad_dfm import PLUGIN_ROOT
from kicad_dfm.language.lang_const import LANG_DOMAIN

builtins.__dict__["_"] = wx.GetTranslation


class eUpdateMainFrame(UiHoleChildframe):
    def __init__(self, parent):
        locale = None
        # locale = wx.Locale(wx.LANGUAGE_ENGLISH)
        locale = wx.Locale(wx.LANGUAGE_CHINESE_SIMPLIFIED)
        if locale.IsOk():
            locale.AddCatalogLookupPathPrefix(
                os.path.join(PLUGIN_ROOT, "language", "locale")
            )
            ibRet = locale.AddCatalog(LANG_DOMAIN)

        UiHoleChildframe.__init__(self, parent)


class MyApp(wx.App):
    def OnInit(self):
        self.frame = RuleManagerView(None)
        # self.frame = wx.Frame(None, title="My App")  # Create a wx.Frame instance
        # self.panel = UiHoleChildframe(self.frame)     # Create a UiDfmMaindialog panel instance
        self.frame.Show()
        return True


if __name__ == "__main__":
    app = MyApp(False)
    app.MainLoop()
