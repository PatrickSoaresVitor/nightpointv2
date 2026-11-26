from pathlib import Path
import os
import subprocess
import sys
import pytest
from app.platform.database import compatible_revisions
from app.platform.test_guard import load_receipt, UnsafeTestTarget


def test_missing_or_invalid_receipt_rejected_before_connect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NP_TEST_RECEIPT_FILE", raising=False)
    with pytest.raises(UnsafeTestTarget):
        load_receipt()
    path = tmp_path / "proof.json"
    path.write_text('{"environment":"test"}')
    monkeypatch.setenv("NP_TEST_RECEIPT_FILE", str(path))
    with pytest.raises(UnsafeTestTarget):
        load_receipt()


@pytest.mark.parametrize("revisions,expected", [
    ({"0008_community"}, True), ({"0007_garage"}, False), ({"0006_event_management"}, False), ({"0005_events"}, False), ({"0001_foundation"}, False), ({"0002_privileges"}, False), ({"0003_identity"}, False), ({"0004_profile_text"}, False),
    ({"future_unreviewed"}, False), (set[str](), False),
    ({"0005_events", "other_head"}, False),
])
def test_release_revision_policy(revisions: set[str], expected: bool) -> None:
    assert compatible_revisions(revisions) is expected


def test_local_downgrade_refused_before_database_connection(tmp_path: Path) -> None:
    path = tmp_path / "synthetic-file"
    sentinel = "synthetic-unused-password-length-32"
    path.write_text(sentinel)
    environment = dict(os.environ, NP_ENV="local", NP_DB_HOST="unreachable.invalid", NP_DB_NAME="nightpoint",
                       NP_DB_USER="np_migrator", NP_DB_PASSWORD_FILE=str(path))
    result = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "Only explicit local upgrades" in result.stderr
    assert "could not translate host" not in result.stderr
    assert sentinel not in result.stdout + result.stderr
