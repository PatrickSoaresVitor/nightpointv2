from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    title: str
    status: int
    detail: str
    correlation_id: str


class PageQuery(BaseModel):
    """Convention available to future operations; no business endpoint exists yet."""
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
