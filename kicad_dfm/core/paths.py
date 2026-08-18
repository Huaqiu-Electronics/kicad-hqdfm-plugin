import os
import tempfile


PLUGIN_ROOT = os.path.dirname(os.path.dirname(__file__))


def plugin_root():
    return PLUGIN_ROOT


def resource_path(*parts):
    return os.path.join(PLUGIN_ROOT, *parts)


def temp_dir(*parts):
    path = os.path.join(tempfile.gettempdir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path
