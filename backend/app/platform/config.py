from pathlib import Path
from typing import Literal
import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import URL


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    environment: Literal["local", "test"] = "local"
    db_host: str = Field(default="db", pattern=r"^[a-zA-Z0-9_.-]+$")
    db_name: str = Field(default="nightpoint", pattern=r"^nightpoint(?:_test)?$")
    db_user: Literal["np_runtime", "np_migrator"] = "np_runtime"
    db_password: SecretStr
    db_port: int = Field(default=5432, ge=1, le=65535)

    def database_url(self) -> URL:
        return URL.create("postgresql+psycopg", username=self.db_user,
                          password=self.db_password.get_secret_value(),
                          host=self.db_host, port=self.db_port, database=self.db_name)


def load_settings() -> Settings:
    # Read only an explicit secret file. Never load .env or production credentials.
    password_file = os.environ.get("NP_DB_PASSWORD_FILE")
    if not password_file:
        raise ValueError("NP_DB_PASSWORD_FILE is required")
    path = Path(password_file)
    try:
        if path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size > 4096:
            raise ValueError("Invalid secret file")
        password = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        raise ValueError("Credential file could not be safely read") from None
    if len(password) < 24:
        raise ValueError("Local credential file is invalid")
    return Settings.model_validate({
        "environment": os.environ.get("NP_ENV", "local"),
        "db_host": os.environ.get("NP_DB_HOST", "db"),
        "db_name": os.environ.get("NP_DB_NAME", "nightpoint"),
        "db_user": os.environ.get("NP_DB_USER", "np_runtime"),
        "db_port": os.environ.get("NP_DB_PORT", "5432"),
        "db_password": password,
    })
