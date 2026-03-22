from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source_type: str = Field(index=True)
    source_name: str = Field(index=True)
    status: str = Field(index=True)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = None
    fetched_count: int = Field(default=0)
    inserted_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    duplicate_count: int = Field(default=0)
    error_count: int = Field(default=0)
    last_successful_published_at: Optional[datetime] = None
    error_message: Optional[str] = None
