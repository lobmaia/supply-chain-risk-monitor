from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, select

from app.core.config import Settings, get_settings
from app.db.session import engine, init_db
from app.main import app
from app.models.article import Article, Entity
from app.models.risk import ArticleRiskScore, EntityRiskSnapshot
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


def _make_article(
    source_article_id: str,
    title: str,
    url: str,
    published_at: datetime,
    normalized_content: str,
) -> Article:
    return Article(
        source_name="Test Feed",
        source_feed_url="https://feeds.example.com",
        source_article_id=source_article_id,
        title=title,
        url=url,
        published_at=published_at,
        normalized_content=normalized_content,
        content_hash=f"hash-{source_article_id}",
    )


def test_processing_cycle_generates_risk_scores_and_spike_snapshots() -> None:
    start = datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(
            WatchlistItem(
                display_name="Intel",
                entity_type="company",
                query_hint="intel corporation",
            )
        )
        session.add_all(
            [
                _make_article(
                    "1",
                    "Intel logistics update supports chip shipments",
                    "https://example.com/intel-1",
                    start,
                    "Intel logistics update supports supply chain chip shipments.",
                ),
                _make_article(
                    "2",
                    "Intel supply chain operations remain steady",
                    "https://example.com/intel-2",
                    start + timedelta(days=1),
                    "Intel supply chain logistics update for semiconductor shipments.",
                ),
                _make_article(
                    "3",
                    "Intel shipment planning continues",
                    "https://example.com/intel-3",
                    start + timedelta(days=2),
                    "Intel manages supply chain shipment planning for chips.",
                ),
                _make_article(
                    "4",
                    "Intel warns factory fire disrupts chip shipments",
                    "https://example.com/intel-4",
                    start + timedelta(days=3),
                    (
                        "Intel warns a factory fire is causing supply chain disruption, "
                        "shipment delays, and semiconductor shortage risk."
                    ),
                ),
            ]
        )
        session.commit()

    stats = run_processing_cycle(Settings(ingestion_enabled=False, processing_enabled=True))

    assert stats.status == "success"
    assert stats.processed_count == 4

    with Session(engine) as session:
        article_scores = session.exec(select(ArticleRiskScore)).all()
        intel = session.exec(select(Entity).where(Entity.name == "Intel")).one()
        intel_snapshots = session.exec(
            select(EntityRiskSnapshot)
            .where(EntityRiskSnapshot.entity_id == intel.id)
            .order_by(EntityRiskSnapshot.snapshot_date)
        ).all()

    assert len(article_scores) == 4
    assert len(intel_snapshots) == 4
    assert intel_snapshots[-1].spike_flag is True
    assert intel_snapshots[-1].aggregated_risk_score > intel_snapshots[0].aggregated_risk_score


def test_risk_endpoints_return_current_history_and_flagged_events() -> None:
    start = datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(
            WatchlistItem(
                display_name="Intel",
                entity_type="company",
                query_hint="intel corporation",
            )
        )
        session.add_all(
            [
                _make_article(
                    "10",
                    "Intel supply chain update",
                    "https://example.com/risk-1",
                    start,
                    "Intel supply chain update for semiconductor shipments.",
                ),
                _make_article(
                    "11",
                    "Intel warns port strike disrupts shipments",
                    "https://example.com/risk-2",
                    start + timedelta(days=1),
                    "Intel warns a port strike disrupts supply chain shipments and causes delays.",
                ),
            ]
        )
        session.commit()

    run_processing_cycle(Settings(ingestion_enabled=False, processing_enabled=True))

    with Session(engine) as session:
        intel = session.exec(select(Entity).where(Entity.name == "Intel")).one()

    with TestClient(app) as client:
        status_response = client.get("/api/v1/risk/status")
        current_response = client.get("/api/v1/risk/entities/current")
        history_response = client.get(f"/api/v1/risk/entities/{intel.id}/history")
        flagged_response = client.get("/api/v1/risk/events/flagged")
        rerun_response = client.post("/api/v1/risk/run")

    assert status_response.status_code == 200
    assert status_response.json()["article_risk_scores"] == 2
    assert current_response.status_code == 200
    assert current_response.json()[0]["entity_name"] == "Intel"
    assert history_response.status_code == 200
    assert len(history_response.json()) == 2
    assert flagged_response.status_code == 200
    assert flagged_response.json()[0]["title"] == "Intel warns port strike disrupts shipments"
    assert "Intel" in flagged_response.json()[0]["spike_entities"]
    assert rerun_response.status_code == 200
    assert rerun_response.json()["scored_article_count"] == 2
