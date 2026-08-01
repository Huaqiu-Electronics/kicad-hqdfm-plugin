# Building kicad-hqdfm-plugin

## Preparation

1. Install wxBuilder:
   https://github.com/wxFormBuilder/wxFormBuilder

2. Install gettext:
   https://mlocati.github.io/articles/gettext-iconv-windows.html

3. Install POedit:
   https://poedit.net/download

## Developer setup (uv)

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```sh
# Install uv (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install dev dependencies
make install
```

## Available commands

```sh
make install       # Create venv and install dev dependencies (ruff, pytest, pre-commit, wxPython)
make lint          # Run ruff check
make format        # Auto-format code with ruff
make format-check  # Check formatting without modifying
make test          # Run pytest
make check         # Run lint + format-check + test
make pre-commit    # Run all pre-commit hooks
make clean         # Remove venv and cache directories
```

## Pre-commit hooks

Pre-commit hooks are configured in `.pre-commit-config.yaml` and run automatically on `git commit`. They include:

- **ruff** — linter (import sorting, error detection, etc.)
- **ruff-format** — code formatter
- **mypy** — static type checking (on `kicad_dfm/utils/` and `tests/`)
- **typos** — spell checker
- **trailing-whitespace**, **end-of-file-fixer**, **check-yaml**, **check-toml** — general hygiene

To run all hooks manually:

```sh
make pre-commit
```

## Python environment

When running inside KiCad, the plugin uses the Python bundled with KiCad
(e.g., `C:\Program Files\KiCad\8.0\bin\python`).

## Running tests

Tests are in the `tests/` directory. They use:

- **`tests/pcbnew_stub.py`** — a mock for KiCad's `pcbnew` module, injected automatically by `conftest.py`
- **wxPython** — installed from PyPI for modules that import `wx`

Tests that only depend on pure logic (`kicad_dfm/utils/pure.py`) do not need wxPython at all.

```sh
# Run all tests
make test

# Run a specific test file
uv run pytest tests/unit/test_pure.py -v
```

## Project structure

```
kicad_dfm/
├── utils/
│   ├── pure.py              # Pure functions (no wx/pcbnew deps)
│   └── CustomRenderer.py    # Custom wx DataView renderer
├── helpers.py               # Mixed helpers (re-exports from pure.py)
├── plugin.py                # KiCad ActionPlugin entry point
├── ...
```

## Update translation

1. Extract po files from py:

```sh
xgettext.exe xxx.py
```

2. Edit the po files in Poedit

## Debug

The `__main__.py` is the entry point for debugging:

```sh
uv run python __main__.py
```

## Deploy

Copy the whole project directory into KiCad's `3rdparty/plugins/` directory.
