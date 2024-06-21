import wx
import os
from .kicad_setting import KiCadSetting
import wx.lib.newevent as ne

LocaleChangeEvent, EVT_LOCALE_CHANGE = ne.NewCommandEvent()

APP_NAME = "kicad_hqdfm_plugin"

VENDOR_NAME = "NextPCB"

LANGUAGE = "language"


WIDTH = "width"

HEIGHT = "height"

MAIN_WINDOW_SASH_POS = "main_window_sash_pos"

SPLITTER_DETAIL_SUMMARY = "splitter_detail_summary"


PRICE_UNIT = {0: "¥", 1: "$"}

TRANSLATED_PRICE_UNIT = {"¥": "元", "$": "美元"}


CN_JP_BUILD_TIME_FORMATTER = "{time}{unit}"

EN_BUILD_TIME_FORMATTER = "{time} {unit}"


class _SettingManager(wx.EvtHandler):
    def __init__(self) -> None:
        self.app: wx.App = None
        sp = wx.StandardPaths.Get()
        config_loc = sp.GetUserConfigDir()
        config_loc = os.path.join(config_loc, f".{APP_NAME}")

        if not os.path.exists(config_loc):
            os.mkdir(config_loc)

        self.app_conf = wx.FileConfig(
            appName=APP_NAME,
            vendorName=VENDOR_NAME,
            localFilename=os.path.join(config_loc, "common.ini"),
        )

        if not self.app_conf.HasEntry(LANGUAGE):
            self.set_language(KiCadSetting.read_lang_setting())
            self.app_conf.Flush()

    def register_app(self, app: wx.App):
        self.app = app

    def set_language(self, now: int):
        old = self.get_language()
        try:
            now = int(now)
        except ValueError:
            # 处理 'now' 不是有效整数的情况
            return
        if old == now:
            return
        self.app_conf.WriteInt(key=LANGUAGE, value=now)
        if self.app:
            evt = LocaleChangeEvent(id=-1)
            evt.SetInt(now)
            self.app_conf.Flush()
            wx.PostEvent(self.app, evt)

    def get_language(self) -> int:
        return self.app_conf.ReadInt(LANGUAGE)

    def set_window_size(self, s: "tuple[int,int]"):
        self.app_conf.WriteInt(key=WIDTH, value=s[0])
        self.app_conf.WriteInt(key=HEIGHT, value=s[1])
        self.app_conf.Flush()

    def set_summary_detail_sash_pos(self, pos: int):
        self.app_conf.WriteInt(key=SPLITTER_DETAIL_SUMMARY, value=int(pos))
        self.app_conf.Flush()

    def get_summary_detail_sash_pos(self):
        return self.app_conf.ReadInt(SPLITTER_DETAIL_SUMMARY, 432)


SETTING_MANAGER = _SettingManager()
