import os

from kicad_dfm.child_frame.picture_catalog import PICTURE_BY_ITEM
from kicad_dfm.picture import GetImagePath


def normalize(value):
    return " ".join(str(value or "").strip().lower().split())


PICTURE_NAMES = {
    normalize(alias): picture_name
    for picture_name, aliases in PICTURE_BY_ITEM.items()
    for alias in aliases
}


def picture_name_for(value):
    return PICTURE_NAMES.get(normalize(value))


def picture_bitmap_for(value, language_string):
    import wx

    picture_name = picture_name_for(value)
    if picture_name:
        path = GetImagePath(picture_name + language_string)
        if os.path.exists(path):
            return wx.Bitmap(path)
    return wx.Bitmap(GetImagePath("none.png"))


class _PictureMatchPath:
    def picture_path(self, string, language_string):
        # A visible fallback is friendlier than a blank detail image.
        return picture_bitmap_for(string, language_string)

    def GetImagePath(self, bitmap_path):
        return GetImagePath(bitmap_path)


PICTURE_MATCH_PATH = _PictureMatchPath
