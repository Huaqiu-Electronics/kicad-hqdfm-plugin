"""Standalone entry point for debugging outside KiCad.

Usage:
    uv run python __main__.py
"""

import sys

import wx


class StandAloneApp(wx.App):
    def __init__(
        self,
        redirect: bool = False,
        filename: str | None = None,
        useBestVisual: bool = False,
        clearSigInt: bool = True,
    ) -> None:
        super().__init__(redirect, filename, useBestVisual, clearSigInt)

    def OnInit(self) -> bool:
        return True


if __name__ == "__main__":
    try:
        from kicad_dfm._main import _main
    except ImportError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.stderr.write("This plugin requires KiCad's Python environment or the pcbnew stub.\n")
        sys.exit(1)

    app = StandAloneApp()
    _main()
    app.MainLoop()
