# `kicad_dfm.utils.pure`

Zero-dependency pure functions extracted from the plugin core.

## Bit manipulation

```python
def get_bit(value: int, bit: int) -> int
def set_bit(value: int, bit: int) -> int
def clear_bit(value: int, bit: int) -> int
def toggle_bit(value: int, bit: int) -> int
```

These operate on individual bits of an integer value, matching
KiCad's pad attribute bitfield layout:

- Bit 0: THT
- Bit 1: SMD
- Bit 2: Exclude from POS
- Bit 3: Exclude from BOM
- Bit 4: Not in schematic

## Sorting

```python
def natural_sort_collation(a: str, b: str) -> int
```

Comparator for natural (human-friendly) sorting of strings containing
numbers. Returns `-1`, `0`, or `1` like `functools.cmp_to_key`.

"item2" < "item10"  (unlike plain lexicographic sort)
"a1b2"  < "a1b10"
