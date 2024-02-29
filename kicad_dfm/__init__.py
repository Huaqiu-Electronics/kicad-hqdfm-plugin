import os

FILE_ROOT = os.path.dirname(__file__)


def GetFilePath(filename):
    return os.path.join(FILE_ROOT, filename)
