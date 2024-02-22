import os

ICON_ROOT = os.path.dirname(__file__)


def GetImagePath(bitmap):
    return os.path.join(ICON_ROOT, bitmap)
