"""Read-only, server-bound attestation before any disposable test mutation."""
from pathlib import Path
import os

from app.platform.telemetry import measure
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine


class UnsafeTestTarget(RuntimeError):
    pass


class TestReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    environment: str = Field(pattern="^disposable-test$")
    system_identifier: str = Field(pattern=r"^\d+$")
    database_oid: int = Field(gt=0)
    token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def load_receipt() -> TestReceipt:
    try:
        path = os.environ["NP_TEST_RECEIPT_FILE"]
        return TestReceipt.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception:
        raise UnsafeTestTarget("Disposable database receipt is required") from None


def verify_connection(connection: Connection, receipt: TestReceipt) -> None:
    try:
        row = connection.execute(text(
            "SELECT current_database(), session_user, system_identifier, database_oid, token_hash "
            "FROM test_guard.identity_proof()"
        )).one()
        valid = (row[0] == "nightpoint_test" and row[1] in ("np_runtime", "np_migrator")
                 and str(row[2]) == receipt.system_identifier and row[3] == receipt.database_oid
                 and row[4] == receipt.token_hash and receipt.environment == "disposable-test")
        if not valid:
            raise UnsafeTestTarget("Disposable database identity mismatch")
    except Exception:
        raise UnsafeTestTarget("Disposable database identity could not be proven") from None


def protect_engine(engine: Engine) -> None:
    receipt = load_receipt()  # Reject missing proof before even connecting.

    @event.listens_for(engine, "engine_connect")
    def verify_checkout(connection: Connection) -> None:
        try:
            with measure("db.attestation"):
                verify_connection(connection, receipt)
        finally:
            connection.rollback()  # Finish the read-only verification transaction.


def require_disposable(connection: Connection) -> None:
    if os.environ.get("NP_ENV") != "test":
        raise UnsafeTestTarget("Destructive migrations require an attested disposable target")
    verify_connection(connection, load_receipt())
