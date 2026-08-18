import wx
import os
import logging

from kicad_dfm.services.offline_analysis import COMPAT_CATEGORIES


class _FrameSetting:
    # 只出现一个查看窗口
    def have_same_class_window(self):
        for line in self.line_list:
            self.board.Delete(line)
        title_name = list(COMPAT_CATEGORIES)
        windows = wx.GetTopLevelWindows()
        dfm_analysis_window = [w for w in windows if w.GetTitle() in title_name]

        if len(dfm_analysis_window) != 0:
            for window in dfm_analysis_window:
                window.Destroy()


FRAME_SETTING = _FrameSetting()
