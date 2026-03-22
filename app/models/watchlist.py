from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WatchlistItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    display_name: str = Field(index=True)
    entity_type: str = Field(index=True)
    query_hint: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)
