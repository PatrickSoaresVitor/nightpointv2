"""Generate only local synthetic credentials; never overwrite or print them."""
from pathlib import Path
import secrets
from private_files import create_directory, verify_private, write_private


def main() -> None:
    directory = Path(__file__).resolve().parent / "local"
    if directory.exists():
        verify_private(directory)
    else:
        create_directory(directory)
    for name in ("admin_password", "runtime_password", "migrator_password"):
        path = directory / name
        if path.exists():
            verify_private(path)
        else:
            write_private(path, secrets.token_urlsafe(36))
    print("Local credential files ready; values omitted. Existing files preserved.")


if __name__ == "__main__":
    main()
