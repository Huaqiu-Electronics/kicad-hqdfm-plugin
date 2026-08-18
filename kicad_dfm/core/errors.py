class DfmError(Exception):
    """Base error for plugin operations."""


class ExportError(DfmError):
    """Manufacturing file export failed."""


class RemoteApiError(DfmError):
    """Remote DFM service request failed."""


class ParseError(DfmError):
    """DFM result parsing failed."""


class LocateError(DfmError):
    """Unable to locate an item on the board."""
