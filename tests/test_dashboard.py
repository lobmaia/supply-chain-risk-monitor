from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, select

from app.core.config import get_settings
from app.db.session import engine, init_db
from app.main import app
from app.models.article import Article
from app.models.watchlist import WatchlistItem
from app.services.processing import run_processing_cycle


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


def _make_article(source_article_id: str, title: str, url: str, published_at: datetime) -> Article:
    return Article(
        source_name="Test Feed",
        source_feed_url="https://feeds.example.com",
        source_article_id=source_article_id,
        title=title,
        url=url,
        published_at=published_at,
        summary="Supply chain disruption coverage for a monitored company.",
        normalized_content=title,
        content_hash=f"hash-{source_article_id}",
    )


def test_dashboard_overview_and_flagged_event_detail() -> None:
    start = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(WatchlistItem(display_name="Intel", entity_type="company", query_hint="intel corporation"))
        session.add_all(
            [
                _make_article(
                    "d1",
                    "Intel logistics update supports semiconductor shipments",
                    "https://example.com/dashboard-1",
                    start,
                ),
                _make_article(
                    "d2",
                    "Intel warns port strike disrupts semiconductor shipments",
                    "https://example.com/dashboard-2",
                    start + timedelta(days=1),
                ),
            ]
        )
        session.commit()

    run_processing_cycle()

    with TestClient(app) as client:
        dashboard_response = client.get("/api/v1/dashboard/overview")
        flagged_response = client.get("/api/v1/risk/events/flagged")
        flagged_article_id = flagged_response.json()[0]["article_id"]
        detail_response = client.get(f"/api/v1/risk/events/{flagged_article_id}")

    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["top_entities"][0]["entity_name"] == "Intel"
    assert flagged_response.status_code == 200
    assert flagged_response.json()[0]["title"] == "Intel warns port strike disrupts semiconductor shipments"
    assert detail_response.status_code == 200
    assert detail_response.json()["title"] == "Intel warns port strike disrupts semiconductor shipments"
    assert detail_response.json()["entities"][0]["entity_name"] == "Intel"


def test_watchlist_crud_endpoints_trigger_reprocessing() -> None:
    article = _make_article(
        "w1",
        "Acme port strike disrupts automotive supply chain",
        "https://example.com/watchlist-article",
        datetime(2026, 3, 21, 11, 0, tzinfo=timezone.utc),
    )
    with Session(engine) as session:
        session.add(article)
        session.commit()
        session.refresh(article)
        article_id = article.id

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/watchlist",
            json={
                "display_name": "Acme",
                "entity_type": "company",
                "query_hint": "acme",
                "is_active": True,
            },
        )
        list_response = client.get("/api/v1/watchlist")
        item_id = create_response.json()["id"]
        update_response = client.put(
            f"/api/v1/watchlist/{item_id}",
            json={
                "display_name": "Acme Corp",
                "entity_type": "company",
                "query_hint": "acme",
                "is_active": True,
            },
        )
        delete_response = client.delete(f"/api/v1/watchlist/{item_id}")

    assert create_response.status_code == 200
    assert create_response.json()["reprocessing_triggered"] is True
    assert any(item["display_name"] == "Acme" for item in list_response.json())
    assert update_response.status_code == 200
    assert update_response.json()["display_name"] == "Acme Corp"
    assert delete_response.status_code == 200

    with Session(engine) as session:
        stored_article = session.get(Article, article_id)
        watchlist_items = session.exec(select(WatchlistItem)).all()

    assert stored_article is not None
    assert stored_article.processing_status == "processed"
    assert watchlist_items == []
