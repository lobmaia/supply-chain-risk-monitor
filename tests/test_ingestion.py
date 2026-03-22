from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import SQLModel, Session, select

from app.core.config import Settings, get_settings
from app.db.session import engine, init_db
from app.main import app
from app.models.article import Article, ArticleEntityLink, Entity
from app.models.ingestion import IngestionRun
from app.models.watchlist import WatchlistItem
from app.services import ingestion as ingestion_service

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Supply Chain Feed</title>
    <item>
      <title>Intel warns Panama Canal delays are disrupting chip shipments</title>
      <link>https://example.com/articles/port-strike</link>
      <guid>port-strike-1</guid>
      <pubDate>Fri, 21 Mar 2026 10:00:00 GMT</pubDate>
      <author>Reporter One</author>
      <description>Dockworkers and canal congestion threaten semiconductor supply chains.</description>
      <content:encoded>Full article body about Intel, the Panama Canal, and semiconductor shipment delays.</content:encoded>
    </item>
    <item>
      <title>Intel warns Panama Canal delays are disrupting chip shipments</title>
      <link>https://mirror.example.com/port-strike</link>
      <guid>port-strike-duplicate</guid>
      <pubDate>Fri, 21 Mar 2026 10:00:00 GMT</pubDate>
      <description>Duplicate syndication copy.</description>
    </item>
  </channel>
</rss>
"""


@pytest.fixture(autouse=True)
def isolate_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("INGESTION_ENABLED", "false")
    get_settings.cache_clear()
    SQLModel.metadata.drop_all(engine)
    init_db()
    with Session(engine) as session:
        session.exec(delete(ArticleEntityLink))
        session.exec(delete(Entity))
        session.exec(delete(WatchlistItem))
        session.exec(delete(IngestionRun))
        session.exec(delete(Article))
        session.commit()
    yield
    with Session(engine) as session:
        session.exec(delete(ArticleEntityLink))
        session.exec(delete(Entity))
        session.exec(delete(WatchlistItem))
        session.exec(delete(IngestionRun))
        session.exec(delete(Article))
        session.commit()
    get_settings.cache_clear()


def make_client_factory(xml_content: str, status_code: int = 200):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code=status_code, text=xml_content, request=request)
    )

    def factory() -> httpx.Client:
        return httpx.Client(transport=transport)

    return factory


def test_parse_rss_feed_normalizes_expected_fields() -> None:
    articles = ingestion_service.parse_rss_feed(
        SAMPLE_RSS,
        "https://feeds.example.com/supply-chain.xml",
    )

    assert len(articles) == 2
    assert articles[0].source_name == "Supply Chain Feed"
    assert articles[0].title == "Intel warns Panama Canal delays are disrupting chip shipments"
    assert articles[0].author == "Reporter One"
    assert articles[0].normalized_content is not None
    assert articles[0].content_hash


def test_run_ingestion_cycle_deduplicates_by_content_hash() -> None:
    settings = Settings(
        ingestion_enabled=False,
        rss_feed_urls="https://feeds.example.com/supply-chain.xml",
        ingestion_max_retries=1,
    )

    run = ingestion_service.run_ingestion_cycle(
        settings=settings,
        client_factory=make_client_factory(SAMPLE_RSS),
    )

    assert run.status == "success"
    assert run.fetched_count == 2
    assert run.inserted_count == 2
    assert run.updated_count == 0
    assert run.duplicate_count == 0

    with Session(engine) as session:
        articles = session.exec(select(Article)).all()
        entity_links = session.exec(select(ArticleEntityLink)).all()
        entities = session.exec(select(Entity)).all()

    assert len(articles) == 2
    assert articles[0].url == "https://example.com/articles/port-strike"
    assert all(article.processing_status == "processed" for article in articles)
    assert all(article.is_relevant is True for article in articles)
    assert len(entity_links) >= 3
    assert {entity.name for entity in entities} >= {"Panama Canal", "Semiconductors"}


def test_ingestion_endpoint_returns_run_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run = IngestionRun(
        id=7,
        source_type="rss",
        source_name="configured_rss_feeds",
        status="success",
        fetched_count=3,
        inserted_count=2,
        updated_count=1,
        duplicate_count=0,
        error_count=0,
    )
    monkeypatch.setattr("app.api.routes.run_ingestion_cycle", lambda: fake_run)

    with TestClient(app) as client:
        response = client.post("/api/v1/ingestion/run")

    assert response.status_code == 200
    assert response.json()["run_id"] == 7
    assert response.json()["inserted_count"] == 2
