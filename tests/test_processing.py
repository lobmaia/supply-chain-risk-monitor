from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, select

from app.core.config import Settings, get_settings
from app.db.session import engine, init_db
from app.main import app
from app.models.article import Article, ArticleEntityLink, Entity
from app.models.watchlist import WatchlistItem
from app.services.processing import get_processing_overview, run_processing_cycle


@pytest.fixture(autouse=True)
def isolate_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("INGESTION_ENABLED", "false")
    get_settings.cache_clear()
    SQLModel.metadata.drop_all(engine)
    init_db()
    yield
    SQLModel.metadata.drop_all(engine)
    init_db()
    get_settings.cache_clear()


def test_run_processing_cycle_filters_and_tags_articles() -> None:
    with Session(engine) as session:
        session.add(
            WatchlistItem(display_name="Intel", entity_type="company", query_hint="intel corporation")
        )
        session.add(
            Article(
                source_name="Test Feed",
                source_feed_url="https://feeds.example.com",
                source_article_id="1",
                title="Intel says Panama Canal congestion is delaying chip shipments",
                url="https://example.com/relevant",
                published_at=datetime.now(timezone.utc),
                summary="The supply chain disruption is raising semiconductor lead times.",
                normalized_content=(
                    "Intel says Panama Canal congestion is delaying chip shipments "
                    "and disrupting semiconductor supply chains."
                ),
                content_hash="hash-1",
            )
        )
        session.add(
            Article(
                source_name="Test Feed",
                source_feed_url="https://feeds.example.com",
                source_article_id="2",
                title="Celebrity chef opens new restaurant",
                url="https://example.com/not-relevant",
                published_at=datetime.now(timezone.utc),
                summary="Entertainment coverage from Toronto.",
                normalized_content="Celebrity chef opens a new restaurant after an entertainment gala.",
                content_hash="hash-2",
            )
        )
        session.commit()

    stats = run_processing_cycle(Settings(ingestion_enabled=False, processing_enabled=True))

    assert stats.status == "success"
    assert stats.processed_count == 2
    assert stats.relevant_count == 1
    assert stats.not_relevant_count == 1
    assert stats.entity_link_count >= 3
    assert stats.watchlist_match_count >= 1

    with Session(engine) as session:
        articles = session.exec(select(Article).order_by(Article.url)).all()
        entities = session.exec(select(Entity)).all()
        links = session.exec(select(ArticleEntityLink)).all()

    assert articles[0].is_relevant is False
    assert articles[1].is_relevant is True
    assert articles[1].matched_watchlist_count == 1
    assert {entity.name for entity in entities} >= {"Intel", "Panama Canal", "Semiconductors"}
    assert len(links) >= 3


def test_processing_status_and_run_endpoints() -> None:
    with Session(engine) as session:
        session.add(
            Article(
                source_name="Test Feed",
                source_feed_url="https://feeds.example.com",
                source_article_id="3",
                title="Factory fire creates supply chain delays",
                url="https://example.com/factory-fire",
                published_at=datetime.now(timezone.utc),
                normalized_content="Factory fire creates supply chain delays for automotive parts.",
                content_hash="hash-3",
            )
        )
        session.commit()

    with TestClient(app) as client:
        run_response = client.post("/api/v1/processing/run")
        status_response = client.get("/api/v1/processing/status")

    assert run_response.status_code == 200
    assert run_response.json()["processed_count"] == 1
    assert status_response.status_code == 200
    assert status_response.json()["processed_articles"] == 1
    assert status_response.json()["relevant_articles"] == 1


def test_get_processing_overview_counts_pending_articles() -> None:
    with Session(engine) as session:
        session.add(
            Article(
                source_name="Test Feed",
                source_feed_url="https://feeds.example.com",
                source_article_id="4",
                title="Unprocessed article",
                url="https://example.com/pending",
                published_at=datetime.now(timezone.utc),
                normalized_content="General market update.",
                content_hash="hash-4",
            )
        )
        session.commit()

    overview = get_processing_overview()

    assert overview["total_articles"] == 1
    assert overview["processed_articles"] == 0
    assert overview["pending_articles"] == 1
