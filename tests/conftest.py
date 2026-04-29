"""Pytest configuration: injects a pcbnew stub so tests can import kicad_dfm modules.

The stub is loaded via importlib.util (not a normal import) to avoid making
the ``tests`` package itself depend on the stub module at collection time.
"""

import importlib.util
import os
import sys


def _inject_pcbnew_stub() -> None:
    if "pcbnew" in sys.modules:
        return
    stub_path = os.path.join(os.path.dirname(__file__), "pcbnew_stub.py")
    spec = importlib.util.spec_from_file_location("pcbnew", stub_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load pcbnew stub from {stub_path}"
        raise RuntimeError(msg)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pcbnew"] = mod
    spec.loader.exec_module(mod)


_inject_pcbnew_stub()
