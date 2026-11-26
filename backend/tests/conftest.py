import os
import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("NP_RUN_DB_TESTS") != "1":
        skip = pytest.mark.skip(reason="Explicit isolated PostGIS environment required")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)
