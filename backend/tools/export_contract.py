"""Explicitly regenerate the active reviewed API contract without connecting to DB."""
from pathlib import Path
import sys
import yaml
from pydantic import SecretStr

from app.bootstrap import create_app
from app.platform.config import Settings


class ContractProbe:
    def ready(self) -> bool:
        raise RuntimeError("Contract export does not execute probes")


if __name__ == "__main__":
    target = Path(sys.argv[1])
    configuration = Settings(environment="test", db_password=SecretStr("synthetic-unused-contract-value"))
    schema = create_app(configuration, ContractProbe()).openapi()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(schema, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    print("Contract exported; no DB connection opened")
