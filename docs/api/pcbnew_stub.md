# `tests/pcbnew_stub`

Mock module for KiCad's ``pcbnew`` API, used when running tests outside
KiCad.  Injected into ``sys.modules["pcbnew"]`` by ``tests/conftest.py``
at pytest collection time.

All classes are empty stubs — they provide enough structure for imports
to succeed without any KiCad runtime.  The
:doc:`/api/test_pcbnew_stub` test verifies that every symbol imported
from ``pcbnew`` in the actual codebase has a corresponding stub.
