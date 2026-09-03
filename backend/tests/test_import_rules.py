"""Architectural boundary tests.

The AI package must be runnable from a script or a test with no web server, so
it may never import the API layer.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_ai_never_imports_api():
    offenders = []
    for path in (APP / "ai").rglob("*.py"):
        if any(name.startswith("app.api") for name in _imports_in(path)):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, f"app/ai must not import app/api: {offenders}"


def test_api_never_imports_the_graph_directly():
    """The API talks to the graph only through app.ai.graph.runner (Phase 1)."""
    offenders = []
    for path in (APP / "api").rglob("*.py"):
        for name in _imports_in(path):
            if name.startswith("app.ai.graph") and not name.startswith("app.ai.graph.runner"):
                offenders.append(f"{path.relative_to(APP)} -> {name}")
    assert not offenders, f"api must go through the runner: {offenders}"
