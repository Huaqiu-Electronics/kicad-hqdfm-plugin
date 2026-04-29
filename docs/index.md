# kicad-hqdfm-plugin

One-click PCB design flaw analysis plugin for KiCad.

## Quick start

```sh
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install dev tools
make install

# Run lint, typecheck, and tests
make check
```

## Project structure

```
kicad_dfm/
├── constants.py          # Named constants for all magic numbers
├── models.py             # Pydantic v2 models (optional dependency)
├── utils/
│   ├── pure.py           # Pure functions (zero external deps)
│   └── CustomRenderer.py # wx DataView custom renderer
├── analysis.py           # Local KiCad analysis logic
├── plugin.py             # KiCad ActionPlugin entry point
├── helpers.py            # Mixed helpers (re-exports from pure.py)
└── ...

tests/
├── unit/                 # Unit tests (pytest)
├── pcbnew_stub.py        # Stub module for KiCad's pcbnew
├── conftest.py           # Test configuration
└── test_pcbnew_stub.py   # Stub completeness tests
```

## Python version

This plugin targets **KiCad 8+** and requires **Python 3.10+**.

## Dependencies

| Tool      | Required | Purpose                    |
|-----------|----------|----------------------------|
| Pydantic  | Optional | Analysis result validation |
| wxPython  | Required | KiCad UI framework         |
| pcbnew    | Required | KiCad PCB editor API       |
