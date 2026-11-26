import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))
# Infra is present on the host; production image deliberately excludes it.
try:
    from private_files import create_directory, verify_private, write_private
except ImportError:
    pytest.skip("Host-only filesystem/ACL checks; no infra source in application image", allow_module_level=True)


def test_private_creation_existing_unsafe_and_no_overwrite(tmp_path: Path) -> None:
    directory = tmp_path / "restricted"
    create_directory(directory)
    path = directory / "synthetic"
    write_private(path, "synthetic-test-only")
    verify_private(path)
    with pytest.raises(FileExistsError):
        write_private(path, "must-not-replace")
    assert path.read_text() == "synthetic-test-only"
    if os.name == "nt":
        subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:R"], check=True, capture_output=True)
    else:
        path.chmod(0o644)
    with pytest.raises(ValueError):
        verify_private(path)
