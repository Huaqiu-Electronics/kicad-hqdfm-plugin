from kicad_dfm._baseApp import BaseApp
from kicad_dfm.settings.single_plugin import SINGLE_PLUGIN


def main():
    if not SINGLE_PLUGIN.show_existing():
        BaseApp()
