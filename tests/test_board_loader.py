import sys
import types
import unittest
from unittest import mock

from kicad_dfm.kicad.board_loader import load_board_noninteractive


class BoardLoaderTest(unittest.TestCase):
    @staticmethod
    def fake_wx(previous_target, events):
        state = {"active": previous_target}
        stderr_target = object()

        class Log:
            @staticmethod
            def SetActiveTarget(target):
                old_target = state["active"]
                state["active"] = target
                events.append(("target", target))
                return old_target

        return (
            types.SimpleNamespace(Log=Log, LogStderr=lambda: stderr_target),
            state,
            stderr_target,
        )

    def test_redirects_wx_log_target_only_while_loading(self):
        previous_target = object()
        events = []
        fake_wx, state, stderr_target = self.fake_wx(previous_target, events)
        board = object()

        def load_board(path):
            events.append(("load", path, state["active"]))
            return board

        fake_pcbnew = types.SimpleNamespace(LoadBoard=load_board)
        with mock.patch.dict(
            sys.modules, {"pcbnew": fake_pcbnew, "wx": fake_wx}
        ):
            result = load_board_noninteractive("example.kicad_pcb")

        self.assertIs(board, result)
        self.assertEqual(
            [
                ("target", stderr_target),
                ("load", "example.kicad_pcb", stderr_target),
                ("target", previous_target),
            ],
            events,
        )
        self.assertIs(previous_target, state["active"])

    def test_restores_wx_log_target_when_loading_raises(self):
        previous_target = object()
        events = []
        fake_wx, state, stderr_target = self.fake_wx(previous_target, events)

        def load_board(_path):
            self.assertIs(stderr_target, state["active"])
            raise RuntimeError("invalid board")

        fake_pcbnew = types.SimpleNamespace(LoadBoard=load_board)
        with mock.patch.dict(
            sys.modules, {"pcbnew": fake_pcbnew, "wx": fake_wx}
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid board"):
                load_board_noninteractive("broken.kicad_pcb")

        self.assertIs(previous_target, state["active"])
        self.assertEqual(
            [("target", stderr_target), ("target", previous_target)], events
        )

    def test_loads_normally_when_wx_is_unavailable(self):
        board = object()
        calls = []
        fake_pcbnew = types.SimpleNamespace(
            LoadBoard=lambda path: calls.append(path) or board
        )

        with mock.patch.dict(
            sys.modules, {"pcbnew": fake_pcbnew, "wx": None}
        ):
            result = load_board_noninteractive("headless.kicad_pcb")

        self.assertIs(board, result)
        self.assertEqual(["headless.kicad_pcb"], calls)


if __name__ == "__main__":
    unittest.main()
