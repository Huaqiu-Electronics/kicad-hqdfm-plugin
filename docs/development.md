# Development

## Setup

```sh
make install   # create venv and install all dev tools
```

## Commands

| Command            | Description                            |
|--------------------|----------------------------------------|
| `make lint`        | Run ruff check                         |
| `make format`      | Auto-format code                       |
| `make format-check`| Check formatting (CI)                  |
| `make typecheck`   | Run pyright static type checking       |
| `make test`        | Run pytest                             |
| `make pure-test`   | Run only zero-dependency pure tests    |
| `make check`       | Run lint + format-check + typecheck + test |
| `make pre-commit`  | Run all pre-commit hooks               |
| `make coverage`    | Run tests with coverage report         |
| `make clean`       | Remove venv and caches                 |

## Code style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.
Configuration is in `pyproject.toml`.

### Active lint rules

- `E` / `W` — pycodestyle
- `F` — pyflakes
- `I` — isort
- `N` — naming
- `UP` — pyupgrade (Python 3.10+)
- `S` — bandit (security)
- `B` — flake8-bugbear
- `C4` — flake8-comprehensions
- `RUF` — ruff-specific
- `SIM` — flake8-simplify
- `T20` — flake8-print
- `RET` — consistent return statements
- `ANN` — type annotations (enforced on new code)
- `PIE` — opinionated patterns
- `RSE` — consistent raise
- `SLF` — private member access
- `T10` — no debugger breakpoints
- `ISC` — no implicit string concatenation

## Pre-commit hooks

All hooks run automatically on `git commit`. To run manually:

```sh
make pre-commit
```

Hooks: check-yaml, check-toml, end-of-file-fixer, trailing-whitespace,
check-added-large-files, ruff check, ruff format, typos.

## Testing

```sh
make test          # all tests
make pure-test     # tests with zero external dependencies
```

Tests are in `tests/unit/`. The `tests/pcbnew_stub.py` module provides
KiCad API stubs so tests can run without KiCad installed.
