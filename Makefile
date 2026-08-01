.PHONY: install lint format test typecheck check pre-commit clean docs-build pure-test coverage

VENV = .venv
PYTHON = $(VENV)/bin/python
UV = uv

install: $(VENV)/.installed

$(VENV)/.installed: pyproject.toml
	$(UV) venv $(VENV)
	$(UV) pip install --python $(PYTHON) ruff pytest pre-commit pyright ty wxPython "pydantic>=2.13" mkdocs mkdocs-material
	@touch $(VENV)/.installed

lint: install
	$(UV) run --python $(VENV) ruff check

format: install
	$(UV) run --python $(VENV) ruff format

format-check: install
	$(UV) run --python $(VENV) ruff format --check

typecheck: install
	$(UV) run --python $(VENV) ty check
	$(UV) run --python $(VENV) pyright kicad_dfm/utils/pure.py tests/unit/test_pure.py tests/unit/test_point_to_line_distance.py

test: install
	$(UV) run --python $(VENV) pytest -v

check: lint format-check typecheck test

coverage: install
	$(UV) pip install --python $(PYTHON) coverage
	$(UV) run --python $(VENV) coverage run -m pytest
	$(UV) run --python $(VENV) coverage report -m

pure-test:
	$(UV) run --python $(VENV) pytest -m pure -v

docs-build:
	$(UV) run --python $(VENV) mkdocs build --strict

pre-commit: install
	$(UV) run --python $(VENV) pre-commit run --all-files

clean:
	rm -rf $(VENV)
	rm -rf .ruff_cache
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
