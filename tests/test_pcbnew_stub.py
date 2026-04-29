"""Verify that the pcbnew stub exports all symbols the codebase actually uses.

This test parses every .py file in kicad_dfm/ (excluding generated UI files),
collects all pcbnew symbol references, and asserts the stub provides them.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_stub

REPO_ROOT = Path(__file__).resolve().parent.parent


def _collect_pcbnew_symbols(source_dir):
    imported = {}
    for pyfile in sorted(source_dir.rglob("*.py")):
        rel = pyfile.relative_to(REPO_ROOT)
        if "ui_" in pyfile.name or pyfile.name == "__init__.py" or "language" in str(rel):
            continue
        try:
            tree = ast.parse(pyfile.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "pcbnew":
                        imported.setdefault(str(rel), []).append("*")
                    elif alias.name.startswith("pcbnew."):
                        imported.setdefault(str(rel), []).append(alias.name.split(".", 1)[1])
            elif isinstance(node, ast.ImportFrom) and node.module == "pcbnew":
                for alias in node.names:
                    imported.setdefault(str(rel), []).append(alias.name)
    return imported


def test_stub_covers_all_imports():
    import tests.pcbnew_stub as stub

    source_dir = REPO_ROOT / "kicad_dfm"
    imports = _collect_pcbnew_symbols(source_dir)
    assert imports, "No pcbnew imports found"

    explicit = set()
    has_wildcard = False
    for symbols in imports.values():
        for s in symbols:
            if s == "*":
                has_wildcard = True
            else:
                explicit.add(s)

    missing = sorted(s for s in explicit if not hasattr(stub, s))
    assert not missing, f"Stub is missing {len(missing)} symbol(s) used by the codebase:\n" + "\n".join(
        f"  - {s}" for s in missing
    )

    if has_wildcard:
        stub_public = [n for n in dir(stub) if not n.startswith("_")]
        assert len(stub_public) > 0, "Stub has no public symbols (wildcard import would fail)"


def test_stub_covers_function_calls():
    import tests.pcbnew_stub as stub

    source_dir = REPO_ROOT / "kicad_dfm"
    calls = set()
    for pyfile in sorted(source_dir.rglob("*.py")):
        rel = pyfile.relative_to(REPO_ROOT)
        if "ui_" in pyfile.name or "language" in str(rel):
            continue
        try:
            tree = ast.parse(pyfile.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pcbnew"
            ):
                calls.add(node.func.attr)

    missing = sorted(s for s in calls if not callable(getattr(stub, s, None)))
    assert not missing, "Stub is missing callable(s) used by the codebase:\n" + "\n".join(
        f"  - pcbnew.{s}()" for s in missing
    )
