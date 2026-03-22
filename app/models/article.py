from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source_name: str
    source_article_id: Optional[str] = Field(default=None, index=True)
    title: str
    url: str = Field(unique=True, index=True)
    published_at: datetime
    source_feed_url: Optional[str] = None
    author: Optional[str] = None
    summary: Optional[str] = None
    raw_content: Optional[str] = None
    raw_payload: Optional[str] = None
    normalized_content: Optional[str] = None
    content_hash: str = Field(index=True)
    processing_status: str = Field(default="pending", index=True)
    is_relevant: bool = Field(default=False, index=True)
    relevance_score: float = Field(default=0.0)
    relevance_reason: Optional[str] = None
    matched_watchlist_count: int = Field(default=0)
    processed_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)


class Entity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    entity_type: str = Field(index=True)
    external_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class ArticleEntityLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="article.id", index=True)
    entity_id: int = Field(foreign_key="entity.id", index=True)
    relation_type: str = Field(default="mentioned")
    confidence: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=utc_now)
