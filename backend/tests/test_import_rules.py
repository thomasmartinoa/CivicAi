"""Architectural boundary tests.

The AI package must be runnable from a script or a test with no web server, so
it may never import the API layer.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _imports_in(path: Path) -> list[str]:
    """Absolute dotted targets imported by a file.

    `ImportFrom` records `module.name` per imported name rather than the bare
    module, so `from app.ai.graph import runner` reads as `app.ai.graph.runner`
    and is distinguishable from `from app.ai.graph.state import X`. Relative
    imports are resolved against the file's own package so they cannot dodge
    the prefix checks below.
    """
    tree = ast.parse(path.read_text())
    pkg_parts = path.relative_to(APP.parent).parent.parts  # e.g. ("app", "ai")
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(pkg_parts[: len(pkg_parts) - node.level + 1])
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            if module:
                names.extend(f"{module}.{alias.name}" for alias in node.names)
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


def test_import_rules_detect_violations(tmp_path):
    """The boundary tests pass vacuously until app/ai exists — prove the
    detector itself works, on synthetic files rather than on real ones."""
    pkg = tmp_path / "app" / "ai"
    pkg.mkdir(parents=True)

    absolute = pkg / "absolute.py"
    absolute.write_text("from app.api.system import router\n")
    relative = pkg / "relative.py"
    relative.write_text("from ..api.system import router\n")
    allowed = pkg / "allowed.py"
    allowed.write_text("from app.ai.graph import runner\n")
    blocked = pkg / "blocked.py"
    blocked.write_text("from app.ai.graph.state import ComplaintState\n")

    global APP
    original, APP = APP, tmp_path / "app"
    try:
        assert any(n.startswith("app.api") for n in _imports_in(absolute))
        assert any(n.startswith("app.api") for n in _imports_in(relative))

        allowed_names = _imports_in(allowed)
        assert any(n.startswith("app.ai.graph.runner") for n in allowed_names)
        assert all(
            n.startswith("app.ai.graph.runner")
            for n in allowed_names
            if n.startswith("app.ai.graph")
        )

        blocked_names = _imports_in(blocked)
        assert any(
            n.startswith("app.ai.graph") and not n.startswith("app.ai.graph.runner")
            for n in blocked_names
        )
    finally:
        APP = original
