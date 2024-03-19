import wx
from kicad_dfm.picture import GetImagePath


class _PictureMatchPath:
    def picture_path(self, string, language_string):
        json_string = string.lower()
        if json_string == "acute angle traces" or json_string == "锐角":
            return wx.Bitmap(self.GetImagePath("acute_angle" + language_string))
        elif json_string == "unconnected traces" or json_string == "断头线":
            return wx.Bitmap(self.GetImagePath("breakage_line" + language_string))
        elif json_string == "floating copper" or json_string == "孤立铜":
            return wx.Bitmap(self.GetImagePath("isolated_copper" + language_string))

        elif json_string == "unconnected vias" or json_string == "无效过孔":
            return wx.Bitmap(self.GetImagePath("invalid_via" + language_string))

        elif json_string == "smallest trace width" or json_string == "最小线宽":
            return wx.Bitmap(self.GetImagePath("line_width" + language_string))

        elif json_string == "trace spacing" or json_string == "线到线":
            return wx.Bitmap(self.GetImagePath("line2line" + language_string))

        elif json_string == "trace-to-pad spacing" or json_string == "焊盘到线":
            return wx.Bitmap(self.GetImagePath("pad2line" + language_string))

        elif json_string == "pad spacing" or json_string == "焊盘间距":
            return wx.Bitmap(self.GetImagePath("pad2pad" + language_string))

        elif (
            json_string == "bga pads"
            or json_string == "short pads"
            or json_string == "long pads"
            or json_string == "bga焊盘"
            or json_string == "长条焊盘"
            or json_string == "常规焊盘"
        ):
            self.bmp.SetBitmap(wx.Bitmap(self.GetImagePath("bga" + language_string)))
        elif (
            json_string == "smd pad spacing"
            or json_string == "pad spacing"
            or json_string == "smd焊盘间距"
            or json_string == "焊盘间距"
        ):
            return wx.Bitmap(self.GetImagePath("pad_spacing_base" + language_string))

        elif json_string == "grid width" or json_string == "网格线宽":
            return wx.Bitmap(self.GetImagePath("grid_width" + language_string))

        elif json_string == "grid spacing" or json_string == "网格间距":
            return wx.Bitmap(self.GetImagePath("grid_spacing" + language_string))

        elif json_string == "smallest drill size" or json_string == "最小孔径":
            return wx.Bitmap(self.GetImagePath("min_diameter" + language_string))

        elif json_string == "aspect ratio" or json_string == "孔后径比":
            return wx.Bitmap(self.GetImagePath("min_thick_diameter" + language_string))

        elif json_string == "smallest slot width" or json_string == "最小槽宽":
            return wx.Bitmap(self.GetImagePath("min_slot" + language_string))

        elif json_string == "largest drill size" or json_string == "最大孔径":
            return wx.Bitmap(self.GetImagePath("max_diameter" + language_string))

        elif json_string == "largest slot width" or json_string == "最大槽宽":
            return wx.Bitmap(self.GetImagePath("max_slot" + language_string))

        elif json_string == "largest slot length" or json_string == "最大槽长":
            return wx.Bitmap(self.GetImagePath("max_slot_length" + language_string))

        elif json_string == "slot aspect ratio" or json_string == "槽长宽比":
            return wx.Bitmap(self.GetImagePath("slot_length_width" + language_string))

        elif json_string == "largest blind/buried via" or json_string == "最大盲埋孔":
            return wx.Bitmap(
                self.GetImagePath("max_diameter_blind_buried" + language_string)
            )

        elif (
            json_string == "via annular ring"
            or json_string == "pth annular ring"
            or json_string == "via孔环"
            or json_string == "pth孔环"
        ):
            return wx.Bitmap(self.GetImagePath("via_ring" + language_string))

        elif (
            json_string == "pth-to-trace (outer)"
            or json_string == "pth-to-trace (inner)"
            or json_string == "via-to-trace (outer)"
            or json_string == "via-to-trace (inner)"
            or json_string == "插件孔到表层"
            or json_string == "插件孔到内层"
            or json_string == "过孔到表层"
            or json_string == "过孔到内层"
        ):
            return wx.Bitmap(self.GetImagePath("line2pth_outer" + language_string))

        elif json_string == "npth-to-copper" or json_string == "npth铜":
            return wx.Bitmap(self.GetImagePath("npth2copper" + language_string))

        elif json_string == "smd-to-board edge" or json_string == "smd到板边":
            return wx.Bitmap(self.GetImagePath("smd2edge" + language_string))

        elif json_string == "copper-to-board edge" or json_string == "铜到板边":
            return wx.Bitmap(self.GetImagePath("copper2edge" + language_string))

        elif json_string == "square/rectangular drills" or json_string == "正长方形孔":
            return wx.Bitmap(self.GetImagePath("hole_spuared" + language_string))

        elif json_string == "castellated holes" or json_string == "半孔":
            return wx.Bitmap(self.GetImagePath("hole_half" + language_string))

        elif json_string == "via-in-pad" or json_string == "盘中孔":
            return wx.Bitmap(self.GetImagePath("resin_hole_plugging" + language_string))

        elif json_string == "pth on smd pad" or json_string == "插件孔上焊盘":
            return wx.Bitmap(self.GetImagePath("pth_insmd" + language_string))

        elif json_string.lower() == "via on smd pad".lower() or json_string == "过孔上焊盘":
            return wx.Bitmap(self.GetImagePath("via_insmd" + language_string))

        elif json_string == "npth on smd pad" or json_string == "npth孔上焊盘":
            return wx.Bitmap(self.GetImagePath("npth_insmd" + language_string))

        elif json_string == "missing smask opening" or json_string == "阻焊少开窗":
            return wx.Bitmap(self.GetImagePath("soldmask_lack" + language_string))

        elif json_string == "same net via spacing" or json_string == "通网络过孔":
            return wx.Bitmap(self.GetImagePath("via_same net" + language_string))

        elif json_string == "different net via spacing" or json_string == "不同网络过孔":
            return wx.Bitmap(self.GetImagePath("via_difference_net" + language_string))

        elif json_string == "different net pth spacing" or json_string == "不同网络插件孔":
            return wx.Bitmap(self.GetImagePath("pth_difference_net" + language_string))

        elif json_string == "blind/buried via spacing" or json_string == "盲埋孔距离":
            return wx.Bitmap(self.GetImagePath("blind2blind" + language_string))

    def GetImagePath(self, bitmap_path):
        return GetImagePath(bitmap_path)


PICTURE_MATCH_PATH = _PictureMatchPath
