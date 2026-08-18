from kicad_dfm.kicad.backend import BackendCapabilities, BoardBackend


class IpcUnavailable(Exception):
    pass


class IpcBackend(BoardBackend):
    kind = "ipc"

    def __init__(self, client=None):
        super().__init__(None)
        self.client = client
        self.unavailable_reason = ""

    @classmethod
    def connect(cls):
        try:
            kicad = _kicad_python()
        except IpcUnavailable as exc:
            backend = cls()
            backend.unavailable_reason = str(exc)
            return backend
        try:
            client = kicad.KiCad()
        except Exception as exc:
            backend = cls()
            backend.unavailable_reason = str(exc)
            return backend
        return cls(client)

    def available(self):
        return self.client is not None

    def capabilities(self):
        return BackendCapabilities(
            can_plot=False,
            can_drill=False,
            can_highlight=False,
            can_resolve_item=False,
            can_iter_zones=False,
        )

    def version(self):
        if not self.available():
            return ""
        for name in ("version", "Version", "get_version"):
            attr = getattr(self.client, name, None)
            if callable(attr):
                return str(attr())
            if attr is not None:
                return str(attr)
        return ""

    def board_name(self):
        board = self.current_board()
        if board is None:
            return ""
        for name in ("name", "title", "filename"):
            value = getattr(board, name, None)
            if value:
                return str(value)
        return ""

    def current_board(self):
        if not self.available():
            return None
        for name in ("get_board", "GetBoard", "board"):
            attr = getattr(self.client, name, None)
            if callable(attr):
                return attr()
            if attr is not None:
                return attr
        return None


def _kicad_python():
    try:
        import kicad
    except ImportError as exc:
        raise IpcUnavailable("kicad-python is not installed") from exc
    return kicad
