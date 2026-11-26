"""Resolve static relative, package and reexport imports without running application."""
import ast
from importlib.util import resolve_name
from pathlib import Path
import sys
import re


def import_graph(root: Path) -> dict[str, set[str]]:
    files = {".".join(path.relative_to(root.parent).with_suffix("").parts).removesuffix(".__init__"): path
             for path in root.rglob("*.py")}
    graph: dict[str, set[str]] = {}
    for module, path in files.items():
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        edges: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                edges.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module or ""
                edges.add(target)
                edges.update(target + "." + alias.name for alias in node.names if target + "." + alias.name in files)
            elif isinstance(node, ast.Call):
                if ((isinstance(node.func, ast.Name) and node.func.id == "__import__") or
                    (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")):
                    raise AssertionError(f"Dynamic import requires explicit architecture review: {module}")
        graph[module] = edges
    return graph


def verify(graph: dict[str, set[str]]) -> None:
    visited: set[str] = set()

    def visit(module: str, stack: set[str]) -> None:
        assert module not in stack, f"Import cycle: {module}"
        if module in visited:
            return
        for dependency in graph.get(module, set()):
            if dependency in graph:
                visit(dependency, stack | {module})
        visited.add(module)

    for module in graph:
        visit(module, set())
    for module, dependencies in graph.items():
        if module.startswith("app.modules."):
            parts = module.split(".")
            own = ".".join(parts[:3])
            layer = parts[3] if len(parts) > 3 else ""
            for target in dependencies:
                public = target.startswith("app.modules.") and len(target.split(".")) == 4 and target.endswith(".api")
                if layer == "api":
                    assert target.split(".")[0] in sys.stdlib_module_names or public, (module, target)
                if layer in {"domain", "ports", "application"}:
                    allowed = {own, own + ".domain", own + ".api"}
                    if layer == "application":
                        allowed.add(own + ".ports")
                    assert public or target in allowed or target.split(".")[0] in sys.stdlib_module_names, (module, target)
                    if target in graph:
                        # Follow package reexports as well as direct imports.
                        pending = list(graph[target])
                        seen: set[str] = set()
                        while pending:
                            indirect = pending.pop()
                            if indirect in seen:
                                continue
                            seen.add(indirect)
                            indirect_public = len(indirect.split(".")) == 4 and indirect.startswith("app.modules.") and indirect.endswith(".api")
                            assert indirect_public or indirect in allowed or indirect.split(".")[0] in sys.stdlib_module_names, (module, indirect)
                            pending.extend(graph.get(indirect, set()))
                if target.startswith("app.modules.") and not target.startswith(own + "."):
                    assert public, f"Non-public cross-module dependency: {module} -> {target}"
                if layer == "presentation":
                    assert target not in {own + ".infrastructure", own + ".firebase"}, (module, target)
        if module.startswith("app.application."):
            for target in dependencies:
                assert target.split(".")[0] in sys.stdlib_module_names or target.startswith("app.application."), (module, target)


def verify_ownership(root: Path, owners: dict[str, set[str]] | None = None) -> None:
    ownership = owners if owners is not None else {"identity": {"accounts"}, "events": {"events"}, "garage": {"garage"}, "community": {"community"}, "discovery": set[str]()}
    for path in (root / "modules").rglob("*.py"):
        module = path.relative_to(root / "modules").parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql = node.value.replace('"', '')
                # SQL-bearing references include reads: consumers use public contracts, not private data.
                for schema in re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([a-zA-Z_][a-zA-Z_0-9]*)\s*\.", sql, re.I):
                    assert schema.lower() in ownership.get(module, set()), (module, schema, path)
