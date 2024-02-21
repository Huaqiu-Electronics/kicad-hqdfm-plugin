import pcbnew
import os
import wx
from pcbnew import *


# 插件入口
class Plugin(pcbnew.ActionPlugin):
    def __init__(self):
        self.name = "Active Manufacturing"  # 插件名称
        self.category = "Manufacturing"  # 描述性类别名称
        self.description = "Quote and place order with one button click."  # 对插件及其功能的描述
        self.pcbnew_icon_support = hasattr(self, "show_toolbar_button")
        self.show_toolbar_button = True  # 可选，默认为 False
        self.icon_file_name = os.path.join(
            os.path.dirname(__file__), "icon.png"
        )  # 可选，默认为 ""
        self.dark_icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        from kicad_dfm._main import _main

        _main()
