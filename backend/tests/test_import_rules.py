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


def test_nothing_outside_evals_imports_evals():
    """The eval harness is a consumer of the application, never a dependency of
    it. A node that imported a metric, or a service that read the golden set,
    would put test fixtures in the production path."""
    offenders = []
    for path in APP.rglob("*.py"):
        if path.is_relative_to(APP / "evals"):
            continue
        if any(name.startswith("app.evals") for name in _imports_in(path)):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, f"app/evals must not be imported by the application: {offenders}"


def test_no_officer_tool_accepts_a_tenant_parameter():
    """The agent must not be able to name a tenant.

    `build_officer_tools` binds the authenticated officer's tenant in a closure, so
    no tool has a parameter an LLM could fill with somebody else's id. That holds
    only until someone adds one, and the signature is the whole security model — the
    agent's context carries complaint text written by members of the public, and
    Phase 3 measured that 1 in 6 prompt-injection items still moves a risk band.

    This checks the source rather than the built tools, so it fails on a helper that
    is not yet wired into the returned list.
    """
    import ast
    from pathlib import Path

    tools_dir = Path(__file__).resolve().parents[1] / "app" / "ai" / "tools"
    offenders = []
    for path in tools_dir.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # build_officer_tools takes it deliberately; it is the binding point.
            if node.name.startswith("build_"):
                continue
            args = node.args
            names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            for name in names:
                if "tenant" in name:
                    offenders.append(f"{path.name}:{node.name}({name})")
    assert not offenders, f"tools must not take a tenant: {offenders}"


def test_tools_do_not_import_the_api_layer():
    """Same rule as the rest of app/ai: the AI system must run from a script or a
    pytest with no HTTP layer."""
    from pathlib import Path

    tools_dir = Path(__file__).resolve().parents[1] / "app" / "ai" / "tools"
    offenders = [
        f"{path.name}: {name}"
        for path in tools_dir.rglob("*.py")
        for name in _imports_in(path)
        if name.startswith("app.api")
    ]
    assert not offenders, f"app/ai/tools must not import app/api: {offenders}"
