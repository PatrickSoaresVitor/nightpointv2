from pathlib import Path
import pytest
from tools.architecture import import_graph, verify, verify_ownership


def test_actual_module_graph_and_data_ownership() -> None:
    graph = import_graph(Path("app"))
    verify(graph)
    verify_ownership(Path("app"))
    assert "app.modules.identity.domain" in graph
    for path in Path("app").rglob("*.py"):
        if "accounts." in path.read_text(encoding="utf-8"):
            assert path.parts[:3] == ("app", "modules", "identity"), path


@pytest.mark.parametrize("source", ["import sqlalchemy", "from fastapi import Request",
    "from .infrastructure import Repository", "from . import infrastructure",
    "import app.modules.identity.infrastructure as concrete",
    "from app.modules.identity import infrastructure"])
def test_domain_rejects_import_forms(tmp_path: Path, source: str) -> None:
    root = tmp_path / "app/modules/identity"
    root.mkdir(parents=True)
    (root / "domain.py").write_text(source)
    (root / "infrastructure.py").write_text("class Repository: pass")
    with pytest.raises(AssertionError):
        verify(import_graph(tmp_path / "app"))


def test_package_reexport_cycle_detected(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / "__init__.py").write_text("from . import first")
    (root / "first.py").write_text("import app.second")
    (root / "second.py").write_text("from app import first")
    with pytest.raises(AssertionError, match="Import cycle"):
        verify(import_graph(root))


def test_valid_inversion_and_transitive_reexport(tmp_path: Path) -> None:
    root = tmp_path / "app/modules/identity"
    root.mkdir(parents=True)
    (root / "domain.py").write_text("from dataclasses import dataclass")
    (root / "ports.py").write_text("from .domain import Entity")
    (root / "application.py").write_text("from .ports import Repository")
    (root / "infrastructure.py").write_text("from .ports import Repository\nimport sqlalchemy")
    verify(import_graph(tmp_path / "app"))
    (root / "ports.py").write_text("from .infrastructure import Repository")
    with pytest.raises(AssertionError):
        verify(import_graph(tmp_path / "app"))


def test_hidden_framework_reexport_rejected(tmp_path: Path) -> None:
    root = tmp_path / "app/modules/identity"
    root.mkdir(parents=True)
    (root / "domain.py").write_text("from . import Entity")
    (root / "__init__.py").write_text("from .infrastructure import Entity")
    (root / "infrastructure.py").write_text("import sqlalchemy")
    with pytest.raises(AssertionError):
        verify(import_graph(tmp_path / "app"))


@pytest.mark.parametrize("source", ["__import__('sqlalchemy')", "import importlib\nimportlib.import_module('sqlalchemy')"])
def test_dynamic_import_requires_review(tmp_path: Path, source: str) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / "domain.py").write_text(source)
    with pytest.raises(AssertionError, match="Dynamic import"):
        import_graph(root)
