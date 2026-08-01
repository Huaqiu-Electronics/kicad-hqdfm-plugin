from __future__ import annotations

import os

FILE_ROOT = os.path.dirname(__file__)
PLUGIN_ROOT = os.path.dirname(__file__)


def GetFilePath(filename: str) -> str:
    return os.path.join(FILE_ROOT, filename)
