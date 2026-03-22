from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArticleRiskScore(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="article.id", unique=True, index=True)
    relevance_score: float = Field(default=0.0)
    risk_score: float = Field(default=0.0)
    scoring_notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class EntityRiskSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="entity.id", index=True)
    snapshot_date: date = Field(index=True)
    aggregated_risk_score: float = Field(default=0.0)
    article_volume: int = Field(default=0)
    spike_flag: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)
