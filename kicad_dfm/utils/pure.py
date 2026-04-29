"""Pure functions with zero external dependencies.

These functions can be imported and tested without KiCad or wxPython.
They operate on primitive types only (int, str, tuple, list, dict).
"""

from __future__ import annotations

import re


def get_bit(value: int, bit: int) -> int:
    """Return the ``bit``-th bit of *value* as a masked integer.

    Use as a truthy check::

        is_tht = bool(get_bit(attributes, 0))

    Returns ``0`` if the bit is not set, or ``1 << bit`` if it is set.
    """
    return value & (1 << bit)


def set_bit(value: int, bit: int) -> int:
    """Set the ``bit``-th bit of *value* and return the result."""
    return value | (1 << bit)


def clear_bit(value: int, bit: int) -> int:
    """Clear the ``bit``-th bit of *value* and return the result."""
    return value & ~(1 << bit)


def toggle_bit(value: int, bit: int) -> int:
    """Toggle the ``bit``-th bit of *value* and return the result."""
    return value ^ (1 << bit)


def natural_sort_collation(a: str, b: str) -> int:
    """Compare two strings using natural (human-friendly) ordering.

    Numeric segments are compared by their integer value rather than
    lexicographically, so ``"item2" < "item10"`` is ``True``.

    Returns ``-1`` if *a* sorts before *b*, ``0`` if equal, ``1`` otherwise.

    Use with ``functools.cmp_to_key``::

        sorted(items, key=cmp_to_key(natural_sort_collation))
    """
    if a == b:
        return 0

    def _convert(text: str) -> int | str:
        return int(text) if text.isdigit() else text.lower()

    def _yellownum_key(key: str) -> list[int | str]:
        return [_convert(c) for c in re.split(r"([0-9]+)", key)]

    natorder = sorted([a, b], key=_yellownum_key)
    return -1 if natorder.index(a) == 0 else 1
