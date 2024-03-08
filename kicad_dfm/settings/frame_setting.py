import wx
import os
import logging


class _FrameSetting:
    # 只出现一个查看窗口
    def have_same_class_window(self):
        for line in self.line_list:
            self.board.Delete(line)
        title_name = [
            "Signal Integrity",
            "Smallest Trace Width",
            "Smallest Trace Spacing",
            "Pad size",
            "Pad Spacing",
            "Hatched Copper Pour",
            "Hole Diameter",
            "RingHole",
            "Drill Hole Spacing",
            "Drill to Copper",
            "Board Edge Clearance",
            "Special Drill Holes",
            "Holes on SMD Pads",
            "Missing SMask Openings",
            "Drill Hole Density",
            "Surface Finish Area",
            "Test Point Count",
        ]
        windows = wx.GetTopLevelWindows()
        dfm_analysis_window = [w for w in windows if w.GetTitle() in title_name]

        if len(dfm_analysis_window) != 0:
            for window in dfm_analysis_window:
                window.Destroy()


FRAME_SETTING = _FrameSetting()
