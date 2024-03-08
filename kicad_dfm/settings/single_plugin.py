import wx


class _SinglePlugin:
    def __init__(self) -> None:
        self.app: wx.App = None
        self.wind: wx.TopLevelWindow = None

    def register_main_wind(self, wind: wx.TopLevelWindow):
        self.wind = wind

    def get_main_wind(self):
        return self.wind

    def show_existing(self):
        if not self.wind is None:
            self.wind.Show(False)
            self.wind.Show(True)
            return True
        return False


SINGLE_PLUGIN = _SinglePlugin()
