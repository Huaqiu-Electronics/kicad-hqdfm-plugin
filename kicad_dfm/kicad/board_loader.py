"""Helpers for loading KiCad boards outside the interactive editor."""

import os


def load_board_noninteractive(board_path):
    """Load a board without allowing wx log warnings to open modal dialogs.

    KiCad reports recoverable load warnings (for example, a missing font that
    can be substituted) through wx logging.  The default wx log target may be
    a modal dialog, which blocks unattended verification processes forever.
    Route those messages to stderr only for the duration of ``LoadBoard`` and
    always restore the caller's log target afterwards.

    The imports intentionally live inside this function so importing this
    module from a normal Python parent process does not require KiCad or wx.
    """

    import pcbnew

    path = os.fspath(board_path)
    try:
        import wx
    except ImportError:
        return pcbnew.LoadBoard(path)

    try:
        stderr_target = wx.LogStderr()
        set_active_target = wx.Log.SetActiveTarget
    except (AttributeError, TypeError):
        return pcbnew.LoadBoard(path)

    previous_target = set_active_target(stderr_target)
    try:
        return pcbnew.LoadBoard(path)
    finally:
        set_active_target(previous_target)
