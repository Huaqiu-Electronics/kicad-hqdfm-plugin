from __future__ import annotations

import os

ICON_ROOT = os.path.dirname(__file__)


def GetImagePath(bitmap: str) -> str:
    return os.path.join(ICON_ROOT, bitmap)
